import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from arq.connections import ArqRedis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.config import get_settings
from atendia.contracts.event import EventType
from atendia.contracts.message import Message
from atendia.contracts.tone import Tone
from atendia.contracts.vision_result import VisionResult
from atendia.db.models import TurnTrace
from atendia.runner.composer_protocol import (
    ComposerInput,
    ComposerOutput,
    ComposerProvider,
)
from atendia.runner.nlu_protocol import NLUProvider
from atendia.runner.outbound_dispatcher import COMPOSED_ACTIONS, enqueue_messages
from atendia.state_machine.event_emitter import EventEmitter
from atendia.state_machine.orchestrator import process_turn
from atendia.state_machine.pipeline_loader import load_active_pipeline
from atendia.tools.base import ToolNoDataResult
from atendia.tools.embeddings import generate_embedding
from atendia.tools.lookup_faq import lookup_faq
from atendia.tools.quote import quote
from atendia.tools.search_catalog import search_catalog
from atendia.tools.vision import classify_image


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (datetime, Decimal, UUID)):
        return str(obj)
    return obj


def _maybe_uuid(s: str) -> UUID | None:
    try:
        return UUID(s)
    except (ValueError, AttributeError):
        return None


# Phase 3c.2 — pending_confirmation handling
#
# The runner only listens for SHORT, UNAMBIGUOUS sí/no replies; long
# free-form messages fall through to NLU + flow_router, which is the
# right behaviour ("¿es nómina tarjeta?" -> "Sí pero también..." should
# go through normal extraction).
#
# Mexican Spanish slang adds "simon" (yes) and "nel" (no); we keep the
# whitelist short on purpose — multi-word phrases need substring rules
# that we'd rather get wrong loudly than silently.
_AFFIRMATIVE: frozenset[str] = frozenset({
    "si", "sí", "claro", "ok", "okay", "yes", "ya", "sip", "simon",
})
_NEGATIVE: frozenset[str] = frozenset({"no", "nop", "nada", "nel"})


def _confirmation_side_effects(
    pending_key: str, answer: str,
) -> dict[str, str]:
    """Translate a yes/no answer to a pending_confirmation key into
    extracted-field updates. Returns a dict of {field_name: value} to
    merge into extracted_data.

    The disambiguations come from PLAN MODE prompt — when the LLM asks
    a binary question to narrow tipo_credito, it sets one of these keys.
    """
    if pending_key == "is_nomina_tarjeta" and answer == "yes":
        return {"tipo_credito": "Nómina Tarjeta", "plan_credito": "10%"}
    if pending_key == "is_nomina_recibos" and answer == "yes":
        return {"tipo_credito": "Nómina Recibos", "plan_credito": "15%"}
    if pending_key == "is_negocio_sat":
        if answer == "yes":
            return {"tipo_credito": "Negocio SAT", "plan_credito": "15%"}
        return {"tipo_credito": "Sin Comprobantes", "plan_credito": "20%"}
    return {}


def _maybe_apply_confirmation(
    *,
    inbound_text: str,
    pending_confirmation: str | None,
    extracted_jsonb: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    """Apply a sí/no answer to the pending slot, returning the new
    extracted_jsonb or None when no resolution is possible.

    None signals the caller to leave state untouched (no DB write).
    """
    if not pending_confirmation:
        return None
    normalized = inbound_text.strip().lower()
    if normalized in _AFFIRMATIVE:
        answer = "yes"
    elif normalized in _NEGATIVE:
        answer = "no"
    else:
        return None
    side_effects = _confirmation_side_effects(pending_confirmation, answer)
    if not side_effects:
        return None
    # ExtractedField.source_turn requires int >= 0; we use 0 to mean
    # "synthesized by the binary confirmation handler, not by NLU". The
    # confidence=1.0 + the constant 0 turn make these rows distinguishable
    # in turn_traces.state_after for analytics.
    new_extracted = dict(extracted_jsonb)
    for k, v in side_effects.items():
        new_extracted[k] = {"value": v, "confidence": 1.0, "source_turn": 0}
    return new_extracted


class ConversationRunner:
    def __init__(
        self,
        session: AsyncSession,
        nlu_provider: NLUProvider,
        composer_provider: ComposerProvider,
    ) -> None:
        self._session = session
        self._nlu = nlu_provider
        self._composer = composer_provider
        self._emitter = EventEmitter(session)

    async def run_turn(
        self,
        *,
        conversation_id: UUID,
        tenant_id: UUID,
        inbound: Message,
        turn_number: int,
        arq_pool: ArqRedis | None = None,
        to_phone_e164: str | None = None,
    ) -> TurnTrace:
        started = time.perf_counter()

        from atendia.runner.followup_scheduler import (
            cancel_pending_followups,
            schedule_followups_after_outbound,
        )

        # Load current state row FIRST so we can short-circuit on bot_paused
        # without invoking the cancel-followups side-effect (Block D code
        # review H1 — cancel before short-circuit was wiping the silence
        # clock for paused conversations even though the runner wasn't
        # producing a replacement schedule).
        row = (await self._session.execute(
            text("""SELECT current_stage, extracted_data, last_intent, stage_entered_at,
                           followups_sent_count, total_cost_usd, pending_confirmation,
                           bot_paused
                    FROM conversation_state cs JOIN conversations c ON c.id = cs.conversation_id
                    WHERE cs.conversation_id = :cid"""),
            {"cid": conversation_id},
        )).fetchone()
        if row is None:
            raise RuntimeError(
                f"conversation_state not found for conversation {conversation_id}"
            )
        (current_stage, extracted_jsonb, last_intent,
         stage_entered_at, followups_sent_count,
         total_cost_usd, pending_confirmation, bot_paused) = row

        # Phase 4 T24 — operator-driven conversation. Persist a minimal
        # turn_trace so the audit log shows the inbound landed but the bot
        # stayed silent, then return without invoking NLU/composer/tools.
        # The operator decides when to flip bot_paused back via
        # POST /api/v1/conversations/:cid/resume-bot.
        #
        # Note we DON'T cancel pending follow-ups in this branch — the
        # operator owns re-engagement while paused. When the bot resumes,
        # the next inbound runs the full pipeline (cancel + schedule).
        if bot_paused:
            paused_trace = TurnTrace(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                turn_number=turn_number,
                inbound_text=inbound.text,
                bot_paused=True,
                state_before={"current_stage": current_stage},
                state_after={"current_stage": current_stage},
                total_latency_ms=int((time.perf_counter() - started) * 1000),
            )
            self._session.add(paused_trace)
            await self._session.flush()
            return paused_trace

        # Bot is driving — restore the Phase 3d invariant: cancel any
        # pending follow-ups for this conversation now that the customer
        # has engaged. Lives in the caller's transaction so a crash
        # mid-turn does NOT leave a stale silence reminder primed.
        await cancel_pending_followups(
            session=self._session, conversation_id=conversation_id,
        )

        pipeline = await load_active_pipeline(self._session, tenant_id)

        state_before = {
            "current_stage": current_stage,
            "extracted_data": extracted_jsonb or {},
            "last_intent": last_intent,
            "stage_entered_at": stage_entered_at.isoformat() if stage_entered_at else None,
            "followups_sent_count": followups_sent_count,
            "total_cost_usd": str(total_cost_usd) if total_cost_usd is not None else "0",
            "pending_confirmation": pending_confirmation,
        }

        # Build a ConversationState-like object for the orchestrator (it consumes
        # an object with `current_stage` and `extracted_data` containing values).
        from atendia.contracts.conversation_state import ConversationState, ExtractedField
        state_obj_extracted = {
            k: ExtractedField(**v) for k, v in (extracted_jsonb or {}).items()
        }
        state_obj = ConversationState(
            conversation_id=str(conversation_id),
            tenant_id=str(tenant_id),
            current_stage=current_stage,
            extracted_data=state_obj_extracted,
            last_intent=last_intent,
            stage_entered_at=stage_entered_at or datetime.now(UTC),
            followups_sent_count=followups_sent_count or 0,
            total_cost_usd=total_cost_usd or Decimal("0"),
            pending_confirmation=pending_confirmation,
        )

        # Fetch the last N (inbound + outbound) messages for NLU context.
        history_turns = pipeline.nlu.history_turns
        history_rows = (await self._session.execute(
            text("""SELECT direction, text FROM messages
                    WHERE conversation_id = :cid
                    ORDER BY sent_at DESC
                    LIMIT :n"""),
            {"cid": conversation_id, "n": history_turns * 2},
        )).fetchall()
        # Reverse so oldest is first; rows come back newest-first.
        history: list[tuple[str, str]] = [(r[0], r[1]) for r in reversed(history_rows)]

        current_stage_def = next(s for s in pipeline.stages if s.id == current_stage)

        # Phase 3c.2 — resolve any pending sí/no the composer asked last turn.
        # If the inbound matches an affirmative or negative form AND state has
        # a pending_confirmation slot set, apply the side-effect to extracted
        # fields and clear the slot before routing.
        confirmation_resolved = _maybe_apply_confirmation(
            inbound_text=inbound.text,
            pending_confirmation=pending_confirmation,
            extracted_jsonb=extracted_jsonb or {},
        )
        if confirmation_resolved is not None:
            extracted_jsonb = confirmation_resolved
            pending_confirmation = None
            await self._session.execute(
                text(
                    "UPDATE conversation_state "
                    "SET pending_confirmation = NULL, "
                    "    extracted_data = CAST(:ed AS JSONB) "
                    "WHERE conversation_id = :cid"
                ),
                {
                    "ed": __import__("json").dumps(extracted_jsonb),
                    "cid": conversation_id,
                },
            )
            # Refresh state_obj so process_turn sees the just-applied fields.
            from atendia.contracts.conversation_state import ExtractedField
            state_obj.extracted_data = {
                k: ExtractedField(**v) for k, v in extracted_jsonb.items()
            }
            state_obj.pending_confirmation = None

        # Phase 3c.2 — run NLU and (optionally) Vision in parallel. Vision
        # only fires when the inbound carries an image attachment with a
        # resolved URL AND OpenAI is configured. Errors in either branch
        # are caught individually so a flaky Vision call cannot wipe out
        # the NLU result that drives state.
        settings = get_settings()
        nlu_task = self._nlu.classify(
            text=inbound.text,
            current_stage=current_stage,
            required_fields=current_stage_def.required_fields,
            optional_fields=current_stage_def.optional_fields,
            history=history,
        )

        vision_result: VisionResult | None = None
        vision_cost_usd: Decimal = Decimal("0")
        vision_latency_ms: int | None = None
        first_image = next(
            (a for a in inbound.attachments if a.mime_type.startswith("image/")),
            None,
        )

        if first_image and first_image.url and settings.openai_api_key:
            from openai import AsyncOpenAI
            vision_client = AsyncOpenAI(api_key=settings.openai_api_key)
            vision_task = classify_image(
                client=vision_client, image_url=first_image.url,
            )
            nlu_outcome, vision_outcome = await asyncio.gather(
                nlu_task, vision_task, return_exceptions=True,
            )
            if isinstance(nlu_outcome, BaseException):
                raise nlu_outcome
            nlu, usage = nlu_outcome
            if isinstance(vision_outcome, BaseException):
                await self._emitter.emit(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    event_type=EventType.ERROR_OCCURRED,
                    payload={
                        "where": "vision",
                        "exception": type(vision_outcome).__name__,
                        "message": str(vision_outcome)[:200],
                    },
                )
            else:
                # vision_result is consumed by mode-specific dispatch in T21.
                (vision_result, _tokens_in, _tokens_out,
                 vision_cost_usd, vision_latency_ms) = vision_outcome
        else:
            nlu, usage = await nlu_task

        # Surface NLU-level errors as ERROR_OCCURRED events for observability.
        nlu_errors = [a for a in nlu.ambiguities if a.startswith("nlu_error:")]
        if nlu_errors:
            await self._emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.ERROR_OCCURRED,
                payload={"where": "nlu", "ambiguities": nlu_errors},
            )

        # Merge NLU entities into state_obj BEFORE process_turn so the transition
        # check (e.g. all_required_fields_present) sees fields just extracted.
        for k, field in nlu.entities.items():
            state_obj.extracted_data[k] = field

        decision = process_turn(pipeline, state_obj, nlu, turn_number)

        # Build the JSONB shape from the now-up-to-date state_obj for persistence.
        merged_extracted = dict(extracted_jsonb or {})
        for k, field in nlu.entities.items():
            merged_extracted[k] = {
                "value": field.value,
                "confidence": field.confidence,
                "source_turn": field.source_turn,
            }

        previous_stage = current_stage
        next_stage_id = decision.next_stage
        new_stage_entered_at = (
            datetime.now(UTC)
            if next_stage_id != previous_stage
            else stage_entered_at
        )

        # Persist updated state
        await self._session.execute(
            text("""UPDATE conversation_state
                    SET extracted_data = :ed\\:\\:jsonb,
                        last_intent = :li,
                        stage_entered_at = :sea
                    WHERE conversation_id = :cid"""),
            {
                "ed": __import__("json").dumps(merged_extracted),
                "li": nlu.intent.value,
                "sea": new_stage_entered_at,
                "cid": conversation_id,
            },
        )
        # Accumulate per-turn LLM cost into conversation_state.total_cost_usd
        # (skipped if the provider didn't produce usage metadata, e.g. KeywordNLU/CannedNLU).
        if usage is not None and usage.cost_usd > 0:
            await self._session.execute(
                text("""UPDATE conversation_state
                        SET total_cost_usd = total_cost_usd + :c
                        WHERE conversation_id = :cid"""),
                {"c": usage.cost_usd, "cid": conversation_id},
            )
        # NOTE: we DO NOT update conversations.last_activity_at yet; the 24h
        # check below must read the value as it stood when the inbound arrived.
        await self._session.execute(
            text("UPDATE conversations SET current_stage = :s WHERE id = :cid"),
            {"s": next_stage_id, "cid": conversation_id},
        )

        # Emit transition events
        if next_stage_id != previous_stage:
            await self._emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.STAGE_EXITED,
                payload={"from": previous_stage},
            )
            await self._emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.STAGE_ENTERED,
                payload={"to": next_stage_id},
            )

        # ===== Phase 3b: tone, tools, 24h check, Composer =====

        # Load tone + brand_facts from tenant_branding.
        # voice -> Tone (Phase 3b). default_messages.brand_facts -> dict (Phase 3c.2,
        # T23 will populate the slot; until then it's an empty dict and the composer
        # pre-pass leaves brand_facts placeholders literal).
        branding_row = (await self._session.execute(
            text("SELECT voice, default_messages FROM tenant_branding WHERE tenant_id = :t"),
            {"t": tenant_id},
        )).fetchone()
        tone = Tone.model_validate(branding_row[0] if branding_row else {})
        brand_facts: dict = {}
        if branding_row and branding_row[1]:
            brand_facts = (branding_row[1] or {}).get("brand_facts", {}) or {}

        # Phase 3c.2 — deterministic flow_mode for this turn.
        # We feed pick_flow_mode an ExtractedFields built from the canonical
        # subset of merged_extracted (Pydantic ignores anything outside the
        # known field list). Tenants without rules in pipeline.flow_mode_rules
        # get the default `always -> SUPPORT` fallback so this never raises.
        from atendia.contracts.extracted_fields import ExtractedFields
        from atendia.runner.flow_router import pick_flow_mode
        ext_fields_data = {
            k: v["value"] for k, v in merged_extracted.items()
            if k in ExtractedFields.model_fields and v.get("value") is not None
        }
        try:
            ext_fields = ExtractedFields.model_validate(ext_fields_data)
        except Exception:
            # Mismatched legacy data shouldn't crash the runner — fall back to
            # defaults; SUPPORT mode handles unknown contexts gracefully.
            ext_fields = ExtractedFields()
        flow_mode = pick_flow_mode(
            rules=pipeline.flow_mode_rules,
            extracted=ext_fields,
            nlu=nlu,
            vision=vision_result,
            inbound_text=inbound.text,
            pending_confirmation=pending_confirmation,
        )

        # ===== Phase 3c.1: real-data tool dispatch =====
        # quote / lookup_faq / search_catalog now hit the real catalog/FAQ
        # tables. Embedding-driven paths (lookup_faq, semantic search_catalog
        # fallback) accumulate cost into `tool_cost_usd`, which is persisted
        # both into turn_traces.tool_cost_usd and rolled into
        # conversation_state.total_cost_usd alongside NLU + Composer cost.
        action_payload: dict = {}
        tool_cost_usd: Decimal = Decimal("0")

        if decision.action == "quote":
            interes = state_obj.extracted_data.get("interes_producto")
            interes_value = interes.value if interes is not None else None
            if interes_value:
                # Step 1: alias-keyword resolve (no embedding cost).
                catalog_hits = await search_catalog(
                    session=self._session, tenant_id=tenant_id,
                    query=str(interes_value), embedding=None, limit=1,
                )
                if isinstance(catalog_hits, list) and catalog_hits:
                    quote_result = await quote(
                        session=self._session, tenant_id=tenant_id,
                        sku=catalog_hits[0].sku,
                    )
                    action_payload = quote_result.model_dump(mode="json")
                else:
                    action_payload = ToolNoDataResult(
                        hint=f"no catalog match for {interes_value!r}",
                    ).model_dump(mode="json")
            else:
                action_payload = ToolNoDataResult(
                    hint="no interes_producto extracted yet",
                ).model_dump(mode="json")

        elif decision.action == "lookup_faq":
            if settings.openai_api_key:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=settings.openai_api_key)
                embedding, _, emb_cost = await generate_embedding(
                    client=client, text=inbound.text,
                )
                tool_cost_usd += emb_cost
                faq_result = await lookup_faq(
                    session=self._session, tenant_id=tenant_id,
                    embedding=embedding, top_k=3,
                )
                if isinstance(faq_result, list):
                    action_payload = {
                        "matches": [m.model_dump(mode="json") for m in faq_result],
                    }
                else:
                    action_payload = faq_result.model_dump(mode="json")
            else:
                action_payload = ToolNoDataResult(
                    hint="openai api key missing; cannot embed query",
                ).model_dump(mode="json")

        elif decision.action == "search_catalog":
            interes = state_obj.extracted_data.get("interes_producto")
            interes_value = interes.value if interes is not None else None
            query_text = str(interes_value) if interes_value else inbound.text
            # Path 1: alias-keyword (free).
            keyword_hits = await search_catalog(
                session=self._session, tenant_id=tenant_id,
                query=query_text, embedding=None,
            )
            if isinstance(keyword_hits, list) and keyword_hits:
                action_payload = {
                    "results": [r.model_dump(mode="json") for r in keyword_hits],
                }
            elif settings.openai_api_key:
                # Path 2: semantic fallback (embedding cost).
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=settings.openai_api_key)
                embedding, _, emb_cost = await generate_embedding(
                    client=client, text=query_text,
                )
                tool_cost_usd += emb_cost
                semantic_hits = await search_catalog(
                    session=self._session, tenant_id=tenant_id,
                    query=query_text, embedding=embedding,
                )
                if isinstance(semantic_hits, list):
                    action_payload = {
                        "results": [r.model_dump(mode="json") for r in semantic_hits],
                    }
                else:
                    action_payload = semantic_hits.model_dump(mode="json")
            else:
                action_payload = ToolNoDataResult(
                    hint=f"no alias match for {query_text!r}; openai key missing for semantic",
                ).model_dump(mode="json")

        elif decision.action == "ask_field":
            extracted_keys = set(merged_extracted.keys())
            missing = next(
                (f for f in current_stage_def.required_fields
                 if f.name not in extracted_keys),
                None,
            )
            if missing:
                action_payload = {
                    "field_name": missing.name,
                    "field_description": missing.description,
                }
        elif decision.action == "close":
            action_payload = {"payment_link": None}

        # 24h window check.
        last_activity_at = (await self._session.execute(
            text("SELECT last_activity_at FROM conversations WHERE id = :cid"),
            {"cid": conversation_id},
        )).scalar()
        inside_24h = (
            last_activity_at is None
            or (datetime.now(UTC) - last_activity_at) < timedelta(hours=24)
        )

        composer_input: ComposerInput | None = None
        composer_output: ComposerOutput | None = None
        composer_usage = None

        if not inside_24h and decision.action in COMPOSED_ACTIONS:
            # Outside 24h: no compose, no enqueue. Create handoff for visibility.
            from atendia.contracts.handoff_summary import HandoffReason
            from atendia.runner.handoff_helper import (
                build_handoff_summary,
                persist_handoff,
            )
            await persist_handoff(
                session=self._session,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                summary=build_handoff_summary(
                    reason=HandoffReason.OUTSIDE_24H_WINDOW,
                    extracted=ext_fields,
                    last_inbound_text=inbound.text,
                    suggested_next_action=(
                        "Contactar al cliente fuera del 24h window."
                    ),
                    docs_per_plan=pipeline.docs_per_plan,
                ),
            )
            await self._emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.HUMAN_HANDOFF_REQUESTED,
                payload={"reason": "outside_24h_window"},
            )
        elif decision.action in COMPOSED_ACTIONS:
            # Inside 24h, action produces text: invoke Composer.
            composer_history_turns = pipeline.composer.history_turns
            history_for_composer = (
                history[-composer_history_turns * 2:]
                if composer_history_turns > 0
                else []
            )
            composer_input = ComposerInput(
                action=decision.action,
                action_payload=action_payload,
                current_stage=next_stage_id,
                last_intent=nlu.intent.value,
                extracted_data={k: v.value for k, v in state_obj.extracted_data.items()}
                | {k: v["value"] for k, v in merged_extracted.items()},
                history=history_for_composer,
                tone=tone,
                max_messages=2,
                # Phase 3c.2 wiring:
                flow_mode=flow_mode,
                brand_facts=brand_facts,
                vision_result=vision_result,
                turn_number=turn_number,
            )
            composer_output, composer_usage = await self._composer.compose(
                input=composer_input,
            )

            # Phase 3c.2 — write back any binary slot the composer raised.
            # The next turn's runner will read this in _maybe_apply_confirmation
            # if the user replies sí/no.
            if composer_output is not None and composer_output.pending_confirmation_set:
                pending_confirmation = composer_output.pending_confirmation_set
                await self._session.execute(
                    text(
                        "UPDATE conversation_state "
                        "SET pending_confirmation = :pc "
                        "WHERE conversation_id = :cid"
                    ),
                    {"pc": pending_confirmation, "cid": conversation_id},
                )

            if composer_usage is not None and composer_usage.fallback_used:
                from atendia.contracts.handoff_summary import HandoffReason
                from atendia.runner.handoff_helper import (
                    build_handoff_summary,
                    persist_handoff,
                )
                await persist_handoff(
                    session=self._session,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    summary=build_handoff_summary(
                        reason=HandoffReason.COMPOSER_FAILED,
                        extracted=ext_fields,
                        last_inbound_text=inbound.text,
                        suggested_next_action=(
                            "Composer agotó retries; el cliente sigue esperando."
                        ),
                        docs_per_plan=pipeline.docs_per_plan,
                    ),
                )
                await self._emitter.emit(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    event_type=EventType.ERROR_OCCURRED,
                    payload={"where": "composer", "fallback": "canned"},
                )

        # Now that we have processed the turn, bump last_activity_at so the
        # next turn's 24h check sees a fresh value.
        await self._session.execute(
            text("UPDATE conversations SET last_activity_at = NOW() WHERE id = :cid"),
            {"cid": conversation_id},
        )

        # Accumulate every cost source for this turn into conversation_state in
        # a single UPDATE. Composer + tools (3c.1) + Vision (3c.2). The same
        # values are also written individually onto turn_traces below; this
        # row keeps the conversation-wide running total.
        composer_cost = composer_usage.cost_usd if composer_usage else Decimal("0")
        turn_cost = composer_cost + tool_cost_usd + vision_cost_usd
        if turn_cost > 0:
            await self._session.execute(
                text(
                    "UPDATE conversation_state "
                    "SET total_cost_usd = total_cost_usd + :c "
                    "WHERE conversation_id = :cid"
                ),
                {"c": turn_cost, "cid": conversation_id},
            )

        # Build state_after snapshot
        state_after = {
            "current_stage": next_stage_id,
            "extracted_data": merged_extracted,
            "last_intent": nlu.intent.value,
            "stage_entered_at": new_stage_entered_at.isoformat() if new_stage_entered_at else None,
            "followups_sent_count": followups_sent_count or 0,
            "total_cost_usd": str(total_cost_usd or Decimal("0")),
            "pending_confirmation": pending_confirmation,
        }

        # Persist turn_trace
        latency_ms = int((time.perf_counter() - started) * 1000)
        trace = TurnTrace(
            id=uuid4(),
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            turn_number=turn_number,
            inbound_message_id=None,  # phase 1: messages table not populated yet
            inbound_text=inbound.text,
            nlu_input={"text": inbound.text, "history": history},
            nlu_output=_jsonable(nlu.model_dump(mode="json")),
            nlu_model=usage.model if usage else None,
            nlu_tokens_in=usage.tokens_in if usage else None,
            nlu_tokens_out=usage.tokens_out if usage else None,
            nlu_cost_usd=usage.cost_usd if usage else None,
            nlu_latency_ms=usage.latency_ms if usage else None,
            state_before=_jsonable(state_before),
            state_after=_jsonable(state_after),
            stage_transition=(
                f"{previous_stage}->{next_stage_id}"
                if next_stage_id != previous_stage
                else None
            ),
            composer_input=(
                _jsonable(composer_input.model_dump(mode="json"))
                if composer_input is not None
                else None
            ),
            composer_output=(
                _jsonable(composer_output.model_dump(mode="json"))
                if composer_output is not None
                else None
            ),
            composer_model=(composer_usage.model if composer_usage else None),
            composer_tokens_in=(composer_usage.tokens_in if composer_usage else None),
            composer_tokens_out=(composer_usage.tokens_out if composer_usage else None),
            composer_cost_usd=(composer_usage.cost_usd if composer_usage else None),
            composer_latency_ms=(composer_usage.latency_ms if composer_usage else None),
            tool_cost_usd=tool_cost_usd if tool_cost_usd > 0 else None,
            vision_cost_usd=vision_cost_usd if vision_cost_usd > 0 else None,
            vision_latency_ms=vision_latency_ms,
            flow_mode=flow_mode.value,
            outbound_messages=(
                composer_output.messages if composer_output is not None else None
            ),
            total_latency_ms=latency_ms,
        )
        self._session.add(trace)
        await self._session.flush()

        # Enqueue outbound messages onto arq if we have a queue and recipient.
        if (
            composer_output is not None
            and arq_pool is not None
            and to_phone_e164 is not None
        ):
            await enqueue_messages(
                arq_pool,
                messages=composer_output.messages,
                tenant_id=tenant_id,
                to_phone_e164=to_phone_e164,
                conversation_id=conversation_id,
                turn_number=turn_number,
                action=decision.action,
            )
            # Phase 3d — schedule the 3h+12h re-engagement ladder. Only
            # when we actually sent text (composer_output is not None +
            # we have a queue). The earlier cancel_pending_followups call
            # cleared any rows from a previous turn; this re-arms with the
            # current snapshot so the silence clock restarts each turn.
            await schedule_followups_after_outbound(
                session=self._session,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                extracted_snapshot=merged_extracted,
            )

        return trace

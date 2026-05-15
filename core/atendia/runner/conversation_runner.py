import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from arq.connections import ArqRedis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.config import get_settings
from atendia.contracts.event import EventType
from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.message import Message
from atendia.contracts.tone import Tone
from atendia.contracts.vision_result import VisionResult
from atendia.db.models import TurnTrace
from atendia.runner.composer_protocol import (
    ComposerInput,
    ComposerOutput,
    ComposerProvider,
)
from atendia.runner.conversation_events import (
    emit_bot_paused,
    emit_document_event,
    emit_field_updated,
    emit_stage_changed,
    emit_system_event,
)
from atendia.runner.flow_router import _normalize_for_router
from atendia.runner.nlu_protocol import NLUProvider
from atendia.runner.outbound_dispatcher import COMPOSED_ACTIONS, enqueue_messages
from atendia.runner.vision_to_attrs import (
    VisionDocWrite,
    apply_vision_to_attrs,
)
from atendia.state_machine.event_emitter import EventEmitter
from atendia.state_machine.orchestrator import process_turn
from atendia.state_machine.pipeline_loader import load_active_pipeline
from atendia.tools.base import ToolNoDataResult
from atendia.tools.embeddings import generate_embedding
from atendia.tools.lookup_faq import lookup_faq
from atendia.tools.lookup_requirements import (
    RequirementsResult,
    lookup_requirements,
)
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


def _composer_provider_short_name(
    composer: ComposerProvider,
    *,
    fallback_used: bool = False,
) -> str | None:
    """Return short adapter name for the composer instance.

    'openai' — OpenAIComposer hitting the API successfully.
    'fallback' — OpenAIComposer that fell back to canned for this turn
      (caller passes ``fallback_used=True`` from the per-call
      ``UsageMetadata.fallback_used``).
    'canned' — CannedComposer (deterministic dev/test path).
    None — any future class we don't recognize (frontend degrades to
      no badge; the CHECK constraint rejects '' so NEVER return that).
    """
    cls = type(composer).__name__
    if cls == "CannedComposer":
        return "canned"
    if cls == "OpenAIComposer":
        return "fallback" if fallback_used else "openai"
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
_AFFIRMATIVE: frozenset[str] = frozenset(
    {
        "si",
        "sí",
        "claro",
        "ok",
        "okay",
        "yes",
        "ya",
        "sip",
        "simon",
    }
)
_NEGATIVE: frozenset[str] = frozenset({"no", "nop", "nada", "nel"})


def _confirmation_side_effects(
    pending_key: str,
    answer: str,
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
        row = (
            await self._session.execute(
                text("""SELECT current_stage, extracted_data, last_intent, stage_entered_at,
                           followups_sent_count, total_cost_usd, pending_confirmation,
                           bot_paused
                    FROM conversation_state cs JOIN conversations c ON c.id = cs.conversation_id
                    WHERE cs.conversation_id = :cid"""),
                {"cid": conversation_id},
            )
        ).fetchone()
        if row is None:
            raise RuntimeError(f"conversation_state not found for conversation {conversation_id}")
        (
            current_stage,
            extracted_jsonb,
            last_intent,
            stage_entered_at,
            followups_sent_count,
            total_cost_usd,
            pending_confirmation,
            bot_paused,
        ) = row

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
                inbound_text_cleaned=_normalize_for_router(inbound.text),
                composer_provider=_composer_provider_short_name(self._composer),
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
            session=self._session,
            conversation_id=conversation_id,
        )

        pipeline = await load_active_pipeline(self._session, tenant_id)
        agent_row = await self._load_agent(conversation_id=conversation_id, tenant_id=tenant_id)

        # Customer id is resolved once at the top of the turn and reused
        # by: (a) Vision-to-attrs (Fase 3, runs right after Vision),
        # (b) apply_ai_extractions (Fase 1, after NLU merges), and
        # (c) lookup_requirements (Fase 2, after action dispatch).
        # Single SELECT keeps the conversation-wide invariant aligned.
        customer_id_for_ext = (
            await self._session.execute(
                text("SELECT customer_id FROM conversations WHERE id = :cid"),
                {"cid": conversation_id},
            )
        ).scalar_one_or_none()

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

        state_obj_extracted = {k: ExtractedField(**v) for k, v in (extracted_jsonb or {}).items()}
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
        history_rows = (
            await self._session.execute(
                text("""SELECT direction, text FROM messages
                    WHERE conversation_id = :cid
                    ORDER BY sent_at DESC
                    LIMIT :n"""),
                {"cid": conversation_id, "n": history_turns * 2},
            )
        ).fetchall()
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

            state_obj.extracted_data = {k: ExtractedField(**v) for k, v in extracted_jsonb.items()}
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
                client=vision_client,
                image_url=first_image.url,
            )
            nlu_outcome, vision_outcome = await asyncio.gather(
                nlu_task,
                vision_task,
                return_exceptions=True,
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
                (vision_result, _tokens_in, _tokens_out, vision_cost_usd, vision_latency_ms) = (
                    vision_outcome
                )
        else:
            nlu, usage = await nlu_task

        # Fase 1 + Fase 3 — Vision side-effects in one pass:
        #   1. apply_vision_to_attrs writes customer.attrs[DOCS_X] using
        #      pipeline.vision_doc_mapping + VisionResult.quality_check.
        #   2. For each write, emit a DOCUMENT_ACCEPTED / _REJECTED
        #      system event so the chat timeline mirrors the attrs state.
        # When the tenant has no vision_doc_mapping configured, we fall
        # back to the Fase 1 category-level event (still useful: the
        # operator sees "Documento aceptado — INE" even if nothing was
        # written to attrs).
        if vision_result is not None:
            try:
                await self._process_vision_result(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    customer_id=customer_id_for_ext,
                    pipeline=pipeline,
                    vision_result=vision_result,
                )
            except Exception:
                import logging as _logging

                _logging.getLogger(__name__).exception(
                    "process_vision_result failed for conv=%s",
                    conversation_id,
                )

        # Surface NLU-level errors as ERROR_OCCURRED events for observability.
        nlu_errors = [a for a in nlu.ambiguities if a.startswith("nlu_error:")]
        if nlu_errors:
            await self._emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.ERROR_OCCURRED,
                payload={"where": "nlu", "ambiguities": nlu_errors},
            )

        if agent_row is not None and agent_row.active_intents:
            allowed = set(agent_row.active_intents or [])
            if nlu.intent.value not in allowed:
                await self._emitter.emit(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    event_type=EventType.HUMAN_HANDOFF_REQUESTED,
                    payload={
                        "reason": "agent_intent_not_allowed",
                        "agent_id": str(agent_row.id),
                        "intent": nlu.intent.value,
                    },
                )

        # Merge NLU entities into state_obj BEFORE process_turn so the transition
        # check (e.g. all_required_fields_present) sees fields just extracted.
        for k, field in nlu.entities.items():
            state_obj.extracted_data[k] = field

        # Cascade extractions to customer.attrs / field_suggestions.
        # Pure side-effect on the same session; never fails the turn.
        # The returned `applied_changes` drives FIELD_UPDATED system
        # messages (a curated subset of fields — see conversation_events
        # ._TIMELINE_WORTHY_FIELDS).
        try:
            from atendia.runner.ai_extraction_service import apply_ai_extractions

            if customer_id_for_ext is not None:
                applied_changes = await apply_ai_extractions(
                    session=self._session,
                    tenant_id=tenant_id,
                    customer_id=customer_id_for_ext,
                    conversation_id=conversation_id,
                    turn_number=turn_number,
                    entities=nlu.entities,
                    inbound_text=inbound.text,
                )
                # Fan out FIELD_UPDATED system events. The helper itself
                # filters by _TIMELINE_WORTHY_FIELDS, so passing every
                # change is safe — non-noisy fields are silently dropped.
                for change in applied_changes:
                    try:
                        await emit_field_updated(
                            self._session,
                            tenant_id=tenant_id,
                            conversation_id=conversation_id,
                            attr_key=change.attr_key,
                            old_value=change.old_value,
                            new_value=change.new_value,
                            confidence=change.confidence,
                            source="nlu",
                        )
                    except Exception:
                        import logging as _logging

                        _logging.getLogger(__name__).exception(
                            "emit_field_updated failed for conv=%s key=%s",
                            conversation_id,
                            change.attr_key,
                        )
        except Exception:
            import logging as _logging

            _logging.getLogger(__name__).exception(
                "apply_ai_extractions failed for conv=%s", conversation_id
            )

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
            datetime.now(UTC) if next_stage_id != previous_stage else stage_entered_at
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

        # M3 of the pipeline-automation editor plan: declarative rule
        # evaluation. The FSM (transitioner) just decided a stage based on
        # the orchestrator's deterministic logic; now we run the operator-
        # authored `auto_enter_rules` on each stage. If a rule fires and
        # picks a different stage, that's the final stage for this turn.
        # Wrapped in try/except so a malformed rule never crashes the
        # turn — the conversation just stays where the FSM put it.
        from atendia.state_machine.pipeline_evaluator import evaluate_pipeline_rules

        # rules_evaluated is captured for migration 045 so the DebugPanel
        # can render per-rule pass/fail. None when evaluation never ran
        # (e.g. evaluator raised below).
        rules_evaluated_payload: list[dict] | None = None
        try:
            rules_result = await evaluate_pipeline_rules(
                self._session,
                conversation_id,
                pipeline,
                trigger_event="field_updated",
            )
            rules_evaluated_payload = rules_result.rules_evaluated
            if rules_result.moved and rules_result.to_stage:
                # evaluate_pipeline_rules already persisted current_stage
                # + stage_entered_at. Sync local vars so subsequent code
                # (event emission, turn_trace state_after) reflects the
                # final stage.
                next_stage_id = rules_result.to_stage
                new_stage_entered_at = datetime.now(UTC)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "auto_enter_rules evaluation raised; staying at FSM stage %s",
                next_stage_id,
                exc_info=exc,
            )

        # Emit transition events (now reflecting both FSM + rule decisions)
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
            # Fase 1 — system message in the chat timeline so the
            # operator SEES "Conversación movida a X" inline. Looks up
            # stage labels from pipeline.stages; falls back to the raw
            # id when labels aren't defined.
            from_label = next(
                (s.label for s in pipeline.stages if s.id == previous_stage),
                None,
            )
            to_label = next(
                (s.label for s in pipeline.stages if s.id == next_stage_id),
                None,
            )
            try:
                await emit_stage_changed(
                    self._session,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    from_stage=previous_stage,
                    to_stage=next_stage_id,
                    from_label=from_label,
                    to_label=to_label,
                    reason=decision.reason,
                )
            except Exception:
                import logging as _logging

                _logging.getLogger(__name__).exception(
                    "emit_stage_changed failed for conv=%s %s->%s",
                    conversation_id,
                    previous_stage,
                    next_stage_id,
                )

        # Fase 4 — stage-entry handoff. When the just-entered stage has
        # `pause_bot_on_enter=true`, we (a) flip bot_paused=true on the
        # conversation, (b) persist a `human_handoffs` row with a
        # snapshot summary, (c) emit BOT_PAUSED + HUMAN_HANDOFF_REQUESTED
        # (+ DOCS_COMPLETE_FOR_PLAN when the stage's auto_enter_rules
        # used that operator), and (d) signal the composer block below
        # to skip — the operator answers from here on. Fail-soft: if
        # anything raises, we leave the conversation in its new stage
        # without pausing so the bot doesn't get stuck silent on a bug.
        auto_handoff_triggered = False
        if next_stage_id != previous_stage:
            try:
                auto_handoff_triggered = await self._trigger_stage_entry_handoff(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    pipeline=pipeline,
                    new_stage_id=next_stage_id,
                    last_inbound_text=inbound.text,
                    merged_extracted=merged_extracted,
                )
            except Exception:
                import logging as _logging

                _logging.getLogger(__name__).exception(
                    "stage_entry_handoff failed for conv=%s stage=%s",
                    conversation_id,
                    next_stage_id,
                )

        # ===== Phase 3b: tone, tools, 24h check, Composer =====

        # Load tone + brand_facts from tenant_branding.
        # voice -> Tone (Phase 3b). default_messages.brand_facts -> dict (Phase 3c.2,
        # T23 will populate the slot; until then it's an empty dict and the composer
        # pre-pass leaves brand_facts placeholders literal).
        branding_row = (
            await self._session.execute(
                text("SELECT voice, default_messages FROM tenant_branding WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).fetchone()
        tone = Tone.model_validate(branding_row[0] if branding_row else {})
        brand_facts: dict = {}
        if branding_row and branding_row[1]:
            brand_facts = (branding_row[1] or {}).get("brand_facts", {}) or {}
        if agent_row is not None:
            tone_data = tone.model_dump()
            tone_data["bot_name"] = agent_row.name
            tone_data["max_words_per_message"] = max(
                10, min(120, (agent_row.max_sentences or 5) * 20)
            )
            tone_data["use_emojis"] = (
                "never" if agent_row.no_emoji else tone_data.get("use_emojis", "sparingly")
            )
            tone_data["register"] = _agent_tone_to_register(agent_row.tone)
            tone = Tone.model_validate(tone_data)
            brand_facts = dict(brand_facts)
            if agent_row.goal:
                brand_facts["agent_goal"] = agent_row.goal
            # Compose the system-prompt-like brand fact from the
            # operator-authored prompt plus any active guardrails. The
            # composer reads `agent_system_prompt` as a single block, so
            # we concatenate here. Guardrails are operator-defined business
            # rules ("don't promise rates", "always confirm name") that
            # *must* survive — they go in their own labeled section so
            # the LLM treats them as hard constraints rather than style
            # suggestions.
            prompt_parts: list[str] = []
            if agent_row.system_prompt and agent_row.system_prompt.strip():
                prompt_parts.append(agent_row.system_prompt.strip())
            active_rules = [
                str(g.get("rule_text", "")).strip()
                for g in ((agent_row.ops_config or {}).get("guardrails") or [])
                if isinstance(g, dict) and g.get("active") is True and g.get("rule_text")
            ]
            if active_rules:
                rendered = "\n".join(f"- {r}" for r in active_rules)
                prompt_parts.append("REGLAS QUE NO PUEDES ROMPER (guardrails):\n" + rendered)
            if prompt_parts:
                brand_facts["agent_system_prompt"] = "\n\n".join(prompt_parts)

        # Knowledge-base scoping. The agent's `knowledge_config` may
        # carry a list of collection ids the agent is *allowed* to read
        # from. When set, every KB lookup downstream (lookup_faq,
        # search_catalog) is filtered to those collections; otherwise the
        # agent sees the full tenant KB. Mis-shaped values are tolerated
        # silently — a future migration can validate the schema.
        agent_collection_ids: list[UUID] = []
        if agent_row is not None:
            raw = (agent_row.knowledge_config or {}).get("collection_ids") or []
            if isinstance(raw, list):
                for item in raw:
                    try:
                        agent_collection_ids.append(UUID(str(item)))
                    except (ValueError, TypeError):
                        continue

        # Phase 3c.2 — deterministic flow_mode for this turn.
        # We feed pick_flow_mode an ExtractedFields built from the canonical
        # subset of merged_extracted (Pydantic ignores anything outside the
        # known field list). Tenants without rules in pipeline.flow_mode_rules
        # get the default `always -> SUPPORT` fallback so this never raises.
        from atendia.contracts.extracted_fields import ExtractedFields
        from atendia.runner.flow_router import pick_flow_mode

        ext_fields_data = {
            k: v["value"]
            for k, v in merged_extracted.items()
            if k in ExtractedFields.model_fields and v.get("value") is not None
        }
        try:
            ext_fields = ExtractedFields.model_validate(ext_fields_data)
        except Exception:
            # Mismatched legacy data shouldn't crash the runner — fall back to
            # defaults; SUPPORT mode handles unknown contexts gracefully.
            ext_fields = ExtractedFields()
        flow_decision = pick_flow_mode(
            rules=pipeline.flow_mode_rules,
            extracted=ext_fields,
            nlu=nlu,
            vision=vision_result,
            inbound_text=inbound.text,
            pending_confirmation=pending_confirmation,
        )
        flow_mode = flow_decision.mode
        # Persisted into turn_traces.router_trigger so the DebugPanel can
        # show the exact rule that fired (e.g. "doc_attachment" instead
        # of inferring it from observable side-effects).
        router_trigger = f"{flow_decision.rule_id}:{flow_decision.trigger_type}"

        # Fase 6 — stage-level override. When the just-entered stage
        # pins `behavior_mode`, it wins over the router's verdict.
        # We look up the FINAL stage (post auto_enter_rules), not the
        # stage where the turn started, so a Plan→DOC transition that
        # happens this turn lands the customer's reply in DOC mode.
        final_stage_def = next(
            (s for s in pipeline.stages if s.id == next_stage_id),
            None,
        )
        stage_pinned_mode = getattr(final_stage_def, "behavior_mode", None)
        if stage_pinned_mode:
            try:
                flow_mode = FlowMode(stage_pinned_mode)
            except (ValueError, KeyError):
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "stage %s behavior_mode=%r is invalid; using router's %s",
                    next_stage_id,
                    stage_pinned_mode,
                    flow_mode,
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
                    session=self._session,
                    tenant_id=tenant_id,
                    query=str(interes_value),
                    embedding=None,
                    limit=1,
                    collection_ids=agent_collection_ids or None,
                )
                if isinstance(catalog_hits, list) and catalog_hits:
                    quote_result = await quote(
                        session=self._session,
                        tenant_id=tenant_id,
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
                    client=client,
                    text=inbound.text,
                )
                tool_cost_usd += emb_cost
                faq_result = await lookup_faq(
                    session=self._session,
                    tenant_id=tenant_id,
                    embedding=embedding,
                    top_k=3,
                    collection_ids=agent_collection_ids or None,
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
                session=self._session,
                tenant_id=tenant_id,
                query=query_text,
                embedding=None,
                collection_ids=agent_collection_ids or None,
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
                    client=client,
                    text=query_text,
                )
                tool_cost_usd += emb_cost
                semantic_hits = await search_catalog(
                    session=self._session,
                    tenant_id=tenant_id,
                    query=query_text,
                    embedding=embedding,
                    collection_ids=agent_collection_ids or None,
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
                (f for f in current_stage_def.required_fields if f.name not in extracted_keys),
                None,
            )
            if missing:
                action_payload = {
                    "field_name": missing.name,
                    "field_description": missing.description,
                }
        elif decision.action == "close":
            action_payload = {"payment_link": None}

        # Fase 2 — surface the plan's doc requirements as auxiliary
        # context for the composer. Runs AFTER the action-specific
        # dispatch so every composed action (ask_field, lookup_faq,
        # search_catalog, …) gets the same shape under
        # `action_payload["requirements"]`. The composer reads it to
        # answer "para tu plan necesito X, Y, Z" — or to acknowledge
        # progress ("ya tengo INE, falta comprobante y estados de
        # cuenta"). When the customer hasn't picked a plan yet OR the
        # pipeline doesn't have docs_per_plan configured, the call
        # returns ToolNoDataResult and we skip silently.
        try:
            await self._attach_requirements_to_payload(
                action_payload=action_payload,
                pipeline=pipeline,
                customer_id=customer_id_for_ext,
                action=decision.action,
            )
        except Exception:
            import logging as _logging

            _logging.getLogger(__name__).exception(
                "attach_requirements_to_payload failed for conv=%s",
                conversation_id,
            )

        # 24h window check.
        last_activity_at = (
            await self._session.execute(
                text("SELECT last_activity_at FROM conversations WHERE id = :cid"),
                {"cid": conversation_id},
            )
        ).scalar()
        inside_24h = last_activity_at is None or (datetime.now(UTC) - last_activity_at) < timedelta(
            hours=24
        )

        composer_input: ComposerInput | None = None
        composer_output: ComposerOutput | None = None
        composer_usage = None

        # Fase 4 — auto-handoff for stage_entry. When pause_bot_on_enter
        # fired above, the bot has already produced its closing system
        # event ("Bot pausado — handoff humano"); we MUST NOT also run
        # Composer because the operator's first message is the next
        # outbound the customer should see. We still fall through to
        # turn_trace persistence so the turn is audited.
        if auto_handoff_triggered:
            # Mirror the outside-24h branch by skipping composer + outbound
            # without raising; turn_trace is still written below.
            pass
        elif not inside_24h and decision.action in COMPOSED_ACTIONS:
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
                    suggested_next_action=("Contactar al cliente fuera del 24h window."),
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
                history[-composer_history_turns * 2 :] if composer_history_turns > 0 else []
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
        # Migration 045 — build the kb_evidence block from action_payload.
        # FAQ matches and catalog results already carry faq_id /
        # catalog_item_id / collection_id since the tool models were
        # extended; we just project them into a stable UI-friendly shape.
        kb_evidence = _build_kb_evidence(decision.action, action_payload)
        trace = TurnTrace(
            id=uuid4(),
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            turn_number=turn_number,
            inbound_message_id=None,  # phase 1: messages table not populated yet
            inbound_text=inbound.text,
            inbound_text_cleaned=_normalize_for_router(inbound.text),
            composer_provider=_composer_provider_short_name(
                self._composer,
                fallback_used=composer_usage.fallback_used if composer_usage else False,
            ),
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
                f"{previous_stage}->{next_stage_id}" if next_stage_id != previous_stage else None
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
            outbound_messages=(composer_output.messages if composer_output is not None else None),
            total_latency_ms=latency_ms,
            # ── Migration 045 — DebugPanel observability ────────────────
            router_trigger=router_trigger,
            raw_llm_response=(
                composer_output.raw_llm_response if composer_output is not None else None
            ),
            agent_id=(agent_row.id if agent_row is not None else None),
            kb_evidence=kb_evidence,
            rules_evaluated=rules_evaluated_payload,
        )
        self._session.add(trace)
        await self._session.flush()

        # Enqueue outbound messages onto arq if we have a queue and recipient.
        if composer_output is not None and arq_pool is not None and to_phone_e164 is not None:
            await enqueue_messages(
                arq_pool,
                session=self._session,
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

        # D6 — composer-suggested escalation. When gpt-4o flags the turn
        # (suggested_handoff set to a HandoffReason value; validated on
        # ComposerOutput so a hallucinated label can't reach here), the
        # runner persists a structured handoff and pauses the bot. The
        # composed holding message ("un momento, te conecto con un
        # asesor") already went out via enqueue_messages above — going
        # abruptly silent would be worse UX — so the customer gets the
        # acknowledgement and a human picks up the next inbound turn.
        #
        # NOTE this path differs from STAGE_TRIGGERED_HANDOFF: there the
        # stage pauses BEFORE compose (auto_handoff_triggered skips
        # Composer/outbound entirely), so no message goes out. Here
        # compose already ran, so we send THEN pause.
        if composer_output is not None and composer_output.suggested_handoff:
            from atendia.contracts.handoff_summary import HandoffReason
            from atendia.runner.handoff_helper import (
                build_handoff_summary,
                persist_handoff,
            )

            reason = HandoffReason(composer_output.suggested_handoff)
            summary = build_handoff_summary(
                reason=reason,
                extracted=ext_fields,
                last_inbound_text=inbound.text,
                suggested_next_action=(
                    "Revisar el caso — el bot marcó escalación tras enviar "
                    "el mensaje de espera al cliente."
                ),
                docs_per_plan=pipeline.docs_per_plan,
            )
            await persist_handoff(
                session=self._session,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                summary=summary,
            )

            # Flip the bot_paused gate so the next inbound turn short-
            # circuits at the top of run_turn until an operator resumes.
            # bot_paused lives on conversation_state (the column the
            # top-of-turn SELECT/JOIN actually reads); the older
            # STAGE_TRIGGERED_HANDOFF path writes `conversations` instead,
            # which has no such column — we don't mirror that bug here.
            await self._session.execute(
                text(
                    "UPDATE conversation_state SET bot_paused = true WHERE conversation_id = :cid"
                ),
                {"cid": conversation_id},
            )

            await emit_bot_paused(
                self._session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                reason=reason.value,
            )

            # HUMAN_HANDOFF_REQUESTED — both the events table (workflows
            # listen to it) and a chat bubble so the operator notices.
            await self._emitter.emit(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                event_type=EventType.HUMAN_HANDOFF_REQUESTED,
                payload={"reason": reason.value, "source": "composer_suggested"},
            )
            await emit_system_event(
                self._session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                event_type=EventType.HUMAN_HANDOFF_REQUESTED,
                text=f"Sistema: Handoff humano solicitado — {reason.value}",
                payload={
                    "reason": reason.value,
                    "source": "composer_suggested",
                    "suggested_next_action": summary.suggested_next_action,
                },
            )

        return trace

    async def _trigger_stage_entry_handoff(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        pipeline: Any,
        new_stage_id: str,
        last_inbound_text: str,
        merged_extracted: dict[str, Any],
    ) -> bool:
        """Pause the bot + persist handoff + emit events for an opt-in stage.

        Returns True when the stage has `pause_bot_on_enter=true` and the
        handoff was triggered; False otherwise. Caller uses the bool to
        skip Composer/outbound for this turn.

        The summary is built from the SAME `extracted_data` snapshot the
        rest of the turn sees, so the operator dashboard reads a
        coherent state (extracted fields, plan, docs received/pending)
        — no race where the handoff lands first with stale fields.
        """
        stage = next(
            (s for s in pipeline.stages if s.id == new_stage_id),
            None,
        )
        if stage is None or not getattr(stage, "pause_bot_on_enter", False):
            return False

        from atendia.contracts.extracted_fields import ExtractedFields
        from atendia.contracts.handoff_summary import HandoffReason
        from atendia.runner.handoff_helper import (
            build_handoff_summary,
            persist_handoff,
        )

        # Translate the per-turn extracted_data map to the ExtractedFields
        # shape the summary builder expects (it's a Pydantic model with
        # a known field list; extras are ignored).
        ext_fields_data = {
            k: v["value"]
            for k, v in merged_extracted.items()
            if k in ExtractedFields.model_fields and v.get("value") is not None
        }
        try:
            ext_fields = ExtractedFields.model_validate(ext_fields_data)
        except Exception:
            ext_fields = ExtractedFields()

        # Resolve the reason: prefer stage-level override; fall back to
        # the generic STAGE_TRIGGERED_HANDOFF when the operator didn't
        # configure one. Strings not in the enum become the generic so
        # `human_handoffs.reason` stays a known label.
        reason_value: str | None = getattr(stage, "handoff_reason", None)
        try:
            reason = (
                HandoffReason(reason_value)
                if reason_value
                else HandoffReason.STAGE_TRIGGERED_HANDOFF
            )
        except ValueError:
            reason = HandoffReason.STAGE_TRIGGERED_HANDOFF

        summary = build_handoff_summary(
            reason=reason,
            extracted=ext_fields,
            last_inbound_text=last_inbound_text,
            suggested_next_action=(f"Revisar la conversación: entró a {stage.label or stage.id}."),
            docs_per_plan=pipeline.docs_per_plan,
        )
        await persist_handoff(
            session=self._session,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            summary=summary,
        )

        # Flip the bot_paused gate so subsequent inbound turns short-
        # circuit at the top of run_turn until an operator resumes.
        # bot_paused lives on conversation_state (the column the
        # top-of-turn SELECT/JOIN actually reads) — NOT conversations,
        # which has no such column. Mirrors the sibling pause site in
        # the composer-suggested handoff path.
        await self._session.execute(
            text("UPDATE conversation_state SET bot_paused = true WHERE conversation_id = :cid"),
            {"cid": conversation_id},
        )

        # Fase 1 events — visible in chat + workflows engine.
        # DOCS_COMPLETE_FOR_PLAN gets its own bubble when the stage's
        # auto_enter_rules used that operator (so the timeline reads
        # "Sistema: docs completos → Bot pausado → Handoff humano").
        if self._stage_uses_docs_complete_for_plan(stage):
            try:
                await emit_system_event(
                    self._session,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    event_type=EventType.DOCS_COMPLETE_FOR_PLAN,
                    text=(
                        f"Sistema: Papelería completa para "
                        f"{(ext_fields.plan_credito.value if ext_fields.plan_credito else 'el plan del cliente')}"
                    ),
                    payload={
                        "plan_credito": (
                            ext_fields.plan_credito.value if ext_fields.plan_credito else None
                        ),
                        "docs_recibidos": summary.docs_recibidos,
                    },
                )
            except Exception:
                import logging as _logging

                _logging.getLogger(__name__).exception(
                    "emit DOCS_COMPLETE_FOR_PLAN failed for conv=%s",
                    conversation_id,
                )

        await emit_bot_paused(
            self._session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            reason=reason.value,
        )

        # HUMAN_HANDOFF_REQUESTED — both the events table (workflows
        # listen to it) and a chat bubble so the operator notices.
        await self._emitter.emit(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            event_type=EventType.HUMAN_HANDOFF_REQUESTED,
            payload={"reason": reason.value, "stage": stage.id},
        )
        await emit_system_event(
            self._session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            event_type=EventType.HUMAN_HANDOFF_REQUESTED,
            text=f"Sistema: Handoff humano solicitado — {reason.value}",
            payload={
                "reason": reason.value,
                "stage": stage.id,
                "stage_label": getattr(stage, "label", None),
                "suggested_next_action": summary.suggested_next_action,
            },
        )
        return True

    @staticmethod
    def _stage_uses_docs_complete_for_plan(stage: Any) -> bool:
        """Inspect a stage's auto_enter_rules for the operator that
        signals papelería completa. Used by the handoff trigger to
        decide whether to emit the DOCS_COMPLETE_FOR_PLAN bubble."""
        rules = getattr(stage, "auto_enter_rules", None)
        if rules is None or not getattr(rules, "enabled", False):
            return False
        for cond in getattr(rules, "conditions", []) or []:
            if getattr(cond, "operator", None) == "docs_complete_for_plan":
                return True
        return False

    async def _attach_requirements_to_payload(
        self,
        *,
        action_payload: dict,
        pipeline: Any,  # PipelineDefinition; loose-typed to avoid a circular import.
        customer_id: UUID | None,
        action: str,
    ) -> None:
        """Enrich `action_payload` with the customer's plan requirements.

        Mutates `action_payload` in place — adds a `requirements` key
        whose value is the JSON-serialized RequirementsResult. Composer
        prompts can then list received / missing docs verbatim.

        No-op when:
          - The action is one the composer doesn't render (escalate, etc.).
          - The customer has no plan_credito yet.
          - The pipeline has no `docs_per_plan` configured for the plan.
          - `action_payload` is not a dict (e.g. some legacy paths set
            the payload to `None`).
          - A key called `requirements` is already present (e.g. set by
            a future tool path — don't clobber).
        """
        # Limit fan-out: paths like `escalate_to_human` don't reach the
        # composer at all; for those we'd be doing work for nothing.
        # Keep this aligned with COMPOSED_ACTIONS in outbound_dispatcher.
        if action not in COMPOSED_ACTIONS:
            return
        if not isinstance(action_payload, dict):
            return
        if "requirements" in action_payload:
            return
        if customer_id is None:
            return
        row = (
            await self._session.execute(
                text("SELECT attrs FROM customers WHERE id = :cid"),
                {"cid": customer_id},
            )
        ).fetchone()
        if row is None:
            return
        attrs = dict(row[0] or {})
        plan_credito = attrs.get("plan_credito")
        # Customer-stored shape is sometimes the {value, confidence}
        # wrapper inherited from the extraction layer — unwrap before
        # passing along, mirroring docs_complete_for_plan.
        if isinstance(plan_credito, dict) and "value" in plan_credito:
            plan_credito = plan_credito["value"]
        if not plan_credito:
            return
        result = lookup_requirements(
            pipeline=pipeline,
            plan_credito=str(plan_credito),
            customer_attrs=attrs,
        )
        if isinstance(result, RequirementsResult):
            action_payload["requirements"] = result.model_dump(mode="json")

    async def _process_vision_result(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        customer_id: UUID | None,
        pipeline: Any,
        vision_result: VisionResult,
    ) -> None:
        """Single entry point for Vision side-effects.

        Two halves, both fail-soft:

        1. **Attrs write** — Fase 3. When the tenant configured a
           `pipeline.vision_doc_mapping` entry for this category,
           `apply_vision_to_attrs` writes ``customer.attrs[DOCS_X]`` to
           the canonical ``{status, confidence, verified_at,
           rejection_reason?, side?}`` shape. Each write becomes a
           ``DOCUMENT_ACCEPTED`` / ``DOCUMENT_REJECTED`` event so the
           chat timeline mirrors the attrs state.

        2. **Fallback event** — Fase 1 behaviour. When the tenant has
           no mapping (or category is `unrelated`), we still emit a
           single category-level event so the operator at least sees
           "Documento aceptado — INE" in the timeline, even though
           nothing was written to attrs (operator marks it manually).

        Skipped entirely for ``category == moto`` (product photo).
        """
        from atendia.contracts.vision_result import VisionCategory

        category = vision_result.category
        confidence = float(vision_result.confidence)

        if category == VisionCategory.MOTO:
            return  # product photo, not a doc — no chat bubble either

        meta = vision_result.metadata if isinstance(vision_result.metadata, dict) else {}
        notas = meta.get("notas") or None

        if category == VisionCategory.UNRELATED:
            # No attrs write possible (no doc), but the operator still
            # benefits from a rejection bubble explaining the noise.
            reason = "no parece un documento del crédito"
            if notas:
                reason = f"{reason} ({notas})"
            await emit_document_event(
                self._session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                accepted=False,
                document_type=category.value,
                confidence=confidence,
                reason=reason,
                metadata=meta,
            )
            return

        # Doc category — try the structured Fase 3 path first.
        writes: list[VisionDocWrite] = []
        if customer_id is not None:
            writes = await apply_vision_to_attrs(
                session=self._session,
                customer_id=customer_id,
                pipeline=pipeline,
                vision_result=vision_result,
            )

        if writes:
            # Emit one event per attrs row touched. The Fase 1
            # SystemEventBubble keys off `metadata.event_type` so we
            # pass the doc_key + side under the payload to give the
            # operator full context.
            for w in writes:
                await emit_document_event(
                    self._session,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    accepted=w.accepted,
                    document_type=w.doc_key,
                    confidence=w.confidence,
                    reason=w.rejection_reason,
                    metadata={
                        "vision_category": category.value,
                        "side": w.side,
                        "notas": notas,
                    },
                )
            return

        # No mapping for this category (or no customer) — fall back to
        # the Fase 1 category-level event. Keeps the contract that
        # every Vision call yields at least one timeline bubble.
        qc = vision_result.quality_check
        if qc is not None:
            accepted = qc.valid_for_credit_file
            reason = qc.rejection_reason if not accepted else None
        else:
            legible = meta.get("legible")
            accepted = confidence >= 0.60 and legible is not False
            if accepted:
                reason = None
            elif legible is False:
                reason = "ilegible — pídela de nuevo con buena luz y sin reflejo"
            else:
                reason = f"baja confianza ({confidence:.0%})"
            if reason and notas:
                reason = f"{reason} — {notas}"
        await emit_document_event(
            self._session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            accepted=accepted,
            document_type=category.value,
            confidence=confidence,
            reason=reason,
            metadata=meta,
        )

    async def _load_agent(self, *, conversation_id: UUID, tenant_id: UUID):
        from atendia.db.models.agent import Agent

        row = (
            await self._session.execute(
                text(
                    """
                    SELECT assigned_agent_id
                    FROM conversations
                    WHERE id = :cid AND tenant_id = :tenant_id
                    """
                ),
                {"cid": conversation_id, "tenant_id": tenant_id},
            )
        ).fetchone()
        assigned_agent_id = row.assigned_agent_id if row else None
        if assigned_agent_id is not None:
            agent = (
                await self._session.execute(
                    select(Agent).where(Agent.id == assigned_agent_id, Agent.tenant_id == tenant_id)
                )
            ).scalar_one_or_none()
            if agent is not None:
                return agent
        return (
            await self._session.execute(
                select(Agent)
                .where(Agent.tenant_id == tenant_id, Agent.is_default.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()


def _agent_tone_to_register(value: str | None) -> str:
    mapping = {
        "amigable": "informal_mexicano",
        "informal": "informal_mexicano",
        "formal": "formal_es",
        "neutral": "neutral_es",
    }
    return mapping.get((value or "").lower(), "neutral_es")


def _build_kb_evidence(action: str, action_payload: dict) -> dict | None:
    """Migration 045 — normalize FAQ/catalog/quote results into a stable
    DebugPanel-friendly shape.

    Returns None when there's nothing knowledge-shaped to surface
    (action is not a KB action, or the tool returned ToolNoDataResult).
    The DebugPanel renders the KnowledgePanel based on this column —
    callers don't need to re-derive it from composer_input.action_payload.

    Shape:
        {
          "action": "lookup_faq" | "search_catalog" | "quote",
          "hits": [
            { "source_type": "faq",
              "source_id": <uuid|null>,
              "collection_id": <uuid|null>,
              "title": <str>,
              "preview": <str|null>,
              "score": <float|null> }
          ]
        }
    """
    if not isinstance(action_payload, dict) or not action_payload:
        return None

    hits: list[dict] = []

    matches = action_payload.get("matches")
    if isinstance(matches, list):
        for m in matches:
            if not isinstance(m, dict):
                continue
            hits.append(
                {
                    "source_type": "faq",
                    "source_id": m.get("faq_id"),
                    "collection_id": m.get("collection_id"),
                    "title": m.get("pregunta"),
                    "preview": m.get("respuesta"),
                    "score": m.get("score"),
                },
            )

    results = action_payload.get("results")
    if isinstance(results, list):
        for r in results:
            if not isinstance(r, dict):
                continue
            hits.append(
                {
                    "source_type": "catalog",
                    "source_id": r.get("catalog_item_id"),
                    "collection_id": r.get("collection_id"),
                    "title": r.get("name") or r.get("sku"),
                    "preview": (
                        f"${r['price_contado_mxn']}" if r.get("price_contado_mxn") else None
                    ),
                    "score": r.get("score"),
                },
            )

    # Quote payloads carry a single record (sku/name + price + planes).
    if action == "quote" and action_payload.get("status") == "ok":
        hits.append(
            {
                "source_type": "quote",
                "source_id": None,
                "collection_id": None,
                "title": action_payload.get("name") or action_payload.get("sku"),
                "preview": (
                    f"${action_payload['price_contado_mxn']}"
                    if action_payload.get("price_contado_mxn")
                    else None
                ),
                "score": None,
            },
        )

    if not hits and action in ("lookup_faq", "search_catalog", "quote"):
        # Tool ran but returned nothing — surface the hint so the
        # operator sees "no FAQ above similarity threshold" instead of
        # an empty panel.
        hint = action_payload.get("hint") if isinstance(action_payload, dict) else None
        return {"action": action, "hits": [], "empty_hint": hint}

    if not hits:
        return None

    return {"action": action, "hits": hits}

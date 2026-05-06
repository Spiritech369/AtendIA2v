import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from arq.connections import ArqRedis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.event import EventType
from atendia.contracts.message import Message
from atendia.contracts.tone import Tone
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

        pipeline = await load_active_pipeline(self._session, tenant_id)

        # Load current state row
        row = (await self._session.execute(
            text("""SELECT current_stage, extracted_data, last_intent, stage_entered_at,
                           followups_sent_count, total_cost_usd, pending_confirmation
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
         total_cost_usd, pending_confirmation) = row

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

        nlu, usage = await self._nlu.classify(
            text=inbound.text,
            current_stage=current_stage,
            required_fields=current_stage_def.required_fields,
            optional_fields=current_stage_def.optional_fields,
            history=history,
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

        # Load tone from tenant_branding.voice (defaults if missing).
        voice_row = (await self._session.execute(
            text("SELECT voice FROM tenant_branding WHERE tenant_id = :t"),
            {"t": tenant_id},
        )).fetchone()
        tone = Tone.model_validate(voice_row[0] if voice_row else {})

        # Invoke tool stubs to build action_payload.
        action_payload: dict = {}
        if decision.action == "quote":
            action_payload = ToolNoDataResult(
                hint="catalog not connected; cannot quote yet"
            ).model_dump()
        elif decision.action == "lookup_faq":
            action_payload = ToolNoDataResult(
                hint="faqs not connected; redirect"
            ).model_dump()
        elif decision.action == "search_catalog":
            action_payload = ToolNoDataResult(
                hint="catalog not connected; redirect"
            ).model_dump()
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
            await self._session.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(conversation_id, tenant_id, reason, status) "
                    "VALUES (:cid, :tid, 'outside_24h_window', 'pending')"
                ),
                {"cid": conversation_id, "tid": tenant_id},
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
            )
            composer_output, composer_usage = await self._composer.compose(
                input=composer_input,
            )

            if composer_usage is not None and composer_usage.fallback_used:
                await self._session.execute(
                    text(
                        "INSERT INTO human_handoffs "
                        "(conversation_id, tenant_id, reason, status) "
                        "VALUES (:cid, :tid, 'composer_failed', 'pending')"
                    ),
                    {"cid": conversation_id, "tid": tenant_id},
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

        # Accumulate composer cost into conversation_state.
        if composer_usage is not None and composer_usage.cost_usd > 0:
            await self._session.execute(
                text(
                    "UPDATE conversation_state "
                    "SET total_cost_usd = total_cost_usd + :c "
                    "WHERE conversation_id = :cid"
                ),
                {"c": composer_usage.cost_usd, "cid": conversation_id},
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

        return trace

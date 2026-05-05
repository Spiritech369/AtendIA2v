import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.event import EventType
from atendia.contracts.message import Message
from atendia.db.models import TurnTrace
from atendia.runner.nlu_protocol import NLUProvider
from atendia.state_machine.event_emitter import EventEmitter
from atendia.state_machine.orchestrator import process_turn
from atendia.state_machine.pipeline_loader import load_active_pipeline


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
    def __init__(self, session: AsyncSession, nlu_provider: NLUProvider) -> None:
        self._session = session
        self._nlu = nlu_provider
        self._emitter = EventEmitter(session)

    async def run_turn(
        self,
        *,
        conversation_id: UUID,
        tenant_id: UUID,
        inbound: Message,
        turn_number: int,
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
            stage_entered_at=stage_entered_at or datetime.now(timezone.utc),
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

        decision = process_turn(pipeline, state_obj, nlu, turn_number)

        # Merge NLU entities into extracted_data (overwrite same keys)
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
            datetime.now(timezone.utc)
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
        await self._session.execute(
            text("UPDATE conversations SET current_stage = :s, last_activity_at = NOW() WHERE id = :cid"),
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
        inbound_msg_uuid = _maybe_uuid(inbound.id)
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
            outbound_messages=None,
            total_latency_ms=latency_ms,
        )
        self._session.add(trace)
        await self._session.flush()
        return trace

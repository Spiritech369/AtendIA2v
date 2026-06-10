from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.agent_service import AgentService
from atendia.agent_runtime.schemas import TurnOutput
from atendia.runner.flow_router import _normalize_for_router
from atendia.db.models import TurnTrace


class DbBackedPreflightTurn(BaseModel):
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class DbBackedPreflightTurnResult(BaseModel):
    turn_number: int
    inbound_message_id: str | None = None
    final_message: str
    tools_requested: list[str] = Field(default_factory=list)
    tools_executed: list[dict[str, Any]] = Field(default_factory=list)
    state_writes: list[dict[str, Any]] = Field(default_factory=list)
    send_decision: dict[str, Any] = Field(default_factory=dict)
    delivery_status: dict[str, str] = Field(default_factory=dict)
    universal_turn_trace_present: bool = False
    trace_id: str | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


class DbBackedPreflightResult(BaseModel):
    tenant_id: str
    conversation_id: str
    mode: str = "no_send"
    turns: list[DbBackedPreflightTurnResult] = Field(default_factory=list)
    outbound_outbox_pending_retry: int | None = None
    business_event_ledger_side_effects_allowed: int | None = None
    audit_errors: list[dict[str, Any]] = Field(default_factory=list)


async def run_db_backed_preflight(
    *,
    session: AsyncSession,
    tenant_id: str,
    conversation_id: str,
    conversation_script: list[DbBackedPreflightTurn | dict[str, Any] | str],
    provider: Any | None = None,
) -> DbBackedPreflightResult:
    """Run a no-send preflight through the same DB-backed AgentService as live.

    This is not a simulator shortcut: messages are persisted as inbound fixture
    rows, context is rebuilt from DB each turn, StateWriter persistence is real,
    and only the final SendAdapter mode is forced to no-send.
    """

    service = AgentService(session=session, provider=provider)
    result = DbBackedPreflightResult(
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
    )
    for idx, raw_turn in enumerate(conversation_script, start=1):
        turn = _preflight_turn(raw_turn)
        metadata = {
            **turn.metadata,
            "attachments": turn.attachments,
            "db_backed_preflight": True,
            "send_execution_mode": "no_send",
        }
        inbound_message_id = await _insert_inbound_message(
            session=session,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            text_value=turn.text,
            metadata=metadata,
        )
        started = time.perf_counter()
        service_result = await service.handle_turn(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            inbound_text=turn.text,
            turn_number=idx,
            mode="no_send",
            metadata=metadata,
        )
        output = service_result.output
        trace = _universal_trace(output)
        turn_result = DbBackedPreflightTurnResult(
            turn_number=idx,
            inbound_message_id=str(inbound_message_id),
            final_message=output.final_message if output is not None else "",
            tools_requested=_tools_requested(output),
            tools_executed=_tools_executed(output),
            state_writes=_state_writes(output),
            send_decision=service_result.send.send_decision.model_dump(mode="json"),
            delivery_status=service_result.send.delivery_status,
            universal_turn_trace_present=trace is not None,
            errors=list(service_result.errors),
        )
        trace_row = TurnTrace(
            conversation_id=UUID(str(conversation_id)),
            tenant_id=UUID(str(tenant_id)),
            turn_number=idx,
            inbound_message_id=UUID(str(inbound_message_id)),
            inbound_text=turn.text,
            inbound_text_cleaned=_normalize_for_router(turn.text),
            state_before={"mode": "db_backed_preflight"},
            state_after={
                "mode": "db_backed_preflight",
                "send_status": service_result.send.delivery_status.get("send_status"),
                "send_decision": service_result.send.send_decision.model_dump(mode="json"),
                "universal_turn_trace": trace,
                "state_persistence": service_result.state_persistence,
            },
            composer_input={"runtime_path": "agent_runtime_v2"},
            composer_output=(
                {
                    "source": "TurnOutput.final_message",
                    "final_message": output.final_message,
                    "trace_metadata": output.trace_metadata,
                }
                if output is not None
                else None
            ),
            outbound_messages=None,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
            errors=service_result.errors or None,
            bot_paused=bool(output.needs_human if output is not None else True),
            router_trigger="agent_runtime_v2_db_backed_preflight",
            rules_evaluated=[
                {
                    "rule": "send_adapter_no_send_mode",
                    "result": service_result.send.delivery_status.get("send_status"),
                }
            ],
        )
        session.add(trace_row)
        await session.flush()
        turn_result.trace_id = str(trace_row.id)
        result.turns.append(turn_result)
    result.outbound_outbox_pending_retry = await _scalar_count(
        session,
        """SELECT COUNT(*)
        FROM outbound_outbox
        WHERE tenant_id = :tenant_id
          AND status IN ('pending', 'retry')""",
        tenant_id=tenant_id,
    )
    result.business_event_ledger_side_effects_allowed = await _scalar_count(
        session,
        """SELECT COUNT(*)
        FROM business_event_ledger
        WHERE tenant_id = :tenant_id
          AND side_effects_allowed = true""",
        tenant_id=tenant_id,
    )
    return result


def _preflight_turn(raw: DbBackedPreflightTurn | dict[str, Any] | str) -> DbBackedPreflightTurn:
    if isinstance(raw, DbBackedPreflightTurn):
        return raw
    if isinstance(raw, str):
        return DbBackedPreflightTurn(text=raw)
    return DbBackedPreflightTurn.model_validate(raw)


async def _insert_inbound_message(
    *,
    session: AsyncSession,
    tenant_id: str,
    conversation_id: str,
    text_value: str,
    metadata: dict[str, Any],
) -> UUID:
    return (
        await session.execute(
            text(
                """INSERT INTO messages
                    (tenant_id, conversation_id, direction, text, sent_at, metadata_json)
                VALUES
                    (:tenant_id, :conversation_id, 'inbound', :text_value, :sent_at,
                     CAST(:metadata AS jsonb))
                RETURNING id"""
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "text_value": text_value,
                "sent_at": datetime.now(UTC),
                "metadata": json.dumps(metadata, ensure_ascii=False),
            },
        )
    ).scalar_one()


def _universal_trace(output: TurnOutput | None) -> dict[str, Any] | None:
    if output is None:
        return None
    trace = output.trace_metadata.get("universal_turn_trace")
    return dict(trace) if isinstance(trace, dict) else None


def _tools_requested(output: TurnOutput | None) -> list[str]:
    if output is None:
        return []
    advisor = output.trace_metadata.get("advisor_brain")
    if not isinstance(advisor, dict):
        return []
    return [
        str(item.get("name"))
        for item in advisor.get("required_tools") or []
        if isinstance(item, dict) and item.get("name")
    ]


def _tools_executed(output: TurnOutput | None) -> list[dict[str, Any]]:
    if output is None:
        return []
    return [
        {
            "tool_name": str(item.get("tool_name")),
            "status": str(item.get("status")),
            "error": item.get("error"),
        }
        for item in output.trace_metadata.get("tool_results") or []
        if isinstance(item, dict)
    ]


def _state_writes(output: TurnOutput | None) -> list[dict[str, Any]]:
    if output is None:
        return []
    return [
        update.model_dump(mode="json")
        for update in output.field_updates
    ]


async def _scalar_count(
    session: AsyncSession,
    query: str,
    *,
    tenant_id: str,
) -> int | None:
    try:
        return int(
            (
                await session.execute(
                    text(query),
                    {"tenant_id": tenant_id},
                )
            ).scalar_one()
        )
    except Exception:
        return None

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.business_events import BusinessEvent, WorkflowResult
from atendia.db.models.business_event_ledger import BusinessEventLedgerRow


@dataclass(frozen=True)
class BusinessEventLedgerRecord:
    event_type: str
    idempotency_key: str
    status: str
    duplicate: bool
    ledger_id: str | None
    reason: str


async def record_business_event(
    session: AsyncSession,
    *,
    event: BusinessEvent,
    workflow_result: WorkflowResult | None = None,
    side_effects_allowed: bool = False,
) -> BusinessEventLedgerRecord:
    """Persist a business event idempotently without executing workflow side effects."""
    values = build_business_event_ledger_values(
        event=event,
        workflow_result=workflow_result,
        side_effects_allowed=side_effects_allowed,
    )
    insert_stmt = (
        insert(BusinessEventLedgerRow)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "conversation_id", "event_type", "idempotency_key"]
        )
        .returning(BusinessEventLedgerRow.id)
    )
    inserted_id = await session.scalar(insert_stmt)
    if inserted_id is not None:
        return BusinessEventLedgerRecord(
            event_type=event.event_type,
            idempotency_key=event.idempotency_key,
            status=str(values["status"]),
            duplicate=False,
            ledger_id=str(inserted_id),
            reason=str(values["reason"]),
        )
    return BusinessEventLedgerRecord(
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        status="duplicate",
        duplicate=True,
        ledger_id=None,
        reason="duplicate_idempotency_key",
    )


async def record_business_event_bundle(
    session: AsyncSession,
    *,
    events: list[BusinessEvent],
    workflow_results: list[WorkflowResult],
    side_effects_allowed: bool = False,
) -> list[BusinessEventLedgerRecord]:
    result_by_key = {result.idempotency_key: result for result in workflow_results}
    records: list[BusinessEventLedgerRecord] = []
    for event in events:
        records.append(
            await record_business_event(
                session,
                event=event,
                workflow_result=result_by_key.get(event.idempotency_key),
                side_effects_allowed=side_effects_allowed,
            )
        )
    return records


def build_business_event_ledger_values(
    *,
    event: BusinessEvent,
    workflow_result: WorkflowResult | None = None,
    side_effects_allowed: bool = False,
) -> dict[str, Any]:
    return {
        "tenant_id": _uuid_or_none(event.tenant_id),
        "conversation_id": _uuid_or_none(event.conversation_id),
        "event_type": event.event_type,
        "idempotency_key": event.idempotency_key,
        "status": _ledger_status(event, workflow_result),
        "reason": workflow_result.reason if workflow_result is not None else event.reason,
        "event_payload": event.model_dump(mode="json"),
        "workflow_result": (
            workflow_result.model_dump(mode="json") if workflow_result is not None else {}
        ),
        "trace_id": event.triggered_by.trace_id,
        "side_effects_allowed": bool(side_effects_allowed),
    }


def _ledger_status(
    event: BusinessEvent,
    workflow_result: WorkflowResult | None,
) -> str:
    if workflow_result is None:
        return event.status
    if workflow_result.status == "dry-run":
        return "dry_run"
    return workflow_result.status


def _uuid_or_none(value: Any) -> UUID | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


__all__ = [
    "BusinessEventLedgerRecord",
    "build_business_event_ledger_values",
    "record_business_event",
    "record_business_event_bundle",
]

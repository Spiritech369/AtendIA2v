from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from atendia.agent_runtime.business_event_ledger import (
    build_business_event_ledger_values,
    record_business_event,
    record_business_event_bundle,
)
from atendia.agent_runtime.business_events import BusinessEvent, TriggeredBy, WorkflowResult
from atendia.db.models.business_event_ledger import BusinessEventLedgerRow
from atendia.db.models.conversation import Conversation
from atendia.db.models.customer import Customer
from atendia.db.models.tenant import Tenant
from atendia.db.session import get_db_session

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER_ID = UUID("22222222-2222-2222-2222-222222222222")
CONVERSATION_ID = UUID("33333333-3333-3333-3333-333333333333")
OTHER_TENANT_ID = UUID("44444444-4444-4444-4444-444444444444")
OTHER_CUSTOMER_ID = UUID("55555555-5555-5555-5555-555555555555")
OTHER_CONVERSATION_ID = UUID("66666666-6666-6666-6666-666666666666")


@pytest_asyncio.fixture
async def db_session():
    async for session in get_db_session():
        yield session


async def _seed_conversation(
    session,
    *,
    tenant_id: UUID = TENANT_ID,
    customer_id: UUID = CUSTOMER_ID,
    conversation_id: UUID = CONVERSATION_ID,
    tenant_name: str = "Ledger Tenant",
    phone: str = "+5215550000001",
) -> None:
    session.add(
        Tenant(
            id=tenant_id,
            name=tenant_name,
            plan="standard",
            status="active",
            config={},
        )
    )
    await session.flush()
    session.add(
        Customer(
            id=customer_id,
            tenant_id=tenant_id,
            phone_e164=phone,
            name="Cliente ledger",
            attrs={},
        )
    )
    await session.flush()
    session.add(
        Conversation(
            id=conversation_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel="whatsapp_meta",
            status="active",
        )
    )
    await session.flush()


def _business_event(
    *,
    idempotency_key: str = "selection_identified:tenant:conversation:field:value",
    event_type: str = "selection_identified",
    tenant_id: UUID = TENANT_ID,
    customer_id: UUID = CUSTOMER_ID,
    conversation_id: UUID = CONVERSATION_ID,
) -> BusinessEvent:
    return BusinessEvent(
        event_id="event-1",
        event_type=event_type,
        tenant_id=str(tenant_id),
        agent_id="agent-1",
        conversation_id=str(conversation_id),
        contact_id=str(customer_id),
        domain="test_domain",
        source="state_writer",
        triggered_by=TriggeredBy(
            turn_id="turn-1",
            trace_id="trace-1",
            field_keys=["product_selection"],
        ),
        evidence_refs=["message:turn-1"],
        payload={"field": "product_selection", "value_hash": "abc123"},
        idempotency_key=idempotency_key,
        status="dry_run",
        reason="state_writer_accepted_selection_field",
    )


def _workflow_result(event: BusinessEvent, *, status: str = "dry-run") -> WorkflowResult:
    return WorkflowResult(
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        status=status,
        reason="workflow_execution_disabled_for_business_events_phase",
    )


def test_build_business_event_ledger_values_keeps_workflows_dry_run_by_default() -> None:
    event = _business_event()
    values = build_business_event_ledger_values(
        event=event,
        workflow_result=_workflow_result(event),
        side_effects_allowed=False,
    )

    assert values["status"] == "dry_run"
    assert values["side_effects_allowed"] is False
    assert values["event_payload"]["idempotency_key"] == event.idempotency_key
    assert values["workflow_result"]["status"] == "dry-run"


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_record_business_event_persists_dry_run_without_side_effects(db_session) -> None:
    await _seed_conversation(db_session)
    event = _business_event()
    workflow_result = _workflow_result(event)

    record = await record_business_event(
        db_session,
        event=event,
        workflow_result=workflow_result,
        side_effects_allowed=False,
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(BusinessEventLedgerRow).where(
                BusinessEventLedgerRow.idempotency_key == event.idempotency_key
            )
        )
    ).scalar_one()

    assert record.duplicate is False
    assert record.status == "dry_run"
    assert row.status == "dry_run"
    assert row.side_effects_allowed is False
    assert row.event_payload["event_type"] == "selection_identified"
    assert row.workflow_result["status"] == "dry-run"


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_record_business_event_blocks_duplicate_idempotency_key(db_session) -> None:
    await _seed_conversation(db_session)
    event = _business_event()

    first = await record_business_event(db_session, event=event)
    duplicate = await record_business_event(db_session, event=event)
    await db_session.flush()
    count = (
        await db_session.execute(
            select(func.count()).select_from(BusinessEventLedgerRow)
        )
    ).scalar_one()

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert duplicate.status == "duplicate"
    assert duplicate.reason == "duplicate_idempotency_key"
    assert count == 1


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_record_business_event_allows_same_key_in_different_tenant_scope(
    db_session,
) -> None:
    await _seed_conversation(db_session)
    await _seed_conversation(
        db_session,
        tenant_id=OTHER_TENANT_ID,
        customer_id=OTHER_CUSTOMER_ID,
        conversation_id=OTHER_CONVERSATION_ID,
        tenant_name="Other Ledger Tenant",
        phone="+5215550000002",
    )
    same_key = "selection_identified:same_external_key"
    first_event = _business_event(idempotency_key=same_key)
    other_event = _business_event(
        idempotency_key=same_key,
        tenant_id=OTHER_TENANT_ID,
        customer_id=OTHER_CUSTOMER_ID,
        conversation_id=OTHER_CONVERSATION_ID,
    )

    first = await record_business_event(db_session, event=first_event)
    second = await record_business_event(db_session, event=other_event)
    await db_session.flush()
    count = (
        await db_session.execute(
            select(func.count()).select_from(BusinessEventLedgerRow)
        )
    ).scalar_one()

    assert first.duplicate is False
    assert second.duplicate is False
    assert count == 2


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_record_business_event_bundle_preserves_safe_mode_blocked_status(db_session) -> None:
    await _seed_conversation(db_session)
    event = _business_event(
        idempotency_key="policy_blocked:tenant:conversation:guard",
        event_type="policy_blocked",
    )
    workflow_result = WorkflowResult(
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        status="blocked",
        dry_run=True,
        reason="safe_mode_blocks_workflow_execution",
        side_effects_allowed=False,
    )

    records = await record_business_event_bundle(
        db_session,
        events=[event],
        workflow_results=[workflow_result],
        side_effects_allowed=False,
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(BusinessEventLedgerRow).where(
                BusinessEventLedgerRow.idempotency_key == event.idempotency_key
            )
        )
    ).scalar_one()

    assert records[0].status == "blocked"
    assert row.status == "blocked"
    assert row.reason == "safe_mode_blocks_workflow_execution"
    assert row.side_effects_allowed is False

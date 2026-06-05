from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select

from atendia.agent_runtime.business_event_ledger import record_business_event
from atendia.agent_runtime.business_events import BusinessEvent, TriggeredBy
from atendia.agent_runtime.post_turn_executor import attach_workflow_bridge_post_turn_preview
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    AdvisorBrainDecision,
    CustomerContext,
    TenantRuntimeConfigContext,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult
from atendia.agent_runtime.universal_turn_trace import attach_universal_turn_trace
from atendia.agent_runtime.workflow_bridge import (
    WorkflowBridgeRuntimeFlags,
    attach_workflow_bridge_results_to_trace,
    consume_business_event_ledger_row,
    evaluate_workflow_bridge,
)
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


def _ledger_entry(
    *,
    event_type: str = "requirements_complete",
    tenant_id: str = str(TENANT_ID),
    conversation_id: str = str(CONVERSATION_ID),
    status: str = "dry_run",
    side_effects_allowed: bool = False,
) -> dict:
    return {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "event_type": event_type,
        "idempotency_key": f"{event_type}:tenant:conversation:fact",
        "status": status,
        "reason": "ledger_recorded",
        "trace_id": "trace-1",
        "side_effects_allowed": side_effects_allowed,
    }


def _tenant_config(
    *,
    event_type: str = "requirements_complete",
    workflow_id: str = "workflow-preview",
    enabled: bool = True,
    side_effects_allowed: bool = False,
    dry_run_by_default: bool = True,
    safe_mode: bool = False,
    actions: list[dict] | None = None,
) -> TenantRuntimeConfigContext:
    return TenantRuntimeConfigContext(
        safe_mode=safe_mode,
        workflow_event_metadata={
            event_type: {
                "event_type": event_type,
                "workflow_id": workflow_id,
                "enabled": enabled,
                "side_effects_allowed": side_effects_allowed,
                "dry_run_by_default": dry_run_by_default,
                "actions": actions or [],
            }
        },
    )


def _enabled_flags(**overrides: bool) -> WorkflowBridgeRuntimeFlags:
    values = {
        "actions_enabled": True,
        "workflow_side_effects_enabled": True,
        "workflow_events_enabled": True,
        "tenant_workflows_enabled": True,
    }
    values.update(overrides)
    return WorkflowBridgeRuntimeFlags(**values)


def _business_event(
    *,
    event_type: str = "requirements_complete",
    tenant_id: UUID = TENANT_ID,
    customer_id: UUID = CUSTOMER_ID,
    conversation_id: UUID = CONVERSATION_ID,
) -> BusinessEvent:
    return BusinessEvent(
        event_id=f"event-{event_type}",
        event_type=event_type,
        tenant_id=str(tenant_id),
        agent_id="agent-1",
        conversation_id=str(conversation_id),
        contact_id=str(customer_id),
        domain="test_domain",
        source="system",
        triggered_by=TriggeredBy(turn_id="turn-1", trace_id="trace-1"),
        evidence_refs=["message:turn-1"],
        payload={"checklist_hash": "abc123"},
        idempotency_key=f"{event_type}:{tenant_id}:{conversation_id}:abc123",
        status="dry_run",
        reason="requirements_complete_validated",
    )


def _turn_context(
    *,
    tenant_id: UUID = TENANT_ID,
    customer_id: UUID = CUSTOMER_ID,
    conversation_id: UUID = CONVERSATION_ID,
    tenant_config: TenantRuntimeConfigContext | None = None,
) -> TurnContext:
    return TurnContext(
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        inbound_text="hola",
        customer=CustomerContext(id=str(customer_id)),
        active_agent=ActiveAgentContext(id="agent-1"),
        tenant_config=tenant_config or _tenant_config(),
        metadata={"turn_id": "turn-1"},
    )


async def _seed_conversation(
    session,
    *,
    tenant_id: UUID = TENANT_ID,
    customer_id: UUID = CUSTOMER_ID,
    conversation_id: UUID = CONVERSATION_ID,
    tenant_name: str = "Bridge Tenant",
    phone: str = "+5215551000001",
) -> None:
    session.add(Tenant(id=tenant_id, name=tenant_name, status="active", config={}))
    await session.flush()
    session.add(
        Customer(
            id=customer_id,
            tenant_id=tenant_id,
            phone_e164=phone,
            name="Cliente bridge",
            attrs={},
        )
    )
    await session.flush()
    session.add(
        Conversation(
            id=conversation_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            status="active",
        )
    )
    await session.flush()


def test_registered_event_produces_dry_run_when_side_effects_disabled() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=_ledger_entry(),
        tenant_config=_tenant_config(),
        runtime_flags=_enabled_flags(workflow_side_effects_enabled=False),
    )

    assert result.status == "dry_run"
    assert result.reason == "workflow_side_effects_disabled"
    assert result.side_effects_allowed is False


def test_duplicate_event_does_not_produce_workflow() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry={**_ledger_entry(), "status": "duplicate", "duplicate": True},
        tenant_config=_tenant_config(),
        runtime_flags=_enabled_flags(),
    )

    assert result.status == "duplicate"
    assert result.workflow_id is None
    assert result.actions == []


def test_safe_mode_blocks_workflow() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=_ledger_entry(side_effects_allowed=True),
        tenant_config=_tenant_config(safe_mode=True, side_effects_allowed=True),
        runtime_flags=_enabled_flags(),
    )

    assert result.status == "blocked"
    assert result.reason == "safe_mode_blocks_workflow"


def test_missing_workflow_config_produces_not_configured() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=_ledger_entry(),
        tenant_config=TenantRuntimeConfigContext(),
        runtime_flags=_enabled_flags(),
    )

    assert result.status == "not_configured"
    assert result.reason == "workflow_not_configured"


def test_actions_enabled_false_blocks_live_execution_as_dry_run() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=_ledger_entry(side_effects_allowed=True),
        tenant_config=_tenant_config(side_effects_allowed=True, dry_run_by_default=False),
        runtime_flags=_enabled_flags(actions_enabled=False),
    )

    assert result.status == "dry_run"
    assert result.reason == "actions_disabled"


def test_workflow_side_effects_enabled_false_blocks_live_execution_as_dry_run() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=_ledger_entry(side_effects_allowed=True),
        tenant_config=_tenant_config(side_effects_allowed=True, dry_run_by_default=False),
        runtime_flags=_enabled_flags(workflow_side_effects_enabled=False),
    )

    assert result.status == "dry_run"
    assert result.reason == "workflow_side_effects_disabled"


def test_tenant_mismatch_blocks_workflow() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=_ledger_entry(tenant_id=str(OTHER_TENANT_ID)),
        tenant_config=_tenant_config(),
        runtime_flags=_enabled_flags(),
    )

    assert result.status == "blocked"
    assert result.reason == "tenant_mismatch"


def test_workflow_results_appear_in_universal_turn_trace() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=_ledger_entry(),
        tenant_config=_tenant_config(),
        runtime_flags=_enabled_flags(workflow_side_effects_enabled=False),
    )
    context = TurnContext(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        inbound_text="hola",
        customer=CustomerContext(id=str(CUSTOMER_ID)),
        active_agent=ActiveAgentContext(id="agent-1"),
        tenant_config=TenantRuntimeConfigContext(),
        metadata={"turn_id": "turn-1"},
    )
    decision = AdvisorBrainDecision(
        understanding="test",
        customer_goal="advance",
        next_best_action="respond",
        response_plan="respond",
        confidence=0.8,
    )
    output = attach_workflow_bridge_results_to_trace(
        TurnOutput(final_message="ok", confidence=0.8, trace_metadata={}),
        [result],
    )
    traced = attach_universal_turn_trace(
        context=context,
        decision=decision,
        tool_results=[],
        state_write_result=StateWriteResult(),
        policy_warnings=[],
        output=output,
    )

    workflow_results = traced.trace_metadata["universal_turn_trace"]["workflow_results"]
    assert workflow_results[0]["event_type"] == "requirements_complete"
    assert workflow_results[0]["status"] == "dry_run"


@pytest.mark.asyncio
async def test_post_turn_preview_attaches_workflow_results_without_session() -> None:
    event = _business_event()
    output = TurnOutput(
        final_message="ok",
        confidence=0.8,
        trace_metadata={"business_events": [event.model_dump(mode="json")]},
    )

    previewed = await attach_workflow_bridge_post_turn_preview(
        output,
        _turn_context(tenant_config=_tenant_config(event_type=event.event_type)),
    )

    workflow_results = previewed.trace_metadata["workflow_results"]
    assert workflow_results == previewed.trace_metadata["workflow_results"]
    assert workflow_results[0]["event_type"] == "requirements_complete"
    assert workflow_results[0]["status"] == "dry_run"
    assert workflow_results[0]["reason"] == "tenant_workflows_disabled"
    assert workflow_results[0]["ledger_status"] == "not_available"
    assert workflow_results[0]["side_effects_allowed"] is False
    assert workflow_results[0]["executed"] is False


@pytest.mark.asyncio
async def test_post_turn_preview_updates_existing_universal_trace_workflow_results() -> None:
    event = _business_event()
    output = TurnOutput(
        final_message="ok",
        confidence=0.8,
        trace_metadata={
            "universal_turn_trace": {
                "business_events": [event.model_dump(mode="json")],
                "workflow_results": [{"event_type": "old", "status": "dry-run"}],
            },
        },
    )

    previewed = await attach_workflow_bridge_post_turn_preview(
        output,
        _turn_context(tenant_config=_tenant_config(event_type=event.event_type)),
    )

    nested_results = previewed.trace_metadata["universal_turn_trace"]["workflow_results"]
    assert len(nested_results) == 1
    assert nested_results[0]["event_type"] == "requirements_complete"
    assert nested_results[0]["ledger_status"] == "not_available"


def test_dinamo_requirements_complete_generates_dry_run_handoff_preview() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=_ledger_entry(event_type="requirements_complete"),
        tenant_config=_tenant_config(
            event_type="requirements_complete",
            workflow_id="dinamo_handoff_review",
            enabled=False,
            actions=[{"type": "handoff_preview", "target": "review_queue"}],
        ),
        runtime_flags=_enabled_flags(workflow_side_effects_enabled=False),
    )

    assert result.status == "dry_run"
    assert result.workflow_id == "dinamo_handoff_review"
    assert result.actions == [{"type": "handoff_preview", "target": "review_queue"}]


def test_appointment_booking_event_generates_booking_preview_without_dinamo_fields() -> None:
    result = evaluate_workflow_bridge(
        tenant_id=str(OTHER_TENANT_ID),
        conversation_id=str(OTHER_CONVERSATION_ID),
        ledger_entry=_ledger_entry(
            event_type="appointment_booked",
            tenant_id=str(OTHER_TENANT_ID),
            conversation_id=str(OTHER_CONVERSATION_ID),
        ),
        tenant_config=_tenant_config(
            event_type="appointment_booked",
            workflow_id="appointment_booking_preview",
            enabled=True,
            actions=[{"type": "booking_preview", "calendar": "primary"}],
        ),
        runtime_flags=_enabled_flags(workflow_side_effects_enabled=False),
    )

    assert result.status == "dry_run"
    assert result.workflow_id == "appointment_booking_preview"
    assert result.actions[0]["type"] == "booking_preview"


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_bridge_consumes_ledger_row_and_persists_workflow_result(db_session) -> None:
    await _seed_conversation(db_session)
    event = _business_event()
    await record_business_event(db_session, event=event)
    row = (
        await db_session.execute(
            select(BusinessEventLedgerRow).where(
                BusinessEventLedgerRow.idempotency_key == event.idempotency_key
            )
        )
    ).scalar_one()

    result = await consume_business_event_ledger_row(
        db_session,
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_row=row,
        tenant_config=_tenant_config(event_type=event.event_type),
        runtime_flags=_enabled_flags(workflow_side_effects_enabled=False),
    )
    await db_session.flush()

    assert result.status == "dry_run"
    assert row.workflow_result["event_type"] == "requirements_complete"
    assert row.workflow_result["status"] == "dry_run"
    assert row.side_effects_allowed is False


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_bridge_duplicate_record_does_not_update_workflow_result(db_session) -> None:
    await _seed_conversation(db_session)
    event = _business_event()
    await record_business_event(db_session, event=event)
    duplicate = await record_business_event(db_session, event=event)

    result = evaluate_workflow_bridge(
        tenant_id=str(TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_entry=duplicate,
        tenant_config=_tenant_config(event_type=event.event_type),
        runtime_flags=_enabled_flags(),
    )

    assert result.status == "duplicate"
    assert result.actions == []


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_bridge_tenant_isolation_blocks_wrong_tenant(db_session) -> None:
    await _seed_conversation(db_session)
    event = _business_event()
    await record_business_event(db_session, event=event)
    row = (
        await db_session.execute(
            select(BusinessEventLedgerRow).where(
                BusinessEventLedgerRow.idempotency_key == event.idempotency_key
            )
        )
    ).scalar_one()

    result = await consume_business_event_ledger_row(
        db_session,
        tenant_id=str(OTHER_TENANT_ID),
        conversation_id=str(CONVERSATION_ID),
        ledger_row=row,
        tenant_config=_tenant_config(event_type=event.event_type),
        runtime_flags=_enabled_flags(),
    )

    assert result.status == "blocked"
    assert result.reason == "tenant_mismatch"


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_post_turn_preview_records_ledger_and_trace_without_side_effects(db_session) -> None:
    await _seed_conversation(db_session)
    event = _business_event()
    output = TurnOutput(
        final_message="ok",
        confidence=0.8,
        trace_metadata={"business_events": [event.model_dump(mode="json")]},
    )

    previewed = await attach_workflow_bridge_post_turn_preview(
        output,
        _turn_context(tenant_config=_tenant_config(event_type=event.event_type)),
        session=db_session,
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(BusinessEventLedgerRow).where(
                BusinessEventLedgerRow.idempotency_key == event.idempotency_key
            )
        )
    ).scalar_one()
    workflow_result = previewed.trace_metadata["workflow_results"][0]

    assert workflow_result["status"] == "dry_run"
    assert workflow_result["ledger_status"] == "inserted"
    assert workflow_result["side_effects_allowed"] is False
    assert workflow_result["executed"] is False
    assert row.workflow_result["ledger_status"] == "inserted"
    assert row.side_effects_allowed is False


@pytest.mark.integration_db
@pytest.mark.asyncio
async def test_post_turn_preview_duplicate_event_does_not_insert_second_ledger_row(
    db_session,
) -> None:
    await _seed_conversation(db_session)
    event = _business_event()
    output = TurnOutput(
        final_message="ok",
        confidence=0.8,
        trace_metadata={"business_events": [event.model_dump(mode="json")]},
    )
    context = _turn_context(tenant_config=_tenant_config(event_type=event.event_type))

    await attach_workflow_bridge_post_turn_preview(output, context, session=db_session)
    duplicate_preview = await attach_workflow_bridge_post_turn_preview(
        output,
        context,
        session=db_session,
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(BusinessEventLedgerRow).where(
                BusinessEventLedgerRow.idempotency_key == event.idempotency_key
            )
        )
    ).scalars().all()

    assert len(rows) == 1
    assert duplicate_preview.trace_metadata["workflow_results"][0]["status"] == "duplicate"
    assert duplicate_preview.trace_metadata["workflow_results"][0]["ledger_status"] == "duplicate"

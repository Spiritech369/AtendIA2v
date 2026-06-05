from __future__ import annotations

from atendia.agent_runtime.schemas import (
    ActionRequest,
    ActionResult,
    CustomerContext,
    FieldUpdate,
    LifecycleUpdate,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.workflow_events import AgentWorkflowEventEmitter


def _context() -> TurnContext:
    return TurnContext(
        tenant_id="11111111-1111-1111-1111-111111111111",
        conversation_id="22222222-2222-2222-2222-222222222222",
        inbound_text="hola",
        customer=CustomerContext(id="33333333-3333-3333-3333-333333333333"),
        metadata={"knowledge": {"answerable": False, "missing_info": "horario"}},
    )


def test_low_confidence_and_knowledge_gap_events_are_built():
    output = TurnOutput(
        final_message="No tengo ese dato confirmado.",
        confidence=0.4,
        needs_human=True,
        risk_flags=["knowledge_gap"],
        trace_metadata={"trace_id": "trace-1"},
    )

    events = AgentWorkflowEventEmitter().build_for_turn(
        context=_context(),
        output=output,
        action_results=[],
        policy_issues=[],
        dry_run=True,
    )

    event_types = {event.type for event in events}
    assert "agent_turn_completed" in event_types
    assert "agent_confidence_low" in event_types
    assert "agent_needs_human" in event_types
    assert "agent_knowledge_gap_detected" in event_types
    assert all(event.payload["dry_run"] is True for event in events)


def test_policy_blocked_and_field_update_events_are_built():
    output = TurnOutput(
        final_message="Listo.",
        confidence=0.8,
        field_updates=[
            FieldUpdate(
                field_key="budget",
                value="1000",
                reason="El cliente dijo su presupuesto.",
                evidence=["tengo 1000"],
                confidence=0.8,
            )
        ],
    )

    events = AgentWorkflowEventEmitter().build_for_turn(
        context=_context(),
        output=output,
        action_results=[],
        policy_issues=[{"code": "field_update_missing_evidence", "message": "blocked"}],
        dry_run=True,
    )

    by_type = {event.type: event for event in events}
    assert by_type["agent_field_update_suggested"].payload["field_key"] == "budget"
    assert by_type["agent_policy_blocked"].payload["policy_issues"][0]["code"] == (
        "field_update_missing_evidence"
    )


async def test_policy_blocked_can_emit_simulated_event_without_turn_output():
    events = await AgentWorkflowEventEmitter().emit_policy_blocked(
        None,  # type: ignore[arg-type]
        context=_context(),
        policy_issues=[{"code": "empty_final_message", "message": "blocked"}],
        dry_run=True,
        emit_real=False,
        trace_id="trace-policy",
    )

    assert len(events) == 1
    assert events[0].type == "agent_policy_blocked"
    assert events[0].simulated is True
    assert events[0].payload["trace_id"] == "trace-policy"
    assert events[0].payload["needs_human"] is True


def test_lifecycle_and_action_result_events_are_built_without_visible_copy():
    output = TurnOutput(
        final_message="Te ayudo.",
        confidence=0.9,
        lifecycle_update=LifecycleUpdate(
            target_stage="qualified",
            reason="Tiene intención clara.",
            evidence=["quiero comprar"],
            confidence=0.9,
        ),
        actions=[
            ActionRequest(
                name="add_tag",
                payload={"tag": "hot"},
                reason="Intención clara.",
                evidence=["quiero comprar"],
            )
        ],
    )

    events = AgentWorkflowEventEmitter().build_for_turn(
        context=_context(),
        output=output,
        action_results=[ActionResult(action_name="add_tag", status="skipped")],
        policy_issues=[],
        dry_run=True,
    )

    by_type = {event.type: event for event in events}
    assert by_type["agent_lifecycle_update_suggested"].payload["lifecycle_stage"] == "qualified"
    assert by_type["agent_action_executed"].payload["action_id"] == "add_tag"
    assert "final_message" not in by_type["agent_action_executed"].payload["result"]

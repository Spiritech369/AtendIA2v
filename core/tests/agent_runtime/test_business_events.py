from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atendia.agent_runtime.business_events import derive_business_event_bundle
from atendia.agent_runtime.canonical import CanonicalProductReference, QuoteSnapshot
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    AdvisorBrainDecision,
    CustomerContext,
    LifecycleUpdate,
    TenantRuntimeConfigContext,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)
from atendia.agent_runtime.tracing import build_trace_metadata
from atendia.agent_runtime.universal_turn_trace import attach_universal_turn_trace

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _raw_with_events(name: str, *events: str) -> dict[str, Any]:
    raw = _fixture(name)
    raw["workflow_events"] = sorted(set([*raw.get("workflow_events", []), *events]))
    return raw


def _tenant_config(
    raw: dict[str, Any] | None,
    *,
    safe_mode: bool = False,
) -> TenantRuntimeConfigContext:
    if raw is None:
        return TenantRuntimeConfigContext(safe_mode=safe_mode)
    result = load_tenant_domain_contract(raw, tenant_id=raw["tenant_id"], agent_id=raw["agent_id"])
    config = apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)
    if safe_mode:
        config = config.model_copy(update={"safe_mode": True})
    return config


def _context(
    raw: dict[str, Any] | None = None,
    *,
    safe_mode: bool = False,
    metadata: dict[str, Any] | None = None,
) -> TurnContext:
    tenant_id = raw["tenant_id"] if raw else "tenant-generic"
    agent_id = raw["agent_id"] if raw else "agent-generic"
    return TurnContext(
        tenant_id=tenant_id,
        conversation_id="conversation-1",
        inbound_text="Mensaje del cliente con palabras que no disparan eventos por si solas.",
        customer=CustomerContext(id="contact-1"),
        tenant_config=_tenant_config(raw, safe_mode=safe_mode),
        active_agent=ActiveAgentContext(id=agent_id),
        metadata={"turn_id": "turn-1", "turn_number": 1, "agent_id": agent_id, **(metadata or {})},
    )


def _decision(**metadata: Any) -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="Structured runtime decision.",
        customer_goal="advance",
        conversation_goals=["advance"],
        next_best_action="respond",
        response_plan="Use validated data only.",
        confidence=0.9,
        metadata=metadata,
    )


def _accepted(
    field: str,
    value: Any,
    *,
    source: str = "customer_message",
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "target": "contact_field",
        "key": field,
        "field": field,
        "proposed_value": value,
        "decision": "accepted",
        "reason": "field_policy_auto_apply_accepted",
        "source": source,
        "writer": "StateWriter",
        "evidence_refs": evidence_refs or ["message:turn-1"],
        "confidence": 1.0,
    }


def _blocked(field: str, value: Any) -> dict[str, Any]:
    return {
        "target": "contact_field",
        "key": field,
        "field": field,
        "proposed_value": value,
        "decision": "blocked",
        "reason": "field_policy_blocked",
        "source": "model_proposed",
    }


def _output(context: TurnContext, *, trace_extra: dict[str, Any] | None = None) -> TurnOutput:
    return TurnOutput(
        final_message="Mensaje final validado.",
        confidence=0.9,
        trace_metadata=build_trace_metadata(
            context=context,
            provider="test",
            extra=trace_extra or {},
        ),
    )


def _bundle(
    *,
    context: TurnContext,
    state_write_result: StateWriteResult,
    tool_results: list[ToolExecutionResult] | None = None,
    output: TurnOutput | None = None,
    decision: AdvisorBrainDecision | None = None,
):
    return derive_business_event_bundle(
        context=context,
        decision=decision or _decision(),
        tool_results=tool_results or [],
        state_write_result=state_write_result,
        output=output or _output(context),
    )


def _event_types(bundle) -> list[str]:
    return [event.event_type for event in bundle.business_events]


def _event(bundle, event_type: str):
    return next(event for event in bundle.business_events if event.event_type == event_type)


def _quote_tool(context: TurnContext) -> ToolExecutionResult:
    snapshot = QuoteSnapshot(
        snapshot_id="quote-123",
        tenant_id=context.tenant_id,
        product=CanonicalProductReference(
            product_id="product-1",
            sku="SKU-1",
            display_name="Producto validado",
            evidence=["catalog:item-1"],
        ),
        plan_code="plan-a",
        currency="MXN",
        pricing={"cash_price": 1000, "payment": 100},
        source_tool="quote.resolve",
        evidence=["quote.resolve"],
        created_at="2026-06-04T00:00:00+00:00",
    )
    return ToolExecutionResult(
        tool_name="quote.resolve",
        status="succeeded",
        data={"quote_snapshot": snapshot.model_dump(mode="json")},
        trace_metadata={"safe_inputs": {"product_id": "product-1"}},
    )


def _requirements_tool() -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name="requirements.lookup",
        status="succeeded",
        data={"requirements": ["id", "proof"], "evidence": ["kb:req-1"]},
    )


def _document_tool(*, complete: bool = False) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name="document.check",
        status="succeeded",
        data={
            "complete": complete,
            "checklist": [
                {"key": "id", "status": "accepted"},
                {"key": "proof", "status": "accepted" if complete else "missing"},
            ],
            "evidence": ["attachment:att-1"],
        },
    )


def test_selection_identified_requires_state_writer_accepted_selection_field() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"))

    accepted_bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[_accepted("product_selection", {"product_id": "product-1"})],
        ),
    )
    blocked_bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[],
            blocked=[_blocked("product_selection", "free text")],
        ),
    )

    event = _event(accepted_bundle, "selection_identified")
    assert event.source == "state_writer"
    assert event.triggered_by.field_keys == ["product_selection"]
    assert event.status == "dry_run"
    assert "selection_identified" not in _event_types(blocked_bundle)


def test_plan_identified_requires_state_writer_accepted_plan_field() -> None:
    context = _context(_raw_with_events("vehicle_credit_sales.json", "plan_identified"))

    bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[_accepted("plan_selection", "plan-a")],
        ),
    )

    event = _event(bundle, "plan_identified")
    assert event.triggered_by.field_keys == ["plan_selection"]
    assert event.idempotency_key.startswith("plan_identified:")


def test_offer_quoted_requires_quote_snapshot_from_quote_resolve() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"))
    bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[_accepted("quote_snapshot_id", "quote-123", source="quote.resolve")],
        ),
        tool_results=[_quote_tool(context)],
    )

    event = _event(bundle, "offer_quoted")
    assert event.triggered_by.tool_ids == ["quote.resolve"]
    assert event.payload["quote_snapshot_id"] == "quote-123"
    assert event.status == "dry_run"


def test_offer_quoted_not_emitted_if_mandatory_tool_guard_blocked_quote() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"))
    output = _output(
        context,
        trace_extra={
            "mandatory_tool_decisions": [
                {"tool_id": "quote.resolve", "status": "missing", "blocking": True}
            ],
            "mandatory_tool_guard": {
                "decisions": [
                    {"tool_id": "quote.resolve", "status": "missing", "blocking": True}
                ]
            },
        },
    )
    bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[_accepted("quote_snapshot_id", "quote-123", source="quote.resolve")],
        ),
        tool_results=[_quote_tool(context)],
        output=output,
    )

    assert "offer_quoted" not in _event_types(bundle)
    assert "policy_blocked" in _event_types(bundle)


def test_requirements_requested_requires_requirements_tool() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"))

    with_tool = _bundle(
        context=context,
        state_write_result=StateWriteResult(),
        tool_results=[_requirements_tool()],
    )
    without_tool = _bundle(context=context, state_write_result=StateWriteResult())

    assert "requirements_requested" in _event_types(with_tool)
    assert "requirements_requested" not in _event_types(without_tool)


def test_document_received_requires_attachment_and_document_check() -> None:
    context = _context(
        _raw_with_events("vehicle_credit_sales.json", "document_received"),
        metadata={"attachment_id": "att-1"},
    )

    with_evidence = _bundle(
        context=context,
        state_write_result=StateWriteResult(),
        tool_results=[_document_tool()],
    )
    without_tool = _bundle(context=context, state_write_result=StateWriteResult())

    assert "document_received" in _event_types(with_evidence)
    assert "document_received" not in _event_types(without_tool)


def test_requirements_complete_requires_system_derived_field_and_document_evidence() -> None:
    context = _context(
        _raw_with_events("vehicle_credit_sales.json", "requirements_complete"),
        metadata={"attachment_id": "att-1"},
    )
    bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[
                _accepted(
                    "requirements_complete",
                    True,
                    source="document.check",
                    evidence_refs=["tool_result:document.check"],
                )
            ],
        ),
        tool_results=[_requirements_tool(), _document_tool(complete=True)],
    )

    event = _event(bundle, "requirements_complete")
    assert sorted(event.triggered_by.tool_ids) == ["document.check", "requirements.lookup"]
    assert event.status == "dry_run"


def test_human_handoff_requested_requires_structured_reason() -> None:
    context = _context(_raw_with_events("vehicle_credit_sales.json", "human_handoff_requested"))
    with_reason = _bundle(
        context=context,
        state_write_result=StateWriteResult(),
        output=_output(context, trace_extra={"handoff_reason": "customer_requested_human"}),
    )
    without_reason = _bundle(
        context=context,
        state_write_result=StateWriteResult(),
        output=TurnOutput(final_message="Necesita humano.", needs_human=True),
    )

    assert "human_handoff_requested" in _event_types(with_reason)
    assert "human_handoff_requested" not in _event_types(without_reason)


def test_events_do_not_duplicate_same_idempotency_key() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"))
    bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[
                _accepted("product_selection", "product-1"),
                _accepted("product_selection", "product-1"),
            ],
        ),
    )

    selection_events = [
        event for event in bundle.business_events if event.event_type == "selection_identified"
    ]
    assert len(selection_events) == 1


def test_safe_mode_blocks_workflow_side_effects() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"), safe_mode=True)
    bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[_accepted("product_selection", "product-1")],
        ),
    )

    event = _event(bundle, "selection_identified")
    workflow = next(
        result for result in bundle.workflow_results if result.event_type == "selection_identified"
    )

    assert event.status == "dry_run"
    assert workflow.status == "blocked"
    assert workflow.side_effects_allowed is False


def test_tenant_declared_appointment_event_without_vehicle_fields() -> None:
    context = _context(_fixture("appointment_services.json"))
    lifecycle = LifecycleUpdate(
        target_stage="appointment_requested",
        reason="availability_checked",
        evidence=["tool_result:availability.check"],
    )
    bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(
            accepted=[_accepted("service_selection", "service-1")],
            lifecycle_update=lifecycle,
        ),
    )
    rendered = json.dumps(bundle.trace_payload(), sort_keys=True)

    assert "appointment_requested" in _event_types(bundle)
    assert "selection_identified" in _event_types(bundle)
    assert "product_selection" not in rendered
    assert "plan_selection" not in rendered
    assert "quote_snapshot_id" not in rendered


def test_no_keyword_trigger_without_validated_state_or_tool_data() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"))
    bundle = _bundle(
        context=context,
        state_write_result=StateWriteResult(),
        decision=_decision(),
        output=_output(context),
    )

    assert "selection_identified" not in _event_types(bundle)
    assert "plan_identified" not in _event_types(bundle)
    assert "offer_quoted" not in _event_types(bundle)


def test_business_events_appear_in_universal_turn_trace() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"))
    decision = _decision()
    output = TurnOutput(
        final_message="Mensaje final validado.",
        trace_metadata=build_trace_metadata(context=context, provider="test"),
    )
    traced = attach_universal_turn_trace(
        context=context,
        decision=decision,
        tool_results=[],
        state_write_result=StateWriteResult(
            accepted=[_accepted("product_selection", "product-1")]
        ),
        policy_warnings=[],
        output=output,
    )

    trace = traced.trace_metadata["universal_turn_trace"]

    assert trace["business_events"][0]["event_type"] == "lead_started"
    assert any(event["event_type"] == "selection_identified" for event in trace["business_events"])
    assert trace["workflow_results"][0]["status"] == "dry-run"

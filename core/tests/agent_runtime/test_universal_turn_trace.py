from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from atendia.agent_runtime import (
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    AdvisorBrainToolRequest,
    AdvisorFirstAgentProvider,
    ToolExecutionResult,
    TurnOutput,
    why_answer_from_universal_trace,
)
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    ConversationMemoryContext,
    CustomerContext,
    TenantRuntimeConfigContext,
    TurnContext,
)
from atendia.agent_runtime.state_writer import StateWriteResult
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
    tenant_domain_trace_metadata,
)
from atendia.agent_runtime.tracing import build_trace_metadata

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"


class _Brain:
    def __init__(self, decision: AdvisorBrainDecision) -> None:
        self._decision = decision

    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        del context
        return self._decision


class _ToolLayer:
    def __init__(self, *results: ToolExecutionResult) -> None:
        self._results = list(results)

    async def execute(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
    ) -> list[ToolExecutionResult]:
        del context, decision
        return list(self._results)


class _Composer:
    def __init__(self, final_message: str) -> None:
        self._final_message = final_message

    async def compose(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]],
    ) -> TurnOutput:
        trace = build_trace_metadata(
            context=context,
            provider="advisor_first_pipeline",
            extra={
                **tenant_domain_trace_metadata(context),
                "advisor_brain": decision.model_dump(mode="json"),
                "tool_results": [result.model_dump(mode="json") for result in tool_results],
                "state_writer": {
                    "accepted": state_write_result.accepted,
                    "blocked": state_write_result.blocked,
                    "needs_review": state_write_result.needs_review,
                },
                "state_writer_decisions": state_write_result.decisions,
                "state_writer_summary": {
                    **state_write_result.summary,
                    "safe_mode": context.tenant_config.safe_mode,
                },
                "invalidated_fields": state_write_result.invalidated_fields,
                "policy_warnings": policy_warnings,
            },
        )
        return TurnOutput(
            final_message=self._final_message,
            confidence=decision.confidence,
            needs_human=decision.needs_human,
            field_updates=list(state_write_result.field_updates),
            lifecycle_update=state_write_result.lifecycle_update,
            risk_flags=list(decision.risk_flags),
            trace_metadata=trace,
        )


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _tenant_config(raw: dict | None, *, safe_mode: bool = False) -> TenantRuntimeConfigContext:
    if raw is None:
        return TenantRuntimeConfigContext(safe_mode=safe_mode)
    result = load_tenant_domain_contract(raw, tenant_id=raw["tenant_id"], agent_id=raw["agent_id"])
    config = apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)
    if safe_mode:
        config = config.model_copy(update={"safe_mode": True})
    return config


def _context(
    raw: dict | None = None,
    *,
    inbound_text: str = "Me interesa avanzar.",
    memory: ConversationMemoryContext | None = None,
    safe_mode: bool = False,
) -> TurnContext:
    tenant_id = raw["tenant_id"] if raw is not None else "tenant-safe"
    agent_id = raw["agent_id"] if raw is not None else "agent-safe"
    return TurnContext(
        tenant_id=tenant_id,
        conversation_id="conversation-1",
        inbound_text=inbound_text,
        customer=CustomerContext(id="contact-1"),
        memory=memory or ConversationMemoryContext(),
        tenant_config=_tenant_config(raw, safe_mode=safe_mode),
        active_agent=ActiveAgentContext(id=agent_id),
        metadata={"turn_id": "turn-1", "agent_id": agent_id},
    )


def _decision(
    *changes: AdvisorBrainStateChange,
    response_plan: str = "Responder con datos validados.",
    required_tools: list[AdvisorBrainToolRequest] | None = None,
) -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="Cliente pide avanzar.",
        customer_goal="advance",
        conversation_goals=["advance"],
        known_facts={},
        missing_facts=[],
        next_best_action="respond",
        required_tools=required_tools or [],
        proposed_state_changes=list(changes),
        response_plan=response_plan,
        confidence=0.9,
    )


def _change(
    key: str,
    value: object,
    *,
    metadata: dict | None = None,
) -> AdvisorBrainStateChange:
    return AdvisorBrainStateChange(
        target="contact_field",
        key=key,
        value=value,
        reason="Cliente lo dijo.",
        evidence=["Me interesa avanzar."],
        confidence=0.9,
        metadata=metadata or {},
    )


def _catalog_tool(tenant_id: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name="catalog.search",
        status="succeeded",
        data={
            "tenant_id": tenant_id,
            "items": [{"id": "item-1", "tenant_id": tenant_id, "name": "R4 250 CC"}],
            "citations": [{"source_id": "catalog-1"}],
        },
        trace_metadata={"tenant_id": tenant_id, "safe_inputs": {"query": "R4"}},
    )


async def _run_provider(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    final_message: str = "Listo, tomo el dato validado.",
    tool_results: list[ToolExecutionResult] | None = None,
) -> TurnOutput:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_Brain(decision),
        tool_layer=_ToolLayer(*(tool_results or [])),
        composer=_Composer(final_message),
    )
    return await provider.generate(context)


@pytest.mark.asyncio
async def test_universal_trace_includes_identity_domain_and_raw_trace() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw)
    output = await _run_provider(
        context=context,
        decision=_decision(
            _change("MOTO", "R4 250 CC"),
            required_tools=[
                AdvisorBrainToolRequest(
                    name="catalog.search",
                    payload={"query": "R4"},
                    reason="Need tenant catalog evidence.",
                )
            ],
        ),
        tool_results=[_catalog_tool(raw["tenant_id"])],
    )

    trace = output.trace_metadata["universal_turn_trace"]

    assert trace["trace_version"] == "1.0"
    assert trace["turn_id"] == "turn-1"
    assert trace["tenant_id"] == raw["tenant_id"]
    assert trace["agent_id"] == raw["agent_id"]
    assert trace["contact_id"] == "contact-1"
    assert trace["domain"] == "vehicle_credit_sales"
    assert output.trace_metadata["advisor_brain"]["understanding"] == "Cliente pide avanzar."
    assert "universal_turn_trace" in output.trace_metadata


@pytest.mark.asyncio
async def test_universal_trace_separates_gpt_proposed_from_atendia_validation() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw)
    output = await _run_provider(
        context=context,
        decision=_decision(
            _change("MOTO", "R4 250 CC"),
            _change("quote_snapshot_id", "quote-1"),
            _change("bureau_status", "mentioned"),
        ),
        tool_results=[_catalog_tool(raw["tenant_id"])],
    )

    trace = output.trace_metadata["universal_turn_trace"]
    proposed_keys = {item["key"] for item in trace["gpt_proposed"]["state_changes"]}
    decisions = trace["atendia_validation"]["state_writer_decisions"]
    decision_statuses = {item["decision"] for item in decisions}

    assert proposed_keys == {"MOTO", "quote_snapshot_id", "bureau_status"}
    assert {"accepted", "blocked", "needs_review"}.issubset(decision_statuses)
    assert trace["state_changes"]["accepted"][0]["field"] == "product_selection"
    assert trace["state_changes"]["blocked"][0]["reason"] == "field_is_tool_only"
    assert trace["state_changes"]["needs_review"][0]["field"] == "bureau_status"


@pytest.mark.asyncio
async def test_universal_trace_maps_mandatory_tool_decisions_and_tool_results() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw)
    output = await _run_provider(
        context=context,
        decision=_decision(
            required_tools=[
                AdvisorBrainToolRequest(
                    name="catalog.search",
                    payload={"query": "R4"},
                    reason="Need tenant catalog evidence.",
                )
            ],
        ),
        tool_results=[_catalog_tool(raw["tenant_id"])],
    )

    trace = output.trace_metadata["universal_turn_trace"]
    catalog_decision = next(
        item for item in trace["mandatory_tool_decisions"] if item["tool_id"] == "catalog.search"
    )
    tool_trace = trace["tool_results"][0]

    assert catalog_decision["status"] == "executed"
    assert tool_trace["tool_id"] == "catalog.search"
    assert tool_trace["tenant_id"] == raw["tenant_id"]
    assert tool_trace["safe_inputs"] == {"query": "R4"}
    assert tool_trace["visible_text_allowed"] is False
    assert "mandatory_tool:advisor_required_tool" in tool_trace["used_for"]


@pytest.mark.asyncio
async def test_universal_trace_records_guard_block_and_final_output_authority() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw, inbound_text="Cuanto cuesta?")
    output = await _run_provider(
        context=context,
        decision=_decision(response_plan="Responder precio validado."),
        final_message="La R4 queda en $62,900 de contado.",
    )

    trace = output.trace_metadata["universal_turn_trace"]
    guard_results = {item["guard_id"]: item["result"] for item in trace["guards"]}
    quote_decision = next(
        item for item in trace["mandatory_tool_decisions"] if item["tool_id"] == "quote.resolve"
    )

    assert quote_decision["status"] == "missing"
    assert guard_results["mandatory_tool_guard"] == "blocked"
    assert guard_results["quote_safety"] == "rewrote"
    assert trace["final_output"]["final_message"] == output.final_message
    assert trace["final_output"]["source"] == "TurnOutput.final_message"
    assert trace["final_output"]["visible"] is True
    assert "$62,900" not in trace["final_output"]["final_message"]


@pytest.mark.asyncio
async def test_universal_trace_includes_invalidated_fields_when_quote_changes() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(
        raw,
        memory=ConversationMemoryContext(
            salient_facts={
                "product_selection": "Adventure 150",
                "quote_snapshot_id": "quote-old",
            }
        ),
    )
    output = await _run_provider(
        context=context,
        decision=_decision(_change("product_selection", "R4 250 CC")),
        tool_results=[_catalog_tool(raw["tenant_id"])],
    )

    trace = output.trace_metadata["universal_turn_trace"]

    assert trace["state_changes"]["invalidated_fields"][0]["field"] == "quote_snapshot_id"
    values = {item["field_key"]: item["value"] for item in trace["state_changes"]["field_updates"]}
    assert values["quote_snapshot_id"] is None


@pytest.mark.asyncio
async def test_tool_result_visible_copy_keys_are_rejected_and_never_customer_copy() -> None:
    for key in ("final_message", "message", "reply"):
        with pytest.raises(ValidationError):
            ToolExecutionResult.model_validate(
                {
                    "tool_name": "faq.lookup",
                    "status": "succeeded",
                    "data": {key: "No debe ser copia visible."},
                }
            )

    valid_tool = ToolExecutionResult(
        tool_name="faq.lookup",
        status="succeeded",
        data={"tenant_id": "tenant-safe", "policy": {"id": "faq-1"}},
    )
    context = _context()
    output = await _run_provider(
        context=context,
        decision=_decision(
            required_tools=[
                AdvisorBrainToolRequest(
                    name="faq.lookup",
                    payload={"topic": "policy"},
                    reason="Need policy fact.",
                )
            ],
        ),
        final_message="Respuesta desde TurnOutput.",
        tool_results=[valid_tool],
    )
    trace = output.trace_metadata["universal_turn_trace"]

    assert trace["final_output"]["final_message"] == "Respuesta desde TurnOutput."
    assert trace["tool_results"][0]["visible_text_allowed"] is False
    assert "final_message" not in trace["tool_results"][0]["structured_output"]


@pytest.mark.asyncio
async def test_universal_trace_records_safe_mode_in_audit() -> None:
    context = _context(safe_mode=True)
    output = await _run_provider(context=context, decision=_decision())

    trace = output.trace_metadata["universal_turn_trace"]

    assert trace["audit"]["safe_mode"] is True
    assert trace["atendia_validation"]["safe_mode"] is True


@pytest.mark.asyncio
async def test_appointment_tenant_trace_does_not_render_vehicle_fields() -> None:
    raw = _fixture("appointment_services.json")
    context = _context(raw, inbound_text="Quiero corte manana a las cinco.")
    output = await _run_provider(
        context=context,
        decision=_decision(
            _change("service_selection", "Corte"),
            _change("appointment_time", "manana 5pm"),
        ),
        tool_results=[_catalog_tool(raw["tenant_id"])],
    )

    trace = output.trace_metadata["universal_turn_trace"]
    rendered = json.dumps(trace, sort_keys=True)

    assert trace["domain"] == "appointment_services"
    assert "service_selection" in rendered
    assert "appointment_time" in rendered
    assert "product_selection" not in rendered
    assert "plan_selection" not in rendered
    assert "quote_snapshot_id" not in rendered
    assert "tenant_dinamo_fixture" not in rendered


@pytest.mark.asyncio
async def test_why_answer_helper_is_non_technical_and_omits_sensitive_values() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw, inbound_text="Cuanto cuesta?")
    output = await _run_provider(
        context=context,
        decision=_decision(response_plan="Responder precio validado."),
        final_message="La R4 queda en $62,900 de contado.",
    )

    summary = why_answer_from_universal_trace(output.trace_metadata["universal_turn_trace"])

    assert "AtendIA" in summary
    assert "$62,900" not in summary
    assert "quote.resolve" not in summary

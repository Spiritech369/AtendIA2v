from __future__ import annotations

import pytest
from pydantic import ValidationError

from atendia.agent_runtime import (
    AdvisorBrainDecision,
    AdvisorBrainToolRequest,
    MandatoryToolGuard,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)


def _context(tenant_id: str = "tenant-b") -> TurnContext:
    return TurnContext(
        tenant_id=tenant_id,
        conversation_id="conversation-1",
        inbound_text="Necesito informacion.",
    )


def _decision(
    *,
    response_plan: str = "Responder usando datos validados.",
    required_tools: list[AdvisorBrainToolRequest] | None = None,
) -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="Cliente necesita informacion sensible.",
        customer_goal="answer",
        conversation_goals=["answer"],
        known_facts={},
        missing_facts=[],
        next_best_action="answer",
        required_tools=required_tools or [],
        proposed_state_changes=[],
        response_plan=response_plan,
        confidence=0.9,
    )


def _apply_without_tools(message: str, *, response_plan: str = "Responder.") -> TurnOutput:
    result = MandatoryToolGuard().apply(
        context=_context(),
        decision=_decision(response_plan=response_plan),
        tool_results=[],
        output=TurnOutput(final_message=message, confidence=0.9),
        defer_quote_final_message=False,
    )
    return result.output


def test_price_without_quote_resolve_is_blocked() -> None:
    output = _apply_without_tools(
        "El producto queda en $12,500 con descuento.",
        response_plan="Responder precio validado.",
    )

    assert "$12,500" not in output.final_message
    assert "cotizacion" in output.final_message.casefold()
    decisions = output.trace_metadata["mandatory_tool_decisions"]
    quote_decision = next(item for item in decisions if item["tool_id"] == "quote.resolve")
    assert quote_decision["status"] == "missing"
    assert quote_decision["blocking"] is True
    assert "mandatory_tool_missing:quote.resolve" in output.risk_flags


def test_requirements_without_requirements_lookup_are_blocked() -> None:
    output = _apply_without_tools("Para avanzar manda INE y comprobante de domicilio.")

    assert "INE" not in output.final_message
    assert "requisitos vigentes" in output.final_message
    decisions = output.trace_metadata["mandatory_tool_decisions"]
    requirements_decision = next(
        item for item in decisions if item["tool_id"] == "requirements.lookup"
    )
    assert requirements_decision["status"] == "missing"
    assert requirements_decision["blocking_scopes"] == ["final_message", "workflow_event"]


def test_sensitive_policy_without_faq_or_policy_lookup_is_blocked() -> None:
    output = _apply_without_tools("Aunque estes en buro, si te podemos aprobar.")

    assert "aprobar" not in output.final_message.casefold()
    assert "politica correspondiente" in output.final_message
    decisions = output.trace_metadata["mandatory_tool_decisions"]
    policy_decision = next(item for item in decisions if item["tool_id"] == "faq.lookup")
    assert policy_decision["status"] == "missing"
    assert policy_decision["topic"] == "policy_or_faq"


def test_sensitive_policy_is_satisfied_by_policy_lookup_alias() -> None:
    result = MandatoryToolGuard().apply(
        context=_context(),
        decision=_decision(),
        tool_results=[
            ToolExecutionResult(
                tool_name="policy.lookup",
                status="succeeded",
                data={"tenant_id": "tenant-b", "policy": {"id": "approval-policy"}},
            )
        ],
        output=TurnOutput(
            final_message="Para aprobacion se revisa la politica vigente.",
            confidence=0.9,
        ),
    )

    assert result.output.final_message == "Para aprobacion se revisa la politica vigente."
    policy_decision = next(
        item
        for item in result.output.trace_metadata["mandatory_tool_decisions"]
        if item["tool_id"] == "faq.lookup"
    )
    assert policy_decision["status"] == "executed"
    assert policy_decision["matched_tools"] == ["policy.lookup"]


def test_tool_results_cannot_return_customer_visible_copy_keys() -> None:
    for key in ("final_message", "message", "reply"):
        with pytest.raises(ValidationError):
            ToolExecutionResult.model_validate(
                {
                    "tool_name": "quote.resolve",
                    "status": "succeeded",
                    "data": {key: "No va aqui."},
                }
            )

    with pytest.raises(ValidationError):
        ToolExecutionResult.model_validate(
            {
                "tool_name": "quote.resolve",
                "status": "succeeded",
                "data": {"nested": {"message": "Tampoco va aqui."}},
            }
        )


def test_cross_tenant_catalog_result_is_blocked_and_does_not_satisfy_requirement() -> None:
    decision = _decision(
        required_tools=[
            AdvisorBrainToolRequest(
                name="catalog.search",
                payload={"query": "producto"},
                reason="Need tenant catalog fact.",
                required=True,
            )
        ]
    )

    evaluation = MandatoryToolGuard().evaluate(
        context=_context("tenant-b"),
        decision=decision,
        tool_results=[
            ToolExecutionResult(
                tool_name="catalog.search",
                status="succeeded",
                data={
                    "tenant_id": "tenant-a",
                    "items": [
                        {"id": "item-1", "tenant_id": "tenant-a", "name": "Catalog item"}
                    ],
                },
            )
        ],
    )

    catalog_decision = next(
        item for item in evaluation.decisions if item.tool_id == "catalog.search"
    )
    assert catalog_decision.status == "blocked"
    assert catalog_decision.blocking is True
    assert catalog_decision.matched_tools == []
    assert catalog_decision.invalid_tool_results[0]["reason"] == "tenant_id_mismatch"
    assert catalog_decision.invalid_tool_results[0]["expected_tenant_id"] == "tenant-b"
    assert catalog_decision.invalid_tool_results[0]["actual_tenant_ids"] == ["tenant-a"]

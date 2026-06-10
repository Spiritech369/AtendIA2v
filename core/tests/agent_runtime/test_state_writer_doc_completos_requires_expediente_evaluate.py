from __future__ import annotations

from atendia.agent_runtime.schemas import AdvisorBrainDecision, ToolExecutionResult
from atendia.agent_runtime.state_writer import DeterministicStateWriter
from tests.agent_runtime.expediente_preflight_utils import field_values, turn_context


def test_state_writer_doc_completos_requires_expediente_evaluate() -> None:
    context = turn_context("ya quedo?", customer_attrs={"plan_selection": "10%"})
    decision = AdvisorBrainDecision(
        understanding="Cliente pregunta si expediente quedo completo.",
        next_best_action="evaluate_expediente",
        response_plan="Usar expediente.evaluate.",
    )
    document_check = ToolExecutionResult(
        tool_name="document.check",
        status="succeeded",
        data={
            "tenant_id": context.tenant_id,
            "classification_only": True,
            "field_updates": [
                {
                    "key": "requirements_complete",
                    "value": True,
                    "reason": "document.check must not decide completeness.",
                }
            ],
        },
        trace_metadata={"tenant_id": context.tenant_id},
    )
    expediente_evaluate = ToolExecutionResult(
        tool_name="expediente.evaluate",
        status="succeeded",
        data={
            "tenant_id": context.tenant_id,
            "field_updates": [
                {
                    "key": "requirements_complete",
                    "value": False,
                    "reason": "expediente.evaluate decided partial expediente.",
                    "evidence": ["tool_result:expediente.evaluate"],
                }
            ],
        },
        trace_metadata={"tenant_id": context.tenant_id},
    )

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=decision,
        tool_results=[document_check, expediente_evaluate],
    )

    assert field_values(result, "requirements_complete") == [False]
    assert all(update.value is not True for update in result.field_updates)

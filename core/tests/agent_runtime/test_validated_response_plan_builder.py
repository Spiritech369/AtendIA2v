from __future__ import annotations

from uuid import uuid4

from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    ConversationMemoryContext,
    CustomerContext,
    FieldUpdate,
    TenantRuntimeConfigContext,
    ToolExecutionResult,
    TurnContext,
)
from atendia.agent_runtime.state_writer import StateWriteResult
from atendia.agent_runtime.validated_response_plan import ValidatedResponsePlanBuilder


def test_validated_response_plan_builder_greeting_does_not_consume_income_slot() -> None:
    context = _context(
        "hola",
        memory=ConversationMemoryContext(metadata={"pending_slot": "income_type"}),
    )
    decision = _decision(user_act="greeting", missing_field="income_type")

    plan = ValidatedResponsePlanBuilder().build(
        context=context,
        decision=decision,
        tool_results=[],
        state_write_result=StateWriteResult(),
    )

    assert plan.user_act == "greeting"
    assert plan.pending_slot == "income_type"
    assert plan.slot_consumed is False
    assert plan.message_goal == "greet_and_resume_without_consuming_slot"
    assert plan.next_best_question == "como recibes tus ingresos"


def test_validated_response_plan_quote_uses_only_quote_facts() -> None:
    context = _context("cotizame")
    decision = _decision(user_act="question", missing_field=None)
    quote = ToolExecutionResult(
        tool_name="quote.resolve",
        status="succeeded",
        data={
            "quote_snapshot": {
                "product": {"display_name": "Producto validado"},
                "pricing": {"down_payment": 1000, "installment": 500},
            }
        },
    )

    plan = ValidatedResponsePlanBuilder().build(
        context=context,
        decision=decision,
        tool_results=[quote],
        state_write_result=StateWriteResult(),
    )

    assert plan.message_goal == "explain_validated_quote"
    assert plan.validated_facts["quote"] == quote.data
    assert plan.required_tools == ["quote.resolve"]


def test_validated_response_plan_requirements_uses_only_requirements_facts() -> None:
    context = _context("que papeles ocupo")
    decision = _decision(user_act="question", missing_field=None)
    requirements = ToolExecutionResult(
        tool_name="requirements.lookup",
        status="succeeded",
        data={"requirements": ["Identificacion", "Comprobante"]},
    )

    plan = ValidatedResponsePlanBuilder().build(
        context=context,
        decision=decision,
        tool_results=[requirements],
        state_write_result=StateWriteResult(),
    )

    assert plan.message_goal == "explain_validated_requirements"
    assert plan.validated_facts["requirements"] == requirements.data
    assert plan.required_tools == ["requirements.lookup"]


def test_document_upload_act_without_document_tool_acknowledges_future_file() -> None:
    context = _context(
        "te mando INE al rato",
        memory=ConversationMemoryContext(
            salient_facts={"requirements_checklist": ["INE vigente por ambos lados"]}
        ),
    )
    decision = _decision(user_act="document_upload", missing_field=None)

    plan = ValidatedResponsePlanBuilder().build(
        context=context,
        decision=decision,
        tool_results=[],
        state_write_result=StateWriteResult(),
    )

    assert plan.message_goal == "acknowledge_future_document_without_state_write"
    assert plan.validated_facts["requirements_checklist"] == [
        "INE vigente por ambos lados"
    ]


def test_state_writes_are_summarized_as_validated_facts() -> None:
    context = _context("tengo 2 anos")
    decision = _decision(user_act="answer_to_pending_slot", missing_field=None)
    state = StateWriteResult(
        field_updates=[
            FieldUpdate(
                field_key="employment_seniority",
                value=24,
                evidence=["tengo 2 anos"],
                confidence=0.9,
            )
        ],
        accepted=[{"field": "employment_seniority"}],
    )

    plan = ValidatedResponsePlanBuilder().build(
        context=context,
        decision=decision,
        tool_results=[],
        state_write_result=state,
    )

    assert plan.validated_facts["employment_seniority"] == 24
    assert plan.state_writes_summary["accepted_count"] == 1


def test_seniority_write_advances_to_income_slot_from_flow_policy() -> None:
    context = _context(
        "22 anos",
        tenant_config=TenantRuntimeConfigContext(
            tenant_domain_contract={
                "flow_policy": {
                    "seniority_before_income": True,
                    "seniority_slot": "employment_seniority",
                    "income_slot": "income_type",
                }
            }
        ),
    )
    decision = _decision(user_act="answer_to_pending_slot", missing_field=None)
    decision.answered_slot = "employment_seniority"
    decision.metadata["pending_slot_answered"] = "employment_seniority"
    state = StateWriteResult(
        field_updates=[
            FieldUpdate(
                field_key="employment_seniority",
                value=264,
                evidence=["22 anos"],
                confidence=0.9,
            )
        ],
        accepted=[{"field": "employment_seniority"}],
    )

    plan = ValidatedResponsePlanBuilder().build(
        context=context,
        decision=decision,
        tool_results=[],
        state_write_result=state,
    )

    assert plan.pending_slot == "income_type"
    assert plan.slot_consumed is False
    assert plan.message_goal == "ask_one_clarifying_question_for_pending_slot"
    assert plan.next_best_question == "como recibes tus ingresos"


def test_product_selection_write_advances_to_income_when_seniority_exists() -> None:
    context = _context(
        "metro",
        memory=ConversationMemoryContext(salient_facts={"employment_seniority": 10}),
        tenant_config=TenantRuntimeConfigContext(
            tenant_domain_contract={
                "flow_policy": {
                    "seniority_before_income": True,
                    "seniority_slot": "employment_seniority",
                    "income_slot": "income_type",
                }
            }
        ),
    )
    decision = _decision(user_act="answer_to_pending_slot", missing_field=None)
    decision.answered_slot = "product_selection"
    decision.metadata["pending_slot_answered"] = "product_selection"
    state = StateWriteResult(
        field_updates=[
            FieldUpdate(
                field_key="product_selection",
                value={"display_name": "Producto validado"},
                evidence=["metro"],
                confidence=1.0,
            )
        ],
        accepted=[{"field": "product_selection"}],
    )

    plan = ValidatedResponsePlanBuilder().build(
        context=context,
        decision=decision,
        tool_results=[],
        state_write_result=state,
    )

    assert plan.pending_slot == "income_type"
    assert plan.slot_consumed is False
    assert plan.message_goal == "ask_one_clarifying_question_for_pending_slot"
    assert plan.next_best_question == "como recibes tus ingresos"


def _context(
    inbound: str,
    *,
    memory: ConversationMemoryContext | None = None,
    tenant_config: TenantRuntimeConfigContext | None = None,
) -> TurnContext:
    return TurnContext(
        tenant_id=str(uuid4()),
        conversation_id=str(uuid4()),
        inbound_text=inbound,
        customer=CustomerContext(id=str(uuid4())),
        memory=memory or ConversationMemoryContext(),
        tenant_config=tenant_config or TenantRuntimeConfigContext(),
    )


def _decision(*, user_act: str, missing_field: str | None) -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="Entendimiento estructurado.",
        customer_goal="credit_quote",
        next_best_action="ask_clarification" if missing_field else "respond",
        response_plan="Responder con facts validados.",
        confidence=0.85,
        latest_customer_act=user_act,
        question_slot=missing_field,
        metadata={
            "semantic_interpreter": True,
            "user_act": user_act,
            "missing_field": missing_field,
        },
    )

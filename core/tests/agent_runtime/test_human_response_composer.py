from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.human_response_composer import (
    HumanResponseCandidate,
    HumanResponseComposer,
    _human_response_system_prompt,
    human_response_json_schema,
    validate_human_response_candidate,
)
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    ConversationMemoryContext,
    CustomerContext,
    FieldUpdate,
    TenantRuntimeConfigContext,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult
from atendia.agent_runtime.validated_response_plan import (
    ValidatedResponsePlan,
)


@pytest.mark.asyncio
async def test_human_response_composer_greeting_no_template_income_copy() -> None:
    composer = HumanResponseComposer(
        provider=_FakeHumanProvider(
            "Hola, claro. Seguimos cuando quieras; para avanzar solo me falta "
            "saber como recibes tus ingresos."
        )
    )
    output = await composer.compose(
        context=_context(
            "hola",
            memory=ConversationMemoryContext(metadata={"pending_slot": "income_type"}),
        ),
        decision=_decision(user_act="greeting", missing_field="income_type"),
        tool_results=[],
        state_write_result=StateWriteResult(),
        policy_warnings=[],
    )

    assert output.final_message.startswith("Hola")
    assert "Si se puede revisar" not in output.final_message
    assert "Dime que dato quieres revisar" not in output.final_message
    plan = output.trace_metadata["validated_response_plan"]
    assert plan["message_goal"] == "greet_and_resume_without_consuming_slot"
    assert plan["slot_consumed"] is False


@pytest.mark.asyncio
async def test_human_response_composer_frustration_explains_pending_without_generic_copy() -> None:
    composer = HumanResponseComposer(
        provider=_FakeHumanProvider(
            "Tienes razon, vamos por partes. Aun me falta confirmar como compruebas tus ingresos."
        )
    )
    output = await composer.compose(
        context=_context(
            "ya te dije",
            memory=ConversationMemoryContext(metadata={"pending_slot": "income_type"}),
        ),
        decision=_decision(user_act="frustration", missing_field="income_type"),
        tool_results=[],
        state_write_result=StateWriteResult(),
        policy_warnings=[],
    )

    assert "Tienes razon" in output.final_message
    assert "reviso el contexto" not in output.final_message
    assert "Si se puede revisar" not in output.final_message
    assert output.trace_metadata["validated_response_plan"]["message_goal"] == (
        "acknowledge_confusion_and_explain_pending_slot"
    )


@pytest.mark.asyncio
async def test_human_response_composer_records_provider_token_usage() -> None:
    provider = _FakeHumanProvider("Va, lo revisamos con los datos validados.")
    provider.last_usage = {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}
    composer = HumanResponseComposer(provider=provider)

    output = await composer.compose(
        context=_context("ok"),
        decision=_decision(user_act="confirmation", missing_field=None),
        tool_results=[],
        state_write_result=StateWriteResult(),
        policy_warnings=[],
    )

    assert output.trace_metadata["model_usage"] == {
        "input_tokens": 12,
        "output_tokens": 8,
        "total_tokens": 20,
    }


def test_policy_blocks_generic_progress_copy_from_human_composer() -> None:
    plan = _plan()
    candidate = HumanResponseCandidate(
        final_message_candidate="Tomo tu mensaje y reviso el contexto.",
        language="es",
    )

    issues = validate_human_response_candidate(plan, candidate)

    assert "forbidden_phrase" in {issue["code"] for issue in issues}


def test_policy_blocks_internal_state_writer_reason_from_human_composer() -> None:
    plan = _plan()
    candidate = HumanResponseCandidate(
        final_message_candidate=(
            "Parece que no puedo registrar tu antigüedad laboral porque "
            "el campo no está visible."
        ),
        language="es",
    )

    issues = validate_human_response_candidate(plan, candidate)

    assert "internal_state_writer_reason_visible" in {issue["code"] for issue in issues}


def test_policy_blocks_question_for_wrong_pending_slot() -> None:
    plan = _plan()
    plan.pending_slot = "product_selection"
    plan.next_best_question = "que modelo quieres revisar"
    candidate = HumanResponseCandidate(
        final_message_candidate="Para continuar, dime como recibes tus ingresos.",
        language="es",
    )

    issues = validate_human_response_candidate(plan, candidate)

    assert "wrong_pending_slot_question" in {issue["code"] for issue in issues}


def test_policy_allows_question_for_expected_pending_slot() -> None:
    plan = _plan()
    plan.pending_slot = "product_selection"
    plan.next_best_question = "que modelo quieres revisar"
    candidate = HumanResponseCandidate(
        final_message_candidate="Claro, que modelo quieres revisar?",
        language="es",
    )

    issues = validate_human_response_candidate(plan, candidate)

    assert "wrong_pending_slot_question" not in {issue["code"] for issue in issues}


def test_policy_blocks_missing_pending_slot_question() -> None:
    plan = _plan()
    plan.pending_slot = "income_type"
    plan.message_goal = "ask_one_clarifying_question_for_pending_slot"
    plan.next_best_question = "como recibes tus ingresos"
    candidate = HumanResponseCandidate(
        final_message_candidate=(
            "He actualizado tu antiguedad laboral. Si necesitas mas informacion, aqui estoy."
        ),
        language="es",
    )

    issues = validate_human_response_candidate(plan, candidate)

    assert {issue["code"] for issue in issues} & {
        "missing_pending_slot_question",
        "wrong_pending_slot_question",
    }


@pytest.mark.asyncio
async def test_human_response_composer_repairs_wrong_slot_question_to_plan_question() -> None:
    composer = HumanResponseComposer(
        provider=_FakeHumanProvider("Para continuar, dime como recibes tus ingresos.")
    )

    output = await composer.compose(
        context=_context("me pagan por transferencia"),
        decision=_decision(user_act="answer_to_pending_slot", missing_field="product_selection"),
        tool_results=[],
        state_write_result=StateWriteResult(),
        policy_warnings=[],
    )

    assert output.final_message == "que modelo de moto quieres revisar?"
    assert output.needs_human is False
    assert "slot_question_repaired" in output.risk_flags
    assert output.trace_metadata["validated_response_plan"]["pending_slot"] == (
        "product_selection"
    )


@pytest.mark.asyncio
async def test_human_response_composer_repairs_slot_update_ack_to_next_question() -> None:
    composer = HumanResponseComposer(
        provider=_FakeHumanProvider(
            "He actualizado tu antiguedad laboral. Si necesitas mas informacion, aqui estoy."
        )
    )
    decision = _decision(user_act="answer_to_pending_slot", missing_field=None)
    decision.answered_slot = "employment_seniority"
    decision.metadata["pending_slot_answered"] = "employment_seniority"

    output = await composer.compose(
        context=_context(
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
        ),
        decision=decision,
        tool_results=[],
        state_write_result=StateWriteResult(
            field_updates=[
                FieldUpdate(
                    field_key="employment_seniority",
                    value=264,
                    evidence=["22 anos"],
                    confidence=0.9,
                )
            ],
            accepted=[{"field": "employment_seniority"}],
        ),
        policy_warnings=[],
    )

    assert output.final_message == "como recibes tus ingresos?"
    assert "slot_question_repaired" in output.risk_flags
    assert output.trace_metadata["validated_response_plan"]["pending_slot"] == "income_type"


@pytest.mark.asyncio
async def test_human_response_composer_repairs_generic_close_to_next_question() -> None:
    composer = HumanResponseComposer(
        provider=_FakeHumanProvider(
            "Has seleccionado el producto. Si necesitas mas informacion, aqui estoy."
        )
    )
    decision = _decision(user_act="answer_to_pending_slot", missing_field=None)
    decision.answered_slot = "product_selection"
    decision.metadata["pending_slot_answered"] = "product_selection"

    output = await composer.compose(
        context=_context(
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
        ),
        decision=decision,
        tool_results=[],
        state_write_result=StateWriteResult(
            field_updates=[
                FieldUpdate(
                    field_key="product_selection",
                    value={"display_name": "Producto validado"},
                    evidence=["metro"],
                    confidence=1.0,
                )
            ],
            accepted=[{"field": "product_selection"}],
        ),
        policy_warnings=[],
    )

    assert output.final_message == "como recibes tus ingresos?"
    assert output.needs_human is False
    assert "slot_question_repaired" in output.risk_flags


@pytest.mark.asyncio
async def test_human_response_composer_repairs_generic_copy_to_business_tax_question() -> None:
    composer = HumanResponseComposer(
        provider=_FakeHumanProvider("Si tienes otra consulta, aqui estoy.")
    )

    output = await composer.compose(
        context=_context("Esta muy caro"),
        decision=_decision(user_act="unknown", missing_field="business_tax_status"),
        tool_results=[
            ToolExecutionResult(
                tool_name="credit_plan.resolve",
                status="succeeded",
                data={
                    "needs_clarification": True,
                    "pending_slot": "business_tax_status",
                    "clarification": {
                        "question": "si tienes SAT/RIF o si seria sin comprobantes"
                    },
                },
            )
        ],
        state_write_result=StateWriteResult(),
        policy_warnings=[],
    )

    assert output.final_message == "si tienes SAT/RIF o si seria sin comprobantes?"
    assert output.needs_human is False
    assert "slot_question_repaired" in output.risk_flags


@pytest.mark.asyncio
async def test_human_response_composer_provider_failure_repairs_to_safe_pending_question() -> None:
    composer = HumanResponseComposer(provider=_FailingHumanProvider())

    output = await composer.compose(
        context=_context("Dime"),
        decision=_decision(user_act="unknown", missing_field="business_tax_status"),
        tool_results=[
            ToolExecutionResult(
                tool_name="credit_plan.resolve",
                status="succeeded",
                data={
                    "needs_clarification": True,
                    "pending_slot": "business_tax_status",
                    "clarification": {
                        "question": "si tienes SAT/RIF o si seria sin comprobantes"
                    },
                },
            )
        ],
        state_write_result=StateWriteResult(),
        policy_warnings=[],
    )

    assert output.final_message == "si tienes SAT/RIF o si seria sin comprobantes?"
    assert output.needs_human is False
    assert "human_response_provider_failed_repaired" in output.risk_flags
    assert "persona del equipo" not in output.final_message


def test_policy_blocks_fact_not_in_validated_facts() -> None:
    plan = _plan(validated_facts={})
    candidate = HumanResponseCandidate(
        final_message_candidate="Queda en $1,000 de enganche.",
        language="es",
    )

    issues = validate_human_response_candidate(plan, candidate)

    assert "unsupported_price_fact" in {issue["code"] for issue in issues}


def test_policy_allows_requirements_from_validated_checklist_state() -> None:
    plan = _plan(validated_facts={"requirements_checklist": ["INE", "comprobante"]})
    candidate = HumanResponseCandidate(
        final_message_candidate="Me falta tu INE y comprobante de domicilio.",
        language="es",
    )

    issues = validate_human_response_candidate(plan, candidate)

    assert "unsupported_requirements_fact" not in {issue["code"] for issue in issues}


def test_human_response_prompt_avoids_cash_price_for_credit_quote() -> None:
    prompt = _human_response_system_prompt()

    assert "For credit quote goals" in prompt
    assert "Avoid cash/list price" in prompt


def test_human_response_schema_is_strict() -> None:
    schema = human_response_json_schema()

    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False


def test_no_dinamo_hardcode_in_human_composer() -> None:
    source = Path("atendia/agent_runtime/human_response_composer.py").read_text(
        encoding="utf-8"
    )

    assert "Dinamo" not in source
    assert "moto" not in source.casefold()
    assert "nomina tarjeta" not in source.casefold()


@pytest.mark.asyncio
async def test_semantic_runtime_uses_human_composer_not_structured_template() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_StaticBrain(_decision(user_act="greeting", missing_field="income_type")),
        tool_layer=_NoopToolLayer(),
        composer=_ExplodingStructuredComposer(),
        human_response_composer=HumanResponseComposer(
            provider=_FakeHumanProvider(
                "Hola, aqui sigo. Avanzamos cuando me digas el dato pendiente."
            )
        ),
    )

    output = await provider.generate(
        _context(
            "hola",
            memory=ConversationMemoryContext(metadata={"pending_slot": "income_type"}),
        )
    )

    assert output.final_message == "Hola, aqui sigo. Avanzamos cuando me digas el dato pendiente."
    assert output.trace_metadata["universal_turn_trace"]["validated_response_plan"][
        "message_goal"
    ] == "greet_and_resume_without_consuming_slot"


@pytest.mark.asyncio
async def test_legacy_structured_composer_not_used_for_product_agent_semantic_path() -> None:
    await test_semantic_runtime_uses_human_composer_not_structured_template()


class _FakeHumanProvider:
    def __init__(self, message: str) -> None:
        self.message = message
        self.last_usage: dict[str, int] = {}

    async def compose(self, plan: ValidatedResponsePlan) -> HumanResponseCandidate:
        return HumanResponseCandidate(
            final_message_candidate=self.message,
            language="es",
            reasoning_summary_safe=f"goal={plan.message_goal}",
            used_facts=list(plan.validated_facts),
            risk_flags=[],
        )


class _FailingHumanProvider:
    async def compose(self, plan: ValidatedResponsePlan) -> HumanResponseCandidate:
        del plan
        raise RuntimeError("composer_provider_unavailable")


class _StaticBrain:
    def __init__(self, decision: AdvisorBrainDecision) -> None:
        self.decision = decision

    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        del context
        return self.decision


class _NoopToolLayer:
    async def execute(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
    ) -> list[ToolExecutionResult]:
        del context, decision
        return []


class _ExplodingStructuredComposer:
    async def compose(self, **kwargs: object) -> TurnOutput:
        del kwargs
        raise AssertionError("StructuredRuntimeComposer must not compose semantic path")


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
        understanding="ChatGPT interpreto el turno.",
        customer_goal="credit_quote",
        next_best_action="ask_clarification" if missing_field else "respond",
        response_plan="Responder como asesor con facts validados.",
        confidence=0.86,
        latest_customer_act=user_act,
        question_slot=missing_field,
        metadata={
            "semantic_interpreter": True,
            "user_act": user_act,
            "missing_field": missing_field,
        },
    )


def _plan(validated_facts: dict[str, object] | None = None) -> ValidatedResponsePlan:
    return ValidatedResponsePlan(
        tenant_id=str(uuid4()),
        conversation_id=str(uuid4()),
        user_act="greeting",
        intent="credit_quote",
        pending_slot="income_type",
        slot_consumed=False,
        message_goal="greet_and_resume_without_consuming_slot",
        validated_facts=validated_facts or {},
        next_best_question="como recibes tus ingresos",
    )

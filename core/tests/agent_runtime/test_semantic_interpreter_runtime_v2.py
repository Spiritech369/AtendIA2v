from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.human_response_composer import (
    HumanResponseCandidate,
    HumanResponseComposer,
)
from atendia.agent_runtime.policy_validator import PolicyValidationError, PolicyValidator
from atendia.agent_runtime.schemas import (
    ContactFieldDefinitionContext,
    ConversationMemoryContext,
    CustomerContext,
    KnowledgeCitation,
    MessageContext,
    TenantRuntimeConfigContext,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.semantic_interpreter import (
    MockSemanticInterpreterProvider,
    SemanticAdvisorBrain,
    SemanticInterpretation,
    _clean_missing_field,
    _is_actionable_catalog_query,
    build_semantic_interpreter_payload,
)
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"
DINAMO_TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
DINAMO_AGENT_ID = UUID("c169deec-226d-55b7-bd07-270f339e75a6")


def test_context_payload_gives_chatgpt_required_semantic_context() -> None:
    context = _turn_context(
        "?",
        messages=[
            MessageContext(role="customer", text=f"mensaje {idx}")
            for idx in range(25)
        ],
        memory=ConversationMemoryContext(
            salient_facts={"product_selection": "Skeleton 400 CC"},
            last_pending_question="¿Cómo recibes tus ingresos?",
            metadata={"pending_slot": "income_type"},
        ),
        knowledge=[
            KnowledgeCitation(
                source_id="requirements",
                title="Requisitos crédito",
                snippet="No inventar requisitos.",
                score=0.9,
            )
        ],
    )

    payload = build_semantic_interpreter_payload(context)

    assert len(payload["last_20_messages"]) == 20
    assert payload["last_20_messages"][0]["text"] == "mensaje 5"
    assert payload["validated_contact_state"]["salient_facts"] == {
        "product_selection": "Skeleton 400 CC"
    }
    assert payload["last_bot_question"] == "¿Cómo recibes tus ingresos?"
    assert payload["pending_slot"] == "income_type"
    assert payload["knowledge"][0]["source_id"] == "requirements"
    assert {
        "catalog.search",
        "requirements.lookup",
        "quote.resolve",
        "faq.lookup",
    }.issubset(set(payload["tools_available"]))
    assert payload["hard_data_restrictions"]["quote"] == "Prices/payments require quote.resolve."


def test_runtime_v2_no_longer_contains_vehicle_credit_keyword_router() -> None:
    source = Path("atendia/agent_runtime/advisor_pipeline.py").read_text(encoding="utf-8")

    assert "_vehicle_credit_sales_decision" not in source
    assert "_income_proof_from_text" not in source
    assert "_vehicle_product_candidate" not in source
    assert "_deterministic_final_message" not in source


@pytest.mark.asyncio
@pytest.mark.parametrize("inbound", ["hola", "Info porfavor"])
async def test_credit_new_lead_asks_employment_seniority_before_income(inbound: str) -> None:
    output = await _run_semantic_turn(
        inbound,
        {
            "intent": "credit_info",
            "user_act": "greeting" if inbound == "hola" else "question",
            "semantic_understanding": "Cliente abre una conversacion de credito.",
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [],
            "response_plan": "Pedir el primer dato de filtro del flujo.",
            "confidence": 0.86,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    metadata = output.trace_metadata["advisor_brain"]
    assert metadata["missing_facts"] == ["employment_seniority"]
    assert metadata["question_slot"] == "employment_seniority"
    assert "tiempo llevas trabajando" in output.final_message
    assert "ingresos" not in output.final_message.casefold()


@pytest.mark.asyncio
async def test_greeting_with_no_seniority_does_not_ask_income() -> None:
    output = await _run_semantic_turn(
        "hola",
        {
            "intent": "credit_info",
            "user_act": "greeting",
            "semantic_understanding": "Saludo inicial sin datos validados.",
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [],
            "response_plan": "Continuar con el primer filtro del flujo.",
            "confidence": 0.8,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    assert "ingresos" not in output.final_message.casefold()
    assert "tiempo llevas trabajando" in output.final_message


@pytest.mark.asyncio
async def test_pending_employment_seniority_consumed_before_income() -> None:
    output = await _run_semantic_turn(
        "tengo 2 años",
        {
            "intent": "answer_pending_slot",
            "user_act": "answer_to_pending_slot",
            "pending_slot_answered": "employment_seniority",
            "semantic_understanding": "Cliente responde antiguedad laboral.",
            "proposed_fields": {"employment_seniority": 24},
            "missing_field": "income_type",
            "required_tools": [],
            "response_plan": "Guardar antiguedad y pedir tipo de ingreso.",
            "confidence": 0.92,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Cuanto tiempo llevas trabajando?",
            metadata={"pending_slot": "employment_seniority"},
        ),
    )

    assert _field_values(output, "employment_seniority") == [24]
    assert output.trace_metadata["advisor_brain"]["answered_slot"] == "employment_seniority"
    assert output.trace_metadata["advisor_brain"]["missing_facts"] == ["income_type"]


@pytest.mark.asyncio
async def test_income_after_seniority_runs_credit_plan_resolve() -> None:
    output = await _run_semantic_turn(
        "Me pagan por transferencia",
        {
            "intent": "answer_pending_slot",
            "user_act": "answer_to_pending_slot",
            "pending_slot_answered": "income_type",
            "semantic_understanding": "Cliente indica metodo de ingreso por transferencia.",
            "income": {
                "present": True,
                "candidate": "nomina_tarjeta",
                "evidence": "Me pagan por transferencia",
                "confidence": 0.9,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": None,
            "required_tools": [],
            "response_plan": "Validar plan con requisitos tenant-aware.",
            "confidence": 0.9,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            salient_facts={"employment_seniority": 24},
            last_pending_question="Como recibes tus ingresos?",
            metadata={"pending_slot": "income_type"},
        ),
    )

    tool_results = output.trace_metadata["universal_turn_trace"]["tool_results"]
    assert [tool["tool_id"] for tool in tool_results] == ["credit_plan.resolve"]
    assert [tool["status"] for tool in tool_results] == ["succeeded"]
    assert _field_values(output, "plan_selection") == ["10%"]
    assert _field_values(output, "down_payment_percent") == [10]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inbound", "interpretation", "expected_phrase"),
    [
        (
            "la quiero para trabajo",
            {
                "intent": "recommend_by_use",
                "semantic_understanding": "El cliente habla del uso de la moto, no de ingresos.",
                "proposed_fields": {},
                "missing_field": None,
                "required_tools": [],
                "final_message_draft": (
                    "Va, la tomo como uso de trabajo. Te puedo revisar opciones "
                    "para ese uso."
                ),
                "confidence": 0.86,
                "needs_human": False,
                "risk_flags": [],
            },
            "uso de trabajo",
        ),
        (
            "sí trabajo",
            {
                "intent": "credit_quote",
                "semantic_understanding": (
                    "El cliente confirma actividad laboral, pero no método de ingreso."
                ),
                "proposed_fields": {},
                "missing_field": "income_type",
                "required_tools": [],
                "final_message_draft": (
                    "Va, sí trabajas. Para darte el plan correcto dime cómo te "
                    "pagan: ¿en tarjeta, con recibos o por fuera?"
                ),
                "confidence": 0.8,
                "needs_human": False,
                "risk_flags": [],
            },
            "cómo te pagan",
        ),
        (
            "trabajo de guardia",
            {
                "intent": "credit_quote",
                "semantic_understanding": (
                    "Puede ser Guardia de Seguridad, pero falta confirmación contextual."
                ),
                "income": {
                    "present": True,
                    "candidate": "guardia_seguridad",
                    "evidence": "trabajo de guardia",
                    "confidence": 0.74,
                    "needs_clarification": True,
                },
                "proposed_fields": {},
                "missing_field": "income_type_confirmation",
                "required_tools": [],
                "final_message_draft": (
                    "Puede aplicar como Guardia de Seguridad. ¿Tu empleo es de "
                    "guardia de seguridad privada?"
                ),
                "confidence": 0.74,
                "needs_human": False,
                "risk_flags": [],
            },
            "guardia de seguridad",
        ),
        (
            "trabajo por mi cuenta",
            {
                "intent": "credit_quote",
                "semantic_understanding": (
                    "Trabaja por cuenta propia; falta saber si comprueba con "
                    "SAT/RIF o sin comprobantes."
                ),
                "income": {
                    "present": True,
                    "candidate": "unknown",
                    "evidence": "trabajo por mi cuenta",
                    "confidence": 0.83,
                    "needs_clarification": True,
                },
                "proposed_fields": {},
                "missing_field": "income_type",
                "required_tools": [],
                "final_message_draft": (
                    "Va. Si trabajas por tu cuenta, ¿tienes SAT/RIF para "
                    "comprobar o sería sin comprobantes?"
                ),
                "confidence": 0.83,
                "needs_human": False,
                "risk_flags": [],
            },
            "SAT/RIF",
        ),
        (
            "la quiero para trabajar",
            {
                "intent": "recommend_by_use",
                "semantic_understanding": (
                    "El cliente expresa uso de moto para trabajar, no ingreso."
                ),
                "proposed_fields": {},
                "missing_field": None,
                "required_tools": [],
                "final_message_draft": (
                    "Claro, lo tomo como uso de la moto para trabajar. Te reviso "
                    "opciones adecuadas para ese uso."
                ),
                "confidence": 0.85,
                "needs_human": False,
                "risk_flags": [],
            },
            "uso de la moto",
        ),
    ],
)
async def test_ambiguous_trabajo_signals_do_not_write_income_or_plan(
    inbound: str,
    interpretation: dict,
    expected_phrase: str,
) -> None:
    del expected_phrase
    output = await _run_semantic_turn(inbound, interpretation)

    assert _field_values(output, "plan_selection") == []
    assert _field_values(output, "down_payment_percent") == []
    assert _field_values(output, "requirements_checklist") == []
    trace = output.trace_metadata["universal_turn_trace"]
    expected_missing = interpretation["missing_field"]
    income = interpretation.get("income")
    if (
        isinstance(income, dict)
        and income.get("needs_clarification")
        and income.get("candidate") in {"unknown", "negocio_sat"}
    ):
        expected_missing = "business_tax_status"
    assert trace["gpt_proposed"]["metadata"]["missing_field"] == expected_missing
    assert trace["state_changes"]["summary"]["accepted_count"] == 0


@pytest.mark.asyncio
async def test_work_seniority_writes_seniority_not_income_plan() -> None:
    output = await _run_semantic_turn(
        "tengo 2 años trabajando",
        {
            "intent": "credit_quote",
            "semantic_understanding": "El cliente respondió antigüedad laboral.",
            "proposed_fields": {"employment_seniority": 24},
            "missing_field": None,
            "required_tools": [],
            "final_message_draft": (
                "Perfecto, tomo tus 2 años de antigüedad. Ahora dime cómo "
                "recibes tus ingresos."
            ),
            "confidence": 0.91,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    assert _field_values(output, "employment_seniority") == [24]
    assert _field_values(output, "plan_selection") == []
    assert _field_values(output, "down_payment_percent") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inbound", "candidate", "expected_plan", "expected_down_payment"),
    [
        ("me pagan por tarjeta", "nomina_tarjeta", "10%", 10),
        ("me depositan en tarjeta", "nomina_tarjeta", "10%", 10),
        ("me pagan por fuera", "sin_comprobantes", "20%", 20),
    ],
)
async def test_income_type_is_validated_by_credit_plan_before_state_write(
    inbound: str,
    candidate: str,
    expected_plan: str,
    expected_down_payment: int,
) -> None:
    output = await _run_semantic_turn(
        inbound,
        {
            "intent": "credit_quote",
            "semantic_understanding": (
                "ChatGPT entendió método de ingreso y pidió validación estructurada."
            ),
            "pending_slot_answered": "income_type",
            "income": {
                "present": True,
                "candidate": candidate,
                "evidence": inbound,
                "confidence": 0.93,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": None,
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {"income_candidate": candidate, "evidence": inbound},
                    "reason": "Validar ingreso contra planes del tenant.",
                    "evidence": [inbound],
                }
            ],
            "final_message_draft": (
                "Perfecto, con eso valido tu plan y te digo los requisitos correctos."
            ),
            "confidence": 0.93,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    assert _field_values(output, "plan_selection") == [expected_plan]
    assert _field_values(output, "down_payment_percent") == [expected_down_payment]
    tool = output.trace_metadata["universal_turn_trace"]["tool_results"][0]
    assert tool["tool_id"] == "credit_plan.resolve"
    assert tool["status"] == "succeeded"
    assert "state_write_validation" in tool["used_for"]


@pytest.mark.asyncio
async def test_pending_income_slot_forces_credit_plan_resolve_with_raw_answer() -> None:
    output = await _run_semantic_turn(
        "me pagan por tarjeta",
        {
            "intent": "answer_pending_slot",
            "user_act": "answer_to_pending_slot",
            "pending_slot_answered": "income_type",
            "semantic_understanding": "El cliente esta contestando como recibe ingresos.",
            "income": {
                "present": True,
                "candidate": "unknown",
                "evidence": "me pagan por tarjeta",
                "confidence": 0.72,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": None,
            "required_tools": [],
            "response_plan": "Resolver ingreso desde el slot pendiente.",
            "ambiguity_reason": None,
            "confidence": 0.72,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Si se puede revisar; dime como recibes tus ingresos.",
            metadata={"pending_slot": "income_type"},
        ),
    )

    assert _field_values(output, "plan_selection") == ["10%"]
    assert _field_values(output, "down_payment_percent") == [10]
    tool = output.trace_metadata["universal_turn_trace"]["tool_results"][0]
    assert tool["tool_id"] == "credit_plan.resolve"
    assert tool["status"] == "succeeded"
    assert tool["structured_output"]["raw_answer"] == "me pagan por tarjeta"
    assert tool["structured_output"]["pending_slot"] == "income_type"


@pytest.mark.asyncio
async def test_seniority_answer_drops_credit_plan_required_tool() -> None:
    output = await _run_semantic_turn(
        "15 meses",
        {
            "intent": "answer_pending_slot",
            "user_act": "answer_to_pending_slot",
            "pending_slot_answered": "employment_seniority",
            "semantic_understanding": "Cliente responde antiguedad.",
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": False,
            },
            "proposed_fields": {"employment_seniority": 15},
            "missing_field": "income_type",
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {"raw_answer": "15 meses", "pending_slot": "income_type"},
                    "reason": "Bad model request from prior context.",
                    "evidence": ["15 meses"],
                }
            ],
            "response_plan": "Guardar antiguedad y pedir ingreso.",
            "ambiguity_reason": None,
            "confidence": 0.9,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Cuanto tiempo llevas trabajando?",
            metadata={"pending_slot": "employment_seniority"},
        ),
    )

    tool_results = output.trace_metadata["universal_turn_trace"]["tool_results"]
    assert not any(item["tool_id"] == "credit_plan.resolve" for item in tool_results)
    assert _field_values(output, "employment_seniority") == [15]
    assert output.trace_metadata["universal_turn_trace"]["validated_response_plan"][
        "pending_slot"
    ] == "income_type"


@pytest.mark.asyncio
async def test_explicit_seniority_duration_overrides_pending_income_slot() -> None:
    output = await _run_semantic_turn(
        "tengo 10 meses",
        {
            "intent": "answer_pending_slot",
            "user_act": "answer_to_pending_slot",
            "pending_slot_answered": "income_type",
            "semantic_understanding": "Cliente da una duracion laboral, no un ingreso.",
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {"raw_answer": "tengo 10 meses", "pending_slot": "income_type"},
                    "reason": "Bad model request from prior context.",
                    "evidence": ["tengo 10 meses"],
                }
            ],
            "response_plan": "Corregir antiguedad y luego pedir ingreso.",
            "ambiguity_reason": None,
            "confidence": 0.82,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Como recibes tus ingresos?",
            metadata={"pending_slot": "income_type"},
            salient_facts={"employment_seniority": 15},
        ),
    )

    tool_results = output.trace_metadata["universal_turn_trace"]["tool_results"]
    assert not any(item["tool_id"] == "credit_plan.resolve" for item in tool_results)
    assert _field_values(output, "employment_seniority") == [10]
    trace = output.trace_metadata["universal_turn_trace"]
    assert output.trace_metadata["advisor_brain"]["answered_slot"] == "employment_seniority"
    assert trace["validated_response_plan"]["pending_slot"] == "income_type"


@pytest.mark.asyncio
async def test_frustration_does_not_resolve_income_from_hallucinated_candidate() -> None:
    output = await _run_semantic_turn(
        "ya te dije no?",
        {
            "intent": "answer_pending_slot",
            "user_act": "frustration",
            "pending_slot_answered": None,
            "semantic_understanding": "El cliente esta molesto y no contesta el ingreso.",
            "income": {
                "present": True,
                "candidate": "nomina_tarjeta",
                "evidence": "nomina_tarjeta",
                "confidence": 0.4,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {
                        "income_candidate": "nomina_tarjeta",
                        "evidence": "nomina_tarjeta",
                    },
                    "reason": "Hypothesis must not be treated as evidence.",
                    "evidence": [],
                }
            ],
            "response_plan": "Aclarar el pendiente sin resolver plan.",
            "ambiguity_reason": "No hay evidencia textual de ingreso.",
            "confidence": 0.4,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="como recibes tus ingresos?",
            metadata={"pending_slot": "income_type"},
        ),
    )

    assert _field_values(output, "plan_selection") == []
    assert _field_values(output, "down_payment_percent") == []
    tool_results = output.trace_metadata["universal_turn_trace"]["tool_results"]
    assert not any(item["tool_id"] == "credit_plan.resolve" for item in tool_results)
    plan = output.trace_metadata["universal_turn_trace"]["validated_response_plan"]
    assert plan["pending_slot"] == "income_type"
    assert plan["message_goal"] == "acknowledge_confusion_and_explain_pending_slot"


@pytest.mark.asyncio
async def test_generic_credit_request_does_not_require_credit_plan_without_income() -> None:
    output = await _run_semantic_turn(
        "Hola, quiero informacion del credito",
        {
            "intent": "credit_quote",
            "pending_slot_answered": None,
            "semantic_understanding": "Cliente pide informacion general del credito.",
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": True,
            },
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {"query": "credito"},
                    "reason": "El modelo pidio una tool sin ingreso concreto.",
                    "evidence": ["credito"],
                }
            ],
            "response_plan": "Preguntar como recibe ingresos antes de validar plan.",
            "ambiguity_reason": "No hay evidencia de ingreso.",
            "confidence": 0.74,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    trace = output.trace_metadata["universal_turn_trace"]
    assert trace["tool_results"] == []
    assert "tiempo llevas trabajando" in output.final_message
    assert "ingresos" not in output.final_message.casefold()
    assert output.trace_metadata["policy_warnings"] == []


@pytest.mark.asyncio
async def test_pending_income_slot_hello_does_not_force_required_tools_from_old_context() -> None:
    output = await _run_semantic_turn(
        "Hola\nHola",
        {
            "intent": "ask_clarification",
            "user_act": "greeting",
            "pending_slot_answered": None,
            "semantic_understanding": (
                "El cliente sigue interesado en Skeleton y menciono buro antes, "
                "pero en este turno solo saludo."
            ),
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": True,
            },
            "proposed_fields": {"bureau_status": "buro"},
            "missing_field": "income_type",
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {
                        "raw_answer": "Hola\nHola",
                        "pending_slot": "income_type",
                        "last_bot_question": "Como recibes tus ingresos?",
                    },
                    "reason": "Customer is answering the pending income_type slot.",
                    "evidence": ["Hola\nHola"],
                },
                {
                    "name": "faq.lookup",
                    "input": {"query": "buro"},
                    "reason": "Old context mentioned buro.",
                    "evidence": [],
                },
            ],
            "response_plan": "Retomar el pendiente real sin validar datos duros.",
            "ambiguity_reason": "El saludo no contesta el pending slot.",
            "confidence": 0.74,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Si se puede revisar; dime como recibes tus ingresos.",
            metadata={"pending_slot": "income_type"},
        ),
    )

    trace = output.trace_metadata["universal_turn_trace"]
    assert trace["tool_results"] == []
    assert output.trace_metadata["policy_warnings"] == []
    assert output.final_message == "Hola, claro. Que te gustaria revisar?"
    assert "plan correcto" not in output.final_message
    assert "ingresos" not in output.final_message
    assert _field_values(output, "plan_selection") == []
    assert _field_values(output, "down_payment_percent") == []


@pytest.mark.asyncio
async def test_pending_income_slot_unknown_user_act_still_resolves_substantive_answer() -> None:
    output = await _run_semantic_turn(
        "Tengo negocio",
        {
            "intent": "needs_human_review",
            "user_act": "unknown",
            "pending_slot_answered": None,
            "semantic_understanding": "Interpreter output was incomplete.",
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": True,
            },
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [],
            "response_plan": "Ask pending slot.",
            "ambiguity_reason": None,
            "confidence": 0.2,
            "needs_human": False,
            "risk_flags": ["semantic_interpreter_invalid_output"],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Como recibes tus ingresos?",
            metadata={"pending_slot": "income_type"},
        ),
    )

    tool = output.trace_metadata["universal_turn_trace"]["tool_results"][0]
    assert tool["tool_id"] == "credit_plan.resolve"
    assert tool["structured_output"]["raw_answer"] == "Tengo negocio"
    assert tool["structured_output"]["pending_slot"] == "business_tax_status"
    assert _field_values(output, "plan_selection") == []
    assert "SAT" in output.final_message or "sat" in output.final_message.casefold()


@pytest.mark.asyncio
async def test_merchant_candidate_requires_sat_clarification_before_plan() -> None:
    output = await _run_semantic_turn(
        "Soy comerciante",
        {
            "intent": "answer_pending_slot",
            "user_act": "answer_to_pending_slot",
            "pending_slot_answered": "income_type",
            "semantic_understanding": "Cliente dice que es comerciante, pero no aclara SAT/RIF.",
            "income": {
                "present": True,
                "candidate": "negocio_sat",
                "evidence": "Soy comerciante",
                "confidence": 0.72,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": None,
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {
                        "income_candidate": "negocio_sat",
                        "evidence": "Soy comerciante",
                    },
                    "reason": "Resolve only if tenant contract has enough evidence.",
                    "evidence": ["Soy comerciante"],
                }
            ],
            "response_plan": "Pedir aclaracion fiscal del negocio.",
            "ambiguity_reason": None,
            "confidence": 0.72,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Como recibes tus ingresos?",
            metadata={"pending_slot": "income_type"},
            salient_facts={
                "employment_seniority": 10,
                "product_selection": {"display_name": "Metro 125 CC"},
            },
        ),
    )

    tools = output.trace_metadata["universal_turn_trace"]["tool_results"]
    credit_plan = next(item for item in tools if item["tool_id"] == "credit_plan.resolve")
    assert credit_plan["structured_output"]["needs_clarification"] is True
    assert credit_plan["structured_output"]["pending_slot"] == "business_tax_status"
    assert not any(item["tool_id"] == "quote.resolve" for item in tools)
    assert _field_values(output, "plan_selection") == []
    assert "SAT" in output.final_message or "sat" in output.final_message.casefold()


@pytest.mark.asyncio
async def test_business_tax_pending_objection_does_not_run_credit_plan() -> None:
    output = await _run_semantic_turn(
        "Esta muy caro",
        {
            "intent": "objection",
            "user_act": "unknown",
            "pending_slot_answered": None,
            "semantic_understanding": "Cliente objeta precio, no contesta SAT/RIF.",
            "income": {
                "present": True,
                "candidate": "negocio_sat",
                "evidence": "negocio_sat",
                "confidence": 0.35,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": "business_tax_status",
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {
                        "income_candidate": "negocio_sat",
                        "evidence": "negocio_sat",
                    },
                    "reason": "Bad model request without current-turn fiscal evidence.",
                    "evidence": [],
                }
            ],
            "response_plan": "Retomar aclaracion fiscal.",
            "ambiguity_reason": "No hay evidencia de SAT/RIF o sin comprobantes.",
            "confidence": 0.35,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Tienes SAT/RIF o seria sin comprobantes?",
            metadata={"pending_slot": "business_tax_status"},
            salient_facts={
                "employment_seniority": 10,
                "product_selection": {"display_name": "Metro 125 CC"},
            },
        ),
    )

    tools = output.trace_metadata["universal_turn_trace"]["tool_results"]
    assert not any(item["tool_id"] == "credit_plan.resolve" for item in tools)
    assert _field_values(output, "plan_selection") == []
    assert "SAT" in output.final_message or "sat" in output.final_message.casefold()


@pytest.mark.asyncio
async def test_business_tax_status_unknown_user_act_uses_actual_pending_slot() -> None:
    output = await _run_semantic_turn(
        "No tengo SAT",
        {
            "intent": "needs_human_review",
            "user_act": "unknown",
            "pending_slot_answered": None,
            "semantic_understanding": "Interpreter output was incomplete.",
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": True,
            },
            "proposed_fields": {},
            "missing_field": "business_tax_status",
            "required_tools": [],
            "response_plan": "Resolve pending business tax status.",
            "ambiguity_reason": None,
            "confidence": 0.2,
            "needs_human": False,
            "risk_flags": ["semantic_interpreter_invalid_output"],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Tienes SAT/RIF o seria sin comprobantes?",
            metadata={"pending_slot": "business_tax_status"},
        ),
    )

    tool = output.trace_metadata["universal_turn_trace"]["tool_results"][0]
    assert tool["tool_id"] == "credit_plan.resolve"
    assert tool["structured_output"]["raw_answer"] == "No tengo SAT"
    assert tool["structured_output"]["pending_slot"] == "business_tax_status"
    assert _field_values(output, "plan_selection") == ["20%"]
    assert _field_values(output, "down_payment_percent") == [20]


@pytest.mark.asyncio
async def test_pending_slot_consumption_requires_answer_to_pending_slot_user_act() -> None:
    output = await _run_semantic_turn(
        "ya te dije",
        {
            "intent": "ask_clarification",
            "user_act": "frustration",
            "pending_slot_answered": None,
            "semantic_understanding": (
                "El cliente muestra frustracion; no esta contestando el slot de ingreso."
            ),
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": True,
            },
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [
                {
                    "name": "credit_plan.resolve",
                    "input": {
                        "raw_answer": "ya te dije",
                        "pending_slot": "income_type",
                    },
                    "reason": "El modelo intento consumir el slot sin respuesta real.",
                    "evidence": ["ya te dije"],
                }
            ],
            "response_plan": "Explicar el pendiente real sin copy generico.",
            "ambiguity_reason": "No hay evidencia de tipo de ingreso.",
            "confidence": 0.72,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Dime como recibes tus ingresos.",
            metadata={"pending_slot": "income_type"},
        ),
    )

    trace = output.trace_metadata["universal_turn_trace"]
    assert trace["tool_results"] == []
    assert "pendiente validar" in output.final_message
    assert "Sí se puede revisar" not in output.final_message
    assert "plan correcto" not in output.final_message
    assert _field_values(output, "plan_selection") == []
    assert _field_values(output, "down_payment_percent") == []


@pytest.mark.asyncio
async def test_business_income_clarification_is_not_rewritten_by_requirements_guard() -> None:
    output = await _run_semantic_turn(
        "Tengo negocio",
        {
            "intent": "answer_pending_slot",
            "pending_slot_answered": "income_type",
            "semantic_understanding": "Cliente menciona negocio pero falta SAT/RIF.",
            "income": {
                "present": True,
                "candidate": "negocio_sat",
                "evidence": "Tengo negocio",
                "confidence": 0.7,
                "needs_clarification": True,
            },
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [],
            "response_plan": "Aclarar SAT/RIF contra contrato tenant antes de pedir requisitos.",
            "ambiguity_reason": "Negocio sin estatus fiscal.",
            "confidence": 0.7,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Dime como recibes tus ingresos.",
            metadata={"pending_slot": "income_type"},
        ),
    )

    assert "SAT" in output.final_message
    assert "requisitos vigentes" not in output.final_message
    assert _field_values(output, "plan_selection") == []


@pytest.mark.asyncio
async def test_business_activity_does_not_require_faq_lookup_without_policy_intent() -> None:
    output = await _run_semantic_turn(
        "Vendo comida desde mi casa",
        {
            "intent": "answer_pending_slot",
            "pending_slot_answered": "business_tax_status",
            "semantic_understanding": "Cliente amplia actividad de negocio.",
            "income": {
                "present": True,
                "candidate": "negocio_sat",
                "evidence": "Vendo comida desde mi casa",
                "confidence": 0.68,
                "needs_clarification": True,
            },
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [
                {
                    "name": "faq.lookup",
                    "input": {"query": "vendo comida desde mi casa"},
                    "reason": "El modelo pidio FAQ sin politica real.",
                    "evidence": ["Vendo comida desde mi casa"],
                }
            ],
            "response_plan": "Aclarar SAT/RIF antes de validar plan.",
            "ambiguity_reason": "Negocio sin estatus fiscal.",
            "confidence": 0.68,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            last_pending_question="Dime si estas dado de alta en SAT/RIF.",
            metadata={"pending_slot": "business_tax_status"},
        ),
    )

    tool_ids = [
        item["tool_id"]
        for item in output.trace_metadata["universal_turn_trace"]["tool_results"]
    ]
    assert "faq.lookup" not in tool_ids
    assert output.trace_metadata["policy_warnings"] == []
    assert "SAT" in output.final_message


@pytest.mark.asyncio
async def test_short_model_answer_matches_tenant_catalog_with_article() -> None:
    output = await _run_semantic_turn(
        "La Adventure",
        {
            "intent": "product_selection",
            "pending_slot_answered": None,
            "semantic_understanding": "Cliente eligio un modelo por nombre corto.",
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": None,
            "required_tools": [],
            "response_plan": "Validar modelo contra catalogo tenant.",
            "ambiguity_reason": None,
            "confidence": 0.8,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    assert _field_values(output, "product_selection")
    tool = output.trace_metadata["universal_turn_trace"]["tool_results"][0]
    assert tool["tool_id"] == "catalog.search"
    assert tool["status"] == "succeeded"


@pytest.mark.asyncio
async def test_model_mention_inside_sentence_matches_tenant_catalog() -> None:
    output = await _run_semantic_turn(
        "Hola, vi una Skeleton, cuanto sale a credito?",
        {
            "intent": "credit_quote",
            "pending_slot_answered": None,
            "semantic_understanding": "Cliente menciona un modelo dentro de una frase.",
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [],
            "response_plan": "Validar modelo contra catalogo tenant y pedir ingreso.",
            "ambiguity_reason": None,
            "confidence": 0.82,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    assert _field_values(output, "product_selection")
    assert output.trace_metadata["universal_turn_trace"]["tool_results"][0]["tool_id"] == (
        "catalog.search"
    )


@pytest.mark.asyncio
async def test_requirements_lookup_prefers_validated_plan_over_free_query() -> None:
    output = await _run_semantic_turn(
        "que papeles ocupo",
        {
            "intent": "document_requirements",
            "pending_slot_answered": None,
            "semantic_understanding": "Cliente pide requisitos del plan validado.",
            "income": {
                "present": False,
                "candidate": "unknown",
                "evidence": None,
                "confidence": 0.0,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": None,
            "required_tools": [
                {
                    "name": "requirements.lookup",
                    "input": {"query": "que papeles ocupo"},
                    "reason": "El modelo envio query libre.",
                    "evidence": ["que papeles ocupo"],
                }
            ],
            "response_plan": "Buscar requisitos exactos del plan.",
            "ambiguity_reason": None,
            "confidence": 0.86,
            "needs_human": False,
            "risk_flags": [],
        },
        memory=ConversationMemoryContext(
            salient_facts={"plan_selection": "10%", "down_payment_percent": 10}
        ),
    )

    tool_results = output.trace_metadata["universal_turn_trace"]["tool_results"]
    assert [item["status"] for item in tool_results] == ["succeeded"]
    assert _field_values(output, "requirements_checklist")


@pytest.mark.asyncio
async def test_technical_llm_model_signal_does_not_trigger_catalog_search() -> None:
    output = await _run_semantic_turn(
        "me pagan por tarjeta",
        {
            "intent": "credit_plan",
            "semantic_understanding": "Cliente indica que recibe ingreso por tarjeta.",
            "pending_slot_answered": "income_type",
            "income": {
                "present": True,
                "candidate": "nomina_tarjeta",
                "evidence": "me pagan por tarjeta",
                "confidence": 0.92,
                "needs_clarification": False,
            },
            "proposed_fields": {},
            "missing_field": "employment_seniority",
            "required_tools": [],
            "response_plan": "Validar plan y pedir antiguedad.",
            "ambiguity_reason": None,
            "confidence": 0.92,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    tool_results = output.trace_metadata["universal_turn_trace"]["tool_results"]
    assert [tool["tool_id"] for tool in tool_results] == ["credit_plan.resolve"]
    assert _field_values(output, "plan_selection") == ["10%"]
    assert _field_values(output, "down_payment_percent") == [10]
    assert "tiempo llevas trabajando" in output.final_message


def test_catalog_query_must_be_actionable_for_tool_payload() -> None:
    assert _is_actionable_catalog_query("Skeleton") is True
    assert _is_actionable_catalog_query("?") is False
    assert _is_actionable_catalog_query("?!") is False
    assert _is_actionable_catalog_query("") is False
    assert _clean_missing_field("model") == "product_selection"
    assert _clean_missing_field("modelo") == "product_selection"


@pytest.mark.asyncio
async def test_hard_plan_field_without_tool_evidence_is_blocked() -> None:
    output = await _run_semantic_turn(
        "sí trabajo",
        {
            "intent": "credit_quote",
            "semantic_understanding": "Modelo propuso un plan sin tool; AtendIA debe bloquearlo.",
            "proposed_fields": {"plan_selection": "10%"},
            "missing_field": "income_type",
            "required_tools": [],
            "final_message_draft": (
                "Va, sí trabajas. Dime cómo recibes tus ingresos para validar "
                "el plan correcto."
            ),
            "confidence": 0.72,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    assert _field_values(output, "plan_selection") == []
    blocked = output.trace_metadata["universal_turn_trace"]["state_changes"]["blocked"]
    assert blocked[0]["field"] == "plan_selection"
    assert blocked[0]["reason"] == "valid_plan_evidence_required"


@pytest.mark.asyncio
async def test_moto_de_trabajo_uses_catalog_category_without_assigning_model_or_credit() -> None:
    output = await _run_semantic_turn(
        "quiero una moto de trabajo",
        {
            "intent": "recommend_by_use",
            "semantic_understanding": "El cliente pide recomendación por uso/categoría de moto.",
            "proposed_fields": {},
            "missing_field": None,
            "required_tools": [
                {
                    "name": "catalog.search",
                    "input": {"category": "trabajo"},
                    "reason": "Buscar modelos de la categoría indicada por uso.",
                    "evidence": ["quiero una moto de trabajo"],
                }
            ],
            "final_message_draft": (
                "Para trabajo te puedo revisar opciones de esa categoría. "
                "¿Buscas la más económica o más capacidad?"
            ),
            "confidence": 0.88,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    assert _field_values(output, "product_selection") == []
    assert _field_values(output, "plan_selection") == []
    tool = output.trace_metadata["universal_turn_trace"]["tool_results"][0]
    assert tool["tool_id"] == "catalog.search"
    assert tool["structured_output"]["category_matches"]


def test_policy_blocks_generic_progress_copy() -> None:
    output = TurnOutput(
        final_message="Tomo tu mensaje y reviso el siguiente paso con el contexto actual.",
        confidence=0.8,
        needs_human=False,
    )

    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(output)

    assert {issue.code for issue in exc.value.issues} == {"generic_progress_copy"}


@pytest.mark.asyncio
async def test_semantic_low_confidence_is_declared_as_policy_risk() -> None:
    output = await _run_semantic_turn(
        "Hola",
        {
            "intent": "greeting",
            "semantic_understanding": "El cliente saluda sin contexto suficiente.",
            "proposed_fields": {},
            "missing_field": "income_type",
            "required_tools": [],
            "final_message_draft": "Hola, claro. Para orientarte mejor dime qué moto te interesa.",
            "confidence": 0.42,
            "needs_human": False,
            "risk_flags": [],
        },
    )

    assert "low_confidence" in output.risk_flags
    PolicyValidator().validate_or_raise(output)


@pytest.mark.asyncio
async def test_dinamo_preflight_skeleton_buro_credit_semantic_no_send_contract() -> None:
    turns = [
        "Hola, vi una Skeleton, cuanto sale a credito? Estoy en buro.",
        "tengo 2 anos",
        "me pagan por tarjeta",
        "que papeles ocupo",
        "te mando INE al rato",
        "?",
    ]
    interpreter = _SequenceSemanticInterpreterProvider(
        [
            {
                "intent": "credit_quote",
                "semantic_understanding": "Quiere cotizar a credito, menciona modelo y buro.",
                "proposed_fields": {},
                "missing_field": "income_type",
                "required_tools": [
                    {
                        "name": "catalog.search",
                        "input": {"query": "Skeleton"},
                        "reason": "Validar modelo",
                        "evidence": [turns[0]],
                    },
                    {
                        "name": "faq.lookup",
                        "input": {"query": "buro"},
                        "reason": "Validar politica buro",
                        "evidence": [turns[0]],
                    },
                ],
                "response_plan": "Pedir antiguedad antes de ingreso.",
                "ambiguity_reason": None,
                "confidence": 0.9,
                "needs_human": False,
                "risk_flags": [],
            },
            {
                "intent": "answer_pending_slot",
                "pending_slot_answered": "employment_seniority",
                "semantic_understanding": "Cliente responde antiguedad laboral.",
                "proposed_fields": {"employment_seniority": 24},
                "missing_field": "income_type",
                "required_tools": [],
                "response_plan": "Guardar antiguedad y pedir ingreso.",
                "ambiguity_reason": None,
                "confidence": 0.91,
                "needs_human": False,
                "risk_flags": [],
            },
            {
                "intent": "credit_plan",
                "semantic_understanding": "Cliente indica que recibe ingreso por tarjeta.",
                "pending_slot_answered": "income_type",
                "income": {
                    "present": True,
                    "candidate": "nomina_tarjeta",
                    "evidence": turns[2],
                    "confidence": 0.92,
                    "needs_clarification": False,
                },
                "proposed_fields": {},
                "missing_field": None,
                "required_tools": [
                    {
                        "name": "credit_plan.resolve",
                        "input": {
                            "income_candidate": "nomina_tarjeta",
                            "evidence": turns[2],
                        },
                        "reason": "Resolver plan por ingreso",
                        "evidence": [turns[2]],
                    }
                ],
                "response_plan": "Validar plan y cotizar si modelo esta validado.",
                "ambiguity_reason": None,
                "confidence": 0.92,
                "needs_human": False,
                "risk_flags": [],
            },
            {
                "intent": "document_requirements",
                "semantic_understanding": "Cliente pide papeles del plan validado.",
                "proposed_fields": {},
                "missing_field": None,
                "required_tools": [],
                "response_plan": "Buscar requisitos del plan validado.",
                "ambiguity_reason": None,
                "confidence": 0.9,
                "needs_human": False,
                "risk_flags": [],
            },
            {
                "intent": "document_future_promise",
                "semantic_understanding": "Cliente promete mandar INE despues.",
                "proposed_fields": {},
                "missing_field": None,
                "required_tools": [],
                "response_plan": "No marcar documento recibido.",
                "ambiguity_reason": None,
                "confidence": 0.9,
                "needs_human": False,
                "risk_flags": [],
            },
            {
                "intent": "clarify_last_pending",
                "semantic_understanding": "Cliente pide aclaracion del estado actual.",
                "proposed_fields": {},
                "missing_field": None,
                "required_tools": [],
                "response_plan": "Retomar faltante real.",
                "ambiguity_reason": None,
                "confidence": 0.86,
                "needs_human": False,
                "risk_flags": [],
            },
        ]
    )
    provider = AdvisorFirstAgentProvider(
        advisor_brain=SemanticAdvisorBrain(interpreter),
        human_response_composer=HumanResponseComposer(provider=_SemanticTestHumanProvider()),
    )
    outputs = await _run_multiturn_no_send(provider, turns)

    assert "tiempo llevas trabajando" in outputs[0].final_message
    assert "ingresos" not in outputs[0].final_message.casefold()
    assert "recibes tus ingresos" in outputs[1].final_message
    assert "$" in outputs[2].final_message
    assert "Para ese plan ocupas:" in outputs[3].final_message
    assert "falta recibirla" in outputs[4].final_message
    assert "quÃ© plan" not in outputs[5].final_message.casefold()
    assert all(output.actions == [] for output in outputs)
    assert _field_values(outputs[1], "employment_seniority") == [24]
    assert _field_values(outputs[2], "plan_selection") == ["10%"]
    assert _field_values(outputs[2], "down_payment_percent") == [10]
    assert _field_values(outputs[3], "requirements_checklist")
    assert not _field_values(outputs[4], "requirements_complete")
    assert interpreter.calls[1]["validated_contact_state"]["validated_product"] == "Skeleton 400 CC"
    assert interpreter.calls[2]["validated_contact_state"]["validated_seniority"] == 24
    return

    assert "cómo recibes tus ingresos" in outputs[0].final_message
    assert "Cuánto tiempo llevas trabajando" in outputs[1].final_message
    assert "$" in outputs[2].final_message
    assert "Para ese plan ocupas:" in outputs[3].final_message
    assert "aún me falta recibirla" in outputs[4].final_message
    assert "qué plan" not in outputs[5].final_message.casefold()
    assert all(output.actions == [] for output in outputs)
    assert _field_values(outputs[1], "plan_selection") == ["10%"]
    assert _field_values(outputs[1], "down_payment_percent") == [10]
    assert _field_values(outputs[2], "employment_seniority") == [24]
    assert _field_values(outputs[3], "requirements_checklist")
    assert not _field_values(outputs[4], "requirements_complete")
    assert interpreter.calls[1]["validated_contact_state"]["validated_product"] == "Skeleton 400 CC"
    assert interpreter.calls[2]["validated_contact_state"]["validated_plan"] == "10%"


class _SequenceSemanticInterpreterProvider:
    def __init__(self, interpretations: list[dict[str, Any]]) -> None:
        self._interpretations = list(interpretations)
        self.calls: list[dict[str, Any]] = []

    async def interpret(self, context: TurnContext) -> SemanticInterpretation:
        self.calls.append(build_semantic_interpreter_payload(context))
        if not self._interpretations:
            raise AssertionError("no semantic interpretation left for test turn")
        return SemanticInterpretation.model_validate(self._interpretations.pop(0))


class _SemanticTestHumanProvider:
    async def compose(self, plan: Any) -> HumanResponseCandidate:
        facts = dict(plan.validated_facts)
        if plan.message_goal == "explain_validated_quote":
            quote = dict(facts.get("quote") or {})
            snapshot = dict(quote.get("quote_snapshot") or {})
            product = dict(snapshot.get("product") or {})
            pricing = dict(snapshot.get("pricing") or {})
            message = (
                f"Para {product.get('display_name', 'el producto')} el enganche es "
                f"${int(pricing.get('down_payment') or 0):,} y los pagos son de "
                f"${int(pricing.get('installment') or 0):,} por "
                f"{int(pricing.get('installments') or 0)} "
                f"{pricing.get('period_label', 'pagos')}."
            )
        elif facts.get("credit_plan") and plan.pending_slot in {
            "seniority",
            "employment_seniority",
        }:
            message = "Perfecto, ya valide tu tipo de ingreso. Cuánto tiempo llevas trabajando?"
        elif plan.message_goal == "greet_and_resume_without_consuming_slot":
            message = "Hola, claro. Que te gustaria revisar?"
        elif plan.message_goal == "acknowledge_confusion_and_explain_pending_slot":
            message = (
                "Entiendo. Aun tengo pendiente validar como recibes tus ingresos; "
                "con ese dato puedo avanzar sin adivinar el plan."
            )
        elif plan.message_goal == "explain_validated_requirements":
            requirements = dict(facts.get("requirements") or {})
            docs = [str(item) for item in requirements.get("requirements") or []]
            message = "Para ese plan ocupas: " + "; ".join(docs) + "."
        elif plan.message_goal == "ask_one_clarifying_question_for_pending_slot":
            if plan.next_best_question and "SAT" in plan.next_best_question:
                message = "Va, dime si tienes SAT/RIF o si seria sin comprobantes."
            elif plan.pending_slot in {"seniority", "employment_seniority"}:
                message = "Cuanto tiempo llevas trabajando?"
            else:
                message = "Para darte el plan correcto dime cómo recibes tus ingresos."
        elif plan.message_goal in {
            "explain_validated_document_status",
            "acknowledge_future_document_without_state_write",
        }:
            message = (
                "Va, cuando me la mandes que sea frente y reverso, completa y "
                "legible. Ahorita aún me falta recibirla."
            )
        else:
            message = "Dime como recibes tus ingresos para avanzar."
        return HumanResponseCandidate(
            final_message_candidate=message,
            language="es",
            reasoning_summary_safe=f"goal={plan.message_goal}",
            used_facts=list(facts),
            risk_flags=[],
        )


async def _run_multiturn_no_send(
    provider: AdvisorFirstAgentProvider,
    turns: list[str],
) -> list[TurnOutput]:
    messages: list[MessageContext] = []
    attrs: dict[str, Any] = {}
    salient_facts: dict[str, Any] = {}
    pending_slot: str | None = None
    last_pending_question: str | None = None
    outputs: list[TurnOutput] = []

    for index, inbound in enumerate(turns, start=1):
        messages.append(MessageContext(role="customer", text=inbound))
        metadata = {"pending_slot": pending_slot} if pending_slot else {}
        context = _turn_context(
            inbound,
            messages=list(messages),
            memory=ConversationMemoryContext(
                salient_facts=dict(salient_facts),
                last_pending_question=last_pending_question,
                metadata=metadata,
            ),
            customer_attrs=dict(attrs),
            turn_number=index,
        )
        output = await provider.generate(context)
        outputs.append(output)
        messages.append(MessageContext(role="agent", text=output.final_message))

        for update in output.field_updates:
            attrs[update.field_key] = update.value
            salient_facts[update.field_key] = update.value

        universal = output.trace_metadata["universal_turn_trace"]
        metadata = universal["gpt_proposed"]["metadata"]
        pending_slot = metadata.get("missing_field") or None
        if metadata.get("intent") == "document_future_promise":
            pending_slot = "document"
        last_pending_question = output.final_message if pending_slot else None

    return outputs


async def _run_semantic_turn(
    inbound: str,
    interpretation: dict,
    *,
    memory: ConversationMemoryContext | None = None,
) -> TurnOutput:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=SemanticAdvisorBrain(MockSemanticInterpreterProvider(interpretation)),
        human_response_composer=HumanResponseComposer(provider=_SemanticTestHumanProvider()),
    )
    return await provider.generate(_turn_context(inbound, memory=memory))


def _turn_context(
    inbound: str,
    *,
    messages: list[MessageContext] | None = None,
    memory: ConversationMemoryContext | None = None,
    knowledge: list[KnowledgeCitation] | None = None,
    customer_attrs: dict[str, Any] | None = None,
    turn_number: int | None = None,
) -> TurnContext:
    config = _dinamo_tenant_runtime_config()
    return TurnContext(
        tenant_id=str(DINAMO_TENANT_ID),
        conversation_id="conversation-semantic-runtime-v2",
        inbound_text=inbound,
        customer=CustomerContext(
            id="contact-semantic",
            phone_e164="+5218128889241",
            attrs=customer_attrs or {},
        ),
        messages=messages or [MessageContext(role="customer", text=inbound)],
        contact_fields=[
            ContactFieldDefinitionContext(
                key=key,
                label=str(metadata.get("label") or key),
                field_type=str(metadata.get("type") or "text"),
            )
            for key, metadata in config.field_metadata.items()
        ],
        memory=memory or ConversationMemoryContext(),
        tenant_config=config,
        knowledge_citations=knowledge or [],
        metadata={
            "agent_id": str(DINAMO_AGENT_ID),
            "no_send": True,
            "turn_number": turn_number,
        },
    )


def _dinamo_tenant_runtime_config() -> TenantRuntimeConfigContext:
    sources = [
        "docs/tenant_sources/dinamo/CatalogoMotos2026_DINAMO.json",
        "docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json",
        "docs/tenant_sources/dinamo/FAQ_DINAMO.json",
    ]
    config = TenantRuntimeConfigContext(
        knowledge_sources=sources,
        metadata={
            "knowledge_os": {
                "sources": {
                    "catalog": {"path": sources[0]},
                    "requirements": {"path": sources[1]},
                    "faq": {"path": sources[2]},
                },
                "mode": "tenant_structured_sources",
            }
        },
    )
    result = load_tenant_domain_contract(
        json.loads((FIXTURE_DIR / "dinamo_motos_nl_shadow.json").read_text(encoding="utf-8")),
        tenant_id=str(DINAMO_TENANT_ID),
        agent_id=str(DINAMO_AGENT_ID),
    )
    return apply_tenant_domain_contract(config, result)


def _field_values(output: TurnOutput, field_key: str) -> list[object]:
    return [
        update.value
        for update in output.field_updates
        if update.field_key == field_key
    ]

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from atendia.contracts.conversation_state import ConversationState
from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import Condition, PipelineDefinition, StageDefinition
from atendia.contracts.tone import Tone
from atendia.contracts.turn_resolution import ResolverAttempt, TurnResolverResult
from atendia.runner.composer_context import build_composer_context_pack
from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import ComposerInput, ComposerOutput
from atendia.runner.confirmation_policy import ConfirmationPolicyRequest, apply_confirmation_policy
from atendia.runner.conversation_memory import build_conversation_summary
from atendia.runner.conversation_runner import (
    _agent_tone_to_register,
    _catalog_binding_config,
    _catalog_binding_queries,
    _catalog_browse_query,
    _catalog_browse_request_type,
    _composer_max_messages_from_qos,
    _is_doc_like_field,
    _public_vision_rejection_reason,
    _quote_candidate_queries,
)
from atendia.runner.response_contract import ResponseContractRequest, apply_response_contract
from atendia.runner.response_frame import build_response_frame, render_response_frame_fallback_message
from atendia.runner.resume_memory_policy import (
    missing_documents_context_from_requirements,
    quote_candidate_queries,
    quote_context_ready_for_recompute,
    quote_plan_code_from_values,
    resume_memory_trace_metadata_from_context,
    resume_pending_action_from_payload,
    resume_target_from_context,
)
from atendia.runner.resolvers.document_expectation_resolver import DocumentExpectationResolver
from atendia.runner.resolvers.last_question_resolver import LastQuestionResolver
from atendia.runner.resolvers.reference_resolver import ReferenceResolver
from atendia.runner.runner_layers import build_runner_layers
from atendia.runner.state_write_policy import StateWritePolicyRequest, apply_state_write_policy
from atendia.state_machine.orchestrator import process_turn
from atendia.state_machine.pipeline_evaluator import evaluate_condition


def test_document_status_rules_accept_flat_ok_shape() -> None:
    complete_condition = Condition(
        field="CREDITO",
        operator="documents_complete_for_selection",
    )

    assert (
        evaluate_condition(
            complete_condition,
            {
                "CREDITO": "Sin Comprobantes",
                "INE_FRENTE": "ok",
                "INE_ATRAS": {"status": "ok"},
            },
            document_requirements={"Sin Comprobantes": ["INE_FRENTE", "INE_ATRAS"]},
            document_requirements_field="CREDITO",
        )
        is True
    )


def test_document_fields_from_tenant_catalog_are_vision_owned() -> None:
    pipeline = SimpleNamespace(
        documents_catalog=[SimpleNamespace(key="INE_FRENTE")],
        vision_doc_mapping={"ine": ["INE_FRENTE", "INE_ATRAS"]},
        document_requirements={"plan": ["COMPROBANTE_DOMICILIO"]},
    )

    assert _is_doc_like_field("INE_FRENTE", pipeline) is True
    assert _is_doc_like_field("INE_ATRAS", pipeline) is True
    assert _is_doc_like_field("COMPROBANTE_DOMICILIO", pipeline) is True
    assert _is_doc_like_field("MOTO", pipeline) is False


def test_quote_candidates_can_use_tenant_product_field_without_producto_interes() -> None:
    pipeline = SimpleNamespace(
        documents_catalog=[],
        vision_doc_mapping={},
        document_requirements={},
    )
    candidates = _quote_candidate_queries(
        extracted_data={},
        customer_attrs={"MOTO": "R4 250 CC", "ENGANCHE": "20%"},
        inbound_text="cuanto cuesta",
        pipeline=pipeline,
    )

    assert candidates[0] == "R4 250 CC"
    assert "20%" not in candidates


def test_resume_memory_quote_helpers_preserve_order_plan_and_readiness() -> None:
    pipeline = SimpleNamespace(
        documents_catalog=[SimpleNamespace(key="INE_FRENTE")],
        vision_doc_mapping={},
        document_requirements={},
    )

    assert quote_candidate_queries(
        extracted_data={
            "MOTO": {"value": "R4 250 CC"},
            "color": {"value": "Azul"},
            "INE_FRENTE": {"value": "ok"},
        },
        customer_attrs={"MOTO": "Modelo anterior", "ENGANCHE": "20%"},
        inbound_text="cotizala",
        pipeline=pipeline,
    ) == ["R4 250 CC", "Azul", "cotizala"]
    assert quote_plan_code_from_values({"plan": "15%"}, {"ENGANCHE": "20%"}) == "15%"
    assert (
        quote_context_ready_for_recompute(
            extracted_data={"MOTO": {"value": "R4 250 CC"}, "ENGANCHE": {"value": "20%"}}
        )
        is True
    )
    assert quote_context_ready_for_recompute(extracted_data={"MOTO": "R4 250 CC"}) is False


def test_resume_memory_document_context_preserves_labels_and_pending_priority() -> None:
    requirements = {
        "missing": [
            {"key": "INE_ATRAS", "label": "INE atras"},
            {"key": "DOMICILIO", "label": "Domicilio"},
        ],
        "received": [{"key": "INE_FRENTE", "label": "INE frente"}],
        "rejected": [{"key": "NOMINA", "label": "Nomina"}],
        "complete": False,
    }

    assert missing_documents_context_from_requirements(requirements) == {
        "missing": ["INE atras", "Domicilio"],
        "received": ["INE frente"],
        "rejected": ["Nomina"],
        "has_missing": True,
        "is_complete": False,
    }
    assert resume_pending_action_from_payload(
        action_payload={"requirements": requirements},
        extracted_data={},
    ) == {"type": "ask_missing_documents", "missing": ["INE atras", "Domicilio"]}
    assert resume_pending_action_from_payload(action_payload={}, extracted_data={}) == {
        "type": "ask_field",
        "field": "MOTO",
    }
    assert resume_pending_action_from_payload(
        action_payload={},
        extracted_data={"MOTO": "R4", "CREDITO": "Nomina"},
    ) == {"type": "ask_field", "field": "ENGANCHE"}


def test_resume_memory_target_and_unpublished_trace_metadata_are_pure() -> None:
    pending = {"type": "ask_field", "field": "MOTO"}
    target = resume_target_from_context(
        pending_to_resume=pending,
        resume_pending_action=None,
        requirements=None,
        current_state=None,
    )
    assert target == pending
    assert target is not pending

    metadata = resume_memory_trace_metadata_from_context(
        pending_to_resume=None,
        resume_pending_action=None,
        requirements={
            "missing": [{"key": "INE", "label": "INE frente"}],
            "received": [],
            "rejected": [],
            "complete": False,
        },
        current_state={"MOTO": "R4", "CREDITO": "Nomina"},
    )
    assert metadata == {
        "resume_target": {"type": "ask_missing_documents", "missing": ["INE frente"]},
        "missing_documents_context": {
            "missing": ["INE frente"],
            "received": [],
            "rejected": [],
            "has_missing": True,
            "is_complete": False,
        },
    }


def test_income_text_cannot_be_written_to_moto() -> None:
    pipeline = SimpleNamespace(documents_catalog=[], vision_doc_mapping={}, document_requirements={})
    result = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={},
            proposed_updates={"MOTO": "Me depositan nomina en tarjeta"},
            nlu_entities={"MOTO": "Me depositan nomina en tarjeta"},
            turn_context={"pipeline": pipeline, "inbound_text": "me depositan nomina en tarjeta"},
        )
    )

    assert result.approved_updates == {}
    assert result.blocked_updates[0]["field"] == "MOTO"
    assert result.blocked_updates[0]["reason"] == "invalid_model_entity_value"


def test_model_field_only_accepts_catalog_entity() -> None:
    pipeline = SimpleNamespace(documents_catalog=[], vision_doc_mapping={}, document_requirements={})
    result = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={},
            proposed_updates={"MOTO": "otra moto"},
            nlu_entities={"MOTO": "otra moto"},
            turn_context={"pipeline": pipeline, "inbound_text": "otra moto"},
        )
    )

    assert result.approved_updates == {}
    assert result.blocked_updates[0]["field"] == "MOTO"
    assert result.blocked_updates[0]["reason"] == "invalid_model_entity_value"


def test_credit_field_only_accepts_credit_plan_entity() -> None:
    pipeline = SimpleNamespace(documents_catalog=[], vision_doc_mapping={}, document_requirements={})
    result = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={},
            proposed_updates={"CREDITO": "credito"},
            nlu_entities={"CREDITO": "credito"},
            turn_context={"pipeline": pipeline, "inbound_text": "credito"},
        )
    )

    assert result.approved_updates == {}
    assert result.blocked_updates[0]["field"] == "CREDITO"
    assert result.blocked_updates[0]["reason"] == "invalid_credit_plan_entity_value"


def test_state_write_blocks_credit_and_downpayment_when_income_ambiguous() -> None:
    pipeline = SimpleNamespace(documents_catalog=[], vision_doc_mapping={}, document_requirements={})
    advisor_decision = SimpleNamespace(
        tool_payload={
            "policy_trace": {
                "income_ambiguity": True,
                "needs_income_disambiguation": True,
                "payroll_ambiguous": True,
                "credit_plan_write_blocked_reason": "payroll_ambiguous",
            }
        }
    )

    result = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={},
            proposed_updates={"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
            nlu_entities={"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
            advisor_decision=advisor_decision,
            turn_context={"pipeline": pipeline, "inbound_text": "me pagan nomina"},
        )
    )

    assert result.approved_updates == {}
    assert {item["field"] for item in result.blocked_updates} == {"CREDITO", "ENGANCHE"}
    assert {item["reason"] for item in result.blocked_updates} == {"payroll_ambiguous"}


def test_agent_ui_tones_map_to_composer_registers() -> None:
    assert _agent_tone_to_register("Calido") == "informal_mexicano"
    assert _agent_tone_to_register("Empatico") == "informal_mexicano"
    assert _agent_tone_to_register("Claro y conciso") == "neutral_es"
    assert _agent_tone_to_register("Formal") == "formal_es"


def test_composer_defaults_to_one_message_even_when_qos_disabled() -> None:
    assert _composer_max_messages_from_qos({}) == 1
    assert _composer_max_messages_from_qos({"enabled": False, "max_messages_per_turn": 1}) == 1
    assert _composer_max_messages_from_qos({"enabled": False, "max_messages_per_turn": 3}) == 3


def test_runner_layers_expose_auditable_state_update_contract() -> None:
    layers = build_runner_layers(
        pipeline=SimpleNamespace(documents_catalog=[], document_requirements={}),
        previous_stage="nuevo",
        next_stage="credito",
        decision_action="ask_field",
        decision_reason="state_guard_protected_conflict",
        flow_mode=FlowMode.PLAN,
        action_payload={"field_name": "CREDITO"},
        extracted_data={"MOTO": {"value": "R4 250 CC"}},
        rules_evaluated=[],
        router_trigger="manual:test",
        pause_bot=False,
        decision_debug={
            "resolver_attempts": [{"resolver": "catalog_resolver"}],
            "field_updates_proposed": [{"field": "CREDITO", "value": "Nomina"}],
            "field_updates_approved": ["MOTO"],
            "field_updates_blocked": [
                {"field": "CREDITO", "reason": "protected_field_conflict_requires_confirmation"}
            ],
            "pending_question": {"type": "clarification", "text": "Confirmas?"},
            "pending_confirmation": '{"yes":{"CREDITO":"Nomina"}}',
            "decision_payload": {"decision": "protected_field_conflict"},
        },
    )

    decision = layers["decision"]
    assert decision["resolver_attempts"] == [{"resolver": "catalog_resolver"}]
    assert decision["field_updates_proposed"][0]["field"] == "CREDITO"
    assert decision["field_updates_approved"] == ["MOTO"]
    assert decision["field_updates_blocked"][0]["field"] == "CREDITO"
    assert decision["pending_question"]["type"] == "clarification"
    assert decision["pending_confirmation"] == '{"yes":{"CREDITO":"Nomina"}}'
    assert decision["decision_payload"]["decision"] == "protected_field_conflict"


def test_catalog_item_field_enables_generic_catalog_binding() -> None:
    field = SimpleNamespace(field_type="catalog_item", field_options=None)

    assert _catalog_binding_config(field) == {"enabled": True}


def test_catalog_binding_queries_extract_product_like_terms_without_tenant_names() -> None:
    queries = _catalog_binding_queries("La r4")

    assert queries[0] == "La r4"
    assert "r4" in queries


def test_catalog_browse_style_queries_keep_style_context() -> None:
    assert (
        _catalog_browse_request_type(
            inbound_text="me interesa una chopper",
            history=[],
        )
        == "catalog_style"
    )
    assert (
        _catalog_browse_query(
            browse_intent="catalog_style",
            inbound_text="me interesa una chopper",
            history=[],
        )
        == "chopper"
    )

    history = [("outbound", "Si, tenemos estas opciones de chopper:")]
    assert (
        _catalog_browse_request_type(
            inbound_text="Solo esas?",
            history=history,
        )
        == "catalog_more"
    )
    assert (
        _catalog_browse_query(
            browse_intent="catalog_more",
            inbound_text="Solo esas?",
            history=history,
        )
        == "chopper"
    )


def test_catalog_browse_request_detects_post_quote_alternative_request() -> None:
    history = [
        (
            "outbound",
            "La Adventure Elite 150 CC de contado queda en $29,900.\n\n"
            "Con tu plan 20%:\nEnganche: $6,279\nPago quincenal: $1,017\nPlazo: 72 quincenas",
        )
    ]

    assert (
        _catalog_browse_request_type(
            inbound_text="mejor otra mas barata",
            history=history,
        )
        == "catalog_more"
    )
    assert (
        _catalog_browse_query(
            browse_intent="catalog_more",
            inbound_text="mejor otra mas barata",
            history=history,
        )
        == ""
    )


def test_pending_confirmation_side_effects_preserve_boolean_values() -> None:
    result = apply_confirmation_policy(
        ConfirmationPolicyRequest(
            user_message="si",
            pending_confirmation='{"yes":{"FILTRO":false},"no":{"FILTRO":true}}',
            current_state={"FILTRO": {"value": True, "confidence": 1.0, "source_turn": 3}},
        )
    )
    updated = result.extracted_data

    assert result.confirmation_resolution is not None
    assert result.approved_updates == {"FILTRO": False}
    assert updated["FILTRO"]["value"] is False
    assert updated["FILTRO"]["source_turn"] == 0


def test_vision_rejection_reason_is_customer_safe_spanish() -> None:
    assert (
        _public_vision_rejection_reason("The image is blurry, affecting legibility.")
        == "la foto salio borrosa y no se alcanza a leer bien"
    )


def test_turn_resolution_bypasses_generic_unclear_clarification_when_state_write_is_safe() -> None:
    pipeline = PipelineDefinition(
        stages=[
            StageDefinition(
                id="nuevo",
                actions_allowed=["ask_clarification", "ask_field"],
            )
        ],
        fallback="ask_clarification",
    )
    state = ConversationState(
        conversation_id="conversation",
        tenant_id="tenant",
        current_stage="nuevo",
        stage_entered_at=datetime.now(UTC),
    )
    nlu = NLUResult(
        intent=Intent.UNCLEAR,
        sentiment=Sentiment.NEUTRAL,
        confidence=0.5,
    )

    generic = process_turn(pipeline, state, nlu, turn_count=1)
    assert generic.action == "ask_clarification"
    assert generic.reason == "ambiguous_nlu"

    resolved = TurnResolverResult(
        resolved=True,
        selected_attempt=ResolverAttempt(
            resolver="catalog_resolver",
            input="r4",
            understood_as="R4 250 CC",
            confidence=0.95,
            can_write_state=True,
            field_updates={"MOTO": "R4 250 CC"},
        ),
        field_updates={"MOTO": "R4 250 CC"},
        effective_intent="ASK_INFO",
    )

    decision = process_turn(
        pipeline,
        state,
        nlu,
        turn_count=1,
        turn_resolution=resolved,
    )
    assert decision.action == "ask_field"
    assert decision.reason == "stay_in_stage"


def test_composer_prompt_includes_clean_decision_payload() -> None:
    prompt = build_composer_prompt(
        ComposerInput(
            action="ask_field",
            action_payload={},
            decision_payload={
                "decision": "product_detected",
                "field_updated": "MOTO",
                "value": "R4 250 CC",
                "next_action": "ask_payment_type",
            },
            current_stage="nuevo",
            last_intent="UNCLEAR",
            tone=Tone(),
        )
    )

    system_prompt = prompt[0]["content"]
    assert "decision_payload" in system_prompt
    assert "product_detected" in system_prompt
    assert "R4 250 CC" in system_prompt


def test_composer_context_pack_makes_answer_first_and_resume_pending_explicit() -> None:
    context_pack = build_composer_context_pack(
        user_message="revisan buro?",
        recent_history=[("inbound", "por fuera"), ("inbound", "20")],
        extracted_data={
            "MOTO": "Skeleton 400 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "requirements": {
                "required": [{"key": "INE_FRENTE", "label": "INE frente"}],
                "received": [],
                "rejected": [],
                "missing": [{"key": "INE_ATRAS", "label": "INE atras"}],
                "complete": False,
            },
        },
        decision_payload={
            "decision": "faq_answered",
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE atras"],
            },
        },
        guardrails=["No preguntes por enganche si ENGANCHE ya tiene valor."],
        conversation_summary="Cliente quiere Skeleton a credito.",
    )

    assert context_pack.must_answer_first == (
        "Responder primero la duda directa del cliente sobre buro."
    )
    assert context_pack.pending_to_resume == {
        "type": "ask_missing_documents",
        "missing": ["INE atras"],
    }
    assert context_pack.state_facts["documentos_faltantes"] == ["INE atras"]
    assert context_pack.business_facts["faq_answer"] == "Si, se revisa buro."
    assert any("No vuelvas a pedir ENGANCHE" in item for item in context_pack.must_not_say)

    prompt = build_composer_prompt(
        ComposerInput(
            action="lookup_faq",
            action_payload=context_pack.tool_payload,
            decision_payload=context_pack.runner_decision,
            context_pack=context_pack,
            current_stage="credito",
            last_intent="ASK_INFO",
            tone=Tone(),
        )
    )

    system_prompt = prompt[0]["content"]
    assert "Context Pack operativo" in system_prompt
    assert "must_answer_first" in system_prompt
    assert "pending_to_resume" in system_prompt
    assert "Cliente quiere Skeleton a credito." in system_prompt


def test_conversation_summary_refreshes_operational_facts_without_raw_chat() -> None:
    summary = build_conversation_summary(
        previous_summary="FAQ respondida (enganche): Se aclaro el enganche minimo.",
        extracted_data={
            "MOTO": {"value": "Skeleton 400 CC"},
            "CREDITO": {"value": "Sin Comprobantes"},
            "ENGANCHE": {"value": "20%"},
        },
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro y aplica sujeto a revision.",
            "requirements": {
                "required": [
                    {"key": "INE_FRENTE", "label": "INE frente"},
                    {"key": "INE_ATRAS", "label": "INE reverso"},
                ],
                "received": [{"key": "INE_FRENTE", "label": "INE frente"}],
                "missing": [{"key": "INE_ATRAS", "label": "INE reverso"}],
                "rejected": [],
            },
        },
        decision_payload={"decision": "faq_answered"},
    )

    assert summary is not None
    assert "Cliente busca credito Sin Comprobantes para Skeleton 400 CC." in summary
    assert "Plan/enganche seleccionado: 20%." in summary
    assert "Documentos recibidos: INE frente." in summary
    assert "Documentos faltantes: INE reverso." in summary
    assert "FAQ respondida (enganche): Se aclaro el enganche minimo." in summary
    assert "FAQ respondida (buro): Si, se revisa buro" in summary
    assert "revisan buro?" not in summary


def test_answer_and_resume_flow_renders_faqs_before_asking_seniority() -> None:
    composer_output = ComposerOutput(messages=["Solo dime tu antiguedad."], suggested_handoff=None)

    result = apply_response_contract(
        ResponseContractRequest(
            action="lookup_faq",
            action_payload={
                "status": "ok",
                "answer": "Si, puedes liquidar antes. Si, se revisa buro. Estamos en Guadalupe.",
                "answers": [
                    {"topic": "liquidacion", "answer": "Si, puedes liquidar antes."},
                    {"topic": "buro", "answer": "Si, se revisa buro."},
                    {"topic": "ubicacion", "answer": "Estamos en Guadalupe."},
                ],
                "answered_intents": ["liquidacion", "buro", "ubicacion"],
                "resume_pending_action": {"type": "ask_field", "field": "ANTIGUEDAD_LABORAL"},
            },
            composer_output=composer_output,
            state={},
            inbound_text="puedo liquidar antes? checan buro? donde estan?",
        )
    )

    assert result.contract_applied is True
    assert result.outbound_messages is not None
    rendered = "\n".join(result.outbound_messages)
    normalized = rendered.lower()
    assert "liquid" in normalized
    assert "buro" in normalized
    assert "guadalupe" in normalized
    assert "antiguedad" in normalized


def test_composer_guard_does_not_replace_multi_faq_with_resume_question_only() -> None:
    composer_output = ComposerOutput(messages=["Solo dime tu antiguedad."], suggested_handoff=None)

    result = apply_response_contract(
        ResponseContractRequest(
            action="ask_credit_context",
            action_payload={
                "status": "ok",
                "field_name": "ANTIGUEDAD_LABORAL",
                "request_type": "ask_employment_seniority",
                "prompt_override": "Para darte el mejor plan, dime cuanto tiempo llevas en tu empleo actual?",
            },
            composer_output=composer_output,
            state={},
            inbound_text="puedo liquidar antes? checan buro? donde estan?",
            advisor_decision={
                "next_action": "answer_faq_and_resume",
                "tool_payload": {
                    "status": "ok",
                    "answer": "Si puedes liquidar antes. Si se revisa buro. Estamos en Monterrey.",
                    "answers": [
                        {"topic": "liquidacion", "answer": "Si puedes liquidar antes."},
                        {"topic": "buro", "answer": "Si se revisa buro."},
                        {"topic": "ubicacion", "answer": "Estamos en Monterrey."},
                    ],
                    "answered_intents": ["liquidacion", "buro", "ubicacion"],
                },
            },
        )
    )

    assert result.contract_applied is True
    rendered = "\n".join(result.outbound_messages or []).lower()
    assert "liquid" in rendered
    assert "buro" in rendered
    assert "monterrey" in rendered
    assert "empleo actual" in rendered


def test_response_contract_does_not_replace_valid_llm_answer_and_resume_with_document_template() -> None:
    composer_output = ComposerOutput(
        messages=[
            "Si, se revisa buro.\n\nY para avanzar, todavia faltaria: INE-FRENTE, Domicilio, INE-ATRAS."
        ],
        suggested_handoff=None,
    )

    result = apply_response_contract(
        ResponseContractRequest(
            action="lookup_faq",
            action_payload={
                "status": "ok",
                "topic": "buro",
                "answer": "Si, se revisa buro.",
                "answered_intents": ["buro"],
                "resume_pending_action": {
                    "type": "ask_missing_documents",
                    "missing": ["INE-FRENTE", "Domicilio", "INE-ATRAS"],
                },
            },
            composer_output=composer_output,
            state={},
            inbound_text="revisan buro?",
        )
    )

    assert result.contract_applied is True
    rendered = "\n".join(result.outbound_messages or []).lower()
    assert "buro" in rendered
    assert "ine por ambos lados" in rendered
    assert "comprobante de domicilio reciente" in rendered
    assert result.contract_reason == "faq_output_rendered_from_payload"


def test_response_contract_respects_valid_response_frame_answer_and_resume_output() -> None:
    response_frame = build_response_frame(
        user_message="revisan buro?",
        recent_history=[
            ("outbound", "Para avanzar solo faltaria: INE-FRENTE."),
            ("inbound", "revisan buro?"),
        ],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "answered_intents": ["buro"],
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE"],
            },
        },
        decision_payload={"resume_pending_action": {"type": "ask_missing_documents", "missing": ["INE-FRENTE"]}},
        extracted_data={},
        current_stage="credito",
        guardrails=[],
    )
    composer_output = ComposerOutput(
        messages=["Si, se revisa buro.\n\nY para seguir, todavia faltaria: parte de enfrente de tu INE."],
        suggested_handoff=None,
    )

    result = apply_response_contract(
        ResponseContractRequest(
            action="lookup_faq",
            action_payload={
                "status": "ok",
                "topic": "buro",
                "answer": "Si, se revisa buro.",
                "answered_intents": ["buro"],
                "resume_pending_action": {
                    "type": "ask_missing_documents",
                    "missing": ["INE-FRENTE"],
                },
            },
            composer_output=composer_output,
            state={},
            response_frame=response_frame,
            inbound_text="revisan buro?",
        )
    )

    assert result.contract_applied is False
    assert result.outbound_messages == [
        "Si, se revisa buro.\n\nY para seguir, todavia faltaria: parte de enfrente de tu INE."
    ]


def test_response_contract_does_not_replace_valid_response_frame_output_with_document_template() -> None:
    response_frame = build_response_frame(
        user_message="revisan buro?",
        recent_history=[
            ("outbound", "Para avanzar solo faltaria: INE-FRENTE."),
            ("inbound", "revisan buro?"),
        ],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "answered_intents": ["buro"],
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE"],
            },
        },
        decision_payload={"resume_pending_action": {"type": "ask_missing_documents", "missing": ["INE-FRENTE"]}},
        extracted_data={},
        current_stage="credito",
        guardrails=[],
    )
    composer_output = ComposerOutput(
        messages=["Si, se revisa buro.\n\nY para seguir, todavia faltaria: parte de enfrente de tu INE."],
        suggested_handoff=None,
    )

    result = apply_response_contract(
        ResponseContractRequest(
            action="lookup_faq",
            action_payload={
                "status": "ok",
                "topic": "buro",
                "answer": "Si, se revisa buro.",
                "answered_intents": ["buro"],
                "resume_pending_action": {
                    "type": "ask_missing_documents",
                    "missing": ["INE-FRENTE"],
                },
            },
            composer_output=composer_output,
            state={},
            response_frame=response_frame,
            inbound_text="revisan buro?",
        )
    )

    assert result.contract_applied is False
    assert result.contract_reason is None
    assert result.outbound_messages == [
        "Si, se revisa buro.\n\nY para seguir, todavia faltaria: parte de enfrente de tu INE."
    ]


def test_response_contract_does_not_rerender_when_valid_frame_output_covers_requirements() -> None:
    response_frame = build_response_frame(
        user_message="que requisitos piden?",
        recent_history=[
            ("outbound", "Perfecto, ya tengo tu perfil."),
            ("inbound", "que requisitos piden?"),
        ],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "requirements",
            "answer": "Para ese perfil normalmente se revisa INE por ambos lados y comprobante de domicilio reciente.",
            "answered_intents": ["requirements"],
            "resume_pending_action": {"type": "ask_field", "field": "MOTO"},
        },
        decision_payload={"resume_pending_action": {"type": "ask_field", "field": "MOTO"}},
        extracted_data={"CREDITO": "Sin Comprobantes"},
        current_stage="credito",
        guardrails=[],
    )
    composer_output = ComposerOutput(
        messages=[
            "Para ese perfil normalmente se revisa INE por ambos lados y comprobante de domicilio reciente.\n\nY para seguir, dime que modelo quieres revisar."
        ],
        suggested_handoff=None,
    )

    result = apply_response_contract(
        ResponseContractRequest(
            action="lookup_faq",
            action_payload={
                "status": "ok",
                "topic": "requirements",
                "answer": "Para ese perfil normalmente se revisa INE por ambos lados y comprobante de domicilio reciente.",
                "answered_intents": ["requirements"],
                "resume_pending_action": {"type": "ask_field", "field": "MOTO"},
            },
            composer_output=composer_output,
            state={},
            response_frame=response_frame,
            inbound_text="que requisitos piden?",
        )
    )

    assert result.contract_applied is False
    assert result.contract_reason is None
    assert result.outbound_messages == composer_output.messages


def test_response_contract_only_guards_not_rewrites_valid_frame_output() -> None:
    response_frame = build_response_frame(
        user_message="donde estan?",
        recent_history=[
            ("outbound", "Para seguir solo faltaria: INE-FRENTE."),
            ("inbound", "donde estan?"),
        ],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "ubicacion",
            "answer": "Estamos en Monterrey, Nuevo Leon.",
            "answered_intents": ["ubicacion"],
            "resume_pending_action": {"type": "ask_missing_documents", "missing": ["INE-FRENTE"]},
        },
        decision_payload={
            "resume_pending_action": {"type": "ask_missing_documents", "missing": ["INE-FRENTE"]}
        },
        extracted_data={},
        current_stage="credito",
        guardrails=["documents_after_quote"],
    )
    composer_output = ComposerOutput(
        messages=[
            "Estamos en Monterrey, Nuevo Leon.\n\nY para seguir, todavia faltaria: parte de enfrente de tu INE."
        ],
        suggested_handoff=None,
    )

    result = apply_response_contract(
        ResponseContractRequest(
            action="lookup_faq",
            action_payload={
                "status": "ok",
                "topic": "ubicacion",
                "answer": "Estamos en Monterrey, Nuevo Leon.",
                "answered_intents": ["ubicacion"],
                "resume_pending_action": {"type": "ask_missing_documents", "missing": ["INE-FRENTE"]},
            },
            composer_output=composer_output,
            state={},
            response_frame=response_frame,
            inbound_text="donde estan?",
        )
    )

    assert result.contract_applied is False
    assert result.contract_reason is None
    assert result.outbound_messages == composer_output.messages


def test_response_frame_blocks_document_resume_during_credit_plan_resolution() -> None:
    response_frame = build_response_frame(
        user_message="ok entonces con tarjeta",
        recent_history=[
            ("outbound", "Perfecto, ya ubique la R4 250 CC. Para seguir, dime como recibes tus ingresos."),
            ("inbound", "ok entonces con tarjeta"),
        ],
        action="resolve_credit_plan",
        action_payload={
            "status": "ok",
            "type": "credit_plan_resolution",
            "selection_key": "Nomina Tarjeta",
            "selection_label": "Nomina Tarjeta",
            "down_payment": "10%",
            "field_updates": {"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
            "requirements": {
                "missing": [
                    {"key": "INE_FRENTE", "label": "INE-FRENTE"},
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Domicilio"},
                ]
            },
            "pending_to_resume": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE", "Domicilio"],
            },
        },
        decision_payload={
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE", "Domicilio"],
            }
        },
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
        },
        current_stage="potencialcliente",
        guardrails=["quote_required_before_documents"],
    )

    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.type == "ask_field"
    assert response_frame.pending_flow.payload["field"] == "FILTRO"
    assert response_frame.response_strategy == "answer_and_resume_flow"
    assert "missing_documents" not in response_frame.known_customer_state


def test_faq_answer_resumes_next_real_step_not_stale_pending() -> None:
    response_frame = build_response_frame(
        user_message="revisan buro?",
        recent_history=[("outbound", "Para seguir, dime que modelo quieres revisar.")],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "answered_intents": ["buro"],
            "resume_pending_action": {"type": "ask_field", "field": "MOTO"},
        },
        decision_payload={},
        extracted_data={"MOTO": "R4 250 CC"},
        current_stage="potencialcliente",
        guardrails=[],
    )

    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.payload["field"] == "CREDITO"
    assert response_frame.trace.pending_flow_recompute_reason == (
        "pending_flow_contradicts_validated_state"
    )
    assert "ingresos" in render_response_frame_fallback_message(response_frame)


def test_repeated_buro_resumes_documents_only_after_quote_valid() -> None:
    action_payload = {
        "status": "ok",
        "topic": "buro",
        "answer": "Si, se revisa buro.",
        "answered_intents": ["buro"],
        "requirements": {
            "missing": [
                {"key": "INE_FRENTE", "label": "INE-FRENTE"},
                {"key": "COMPROBANTE_DOMICILIO", "label": "Domicilio"},
            ]
        },
    }
    no_quote_frame = build_response_frame(
        user_message="otra vez, entonces si checan buro?",
        recent_history=[("outbound", "Si, se revisa buro.")],
        action="lookup_faq",
        action_payload=action_payload,
        decision_payload={},
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        current_stage="potencialcliente",
        guardrails=[],
    )
    quote_frame = build_response_frame(
        user_message="otra vez, entonces si checan buro?",
        recent_history=[
            (
                "outbound",
                "La R4 250 CC de contado queda en $52,700. Enganche: $11,067. Pago quincenal: $1,792.",
            )
        ],
        action="lookup_faq",
        action_payload=action_payload,
        decision_payload={},
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        current_stage="potencialcliente",
        guardrails=[],
    )

    assert no_quote_frame.pending_flow is not None
    assert no_quote_frame.pending_flow.type == "quote"
    assert quote_frame.pending_flow is not None
    assert quote_frame.pending_flow.type == "ask_missing_documents"


def test_rejects_documents_before_understanding_explains_and_resumes_correct_step() -> None:
    response_frame = build_response_frame(
        user_message="primero explicame bien para que los ocupan",
        recent_history=[("outbound", "Ya tengo el plan. Falta aterrizar la cotizacion.")],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "requirements",
            "answer": "Los documentos sirven para revisar tu expediente antes de avanzar.",
            "answered_intents": ["requirements"],
            "requirements": {
                "missing": [
                    {"key": "INE_FRENTE", "label": "INE-FRENTE"},
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Domicilio"},
                ]
            },
        },
        decision_payload={},
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        current_stage="potencialcliente",
        guardrails=[],
    )

    rendered = render_response_frame_fallback_message(response_frame).casefold()
    assert response_frame.response_strategy == "answer_and_resume_flow"
    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.type == "quote"
    assert "documentos sirven" in rendered
    assert "cotizacion" in rendered
    assert "ine" not in rendered


def test_document_clarification_after_quote_resumes_missing_documents() -> None:
    response_frame = build_response_frame(
        user_message="que seria lo minimo que te mando primero",
        recent_history=[
            (
                "outbound",
                "La R4 250 CC queda en $55,335 de lista. Enganche: $11,067. Pago quincenal: $1,792.",
            )
        ],
        action="ask_clarification",
        action_payload={
            "status": "ok",
            "request_type": "clarify_ambiguous_direct_question",
            "suggested_clarification": "Me confirmas si quieres cotizacion o revisar otra cosa?",
            "requirements": {
                "missing": [
                    {"key": "INE_FRENTE", "label": "INE-FRENTE"},
                    {"key": "INE_ATRAS", "label": "INE-ATRAS"},
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Domicilio"},
                ]
            },
        },
        decision_payload={},
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        current_stage="potencialcliente",
        guardrails=[],
    )

    rendered = render_response_frame_fallback_message(response_frame).casefold()
    assert response_frame.response_strategy == "answer_and_resume_flow"
    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.type == "ask_missing_documents"
    assert response_frame.trace.pending_flow_recompute_reason == "document_question_after_quote"
    assert "ine" in rendered
    assert "domicilio" in rendered


def test_soft_close_blocked_when_next_real_step_exists() -> None:
    response_frame = build_response_frame(
        user_message="va",
        recent_history=[("outbound", "Para seguir, dime como recibes tus ingresos.")],
        action="soft_close",
        action_payload={"status": "ok"},
        decision_payload={},
        extracted_data={"MOTO": "R4 250 CC"},
        current_stage="potencialcliente",
        guardrails=[],
    )

    assert response_frame.response_strategy == "answer_and_resume_flow"
    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.payload["field"] == "CREDITO"
    assert response_frame.trace.soft_close_blocked_reason == "missing_credit_plan"


def test_pending_flow_recomputed_when_stale() -> None:
    response_frame = build_response_frame(
        user_message="donde estan?",
        recent_history=[("outbound", "Para seguir, dime cuanto tiempo llevas trabajando ahi.")],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "ubicacion",
            "answer": "Estamos en Monterrey, Nuevo Leon.",
            "answered_intents": ["ubicacion"],
            "resume_pending_action": {"type": "ask_field", "field": "FILTRO"},
        },
        decision_payload={},
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "FILTRO": "5 anos",
        },
        current_stage="potencialcliente",
        guardrails=[],
    )

    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.type == "quote"
    assert response_frame.trace.pending_flow_recompute_reason == (
        "pending_flow_contradicts_validated_state"
    )


def test_pending_flow_recomputed_from_documents_to_quote_when_quote_missing() -> None:
    response_frame = build_response_frame(
        user_message="buro tambien lo ven?",
        recent_history=[("outbound", "Ya tengo el plan. Falta aterrizar la cotizacion.")],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "answered_intents": ["buro"],
            "requirements": {
                "missing": [
                    {"key": "INE_FRENTE", "label": "INE-FRENTE"},
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Domicilio"},
                ]
            },
        },
        decision_payload={},
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        current_stage="potencialcliente",
        guardrails=[],
    )

    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.type == "quote"
    assert response_frame.trace.resume_missing_blocked_reason == "quote_missing"


def test_pending_flow_recomputed_from_documents_to_income_clarification_when_income_ambiguous() -> None:
    response_frame = build_response_frame(
        user_message="que papeles son?",
        recent_history=[("outbound", "Para seguir, mandame primero INE por ambos lados.")],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "requirements",
            "answer": "Los documentos dependen del plan que usemos.",
            "answered_intents": ["requirements"],
            "requirements": {
                "missing": [
                    {"key": "INE_FRENTE", "label": "INE-FRENTE"},
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Domicilio"},
                ]
            },
            "policy_trace": {
                "income_ambiguity": True,
                "needs_income_disambiguation": True,
            },
        },
        decision_payload={},
        extracted_data={"MOTO": "R4 250 CC"},
        current_stage="potencialcliente",
        guardrails=[],
    )

    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.type == "ask_field"
    assert response_frame.pending_flow.payload["field"] == "CREDITO"
    assert response_frame.trace.resume_missing_blocked_reason == "income_ambiguity"


def test_response_contract_rephrases_exact_repeat_from_response_frame() -> None:
    repeated = "Si, se revisa buro.\n\nY para seguir, todavia faltaria: parte de enfrente de tu INE."
    response_frame = build_response_frame(
        user_message="revisan buro?",
        recent_history=[
            ("outbound", repeated),
            ("inbound", "revisan buro?"),
        ],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "answered_intents": ["buro"],
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE"],
            },
        },
        decision_payload={"resume_pending_action": {"type": "ask_missing_documents", "missing": ["INE-FRENTE"]}},
        extracted_data={},
        current_stage="credito",
        guardrails=[],
    )
    composer_output = ComposerOutput(messages=[repeated], suggested_handoff=None)

    result = apply_response_contract(
        ResponseContractRequest(
            action="lookup_faq",
            action_payload={
                "status": "ok",
                "topic": "buro",
                "answer": "Si, se revisa buro.",
                "answered_intents": ["buro"],
                "resume_pending_action": {
                    "type": "ask_missing_documents",
                    "missing": ["INE-FRENTE"],
                },
            },
            composer_output=composer_output,
            state={},
            response_frame=response_frame,
            inbound_text="revisan buro?",
        )
    )

    assert result.contract_applied is True
    assert result.contract_reason == "response_frame_exact_repeat_rephrased"
    assert result.outbound_messages is not None
    assert result.outbound_messages[0] != repeated
    assert "buro" in result.outbound_messages[0].lower()
    assert "parte de enfrente de tu INE" in result.outbound_messages[0]


def test_response_contract_rephrases_recent_semantic_duplicate_from_response_frame() -> None:
    previous = (
        "Sobre eso, Si, se revisa buro.\n\n"
        "Y para seguir, todavia faltaria: INE por ambos lados y comprobante de domicilio reciente."
    )
    candidate = (
        "Si, se revisa buro.\n\n"
        "Y para seguir, todavia faltaria: INE por ambos lados y comprobante de domicilio reciente."
    )
    response_frame = build_response_frame(
        user_message="otra vez, entonces si checan buro?",
        recent_history=[
            ("outbound", previous),
            ("inbound", "otra vez, entonces si checan buro?"),
        ],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "answered_intents": ["buro"],
                "resume_pending_action": {
                    "type": "ask_missing_documents",
                    "missing": ["INE-FRENTE", "INE-ATRAS", "COMPROBANTE_DOMICILIO"],
                },
            },
        decision_payload={
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE", "INE-ATRAS", "COMPROBANTE_DOMICILIO"],
            }
        },
        extracted_data={},
        current_stage="credito",
        guardrails=[],
    )
    composer_output = ComposerOutput(messages=[candidate], suggested_handoff=None)

    result = apply_response_contract(
        ResponseContractRequest(
            action="lookup_faq",
            action_payload={
                "status": "ok",
                "topic": "buro",
                "answer": "Si, se revisa buro.",
                "answered_intents": ["buro"],
                "resume_pending_action": {
                    "type": "ask_missing_documents",
                    "missing": ["INE-FRENTE", "INE-ATRAS", "COMPROBANTE_DOMICILIO"],
                },
            },
            composer_output=composer_output,
            state={},
            response_frame=response_frame,
            inbound_text="otra vez, entonces si checan buro?",
            history=[
                ("outbound", previous),
                ("inbound", "otra vez, entonces si checan buro?"),
            ],
        )
    )

    assert result.contract_applied is True
    assert result.contract_reason == "response_frame_recent_duplicate_rephrased"
    assert result.outbound_messages is not None
    assert result.outbound_messages[0] != candidate
    assert "buro" in result.outbound_messages[0].lower()
    assert "INE por ambos lados" in result.outbound_messages[0]
    assert "domicilio" in result.outbound_messages[0]


def test_composer_output_rejects_next_action_control_fields() -> None:
    with pytest.raises(ValidationError):
        ComposerOutput.model_validate(
            {
                "messages": ["Voy con eso."],
                "suggested_handoff": None,
                "next_action": "quote",
            }
        )


async def test_last_question_resolver_only_writes_from_configured_pending_confirmation() -> None:
    resolver = LastQuestionResolver()
    result = await resolver.resolve(
        _turn_input(
            text="si",
            pending_confirmation='{"yes":{"PLAN":"credito"},"no":{"PLAN":"contado"}}',
        )
    )

    assert result is not None
    assert result.can_write_state is True
    assert result.field_updates == {"PLAN": "credito"}


async def test_document_expectation_resolver_reports_real_missing_docs_without_writing() -> None:
    resolver = DocumentExpectationResolver()
    result = await resolver.resolve(
        _turn_input(
            text="ya te lo mande",
            extracted_data={
                "CREDITO": {"value": "Sin Comprobantes"},
                "INE_FRENTE": {"value": "ok"},
                "INE_ATRAS": {"value": "missing"},
            },
            pipeline=PipelineDefinition(
                stages=[StageDefinition(id="nuevo", actions_allowed=["ask_clarification"])],
                fallback="ask_clarification",
                document_requirements_field="CREDITO",
                document_requirements={"Sin Comprobantes": ["INE_FRENTE", "INE_ATRAS"]},
                documents_catalog=[
                    {"key": "INE_FRENTE", "label": "INE frente"},
                    {"key": "INE_ATRAS", "label": "INE atras"},
                ],
            ),
        )
    )

    assert result is not None
    assert result.can_write_state is False
    assert result.blocked_reason == "documents_cannot_be_marked_received_from_text"
    assert "INE frente" in (result.suggested_clarification or "")
    assert "INE atras" in (result.suggested_clarification or "")


async def test_reference_resolver_never_writes_without_confirmation() -> None:
    resolver = ReferenceResolver()
    result = await resolver.resolve(_turn_input(text="la roja"))

    assert result is not None
    assert result.can_write_state is False
    assert result.requires_confirmation is True
    assert result.blocked_reason == "no_clear_last_product"


def _turn_input(
    *,
    text: str,
    extracted_data: dict | None = None,
    pending_confirmation: str | None = None,
    pipeline: PipelineDefinition | None = None,
) -> object:
    from uuid import uuid4

    from atendia.contracts.turn_resolution import TurnResolverInput

    pipeline = pipeline or PipelineDefinition(
        stages=[StageDefinition(id="nuevo", actions_allowed=["ask_clarification"])],
        fallback="ask_clarification",
    )
    return TurnResolverInput(
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        inbound_text=text,
        nlu=NLUResult(
            intent=Intent.UNCLEAR,
            sentiment=Sentiment.NEUTRAL,
            confidence=0.5,
        ),
        state=ConversationState(
            conversation_id=str(uuid4()),
            tenant_id=str(uuid4()),
            current_stage="nuevo",
            stage_entered_at=datetime.now(UTC),
        ),
        extracted_data=extracted_data or {},
        history=[],
        pipeline=pipeline,
        pending_confirmation=pending_confirmation,
        current_stage="nuevo",
    )

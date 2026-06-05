from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from atendia.commercial_catalog_service import publish_authoring_catalog
from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.message import Attachment, Message, MessageDirection
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.db.models.agent import Agent
from atendia.db.models.commercial_catalog import Catalog, CatalogItem, CatalogItemPlan
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.db.models.message import MessageRow
from atendia.db.models.tenant import Tenant
from atendia.db.models.tenant_config import TenantBranding, TenantPipeline
from atendia.db.session import _get_factory
from atendia.runner.composer_openai import ComposerProviderError
from atendia.runner.composer_protocol import ComposerInput, ComposerOutput
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.document_language import join_humanized_documents
from atendia.runner.nlu_protocol import UsageMetadata
from atendia.runner.response_contract import _guard_composer_output
from atendia.runner.response_frame import build_response_frame, render_response_frame_fallback_message


class _NoAgentRunner(ConversationRunner):
    async def _load_agent(self, *, conversation_id, tenant_id):
        return None


class _ScriptedNLU:
    def __init__(self, scripts: dict[str, NLUResult]) -> None:
        self._scripts = scripts

    async def classify(self, **kwargs: object) -> tuple[NLUResult, UsageMetadata | None]:
        text = str(kwargs.get("text") or "").strip()
        result = self._scripts[text]
        return (
            result,
            UsageMetadata(
                model="scripted-nlu",
                tokens_in=1,
                tokens_out=1,
                cost_usd=Decimal("0"),
                latency_ms=1,
            ),
        )


class _FlowComposer:
    def __init__(self) -> None:
        self.inputs: list[ComposerInput] = []

    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        self.inputs.append(input)
        message = _compose_message(input)
        return (
            ComposerOutput(
                messages=[message],
                raw_llm_response=f'{{"messages":["{message.replace(chr(10), "\\n")}"]}}',
            ),
            UsageMetadata(
                model="scripted-composer",
                tokens_in=1,
                tokens_out=1,
                cost_usd=Decimal("0"),
                latency_ms=1,
            ),
        )


class _BadQuoteComposer(_FlowComposer):
    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        if input.action == "quote":
            self.inputs.append(input)
            message = "Para cotizarla, necesito saber cuanto tiempo llevas en tu empleo actual."
            return (
                ComposerOutput(
                    messages=[message],
                    raw_llm_response=f'{{"messages":["{message}"]}}',
                ),
                UsageMetadata(
                    model="bad-quote-composer",
                    tokens_in=1,
                    tokens_out=1,
                    cost_usd=Decimal("0"),
                    latency_ms=1,
                ),
            )
        return await super().compose(input=input)


class _SummaryAwareComposer(_FlowComposer):
    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        if input.action == "lookup_faq" and input.context_pack is not None:
            self.inputs.append(input)
            summary = input.context_pack.conversation_summary or ""
            payload = input.action_payload or {}
            if (
                "R4 250 CC" in summary
                and "Sin Comprobantes" in summary
                and "20%" in summary
            ):
                missing = input.context_pack.pending_to_resume or {}
                missing_text = join_humanized_documents(missing.get("missing", []))
                message = (
                    f"{payload.get('answer')}\n\n"
                    f"Para avanzar solo faltaria: {missing_text} y sigo con tu "
                    "R4 250 CC al 20%."
                )
            else:
                message = "No tengo memoria operativa suficiente para retomar el tramite."
            return (
                ComposerOutput(
                    messages=[message],
                    raw_llm_response=f'{{"messages":["{message.replace(chr(10), "\\n")}"]}}',
                ),
                UsageMetadata(
                    model="summary-aware-composer",
                    tokens_in=1,
                    tokens_out=1,
                    cost_usd=Decimal("0"),
                    latency_ms=1,
                ),
            )
        return await super().compose(input=input)


class _AnswerAndResumeLLMComposer(_FlowComposer):
    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        self.inputs.append(input)
        payload = input.action_payload or {}
        answers = payload.get("answers") if isinstance(payload.get("answers"), list) else []
        answer_text = "\n".join(
            str(item.get("answer") or "").strip()
            for item in answers
            if isinstance(item, dict) and str(item.get("answer") or "").strip()
        ).strip() or str(payload.get("answer") or "").strip()
        resume = input.context_pack.pending_to_resume if input.context_pack is not None else {}
        missing_text = join_humanized_documents((resume or {}).get("missing") or [])
        message = answer_text
        if missing_text:
            message = "\n\n".join(
                [
                    answer_text,
                    "Y para avanzar, todavia faltaria: " + missing_text + ".",
                ]
            )
        return (
            ComposerOutput(
                messages=[message],
                raw_llm_response=f'{{"messages":["{message.replace(chr(10), "\\n")}"]}}',
            ),
            UsageMetadata(
                model="openai",
                tokens_in=12,
                tokens_out=18,
                cost_usd=Decimal("0"),
                latency_ms=1,
            ),
        )


class _FailingComposer(_FlowComposer):
    async def compose(
        self,
        *,
        input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        self.inputs.append(input)
        raise ComposerProviderError(
            "composer down",
            usage=UsageMetadata(
                model="openai",
                tokens_in=0,
                tokens_out=0,
                cost_usd=Decimal("0"),
                latency_ms=1,
                fallback_used=False,
                error_type="TimeoutError",
            ),
        )


async def test_multiturn_credit_flow_accumulates_context_and_recomputes_quote() -> None:
    factory = _get_factory()
    session = factory()
    composer = _FlowComposer()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_runner_flow_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
        )
        runner = _NoAgentRunner(session, _primary_flow_nlu(), composer)

        turns = [
            "hola",
            "me interesa la r4",
            "a crédito",
            "por fuera",
            "20",
        ]
        traces = []
        for index, text in enumerate(turns, start=1):
            trace = await _run_persisted_turn(
                session=session,
                runner=runner,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                turn_number=index,
                text=text,
                sent_at=started_at + timedelta(minutes=index),
            )
            traces.append(trace)

        turn1, turn2, turn3, turn4, turn5 = traces

        assert turn1.state_before["current_stage"] == "nuevos"
        assert turn1.composer_input["action"] == "greet"
        assert turn1.state_after["current_stage"] == "nuevos"
        assert _resolver_layer(turn1)["attempts"] == []
        assert "cotizo" not in turn1.outbound_messages[0].casefold()
        assert "modelo" in turn1.outbound_messages[0].casefold()

        turn2_decision = _decision_layer(turn2)
        turn2_resolver = _resolver_layer(turn2)
        assert turn2.state_before["current_stage"] == "nuevos"
        assert turn2_decision["action_before_auto_enter"] == "ask_field"
        assert turn2_decision["action_after_recompute"] == "ask_credit_context"
        assert turn2.state_after["final_action"] == "ask_credit_context"
        assert turn2_resolver["selected_attempt"]["resolver"] == "catalog_resolver"
        assert turn2_resolver["selected_attempt"]["field_updates"] == {"MOTO": "R4 250 CC"}
        assert turn2_resolver["selected_attempt"]["evidence"][0]["type"] == "catalog_unique_match"
        assert turn2_decision["field_updates_approved"] == ["MOTO"]
        assert turn2.composer_input["decision_payload"]["field_updated"] == "MOTO"
        assert turn2.composer_input["decision_payload"]["evidence"] == "catalog_unique_match"
        assert turn2.composer_input["action_payload"]["request_type"] == "resolve_model"
        assert turn2.state_after["extracted_data"]["MOTO"]["value"] == "R4 250 CC"
        assert "ingresos" in turn2.outbound_messages[0].casefold()

        assert turn3.state_before["extracted_data"]["MOTO"]["value"] == "R4 250 CC"
        assert turn3.composer_input["action"] == "ask_credit_context"
        assert turn3.state_after["final_action"] == "ask_credit_context"
        assert "modelo" not in turn3.outbound_messages[0].casefold()
        assert "ingresos" in turn3.outbound_messages[0].casefold()

        turn4_decision = _decision_layer(turn4)
        assert _resolver_layer(turn4)["selected_attempt"]["resolver"] == "credit_plan_resolver"
        assert turn4_resolver_field(turn4, "CREDITO") == "Sin Comprobantes"
        assert turn4.state_after["current_stage"] == "potencialcliente"
        assert turn4_decision["stage_after_auto_enter"] == "potencialcliente"
        assert turn4_decision["recomputed_after_stage_change"] is True
        assert turn4_decision["action_after_recompute"] == "resolve_credit_plan"
        assert "20%" in turn4.outbound_messages[0]

        turn5_decision = _decision_layer(turn5)
        turn5_payload = turn5.composer_input["action_payload"]
        assert turn5.state_before["current_stage"] == "potencialcliente"
        assert turn5.state_after["final_action"] == "quote"
        assert turn5_payload["status"] == "ok"
        assert turn5_payload["resolved_sku"] == "R4-250"
        assert turn5_payload["requested_plan_code"] == "20%"
        assert turn5_payload["requirements"]["selection_key"] == "Sin Comprobantes"
        assert [tool["tool"] for tool in turn5_decision["executed_tools"]] == [
            "search_catalog",
            "quote",
        ]
        assert turn5.outbound_messages[0].startswith("La R4 250 CC de contado queda en")
        assert "Enganche: $11,067" in turn5.outbound_messages[0]

        history = turn5.composer_input["history"]
        assert history
        assert any("por fuera" in item[1].casefold() for item in history if item[0] == "inbound")
    finally:
        await session.rollback()
        await session.close()


async def test_ask_info_product_references_resolve_catalog_without_aggressive_greeting() -> None:
    for text in ("la r4", "quiero info de la r4"):
        trace = await _run_scenario(["hola", text])

        turn1, turn2 = trace
        assert _resolver_layer(turn1)["attempts"] == []
        assert "MOTO" not in turn1.state_after["extracted_data"]
        assert turn2.nlu_output["intent"] == "ASK_INFO"
        assert turn2.state_after["extracted_data"]["MOTO"]["value"] == "R4 250 CC"
        assert turn2.composer_input["decision_payload"]["evidence"] == "catalog_unique_match"


async def test_generic_credit_info_does_not_run_catalog_resolver() -> None:
    trace = await _run_scenario(["Hola quiero info de credito"])

    turn1 = trace[0]
    assert turn1.nlu_output["intent"] == "ASK_INFO"
    assert _resolver_layer(turn1)["attempts"] == []
    assert "MOTO" not in turn1.state_after["extracted_data"]


async def test_catalog_browsing_requests_use_structured_catalog_payload() -> None:
    factory = _get_factory()
    session = factory()
    composer = _FlowComposer()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_runner_flow_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
        )
        session.add(
            TenantBranding(
                tenant_id=tenant_id,
                default_messages={
                    "brand_facts": {
                        "catalog_url": "https://dinamomotos.com/catalogo.html",
                    }
                },
            )
        )
        session.add(
            Agent(
                tenant_id=tenant_id,
                name="Francisco",
                role="sales_agent",
                is_default=True,
                system_prompt="Responde como asesor y usa evidencia real.",
            )
        )
        await session.flush()
        runner = ConversationRunner(session, _primary_flow_nlu(), composer)

        turn1 = await _run_persisted_turn(
            session=session,
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=1,
            text="A ver las motos",
            sent_at=started_at + timedelta(minutes=1),
        )
        turn2 = await _run_persisted_turn(
            session=session,
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=2,
            text="Solo esas?",
            sent_at=started_at + timedelta(minutes=2),
        )

        assert turn1.composer_input["action"] == "search_catalog"
        assert turn1.composer_input["action_payload"]["request_type"] == "catalog_browse"
        assert turn1.composer_input["action_payload"]["browse_intent"] == "catalog_overview"
        assert turn1.composer_input["action_payload"]["total_results"] == 3
        assert "catalogo" in turn1.outbound_messages[0].casefold()
        assert "https://dinamomotos.com/catalogo.html" in turn1.outbound_messages[0]
        assert "que modelo te interesa" not in turn1.outbound_messages[0].casefold()

        turn2_decision = _decision_layer(turn2)
        assert turn2.composer_input["action"] == "search_catalog"
        assert turn2.composer_input["action_payload"]["browse_intent"] == "catalog_more"
        assert turn2_decision["executed_tools"][0]["mode"] == "catalog_browse"
        assert "No, tenemos 3 modelos activos." in turn2.outbound_messages[0]
        assert "antiguedad" not in turn2.outbound_messages[0].casefold()
    finally:
        await session.rollback()
        await session.close()


async def test_plan_model_question_includes_catalog_link_when_model_is_missing() -> None:
    output = ComposerOutput(
        messages=["Perfecto, ese plan maneja 20%. Que modelo te interesa?"],
        raw_llm_response="{}",
    )

    event = _guard_composer_output(
        composer_output=output,
        decision_action="agent_response",
        action_payload={},
        extracted_data={
            "CREDITO": {"value": "Sin Comprobantes"},
            "ENGANCHE": {"value": "20%"},
        },
        brand_facts={"catalog_url": "https://dinamomotos.com/catalogo.html"},
    )

    assert event is not None
    assert event["overwrite_blocked_reason"] == "model_question_catalog_link_added"
    assert "20%" in output.messages[0]
    assert "catalogo" in output.messages[0].casefold()
    assert "https://dinamomotos.com/catalogo.html" in output.messages[0]
    assert "Dime cual moto" in output.messages[0]


async def test_multiturn_unknown_model_does_not_write_or_quote() -> None:
    trace = await _run_scenario(["buenas", "italika tc 250"])

    turn2 = trace[1]
    resolver = _resolver_layer(turn2)
    extracted = turn2.state_after["extracted_data"]
    assert resolver["selected_attempt"]["resolver"] == "catalog_resolver"
    assert resolver["selected_attempt"]["blocked_reason"] in {
        "no_catalog_match",
        "catalog_match_below_threshold",
        "catalog_query_low_coverage",
    }
    assert "MOTO" not in extracted
    assert turn2.state_after["final_action"] == "ask_clarification"
    assert turn2.composer_input["action"] in {"ask_field", "ask_clarification"}
    assert turn2.composer_input["decision_payload"]["decision"] in {
        "clarification_required",
        "product_not_found",
    }
    outbound = turn2.outbound_messages[0].casefold()
    assert "cotiz" not in outbound
    assert any(term in outbound for term in ("modelo", "catalogo", "opcion parecida"))


async def test_multiturn_reference_uses_last_model_context() -> None:
    trace = await _run_scenario(["hola", "me interesa la r4", "la roja"])

    turn3 = trace[2]
    resolver = _resolver_layer(turn3)
    assert resolver["selected_attempt"]["resolver"] == "reference_resolver"
    assert resolver["selected_attempt"]["blocked_reason"] == "reference_requires_confirmation"
    assert turn3.composer_input["action"] == "ask_clarification"
    assert "R4 250 CC" in turn3.outbound_messages[0]


async def test_multiturn_yes_without_pending_confirmation_does_not_write_state() -> None:
    trace = await _run_scenario(["hola", "r4", "sí"])

    turn3 = trace[2]
    resolver = _resolver_layer(turn3)
    assert resolver["attempts"][0]["resolver"] == "last_question_resolver"
    assert resolver["attempts"][0]["blocked_reason"] == "no_pending_confirmation"
    assert (turn3.state_after or {}).get("pending_confirmation") is None
    assert turn3.state_after["extracted_data"]["MOTO"]["value"] == "R4 250 CC"
    assert turn3.composer_input["action"] in {"ask_field", "ask_clarification"}


async def test_multiturn_document_claim_does_not_mark_docs_received_from_text() -> None:
    trace = await _run_scenario(["hola", "r4", "por fuera", "ya te lo mandé"])

    turn4 = trace[3]
    resolver = _resolver_layer(turn4)
    extracted = turn4.state_after["extracted_data"]
    assert resolver["selected_attempt"]["resolver"] == "document_expectation_resolver"
    assert (
        resolver["selected_attempt"]["blocked_reason"]
        == "documents_cannot_be_marked_received_from_text"
    )
    assert "INE_FRENTE" not in extracted
    assert "INE_ATRAS" not in extracted
    assert "comprobante de domicilio reciente" in turn4.outbound_messages[0]


async def test_protected_field_conflict_blocks_filtro_overwrite() -> None:
    trace = await _run_scenario(["hola", "r4", "por fuera", "20", "15 anos", "3 meses"])

    turn5 = trace[4]
    turn6 = trace[5]
    assert turn5.state_after["extracted_data"]["FILTRO"]["value"] is True
    assert turn6.state_after["extracted_data"]["FILTRO"]["value"] is True
    decision = _decision_layer(turn6)
    assert decision["conflict_detected"] is True
    assert decision["protected_field"] == "FILTRO"
    assert decision["overwrite_allowed"] is False
    assert decision["overwrite_blocked_reason"] == "protected_field_conflict_requires_confirmation"
    assert "Quieres corregirlo" in turn6.outbound_messages[0]


async def test_protected_field_conflict_blocks_credit_overwrite() -> None:
    trace = await _run_scenario(["hola", "r4", "por fuera", "20", "Por tarjeta"])

    turn5 = trace[4]
    extracted = turn5.state_after["extracted_data"]
    decision = _decision_layer(turn5)
    assert extracted["CREDITO"]["value"] == "Sin Comprobantes"
    assert extracted["ENGANCHE"]["value"] == "20%"
    assert decision["conflict_detected"] is True
    assert decision["protected_field"] == "CREDITO"
    assert decision["overwrite_allowed"] is False


async def test_quote_payload_cannot_be_replaced_by_repeated_question() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20"],
        composer=_BadQuoteComposer(),
    )

    turn4 = trace[3]
    decision = _decision_layer(turn4)
    assert turn4.composer_input["action"] == "quote"
    assert decision["repeated_question_blocked"] is True
    assert decision["protected_field"] == "FILTRO"
    assert "Enganche: $11,067" in turn4.outbound_messages[0]


async def test_pack_faq_answers_and_resumes_missing_documents() -> None:
    trace = await _run_scenario(["hola", "r4", "por fuera", "20", "revisan buro?"])

    turn5 = trace[4]
    payload = turn5.composer_input["action_payload"]
    decision = _decision_layer(turn5)

    assert turn5.composer_input["action"] == "lookup_faq"
    assert turn5.state_after["final_action"] == "lookup_faq"
    assert payload["status"] == "ok"
    assert payload["source"]["type"] == "knowledge_pack"
    assert payload["source"]["knowledge_pack_version"] == "2026-05-23"
    assert payload["topic"] == "buro"
    assert payload["answer"] == "Si, se revisa buro."
    assert payload["resume_pending_action"] == {
        "type": "ask_missing_documents",
        "missing": ["INE-FRENTE", "Domicilio", "INE-ATRAS"],
    }
    assert turn5.state_after["missing_documents_after_turn"] == [
        "INE-FRENTE",
        "Domicilio",
        "INE-ATRAS",
    ]
    assert decision["pending_question"] == {
        "type": "ask_missing_documents",
        "missing": ["INE-FRENTE", "Domicilio", "INE-ATRAS"],
    }
    context_pack = turn5.composer_input["context_pack"]
    assert context_pack["user_message"] == "revisan buro?"
    assert context_pack["must_answer_first"] == (
        "Responder primero la duda directa del cliente sobre buro."
    )
    assert context_pack["business_facts"]["faq_answer"] == "Si, se revisa buro."
    assert context_pack["pending_to_resume"] == {
        "type": "ask_missing_documents",
        "missing": ["INE-FRENTE", "Domicilio", "INE-ATRAS"],
    }
    assert context_pack["state_facts"]["documentos_faltantes"] == [
        "INE-FRENTE",
        "Domicilio",
        "INE-ATRAS",
    ]
    assert any(
        "No ignores la duda directa" in rule
        for rule in context_pack["must_not_say"]
    )
    assert [tool["tool"] for tool in decision["executed_tools"]] == ["lookup_faq"]
    assert "se revisa buro" in turn5.outbound_messages[0].casefold()
    assert "INE por ambos lados" in turn5.outbound_messages[0]
    assert "comprobante de domicilio reciente" in turn5.outbound_messages[0]


async def test_composer_uses_llm_for_answer_and_resume_flow_when_available() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    turn5 = trace[4]

    assert turn5.state_after["composer_llm_called"] is True
    assert turn5.state_after["composer_mode"] == "llm"
    assert turn5.state_after["composer_provider"] == "_AnswerAndResumeLLMComposer"
    assert turn5.state_after["composer_input_has_current_message"] is True
    assert turn5.state_after["composer_input_has_recent_history"] is True
    assert turn5.state_after["composer_input_has_resume_pending_action"] is True
    assert turn5.state_after["response_frame_present"] is True
    assert turn5.state_after["response_frame_valid"] is True
    assert turn5.state_after["response_frame_strategy"] == "answer_and_resume_flow"
    assert "se revisa buro" in turn5.outbound_messages[0].casefold()
    assert "INE por ambos lados" in turn5.outbound_messages[0]


async def test_composer_input_for_answer_and_resume_contains_current_message_and_history() -> None:
    composer = _AnswerAndResumeLLMComposer()
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=composer,
    )

    turn5 = trace[4]
    composer_input = composer.inputs[-1]
    context_pack = composer_input.context_pack
    response_frame = composer_input.response_frame

    assert context_pack is not None
    assert response_frame is not None
    assert context_pack.user_message == "revisan buro?"
    assert context_pack.recent_history
    assert response_frame.current_customer_message == "revisan buro?"
    assert response_frame.response_strategy == "answer_and_resume_flow"
    assert response_frame.answered_intents == ["buro"]
    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.type == "ask_missing_documents"
    assert response_frame.pending_flow.payload["missing"] == [
        "INE-FRENTE",
        "Domicilio",
        "INE-ATRAS",
    ]
    assert composer_input.action_payload["answered_intents"] == ["buro"]
    assert composer_input.action_payload["resume_pending_action"] == {
        "type": "ask_missing_documents",
        "missing": ["INE-FRENTE", "Domicilio", "INE-ATRAS"],
    }
    assert turn5.state_after["composer_input_has_response_frame"] is True
    assert turn5.state_after["composer_input_has_answered_intents"] is True
    assert turn5.state_after["composer_input_has_validated_answers"] is True
    assert turn5.state_after["composer_input_has_pending_flow"] is True
    assert turn5.state_after["composer_input_has_resume_pending_action"] is True


async def test_response_frame_is_required_for_customer_visible_output() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    turn5 = trace[4]

    assert turn5.outbound_messages
    assert turn5.state_after["response_frame_present"] is True
    assert turn5.state_after["response_frame_valid"] is True
    assert turn5.state_after["response_frame"]["current_customer_message"] == "revisan buro?"
    assert turn5.state_after["response_frame"]["pending_flow"]["type"] == "ask_missing_documents"


async def test_composer_receives_response_frame_for_answer_and_resume() -> None:
    composer = _AnswerAndResumeLLMComposer()
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=composer,
    )

    turn5 = trace[4]
    composer_input = composer.inputs[-1]

    assert composer_input.response_frame is not None
    assert composer_input.response_frame.current_customer_message == "revisan buro?"
    assert composer_input.response_frame.response_strategy == "answer_and_resume_flow"
    assert composer_input.response_frame.validated_answers["buro"].text == "Si, se revisa buro."
    assert composer_input.response_frame.pending_flow is not None
    assert composer_input.response_frame.anti_repetition is not None
    assert turn5.state_after["composer_input_has_response_frame"] is True
    assert turn5.state_after["composer_input_has_current_message"] is True
    assert turn5.state_after["composer_input_has_recent_history"] is True
    assert turn5.state_after["composer_input_has_validated_answers"] is True
    assert turn5.state_after["composer_input_has_pending_flow"] is True
    assert turn5.state_after["composer_input_has_anti_repetition"] is True


async def test_response_frame_created_for_buro_while_missing_ine() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "revisan buro?"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    turn4 = trace[3]
    response_frame = turn4.state_after["response_frame"]

    assert turn4.state_after["response_frame_present"] is True
    assert turn4.state_after["response_frame_valid"] is True
    assert turn4.state_after["response_frame_strategy"] == "answer_and_resume_flow"
    assert response_frame["current_customer_message"] == "revisan buro?"
    assert response_frame["pending_flow"]["type"] == "ask_missing_documents"
    assert response_frame["validated_answers"]["buro"]["text"]


async def test_response_frame_created_for_location_while_missing_document() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "ubicacion"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    turn4 = trace[3]
    response_frame = turn4.state_after["response_frame"]

    assert turn4.state_after["response_frame_present"] is True
    assert turn4.state_after["response_frame_valid"] is True
    assert turn4.state_after["response_frame_strategy"] == "answer_and_resume_flow"
    assert response_frame["current_customer_message"] == "ubicacion"
    assert response_frame["pending_flow"]["type"] == "ask_missing_documents"
    assert response_frame["validated_answers"]["ubicacion"]["text"]


def test_response_frame_converts_ask_documents_to_answer_and_resume_when_intent_exists() -> None:
    response_frame = build_response_frame(
        user_message="revisan buro?",
        recent_history=[
            ("outbound", "Para avanzar faltaria: INE-FRENTE."),
            ("inbound", "revisan buro?"),
        ],
        action="classify_document",
        action_payload={
            "request_type": "ask_missing_document",
            "answers": [
                {
                    "topic": "buro",
                    "answer": "Si, se revisa buro.",
                    "source": "faq",
                    "confidence": 1.0,
                }
            ],
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE", "Domicilio"],
            },
        },
        decision_payload={},
        extracted_data={"CREDITO": "Sin Comprobantes", "MOTO": "R4 250 CC", "ENGANCHE": "20%"},
        current_stage="potencialcliente",
        guardrails=["No expongas campos tecnicos."],
    )

    assert response_frame.response_strategy == "answer_and_resume_flow"
    assert "buro" in response_frame.current_intents
    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.type == "ask_missing_documents"
    assert response_frame.validated_answers["buro"].text == "Si, se revisa buro."


def test_response_frame_contains_current_message_history_pending_flow() -> None:
    response_frame = build_response_frame(
        user_message="donde estan?",
        recent_history=[
            ("outbound", "Para avanzar faltaria: INE-FRENTE, Domicilio."),
            ("inbound", "donde estan?"),
        ],
        action="lookup_faq",
        action_payload={
            "topic": "ubicacion",
            "answer": "Estamos en Monterrey, Nuevo Leon.",
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE", "Domicilio"],
            },
        },
        decision_payload={},
        extracted_data={"CREDITO": "Sin Comprobantes"},
        current_stage="potencialcliente",
        guardrails=["No inventes direccion."],
    )

    assert response_frame.current_customer_message == "donde estan?"
    assert response_frame.recent_history == [
        "outbound: Para avanzar faltaria: INE-FRENTE, Domicilio.",
        "inbound: donde estan?",
    ]
    assert response_frame.pending_flow is not None
    assert response_frame.pending_flow.payload["missing"] == ["INE-FRENTE", "Domicilio"]
    assert response_frame.trace.frame_valid is True


def test_credit_plan_resolution_fallback_does_not_render_documents_before_quote() -> None:
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

    rendered = render_response_frame_fallback_message(response_frame).casefold()

    assert "nomina tarjeta" in rendered
    assert "ine" not in rendered
    assert "domicilio" not in rendered
    assert "tiempo" in rendered or "antiguedad" in rendered


def test_response_frame_has_anti_repetition_when_document_prompt_repeated() -> None:
    response_frame = build_response_frame(
        user_message="revisan buro?",
        recent_history=[
            ("outbound", "Para avanzar faltaria: INE-FRENTE."),
            ("inbound", "ok"),
            ("outbound", "Para avanzar faltaria: INE-FRENTE."),
            ("inbound", "revisan buro?"),
        ],
        action="lookup_faq",
        action_payload={
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "resume_pending_action": {
                "type": "ask_missing_documents",
                "missing": ["INE-FRENTE"],
            },
        },
        decision_payload={},
        extracted_data={"CREDITO": "Sin Comprobantes"},
        current_stage="potencialcliente",
        guardrails=[],
    )

    assert response_frame.anti_repetition.repeated_prompt_count >= 1
    assert response_frame.anti_repetition.last_document_prompt is not None
    assert response_frame.anti_repetition.avoid_same_document_prompt is True
    assert response_frame.composer_instructions.avoid_exact_repeat is True


async def test_composer_fallback_reason_is_traced_when_llm_fails() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=_FailingComposer(),
    )

    turn5 = trace[4]
    outbound = turn5.outbound_messages[0]

    assert turn5.state_after["composer_llm_called"] is True
    assert turn5.state_after["composer_mode"] == "guarded"
    assert turn5.state_after["composer_fallback_reason"] == "TimeoutError"
    assert turn5.state_after["composer_guard_applied"] is True
    assert turn5.state_after["composer_input_has_response_frame"] is True
    assert turn5.state_after["composer_input_has_validated_answers"] is True
    assert turn5.state_after["composer_input_has_pending_flow"] is True
    assert "buro" in outbound.casefold()
    assert "INE por ambos lados" in outbound
    assert turn5.state_after["fallback_preserved_response_frame"] is True
    assert turn5.state_after["fallback_generated_customer_visible"] is True


async def test_composer_failure_fallback_preserves_answer_and_resume_frame() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=_FailingComposer(),
    )

    turn5 = trace[4]
    response_frame = turn5.state_after["response_frame"]

    assert turn5.state_after["response_frame_present"] is True
    assert turn5.state_after["fallback_preserved_response_frame"] is True
    assert response_frame["validated_answers"]["buro"]["text"] == "Si, se revisa buro."
    assert response_frame["pending_flow"]["type"] == "ask_missing_documents"
    assert turn5.outbound_messages
    assert "buro" in turn5.outbound_messages[0].casefold()
    assert "INE por ambos lados" in turn5.outbound_messages[0]


async def test_composer_failure_does_not_emit_generic_prompt_when_frame_has_answer() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=_FailingComposer(),
    )

    outbound = trace[4].outbound_messages[0].casefold()

    assert "ahorita solo necesito el siguiente dato" not in outbound
    assert "buro" in outbound


def test_invalid_frame_fallback_is_traced_and_safe() -> None:
    from atendia.runner.conversation_runner import _traced_fallback_output

    composer_output, response_frame, preserved, generated = _traced_fallback_output(
        response_frame=None,
        action="ask_credit_context",
        action_payload={"status": "ok", "request_type": "ask_income_type"},
        inbound_text="quiero seguir",
        fallback_reason="ResponseFrameInvalid",
        response_frame_reason="minimal_error_frame",
        response_frame_source="pytest",
    )

    assert preserved is False
    assert generated is True
    assert response_frame.trace.frame_valid is True
    assert response_frame.response_strategy == "handoff"
    assert composer_output.messages
    assert "recibes tus ingresos" in composer_output.messages[0].casefold()


async def test_composer_trace_records_llm_or_fallback_reason() -> None:
    llm_trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=_AnswerAndResumeLLMComposer(),
    )
    fallback_trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=_FailingComposer(),
    )

    llm_turn = llm_trace[4]
    fallback_turn = fallback_trace[4]

    assert llm_turn.state_after["composer_mode"] == "llm"
    assert llm_turn.state_after["composer_llm_called"] is True
    assert llm_turn.state_after["composer_provider"] == "_AnswerAndResumeLLMComposer"
    assert llm_turn.state_after["composer_input_has_response_frame"] is True
    assert llm_turn.state_after["final_response_source"]
    assert fallback_turn.state_after["composer_fallback_reason"] == "TimeoutError"
    assert fallback_turn.state_after["composer_guard_applied"] is True
    assert fallback_turn.state_after["final_response_source"]


async def test_live_like_buro_while_missing_ine_uses_llm_or_traced_fallback() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "revisan buro?"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    turn5 = trace[4]

    assert turn5.state_after["final_action"] == "lookup_faq"
    assert turn5.state_after["composer_mode"] in {"llm", "guarded", "fallback"}
    if turn5.state_after["composer_mode"] == "fallback":
        assert turn5.state_after["composer_fallback_reason"]
    else:
        assert turn5.state_after["composer_llm_called"] is True
    assert "buro" in turn5.outbound_messages[0].casefold()
    assert "INE por ambos lados" in turn5.outbound_messages[0]


async def test_safe_reply_uses_response_frame() -> None:
    factory = _get_factory()
    session = factory()
    composer = _FlowComposer()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    safe_template = "Te comparto el horario en un momento."
    try:
        await _seed_runner_flow_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
        )
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        tenant.config = {
            **dict(tenant.config or {}),
            "operational_policy_config": {
                "version": 1,
                "tenant_id": str(tenant_id),
                "categories": [
                    {
                        "id": "faq",
                        "risk_level": "low",
                        "signals": {
                            "keywords": ["horario"],
                            "semantic_examples": ["cual es su horario"],
                        },
                        "pause_rules": {
                            "pause_bot": False,
                            "block_pipeline": True,
                            "auto_reply_allowed": True,
                            "copilot_only": False,
                        },
                        "blocked_actions": ["continue_sales_funnel"],
                        "response_template_id": "hours_template",
                    }
                ],
                "templates": {"hours_template": safe_template},
            },
        }
        await session.flush()
        runner = _NoAgentRunner(session, _primary_flow_nlu(), composer)

        trace = await _run_persisted_turn(
            session=session,
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=1,
            text="cual es su horario?",
            sent_at=started_at,
        )

        assert trace.outbound_messages
        assert trace.state_after["response_frame_present"] is True
        assert trace.state_after["response_frame_strategy"] == "operational_safe_reply"
        assert trace.state_after["safe_reply_wrapped_in_response_frame"] is True
    finally:
        await session.rollback()
        await session.close()


async def test_safe_reply_does_not_emit_operational_template_directly() -> None:
    factory = _get_factory()
    session = factory()
    composer = _FlowComposer()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    safe_template = "Te comparto el horario en un momento."
    try:
        await _seed_runner_flow_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
        )
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        tenant.config = {
            **dict(tenant.config or {}),
            "operational_policy_config": {
                "version": 1,
                "tenant_id": str(tenant_id),
                "categories": [
                    {
                        "id": "faq",
                        "risk_level": "low",
                        "signals": {"keywords": ["horario"]},
                        "pause_rules": {
                            "pause_bot": False,
                            "block_pipeline": True,
                            "auto_reply_allowed": True,
                            "copilot_only": False,
                        },
                        "blocked_actions": ["continue_sales_funnel"],
                        "response_template_id": "hours_template",
                    }
                ],
                "templates": {"hours_template": safe_template},
            },
        }
        await session.flush()
        runner = _NoAgentRunner(session, _primary_flow_nlu(), composer)

        trace = await _run_persisted_turn(
            session=session,
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=1,
            text="horario",
            sent_at=started_at,
        )

        assert trace.outbound_messages[0] != safe_template
        assert trace.outbound_messages[0].casefold().startswith("sobre eso")
    finally:
        await session.rollback()
        await session.close()


async def test_safe_reply_trace_marks_operational_frame() -> None:
    factory = _get_factory()
    session = factory()
    composer = _FlowComposer()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    try:
        await _seed_runner_flow_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
        )
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None
        tenant.config = {
            **dict(tenant.config or {}),
            "operational_policy_config": {
                "version": 1,
                "tenant_id": str(tenant_id),
                "categories": [
                    {
                        "id": "faq",
                        "risk_level": "low",
                        "signals": {"keywords": ["horario"]},
                        "pause_rules": {
                            "pause_bot": False,
                            "block_pipeline": True,
                            "auto_reply_allowed": True,
                            "copilot_only": False,
                        },
                        "blocked_actions": ["continue_sales_funnel"],
                        "response_template_id": "hours_template",
                    }
                ],
                "templates": {"hours_template": "Te comparto el horario en un momento."},
            },
        }
        await session.flush()
        runner = _NoAgentRunner(session, _primary_flow_nlu(), composer)

        trace = await _run_persisted_turn(
            session=session,
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=1,
            text="horario",
            sent_at=started_at,
        )

        assert trace.state_after["safe_reply_wrapped_in_response_frame"] is True
        assert trace.state_after["composer_fallback_reason"] == "operational_safe_reply"
        assert trace.state_after["fallback_generated_customer_visible"] is True
        assert trace.state_after["response_frame"]["trace"]["response_frame_source"] == "conversation_control"
    finally:
        await session.rollback()
        await session.close()


def test_sales_policy_prompt_override_is_not_customer_visible_directly() -> None:
    response_frame = build_response_frame(
        user_message="que requisitos piden?",
        recent_history=[("inbound", "que requisitos piden?")],
        action="ask_credit_context",
        action_payload={
            "status": "ok",
            "request_type": "ask_income_type",
            "field_name": "CREDITO",
            "prompt_override": "Para orientarte mejor, dime como recibes tus ingresos.",
        },
        decision_payload={},
        extracted_data={},
        current_stage="nuevos",
        guardrails=[],
    )

    rendered = render_response_frame_fallback_message(response_frame)

    assert "prompt_override" in response_frame.validated_answers
    assert response_frame.validated_answers["prompt_override"].must_include is False
    assert rendered != "Para orientarte mejor, dime como recibes tus ingresos."


def test_policy_payload_passes_through_response_frame() -> None:
    response_frame = build_response_frame(
        user_message="que requisitos piden?",
        recent_history=[("inbound", "que requisitos piden?")],
        action="ask_credit_context",
        action_payload={
            "status": "ok",
            "request_type": "ask_income_type",
            "field_name": "CREDITO",
            "prompt_override": "Para orientarte mejor, dime como recibes tus ingresos.",
        },
        decision_payload={},
        extracted_data={},
        current_stage="nuevos",
        guardrails=[],
    )

    assert response_frame.trace.frame_valid is True
    assert response_frame.response_strategy == "answer_and_resume_flow"


async def test_buro_while_missing_ine_composer_answers_buro_then_resumes_ine() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "revisan buro?"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    turn4 = trace[3]
    outbound = turn4.outbound_messages[0].casefold()

    assert turn4.state_after["final_action"] == "lookup_faq"
    assert turn4.state_after["response_frame_strategy"] == "answer_and_resume_flow"
    assert "buro" in outbound
    assert "ine por ambos lados" in outbound
    assert "mandame tu ine" not in outbound


async def test_location_while_missing_document_answers_location_then_resumes() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "ubicacion"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    turn4 = trace[3]
    outbound = turn4.outbound_messages[0].casefold()

    assert turn4.state_after["final_action"] == "lookup_faq"
    assert turn4.state_after["response_frame_strategy"] == "answer_and_resume_flow"
    assert "monterrey" in outbound
    assert "ine por ambos lados" in outbound


async def test_payoff_while_missing_document_answers_payoff_then_resumes() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "puedo liquidar antes?"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    turn4 = trace[3]
    outbound = turn4.outbound_messages[0].casefold()

    assert turn4.state_after["final_action"] == "lookup_faq"
    assert turn4.state_after["response_frame_strategy"] == "answer_and_resume_flow"
    assert "liquid" in outbound
    assert "ine por ambos lados" in outbound


async def test_cash_price_request_does_not_start_credit_flow() -> None:
    trace = await _run_scenario(
        ["la R4 de contado cuanto"],
        nlu_scripts_override={
            "la R4 de contado cuanto": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
        },
    )

    turn = trace[0]
    outbound = " ".join(turn.outbound_messages or []).casefold()
    response_frame = turn.state_after["response_frame"]

    assert turn.state_after["final_action"] == "quote"
    assert response_frame["response_strategy"] == "quote_cash"
    assert response_frame["known_customer_state"]["active_purchase_mode"] == "cash"
    assert response_frame["known_customer_state"]["quote_mode"] == "cash"
    assert response_frame["pending_flow"] is None
    assert "contado" in outbound
    assert "ingresos" not in outbound
    assert "antiguedad" not in outbound
    assert "ine" not in outbound


async def test_cash_then_credit_switch_starts_credit_flow_without_losing_model() -> None:
    trace = await _run_scenario(
        ["la R4 de contado cuanto", "y a credito?"],
        nlu_scripts_override={
            "la R4 de contado cuanto": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
            "y a credito?": _nlu(Intent.ASK_PRICE),
            "me depositan nomina": _nlu(Intent.ASK_INFO),
            "tarjeta": _nlu(
                Intent.ASK_INFO,
                entities={"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
            ),
        },
    )

    cash_turn = trace[0]
    credit_turn = trace[1]
    response_frame = credit_turn.state_after["response_frame"]

    assert cash_turn.state_after["final_action"] == "quote"
    assert cash_turn.state_after["response_frame"]["known_customer_state"]["active_purchase_mode"] == "cash"
    assert credit_turn.state_after["final_action"] == "ask_credit_context"
    assert credit_turn.state_after["extracted_data"]["MOTO"]["value"] == "R4 250 CC"
    assert response_frame["known_customer_state"]["active_purchase_mode"] == "credit"
    assert response_frame["pending_flow"]["type"] == "ask_field"
    assert response_frame["pending_flow"]["payload"]["field"] == "CREDITO"
    assert "INE" not in " ".join(credit_turn.outbound_messages or [])


async def test_credit_then_cash_switch_answers_cash_without_documents() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "y de contado cuanto?"],
        nlu_scripts_override={
            "y de contado cuanto?": _nlu(Intent.ASK_PRICE),
        },
    )

    cash_turn = trace[-1]
    response_frame = cash_turn.state_after["response_frame"]
    outbound = " ".join(cash_turn.outbound_messages or []).casefold()

    assert cash_turn.state_after["final_action"] == "quote"
    assert response_frame["known_customer_state"]["active_purchase_mode"] == "cash"
    assert response_frame["pending_flow"] is None
    assert "contado" in outbound
    assert "ine" not in outbound
    assert "document" not in outbound


async def test_cash_mode_blocks_document_flow() -> None:
    response_frame = build_response_frame(
        user_message="y de contado cuanto?",
        recent_history=[
            (
                "outbound",
                "La R4 250 CC queda en $55,335 de lista. Enganche: $5,534. Pago quincenal: $2,198.",
            )
        ],
        action="quote",
        action_payload={
            "status": "ok",
            "request_type": "cash_price_request",
            "active_purchase_mode": "cash",
            "quote_mode": "cash",
            "name": "R4 250 CC",
            "list_price_mxn": "55335",
            "cash_price_mxn": "52700",
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
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
        },
        current_stage="potencialcliente",
        guardrails=[],
    )

    assert response_frame.response_strategy == "quote_cash"
    assert response_frame.pending_flow is None
    assert response_frame.known_customer_state["active_purchase_mode"] == "cash"
    assert "missing_documents" not in response_frame.known_customer_state


async def test_cash_and_credit_quotes_are_stored_separately() -> None:
    trace = await _run_scenario(
        ["la R4 de contado cuanto", "y a credito?", "me depositan nomina", "tarjeta"],
        nlu_scripts_override={
            "la R4 de contado cuanto": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
            "y a credito?": _nlu(Intent.ASK_PRICE),
            "me depositan nomina": _nlu(Intent.ASK_INFO),
            "tarjeta": _nlu(
                Intent.ASK_INFO,
                entities={"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
            ),
        },
    )

    cash_state = trace[0].state_after["response_frame"]["known_customer_state"]
    credit_state = trace[-1].state_after["response_frame"]["known_customer_state"]

    assert cash_state["quote_mode"] == "cash"
    assert cash_state["cash_quote_valid"] is True
    assert "last_cash_quote_payload" in cash_state
    assert credit_state["quote_mode"] == "credit"
    assert credit_state["credit_quote_valid"] is True
    assert "last_credit_quote_payload" in credit_state
    assert cash_state["last_cash_quote_payload"] != credit_state["last_credit_quote_payload"]


async def test_cash_credit_mix_extended_case_passes_runtime_shape() -> None:
    trace = await _run_scenario(
        [
            "hola la r4 de contado cuanto",
            "y a credito?",
            "llevo 2 anos en el jale",
            "me depositan nomina",
            "tarjeta",
            "mejor la adventure de contado",
            "y de esa a credito como quedaria",
            "ok no mando papeles hasta entender",
            "entonces cuanto de enganche seria",
            "va y luego que sigue",
            "y si tengo buro",
            "ok",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "hola la r4 de contado cuanto": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
            "y a credito?": _nlu(Intent.ASK_PRICE),
            "llevo 2 anos en el jale": _nlu(
                Intent.ASK_INFO, entities={"FILTRO": True}
            ),
            "me depositan nomina": _nlu(Intent.ASK_INFO),
            "tarjeta": _nlu(
                Intent.ASK_INFO,
                entities={"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
            ),
            "mejor la adventure de contado": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "Adventure Elite 150 CC"}
            ),
            "y de esa a credito como quedaria": _nlu(Intent.ASK_PRICE),
            "ok no mando papeles hasta entender": _nlu(Intent.ASK_INFO),
            "entonces cuanto de enganche seria": _nlu(Intent.ASK_PRICE),
            "va y luego que sigue": _nlu(Intent.ASK_INFO),
            "y si tengo buro": _nlu(Intent.ASK_INFO),
            "ok": _nlu(Intent.UNCLEAR),
        },
    )

    turn1 = trace[0]
    turn6 = trace[5]
    turn7 = trace[6]

    assert turn1.state_after["final_action"] == "quote"
    assert turn1.state_after["response_frame"]["known_customer_state"]["active_purchase_mode"] == "cash"
    assert turn1.state_after["response_frame"]["pending_flow"] is None
    assert turn6.state_after["final_action"] == "quote"
    assert turn6.state_after["response_frame"]["known_customer_state"]["active_purchase_mode"] == "cash"
    assert turn6.state_after["response_frame"]["pending_flow"] is None
    assert turn7.state_after["final_action"] == "quote"
    assert turn7.state_after["response_frame"]["known_customer_state"]["active_purchase_mode"] == "credit"
    assert turn7.state_after["extracted_data"]["MOTO"]["value"] == "Adventure Elite 150 CC"


async def test_repeated_buro_uses_rephrase_not_duplicate_document_prompt() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "revisan buro?", "revisan buro?"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    first_answer = trace[3].outbound_messages[0]
    second_answer = trace[4].outbound_messages[0]

    assert "buro" in second_answer.casefold()
    assert "INE por ambos lados" in second_answer
    assert first_answer != second_answer
    assert any(
        second_answer.casefold().startswith(prefix)
        for prefix in ("sobre eso", "te confirmo", "para que quede claro")
    )
    assert second_answer.casefold() != "mandame tu ine"


async def test_does_not_ask_seniority_when_filtro_already_true() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="va, seguimos",
        seeded_outbound_text=(
            "La Adventure Elite 150 CC de contado queda en $50,400.\n\n"
            "Con tu plan 10%:\nEnganche: $5,040\nPago quincenal: $2,100\nPlazo: 72 quincenas"
        ),
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"va, seguimos": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] != "ask_field"
    assert "cuanto tiempo" not in trace.outbound_messages[0].casefold()


async def test_ack_after_quote_does_not_reopen_seniority() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="si",
        seeded_outbound_text=(
            "La Adventure Elite 150 CC de contado queda en $50,400.\n\n"
            "Con tu plan 10%:\nEnganche: $5,040\nPago quincenal: $2,100\nPlazo: 72 quincenas"
        ),
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"si": _nlu(Intent.UNCLEAR)},
    )

    payload = trace.composer_input["action_payload"] if trace.composer_input else {}

    assert trace.state_after["final_action"] != "ask_field"
    assert trace.state_after["final_action"] != "quote"
    assert payload.get("field_name") != "ANTIGUEDAD_LABORAL"
    assert "cuanto tiempo" not in "\n".join(trace.outbound_messages or []).casefold()


async def test_buro_after_quote_resumes_documents_not_seniority() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="revisan buro?",
        seeded_outbound_text="Para seguir, revisa estos documentos: INE-FRENTE, INE-ATRAS, Domicilio",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        composer=_AnswerAndResumeLLMComposer(),
        nlu_scripts_override={"revisan buro?": _nlu(Intent.ASK_INFO, confidence=0.86)},
    )

    outbound = trace.outbound_messages[0].casefold()

    assert "buro" in outbound
    assert "cuanto tiempo" not in outbound
    assert "ine por ambos lados" in outbound


async def test_sin_comprobantes_bank_statement_question_answers_directly() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="entonces no ocupo estados de cuenta?",
        seeded_outbound_text="Para seguir, revisa estos documentos: INE-FRENTE, INE-ATRAS, Domicilio",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
            "MOTO": "R4 250 CC",
        },
        composer=_AnswerAndResumeLLMComposer(),
        nlu_scripts_override={
            "entonces no ocupo estados de cuenta?": _nlu(Intent.ASK_INFO, confidence=0.88),
        },
    )

    outbound = trace.outbound_messages[0].casefold()

    assert "no te estoy pidiendo estados de cuenta" in outbound
    assert "ine por ambos lados" in outbound
    assert "comprobante de domicilio reciente" in outbound


async def test_document_labels_are_humanized_in_customer_output() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "revisan buro?"],
        composer=_AnswerAndResumeLLMComposer(),
    )

    outbound = trace[3].outbound_messages[0]

    assert "INE-FRENTE" not in outbound
    assert "INE-ATRAS" not in outbound
    assert "Domicilio" not in outbound
    assert "INE por ambos lados" in outbound
    assert "comprobante de domicilio reciente" in outbound


async def test_document_order_followup_uses_humanized_request() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="va, que te mando primero?",
        seeded_outbound_text="Revise tu expediente y todavia me faltan estos documentos.\n\nPara seguir, mandame primero INE por ambos lados y comprobante de domicilio reciente.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        composer=_AnswerAndResumeLLMComposer(),
        nlu_scripts_override={
            "va, que te mando primero?": _nlu(Intent.ASK_INFO, confidence=0.82),
        },
    )

    outbound = trace.outbound_messages[0]

    assert trace.state_after["final_action"] != "ask_clarification"
    assert "INE-FRENTE" not in outbound
    assert "INE-ATRAS" not in outbound
    assert "INE por ambos lados" in outbound
    assert "comprobante de domicilio reciente" in outbound


async def test_document_order_question_does_not_resolve_mando_as_comando() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="que mando primero",
        seeded_outbound_text="Para Adventure Elite 150 CC con plan Nomina Recibos 15%: lista $50,400, contado $48,000, enganche $7,560, pago quincenal $1,980 y plazo 72 quincenas.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Recibos",
            "ENGANCHE": "15%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        composer=_AnswerAndResumeLLMComposer(),
        nlu_scripts_override={
            "que mando primero": _nlu(
                Intent.ASK_INFO,
                confidence=0.84,
                entities={"MOTO": "Comando 400 CC"},
            ),
        },
    )

    outbound = " ".join(trace.outbound_messages or []).casefold()

    assert trace.state_after["extracted_data"]["MOTO"]["value"] == "Adventure Elite 150 CC"
    assert "ine por ambos lados" in outbound
    assert "comprobante de domicilio reciente" in outbound


async def test_what_do_i_send_first_after_quote_answers_human_document_order() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="te mando primero la ine?",
        seeded_outbound_text="Revise tu expediente y todavia me faltan estos documentos.\n\nPara seguir, mandame primero INE por ambos lados y comprobante de domicilio reciente.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "R4 250 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        composer=_AnswerAndResumeLLMComposer(),
        nlu_scripts_override={
            "te mando primero la ine?": _nlu(Intent.ASK_INFO, confidence=0.84),
        },
    )

    outbound = trace.outbound_messages[0]

    assert "INE-FRENTE" not in outbound
    assert "INE-ATRAS" not in outbound
    assert "INE por ambos lados" in outbound
    assert "comprobante de domicilio reciente" in outbound


async def test_ok_after_document_request_does_not_repeat_quote() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="ok",
        seeded_outbound_text="Para seguir, revisa estos documentos: INE-FRENTE, INE-ATRAS, Domicilio",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"ok": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] != "quote"
    assert "$" not in "\n".join(trace.outbound_messages or [])


async def test_text_ack_is_not_classified_as_document() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="ya te mandé el frente",
        seeded_outbound_text="Revise tu expediente y todavia me faltan estos documentos.\n\nPara seguir, mandame primero INE por ambos lados y comprobante de domicilio reciente.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "R4 250 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        composer=_AnswerAndResumeLLMComposer(),
        nlu_scripts_override={
            "ya te mandé el frente": _nlu(Intent.ASK_INFO, confidence=0.82),
        },
    )

    outbound = trace.outbound_messages[0].casefold()

    assert trace.state_after["final_action"] != "classify_document"
    assert trace.state_after["final_action"] != "quote"
    assert "todavia no me aparece cargado" in outbound
    assert "enganche" not in outbound


def test_current_question_guard_blocks_pending_flow_only_response() -> None:
    frame = build_response_frame(
        user_message="me aprueban seguro o no?",
        recent_history=[("outbound", "Para seguir, mandame INE por ambos lados.")],
        action="classify_document",
        action_payload={
            "request_type": "ask_missing_document",
            "requirements": {"missing": [{"key": "INE_FRENTE", "label": "INE-FRENTE"}]},
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
    output = ComposerOutput(messages=["Para seguir, mandame INE por ambos lados."])

    event = _guard_composer_output(
        composer_output=output,
        decision_action="classify_document",
        action_payload={},
        response_frame=frame,
        extracted_data={},
    )

    assert event is not None
    assert event["current_question_guard_applied"] is True
    assert "no puedo prometer aprobacion" in output.messages[0].casefold()
    assert "ine" in output.messages[0].casefold()


def test_current_question_answered_then_resume_flow() -> None:
    frame = build_response_frame(
        user_message="buro revisan?",
        recent_history=[("outbound", "Para seguir, mandame INE por ambos lados.")],
        action="lookup_faq",
        action_payload={
            "status": "ok",
            "topic": "buro",
            "answer": "Si, se revisa buro.",
            "requirements": {"missing": [{"key": "INE_FRENTE", "label": "INE-FRENTE"}]},
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

    assert frame.required_answer_targets == ["buro"]
    assert frame.missing_answer_targets == []
    rendered = render_response_frame_fallback_message(frame).casefold()
    assert "buro" in rendered
    assert "ine" in rendered


def test_current_question_without_tool_answer_marks_unresolved() -> None:
    frame = build_response_frame(
        user_message="me dicen hoy si o no?",
        recent_history=[],
        action="ask_field",
        action_payload={"field_name": "CREDITO"},
        decision_payload={},
        extracted_data={"MOTO": "R4 250 CC"},
        current_stage="nuevos",
        guardrails=[],
    )
    rendered = render_response_frame_fallback_message(frame).casefold()

    assert "timing" in frame.missing_answer_targets
    assert frame.trace.current_question_unresolved_reason
    assert "revision" in rendered
    assert "ingresos" in rendered


def test_current_question_not_overridden_by_soft_close() -> None:
    frame = build_response_frame(
        user_message="cuanto tarda aprobacion?",
        recent_history=[("outbound", "Para seguir, mandame INE por ambos lados.")],
        action="soft_close",
        action_payload={
            "request_type": "soft_close",
            "requirements": {"missing": [{"key": "INE_FRENTE", "label": "INE-FRENTE"}]},
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
    output = ComposerOutput(messages=["Claro, aqui sigo para ayudarte."])

    event = _guard_composer_output(
        composer_output=output,
        decision_action="soft_close",
        action_payload={},
        response_frame=frame,
        extracted_data={},
    )

    assert event is not None
    assert "revision" in output.messages[0].casefold()


def test_current_question_not_overridden_by_document_request() -> None:
    frame = build_response_frame(
        user_message="me aprueban seguro?",
        recent_history=[],
        action="classify_document",
        action_payload={
            "request_type": "ask_missing_document",
            "requirements": {"missing": [{"key": "COMPROBANTE_DOMICILIO", "label": "Domicilio"}]},
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
    output = ComposerOutput(messages=["Para seguir, mandame comprobante de domicilio."])

    event = _guard_composer_output(
        composer_output=output,
        decision_action="classify_document",
        action_payload={},
        response_frame=frame,
        extracted_data={},
    )

    assert event is not None
    assert "no puedo prometer aprobacion" in output.messages[0].casefold()


def test_current_question_not_overridden_by_quote_only() -> None:
    quote_payload = _quote_payload_fixture()
    frame = build_response_frame(
        user_message="quiero hablar con una persona",
        recent_history=[],
        action="quote",
        action_payload=quote_payload,
        decision_payload={},
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
        },
        current_stage="potencialcliente",
        guardrails=[],
    )
    output = ComposerOutput(messages=["Para R4 250 CC con plan 10%: enganche $5,534."])

    event = _guard_composer_output(
        composer_output=output,
        decision_action="quote",
        action_payload=quote_payload,
        response_frame=frame,
        extracted_data={},
    )

    assert event is not None
    assert "asesor" in output.messages[0].casefold()


def test_response_frame_tracks_required_answer_targets() -> None:
    frame = build_response_frame(
        user_message="buro revisan y cuanto tarda aprobacion?",
        recent_history=[],
        action="lookup_faq",
        action_payload={"status": "ok", "topic": "buro", "answer": "Si, se revisa buro."},
        decision_payload={},
        extracted_data={},
        current_stage="nuevos",
        guardrails=[],
    )

    assert {item["target"] for item in frame.current_questions} == {"buro", "approval", "timing"}
    assert set(frame.required_answer_targets) == {"buro", "approval", "timing"}
    assert set(frame.missing_answer_targets) == {"approval", "timing"}
    assert frame.trace.current_question_detected is True
    assert frame.trace.outbound_blocked_missing_answer is True


async def test_final_wide_current_question_cases_regression() -> None:
    approval = await _run_single_turn_with_seeded_context(
        inbound_text="me aprueban seguro o no?",
        seeded_outbound_text="Para seguir, revisa estos documentos: INE-FRENTE, INE-ATRAS, Domicilio",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"me aprueban seguro o no?": _nlu(Intent.ASK_INFO, confidence=0.86)},
    )
    human = await _run_single_turn_with_seeded_context(
        inbound_text="quiero hablar con una persona",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "R4 250 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"quiero hablar con una persona": _nlu(Intent.ASK_INFO, confidence=0.86)},
    )
    docs = await _run_single_turn_with_seeded_context(
        inbound_text="solo confirmame cuales eran",
        seeded_outbound_text="Revise tu expediente y todavia me faltan estos documentos.\n\nPara seguir, mandame primero INE por ambos lados y comprobante de domicilio reciente.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"solo confirmame cuales eran": _nlu(Intent.ASK_INFO, confidence=0.82)},
    )

    assert "no puedo prometer aprobacion" in approval.outbound_messages[0].casefold()
    assert approval.state_after["current_question_answered"] is False
    assert approval.state_after["current_question_guard_applied"] is True
    assert "asesor" in human.outbound_messages[0].casefold()
    assert human.state_after["current_question_guard_applied"] is True
    assert "ine por ambos lados" in docs.outbound_messages[0].casefold()
    assert "comprobante de domicilio reciente" in docs.outbound_messages[0].casefold()


async def test_document_labels_humanized_after_quote() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="te mando primero la ine?",
        seeded_outbound_text="Revise tu expediente y todavia me faltan estos documentos.\n\nPara seguir, mandame primero INE por ambos lados y comprobante de domicilio reciente.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        composer=_AnswerAndResumeLLMComposer(),
        nlu_scripts_override={
            "te mando primero la ine?": _nlu(Intent.ASK_INFO, confidence=0.84),
        },
    )

    outbound = trace.outbound_messages[0]

    assert "INE-FRENTE" not in outbound
    assert "INE-ATRAS" not in outbound
    assert "Domicilio" not in outbound


async def test_adventure_alias_resolves_to_adventure_elite_and_quotes_when_plan_ready() -> None:
    trace = await _run_scenario(
        ["hola", "por fuera", "15 anos", "adventure"],
        after_seed=_seed_catalog_resolution_fixture,
    )

    turn4 = trace[3]
    resolver = _resolver_layer(turn4)
    decision = _decision_layer(turn4)
    payload = turn4.composer_input["action_payload"]

    assert resolver["selected_attempt"]["resolver"] == "catalog_resolver"
    assert turn4.state_after["extracted_data"]["MOTO"]["value"] == "Adventure Elite 150 CC"
    assert turn4.state_after["final_action"] == "quote"
    assert payload["name"] == "Adventure Elite 150 CC"
    assert decision["quote_gate_result"] == "ready"
    assert decision["quote_gate_blocked_actions"] == []


async def test_resolved_model_entity_beats_catalog_browse_when_quote_is_ready() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="la adventure",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "la adventure": _nlu(
                Intent.ASK_INFO,
                confidence=0.9,
                entities={"MOTO": "Adventure Elite 150 CC"},
            ),
        },
    )

    assert trace.state_after["extracted_data"]["MOTO"]["value"] == "Adventure Elite 150 CC"
    assert trace.state_after["final_action"] == "quote"
    assert trace.composer_input["action"] == "quote"


async def test_custom_ambiguous_asks_clarification_with_max_3_options() -> None:
    trace = await _run_scenario(
        ["hola", "custom"],
        after_seed=_seed_catalog_resolution_fixture,
    )

    turn2 = trace[1]
    resolver = _resolver_layer(turn2)
    metadata = turn2.composer_input["decision_payload"]["metadata"]
    outbound = turn2.outbound_messages[0]

    assert resolver["selected_attempt"]["resolver"] == "catalog_resolver"
    assert resolver["selected_attempt"]["blocked_reason"] == "multiple_catalog_matches"
    assert "MOTO" not in turn2.state_after["extracted_data"]
    assert turn2.state_after["final_action"] == "ask_clarification"
    assert metadata["catalog_resolution_status"] == "ambiguous"
    assert 1 < metadata["catalog_candidate_count"] <= 3
    assert len(metadata["catalog_candidates"]) <= 3
    assert "Custom 150 CC" in outbound
    assert "Custom Black 175 CC" in outbound
    assert "cotiz" not in outbound.casefold()


async def test_custom_ambiguo_preserves_options_until_customer_selects() -> None:
    trace = await _run_scenario(
        ["quiero la custom", "la black"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la custom": _nlu(Intent.ASK_INFO, confidence=0.82),
            "la black": _nlu(Intent.ASK_INFO, confidence=0.86),
        },
    )

    assert "Custom 150 CC" in trace[0].outbound_messages[0]
    assert "Custom Black 175 CC" in trace[0].outbound_messages[0]
    assert trace[1].state_after["final_action"] != "ask_clarification"
    assert trace[1].state_after["extracted_data"]["MOTO"]["value"] == "Custom Black 175 CC"


async def test_custom_black_selection_resolves_and_quotes() -> None:
    trace = await _run_scenario(
        ["quiero la custom", "la black", "tengo recibos de nómina", "cuánto me queda?"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la custom": _nlu(Intent.ASK_INFO, confidence=0.82),
            "la black": _nlu(Intent.ASK_INFO, confidence=0.86),
            "tengo recibos de nómina": _nlu(Intent.ASK_INFO, confidence=0.86),
            "cuánto me queda?": _nlu(Intent.ASK_PRICE, confidence=0.9),
        },
    )

    assert trace[3].state_after["final_action"] == "quote"
    assert "Custom Black 175 CC" in trace[3].outbound_messages[0]
    assert "enganche" in trace[3].outbound_messages[0].casefold()


async def test_custom_ambiguous_does_not_quote_arbitrarily() -> None:
    trace = await _run_scenario(
        ["quiero la custom"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la custom": _nlu(Intent.ASK_INFO, confidence=0.82),
        },
    )

    assert trace[0].state_after["final_action"] == "ask_clarification"
    assert "cotiz" not in trace[0].outbound_messages[0].casefold()


async def test_motonetas_category_returns_only_motoneta_models() -> None:
    trace = await _run_scenario(
        ["que motonetas tienes"],
        after_seed=_seed_catalog_resolution_fixture,
    )

    turn1 = trace[0]
    payload = turn1.composer_input["action_payload"]
    result_names = [item["name"] for item in payload["results"]]

    assert turn1.composer_input["action"] == "search_catalog"
    assert payload["request_type"] == "catalog_browse"
    assert payload["browse_intent"] == "catalog_style"
    assert payload["query"] == "motoneta"
    assert set(result_names) == {
        "Adventure Elite 150 CC",
        "Alien R 175 CC",
        "Metro 125 CC",
    }
    assert all(item["category"] == "Motoneta" for item in payload["results"])
    assert "R4 250 CC" not in result_names
    assert "Moto Taxi" not in result_names


async def test_category_then_la_primera_resolves_and_quotes_when_plan_ready() -> None:
    trace = await _run_scenario(
        ["hola", "por fuera", "15 anos", "que motonetas tienes", "la primera"],
        after_seed=_seed_catalog_resolution_fixture,
    )

    turn5 = trace[4]
    resolver = _resolver_layer(turn5)
    decision = _decision_layer(turn5)
    payload = turn5.composer_input["action_payload"]

    assert resolver["selected_attempt"]["resolver"] == "catalog_context_resolver"
    assert turn5.state_after["extracted_data"]["MOTO"]["value"] == "Adventure Elite 150 CC"
    assert turn5.state_after["final_action"] == "quote"
    assert payload["name"] == "Adventure Elite 150 CC"
    assert decision["quote_gate_result"] == "ready"


async def test_resolved_model_after_credit_context_never_goes_to_documents_before_quote() -> None:
    trace = await _run_scenario(
        ["hola", "por fuera", "15 anos", "adventure"],
        after_seed=_seed_catalog_resolution_fixture,
    )

    turn4 = trace[3]
    assert turn4.state_after["final_action"] == "quote"
    assert turn4.composer_input["action"] == "quote"
    assert turn4.composer_input["decision_payload"]["metadata"]["catalog_selected_model"] == (
        "Adventure Elite 150 CC"
    )
    assert turn4.state_after["runner_layers"]["decision"]["quote_gate_blocked_actions"] == []


async def test_requirements_before_income_answers_general_and_asks_income() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="que documentos ocupo?",
        extracted_data={"MOTO": "R4 250 CC"},
        seeded_outbound_text="Perfecto, ya ubique la R4 250 CC. Para seguir, dime como recibes tus ingresos.",
        prior_inbound_messages=["quiero la r4 a credito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"que documentos ocupo?": _nlu(Intent.ASK_INFO, confidence=0.88)},
    )

    outbound = trace.outbound_messages[0].casefold()
    assert trace.state_after["final_action"] == "lookup_faq"
    assert trace.state_after["response_frame_strategy"] == "answer_and_resume_flow"
    assert "dependen" in outbound or "depende" in outbound
    assert "ingres" in outbound
    assert "ine" not in outbound
    assert "domicilio" not in outbound


async def test_requirements_before_quote_answers_info_but_resumes_model() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="que papeles siguen?",
        extracted_data={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
        seeded_outbound_text=(
            "Perfecto, ya quedo tu plan Sin Comprobantes con 20% de enganche. "
            "Para cotizarte bien dime que modelo quieres revisar."
        ),
        prior_inbound_messages=["quiero una moto a credito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"que papeles siguen?": _nlu(Intent.ASK_INFO, confidence=0.88)},
    )

    outbound = trace.outbound_messages[0].casefold()
    assert trace.state_after["final_action"] == "lookup_faq"
    assert trace.state_after["response_frame_strategy"] == "answer_and_resume_flow"
    assert "modelo" in outbound
    assert "ine" not in outbound
    assert "domicilio" not in outbound


async def test_documents_blocked_when_model_missing_even_if_plan_exists() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="que documentos piden?",
        extracted_data={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
        seeded_outbound_text="Listo, tu plan ya quedo en 20%.",
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"que documentos piden?": _nlu(Intent.ASK_INFO, confidence=0.88)},
    )

    assert trace.state_after["final_action"] == "lookup_faq"
    assert trace.composer_input["action_payload"]["policy_trace"]["documents_blocked_reason"] == (
        "requirements_need_model_context"
    )


async def test_documents_blocked_when_quote_payload_missing_but_model_plan_ready() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="que documentos siguen?",
        extracted_data={
            "MOTO": "Adventure Elite 150 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"que documentos siguen?": _nlu(Intent.ASK_INFO, confidence=0.88)},
    )

    outbound = trace.outbound_messages[0].casefold()
    assert trace.state_after["final_action"] == "quote"
    assert "$" in trace.outbound_messages[0]
    assert "enganche" in outbound
    assert "ine" not in outbound


async def test_price_request_after_requirements_forces_quote() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="y cuanto sale?",
        extracted_data={
            "MOTO": "Adventure Elite 150 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        seeded_outbound_text=(
            "Los documentos exactos dependen del plan y del modelo. "
            "Para seguir solo falta la cotizacion final."
        ),
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"y cuanto sale?": _nlu(Intent.ASK_PRICE, confidence=0.9)},
    )

    assert trace.state_after["final_action"] == "quote"
    assert "enganche" in trace.outbound_messages[0].casefold()


async def test_complaint_no_docs_before_price_blocks_document_flow() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="no mando papeles hasta entender el precio",
        extracted_data={
            "MOTO": "Adventure Elite 150 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "no mando papeles hasta entender el precio": _nlu(Intent.ASK_INFO, confidence=0.9)
        },
    )

    assert trace.state_after["final_action"] == "quote"
    assert "document" not in trace.outbound_messages[0].casefold()


async def test_model_change_requires_requote_before_documents() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="que papeles siguen?",
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        seeded_outbound_text=(
            "La Adventure Elite 150 CC de contado queda en $50,400.\n\n"
            "Con tu plan 20%:\nEnganche: $10,080\nPago quincenal: $1,820\nPlazo: 72 quincenas"
        ),
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"que papeles siguen?": _nlu(Intent.ASK_INFO, confidence=0.88)},
    )

    assert trace.state_after["final_action"] == "quote"
    assert "R4 250 CC" in trace.outbound_messages[0]
    assert "document" not in trace.outbound_messages[0].casefold()


async def test_response_frame_sets_quote_required_before_documents() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="que documentos siguen?",
        extracted_data={
            "MOTO": "R4 250 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        seeded_outbound_text=(
            "La Adventure Elite 150 CC de contado queda en $50,400.\n\n"
            "Con tu plan 20%:\nEnganche: $10,080\nPago quincenal: $1,820\nPlazo: 72 quincenas"
        ),
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"que documentos siguen?": _nlu(Intent.ASK_INFO, confidence=0.88)},
    )

    guardrails = trace.state_after["response_frame"]["guardrails"]
    assert "quote_required_before_documents" in guardrails
    assert "documents_after_quote_only" in guardrails


async def test_formal_documents_not_listed_before_income_plan_resolved() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="que documentos ocupan?",
        extracted_data={"MOTO": "Adventure Elite 150 CC"},
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"que documentos ocupan?": _nlu(Intent.ASK_INFO, confidence=0.88)},
    )

    outbound = trace.outbound_messages[0].casefold()
    assert "ine" not in outbound
    assert "domicilio" not in outbound
    assert "ingres" in outbound


async def test_ambiguous_payroll_income_asks_card_or_receipts_without_setting_plan() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="me pagan nomina",
        seeded_outbound_text="Para seguir, dime como recibes tus ingresos.",
        prior_inbound_messages=["quiero una moto a credito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"me pagan nomina": _nlu(Intent.UNCLEAR)},
    )

    outbound = trace.outbound_messages[0].casefold()
    assert trace.state_after["final_action"] == "lookup_faq"
    assert "CREDITO" not in trace.state_after["extracted_data"]
    assert "ENGANCHE" not in trace.state_after["extracted_data"]
    assert "tarjeta" in outbound
    assert "recib" in outbound


async def test_me_depositan_asks_if_formal_nomina_without_setting_plan() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="me depositan",
        seeded_outbound_text="Para seguir, dime como recibes tus ingresos.",
        prior_inbound_messages=["quiero una moto a credito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"me depositan": _nlu(Intent.UNCLEAR)},
    )

    outbound = trace.outbound_messages[0].casefold()
    assert trace.state_after["final_action"] == "lookup_faq"
    assert "CREDITO" not in trace.state_after["extracted_data"]
    assert "nomina formal" in outbound or "nomina" in outbound
    assert "deposit" in outbound


async def test_transfer_deposit_asks_if_formal_nomina_without_setting_plan() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="me pagan por transferencia",
        seeded_outbound_text="Para seguir, dime como recibes tus ingresos.",
        prior_inbound_messages=["quiero una moto a credito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"me pagan por transferencia": _nlu(Intent.UNCLEAR)},
    )

    outbound = trace.outbound_messages[0].casefold()
    assert trace.state_after["final_action"] == "lookup_faq"
    assert "CREDITO" not in trace.state_after["extracted_data"]
    assert "nomina" in outbound
    assert "transfer" in outbound or "deposit" in outbound


async def test_payroll_card_resolves_nomina_tarjeta_after_clarification() -> None:
    trace = await _run_scenario(
        ["quiero la r4 a credito", "me pagan nomina", "en tarjeta"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(
                Intent.ASK_INFO,
                confidence=0.88,
                entities={"MOTO": "R4 250 CC"},
            ),
            "me pagan nomina": _nlu(Intent.UNCLEAR),
            "en tarjeta": _nlu(Intent.UNCLEAR),
        },
    )

    turn3 = trace[2]
    assert turn3.state_after["extracted_data"]["CREDITO"]["value"] == "Nomina Tarjeta"
    assert turn3.state_after["extracted_data"]["ENGANCHE"]["value"] == "10%"


async def test_payroll_receipts_resolves_nomina_recibos_after_clarification() -> None:
    trace = await _run_scenario(
        ["quiero la r4 a credito", "me pagan nomina", "con recibos"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(
                Intent.ASK_INFO,
                confidence=0.88,
                entities={"MOTO": "R4 250 CC"},
            ),
            "me pagan nomina": _nlu(Intent.UNCLEAR),
            "con recibos": _nlu(Intent.UNCLEAR),
        },
    )

    turn3 = trace[2]
    assert turn3.state_after["extracted_data"]["CREDITO"]["value"] == "Nomina Recibos"
    assert turn3.state_after["extracted_data"]["ENGANCHE"]["value"] == "15%"


async def test_dual_income_asks_which_income_to_use_without_setting_plan() -> None:
    trace = await _run_scenario(
        ["quiero la r4 a credito", "uno por fuera y otro me cae deposito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
        },
    )

    turn2 = trace[1]
    outbound = turn2.outbound_messages[0].casefold()
    assert turn2.state_after["final_action"] == "lookup_faq"
    assert "CREDITO" not in turn2.state_after["extracted_data"]
    assert "cual ingreso" in outbound or "cual" in outbound


async def test_dual_income_explains_comprobable_vs_sin_comprobantes() -> None:
    trace = await _run_scenario(
        ["quiero la r4 a credito", "uno por fuera y otro me cae deposito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
        },
    )

    outbound = trace[1].outbound_messages[0].casefold()
    assert "comprobable" in outbound or "comprobar" in outbound
    assert "sin comprobantes" in outbound


async def test_dual_income_deposit_confirmed_resolves_best_plan_if_formal() -> None:
    trace = await _run_scenario(
        ["quiero la r4 a credito", "uno por fuera y otro me cae deposito", "ok entonces con tarjeta"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
            "ok entonces con tarjeta": _nlu(Intent.UNCLEAR),
        },
    )

    turn3 = trace[2]
    assert turn3.state_after["extracted_data"]["CREDITO"]["value"] == "Nomina Tarjeta"
    assert turn3.state_after["extracted_data"]["ENGANCHE"]["value"] == "10%"


async def test_dual_income_no_comprobante_falls_to_sin_comprobantes() -> None:
    trace = await _run_scenario(
        ["quiero la r4 a credito", "uno por fuera y otro me cae deposito", "no se puede comprobar"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
            "no se puede comprobar": _nlu(Intent.UNCLEAR),
        },
    )

    turn3 = trace[2]
    assert turn3.state_after["extracted_data"]["CREDITO"]["value"] == "Sin Comprobantes"
    assert turn3.state_after["extracted_data"]["ENGANCHE"]["value"] == "20%"


async def test_two_jobs_mixed_income_blocks_documents_until_income_selected() -> None:
    trace = await _run_scenario(
        ["quiero la r4 a credito", "tengo dos trabajos", "uno por fuera y otro me cae deposito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "tengo dos trabajos": _nlu(Intent.UNCLEAR),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
        },
    )

    turn3 = trace[2]
    outbound = " ".join(turn3.outbound_messages or []).casefold()
    frame = turn3.state_after["response_frame"]

    assert turn3.state_after["final_action"] == "lookup_faq"
    assert "documento" not in outbound
    assert "ine" not in outbound
    assert frame["pending_flow"]["type"] == "ask_field"
    assert frame["pending_flow"]["payload"]["type"] == "ask_income_disambiguation"
    assert frame["trace"]["dual_income_resolution_required"] is True
    assert frame["trace"]["documents_blocked_by_dual_income"] is True
    assert frame["trace"]["pending_flow_forced_to_income_disambiguation"] is True


async def test_two_jobs_mixed_income_does_not_write_credit_plan_before_selection() -> None:
    trace = await _run_scenario(
        ["quiero la r4 a credito", "tengo dos trabajos", "uno por fuera y otro me cae deposito"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "tengo dos trabajos": _nlu(Intent.UNCLEAR),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
        },
    )

    extracted = trace[2].state_after["extracted_data"]
    assert "CREDITO" not in extracted
    assert "ENGANCHE" not in extracted


async def test_two_jobs_mixed_income_explains_options_without_formal_documents() -> None:
    trace = await _run_scenario(
        [
            "quiero la r4 a credito",
            "tengo dos trabajos",
            "uno por fuera y otro me cae deposito",
            "cual me conviene mas",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "tengo dos trabajos": _nlu(Intent.UNCLEAR),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
            "cual me conviene mas": _nlu(Intent.UNCLEAR),
        },
    )

    outbound = " ".join(trace[3].outbound_messages or []).casefold()
    assert "comprobable" in outbound or "comprobar" in outbound
    assert "sin comprobantes" in outbound
    assert "documento" not in outbound
    assert "ine" not in outbound


async def test_two_jobs_deposit_selected_then_resolves_plan_and_quotes() -> None:
    trace = await _run_scenario(
        [
            "quiero la r4 a credito",
            "tengo dos trabajos",
            "uno por fuera y otro me cae deposito",
            "uso el deposito, si es nomina",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "tengo dos trabajos": _nlu(Intent.UNCLEAR),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
            "uso el deposito, si es nomina": _nlu(Intent.UNCLEAR),
        },
    )

    turn4 = trace[3]
    assert turn4.state_after["extracted_data"]["CREDITO"]["value"] == "Nomina Tarjeta"
    assert turn4.state_after["extracted_data"]["ENGANCHE"]["value"] == "10%"
    assert turn4.state_after["final_action"] == "quote"
    assert "r4" in " ".join(turn4.outbound_messages or []).casefold()
    assert turn4.state_after["response_frame"]["trace"]["selected_income_source"] == (
        "deposito_nomina_tarjeta"
    )


async def test_two_jobs_cash_selected_then_sin_comprobantes_and_quotes() -> None:
    trace = await _run_scenario(
        [
            "quiero la r4 a credito",
            "tengo dos trabajos",
            "uno por fuera y otro me cae deposito",
            "mejor por fuera, no tengo comprobante",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "tengo dos trabajos": _nlu(Intent.UNCLEAR),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
            "mejor por fuera, no tengo comprobante": _nlu(Intent.UNCLEAR),
        },
    )

    turn4 = trace[3]
    assert turn4.state_after["extracted_data"]["CREDITO"]["value"] == "Sin Comprobantes"
    assert turn4.state_after["extracted_data"]["ENGANCHE"]["value"] == "20%"
    assert turn4.state_after["final_action"] == "quote"
    assert "r4" in " ".join(turn4.outbound_messages or []).casefold()
    assert turn4.state_after["response_frame"]["trace"]["selected_income_source"] == (
        "ingreso_por_fuera_sin_comprobantes"
    )


async def test_two_jobs_cash_hint_waits_for_sin_comprobantes_confirmation() -> None:
    trace = await _run_scenario(
        [
            "quiero la r4 a credito",
            "tengo dos trabajos",
            "uno con recibos pero casi no gano y otro efectivo",
            "mejor quiero tomar el de efectivo",
            "entonces sin comprobantes",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(
                Intent.ASK_INFO,
                confidence=0.88,
                entities={"MOTO": "R4 250 CC"},
            ),
            "tengo dos trabajos": _nlu(Intent.UNCLEAR),
            "uno con recibos pero casi no gano y otro efectivo": _nlu(Intent.UNCLEAR),
            "mejor quiero tomar el de efectivo": _nlu(Intent.UNCLEAR),
            "entonces sin comprobantes": _nlu(
                Intent.ASK_INFO,
                entities={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
            ),
        },
    )

    cash_hint_turn = trace[3]
    confirmed_turn = trace[4]

    assert "CREDITO" not in cash_hint_turn.state_after["extracted_data"]
    assert "sin comprobantes" in " ".join(cash_hint_turn.outbound_messages or []).casefold()
    assert confirmed_turn.state_after["extracted_data"]["CREDITO"]["value"] == "Sin Comprobantes"
    assert confirmed_turn.state_after["extracted_data"]["ENGANCHE"]["value"] == "20%"


async def test_two_jobs_quote_does_not_unlock_documents_until_quote_sent() -> None:
    trace = await _run_scenario(
        [
            "quiero la r4 a credito",
            "tengo dos trabajos",
            "uno por fuera y otro me cae deposito",
            "ok entonces con tarjeta",
            "si",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "tengo dos trabajos": _nlu(Intent.UNCLEAR),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
            "ok entonces con tarjeta": _nlu(Intent.UNCLEAR),
            "si": _nlu(Intent.UNCLEAR),
        },
    )

    turn4 = trace[3]
    turn5 = trace[4]
    assert turn4.state_after["final_action"] == "quote"
    assert "documento" not in " ".join(turn4.outbound_messages or []).casefold()
    assert "ine" not in " ".join(turn4.outbound_messages or []).casefold()
    assert turn5.state_after["final_action"] != "classify_document"
    assert "ine-frente" not in " ".join(turn5.outbound_messages or []).casefold()


async def test_two_jobs_extended_case_no_documents_before_quote() -> None:
    trace = await _run_scenario(
        [
            "quiero la r4 a credito",
            "tengo dos trabajos",
            "uno por fuera y otro me cae deposito",
            "llevo 5 anos en uno y 1 en otro",
            "cual me conviene mas",
            "si se puede con comprobable mejor",
            "ok entonces con tarjeta",
            "si",
            "cuanto sale",
            "que papeles siguen",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(Intent.ASK_INFO, confidence=0.88),
            "tengo dos trabajos": _nlu(Intent.UNCLEAR),
            "uno por fuera y otro me cae deposito": _nlu(Intent.UNCLEAR),
            "llevo 5 anos en uno y 1 en otro": _nlu(Intent.UNCLEAR),
            "cual me conviene mas": _nlu(Intent.UNCLEAR),
            "si se puede con comprobable mejor": _nlu(Intent.UNCLEAR),
            "ok entonces con tarjeta": _nlu(Intent.UNCLEAR),
            "si": _nlu(Intent.UNCLEAR),
            "cuanto sale": _nlu(Intent.ASK_PRICE),
            "que papeles siguen": _nlu(Intent.ASK_INFO),
        },
    )

    before_quote = []
    quote_seen = False
    for turn in trace:
        if turn.state_after["final_action"] == "quote":
            quote_seen = True
        text = " ".join(turn.outbound_messages or []).casefold()
        if not quote_seen:
            before_quote.append(text)

    assert quote_seen is True
    assert not any("ine-frente" in text or "ine-atras" in text for text in before_quote)
    assert trace[-1].state_after["final_action"] == "classify_document"


async def test_live_like_credit_then_model_keeps_quote_after_stage_recompute() -> None:
    trace = await _run_scenario(
        ["hola", "15 anos", "me pagan por fuera", "adventure"],
        after_seed=_seed_catalog_resolution_fixture,
    )

    turn4 = trace[3]
    decision = _decision_layer(turn4)

    assert turn4.state_after["extracted_data"]["MOTO"]["value"] == "Adventure Elite 150 CC"
    assert turn4.state_after["extracted_data"]["CREDITO"]["value"] == "Sin Comprobantes"
    assert turn4.state_after["extracted_data"]["ENGANCHE"]["value"] == "20%"
    assert turn4.state_after["final_action"] == "quote"
    assert turn4.composer_input["action"] == "quote"
    assert decision["action_after_recompute"] == "quote"


async def test_cuanto_es_de_enganche_after_quote_uses_last_quote_payload() -> None:
    trace = await _run_scenario(["hola", "r4", "por fuera", "20", "cuanto es de enganche"])

    turn4 = trace[3]
    turn5 = trace[4]
    previous_payload = turn4.composer_input["action_payload"]
    recalled_payload = turn5.composer_input["action_payload"]

    assert turn4.state_after["final_action"] == "quote"
    assert turn5.state_after["final_action"] == "quote"
    assert turn5.composer_input["action"] == "quote"
    assert recalled_payload["requested_plan_code"] == previous_payload["requested_plan_code"]
    assert recalled_payload["name"] == previous_payload["name"]
    assert (
        recalled_payload["payment_options"]["20%"]["down_payment_mxn"]
        == previous_payload["payment_options"]["20%"]["down_payment_mxn"]
    )
    assert "enganche" in turn5.outbound_messages[0].casefold()


async def test_esa_after_single_candidate_confirmation_resolves_model() -> None:
    trace = await _run_scenario(
        ["hola", "por fuera", "que deportivas tienes", "esa"],
        after_seed=_seed_catalog_resolution_fixture,
    )

    turn4 = trace[3]
    resolver = _resolver_layer(turn4)
    metadata = turn4.composer_input["decision_payload"]["metadata"]

    assert resolver["selected_attempt"]["resolver"] == "catalog_context_resolver"
    assert turn4.state_after["extracted_data"]["MOTO"]["value"] == "R4 250 CC"
    assert turn4.state_after["final_action"] == "quote"
    assert metadata["resolved_from_context"] is True
    assert metadata["catalog_selected_model"] == "R4 250 CC"


async def test_model_change_after_quote_invalidates_previous_quote_and_requotes() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "mejor otra mas barata",
            "la primera",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "mejor otra mas barata": _nlu(Intent.ASK_INFO, confidence=0.86),
            "la primera": _nlu(Intent.UNCLEAR),
        },
    )

    turn5 = trace[4]
    turn6 = trace[5]
    decision6 = _decision_layer(turn6)
    payload6 = turn6.composer_input["action_payload"]

    assert turn5.composer_input["action"] == "search_catalog"
    assert turn5.composer_input["action_payload"]["request_type"] == "catalog_browse"
    assert turn6.state_after["final_action"] == "quote"
    assert turn6.composer_input["action"] == "quote"
    assert turn6.state_after["extracted_data"]["CREDITO"]["value"] == "Sin Comprobantes"
    assert turn6.state_after["extracted_data"]["ENGANCHE"]["value"] == "20%"
    assert turn6.state_after["extracted_data"]["MOTO"]["value"] != "Adventure Elite 150 CC"
    assert payload6["name"] == turn6.state_after["extracted_data"]["MOTO"]["value"]
    assert decision6["model_change_detected"] is True
    assert decision6["previous_model"] == "Adventure Elite 150 CC"
    assert decision6["new_model"] == turn6.state_after["extracted_data"]["MOTO"]["value"]
    assert "CREDITO" in decision6["preserved_fields"]
    assert "ENGANCHE" in decision6["preserved_fields"]
    assert "last_quote_payload" in decision6["invalidated_fields"]
    assert "quote" in decision6["recalculated_fields"]
    assert decision6["documents_blocked_until_requote"] is True


async def test_model_change_explicit_model_requotes_with_existing_plan() -> None:
    trace = await _run_scenario(
        ["hola", "15 anos", "me pagan por fuera", "adventure", "y la R4 cuanto queda?"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "y la R4 cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
        },
    )

    turn5 = trace[4]
    decision = _decision_layer(turn5)

    assert turn5.state_after["final_action"] == "quote"
    assert turn5.composer_input["action_payload"]["name"] == "R4 250 CC"
    assert turn5.state_after["extracted_data"]["MOTO"]["value"] == "R4 250 CC"
    assert turn5.state_after["extracted_data"]["CREDITO"]["value"] == "Sin Comprobantes"
    assert turn5.state_after["extracted_data"]["ENGANCHE"]["value"] == "20%"
    assert decision["model_change_detected"] is True
    assert decision["previous_model"] == "Adventure Elite 150 CC"
    assert decision["new_model"] == "R4 250 CC"
    assert "ine" not in turn5.outbound_messages[0].casefold()


async def test_model_change_multiple_times_preserves_plan_each_time() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "y la R4 cuanto queda?",
            "ahora la metro cuanto queda?",
            "otra vez la adventure cuanto queda?",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "y la R4 cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
            "ahora la metro cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "Metro 125 CC"}
            ),
            "otra vez la adventure cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "Adventure Elite 150 CC"}
            ),
        },
    )

    quote_turns = trace[3:]
    expected_models = [
        "Adventure Elite 150 CC",
        "R4 250 CC",
        "Metro 125 CC",
        "Adventure Elite 150 CC",
    ]

    assert [turn.composer_input["action_payload"]["name"] for turn in quote_turns] == expected_models
    for turn in quote_turns:
        assert turn.state_after["final_action"] == "quote"
        assert turn.state_after["extracted_data"]["CREDITO"]["value"] == "Sin Comprobantes"
        assert turn.state_after["extracted_data"]["ENGANCHE"]["value"] == "20%"
        assert "ine" not in turn.outbound_messages[0].casefold()


async def test_deictic_quote_request_reuses_current_model_after_model_change() -> None:
    trace = await _run_scenario(
        [
            "quiero la r4 a credito",
            "llevo 3 anos",
            "me pagan por fuera",
            "no, una custom black",
            "y esa cuanto",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "quiero la r4 a credito": _nlu(
                Intent.ASK_INFO,
                entities={"MOTO": "R4 250 CC"},
            ),
            "llevo 3 anos": _nlu(Intent.ASK_INFO, entities={"FILTRO": True}),
            "me pagan por fuera": _nlu(
                Intent.ASK_INFO,
                entities={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
            ),
            "no, una custom black": _nlu(
                Intent.ASK_INFO,
                entities={"MOTO": "Custom Black 175 CC"},
            ),
            "y esa cuanto": _nlu(Intent.ASK_PRICE),
        },
    )

    deictic_turn = trace[4]
    outbound = " ".join(deictic_turn.outbound_messages or []).casefold()

    assert deictic_turn.state_after["final_action"] == "quote"
    assert deictic_turn.composer_input["action_payload"]["name"] == "Custom Black 175 CC"
    assert "custom" in outbound
    assert "enganche" in outbound


async def test_model_change_back_to_previous_model_uses_correct_quote() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "y la R4 cuanto queda?",
            "la adventure otra vez cuanto queda?",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "y la R4 cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
            "la adventure otra vez cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "Adventure Elite 150 CC"}
            ),
        },
    )

    final_turn = trace[-1]
    decision = _decision_layer(final_turn)

    assert final_turn.state_after["final_action"] == "quote"
    assert final_turn.state_after["extracted_data"]["MOTO"]["value"] == "Adventure Elite 150 CC"
    assert final_turn.composer_input["action_payload"]["name"] == "Adventure Elite 150 CC"
    assert decision["previous_model"] == "R4 250 CC"
    assert decision["new_model"] == "Adventure Elite 150 CC"


async def test_catalog_selection_after_cheaper_option_requotes_selected_candidate() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "otra mas barata",
            "la primera",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "otra mas barata": _nlu(Intent.ASK_INFO, confidence=0.86),
            "la primera": _nlu(Intent.UNCLEAR),
        },
    )

    browse_turn = trace[4]
    selected_turn = trace[5]
    decision = _decision_layer(selected_turn)

    assert browse_turn.state_after["final_action"] == "search_catalog"
    assert selected_turn.state_after["final_action"] == "quote"
    assert selected_turn.composer_input["action_payload"]["name"] != "Adventure Elite 150 CC"
    assert decision["model_change_detected"] is True
    assert selected_turn.composer_input["action_payload"]["model_change_source"] == "catalog_selection"
    assert decision["selected_catalog_candidate"] == selected_turn.composer_input["action_payload"]["name"]


async def test_browse_does_not_override_explicit_model_request() -> None:
    trace = await _run_scenario(
        ["hola", "15 anos", "me pagan por fuera", "adventure", "y la R4 cuanto queda?"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "y la R4 cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
        },
    )

    turn5 = trace[4]
    decision = _decision_layer(turn5)

    assert turn5.state_after["final_action"] == "quote"
    assert turn5.composer_input["action_payload"]["name"] == "R4 250 CC"
    assert "catalog_browse_request" not in decision["reason"]
    assert "resolved_model_before_catalog_browse" in turn5.state_after["advisor_decision"]["blocked_commercial_actions"] or (
        "explicit_model_before_catalog_browse"
        in turn5.state_after["advisor_decision"]["blocked_commercial_actions"]
    )


async def test_documents_blocked_until_requote_after_model_change() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "que papeles son y la R4 cuanto queda?",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "que papeles son y la R4 cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
        },
    )

    turn5 = trace[4]
    decision = _decision_layer(turn5)

    assert turn5.state_after["final_action"] == "quote"
    assert turn5.composer_input["action_payload"]["name"] == "R4 250 CC"
    assert decision["documents_blocked_until_requote"] is True
    assert "ine" not in turn5.outbound_messages[0].casefold()
    assert "comprobante" not in turn5.outbound_messages[0].casefold()


async def test_response_frame_model_change_contains_previous_and_new_model() -> None:
    trace = await _run_scenario(
        ["hola", "15 anos", "me pagan por fuera", "adventure", "y la R4 cuanto queda?"],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "y la R4 cuanto queda?": _nlu(
                Intent.ASK_PRICE, entities={"MOTO": "R4 250 CC"}
            ),
        },
    )

    response_frame = trace[4].state_after["response_frame"]
    known_state = response_frame["known_customer_state"]
    trace_payload = response_frame["trace"]

    assert "model_change" in response_frame["current_intents"]
    assert response_frame["response_strategy"] in {"quote", "quote_and_resume"}
    assert response_frame["pending_flow"] is None
    assert known_state["new_model"] == "R4 250 CC"
    assert trace_payload["model_change_detected"] is True
    assert trace_payload["previous_model"] == "Adventure Elite 150 CC"
    assert trace_payload["new_model"] == "R4 250 CC"


async def test_category_selection_after_price_change_keeps_plan_and_requotes() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "otra opcion mas barata",
            "la primera",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "otra opcion mas barata": _nlu(Intent.ASK_INFO, confidence=0.86),
            "la primera": _nlu(Intent.UNCLEAR),
        },
    )

    turn5 = trace[4]
    turn6 = trace[5]
    browse_payload = turn5.composer_input["action_payload"]

    assert turn5.state_after["final_action"] == "search_catalog"
    assert browse_payload["request_type"] == "catalog_browse"
    assert browse_payload["browse_intent"] == "catalog_more"
    result_names = [item["name"] for item in browse_payload["results"]]
    assert "Adventure Elite 150 CC" not in result_names
    assert turn6.state_after["final_action"] == "quote"
    assert turn6.composer_input["action_payload"]["requested_plan_code"] == "20%"


async def test_documents_do_not_win_after_model_change_until_requote_sent() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "mejor otra mas barata",
            "la primera",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "mejor otra mas barata": _nlu(Intent.ASK_INFO, confidence=0.86),
            "la primera": _nlu(Intent.UNCLEAR),
        },
    )

    turn6 = trace[5]

    assert turn6.state_after["final_action"] == "quote"
    assert turn6.composer_input["action"] == "quote"
    assert "ine" not in turn6.outbound_messages[0].casefold()
    assert "comprobante" not in turn6.outbound_messages[0].casefold()


async def test_model_change_to_ambiguous_candidate_asks_clarification_not_documents() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "mejor otra",
            "custom",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "mejor otra": _nlu(Intent.ASK_INFO, confidence=0.84),
            "custom": _nlu(Intent.ASK_INFO, confidence=0.84),
        },
    )

    turn6 = trace[5]

    assert turn6.state_after["final_action"] == "ask_clarification"
    assert turn6.composer_input["action"] == "ask_clarification"
    assert "ine" not in turn6.outbound_messages[0].casefold()
    assert "comprobante" not in turn6.outbound_messages[0].casefold()


async def test_conv09_live_like_model_change_requotes() -> None:
    trace = await _run_scenario(
        [
            "hola",
            "15 anos",
            "me pagan por fuera",
            "adventure",
            "mejor otra mas barata",
            "la primera",
        ],
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "mejor otra mas barata": _nlu(Intent.ASK_INFO, confidence=0.86),
            "la primera": _nlu(Intent.UNCLEAR),
        },
    )

    quote_turns = [turn for turn in trace if turn.state_after["final_action"] == "quote"]
    final_quote = quote_turns[-1]

    assert len(quote_turns) >= 2
    assert final_quote.state_after["extracted_data"]["MOTO"]["value"] != "Adventure Elite 150 CC"
    assert final_quote.composer_input["action_payload"]["name"] == final_quote.state_after["extracted_data"]["MOTO"]["value"]
    assert "ine" not in final_quote.outbound_messages[0].casefold()


async def test_contextual_catalog_selection_uses_structured_browse_candidates_after_quote() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="la primera",
        seeded_outbound_text=(
            "Entiendo, dejame buscarte opciones mas economicas. "
            "Puedes ver el catalogo aqui: https://dinamomotos.com/catalogo.html."
        ),
        extracted_data={
            "MOTO": "Adventure Elite 150 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
            "ANTIGUEDAD_LABORAL": "15 anos",
            "_LAST_CATALOG_CANDIDATES": ["Alien R 175 CC", "Metro 125 CC"],
            "_LAST_CATALOG_PREVIOUS_MODEL": "Adventure Elite 150 CC",
            "_LAST_CATALOG_BROWSE_INTENT": "catalog_more",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"la primera": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] == "quote"
    assert trace.state_after["extracted_data"]["MOTO"]["value"] == "Alien R 175 CC"
    assert trace.composer_input["action_payload"]["name"] == "Alien R 175 CC"
    assert "adventure elite 150 cc" not in trace.outbound_messages[0].casefold()
    assert "ine" not in trace.outbound_messages[0].casefold()


async def test_context_short_yes_resolves_pending_question_not_soft_close() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="si",
        seeded_outbound_text=(
            "La Adventure Elite 150 CC de contado queda en $50,400.\n\n"
            "Con tu plan 20%:\n"
            "Enganche: $10,080\n"
            "Pago quincenal: $1,820\n"
            "Plazo: 72 quincenas"
        ),
        extracted_data={
            "MOTO": "Adventure Elite 150 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        after_seed=_seed_identity_only_requirements_fixture,
        nlu_scripts_override={"si": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] == "classify_document"
    assert trace.composer_input["action"] == "classify_document"
    assert "$" not in trace.outbound_messages[0]
    assert "ine" in trace.outbound_messages[0].casefold()


async def test_context_esa_resolves_single_candidate() -> None:
    trace = await _run_scenario(
        ["hola", "por fuera", "que deportivas tienes", "esa"],
        after_seed=_seed_catalog_resolution_fixture,
    )

    turn4 = trace[3]
    resolver = _resolver_layer(turn4)
    metadata = turn4.composer_input["decision_payload"]["metadata"]

    assert resolver["selected_attempt"]["resolver"] == "catalog_context_resolver"
    assert turn4.state_after["extracted_data"]["MOTO"]["value"] == "R4 250 CC"
    assert turn4.state_after["final_action"] == "quote"
    assert metadata["resolved_from_context"] is True


async def test_context_la_primera_uses_pending_options() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="la primera",
        seeded_outbound_text=(
            "Entiendo, dejame buscarte opciones mas economicas. "
            "Puedes ver el catalogo aqui: https://dinamomotos.com/catalogo.html."
        ),
        extracted_data={
            "MOTO": "Adventure Elite 150 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
            "_LAST_CATALOG_CANDIDATES": ["Alien R 175 CC", "Metro 125 CC"],
            "_LAST_CATALOG_PREVIOUS_MODEL": "Adventure Elite 150 CC",
            "_LAST_CATALOG_BROWSE_INTENT": "catalog_more",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={"la primera": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] == "quote"
    assert trace.state_after["extracted_data"]["MOTO"]["value"] == "Alien R 175 CC"
    assert trace.composer_input["action_payload"]["name"] == "Alien R 175 CC"


async def test_context_ok_after_document_prompt_does_not_requote() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="ok",
        seeded_outbound_text=(
            "Para seguir, mandame primero INE por ambos lados y comprobante de domicilio reciente."
        ),
        extracted_data={
            "MOTO": "Adventure Elite 150 CC",
            "CREDITO": "Nomina Tarjeta",
            "ENGANCHE": "10%",
        },
        nlu_scripts_override={"ok": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] != "quote"
    assert trace.composer_input["action"] != "quote"
    assert "$" not in trace.outbound_messages[0]


async def test_context_va_after_quote_advances_documents_not_soft_close() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="va",
        seeded_outbound_text=(
            "La Adventure Elite 150 CC de contado queda en $50,400.\n\n"
            "Con tu plan 20%:\n"
            "Enganche: $10,080\n"
            "Pago quincenal: $1,820\n"
            "Plazo: 72 quincenas"
        ),
        extracted_data={
            "MOTO": "Adventure Elite 150 CC",
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        after_seed=_seed_identity_only_requirements_fixture,
        nlu_scripts_override={"va": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] == "classify_document"
    assert trace.composer_input["action"] == "classify_document"
    outbound = trace.outbound_messages[0].casefold()
    assert "document" in outbound
    assert "ine" in outbound


async def test_context_short_reply_without_context_asks_clarification() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="si",
        nlu_scripts_override={"si": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] == "ask_clarification"
    assert trace.composer_input["action"] == "ask_clarification"


async def test_multi_intent_payoff_buro_location_answers_all() -> None:
    trace = await _run_scenario(["puedo liquidar antes? checan buro? ubicacion"])

    turn1 = trace[0]
    payload = turn1.composer_input["action_payload"]
    decision = _decision_layer(turn1)

    assert turn1.composer_input["action"] == "lookup_faq"
    assert set(payload["answered_intents"]) == {"liquidacion", "buro", "ubicacion"}
    assert set(decision["answered_intents"]) == {"liquidacion", "buro", "ubicacion"}
    outbound = turn1.outbound_messages[0].casefold()
    assert "liquid" in outbound
    assert "buro" in outbound
    assert "monterrey" in outbound
    assert decision["soft_close_applied"] is False


async def test_conv06_live_like_multi_intent_outbound_preserves_faq_answers_before_resume() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="puedo liquidar antes? checan buro? donde estan?",
        extracted_data={"MOTO": "R4 250 CC"},
        nlu_scripts_override={
            "puedo liquidar antes? checan buro? donde estan?": _nlu(
                Intent.ASK_INFO,
                confidence=0.9,
                entities={"multi_intent": ["liquidacion", "buro", "ubicacion"]},
            )
        },
    )

    outbound = trace.outbound_messages[0].casefold()

    assert trace.state_after["final_action"] in {"lookup_faq", "ask_credit_context"}
    assert "liquid" in outbound
    assert "buro" in outbound
    assert "monterrey" in outbound
    assert any(
        term in outbound
        for term in ("como recibes", "recibes tus ingresos", "falta como recibes ingresos")
    )


async def test_multi_intent_answers_faq_and_resumes_credit_flow() -> None:
    trace = await _run_scenario(["hola", "por fuera", "revisan buro y que requisitos piden?"])

    turn3 = trace[2]
    payload = turn3.composer_input["action_payload"]
    decision = _decision_layer(turn3)

    assert turn3.composer_input["action"] == "lookup_faq"
    assert "buro" in payload["answered_intents"]
    assert "requirements" in payload["answered_intents"]
    assert payload["resume_pending_action"] == {"type": "ask_field", "field": "MOTO"}
    assert decision["next_required_step"] == {"type": "ask_field", "field": "MOTO"}
    assert "modelo" in turn3.outbound_messages[0].casefold()


async def test_nomina_tarjeta_does_not_ask_recibos_before_quote() -> None:
    trace = await _run_scenario(["hola", "r4", "Por tarjeta"])

    turn3 = trace[2]

    assert turn3.state_after["extracted_data"]["CREDITO"]["value"] == "Nomina Tarjeta"
    assert turn3.state_after["extracted_data"]["ENGANCHE"]["value"] == "10%"
    assert turn3.state_after["final_action"] == "quote"
    assert "recibos" not in turn3.outbound_messages[0].casefold()


async def test_resolved_credit_plan_moves_to_model_or_quote_not_extra_income_question() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="Por tarjeta",
        seeded_outbound_text="Para seguir, como recibes tus ingresos?",
        extracted_data={"FILTRO": True},
    )
    payload = trace.composer_input["action_payload"]

    assert trace.state_after["extracted_data"]["CREDITO"]["value"] == "Nomina Tarjeta"
    assert trace.state_after["extracted_data"]["ENGANCHE"]["value"] == "10%"
    assert trace.state_after["final_action"] in {"ask_field", "quote"}
    if trace.state_after["final_action"] == "ask_field":
        assert payload["field_name"] == "MOTO"
    assert "recibos" not in trace.outbound_messages[0].casefold()
    if trace.state_after["final_action"] == "ask_field":
        assert "modelo" in trace.outbound_messages[0].casefold()


async def test_yes_after_location_question_gives_location() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="si",
        seeded_outbound_text="Si quieres te paso la ubicación.",
    )
    payload = trace.composer_input["action_payload"]
    decision = _decision_layer(trace)

    assert trace.composer_input["action"] == "lookup_faq"
    assert decision["resolved_followup_intent"] == "ubicacion"
    assert decision["yes_no_context_resolution"] == "location_confirmation"
    assert "monterrey" in trace.outbound_messages[0].casefold()
    assert trace.state_after["final_action"] == "lookup_faq"


async def test_yes_after_model_confirmation_resolves_and_quotes_when_plan_ready() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="si",
        seeded_outbound_text="Tengo Adventure Elite 150 CC, te refieres a Adventure Elite 150 CC?",
        extracted_data={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%", "FILTRO": True},
        after_seed=_seed_catalog_resolution_fixture,
    )
    decision = _decision_layer(trace)

    assert trace.state_after["extracted_data"]["MOTO"]["value"] == "Adventure Elite 150 CC"
    assert trace.state_after["final_action"] == "quote"
    assert decision["resolved_followup_intent"] == "modelo"
    assert decision["quote_gate_evaluated"] is True


async def test_si_after_quote_offer_quotes_or_requests_missing_field() -> None:
    quoted = await _run_single_turn_with_seeded_context(
        inbound_text="si",
        seeded_outbound_text="Te la cotizo?",
        extracted_data={
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
            "FILTRO": True,
            "MOTO": "R4 250 CC",
        },
    )
    assert quoted.state_after["final_action"] == "quote"

    missing_field = await _run_single_turn_with_seeded_context(
        inbound_text="si",
        seeded_outbound_text="Te la cotizo?",
        extracted_data={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
    )
    decision = _decision_layer(missing_field)
    assert missing_field.state_after["final_action"] == "ask_field"
    assert decision["next_required_step"] == {"type": "ask_field", "field": "MOTO"}


async def test_ok_after_quote_can_soft_close_only_when_no_active_intent() -> None:
    trace = await _run_scenario(["hola", "r4", "por fuera", "20", "ok"])

    turn5 = trace[4]
    decision = _decision_layer(turn5)
    assert turn5.state_after["final_action"] == "soft_close"
    assert decision["soft_close_applied"] is True


async def test_ok_with_pending_question_does_not_soft_close() -> None:
    trace = await _run_scenario(["hola", "r4", "ok"])

    turn3 = trace[2]
    decision = _decision_layer(turn3)
    assert turn3.state_after["final_action"] != "soft_close"
    assert decision["soft_close_applied"] is False
    assert decision["soft_close_blocked_reason"] is not None


async def test_multi_message_intent_pack_answers_all_recent_questions() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="ubicacion",
        prior_inbound_messages=["puedo liquidar antes?", "checan buro?"],
    )
    decision = _decision_layer(trace)
    payload = trace.composer_input["action_payload"]

    assert trace.composer_input["action"] == "lookup_faq"
    assert set(decision["intent_stack"]) == {"liquidacion", "buro", "ubicacion"}
    assert set(payload["answered_intents"]) == {"liquidacion", "buro", "ubicacion"}
    outbound = trace.outbound_messages[0].casefold()
    assert "liquid" in outbound
    assert "buro" in outbound
    assert "monterrey" in outbound


async def test_multi_intent_price_requirements_quotes_before_documents_when_ready() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "cuanto sale y que requisitos ocupo?"],
        nlu_scripts_override={
            "cuanto sale y que requisitos ocupo?": _nlu(Intent.ASK_PRICE, confidence=0.9),
        },
    )

    turn5 = trace[4]
    payload = turn5.composer_input["action_payload"]
    decision = _decision_layer(turn5)

    assert turn5.state_after["final_action"] == "quote"
    assert turn5.composer_input["action"] == "quote"
    assert payload["status"] == "ok"
    assert payload["requirements"]["selection_key"] == "Sin Comprobantes"
    assert decision["quote_gate_evaluated"] is True
    assert "enganche" in turn5.outbound_messages[0].casefold()
    assert "INE-FRENTE" in turn5.outbound_messages[0]


async def test_complaint_price_before_documents_forces_quote() -> None:
    trace = await _run_scenario(
        ["hola", "r4", "por fuera", "20", "no voy a mandar nada antes de saber cuanto sale"],
        nlu_scripts_override={
            "no voy a mandar nada antes de saber cuanto sale": _nlu(
                Intent.ASK_INFO,
                confidence=0.9,
            ),
        },
    )

    turn5 = trace[4]
    outbound = turn5.outbound_messages[0].casefold()

    assert turn5.state_after["final_action"] == "quote"
    assert turn5.composer_input["action"] == "quote"
    assert "document" not in outbound
    assert "enganche" in outbound


async def test_complaint_no_docs_before_price_quotes_if_ready() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="pero no voy a mandar nada antes de saber cuánto sale",
        seeded_outbound_text="Perfecto, ya quedó tu plan Sin Comprobantes con 20% de enganche. Para cotizarte bien dime qué modelo quieres revisar.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
            "MOTO": "Adventure Elite 150 CC",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "pero no voy a mandar nada antes de saber cuánto sale": _nlu(Intent.ASK_INFO, confidence=0.9),
        },
    )

    outbound = trace.outbound_messages[0].casefold()

    assert trace.state_after["final_action"] == "quote"
    assert "document" not in outbound
    assert "enganche" in outbound


async def test_complaint_no_docs_before_price_asks_only_missing_quote_field() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="pero no voy a mandar nada antes de saber cuánto sale",
        seeded_outbound_text="Perfecto, ya quedó tu plan Sin Comprobantes con 20% de enganche. Para cotizarte bien dime qué modelo quieres revisar.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "pero no voy a mandar nada antes de saber cuánto sale": _nlu(Intent.ASK_INFO, confidence=0.9),
        },
    )

    outbound = trace.outbound_messages[0].casefold()
    payload = trace.composer_input["action_payload"]

    assert trace.state_after["final_action"] in {"ask_field", "ask_credit_context"}
    assert payload.get("field_name") == "MOTO"
    assert "document" not in outbound
    assert "modelo" in outbound


async def test_complaint_blocks_document_request_until_quote() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="pero no voy a mandar nada antes de saber cuánto sale",
        seeded_outbound_text="Perfecto, ya quedó tu plan Sin Comprobantes con 20% de enganche. Para cotizarte bien dime qué modelo quieres revisar.",
        extracted_data={
            "FILTRO": True,
            "CREDITO": "Sin Comprobantes",
            "ENGANCHE": "20%",
        },
        after_seed=_seed_catalog_resolution_fixture,
        nlu_scripts_override={
            "pero no voy a mandar nada antes de saber cuánto sale": _nlu(Intent.ASK_INFO, confidence=0.9),
        },
    )

    outbound = trace.outbound_messages[0].casefold()

    assert trace.state_after["final_action"] != "classify_document"
    assert "ine" not in outbound
    assert "domicilio" not in outbound


async def test_customer_asks_requirements_before_model_answers_but_returns_to_missing_model() -> None:
    trace = await _run_scenario(
        ["hola", "por fuera", "que requisitos piden?"],
        nlu_scripts_override={
            "que requisitos piden?": _nlu(Intent.ASK_INFO, confidence=0.88),
        },
    )

    turn3 = trace[2]
    payload = turn3.composer_input["action_payload"]

    assert turn3.state_after["final_action"] == "lookup_faq"
    assert payload["resume_pending_action"] == {"type": "ask_field", "field": "MOTO"}
    assert "modelo" in turn3.outbound_messages[0].casefold()
    assert "document" not in turn3.outbound_messages[0].casefold()


async def test_pdf_with_ine_both_sides_updates_front_back_and_requests_next_missing() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="[pdf ine]",
        extracted_data={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%", "MOTO": "R4 250 CC"},
        attachments=[
            Attachment(
                media_id="media-pdf-ine-front",
                mime_type="application/pdf",
                url="https://example.test/ine.pdf",
                caption="ine frente",
            ),
            Attachment(
                media_id="media-pdf-ine-back",
                mime_type="application/pdf",
                url="https://example.test/ine.pdf",
                caption="ine atras",
            ),
        ],
        metadata_override={
            "attachments": [
                {"semantic_label": "ine frente"},
                {"semantic_label": "ine atras"},
            ]
        },
        nlu_scripts_override={"[pdf ine]": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] == "classify_document"
    assert trace.state_after["extracted_data"]["INE_FRENTE"]["value"] == "ok"
    assert trace.state_after["extracted_data"]["INE_ATRAS"]["value"] == "ok"
    assert trace.state_after["accepted_documents"] == ["INE-FRENTE", "INE-ATRAS"]
    assert trace.state_after["next_missing_document"] == "Domicilio"
    assert "comprobante de domicilio reciente" in trace.outbound_messages[0]


async def test_ine_front_image_requests_back_only() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="[imagen ine frente]",
        extracted_data={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%", "MOTO": "R4 250 CC"},
        attachments=[
            Attachment(
                media_id="media-ine-front",
                mime_type="image/jpeg",
                url="https://example.test/ine-front.jpg",
                caption="ine frente",
            ),
        ],
        metadata_override={"attachments": [{"semantic_label": "ine frente"}]},
        after_seed=_seed_identity_only_requirements_fixture,
        nlu_scripts_override={"[imagen ine frente]": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] == "classify_document"
    assert trace.state_after["extracted_data"]["INE_FRENTE"]["value"] == "ok"
    assert "INE_ATRAS" not in trace.state_after["extracted_data"]
    assert trace.state_after["accepted_documents"] == ["INE-FRENTE"]
    assert trace.state_after["next_missing_document"] == "INE-ATRAS"
    assert "parte de atras de tu INE" in trace.outbound_messages[0]


async def test_blurry_document_rejected_without_updating_fields() -> None:
    trace = await _run_single_turn_with_seeded_context(
        inbound_text="[imagen borrosa]",
        extracted_data={"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%", "MOTO": "R4 250 CC"},
        attachments=[
            Attachment(
                media_id="media-blurry",
                mime_type="image/jpeg",
                url="https://example.test/blurry.jpg",
                caption="borrosa",
            ),
        ],
        metadata_override={"attachments": [{"semantic_label": "borrosa"}]},
        nlu_scripts_override={"[imagen borrosa]": _nlu(Intent.UNCLEAR)},
    )

    assert trace.state_after["final_action"] == "classify_document"
    assert "INE_FRENTE" not in trace.state_after["extracted_data"]
    assert trace.state_after["accepted_documents"] == []
    assert trace.state_after["missing_documents_after_turn"] == [
        "INE-FRENTE",
        "Domicilio",
        "INE-ATRAS",
    ]
    assert "clara" in trace.outbound_messages[0].casefold()


async def test_conversation_summary_feeds_composer_when_recent_history_is_empty() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    composer = _SummaryAwareComposer()
    try:
        await _seed_runner_flow_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
        )
        await _set_composer_history_turns(session, tenant_id=tenant_id, turns=0)
        runner = _NoAgentRunner(session, _primary_flow_nlu(), composer)
        traces = []
        for index, text in enumerate(
            ["hola", "me interesa la r4", "a crédito", "por fuera", "20", "revisan buro?"],
            start=1,
        ):
            traces.append(
                await _run_persisted_turn(
                    session=session,
                    runner=runner,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    turn_number=index,
                    text=text,
                    sent_at=started_at + timedelta(minutes=index),
                )
            )

        turn6 = traces[5]
        context_pack = turn6.composer_input["context_pack"]
        summary = context_pack["conversation_summary"]

        assert turn6.composer_input["history"] == []
        assert context_pack["recent_history"] == []
        assert "me interesa la r4" not in summary
        assert "R4 250 CC" in summary
        assert "Sin Comprobantes" in summary
        assert "20%" in summary
        assert "Ultima cotizacion: R4 250 CC" in summary
        assert "FAQ respondida (buro): Si, se revisa buro." in summary
        assert "sigo con tu r4 250 cc al 20%" in turn6.outbound_messages[0].casefold()
        customer = await session.get(Customer, customer_id)
        assert customer is not None
        assert customer.ai_summary == summary
        assert turn6.state_after["conversation_summary"] == summary
    finally:
        await session.rollback()
        await session.close()


async def _run_scenario(
    turns: list[str],
    composer: _FlowComposer | None = None,
    after_seed=None,
    nlu_scripts_override: dict[str, NLUResult] | None = None,
) -> list:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    composer = composer or _FlowComposer()
    try:
        await _seed_runner_flow_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
        )
        if after_seed is not None:
            await after_seed(
                session=session,
                tenant_id=tenant_id,
                created_at=started_at,
            )
        runner = _NoAgentRunner(
            session,
            _primary_flow_nlu_with_overrides(nlu_scripts_override),
            composer,
        )
        traces = []
        for index, text in enumerate(turns, start=1):
            traces.append(
                await _run_persisted_turn(
                    session=session,
                    runner=runner,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    turn_number=index,
                    text=text,
                    sent_at=started_at + timedelta(minutes=index),
                )
            )
        return traces
    finally:
        await session.rollback()
        await session.close()


def _quote_payload_fixture() -> dict[str, object]:
    return {
        "status": "ok",
        "sku": "R4-250",
        "name": "R4 250 CC",
        "category": "Deportiva",
        "list_price_mxn": "55335",
        "cash_price_mxn": "52700",
        "requested_plan_code": "10%",
        "active_purchase_mode": "credit",
        "payment_options": {
            "10%": {
                "down_payment_mxn": 5534,
                "installment_mxn": 2198,
                "frequency": "quincenal",
                "term_count": 72,
            }
        },
    }


async def _run_single_turn_with_seeded_context(
    *,
    inbound_text: str,
    seeded_outbound_text: str | None = None,
    prior_inbound_messages: list[str] | None = None,
    extracted_data: dict[str, object] | None = None,
    attachments: list[Attachment] | None = None,
    metadata_override: dict[str, object] | None = None,
    after_seed=None,
    nlu_scripts_override: dict[str, NLUResult] | None = None,
    composer: _FlowComposer | None = None,
):
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    started_at = datetime.now(UTC)
    composer = composer or _FlowComposer()
    try:
        await _seed_runner_flow_fixture(
            session=session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            created_at=started_at,
        )
        if after_seed is not None:
            await after_seed(
                session=session,
                tenant_id=tenant_id,
                created_at=started_at,
            )
        state_row = await session.get(ConversationStateRow, conversation_id)
        if state_row is not None and extracted_data:
            state_row.extracted_data = {
                key: {"value": value, "confidence": 1.0, "source_turn": 0}
                for key, value in extracted_data.items()
            }
        for index, text in enumerate(prior_inbound_messages or [], start=1):
            session.add(
                MessageRow(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    direction="inbound",
                    text=text,
                    channel_message_id=f"wamid.pytest.seed.in.{index}",
                    delivery_status="received",
                    metadata_json={"source": "pytest_multiturn_seed"},
                    sent_at=started_at + timedelta(seconds=index),
                )
            )
        if seeded_outbound_text:
            session.add(
                MessageRow(
                    id=uuid4(),
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    direction="outbound",
                    text=seeded_outbound_text,
                    channel_message_id="wamid.pytest.seed.out.1",
                    delivery_status="sent",
                    metadata_json={"source": "pytest_multiturn_seed"},
                    sent_at=started_at + timedelta(seconds=30),
                )
            )
        await session.flush()
        runner = _NoAgentRunner(
            session,
            _primary_flow_nlu_with_overrides(nlu_scripts_override),
            composer,
        )
        return await _run_persisted_turn(
            session=session,
            runner=runner,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_number=99,
            text=inbound_text,
            sent_at=started_at + timedelta(minutes=2),
            metadata=metadata_override,
            attachments=attachments,
        )
    finally:
        await session.rollback()
        await session.close()


async def _set_composer_history_turns(session, *, tenant_id, turns: int) -> None:
    row = (
        await session.execute(
            select(TenantPipeline).where(
                TenantPipeline.tenant_id == tenant_id,
                TenantPipeline.active.is_(True),
            )
        )
    ).scalar_one()
    definition = dict(row.definition or {})
    definition["composer"] = {"history_turns": turns}
    row.definition = definition
    await session.flush()


async def _seed_catalog_resolution_fixture(
    *,
    session,
    tenant_id,
    created_at: datetime,
) -> None:
    catalog = (
        await session.execute(select(Catalog).where(Catalog.tenant_id == tenant_id))
    ).scalar_one()
    extra_specs = [
        ("ADV-150", "Adventure Elite 150 CC", "Motoneta", ["adventure", "adventure elite", "elite 150"]),
        ("ALIEN-175", "Alien R 175 CC", "Motoneta", ["alien", "alien r", "alien r 175"]),
        ("METRO-125", "Metro 125 CC", "Motoneta", ["metro", "metro 125"]),
        ("CUSTOM-150", "Custom 150 CC", "Chopper", ["custom", "custom 150"]),
        (
            "CUSTOM-BLACK-175",
            "Custom Black 175 CC",
            "Chopper",
            ["custom black", "custom 175", "custom"],
        ),
    ]
    for sku, name, category, aliases in extra_specs:
        item = CatalogItem(
            tenant_id=tenant_id,
            catalog_id=catalog.id,
            sku=sku,
            name=name,
            category=category,
            base_price=Decimal("48000.00"),
            list_price=Decimal("50400.00"),
            stock_status="available",
            stock_quantity=3,
            status="active",
            attributes_json={
                "modelo_moto": name,
                "precio_lista_mxn": 50400,
                "precio_contado_mxn": 48000,
                "alias_normalizados": aliases,
            },
            ai_rules_json={"can_quote": True, "requires_plan": True},
            tags_json=[category.casefold()],
            updated_at=created_at,
        )
        session.add(item)
        await session.flush()
        for plan_name, down_payment, installment in (
            ("10%", "5040.00", "2100.00"),
            ("15%", "7560.00", "1980.00"),
            ("20%", "10080.00", "1820.00"),
            ("30%", "15120.00", "1440.00"),
        ):
            session.add(
                CatalogItemPlan(
                    tenant_id=tenant_id,
                    catalog_item_id=item.id,
                    plan_name=plan_name,
                    plan_code=plan_name,
                    down_payment_amount=Decimal(down_payment),
                    installment_amount=Decimal(installment),
                    installment_frequency="quincenal",
                    installment_count=72,
                    status="active",
                )
            )
    await session.flush()
    await publish_authoring_catalog(
        session,
        tenant_id=tenant_id,
        catalog_id=catalog.id,
        actor_user_id=None,
    )
    await session.flush()


async def _seed_identity_only_requirements_fixture(
    *,
    session,
    tenant_id,
    created_at: datetime,
) -> None:
    row = (
        await session.execute(
            select(TenantPipeline).where(
                TenantPipeline.tenant_id == tenant_id,
                TenantPipeline.active.is_(True),
            )
        )
    ).scalar_one()
    definition = dict(row.definition or {})
    definition["document_requirements"] = {
        "Sin Comprobantes": ["INE_FRENTE", "INE_ATRAS"],
    }
    row.definition = definition
    await session.flush()


async def _seed_runner_flow_fixture(
    *,
    session,
    tenant_id,
    customer_id,
    conversation_id,
    created_at: datetime,
) -> None:
    session.add(
        Tenant(
            id=tenant_id,
            name=f"pytest-multiturn-{tenant_id}",
            status="active",
            config={
                "knowledge_pack_version": "2026-05-23",
                "knowledge_pack": {
                    "tenant_id": "dinamo_nl",
                    "pack_version": "2026-05-23",
                    "faq_policies": {
                        "buro": [
                            {
                                "topic": "buro",
                                "question": "Revisan buro?",
                                "answer": "Si, se revisa buro.",
                                "tags": ["buro", "credito"],
                            }
                        ],
                        "liquidacion": [
                            {
                                "topic": "liquidacion",
                                "question": "Puedo liquidar antes?",
                                "answer": "Si puedes liquidar antes y se recalculan los intereses.",
                                "tags": ["liquidar", "adelantar pagos", "abonar"],
                            }
                        ],
                        "ubicacion": [
                            {
                                "topic": "ubicacion",
                                "question": "Donde estan?",
                                "answer": "Estamos en Monterrey, Nuevo Leon.",
                                "tags": ["ubicacion", "direccion", "donde"],
                            }
                        ],
                        "aval": [
                            {
                                "topic": "aval",
                                "question": "Piden aval?",
                                "answer": "Depende del perfil; si llega a aplicar te lo confirmamos en revision.",
                                "tags": ["aval"],
                            }
                        ],
                    },
                },
            },
        )
    )
    await session.flush()
    session.add_all(
        [
            CustomerFieldDefinition(
                tenant_id=tenant_id,
                key="FILTRO",
                label="Filtro Antiguedad",
                field_type="checkbox",
                ordering=1,
            ),
            CustomerFieldDefinition(
                tenant_id=tenant_id,
                key="CREDITO",
                label="Plan Credito",
                field_type="text",
                ordering=2,
                field_options={
                    "turn_resolver": {
                        "pending_field": {
                            "enabled": True,
                            "aliases": {
                                "por fuera": "Sin Comprobantes",
                                "me pagan por fuera": "Sin Comprobantes",
                                "sin comprobantes": "Sin Comprobantes",
                            },
                        }
                    }
                },
            ),
            CustomerFieldDefinition(
                tenant_id=tenant_id,
                key="ENGANCHE",
                label="Enganche",
                field_type="text",
                ordering=3,
                field_options={
                    "turn_resolver": {
                        "numeric_answer": {
                            "enabled": True,
                            "allowed_values": ["10%", "15%", "20%", "30%"],
                        }
                    }
                },
            ),
            CustomerFieldDefinition(
                tenant_id=tenant_id,
                key="MOTO",
                label="Moto",
                field_type="catalog_item",
                ordering=4,
                field_options={
                    "catalog_binding": {
                        "source": "active_catalog",
                        "enabled": True,
                        "min_score": 1,
                        "save_when": "single_confident_match",
                        "canonical_field": "name",
                    }
                },
            ),
            CustomerFieldDefinition(
                tenant_id=tenant_id,
                key="INE_FRENTE",
                label="INE-FRENTE",
                field_type="document",
                ordering=5,
                field_options={
                    "choices": ["missing", "ok", "rejected"],
                    "is_document_status": True,
                },
            ),
            CustomerFieldDefinition(
                tenant_id=tenant_id,
                key="INE_ATRAS",
                label="INE-ATRAS",
                field_type="document",
                ordering=6,
                field_options={
                    "choices": ["missing", "ok", "rejected"],
                    "is_document_status": True,
                },
            ),
            CustomerFieldDefinition(
                tenant_id=tenant_id,
                key="COMPROBANTE_DOMICILIO",
                label="Domicilio",
                field_type="document",
                ordering=7,
                field_options={
                    "choices": ["missing", "ok", "rejected"],
                    "is_document_status": True,
                },
            ),
        ]
    )
    session.add(
        TenantPipeline(
            tenant_id=tenant_id,
            version=1,
            active=True,
            definition={
                "version": 1,
                "fallback": "ask_clarification",
                "document_requirements_field": "CREDITO",
                "document_requirements": {
                    "Sin Comprobantes": [
                        "INE_FRENTE",
                        "COMPROBANTE_DOMICILIO",
                        "INE_ATRAS",
                    ]
                },
                "selection_catalog": {
                    "Sin Comprobantes": {
                        "label": "Sin Comprobantes",
                        "aliases": [
                            "por fuera",
                            "me pagan por fuera",
                            "sin comprobantes",
                            "20%",
                        ],
                    }
                },
                "documents_catalog": [
                    {"key": "INE_FRENTE", "label": "INE-FRENTE"},
                    {"key": "INE_ATRAS", "label": "INE-ATRAS"},
                    {"key": "COMPROBANTE_DOMICILIO", "label": "Domicilio"},
                ],
                "stages": [
                    {
                        "id": "nuevos",
                        "label": "Nuevos",
                        "behavior_mode": "PLAN",
                        "actions_allowed": ["greet", "ask_field", "ask_clarification"],
                    },
                    {
                        "id": "credito",
                        "label": "Credito",
                        "behavior_mode": "PLAN",
                        "actions_allowed": [
                            "ask_field",
                            "ask_clarification",
                            "search_catalog",
                            "quote",
                        ],
                        "auto_enter_rules": {
                            "enabled": True,
                            "match": "all",
                            "conditions": [{"field": "CREDITO", "operator": "exists"}],
                        },
                    },
                    {
                        "id": "potencialcliente",
                        "label": "Cliente Potencial",
                        "behavior_mode": "PLAN",
                        "actions_allowed": [
                            "ask_field",
                            "ask_clarification",
                            "search_catalog",
                            "quote",
                        ],
                        "auto_enter_rules": {
                            "enabled": True,
                            "match": "all",
                            "conditions": [
                                {"field": "CREDITO", "operator": "exists"},
                                {"field": "MOTO", "operator": "exists"},
                                {"field": "ENGANCHE", "operator": "exists"},
                            ],
                        },
                    },
                    {
                        "id": "doc_incompleta",
                        "label": "Papeleria Incompleta",
                        "behavior_mode": "PLAN",
                        "actions_allowed": ["ask_field", "ask_clarification"],
                    },
                ],
            },
        )
    )
    session.add(
        Customer(
            id=customer_id,
            tenant_id=tenant_id,
            phone_e164=f"+521555{str(customer_id.int)[-7:]}",
            name="Cliente Multi Turn",
            attrs={},
            status="active",
            stage="nuevos",
            last_activity_at=created_at,
        )
    )
    await session.flush()
    session.add(
        Conversation(
            id=conversation_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel="whatsapp_meta",
            status="active",
            current_stage="nuevos",
            last_activity_at=created_at,
        )
    )
    session.add(
        ConversationStateRow(
            conversation_id=conversation_id,
            extracted_data={},
            stage_entered_at=created_at,
            total_cost_usd=Decimal("0"),
            bot_paused=False,
        )
    )
    catalog = Catalog(
        tenant_id=tenant_id,
        name="Catalogo motos pytest",
        vertical="motorcycles",
        currency="MXN",
        status="draft",
        updated_at=created_at,
    )
    session.add(catalog)
    await session.flush()
    item = CatalogItem(
        tenant_id=tenant_id,
        catalog_id=catalog.id,
        sku="R4-250",
        name="R4 250 CC",
        category="Deportiva",
        base_price=Decimal("52700.00"),
        list_price=Decimal("55335.00"),
        stock_status="available",
        stock_quantity=3,
        status="active",
        attributes_json={
            "modelo_moto": "R4 250 CC",
            "precio_lista_mxn": 55335,
            "precio_contado_mxn": 52700,
            "alias_normalizados": ["r4 250 cc", "r4", "r4cc", "r4 250", "r4 250cc", "r4250cc"],
            "ficha_tecnica": {
                "motor_cc": 250,
                "potencia_hp": 24,
                "rendimiento_km_l": "23-26",
                "peso_kg": 165,
                "tanque_l": 14,
                "altura_asiento_cm": 78,
                "transmision": "Estandar",
            },
        },
        ai_rules_json={"can_quote": True, "requires_plan": True},
        tags_json=["deportiva", "potencia"],
        updated_at=created_at,
    )
    session.add(item)
    await session.flush()
    for sku, name, category in (
        ("MOTO-TAXI", "Moto Taxi", "Trabajo"),
        ("COMANDO-400", "Comando 400 CC", "Doble proposito"),
    ):
        session.add(
            CatalogItem(
                tenant_id=tenant_id,
                catalog_id=catalog.id,
                sku=sku,
                name=name,
                category=category,
                base_price=Decimal("50000.00"),
                list_price=Decimal("52000.00"),
                stock_status="available",
                stock_quantity=2,
                status="active",
                attributes_json={
                    "modelo_moto": name,
                    "alias_normalizados": [name.casefold(), sku.casefold()],
                },
                ai_rules_json={"can_quote": False},
                tags_json=[category.casefold()],
                updated_at=created_at,
            )
        )
    await session.flush()
    for plan_name, down_payment, installment in (
        ("10%", "5534.00", "2198.00"),
        ("15%", "8300.00", "2169.00"),
        ("20%", "11067.00", "1792.00"),
        ("30%", "16601.00", "1364.00"),
    ):
        session.add(
            CatalogItemPlan(
                tenant_id=tenant_id,
                catalog_item_id=item.id,
                plan_name=plan_name,
                plan_code=plan_name,
                down_payment_amount=Decimal(down_payment),
                installment_amount=Decimal(installment),
                installment_frequency="quincenal",
                installment_count=72,
                status="active",
            )
        )
    await session.flush()
    await publish_authoring_catalog(
        session,
        tenant_id=tenant_id,
        catalog_id=catalog.id,
        actor_user_id=None,
    )
    await session.flush()


async def _run_persisted_turn(
    *,
    session,
    runner: ConversationRunner,
    tenant_id,
    conversation_id,
    turn_number: int,
    text: str,
    sent_at: datetime,
    metadata: dict[str, object] | None = None,
    attachments: list[Attachment] | None = None,
):
    inbound_id = uuid4()
    session.add(
        MessageRow(
            id=inbound_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            direction="inbound",
            text=text,
            channel_message_id=f"wamid.pytest.in.{turn_number}",
            delivery_status="received",
            metadata_json={"source": "pytest_multiturn", **(metadata or {})},
            sent_at=sent_at,
        )
    )
    await session.flush()
    trace = await runner.run_turn(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        inbound=Message(
            id=str(inbound_id),
            conversation_id=str(conversation_id),
            tenant_id=str(tenant_id),
            direction=MessageDirection.INBOUND,
            text=text,
            sent_at=sent_at,
            metadata={"source": "pytest_multiturn", **(metadata or {})},
            attachments=attachments or [],
        ),
        turn_number=turn_number,
    )
    trace.inbound_message_id = inbound_id
    for index, outbound_text in enumerate(trace.outbound_messages or [], start=1):
        session.add(
            MessageRow(
                id=uuid4(),
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                direction="outbound",
                text=outbound_text,
                channel_message_id=f"wamid.pytest.out.{turn_number}.{index}",
                delivery_status="sent",
                metadata_json={"source": "pytest_multiturn", "turn_number": turn_number},
                sent_at=sent_at + timedelta(seconds=index),
            )
        )
    await session.flush()
    return trace


def _primary_flow_nlu() -> _ScriptedNLU:
    return _ScriptedNLU(
        {
            "hola": _nlu(Intent.GREETING),
            "buenas": _nlu(Intent.GREETING),
            "Hola quiero info de credito": _nlu(Intent.ASK_INFO, confidence=0.8),
            "A ver las motos": _nlu(Intent.ASK_INFO, confidence=0.85),
            "Solo esas?": _nlu(Intent.ASK_INFO, confidence=0.85),
            "Dame el catalogo": _nlu(Intent.ASK_INFO, confidence=0.85),
            "que motonetas tienes": _nlu(Intent.ASK_INFO, confidence=0.85),
            "que deportivas tienes": _nlu(Intent.ASK_INFO, confidence=0.85),
            "me interesa la r4": _nlu(
                Intent.ASK_INFO,
                confidence=0.8,
                ambiguities=["intent_borderline_buy_vs_ask_price"],
                sales_signal="low",
            ),
            "la r4": _nlu(Intent.ASK_INFO, confidence=0.8, sales_signal="low"),
            "r4": _nlu(Intent.ASK_INFO, confidence=0.8, sales_signal="low"),
            "adventure": _nlu(Intent.ASK_INFO, confidence=0.82, sales_signal="low"),
            "custom": _nlu(Intent.ASK_INFO, confidence=0.82, sales_signal="low"),
            "quiero info de la r4": _nlu(Intent.ASK_INFO, confidence=0.8, sales_signal="low"),
            "a crédito": _nlu(Intent.ASK_INFO),
            "credito": _nlu(Intent.ASK_INFO),
            "por fuera": _nlu(Intent.UNCLEAR),
            "me pagan por fuera": _nlu(Intent.UNCLEAR),
            "20": _nlu(Intent.UNCLEAR),
            "la primera": _nlu(Intent.UNCLEAR),
            "esa": _nlu(Intent.UNCLEAR),
            "15 anos": _nlu(Intent.ASK_INFO, entities={"FILTRO": True}),
            "3 meses": _nlu(Intent.ASK_INFO, entities={"FILTRO": False}),
            "Por tarjeta": _nlu(
                Intent.ASK_INFO,
                entities={"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
            ),
            "revisan buro?": _nlu(Intent.ASK_INFO, confidence=0.86),
            "puedo liquidar antes? checan buro? ubicacion": _nlu(Intent.ASK_INFO, confidence=0.9),
            "revisan buro y que requisitos piden?": _nlu(Intent.ASK_INFO, confidence=0.88),
            "si": _nlu(Intent.UNCLEAR),
            "ok": _nlu(Intent.UNCLEAR),
            "ubicacion": _nlu(Intent.ASK_INFO, confidence=0.82),
            "puedo liquidar antes?": _nlu(Intent.ASK_INFO, confidence=0.86),
            "checan buro?": _nlu(Intent.ASK_INFO, confidence=0.86),
            "cuanto es de enganche": _nlu(Intent.ASK_PRICE, confidence=0.88),
            "italika tc 250": _nlu(Intent.ASK_INFO, confidence=0.8, sales_signal="low"),
            "la roja": _nlu(Intent.UNCLEAR),
            "sí": _nlu(Intent.UNCLEAR),
            "ya te lo mandé": _nlu(Intent.UNCLEAR),
            "Cotizame esa opcion por favor": _nlu(Intent.ASK_PRICE),
        }
    )


def _primary_flow_nlu_with_overrides(
    overrides: dict[str, NLUResult] | None = None,
) -> _ScriptedNLU:
    nlu = _primary_flow_nlu()
    if overrides:
        nlu._scripts.update(overrides)
    return nlu


def _nlu(
    intent: Intent,
    *,
    confidence: float | None = None,
    ambiguities: list[str] | None = None,
    sales_signal: str = "none",
    entities: dict[str, object] | None = None,
) -> NLUResult:
    return NLUResult(
        intent=intent,
        sales_signal=sales_signal,
        entities={
            key: ExtractedField(value=value, confidence=1.0, source_turn=1)
            for key, value in (entities or {}).items()
        },
        sentiment=Sentiment.NEUTRAL,
        confidence=(
            confidence
            if confidence is not None
            else 0.92
            if intent != Intent.UNCLEAR
            else 0.45
        ),
        ambiguities=ambiguities or [],
    )


def _compose_message(input: ComposerInput) -> str:
    extracted = input.extracted_data or {}
    payload = input.action_payload or {}
    decision_payload = input.decision_payload or {}

    if input.action == "greet":
        return "Hola, con gusto te ayudo. ¿Qué modelo te interesa?"
    if decision_payload.get("decision") == "product_not_found":
        return "No lo encontré en el catálogo activo. Mándame el modelo exacto y lo reviso."
    if decision_payload.get("suggested_clarification"):
        return str(decision_payload["suggested_clarification"])
    if decision_payload.get("decision") == "clarification_required":
        clarification = decision_payload.get("suggested_clarification")
        return str(clarification or "Ayúdame con un poco más de detalle para seguir.")
    if input.action == "quote" and payload.get("status") == "ok":
        payment_options = payload.get("payment_options") or {}
        selected_plan = payment_options.get(str(payload.get("requested_plan_code"))) or {}
        list_price = int(payload.get("list_price_mxn") or 0)
        return (
            f"La {payload.get('name')} de contado queda en ${list_price:,}.\n\n"
            f"Con tu plan {payload.get('requested_plan_code')}:\n"
            f"Enganche: ${int(selected_plan.get('down_payment_mxn') or 0):,}\n"
            f"Pago quincenal: ${int(selected_plan.get('installment_mxn') or 0):,}\n"
            f"Plazo: {selected_plan.get('term_count')} quincenas"
        )
    if input.action == "lookup_faq" and payload.get("status") == "ok":
        message = str(payload.get("answer") or "")
        resume = payload.get("resume_pending_action") or {}
        requirements_summary = str(payload.get("requirements_summary") or "")
        if requirements_summary:
            message = f"{message}\n\n{requirements_summary}" if message else requirements_summary
        if resume.get("type") == "ask_missing_documents":
            missing = ", ".join(str(item) for item in (resume.get("missing") or []))
            message = f"{message}\n\nPara avanzar solo faltaria: {missing}."
        elif resume.get("type") == "ask_field":
            field = str(resume.get("field") or "")
            if field == "MOTO":
                message = f"{message}\n\nPara seguir solo falta el modelo."
            elif field == "CREDITO":
                message = f"{message}\n\nPara seguir solo falta como recibes ingresos."
        return message
    if payload.get("requirements") and extracted.get("CREDITO") and not extracted.get("ENGANCHE"):
        return "Perfecto, ese perfil maneja 20% de enganche. ¿Quieres que te lo cotice con 20%?"
    if not extracted.get("MOTO"):
        return "Hola, con gusto te ayudo. ¿Qué modelo te interesa?"
    if not extracted.get("CREDITO"):
        return (
            f"Perfecto, ya ubiqué la {extracted.get('MOTO')}. "
            "Para seguir, ¿cómo recibes tus ingresos?"
        )
    if not extracted.get("ENGANCHE") and not extracted.get("plan"):
        return "Perfecto. ¿Qué enganche quieres manejar: 10%, 15%, 20% o 30%?"
    if payload.get("requirements"):
        missing = payload["requirements"].get("missing") or []
        labels = [doc.get("label") for doc in missing if isinstance(doc, dict)]
        labels_text = ", ".join(str(label) for label in labels if label)
        return "Para seguir, revisa estos documentos: " + labels_text
    return "Voy avanzando con tu trámite."


def _decision_layer(trace) -> dict:
    return trace.state_after["runner_layers"]["decision"]


def _resolver_layer(trace) -> dict:
    return trace.state_after["runner_layers"]["resolver"]


def turn4_resolver_field(trace, key: str) -> str | None:
    resolver = _resolver_layer(trace)
    updates = resolver["selected_attempt"]["field_updates"]
    return updates.get(key)

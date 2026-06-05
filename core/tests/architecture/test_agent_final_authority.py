from __future__ import annotations

import inspect
from datetime import UTC, datetime

from atendia.contracts.message import Message, MessageDirection
from atendia.runner.agent_final_response import (
    AgentFinalResponseRequest,
    finalize_agent_visible_response,
    build_agent_final_response,
)
from atendia.runner.composer_protocol import ComposerOutput
from atendia.runner.conversation_runner import _stage_requires_received_document_guard
from atendia.runner.state_write_policy import StateWritePolicyRequest, apply_state_write_policy
from atendia.runner.tool_dispatch import facts_only_tool_payload


def _final_text(
    *,
    user_message: str,
    draft: str,
    final_action: str = "agent_response",
    tool_results: dict | None = None,
    history: list[tuple[str, str]] | None = None,
    advisor_brain_result: dict | None = None,
) -> str:
    result = build_agent_final_response(
        AgentFinalResponseRequest(
            user_message=user_message,
            history=history or [],
            tool_results=tool_results or {},
            final_action=final_action,
            advisor_brain_result=advisor_brain_result,
            composer_output=ComposerOutput(messages=[draft], suggested_handoff=None),
            brand_facts={
                "address": "Benito Juarez 801, Centro Monterrey",
                "buro_max_amount": "$50 mil",
            },
        )
    )
    return result.text


def test_agent_final_authority_only_path_persists_outbound() -> None:
    from atendia.runner import conversation_runner

    source = inspect.getsource(conversation_runner.ConversationRunner.run_turn)
    final_idx = source.index("finalize_agent_visible_response")
    trace_idx = source.index("TurnTrace(")
    enqueue_idx = source.index("await enqueue_messages")

    assert final_idx < trace_idx
    assert final_idx < enqueue_idx
    assert "messages=composer_output.messages" in source


def test_finalize_agent_visible_response_replaces_draft_and_returns_trace() -> None:
    result = finalize_agent_visible_response(
        AgentFinalResponseRequest(
            user_message="donde estan?",
            composer_output=ComposerOutput(
                messages=["No encontre ese modelo en el catalogo activo."],
                suggested_handoff=None,
            ),
            final_action="search_catalog",
            brand_facts={"address": "Benito Juarez 801, Centro Monterrey"},
        )
    )

    assert result.composer_output.messages == [result.final_response.text]
    assert result.trace["agent_final_authority_applied"] is True
    assert result.trace["agent_final_authority_rewrote"] is True
    assert "benito juarez" in result.final_response.text.casefold()
    assert "catalogo activo" not in result.final_response.text.casefold()


def test_location_multi_intent_answered_first() -> None:
    text = _final_text(
        user_message="hola, quiero una moto y tambien la ubicacion",
        draft="Hola, cuanto tiempo llevas en tu empleo actual?",
        final_action="ask_credit_context",
    ).casefold()

    assert "benito juarez" in text or "monterrey" in text
    assert text.index("monterrey") < text.index("ingresos")


def test_no_internal_state_language_visible() -> None:
    text = _final_text(
        user_message="la adventure",
        draft="Ya tenia registrado MOTO como Me depositan nomina en tarjeta. Quieres corregirlo a Adventure Elite 150 CC?",
    )

    blocked = (
        "MOTO",
        "CREDITO",
        "FILTRO",
        "ENGANCHE",
        "registrado como",
        "corregirlo a",
        "catalogo activo",
    )
    assert all(token not in text for token in blocked)


def test_agent_response_with_missing_documents_overrides_model_question() -> None:
    text = _final_text(
        user_message="me pagan en efectivo",
        draft="Y para seguir, dime que modelo quieres revisar.",
        final_action="agent_response",
        tool_results={
            "requirements": {
                "selection_label": "Sin Comprobantes",
                "missing": [
                    {"label": "INE ambos lados"},
                    {"label": "Comprobante de domicilio"},
                ],
            }
        },
    ).casefold()

    assert "sin comprobantes" in text
    assert "ine ambos lados" in text
    assert "comprobante de domicilio" in text
    assert "modelo" not in text


def test_state_write_moto_rejects_income_text() -> None:
    for inbound in (
        "me depositan en tarjeta",
        "que mando primero",
        "donde estan",
        "si",
        "va",
        "me pagan por fuera",
        "quiero credito",
    ):
        result = apply_state_write_policy(
            StateWritePolicyRequest(
                current_state={},
                proposed_updates={"MOTO": inbound},
                nlu_entities={"MOTO": inbound},
                turn_context={"inbound_text": inbound, "pipeline": None},
            )
        )
        assert "MOTO" not in result.approved_updates
        assert any(item["field"] == "MOTO" for item in result.blocked_updates)


def test_state_write_rejects_document_status_from_text_even_when_configured() -> None:
    pipeline = type(
        "Pipeline",
        (),
        {
            "documents_catalog": [type("Doc", (), {"key": "INE_FRENTE"})()],
            "vision_doc_mapping": {},
            "document_requirements": {"Sin Comprobantes": ["INE_FRENTE"]},
        },
    )()
    result = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={"CREDITO": "Sin Comprobantes"},
            proposed_updates={"INE_FRENTE": "ok"},
            nlu_entities={"INE_FRENTE": "ok"},
            turn_context={
                "pipeline": pipeline,
                "inbound_text": "ya te mande la INE",
            },
        )
    )

    assert result.approved_updates == {}
    assert result.blocked_updates == [
        {
            "field": "INE_FRENTE",
            "existing_value": None,
            "attempted_value": "ok",
            "reason": "documents_cannot_be_marked_received_from_text",
            "conflict_detected": False,
        }
    ]


def test_state_write_trace_includes_source_evidence_for_approved_updates() -> None:
    result = apply_state_write_policy(
        StateWritePolicyRequest(
            current_state={},
            proposed_updates={"ENGANCHE": "20%"},
            nlu_entities={"ENGANCHE": "20%"},
            turn_context={
                "inbound_text": "puedo dar 20%",
                "pipeline": None,
                "write_source": "nlu",
            },
        )
    )

    assert result.approved_updates == {"ENGANCHE": "20%"}
    approved = [item for item in result.state_write_trace if item.get("write_allowed")]
    assert approved == [
        {
            "field": "ENGANCHE",
            "new_value": "20%",
            "confidence": None,
            "source_turn": None,
            "source": "nlu",
            "evidence": "puedo dar 20%",
            "approved_by": "StateWritePolicy",
            "write_allowed": True,
        }
    ]


def test_tool_payload_contract_strips_customer_visible_drafts() -> None:
    payload = facts_only_tool_payload(
        {
            "status": "ok",
            "answer": "Si, se revisa buro.",
            "prompt_override": "Mandale este texto al cliente.",
            "natural_response": "Texto final listo para enviar.",
            "results": [{"name": "R4 250 CC"}],
        }
    )

    assert payload["answer"] == "Si, se revisa buro."
    assert payload["results"] == [{"name": "R4 250 CC"}]
    assert payload["_tool_contract"] == {"facts_only": True}
    assert "prompt_override" not in payload
    assert "natural_response" not in payload


def test_search_catalog_cannot_override_location_answer() -> None:
    text = _final_text(
        user_message="donde estan?",
        draft="No encontre ese modelo en el catalogo activo. Mandame el nombre exacto.",
        final_action="search_catalog",
        tool_results={
            "query": "Adventure Elite 150 CC",
            "status": "ok",
            "prompt_override": "Estamos ubicados en Monterrey, Nuevo Leon.",
        },
        advisor_brain_result={
            "natural_response": "Estamos ubicados en Monterrey, Nuevo Leon."
        },
    ).casefold()

    assert "monterrey" in text
    assert "no encontre" not in text
    assert "catalogo activo" not in text


def test_doc_incompleta_requires_received_attachment() -> None:
    inbound = Message(
        id="m1",
        conversation_id="c1",
        tenant_id="t1",
        direction=MessageDirection.INBOUND,
        text="que documentos mando?",
        sent_at=datetime.now(UTC),
        attachments=[],
    )

    assert (
        _stage_requires_received_document_guard(
            next_stage_id="doc_incompleta",
            previous_stage="potencialcliente",
            inbound=inbound,
        )
        == "potencialcliente"
    )


def test_no_document_request_loop() -> None:
    text = _final_text(
        user_message="y si traigo buro hay problema?",
        draft="Va, para avanzar primero mandame tu INE vigente por ambos lados.",
        final_action="classify_document",
        history=[
            ("outbound", "Va, para avanzar primero mandame tu INE vigente por ambos lados."),
        ],
    ).casefold()

    assert "buro" in text
    assert "ine" not in text


def test_buro_location_payoff_all_answered() -> None:
    text = _final_text(
        user_message="checan buro, donde estan y puedo liquidar antes?",
        draft="Va, mandame tu INE para avanzar.",
        final_action="classify_document",
    ).casefold()

    assert "buro" in text
    assert "monterrey" in text
    assert "liquid" in text
    assert text.index("buro") < text.find("ine") if "ine" in text else True


def test_menu_not_sent_as_default() -> None:
    draft = (
        "1. Me depositan nomina en tarjeta\n"
        "2. Me pagan con recibos de nomina\n"
        "3. Soy pensionado\n"
        "4. Tengo negocio registrado en SAT\n"
        "5. Me pagan sin comprobantes\n"
        "6. Soy guardia de seguridad"
    )
    text = _final_text(
        user_message="ya llevo 6 anos",
        draft=draft,
        final_action="ask_credit_context",
    )

    assert "1." not in text
    assert "2." not in text
    assert "como recibes tus ingresos" in text.casefold()


def test_realpath_ui_audit_zero_blockers_contract_shape() -> None:
    text = _final_text(
        user_message="donde estan?",
        draft="No encontre ese modelo en el catalogo activo.",
        final_action="search_catalog",
    )
    assert "catalogo activo" not in text.casefold()
    assert "monterrey" in text.casefold()

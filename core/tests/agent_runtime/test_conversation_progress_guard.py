from __future__ import annotations

from atendia.agent_runtime.conversation_progress import (
    ConversationProgressGuard,
    build_conversation_progress_context,
    normalize_composer_progress,
    output_from_progress_result,
)
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    ConversationMemoryContext,
    FieldUpdate,
    MessageContext,
    TurnContext,
    TurnOutput,
)


def _context(
    *,
    inbound: str,
    last_assistant: str | None = None,
    facts: dict | None = None,
    progress: dict | None = None,
) -> TurnContext:
    messages = []
    if last_assistant:
        messages.append(MessageContext(role="agent", text=last_assistant))
    messages.append(MessageContext(role="customer", text=inbound))
    return TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text=inbound,
        messages=messages,
        memory=ConversationMemoryContext(
            salient_facts=facts or {},
            metadata={"conversation_progress": progress or {}},
        ),
        active_agent=ActiveAgentContext(
            enabled_action_ids=["quote.resolve", "requirements.resolve"]
        ),
    )


def _output(message: str) -> TurnOutput:
    return TurnOutput(final_message=message, confidence=0.9)


def _output_with_product(message: str, product_id: str) -> TurnOutput:
    return TurnOutput(
        final_message=message,
        confidence=0.9,
        field_updates=[
            FieldUpdate(
                field_key="Producto",
                value={"product_id": product_id, "sku": product_id, "display_name": "R4"},
                evidence=["customer changed product"],
            )
        ],
    )


def _guarded_message(context: TurnContext, message: str) -> tuple[dict, str]:
    result = ConversationProgressGuard(mode="block").apply(context=context, output=_output(message))
    return result.to_dict(), output_from_progress_result(result).final_message


def _normalized_then_guarded(context: TurnContext, message: str) -> tuple[dict, str]:
    normalized = normalize_composer_progress(context, _output(message))
    result = ConversationProgressGuard(mode="block").apply(context=context, output=normalized)
    return result.to_dict(), output_from_progress_result(result).final_message


def test_blocks_repeated_income_question_when_income_is_known() -> None:
    context = _context(
        inbound="Me depositan en tarjeta",
        facts={"Ingreso": "Nomina Tarjeta"},
    )

    result, final_message = _guarded_message(context, "Como recibes tus ingresos?")

    assert result["allowed"] is False
    assert result["metrics"]["repeated_slot"] == "Ingreso"
    assert "same_slot_question_repeated" in result["failures"]
    assert "ingresos?" not in final_message


def test_income_fact_does_not_repeat_requirements_upstream() -> None:
    context = _context(
        inbound="Me depositan en tarjeta",
        last_assistant="De base ocupas INE y comprobante de domicilio.",
    )

    result, final_message = _normalized_then_guarded(
        context,
        "Para avanzar necesitas INE y comprobante de domicilio.",
    )

    assert result["allowed"] is True
    assert "requirements_repeated_without_user_asking" not in result["failures"]
    assert "ingresos" in final_message
    assert "INE" not in final_message


def test_blocks_repeated_seniority_question_when_seniority_is_known() -> None:
    context = _context(
        inbound="Tengo 1 año trabajando",
        facts={"Antiguedad_Laboral": "1 año"},
    )

    result, final_message = _guarded_message(context, "Cuanto tiempo llevas trabajando?")

    assert result["allowed"] is False
    assert result["metrics"]["repeated_slot"] == "Antiguedad_Laboral"
    assert "same_slot_question_repeated" in result["failures"]
    assert "trabajando?" not in final_message


def test_seniority_fact_does_not_repeat_requirements_upstream() -> None:
    context = _context(
        inbound="Tengo 1 año trabajando",
        last_assistant="De base ocupas INE y comprobante de domicilio.",
    )

    result, final_message = _normalized_then_guarded(
        context,
        "Para continuar necesitas INE y comprobante de domicilio.",
    )

    assert result["allowed"] is True
    assert "requirements_repeated_without_user_asking" not in result["failures"]
    assert "antiguedad" in final_message
    assert "INE" not in final_message


def test_blocks_full_quote_repeat_after_acknowledgement() -> None:
    quote = "De contado, la Adventure Elite 150 CC queda en $50,400."
    context = _context(inbound="ok", last_assistant=quote)

    result, final_message = _guarded_message(context, quote)

    assert result["allowed"] is False
    assert "quote_repeated_without_user_asking" in result["failures"]
    assert "$50,400" not in final_message


def test_allows_quote_repeat_when_customer_asks_how_much_it_was() -> None:
    quote = "De contado, la Adventure Elite 150 CC queda en $50,400."
    context = _context(inbound="cuanto era?", last_assistant=quote)

    result, final_message = _guarded_message(context, quote)

    assert result["allowed"] is True
    assert final_message == quote


def test_blocks_requirements_repeat_after_document_acknowledgement() -> None:
    docs = "De base ocupas INE y comprobante de domicilio."
    context = _context(inbound="va, los junto", last_assistant=docs)

    result, final_message = _guarded_message(context, docs)

    assert result["allowed"] is False
    assert "requirements_repeated_without_user_asking" in result["failures"]
    assert final_message != docs


def test_documents_request_can_repeat_documents_when_user_asks() -> None:
    docs = "De base ocupas INE y comprobante de domicilio."
    context = _context(inbound="Que documentos necesito?", last_assistant=docs)

    result, final_message = _guarded_message(context, docs)

    assert result["allowed"] is True
    assert final_message == docs


def test_documents_request_does_not_use_generic_progress_fallback() -> None:
    context = _context(inbound="Que documentos necesito?")

    result, final_message = _normalized_then_guarded(
        context,
        "Avanzo con lo nuevo que me dijiste y evito repetir lo anterior.",
    )

    assert result["allowed"] is True
    assert "INE" in final_message
    assert "avanzo con lo nuevo" not in final_message


def test_ack_after_quote_gets_next_step_without_repeating_quote() -> None:
    quote = "De contado, la Adventure Elite 150 CC queda en $50,400."
    context = _context(inbound="ok", last_assistant=quote)

    result, final_message = _normalized_then_guarded(context, quote)

    assert result["allowed"] is True
    assert "$50,400" not in final_message


def test_blocks_exact_response_repeat() -> None:
    message = "Perfecto, reviso ese modelo con datos validados."
    context = _context(inbound="ok", last_assistant=message)

    result, final_message = _guarded_message(context, message)

    assert result["allowed"] is False
    assert "exact_response_repeat" in result["failures"]
    assert final_message != message


def test_repeated_quote_safety_fallback_is_varied() -> None:
    fallback = (
        "Para darte el precio exacto necesito confirmar el modelo y el plan "
        "con la cotizacion del sistema."
    )
    context = _context(inbound="ok", last_assistant=fallback)

    result, final_message = _guarded_message(context, fallback)

    assert result["allowed"] is False
    assert "guard_fallback_repeated" in result["failures"]
    assert final_message != fallback


def test_product_change_is_not_treated_as_repetition() -> None:
    previous = "Perfecto, reviso ese modelo con datos validados."
    context = _context(inbound="Ahora mejor la R4", last_assistant=previous)

    result, final_message = _guarded_message(context, previous)

    assert result["allowed"] is True
    assert final_message == previous


def test_product_change_with_active_quote_gets_acknowledged() -> None:
    context = _context(
        inbound="Cotiza la R4",
        facts={"Producto": {"product_id": "prod-adventure"}},
    ).model_copy(
        update={
            "memory": ConversationMemoryContext(
                salient_facts={"Producto": {"product_id": "prod-adventure"}},
                last_quote_snapshot={
                    "snapshot_id": "quote-1",
                    "product": {"product_id": "prod-adventure"},
                },
            )
        }
    )
    output = _output_with_product(
        "Para R4 con Sin Comprobantes, el enganche es de $12,580.",
        "prod-r4",
    )

    result = ConversationProgressGuard(mode="block").apply(context=context, output=output)
    final_message = output_from_progress_result(result).final_message

    assert result.allowed is False
    assert "product_change_ack_missing" in result.failures
    assert "cotizacion anterior ya no aplica" in final_message


def test_build_progress_context_marks_known_slots_and_repeat_rules() -> None:
    quote = "De contado, la Adventure Elite 150 CC queda en $50,400."
    context = _context(
        inbound="ok",
        last_assistant=quote,
        facts={"Ingreso": "Nomina Tarjeta", "Producto": {"product_id": "prod-1"}},
    )

    progress = build_conversation_progress_context(context)

    assert progress.latest_customer_act == "acknowledgement"
    assert "Ingreso" in progress.must_not_ask_slots
    assert "Producto" in progress.must_not_ask_slots
    assert "quote" in progress.must_not_repeat_actions

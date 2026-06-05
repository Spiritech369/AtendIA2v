from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from atendia.runner.dinamo_agent_runtime import run_dinamo_agent_turn


class FakeToolDispatch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def search_catalog(self, **kwargs):
        self.calls.append(("search_catalog", kwargs))
        query = str(kwargs.get("query_text") or "").casefold()
        if "r4" in query:
            name = "R4 250 CC"
            sku = "R4-250"
        else:
            name = "Adventure Elite 150 CC"
            sku = "ADV-150"
        return SimpleNamespace(
            action_payload={"status": "ok", "results": [{"name": name, "sku": sku}]}
        )

    async def quote(self, **kwargs):
        self.calls.append(("quote", kwargs))
        model = (kwargs.get("candidate_queries") or ["Adventure Elite 150 CC"])[0]
        plan_code = kwargs.get("plan_code") or "20%"
        return SimpleNamespace(
            action_payload={
                "status": "ok",
                "name": model,
                "cash_price_mxn": 58000 if "R4" in str(model) else 48000,
                "requested_plan_code": plan_code,
                "payment_options": {
                    str(plan_code): {
                        "down_payment_mxn": 11600 if "R4" in str(model) else 9600,
                        "installment_mxn": 1450 if "R4" in str(model) else 1250,
                        "term_count": 48,
                    }
                },
            }
        )

    async def lookup_faq(self, **kwargs):
        self.calls.append(("lookup_faq", kwargs))
        text = str(kwargs.get("inbound_text") or "").casefold()
        if "buro" in text:
            payload = {
                "status": "ok",
                "topic": "buro",
                "answer": "Si, revisamos buro; puede aplicar de forma flexible hasta $50 mil.",
            }
        elif "liquid" in text or "pagar antes" in text:
            payload = {
                "status": "ok",
                "topic": "liquidacion",
                "answer": "Si, puedes liquidar antes; se recalcula lo pendiente a la fecha de pago.",
            }
        else:
            payload = {
                "status": "ok",
                "topic": "ubicacion",
                "answer": "Estamos en Benito Juarez 801, Centro Monterrey.",
            }
        return SimpleNamespace(action_payload=payload)


class ConversationProbe:
    def __init__(self) -> None:
        self.dispatch = FakeToolDispatch()
        self.state: dict = {}
        self.history: list[tuple[str, str]] = []
        self.turns = []

    async def send(self, text: str):
        result = await run_dinamo_agent_turn(
            tenant={"id": str(uuid4()), "name": "Dinamo Motos NL"},
            inbound_message=text,
            history=self.history,
            current_state=self.state,
            attachments=[],
            config={"features": {"dinamo_agent_first": True}},
            tool_dispatch=self.dispatch,
            brand_facts={
                "address": "Benito Juarez 801, Centro Monterrey",
                "buro_max_amount": "$50 mil",
            },
        )
        self.state = result.state_after
        self.history.extend([("inbound", text), ("outbound", result.final_text)])
        self.turns.append((text, result))
        return result


def _state_value(state: dict, key: str):
    value = state.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _all_bot_text(probe: ConversationProbe) -> str:
    return "\n".join(result.final_text for _text, result in probe.turns)


def _does_not_restart(text: str) -> None:
    lowered = text.casefold()
    assert "que modelo buscas" not in lowered
    assert "que modelo te interesa" not in lowered
    assert "como recibes tus ingresos" not in lowered


@pytest.mark.asyncio
async def test_model_given_price_question_does_not_ask_model_again():
    probe = ConversationProbe()

    result = await probe.send("cuanto cuesta la adventure")

    assert "que modelo buscas" not in result.final_text.casefold()
    assert "precio exacto" in result.final_text.casefold()
    assert result.final_text.casefold().count("como recibes tus ingresos") == 1
    assert _state_value(result.state_after, "MOTO") == "Adventure Elite 150 CC"


@pytest.mark.asyncio
async def test_multiturn_happy_path_quotes_then_documents():
    probe = ConversationProbe()

    for text in [
        "hola, quiero una moto a credito",
        "llevo 6 anos",
        "me depositan nomina en tarjeta",
        "la adventure",
        "cuanto queda",
        "checan buro?",
        "va, que mando primero?",
        "donde estan?",
    ]:
        await probe.send(text)

    bot_text = _all_bot_text(probe).casefold()
    assert _state_value(probe.state, "MOTO") == "Adventure Elite 150 CC"
    assert _state_value(probe.state, "CREDITO") == "Nomina Tarjeta"
    assert _state_value(probe.state, "ENGANCHE") == "10%"
    assert "pago quincenal" in bot_text
    assert "ine" in bot_text
    assert "buro" in bot_text
    assert "benito juarez" in bot_text


@pytest.mark.asyncio
async def test_model_change_esa_cuanto_uses_latest_model():
    probe = ConversationProbe()

    await probe.send("me pagan por fuera")
    await probe.send("la adventure")
    await probe.send("mejor la R4")
    result = await probe.send("esa cuanto queda?")

    assert _state_value(probe.state, "MOTO") == "R4 250 CC"
    assert "R4 250 CC" in result.final_text
    assert "$58000" in result.final_text.replace(",", "")


@pytest.mark.asyncio
async def test_faq_answer_then_resume_sales_naturally():
    probe = ConversationProbe()

    await probe.send("la adventure")
    result = await probe.send("checan buro?")

    assert "buro" in result.final_text.casefold()
    assert "dime como recibes tus ingresos" in result.final_text.casefold()


@pytest.mark.asyncio
async def test_bad_buro_followup_is_not_exact_repeat():
    probe = ConversationProbe()

    await probe.send("la adventure")
    first = await probe.send("checan buro?")
    second = await probe.send("tengo detalle en buro")

    assert first.final_text != second.final_text
    assert "menor a $50,000" in second.final_text.casefold()


@pytest.mark.asyncio
async def test_payment_support_escalates_not_sales_flow():
    probe = ConversationProbe()

    result = await probe.send("quiero hacer un pago, donde deposito?")

    assert result.handoff_requested is True
    assert "payment_support_requires_manual_handling" in result.safety_flags
    assert _state_value(result.state_after, "MOTO") is None
    assert _state_value(result.state_after, "agent_paused") is True
    assert "asesor" in result.final_text.casefold() or "dato bancario" in result.final_text.casefold()


@pytest.mark.asyncio
async def test_separar_sets_agent_paused_and_handoff():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    result = await probe.send("quiero separar la moto")

    assert result.handoff_requested is True
    assert _state_value(result.state_after, "agent_paused") is True
    assert "asesor" in result.final_text.casefold() or "francisco" in result.final_text.casefold()


@pytest.mark.asyncio
async def test_payment_and_new_purchase_prioritizes_payment_handoff():
    probe = ConversationProbe()

    result = await probe.send("quiero pagar y tambien ver otra moto")

    assert result.handoff_requested is True
    assert _state_value(result.state_after, "agent_paused") is True
    assert not result.tool_calls


@pytest.mark.asyncio
async def test_payoff_question_does_not_pause_as_payment_support():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me depositan nomina en tarjeta")
    result = await probe.send("si adelanto pagos hay penalizacion?")

    assert result.handoff_requested is False
    assert _state_value(result.state_after, "agent_paused") is not True
    assert "liquid" in result.final_text.casefold() or "penalizacion" in result.final_text.casefold()


@pytest.mark.asyncio
async def test_document_attachment_followup_does_not_go_to_catalog():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    await probe.send("cuanto queda?")
    await probe.send("no trae adjunto")
    result = await probe.send("entonces que hago?")

    assert not result.tool_calls
    assert "foto o archivo" in result.final_text.casefold()
    assert "catalogo" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_work_cargo_request_returns_options():
    probe = ConversationProbe()

    result = await probe.send("quiero una para trabajo tipo cargo")

    assert result.tool_calls
    assert "que modelo buscas" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_no_doc_incompleta_without_attachment_multiturn():
    probe = ConversationProbe()

    await probe.send("me pagan por fuera")
    await probe.send("la adventure")
    await probe.send("cuanto queda")
    result = await probe.send("ya te mande la INE")

    assert result.stage_update != "doc_incompleta"
    assert "doc_incompleta_blocked_without_attachment" in result.safety_flags


@pytest.mark.asyncio
async def test_human_handoff_stops_bot_flow():
    probe = ConversationProbe()

    result = await probe.send("quiero hablar con Francisco")

    assert result.handoff_requested is True
    assert "francisco" in result.final_text.casefold() or "asesor" in result.final_text.casefold()
    assert "cotiz" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_ambiguous_income_does_not_assign_plan_until_clarified():
    probe = ConversationProbe()

    first = await probe.send("me depositan")
    second = await probe.send("no se si cuenta como nomina")
    third = await probe.send("no me dan recibos")

    assert _state_value(first.state_after, "CREDITO") is None
    assert _state_value(second.state_after, "CREDITO") is None
    assert _state_value(third.state_after, "CREDITO") == "Sin Comprobantes"


@pytest.mark.asyncio
async def test_dual_income_asks_which_income_to_use():
    probe = ConversationProbe()

    result = await probe.send("tengo dos trabajos, uno me deposita y otro por fuera")

    assert _state_value(result.state_after, "CREDITO") is None
    assert "cual quieres comprobar" in result.final_text.casefold()


@pytest.mark.asyncio
async def test_quote_question_after_quote_reuses_last_quote():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    first_quote = await probe.send("cuanto queda?")
    second_quote = await probe.send("cuanto queda entonces?")

    assert "pago quincenal" in first_quote.final_text.casefold()
    assert "pago quincenal" in second_quote.final_text.casefold()
    assert "$48000" in second_quote.final_text.replace(",", "")
    _does_not_restart(second_quote.final_text)
    assert _state_value(probe.state, "last_quote")["name"] == "Adventure Elite 150 CC"


@pytest.mark.asyncio
async def test_closing_ack_after_quote_does_not_restart_flow():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    await probe.send("cuanto queda?")
    result = await probe.send("perfecto")

    _does_not_restart(result.final_text)
    assert "asesor" in result.final_text.casefold() or "seguimos" in result.final_text.casefold()


@pytest.mark.asyncio
async def test_document_upload_status_question_does_not_ask_model_or_income():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    await probe.send("cuanto queda?")
    await probe.send("ya te mande la INE")
    result = await probe.send("no me aparece?")

    assert "aparece cargado" in result.final_text.casefold()
    assert "foto o archivo" in result.final_text.casefold()
    _does_not_restart(result.final_text)


@pytest.mark.asyncio
async def test_ambiguous_income_followup_does_not_ask_model_when_model_known():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me depositan")
    result = await probe.send("no se si cuenta como nomina")

    assert _state_value(probe.state, "MOTO") == "Adventure Elite 150 CC"
    assert "recibos" in result.final_text.casefold() or "comprobantes" in result.final_text.casefold()
    assert "que modelo" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_model_known_never_asks_model_again():
    probe = ConversationProbe()

    await probe.send("la adventure")
    result = await probe.send("perfecto")

    assert _state_value(probe.state, "MOTO") == "Adventure Elite 150 CC"
    assert "que modelo" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_credit_known_never_asks_income_again_unless_user_changes_income():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    await probe.send("cuanto queda?")
    result = await probe.send("ok")

    assert _state_value(probe.state, "CREDITO") == "Sin Comprobantes"
    assert "como recibes tus ingresos" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_thanks_today_visit_closes_humanly():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    await probe.send("cuanto queda?")
    result = await probe.send("gracias, hoy paso")

    _does_not_restart(result.final_text)
    assert "benito juarez" in result.final_text.casefold()
    assert "asesor" in result.final_text.casefold()

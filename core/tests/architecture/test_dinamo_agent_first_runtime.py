from __future__ import annotations

import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

from atendia.runner.dinamo_agent_runtime import (
    dinamo_agent_first_enabled,
    dinamo_runtime_path,
    run_dinamo_agent_turn,
    select_dinamo_runtime,
)


class FakeToolDispatch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def search_catalog(self, **kwargs):
        self.calls.append(("search_catalog", kwargs))
        query = str(kwargs.get("query_text") or "").casefold()
        if "adventure" in query:
            return SimpleNamespace(
                action_payload={
                    "status": "ok",
                    "results": [
                        {
                            "name": "Adventure Elite 150 CC",
                            "sku": "ADV-150",
                        }
                    ],
                }
            )
        return SimpleNamespace(action_payload={"status": "no_data", "results": []})

    async def quote(self, **kwargs):
        self.calls.append(("quote", kwargs))
        model = (kwargs.get("candidate_queries") or ["Adventure Elite 150 CC"])[0]
        plan_code = kwargs.get("plan_code") or "20%"
        return SimpleNamespace(
            action_payload={
                "status": "ok",
                "name": model,
                "cash_price_mxn": 48000,
                "requested_plan_code": plan_code,
                "payment_options": {
                    str(plan_code): {
                        "down_payment_mxn": 9600,
                        "installment_mxn": 1250,
                        "term_count": 48,
                    }
                },
            }
        )

    async def lookup_faq(self, **kwargs):
        self.calls.append(("lookup_faq", kwargs))
        text = str(kwargs.get("inbound_text") or "").casefold()
        if "buro" in text:
            return SimpleNamespace(
                action_payload={
                    "status": "ok",
                    "topic": "buro",
                    "answer": "Si, revisamos buro; puede aplicar de forma flexible hasta $50 mil.",
                }
            )
        if "liquid" in text or "pagar antes" in text:
            return SimpleNamespace(
                action_payload={
                    "status": "ok",
                    "topic": "liquidacion",
                    "answer": "Si, puedes liquidar antes; se recalcula lo pendiente a la fecha de pago.",
                }
            )
        return SimpleNamespace(
            action_payload={
                "status": "ok",
                "topic": "ubicacion",
                "answer": "Estamos en Benito Juarez 801, Centro Monterrey.",
            }
        )


def _tenant(name: str = "Dinamo Motos NL") -> dict:
    return {"id": str(uuid4()), "name": name}


async def _run(
    text: str,
    *,
    state: dict | None = None,
    history: list[tuple[str, str]] | None = None,
    attachments: list | None = None,
    tool_dispatch: FakeToolDispatch | None = None,
):
    return await run_dinamo_agent_turn(
        tenant=_tenant(),
        inbound_message=text,
        history=history or [],
        current_state=state or {},
        attachments=attachments or [],
        config={"features": {"dinamo_agent_first": True}},
        tool_dispatch=tool_dispatch or FakeToolDispatch(),
        brand_facts={
            "address": "Benito Juarez 801, Centro Monterrey",
            "buro_max_amount": "$50 mil",
        },
    )


def _state_value(state: dict, key: str):
    value = state.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _assert_customer_text_is_clean(text: str) -> None:
    assert not re.search(r"\b(MOTO|CREDITO|FILTRO|ENGANCHE)\b", text)
    assert "registrado como" not in text.casefold()
    assert "catalogo activo" not in text.casefold()
    assert "catálogo activo" not in text.casefold()


def _tool_names(dispatch: FakeToolDispatch) -> list[str]:
    return [name for name, _payload in dispatch.calls]


def test_feature_flag_selects_new_path_only_for_dinamo_when_enabled():
    config = {"features": {"dinamo_agent_first": True}}

    assert dinamo_agent_first_enabled(_tenant(), config=config)
    assert dinamo_runtime_path(_tenant(), config=config) == "dinamo_agent_first"
    assert dinamo_runtime_path(_tenant("Other Dealer"), config=config) == "conversation_runner"
    assert dinamo_runtime_path(_tenant(), config={"features": {"dinamo_agent_first": False}}) == "conversation_runner"


def test_real_outbox_stays_blocked_without_live_limited_allowlist():
    selection = select_dinamo_runtime(
        _tenant(),
        {"features": {"dinamo_agent_first": True}},
        channel="whatsapp_meta",
        customer_phone_e164="+5218128889241",
    )

    assert selection.runtime_path == "dinamo_agent_first"
    assert selection.sandbox_allowed is False
    assert selection.live_limited_allowed is False
    assert selection.real_outbox_blocked is True


def test_live_limited_allowlist_unblocks_real_outbox_for_one_phone_only():
    config = {
        "features": {"dinamo_agent_first": True},
        "dinamo_agent_first_live_limited": {
            "enabled": True,
            "allow_real_outbox": True,
            "human_monitoring_active": True,
            "rollback_ready": True,
            "restrict_to_allowlist": True,
            "allowed_tenant_ids": [_tenant()["id"]],
            "allowed_phone_numbers": ["+5218128889241"],
        },
    }
    tenant = _tenant()
    config["dinamo_agent_first_live_limited"]["allowed_tenant_ids"] = [tenant["id"]]

    allowed = select_dinamo_runtime(
        tenant,
        config,
        channel="whatsapp_meta",
        customer_phone_e164="+52 1 812 888 9241",
    )
    blocked = select_dinamo_runtime(
        tenant,
        config,
        channel="whatsapp_meta",
        customer_phone_e164="+5218100000000",
    )

    assert allowed.live_limited_allowed is True
    assert allowed.real_outbox_blocked is False
    assert allowed.reason_selected == "dinamo_flag_on_live_limited_allowlist"
    assert blocked.runtime_path == "conversation_runner"
    assert blocked.reason_selected == "dinamo_live_limited_not_allowlisted"


@pytest.mark.asyncio
async def test_location_question_is_answered_before_model_flow_and_does_not_search_catalog():
    dispatch = FakeToolDispatch()

    result = await _run("Hola, quiero una moto y tambien la ubicacion", tool_dispatch=dispatch)

    _assert_customer_text_is_clean(result.final_text)
    assert "Benito Juarez" in result.final_text
    assert "search_catalog" not in _tool_names(dispatch)
    assert result.trace_payload["runtime_path"] == "dinamo_agent_first"
    assert result.trace_payload["final_text_source"] == "agent_final_response"


@pytest.mark.asyncio
async def test_seniority_writes_filter_and_asks_income_without_robotic_menu():
    result = await _run("Ya llevo 6 anos trabajando ahi")

    _assert_customer_text_is_clean(result.final_text)
    assert _state_value(result.state_after, "FILTRO") is True
    assert _state_value(result.state_after, "ANTIGUEDAD_LABORAL")["normalized_months"] == 72
    assert "ingresos" in result.final_text.casefold()
    assert "1." not in result.final_text


@pytest.mark.asyncio
async def test_ambiguous_income_does_not_write_credit_plan_or_pollute_model():
    result = await _run("Me depositan en tarjeta")

    _assert_customer_text_is_clean(result.final_text)
    assert _state_value(result.state_after, "CREDITO") is None
    assert _state_value(result.state_after, "ENGANCHE") is None
    assert _state_value(result.state_after, "MOTO") is None
    assert "nomina" in result.final_text.casefold()
    assert "credito_ambiguous" in result.safety_flags


@pytest.mark.asyncio
async def test_model_resolution_accepts_only_catalog_model_for_moto():
    dispatch = FakeToolDispatch()

    result = await _run("La adventure", tool_dispatch=dispatch)

    _assert_customer_text_is_clean(result.final_text)
    assert "search_catalog" in _tool_names(dispatch)
    assert _state_value(result.state_after, "MOTO") == "Adventure Elite 150 CC"
    assert all(write.source == "catalog_tool" for write in result.accepted_state_writes if write.field == "MOTO")


@pytest.mark.asyncio
async def test_quote_uses_deterministic_tool_and_answers_price_without_asking_docs_first():
    dispatch = FakeToolDispatch()
    state = {
        "MOTO": {"value": "Adventure Elite 150 CC"},
        "CREDITO": {"value": "Sin Comprobantes"},
        "ENGANCHE": {"value": "20%"},
    }

    result = await _run("Cuanto sale?", state=state, tool_dispatch=dispatch)

    _assert_customer_text_is_clean(result.final_text)
    assert "quote" in _tool_names(dispatch)
    assert "$48000" in result.final_text.replace(",", "")
    assert "Pago quincenal" in result.final_text
    assert "document" not in result.final_text.casefold()
    assert "ine" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_buro_question_answers_current_question_instead_of_documents():
    result = await _run(
        "Y si traigo buro hay problema?",
        state={"last_quote": {"value": True}},
    )

    _assert_customer_text_is_clean(result.final_text)
    assert "buro" in result.final_text.casefold()
    assert "ine" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_payoff_question_answers_liquidation_instead_of_restart_flow():
    result = await _run("Puedo liquidar antes o pagar antes?")

    _assert_customer_text_is_clean(result.final_text)
    assert "liquid" in result.final_text.casefold() or "pagar antes" in result.final_text.casefold()
    assert "ine" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_documents_after_quote_do_not_loop_or_mark_doc_incomplete_without_attachment():
    state = {"last_quote": {"value": True}, "CREDITO": {"value": "Sin Comprobantes"}}

    result = await _run("Que documentos mando primero?", state=state)

    _assert_customer_text_is_clean(result.final_text)
    assert "ine" in result.final_text.casefold()
    assert result.stage_update != "doc_incompleta"
    assert "doc_incompleta_blocked_without_attachment" in result.safety_flags

    follow_up = await _run(
        "Y si traigo buro?",
        state=state,
        history=[("assistant", result.final_text)],
    )
    _assert_customer_text_is_clean(follow_up.final_text)
    assert "buro" in follow_up.final_text.casefold()
    assert "ine" not in follow_up.final_text.casefold()


@pytest.mark.asyncio
async def test_location_after_quote_does_not_search_catalog():
    dispatch = FakeToolDispatch()
    state = {
        "last_quote": {"value": True},
        "MOTO": {"value": "Adventure Elite 150 CC"},
        "CREDITO": {"value": "Sin Comprobantes"},
        "ENGANCHE": {"value": "20%"},
    }

    result = await _run("Donde estan?", state=state, tool_dispatch=dispatch)

    _assert_customer_text_is_clean(result.final_text)
    assert "Benito Juarez" in result.final_text
    assert "search_catalog" not in _tool_names(dispatch)


@pytest.mark.asyncio
async def test_human_handoff_sets_flag_without_selling_more():
    result = await _run("Quiero hablar con Francisco")

    _assert_customer_text_is_clean(result.final_text)
    assert result.handoff_requested is True
    assert result.should_enqueue is True
    assert "asesor" in result.final_text.casefold() or "francisco" in result.final_text.casefold()
    assert "cotizacion" not in result.final_text.casefold()


@pytest.mark.asyncio
async def test_replay_bad_traces_current_question_menu_pollution_leak_and_false_doc_incomplete():
    location = await _run("Me interesa una moto, donde estan?")
    _assert_customer_text_is_clean(location.final_text)
    assert "Benito Juarez" in location.final_text

    seniority = await _run("Tengo 8 meses trabajando")
    _assert_customer_text_is_clean(seniority.final_text)
    assert "1." not in seniority.final_text

    pollution = await _run("Me depositan en tarjeta")
    assert _state_value(pollution.state_after, "MOTO") is None
    assert _state_value(pollution.state_after, "CREDITO") is None

    dispatch = FakeToolDispatch()
    leak = await _run(
        "La adventure",
        state={"MOTO": {"value": "Me depositan nomina en tarjeta"}},
        tool_dispatch=dispatch,
    )
    _assert_customer_text_is_clean(leak.final_text)
    assert _state_value(leak.state_after, "MOTO") == "Adventure Elite 150 CC"

    no_doc = await _run("Ya te mande la ine", attachments=[])
    _assert_customer_text_is_clean(no_doc.final_text)
    assert no_doc.stage_update != "doc_incompleta"
    assert "doc_incompleta_blocked_without_attachment" in no_doc.safety_flags
    assert no_doc.trace_payload["blocked_reasons"] or no_doc.safety_flags

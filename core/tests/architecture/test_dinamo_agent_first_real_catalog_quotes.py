from __future__ import annotations

import sys
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atendia.runner.dinamo_agent_runtime import run_dinamo_agent_turn

_SCRIPT_PATH = ROOT / "scripts" / "run_dinamo_agent_first_multiturn_canary.py"
if not _SCRIPT_PATH.exists():
    pytest.skip(
        "legacy Dinamo multiturn canary script is missing; quarantined until "
        "the harness is restored or migrated to Eval Lab.",
        allow_module_level=True,
    )
_SPEC = importlib.util.spec_from_file_location("dinamo_multiturn_canary", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
RealDinamoCatalogData = _MODULE.RealDinamoCatalogData
RealDinamoCatalogToolDispatch = _MODULE.RealDinamoCatalogToolDispatch


class ConversationProbe:
    def __init__(self) -> None:
        self.catalog = RealDinamoCatalogData()
        self.dispatch = RealDinamoCatalogToolDispatch(self.catalog)
        self.state: dict = {}
        self.history: list[tuple[str, str]] = []

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
        return result


def _payment_option(payload: dict, plan: str) -> dict:
    return payload["payment_options"][plan]


@pytest.mark.asyncio
async def test_adventure_plan_10_uses_real_catalog():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me depositan nomina en tarjeta")
    result = await probe.send("cuanto queda?")

    text = result.final_text
    quote = result.state_after["last_quote"]["value"]
    option = _payment_option(quote, "10%")
    assert quote["cash_price_mxn"] == 29900
    assert option["down_payment_mxn"] == 3140
    assert option["installment_mxn"] == 1247
    assert option["term_count"] == 72
    assert "$29900" in text.replace(",", "")
    assert "$3,140" in text
    assert "$1,247" in text
    assert "72 quincenas" in text


@pytest.mark.asyncio
async def test_adventure_plan_20_uses_real_catalog():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    result = await probe.send("cuanto queda?")

    quote = result.state_after["last_quote"]["value"]
    option = _payment_option(quote, "20%")
    assert quote["cash_price_mxn"] == 29900
    assert option["down_payment_mxn"] == 6279
    assert option["installment_mxn"] == 1017
    assert option["term_count"] == 72
    assert "$6,279" in result.final_text
    assert "$1,017" in result.final_text
    assert "72 quincenas" in result.final_text


@pytest.mark.asyncio
async def test_never_quote_fake_adventure_values():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me depositan nomina en tarjeta")
    result = await probe.send("cuanto queda?")

    quote = result.state_after["last_quote"]["value"]
    option = _payment_option(quote, "10%")
    serialized_quote = json.dumps(quote, sort_keys=True)
    normalized = result.final_text.replace(",", "")
    assert "48000" not in normalized
    assert "4800" not in normalized
    assert "1125" not in normalized
    assert "Plazo: 48" not in result.final_text
    assert "48000" not in serialized_quote
    assert option["down_payment_mxn"] != 4800
    assert option["installment_mxn"] != 1125
    assert option["term_count"] != 48


def test_quote_matches_catalog_exactly_for_all_plans():
    catalog = RealDinamoCatalogData()
    for model_name in ["Adventure Elite 150 CC", "R4 250 CC", "Alien R 175 CC"]:
        model = catalog.find_model(model_name)
        assert model is not None
        for plan_code, expected in model["planes_credito_normalizados"].items():
            payload = catalog.quote_payload(model_query=model_name, plan_code=plan_code)
            option = payload["payment_options"][plan_code]
            assert payload["cash_price_mxn"] == model["precio_contado_mxn"]
            assert option["down_payment_mxn"] == expected["enganche_mxn"]
            assert option["installment_mxn"] == expected["pago_quincenal_mxn"]
            assert option["term_count"] == expected["numero_quincenas"]
            assert option["plazo_texto"] == expected["plazo_texto"]


def test_income_to_plan_uses_requisitos_json():
    catalog = RealDinamoCatalogData()

    assert catalog.resolve_plan_for_credit("Nomina Tarjeta") == "10%"
    assert catalog.resolve_plan_for_credit("Sin Comprobantes") == "20%"
    assert catalog.resolve_plan_for_credit("Guardia de Seguridad") == "30%"

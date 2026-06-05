from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atendia.dinamo_atendia_kb import DinamoAtendiaKnowledgeBase, PublishedKnowledgeMetadata
from atendia.runner.dinamo_agent_runtime import run_dinamo_agent_turn

_SCRIPT_PATH = ROOT / "scripts" / "run_dinamo_agent_first_multiturn_canary.py"
if not _SCRIPT_PATH.exists():
    pytest.skip(
        "legacy Dinamo multiturn canary script is missing; quarantined until "
        "the harness is restored or migrated to Eval Lab.",
        allow_module_level=True,
    )
_SPEC = importlib.util.spec_from_file_location("dinamo_multiturn_canary_atendia", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
AtendiaKnowledgeBaseToolDispatch = _MODULE.AtendiaKnowledgeBaseToolDispatch


def _kb() -> DinamoAtendiaKnowledgeBase:
    return DinamoAtendiaKnowledgeBase(
        metadata=PublishedKnowledgeMetadata(
            tenant_id="6ad78236-1fc9-467a-858d-90d248d57ee5",
            tenant_name="Dinamo Motos NL",
            knowledge_version="kb-test-version",
            catalog_version="catalog-v1",
            requirements_version="requirements-v1",
            faq_version="faq-v1",
        ),
        catalog_items=[
            {
                "sku": "adventure_elite_150_cc",
                "name": "Adventure Elite 150 CC",
                "category": "Motoneta",
                "status": "active",
                "base_price": "29900",
                "list_price": "31395",
                "attributes_json": {"aliases": ["adventure", "motoneta adventure"]},
                "plans": [
                    {
                        "status": "active",
                        "plan_code": "10%",
                        "down_payment_amount": "3140",
                        "installment_amount": "1247",
                        "installment_frequency": "quincenal",
                        "installment_count": 72,
                        "eligibility_rules_json": {"plazo_texto": "72 quincenas"},
                    },
                    {
                        "status": "active",
                        "plan_code": "20%",
                        "down_payment_amount": "6279",
                        "installment_amount": "1017",
                        "installment_frequency": "quincenal",
                        "installment_count": 72,
                        "eligibility_rules_json": {"plazo_texto": "72 quincenas"},
                    },
                ],
            },
            {
                "sku": "u2_150_cc",
                "name": "U2 150 CC",
                "category": "Trabajo",
                "status": "active",
                "base_price": "21900",
                "list_price": "22995",
                "attributes_json": {"aliases": ["urban", "urbana", "u2", "moto urbana"]},
                "plans": [
                    {
                        "status": "active",
                        "plan_code": "10%",
                        "down_payment_amount": "2295",
                        "installment_amount": "915",
                        "installment_frequency": "quincenal",
                        "installment_count": 72,
                        "eligibility_rules_json": {"plazo_texto": "72 quincenas"},
                    },
                    {
                        "status": "active",
                        "plan_code": "20%",
                        "down_payment_amount": "4590",
                        "installment_amount": "805",
                        "installment_frequency": "quincenal",
                        "installment_count": 72,
                        "eligibility_rules_json": {"plazo_texto": "72 quincenas"},
                    },
                ],
            },
            {
                "sku": "u5_150_cc",
                "name": "U5 150 CC",
                "category": "Trabajo",
                "status": "active",
                "base_price": "24900",
                "list_price": "26145",
                "attributes_json": {"aliases": ["trabajo", "moto para trabajo", "reparto"]},
                "plans": [
                    {
                        "status": "active",
                        "plan_code": "20%",
                        "down_payment_amount": "5229",
                        "installment_amount": "880",
                        "installment_frequency": "quincenal",
                        "installment_count": 72,
                        "eligibility_rules_json": {"plazo_texto": "72 quincenas"},
                    },
                ],
            },
            {
                "sku": "heavy_b_150_cc",
                "name": "Heavy-B 150 CC",
                "category": "Trabajo",
                "status": "active",
                "base_price": "32900",
                "list_price": "34545",
                "attributes_json": {"aliases": ["heavy", "heavy b", "cargo", "carga"]},
                "plans": [
                    {
                        "status": "active",
                        "plan_code": "20%",
                        "down_payment_amount": "6909",
                        "installment_amount": "1110",
                        "installment_frequency": "quincenal",
                        "installment_count": 72,
                        "eligibility_rules_json": {"plazo_texto": "72 quincenas"},
                    },
                ],
            },
            {
                "sku": "heavy_cab_200_cc",
                "name": "Heavy Cab 200 CC",
                "category": "Trabajo",
                "status": "active",
                "base_price": "48900",
                "list_price": "51345",
                "attributes_json": {"aliases": ["heavy cab", "cargo", "motocarro", "carga"]},
                "plans": [
                    {
                        "status": "active",
                        "plan_code": "20%",
                        "down_payment_amount": "10269",
                        "installment_amount": "1630",
                        "installment_frequency": "quincenal",
                        "installment_count": 72,
                        "eligibility_rules_json": {"plazo_texto": "72 quincenas"},
                    },
                ],
            },
        ],
        requirements=[
            {
                "tipo_credito": "Nomina Tarjeta",
                "plan_credito": "10%",
                "aliases": "nomina en tarjeta, me depositan nomina, tarjeta",
            },
            {
                "tipo_credito": "Sin Comprobantes",
                "plan_credito": "20%",
                "aliases": "sin comprobantes, por fuera, no tengo recibos",
            },
            {
                "tipo_credito": "Guardia de Seguridad",
                "plan_credito": "30%",
                "aliases": "guardia de seguridad, seguridad privada, vigilante",
            },
        ],
        faqs=[
            {
                "question": "¿Dónde están ubicados?",
                "answer": "Estamos en BENITO JUAREZ 801, Centro, Monterrey.",
                "status": "published",
            }
        ],
    )


class ConversationProbe:
    def __init__(self) -> None:
        self.dispatch = AtendiaKnowledgeBaseToolDispatch(_kb())
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
            brand_facts={"address": "No usar fallback local"},
        )
        self.state = result.state_after
        self.history.extend([("inbound", text), ("outbound", result.final_text)])
        return result


@pytest.mark.asyncio
async def test_dinamo_agent_uses_atendia_catalog_not_downloads():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me depositan nomina en tarjeta")
    result = await probe.send("cuanto queda?")

    quote = result.state_after["last_quote"]["value"]
    assert quote["quote_source"] == "atendia_knowledge_base"
    assert quote["catalog_source"] == "atendia_catalog_published"
    assert "Downloads" not in str(quote)
    assert "C:\\Users" not in str(quote)


@pytest.mark.asyncio
async def test_adventure_quote_from_atendia_knowledge_base():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me depositan nomina en tarjeta")
    result = await probe.send("cuanto queda?")

    quote = result.state_after["last_quote"]["value"]
    option = quote["payment_options"]["10%"]
    assert quote["cash_price_mxn"] == 29900
    assert option["down_payment_mxn"] == 3140
    assert option["installment_mxn"] == 1247
    assert option["term_count"] == 72
    assert "72 quincenas" in result.final_text


def test_requirements_mapping_from_atendia_knowledge_base():
    kb = _kb()

    assert kb.resolve_plan_for_credit("Nomina Tarjeta") == "10%"
    assert kb.resolve_plan_for_credit("Sin Comprobantes") == "20%"
    assert kb.resolve_plan_for_credit("Guardia de Seguridad") == "30%"


@pytest.mark.asyncio
async def test_faq_location_from_atendia_knowledge_base():
    probe = ConversationProbe()

    result = await probe.send("donde estan?")

    assert "BENITO JUAREZ 801" in result.final_text
    assert result.trace_payload["faq_source"] == "atendia_faq_published"


@pytest.mark.asyncio
async def test_quote_source_metadata_present():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me depositan nomina en tarjeta")
    result = await probe.send("cuanto queda?")

    assert result.trace_payload["quote_source"] == "atendia_knowledge_base"
    assert result.trace_payload["catalog_version"] == "catalog-v1"
    assert result.trace_payload["requirements_version"] == "requirements-v1"
    assert result.trace_payload["tenant_id"] == "6ad78236-1fc9-467a-858d-90d248d57ee5"


@pytest.mark.asyncio
async def test_urban_alias_does_not_leave_moto_null_without_options():
    probe = ConversationProbe()

    result = await probe.send("la urban")

    moto = result.state_after.get("MOTO", {}).get("value")
    options = result.trace_payload.get("state_after", {}).get("recent_catalog_candidates", {}).get("value")
    assert moto == "U2 150 CC" or options
    assert "ese modelo" not in result.final_text.lower()
    assert "esa moto" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_cargo_ambiguous_returns_options_not_fake_context():
    probe = ConversationProbe()

    result = await probe.send("la cargo")

    assert result.state_after.get("MOTO", {}).get("value") is None
    assert "Heavy-B 150 CC" in result.final_text
    assert "Heavy Cab 200 CC" in result.final_text
    assert "te la puedo cotizar" not in result.final_text.lower()
    assert "esa moto" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_price_question_with_plan_but_no_model_asks_model_not_income():
    probe = ConversationProbe()

    await probe.send("me pagan por fuera")
    result = await probe.send("cuanto queda?")

    text = result.final_text.lower()
    assert "modelo" in text
    assert "ingresos" not in text
    assert "como recibes" not in text


@pytest.mark.asyncio
async def test_no_followup_says_esa_moto_when_moto_null():
    probe = ConversationProbe()

    result = await probe.send("moto para trabajo")

    text = result.final_text.lower()
    assert result.state_after.get("MOTO", {}).get("value") is None
    for forbidden in ("esa moto", "ese modelo", "seguimos con esa moto", "te la cotizo"):
        assert forbidden not in text


@pytest.mark.asyncio
async def test_recent_catalog_candidates_resolve_esa_cuanto():
    probe = ConversationProbe()

    await probe.send("moto para trabajo")
    await probe.send("la u2")
    await probe.send("me depositan nomina en tarjeta")
    result = await probe.send("esa cuanto queda?")

    assert result.state_after["MOTO"]["value"] == "U2 150 CC"
    assert result.state_after["last_quote"]["value"]["name"] == "U2 150 CC"
    assert "U2 150 CC" in result.final_text
    assert "ingresos" not in result.final_text.lower()


@pytest.mark.asyncio
async def test_moto_para_trabajo_offers_work_models_not_adventure():
    probe = ConversationProbe()

    result = await probe.send("moto para trabajo")

    assert result.state_after.get("MOTO", {}).get("value") is None
    assert "U5 150 CC" in result.final_text or "Heavy-B 150 CC" in result.final_text
    assert "Adventure Elite 150 CC" not in result.final_text


@pytest.mark.asyncio
async def test_urban_after_work_candidates_keeps_work_options():
    probe = ConversationProbe()

    await probe.send("moto para trabajo")
    result = await probe.send("la urban")

    text = result.final_text
    assert result.state_after.get("MOTO", {}).get("value") is None
    assert "U2 150 CC" in text or "U5 150 CC" in text
    assert "Adventure Elite 150 CC" not in text


@pytest.mark.asyncio
async def test_location_then_urban_uses_workish_urban_options():
    probe = ConversationProbe()

    await probe.send("donde estan?")
    result = await probe.send("me interesa la urban")

    text = result.final_text
    assert result.state_after.get("MOTO", {}).get("value") == "U2 150 CC"
    assert "como recibes tus ingresos" in text.lower()
    assert "Adventure Elite 150 CC" not in text


@pytest.mark.asyncio
async def test_location_then_urban_quotes_after_income():
    probe = ConversationProbe()

    await probe.send("donde estan?")
    await probe.send("me interesa la urban")
    await probe.send("me depositan nomina en tarjeta")
    result = await probe.send("cuanto queda?")

    assert result.state_after["MOTO"]["value"] == "U2 150 CC"
    assert result.state_after["last_quote"]["value"]["name"] == "U2 150 CC"
    assert "U2 150 CC" in result.final_text


@pytest.mark.asyncio
async def test_mejor_la_adventure_updates_model_context_with_stale_candidates():
    probe = ConversationProbe()

    await probe.send("me pagan por fuera")
    await probe.send("la urban")
    await probe.send("mejor la adventure")
    result = await probe.send("esa cuanto queda?")

    assert result.state_after["MOTO"]["value"] == "Adventure Elite 150 CC"
    assert result.state_after["last_quote"]["value"]["name"] == "Adventure Elite 150 CC"
    assert "Adventure Elite 150 CC" in result.final_text


@pytest.mark.asyncio
async def test_ine_frente_asks_only_back():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    await probe.send("cuanto queda?")
    result = await probe.send("te mando INE frente")

    text = result.final_text.lower()
    assert "parte de atras" in text
    assert "comprobante" not in text


@pytest.mark.asyncio
async def test_price_objection_more_down_payment_answered_first():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    await probe.send("cuanto queda?")
    await probe.send("esta caro")
    result = await probe.send("se puede con mas enganche?")

    text = result.final_text.lower()
    assert "mas enganche" in text
    assert "10%" in text and "30%" in text
    assert "que modelo" not in text


@pytest.mark.asyncio
async def test_quote_format_separates_cash_and_credit():
    probe = ConversationProbe()

    await probe.send("la adventure")
    await probe.send("me pagan por fuera")
    result = await probe.send("cuanto queda?")

    text = result.final_text
    assert "de contado esta" in text
    assert "A credito" in text
    assert "\nEnganche:" in text
    assert "de contado queda en" not in text


@pytest.mark.asyncio
async def test_generic_credit_start_asks_model_without_fake_catalog_context():
    probe = ConversationProbe()

    result = await probe.send("hola, quiero una moto a credito")

    text = result.final_text.lower()
    assert "modelo" in text
    assert "ingresos" not in text
    assert not result.tool_calls
    assert "reviso en catalogo" not in text


@pytest.mark.asyncio
async def test_mixed_questions_answers_faq_and_shows_cargo_options():
    probe = ConversationProbe()

    result = await probe.send("la cargo, donde estan y checan buro?")

    assert "BENITO JUAREZ 801" in result.final_text
    assert "buro" in result.final_text.lower()
    assert "Heavy-B 150 CC" in result.final_text
    assert "Heavy Cab 200 CC" in result.final_text
    assert result.state_after.get("MOTO", {}).get("value") is None

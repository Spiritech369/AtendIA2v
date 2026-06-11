from __future__ import annotations

from atendia.agent_runtime import AgentContextPackage
from atendia.agent_runtime.respond_style_real_facts_executor import (
    RealFactsToolExecutor,
)
from atendia.agent_runtime.respond_style_turn_contract import LLMToolCallProposal

BINDINGS = [
    {"name": "catalog.search", "real_source": "catalog_search"},
    {
        "name": "quote.resolve",
        "real_source": "catalog_quote",
        "preconditions": ["selected_model"],
    },
    {
        "name": "requirements.lookup",
        "real_source": "knowledge_plans",
        "preconditions": ["income_type"],
    },
    {"name": "legacy.tool"},  # no real_source configured
]

FACTS = {
    "models": [
        {
            "model_id": "alpha-150",
            "label": "Alpha 150",
            "category": "urbana",
            "aliases": ["alpha", "alpha 150", "la alpha"],
            "price_lista_mxn": 31395,
            "price_contado_mxn": 29900,
            "tags": ["ciudad"],
            "ficha_tecnica": {"motor_cc": 150},
            "planes_credito": {
                "10%": {"enganche_mxn": 3140, "pago_quincenal_mxn": 1247},
                "30%": {"enganche_mxn": 9419, "pago_quincenal_mxn": 774},
            },
            "search_text": "alpha 150 urbana ciudad economica",
        },
        {
            "model_id": "beta-250",
            "label": "Beta 250",
            "category": "trabajo",
            "aliases": ["beta"],
            "price_lista_mxn": 45000,
            "price_contado_mxn": 42000,
            "tags": ["carga"],
            "ficha_tecnica": {"motor_cc": 250},
            "planes_credito": {"20%": {"enganche_mxn": 9000}},
            "search_text": "beta 250 trabajo carga",
        },
    ],
    "requirement_plans": [
        {
            "title": "Pensionados",
            "plan_id": "pensionados_15",
            "tipo_credito": "Pensionados",
            "plan_credito": "15%",
            "aliases_usuario": ["soy pensionado", "pension", "pensionada"],
            "texto_retrieval": "requisitos pensionados: identificacion, "
            "comprobante de pension de los ultimos 3 meses",
            "structured": {},
        },
        {
            "title": "Sin Comprobantes",
            "plan_id": "sin_comprobantes_20",
            "tipo_credito": "Sin Comprobantes",
            "plan_credito": "20%",
            "aliases_usuario": ["no tengo comprobantes", "sin recibos"],
            "texto_retrieval": "requisitos sin comprobantes: 20% de enganche",
            "structured": {},
        },
    ],
}


def _call(tool_name, arguments=None, contact_state=None):
    executor = RealFactsToolExecutor(BINDINGS, FACTS)
    return executor.execute_tool(
        LLMToolCallProposal(
            tool_name=tool_name,
            arguments=arguments or {},
            reason="test",
            required=True,
        ),
        AgentContextPackage(
            agent_identity={"contact_state": contact_state or {}}
        ),
    )


def test_catalog_search_matches_real_models_only() -> None:
    result = _call("catalog.search", {"query": "alpha"})
    assert result.status == "succeeded"
    assert result.source_kind == "real_catalog"
    labels = [model["label"] for model in result.facts["models"]]
    assert labels == ["Alpha 150"]
    # A model that does not exist in the published catalog never appears.
    ghost = _call("catalog.search", {"query": "fantasma-999"})
    assert all(
        model["label"] != "fantasma-999" for model in ghost.facts.get("models", [])
    )


def test_quote_resolves_real_prices_by_alias() -> None:
    result = _call(
        "quote.resolve", contact_state={"selected_model": "la alpha"}
    )
    assert result.status == "succeeded"
    assert result.facts["price_lista_mxn"] == 31395
    assert result.facts["price_contado_mxn"] == 29900
    assert "10%" in result.facts["planes_credito"]
    # The static dry quote ($32,500) can never come out of the real executor.
    assert result.facts["price_lista_mxn"] != 32500


def test_quote_unknown_model_skips_not_invents() -> None:
    result = _call(
        "quote.resolve", contact_state={"selected_model": "modelo-fantasma"}
    )
    assert result.status == "skipped"
    assert result.error_code == "no_real_data_match"
    assert result.can_support_claims is False


def test_requirements_match_income_aliases() -> None:
    result = _call(
        "requirements.lookup", contact_state={"income_type": "soy pensionado"}
    )
    assert result.status == "succeeded"
    assert result.source_kind == "knowledge_os"
    assert result.facts["matched"] is True
    tipos = [plan["tipo_credito"] for plan in result.facts["plans"]]
    assert "Pensionados" in tipos


def test_tool_without_real_source_skips() -> None:
    result = _call("legacy.tool")
    assert result.status == "skipped"
    assert result.error_code == "real_source_not_configured"


def test_real_allowed_values_replace_harness_vocabulary() -> None:
    """Visible-send turns rebuild referent-checked field vocabularies from
    the REAL catalog so demo/harness model names never leak via the prompt."""
    from atendia.product_agents.agent_service_bridge import (
        _real_allowed_values_for_fields,
    )

    fields = [
        {
            "field_key": "selected_option",
            "referent_check": True,
            "allowed_values": [{"value": "demo-1", "aliases": ["Demo"]}],
        },
        {"field_key": "income_type", "allowed_values": ["a", "b"]},
    ]
    updated = _real_allowed_values_for_fields(fields, FACTS)
    product_values = {
        group["value"] for group in updated[0]["allowed_values"]
    }
    assert product_values == {"alpha-150", "beta-250"}
    assert "Alpha 150" in updated[0]["allowed_values"][0]["aliases"]
    # Non-referent fields untouched; empty real catalog leaves config as-is.
    assert updated[1]["allowed_values"] == ["a", "b"]
    untouched = _real_allowed_values_for_fields(fields, {"models": []})
    assert untouched[0]["allowed_values"][0]["value"] == "demo-1"

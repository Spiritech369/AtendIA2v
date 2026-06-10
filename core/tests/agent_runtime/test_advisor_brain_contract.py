from __future__ import annotations

from atendia.agent_runtime.advisor_brain_contract import (
    AdvisorBrainContractValidator,
    advisor_brain_contract_system_rules,
    advisor_brain_decision_json_schema,
)
from atendia.agent_runtime.canonical import CanonicalProductReference
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    AdvisorBrainToolRequest,
    ConversationMemoryContext,
    TenantRuntimeConfigContext,
    TurnContext,
)


def _product(
    product_id: str = "prod-adventure",
    sku: str = "ADV-250",
    display_name: str = "Adventure 250 CC",
) -> CanonicalProductReference:
    return CanonicalProductReference(
        product_id=product_id,
        sku=sku,
        display_name=display_name,
        catalog_id="catalog-1",
        catalog_version_id="v1",
    )


def _context(
    message: str,
    *,
    product: CanonicalProductReference | None = None,
    last_options: list[CanonicalProductReference] | None = None,
    facts: dict | None = None,
) -> TurnContext:
    salient = dict(facts or {})
    if product is not None:
        salient["Producto"] = product.model_dump(mode="json")
    return TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text=message,
        memory=ConversationMemoryContext(
            salient_facts=salient,
            metadata={
                "last_options": [
                    option.model_dump(mode="json")
                    for option in (last_options or [])
                ]
            },
        ),
        tenant_config=TenantRuntimeConfigContext(
            ruleset={
                "operational_state": {
                    "fields": {
                        "product": "Producto",
                        "last_quote": "Ultima_Cotizacion",
                        "quote_sent": "Cotizacion_Enviada",
                    }
                }
            }
        ),
    )


def _tool(name: str, payload: dict | None = None) -> AdvisorBrainToolRequest:
    return AdvisorBrainToolRequest(
        name=name,
        payload=payload or {},
        reason="model requested tool",
        evidence=["customer message"],
        required=True,
    )


def _change(key: str, value: object) -> AdvisorBrainStateChange:
    return AdvisorBrainStateChange(
        target="contact_field",
        key=key,
        value=value,
        reason="model proposed field",
        evidence=["customer message"],
        confidence=0.9,
    )


def _decision(
    *,
    tools: list[AdvisorBrainToolRequest] | None = None,
    changes: list[AdvisorBrainStateChange] | None = None,
    response_plan: str = "Responder sin precios usando herramientas.",
) -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="structured model decision",
        customer_goal="advance_sale",
        conversation_goals=["advance_sale"],
        known_facts={},
        missing_facts=[],
        next_best_action="advance_sale",
        required_tools=tools or [],
        proposed_state_changes=changes or [],
        response_plan=response_plan,
        confidence=0.8,
        needs_human=False,
        risk_flags=[],
        metadata={},
    )


def _normalize(context: TurnContext, decision: AdvisorBrainDecision) -> AdvisorBrainDecision:
    return AdvisorBrainContractValidator().normalize(context=context, decision=decision).decision


def test_runtime_prompt_contains_user_contract_and_metadata_schema() -> None:
    prompt = advisor_brain_contract_system_rules()
    schema = advisor_brain_decision_json_schema()["schema"]
    tool_schema = schema["properties"]["required_tools"]["items"]
    state_schema = schema["properties"]["proposed_state_changes"]["items"]

    assert "Eres AdvisorBrain para un agente comercial" in prompt
    assert "No eres fuente de precios" in prompt
    assert "No marques `Cotizacion_Enviada`" in prompt
    assert "No escribas `Ultima_Cotizacion`" in prompt
    assert "metadata" in tool_schema["required"]
    assert "metadata" in state_schema["required"]


def test_location_plus_commercial_interest_keeps_faq_and_product_without_quote() -> None:
    product = _product()
    decision = _decision(
        tools=[
            _tool("faq.resolve", {"topic": "ubicacion"}),
            _tool("catalog.lookup", {"canonical_product_ref": product.model_dump(mode="json")}),
            _tool(
                "quote.resolve",
                {"product": product.model_dump(mode="json"), "plan_code": "cash"},
            ),
        ],
        changes=[_change("Producto", product.model_dump(mode="json"))],
    )

    normalized = _normalize(
        _context("Hola, donde están y quiero la Adventure, tengo buró"),
        decision,
    )

    assert [tool.name for tool in normalized.required_tools] == ["faq.resolve", "catalog.lookup"]
    assert normalized.proposed_state_changes[0].key == "Producto"
    assert "advisor_contract_violation" in normalized.risk_flags


def test_first_option_uses_last_options_canonical_ref_and_blocks_alias_quote() -> None:
    first = _product("prod-r4", "R4-250", "R4 250 CC")
    decision = _decision(
        tools=[
            _tool("catalog.lookup", {"canonical_product_ref": first.model_dump(mode="json")}),
            _tool("quote.resolve", {"product": "la primera", "plan_code": "cash"}),
        ],
        changes=[_change("Producto", first.model_dump(mode="json"))],
    )

    normalized = _normalize(_context("La primera", last_options=[first]), decision)

    assert [tool.name for tool in normalized.required_tools] == ["catalog.lookup"]
    assert normalized.proposed_state_changes[0].value["product_id"] == "prod-r4"


def test_cotizamela_adds_canonical_product_from_state_to_quote_tool() -> None:
    product = _product("prod-r4", "R4-250", "R4 250 CC")
    decision = _decision(tools=[_tool("quote.resolve", {"plan_code": "cash"})])

    normalized = _normalize(_context("Cotízamela", product=product), decision)

    assert normalized.required_tools[0].name == "quote.resolve"
    assert normalized.required_tools[0].payload["product"]["product_id"] == "prod-r4"
    assert "advisor_contract_violation" in normalized.risk_flags


def test_quote_resolve_without_plan_is_blocked_instead_of_defaulting_to_cash() -> None:
    product = _product("prod-r4", "R4-250", "R4 250 CC")
    decision = _decision(tools=[_tool("quote.resolve", {})])

    normalized = _normalize(_context("Cotizamela", product=product), decision)

    assert normalized.required_tools == []
    assert "advisor_contract_violation" in normalized.risk_flags
    assert "quote_resolve_without_validated_plan" in {
        item["code"] for item in normalized.metadata["advisor_contract"]["violations"]
    }


def test_contract_does_not_map_income_words_to_plan_code() -> None:
    product = _product("prod-r4", "R4-250", "R4 250 CC")
    decision = _decision(
        tools=[
            _tool(
                "quote.resolve",
                {"product": product.model_dump(mode="json"), "plan_code": "tarjeta"},
            )
        ]
    )

    normalized = _normalize(_context("Cotizame, me pagan por tarjeta", product=product), decision)

    assert normalized.required_tools[0].payload["plan_code"] == "tarjeta"
    assert normalized.required_tools[0].payload["plan_code"] != "Nomina Tarjeta"


def test_documents_question_drops_quote_and_keeps_requirements_resolve() -> None:
    product = _product()
    decision = _decision(
        tools=[
            _tool("requirements.resolve", {"plan": None}),
            _tool(
                "quote.resolve",
                {"product": product.model_dump(mode="json"), "plan_code": "cash"},
            ),
        ]
    )

    normalized = _normalize(_context("Qué documentos necesito?", product=product), decision)

    assert [tool.name for tool in normalized.required_tools] == ["requirements.resolve"]


def test_product_change_without_price_intent_does_not_reuse_old_quote() -> None:
    r4 = _product("prod-r4", "R4-250", "R4 250 CC")
    previous = _product("prod-adventure", "ADV-250", "Adventure 250 CC")
    decision = _decision(
        tools=[
            _tool("catalog.lookup", {"canonical_product_ref": r4.model_dump(mode="json")}),
            _tool(
                "quote.resolve",
                {"product": previous.model_dump(mode="json"), "plan_code": "cash"},
            ),
        ],
        changes=[_change("Producto", r4.model_dump(mode="json"))],
    )

    normalized = _normalize(_context("Quiero otra moto, la R4", product=previous), decision)

    assert [tool.name for tool in normalized.required_tools] == ["catalog.lookup"]
    assert normalized.proposed_state_changes[0].value["product_id"] == "prod-r4"


def test_seniority_message_preserves_evidenced_state_and_drops_quote() -> None:
    product = _product()
    decision = _decision(
        tools=[
            _tool(
                "quote.resolve",
                {"product": product.model_dump(mode="json"), "plan_code": "cash"},
            )
        ],
        changes=[_change("Antiguedad_Laboral", "1 año")],
    )

    normalized = _normalize(_context("Tengo 1 año trabajando", product=product), decision)

    assert normalized.required_tools == []
    assert normalized.proposed_state_changes[0].key == "Antiguedad_Laboral"


def test_card_deposit_message_preserves_plan_and_drops_quote() -> None:
    product = _product()
    decision = _decision(
        tools=[
            _tool(
                "quote.resolve",
                {"product": product.model_dump(mode="json"), "plan_code": "cash"},
            )
        ],
        changes=[_change("Plan_Credito", "Nomina Tarjeta")],
    )

    normalized = _normalize(_context("Me depositan en tarjeta", product=product), decision)

    assert normalized.required_tools == []
    assert normalized.proposed_state_changes[0].value == "Nomina Tarjeta"


def test_contract_drops_forbidden_quote_state_and_price_response_plan() -> None:
    decision = _decision(
        changes=[
            _change("Ultima_Cotizacion", {"cash_price": 62900}),
            _change("Cotizacion_Enviada", True),
        ],
        response_plan="Responder que el precio queda en $62,900.",
    )

    normalized = _normalize(_context("Dame precio"), decision)

    assert normalized.proposed_state_changes == []
    assert "$62,900" not in normalized.response_plan
    assert "advisor_contract_violation" in normalized.risk_flags
    assert "advisor_contract_warning" in normalized.risk_flags


def test_contract_dedupes_incompatible_quote_resolve_tools() -> None:
    product = _product()
    decision = _decision(
        tools=[
            _tool(
                "quote.resolve",
                {"product": product.model_dump(mode="json"), "plan_code": "cash"},
            ),
            _tool(
                "quote.resolve",
                {"product": product.model_dump(mode="json"), "plan_code": "Sin Comprobantes"},
            ),
        ]
    )

    normalized = _normalize(_context("Cotízame la Adventure", product=product), decision)

    assert len(normalized.required_tools) == 1
    assert normalized.required_tools[0].payload["plan_code"] == "cash"
    assert "advisor_contract_violation" in normalized.risk_flags

from __future__ import annotations

import pytest

from atendia.agent_runtime import (
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    AdvisorFirstAgentProvider,
    AliasMap,
    CanonicalProduct,
    CanonicalProductReference,
    DeterministicStateWriter,
    QuoteSnapshot,
    SKUIndex,
    ToolExecutionResult,
)
from atendia.agent_runtime.canonical import quote_snapshot_hash
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    TenantRuntimeConfigContext,
    TurnContext,
)


class _Brain:
    def __init__(self, changes: list[AdvisorBrainStateChange]) -> None:
        self._changes = changes

    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        del context
        return AdvisorBrainDecision(
            understanding="Cliente quiere avanzar con un producto.",
            customer_goal="quote",
            conversation_goals=["quote", "advance_sale"],
            known_facts={},
            missing_facts=[],
            next_best_action="quote",
            proposed_state_changes=self._changes,
            response_plan="Responder naturalmente con datos validados.",
            confidence=0.9,
        )


def _context(memory: dict | None = None) -> TurnContext:
    return TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text="Me interesa esa opcion",
        memory=memory or {},
        tenant_config=TenantRuntimeConfigContext(
            ruleset={
                "operational_state": {
                    "fields": {
                        "product": "Producto",
                        "last_quote": "Ultima_Cotizacion",
                        "quote_sent": "Cotizacion_Enviada",
                        "plan": "Plan_Credito",
                        "income": "Ingreso",
                        "documents_complete": "Doc_Completos",
                        "documents_incomplete": "Doc_Incompletos",
                        "documents_checklist": "Docs_Checklist",
                    }
                },
                "state_writer": {
                    "product_fields": ["Producto"],
                    "quote_snapshot_fields": ["Ultima_Cotizacion"],
                    "plan_fields": ["Plan_Credito"],
                    "income_fields": ["Ingreso"],
                    "document_fields": ["Doc_Completos", "Doc_Incompletos", "Docs_Checklist"],
                    "document_stages": ["papeleria_completa", "papeleria_incompleta"],
                },
            }
        ),
        active_agent=ActiveAgentContext(
            visible_contact_field_keys=[
                "Producto",
                "Ultima_Cotizacion",
                "Cotizacion_Enviada",
                "Nombre",
                "Plan_Credito",
                "Ingreso",
                "Doc_Completos",
                "Doc_Incompletos",
                "Docs_Checklist",
            ],
        ),
    )


def _product_ref() -> CanonicalProductReference:
    return CanonicalProductReference(
        product_id="prod-1",
        sku="SKU-1",
        display_name="Producto Uno",
        catalog_id="catalog-1",
        catalog_version_id="v1",
        evidence=["CatalogLookup matched SKU-1"],
    )


def _quote_snapshot() -> QuoteSnapshot:
    return QuoteSnapshot(
        snapshot_id="quote-prod-1-cash",
        tenant_id="tenant-1",
        product=_product_ref(),
        plan_code="cash",
        plan_name="Contado",
        pricing={"cash_price": "1000"},
        quote_payload={"currency": "MXN", "cash_price": "1000"},
        evidence=["QuoteResolver returned SKU-1 cash quote"],
    )


def _finance_quote_snapshot() -> QuoteSnapshot:
    return QuoteSnapshot(
        snapshot_id="quote-prod-1-finance",
        tenant_id="tenant-1",
        product=_product_ref(),
        plan_code="Sin Comprobantes",
        plan_name="Sin Comprobantes",
        pricing={"down_payment": 200, "installment": 100, "installments": 36},
        quote_payload={"pricing": {"down_payment": 200, "installment": 100}},
        evidence=["QuoteResolver returned SKU-1 finance quote"],
    )


def _other_product_ref() -> CanonicalProductReference:
    return CanonicalProductReference(
        product_id="prod-2",
        sku="SKU-2",
        display_name="Producto Dos",
        catalog_id="catalog-1",
        catalog_version_id="v1",
        evidence=["CatalogLookup matched SKU-2"],
    )


def test_alias_map_and_sku_index_resolve_to_canonical_refs() -> None:
    product = CanonicalProduct(
        product_id="prod-1",
        sku="SKU-1",
        display_name="Producto Uno",
        aliases=["uno", "producto principal"],
    )

    assert AliasMap.from_products([product]).resolve("Producto Principal") == product.ref()
    assert SKUIndex.from_products([product]).resolve("sku 1") == product.ref()


def test_quote_snapshot_integrity_hash_is_stable_and_validated() -> None:
    snapshot = _quote_snapshot().with_integrity_hash()

    assert snapshot.integrity_hash == quote_snapshot_hash(snapshot)
    with pytest.raises(ValueError):
        QuoteSnapshot.model_validate(
            {
                **snapshot.model_dump(mode="json"),
                "pricing": {"cash_price": "2000"},
            }
        )


@pytest.mark.asyncio
async def test_state_writer_accepts_only_canonical_product_references() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_Brain(
            [
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Producto",
                    value="Producto Uno",
                    reason="Modelo intento guardar texto libre.",
                    evidence=["Producto Uno"],
                    confidence=0.9,
                ),
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Producto",
                    value=_product_ref().model_dump(mode="json"),
                    reason="CatalogLookup resolvio referencia canonica.",
                    evidence=["CatalogLookup matched SKU-1"],
                    confidence=1.0,
                ),
            ]
        )
    )

    output = await provider.generate(_context())

    values = {update.field_key: update.value for update in output.field_updates}
    assert values["Producto"]["product_id"] == "prod-1"
    assert values["Producto"]["sku"] == "SKU-1"
    assert output.trace_metadata["state_writer"]["blocked"] == [
        {"target": "contact_field", "key": "Producto", "reason": "invalid_or_unsafe_field_update"}
    ]


@pytest.mark.asyncio
async def test_state_writer_blocks_model_authored_quote_snapshot() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_Brain(
            [
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Ultima_Cotizacion",
                    value="Precio 1000 de contado",
                    reason="Modelo intento reconstruir cotizacion.",
                    evidence=["Precio 1000 de contado"],
                    confidence=0.9,
                ),
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Ultima_Cotizacion",
                    value=_quote_snapshot().model_dump(mode="json"),
                    reason="QuoteResolver devolvio snapshot estructurado.",
                    evidence=["QuoteResolver returned SKU-1 cash quote"],
                    confidence=1.0,
                ),
            ]
        )
    )

    output = await provider.generate(_context())

    assert {update.field_key for update in output.field_updates} == set()
    assert output.trace_metadata["state_writer"]["blocked"] == [
        {
            "target": "contact_field",
            "key": "Ultima_Cotizacion",
            "reason": "quote_snapshot_requires_quote_resolver",
        },
        {
            "target": "contact_field",
            "key": "Ultima_Cotizacion",
            "reason": "quote_snapshot_requires_quote_resolver",
        },
    ]


def test_state_writer_applies_quote_snapshot_only_from_quote_resolver() -> None:
    decision = AdvisorBrainDecision(
        understanding="Tool resolved a quote.",
        customer_goal="quote",
        conversation_goals=["quote"],
        known_facts={},
        missing_facts=[],
        next_best_action="quote",
        proposed_state_changes=[],
        response_plan="Responder con snapshot validado.",
        confidence=0.9,
    )
    snapshot = _quote_snapshot()

    result = DeterministicStateWriter().build_updates(
        context=_context(),
        decision=decision,
        tool_results=[
            ToolExecutionResult(
                tool_name="faq.resolve",
                status="succeeded",
                data={"quote_snapshot": snapshot.model_dump(mode="json")},
            ),
            ToolExecutionResult(
                tool_name="quote.resolve",
                status="succeeded",
                data={"quote_snapshot": snapshot.model_dump(mode="json")},
            ),
        ],
    )

    updates = {update.field_key: update for update in result.field_updates}
    quote = updates["Ultima_Cotizacion"].value
    assert quote["snapshot_id"] == "quote-prod-1-cash"
    assert quote["product"]["product_id"] == "prod-1"
    assert quote["plan_code"] == "cash"
    assert quote["pricing"] == {"cash_price": "1000"}
    assert quote["currency"] == "MXN"
    assert quote["integrity_hash"]
    assert quote["evidence"] == ["QuoteResolver returned SKU-1 cash quote"]
    assert updates["Ultima_Cotizacion"].metadata["quote_snapshot_id"] == "quote-prod-1-cash"
    quote_updates = [
        update for update in result.field_updates if update.field_key == "Ultima_Cotizacion"
    ]
    assert len(quote_updates) == 1


@pytest.mark.asyncio
async def test_state_writer_invalidates_quote_snapshot_when_product_changes() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_Brain(
            [
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Producto",
                    value=_other_product_ref().model_dump(mode="json"),
                    reason="Cliente cambio a otro producto canonico.",
                    evidence=["Mejor el Producto Dos"],
                    confidence=1.0,
                )
            ]
        )
    )
    current_quote = _quote_snapshot().with_integrity_hash().model_dump(mode="json")

    output = await provider.generate(
        _context(
            {
                "salient_facts": {
                    "Producto": _product_ref().model_dump(mode="json"),
                    "Ultima_Cotizacion": current_quote,
                    "Cotizacion_Enviada": True,
                },
                "last_quote_snapshot": current_quote,
            }
        )
    )

    updates = {update.field_key: update for update in output.field_updates}
    assert updates["Producto"].value["product_id"] == "prod-2"
    assert updates["Ultima_Cotizacion"].value is None
    assert updates["Ultima_Cotizacion"].metadata["quote_snapshot_invalidated"] is True
    assert updates["Ultima_Cotizacion"].metadata["invalidated_by_product_change"] is True
    assert updates["Ultima_Cotizacion"].metadata["invalidated_quote_snapshot"]["snapshot_id"] == (
        "quote-prod-1-cash"
    )
    assert updates["Cotizacion_Enviada"].value is False


@pytest.mark.asyncio
async def test_state_writer_invalidates_financing_quote_when_plan_changes() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_Brain(
            [
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Ingreso",
                    value="nomina tarjeta",
                    reason="Cliente cambio forma de ingreso.",
                    evidence=["Me depositan en tarjeta"],
                    confidence=1.0,
                )
            ]
        )
    )
    current_quote = _finance_quote_snapshot().with_integrity_hash().model_dump(mode="json")

    output = await provider.generate(
        _context(
            {
                "salient_facts": {
                    "Producto": _product_ref().model_dump(mode="json"),
                    "Ultima_Cotizacion": current_quote,
                    "Cotizacion_Enviada": True,
                },
                "last_quote_snapshot": current_quote,
            }
        )
    )

    updates = {update.field_key: update for update in output.field_updates}
    assert updates["Ingreso"].value == "nomina tarjeta"
    assert updates["Ultima_Cotizacion"].value is None
    assert updates["Ultima_Cotizacion"].metadata["invalidated_by_plan_change"] is True
    assert updates["Cotizacion_Enviada"].value is False


@pytest.mark.asyncio
async def test_state_writer_blocks_papeleria_incompleta_without_attachment() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_Brain(
            [
                AdvisorBrainStateChange(
                    target="contact_field",
                    key="Doc_Incompletos",
                    value=True,
                    reason="Cliente dijo que enviaria INE.",
                    evidence=["Te mando INE"],
                    confidence=0.9,
                ),
                AdvisorBrainStateChange(
                    target="lifecycle",
                    key="papeleria_incompleta",
                    value={"target_stage": "papeleria_incompleta"},
                    reason="Cliente dijo que enviaria INE.",
                    evidence=["Te mando INE"],
                    confidence=0.9,
                ),
            ]
        )
    )

    output = await provider.generate(_context())

    assert output.lifecycle_update is None
    assert {update.field_key for update in output.field_updates} == set()
    assert output.trace_metadata["state_writer"]["blocked"] == [
        {
            "target": "contact_field",
            "key": "Doc_Incompletos",
            "reason": "document_update_requires_attachment_or_checklist",
        },
        {
            "target": "lifecycle",
            "key": "papeleria_incompleta",
            "reason": "document_stage_requires_attachment_or_checklist",
        },
    ]

from __future__ import annotations

import pytest

from atendia.agent_runtime import (
    AdvisorBrainDecision,
    AdvisorFirstAgentProvider,
    QuoteSnapshot,
)
from atendia.agent_runtime.canonical import CanonicalProductReference
from atendia.agent_runtime.quote_safety import (
    QuoteSafetyGuard,
    find_price_mentions,
    visible_quote_signal,
)
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    FieldUpdate,
    TenantRuntimeConfigContext,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult


class _Brain:
    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        del context
        return AdvisorBrainDecision(
            understanding="Cliente pide precio.",
            customer_goal="quote",
            conversation_goals=["quote"],
            next_best_action="quote",
            response_plan="Responder con datos validados.",
            confidence=0.9,
        )


class _NoToolLayer:
    async def execute(self, *, context: TurnContext, decision: AdvisorBrainDecision):
        del context, decision
        return []


class _QuoteToolLayer:
    async def execute(self, *, context: TurnContext, decision: AdvisorBrainDecision):
        del context, decision
        return [
            ToolExecutionResult(
                tool_name="quote.resolve",
                status="succeeded",
                data={"quote_snapshot": _quote_snapshot().model_dump(mode="json")},
            )
        ]


class _PricingComposer:
    async def compose(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]],
    ) -> TurnOutput:
        del context, decision, tool_results, policy_warnings
        return TurnOutput(
            final_message="La R4 queda en $62,900 de contado.",
            confidence=0.9,
            field_updates=[
                *state_write_result.field_updates,
                FieldUpdate(
                    field_key="Cotizacion_Enviada",
                    value=True,
                    reason="Composer tried to mark sent before safety.",
                    evidence=["La R4 queda en $62,900 de contado."],
                    confidence=1.0,
                    source="ai_inference",
                ),
            ],
            trace_metadata={"state_writer": {"blocked": state_write_result.blocked}},
        )


def _context(memory: dict | None = None) -> TurnContext:
    return TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text="Cuanto cuesta la R4?",
        memory=memory or {},
        tenant_config=TenantRuntimeConfigContext(
            ruleset={
                "operational_state": {
                    "fields": {
                        "product": "Producto",
                        "last_quote": "Ultima_Cotizacion",
                        "quote_sent": "Cotizacion_Enviada",
                    }
                },
                "state_writer": {
                    "product_fields": ["Producto"],
                    "quote_snapshot_fields": ["Ultima_Cotizacion"],
                },
            }
        ),
        active_agent=ActiveAgentContext(
            visible_contact_field_keys=[
                "Producto",
                "Ultima_Cotizacion",
                "Cotizacion_Enviada",
            ]
        ),
    )


def _product_ref() -> CanonicalProductReference:
    return CanonicalProductReference(
        product_id="prod-r4",
        sku="R4-250",
        display_name="R4 250 CC",
        catalog_id="catalog-1",
        catalog_version_id="v1",
        evidence=["CatalogLookup matched R4"],
    )


def _quote_snapshot() -> QuoteSnapshot:
    return QuoteSnapshot(
        snapshot_id="quote-r4-cash",
        tenant_id="tenant-1",
        product=_product_ref(),
        plan_code="cash",
        plan_name="Contado",
        pricing={"cash_price": 62900},
        quote_payload={"pricing": {"cash_price": 62900}},
        evidence=["QuoteResolver returned R4 cash quote"],
    ).with_integrity_hash()


def _finance_quote_snapshot() -> QuoteSnapshot:
    return QuoteSnapshot(
        snapshot_id="quote-r4-finance",
        tenant_id="tenant-1",
        product=_product_ref(),
        plan_code="credit_72q",
        plan_name="Credito 72 quincenas",
        pricing={
            "cash_price": 62900,
            "down_payment": 8390,
            "installment": 3333,
            "installments": 72,
        },
        quote_payload={"pricing": {"down_payment": 8390, "installment": 3333, "installments": 72}},
        evidence=["QuoteResolver returned R4 finance quote"],
    ).with_integrity_hash()


def _quote_result(snapshot: QuoteSnapshot | None = None) -> list[ToolExecutionResult]:
    return [
        ToolExecutionResult(
            tool_name="quote.resolve",
            status="succeeded",
            data={"quote_snapshot": (snapshot or _quote_snapshot()).model_dump(mode="json")},
        )
    ]


def test_detects_money_symbol_amount() -> None:
    assert visible_quote_signal("La moto queda en $50,400.")
    assert find_price_mentions("La moto queda en $50,400.")[0].value == 50400


def test_detects_quoted_bare_amount() -> None:
    assert visible_quote_signal("De contado queda en 79900")


def test_detects_finance_amounts_and_installment_count() -> None:
    mentions = find_price_mentions("Enganche $8,390, pagos $3,333 por 72 quincenas.")

    assert [mention.value for mention in mentions] == [8390, 3333, 72]


def test_does_not_detect_labor_seniority_months_as_quote_term() -> None:
    mentions = find_price_mentions(
        "Con tu antiguedad laboral de 24 meses, enganche $8,390 y pagos $3,333."
    )

    assert [mention.value for mention in mentions] == [8390, 3333]


def test_does_not_detect_document_validity_months_as_quote_term() -> None:
    mentions = find_price_mentions(
        "Con pago inicial del 10%, manda comprobante de domicilio menor a 2 meses."
    )

    assert mentions == []


def test_does_not_detect_phone_like_value_as_price() -> None:
    assert visible_quote_signal("+52999836cc71874") is False


def test_does_not_detect_engine_cc_as_price() -> None:
    assert visible_quote_signal("Comando 400 CC") is False


@pytest.mark.asyncio
async def test_quote_safety_rewrites_visible_price_without_quote_snapshot() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_Brain(),
        tool_layer=_NoToolLayer(),
        composer=_PricingComposer(),
    )

    output = await provider.generate(_context())

    assert "$62,900" not in output.final_message
    assert "modelo quieres" in output.final_message
    assert output.trace_metadata["quote_safety"]["allowed"] is False
    assert output.trace_metadata["quote_safety"]["action"] == "rewritten"
    assert "quoted_without_canonical_product" in output.trace_metadata["quote_safety"]["failures"]
    assert all(update.field_key != "Cotizacion_Enviada" for update in output.field_updates)


def test_quote_safety_shadow_mode_records_but_does_not_sanitize() -> None:
    output = TurnOutput(final_message="La R4 queda en $62,900 de contado.", confidence=0.9)

    result = QuoteSafetyGuard(mode="shadow").apply(context=_context(), output=output)

    assert result.allowed is False
    assert result.action == "shadow"
    assert result.output.final_message == "La R4 queda en $62,900 de contado."
    assert result.output.trace_metadata["quote_safety"]["mode"] == "shadow"
    assert result.output.trace_metadata["quote_safety"]["action"] == "shadow"


@pytest.mark.asyncio
async def test_quote_safety_allows_visible_price_with_quote_snapshot_and_marks_sent() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_Brain(),
        tool_layer=_QuoteToolLayer(),
        composer=_PricingComposer(),
    )

    output = await provider.generate(_context())

    assert "$62,900" in output.final_message
    values = {update.field_key: update.value for update in output.field_updates}
    assert values["Producto"]["product_id"] == "prod-r4"
    assert values["Ultima_Cotizacion"]["integrity_hash"]
    assert values["Cotizacion_Enviada"] is True
    assert output.trace_metadata["quote_safety"]["allowed"] is True


def test_quote_safety_blocks_amount_not_in_snapshot() -> None:
    output = TurnOutput(final_message="La R4 queda en $99,999 de contado.", confidence=0.9)

    result = QuoteSafetyGuard().apply(
        context=_context(),
        output=output,
        tool_results=_quote_result(),
    )

    assert result.allowed is False
    assert "quote_amount_not_in_snapshot" in result.failures
    assert "$99,999" not in result.output.final_message
    assert result.metrics.unmatched_amounts == ["$99,999"]


def test_quote_safety_blocks_product_that_differs_from_snapshot() -> None:
    output = TurnOutput(final_message="La U5 queda en $62,900 de contado.", confidence=0.9)

    result = QuoteSafetyGuard().apply(
        context=_context(),
        output=output,
        tool_results=_quote_result(),
    )

    assert result.allowed is False
    assert "quote_product_mismatch" in result.failures


def test_quote_safety_allows_active_quote_repetition_without_product_or_plan_change() -> None:
    snapshot = _quote_snapshot()
    context = _context(
        {
            "last_quote_snapshot": snapshot.model_dump(mode="json"),
            "salient_facts": {
                "Producto": _product_ref().model_dump(mode="json"),
                "Ultima_Cotizacion": snapshot.model_dump(mode="json"),
            },
        }
    )
    output = TurnOutput(final_message="Claro, la R4 sigue en $62,900 de contado.", confidence=0.9)

    result = QuoteSafetyGuard().apply(context=context, output=output)

    assert result.allowed is True
    assert result.quote_snapshot_id == "quote-r4-cash"


def test_quote_safety_blocks_active_quote_when_customer_changed_product() -> None:
    snapshot = _quote_snapshot()
    context = _context(
        {
            "last_quote_snapshot": snapshot.model_dump(mode="json"),
            "salient_facts": {
                "Producto": _product_ref().model_dump(mode="json"),
                "Ultima_Cotizacion": snapshot.model_dump(mode="json"),
            },
        }
    )
    output = TurnOutput(final_message="La U5 queda en $62,900 de contado.", confidence=0.9)

    result = QuoteSafetyGuard().apply(context=context, output=output)

    assert result.allowed is False
    assert "stale_quote_product_mismatch" in result.failures


def test_quote_safety_allows_finance_amounts_when_all_values_match_snapshot() -> None:
    output = TurnOutput(
        final_message="La R4 va con enganche $8,390, pagos $3,333 por 72 quincenas.",
        confidence=0.9,
    )

    result = QuoteSafetyGuard().apply(
        context=_context(),
        output=output,
        tool_results=_quote_result(_finance_quote_snapshot()),
    )

    assert result.allowed is True
    assert result.metrics.price_mentions_count == 3
    assert result.metrics.matched_snapshot_amounts == 3


def test_quote_safety_reports_missing_canonical_product_failure() -> None:
    output = TurnOutput(final_message="Queda en $50,400.", confidence=0.9)

    result = QuoteSafetyGuard().apply(context=_context(), output=output)

    assert result.allowed is False
    assert "quoted_without_canonical_product" in result.failures

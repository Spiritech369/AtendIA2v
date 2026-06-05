from __future__ import annotations

from atendia.agent_runtime.canonical import CanonicalProductReference, QuoteSnapshot
from atendia.agent_runtime.composer_quote_context import (
    QuoteContext,
    QuoteSnippetBuilder,
    build_quote_context,
    enforce_quote_context_on_message,
    quote_snippet_from_snapshot,
)
from atendia.agent_runtime.quote_safety import visible_quote_signal
from atendia.agent_runtime.schemas import (
    ConversationMemoryContext,
    TenantRuntimeConfigContext,
    ToolExecutionResult,
    TurnContext,
)
from atendia.simulation.provider_advisor_first_eval import (
    _composer_output_json_schema,
    _composer_system_prompt,
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


def _quote_snapshot(product: CanonicalProductReference | None = None) -> QuoteSnapshot:
    return QuoteSnapshot(
        snapshot_id="quote-adventure-cash",
        tenant_id="tenant-1",
        product=product or _product(),
        plan_code="cash",
        plan_name="Contado",
        pricing={"cash_price": 62900},
        quote_payload={"pricing": {"cash_price": 62900}},
        evidence=["QuoteResolver returned quote"],
    ).with_integrity_hash()


def _finance_quote_snapshot() -> QuoteSnapshot:
    return QuoteSnapshot(
        snapshot_id="quote-adventure-finance",
        tenant_id="tenant-1",
        product=_product(),
        plan_code="Sin Comprobantes",
        plan_name="Sin Comprobantes",
        pricing={
            "down_payment": 10080,
            "installment": 1120,
            "installments": 72,
            "period_label": "quincenas",
        },
        quote_payload={"pricing": {"down_payment": 10080, "installment": 1120}},
        evidence=["QuoteResolver returned finance quote"],
    ).with_integrity_hash()


def _context(message: str, *, snapshot: QuoteSnapshot | None = None) -> TurnContext:
    quote = snapshot.model_dump(mode="json") if snapshot else None
    return TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text=message,
        memory=ConversationMemoryContext(
            last_quote_snapshot=quote,
            salient_facts={"Ultima_Cotizacion": quote} if quote else {},
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


def _quote_tool(snapshot: QuoteSnapshot) -> list[ToolExecutionResult]:
    return [
        ToolExecutionResult(
            tool_name="quote.resolve",
            status="succeeded",
            data={"quote_snapshot": snapshot.model_dump(mode="json")},
        )
    ]


def test_runtime_composer_prompt_and_schema_use_quote_context_contract() -> None:
    prompt = _composer_system_prompt()
    schema = _composer_output_json_schema()["schema"]

    assert "Eres Composer para un agente comercial" in prompt
    assert "quote_context.can_quote" in prompt
    assert "quote_context.quote_snippet" in prompt
    assert "No inventes ni recuerdes precios" in prompt
    assert "used_quote_snapshot_id" in schema["required"]
    assert "used_quote_snapshot_hash" in schema["required"]


def test_quote_snippet_builder_formats_cash_snapshot() -> None:
    snippet = QuoteSnippetBuilder().build(_quote_snapshot())

    assert snippet == "De contado, la Adventure 250 CC queda en $62,900."


def test_quote_snippet_builder_formats_financing_snapshot() -> None:
    snippet = QuoteSnippetBuilder().build(_finance_quote_snapshot())

    assert snippet == (
        "Para Adventure 250 CC con Sin Comprobantes, el enganche es de $10,080 "
        "y los pagos son de $1,120 por 72 quincenas."
    )


def test_composer_removes_price_when_quote_context_blocks_quote() -> None:
    context = _context("Tengo 1 ano trabajando")
    quote_context = QuoteContext(
        can_quote=False,
        quote_snapshot=None,
        quote_snippet=None,
        blocked_reason="qualification_only",
    )

    message, notes = enforce_quote_context_on_message(
        message="Perfecto, entonces te queda en $62,900.",
        quote_context=quote_context,
        context=context,
    )

    assert visible_quote_signal(message) is False
    assert "removed_price_without_quote_context" in notes


def test_composer_uses_exact_quote_snippet_when_quote_allowed() -> None:
    snapshot = _quote_snapshot()
    context = _context("Cotizamela")
    quote_context = build_quote_context(context=context, tool_results=_quote_tool(snapshot))
    snippet = quote_snippet_from_snapshot(snapshot)

    message, notes = enforce_quote_context_on_message(
        message="Perfecto, la Adventure queda en $60,000.",
        quote_context=quote_context,
        context=context,
    )

    assert snippet in message
    assert "$60,000" not in message
    assert "quote_snippet_inserted_or_restored" in notes


def test_composer_does_not_change_adventure_snippet_to_r4() -> None:
    snapshot = _quote_snapshot()
    context = _context("Cotizamela")
    quote_context = build_quote_context(context=context, tool_results=_quote_tool(snapshot))
    snippet = quote_snippet_from_snapshot(snapshot)

    message, notes = enforce_quote_context_on_message(
        message=f"Perfecto para la R4. {snippet}",
        quote_context=quote_context,
        context=context,
    )

    assert "R4" not in message
    assert snippet in message
    assert "replaced_product_mismatched_quote_copy" in notes


def test_documents_question_does_not_repeat_active_quote_unnecessarily() -> None:
    snapshot = _quote_snapshot()
    context = _context("Que documentos necesito?", snapshot=snapshot)
    quote_context = build_quote_context(context=context, tool_results=[])

    message, notes = enforce_quote_context_on_message(
        message="Para documentos ocupas INE. La Adventure queda en $62,900.",
        quote_context=quote_context,
        context=context,
    )

    assert quote_context.can_quote is False
    assert visible_quote_signal(message) is False
    assert "removed_price_without_quote_context" in notes


def test_ok_after_quote_does_not_repeat_full_price_without_repeat_request() -> None:
    snapshot = _quote_snapshot()
    context = _context("ok", snapshot=snapshot)
    quote_context = build_quote_context(context=context, tool_results=[])

    message, notes = enforce_quote_context_on_message(
        message="Va, la cotizacion sigue en $62,900.",
        quote_context=quote_context,
        context=context,
    )

    assert quote_context.can_quote is False
    assert visible_quote_signal(message) is False
    assert "removed_price_without_quote_context" in notes

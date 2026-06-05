from __future__ import annotations

import asyncio

import pytest

from atendia.agent_runtime import (
    AdvisorBrainDecision,
    AdvisorFirstAgentProvider,
    ProviderReliabilityConfig,
    ProviderReliabilityLayer,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.canonical import CanonicalProductReference, QuoteSnapshot
from atendia.agent_runtime.provider_reliability import (
    ProviderMalformedJSONError,
    ProviderRetryExhaustedError,
    reset_provider_reliability_circuits,
)
from atendia.agent_runtime.schemas import FieldUpdate, TenantRuntimeConfigContext
from atendia.agent_runtime.state_writer import StateWriteResult


class _RateLimitError(Exception):
    status_code = 429


class _ServerError(Exception):
    status_code = 500


def _config(**overrides) -> ProviderReliabilityConfig:
    data = {
        "max_retries": 2,
        "timeout_s": 0.2,
        "base_delay_ms": 0,
        "max_delay_ms": 0,
        "jitter_ms": 0,
        "circuit_failure_threshold": 2,
        "circuit_cooldown_s": 0.01,
    }
    data.update(overrides)
    return ProviderReliabilityConfig(**data)


def _context(inbound: str = "Cuanto cuesta la R4?") -> TurnContext:
    return TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text=inbound,
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
    )


@pytest.fixture(autouse=True)
def _reset_circuits():
    reset_provider_reliability_circuits()


@pytest.mark.asyncio
async def test_429_once_then_success_retries_once() -> None:
    calls = 0
    layer = ProviderReliabilityLayer(
        provider="openai",
        model="gpt-test",
        tenant_id="tenant-1",
        config=_config(),
    )

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _RateLimitError("429 Too Many Requests")
        return "ok"

    assert await layer.execute(operation, operation_name="test") == "ok"
    snapshot = layer.snapshot().to_dict()

    assert calls == 2
    assert snapshot["provider_retry_count"] == 1
    assert snapshot["provider_429_count"] == 1


@pytest.mark.asyncio
async def test_429_until_retry_exhausted_opens_fallback_path() -> None:
    layer = ProviderReliabilityLayer(
        provider="openai",
        model="gpt-test",
        tenant_id="tenant-1",
        config=_config(max_retries=1),
    )

    async def operation() -> str:
        raise _RateLimitError("429 Too Many Requests")

    with pytest.raises(ProviderRetryExhaustedError):
        await layer.execute(operation, operation_name="test")

    layer.record_fallback_response()
    snapshot = layer.snapshot().to_dict()
    assert snapshot["provider_retry_count"] == 1
    assert snapshot["provider_retry_exhausted_count"] == 1
    assert snapshot["provider_fallback_response_count"] == 1


@pytest.mark.asyncio
async def test_timeout_retries_and_exhausts() -> None:
    layer = ProviderReliabilityLayer(
        provider="openai",
        model="gpt-test",
        tenant_id="tenant-1",
        config=_config(max_retries=1, timeout_s=0.01),
    )

    async def operation() -> str:
        await asyncio.sleep(0.05)
        return "late"

    with pytest.raises(ProviderRetryExhaustedError):
        await layer.execute(operation, operation_name="timeout")

    snapshot = layer.snapshot().to_dict()
    assert snapshot["provider_timeout_count"] == 2
    assert snapshot["provider_retry_count"] == 1


@pytest.mark.asyncio
async def test_circuit_breaker_opens_for_repeated_5xx() -> None:
    layer = ProviderReliabilityLayer(
        provider="openai",
        model="gpt-test",
        tenant_id="tenant-1",
        config=_config(max_retries=0, circuit_failure_threshold=2),
    )

    async def operation() -> str:
        raise _ServerError("500")

    with pytest.raises(ProviderRetryExhaustedError):
        await layer.execute(operation, operation_name="first")
    with pytest.raises(ProviderRetryExhaustedError):
        await layer.execute(operation, operation_name="second")

    snapshot = layer.snapshot().to_dict()
    assert snapshot["provider_5xx_count"] == 2
    assert snapshot["provider_circuit_breaker_open_count"] >= 1
    assert snapshot["circuit_state"] == "open"


class _FailingAdvisor:
    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        del context
        raise ProviderMalformedJSONError("bad advisor json")


class _QuoteAdvisor:
    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        del context
        return AdvisorBrainDecision(
            understanding="Cliente pide cotizacion.",
            customer_goal="quote",
            conversation_goals=["quote"],
            next_best_action="quote",
            required_tools=[],
            response_plan="Cotizar con snapshot.",
            confidence=0.9,
        )


class _QuoteToolLayer:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *, context: TurnContext, decision: AdvisorBrainDecision):
        del context, decision
        self.calls += 1
        return [
            ToolExecutionResult(
                tool_name="quote.resolve",
                status="succeeded",
                data={"quote_snapshot": _quote_snapshot().model_dump(mode="json")},
            )
        ]


class _NoToolLayer:
    async def execute(self, *, context: TurnContext, decision: AdvisorBrainDecision):
        del context, decision
        return []


class _CountingComposer:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def compose(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        policy_warnings: list[dict[str, str]],
    ) -> TurnOutput:
        del context, decision, tool_results, state_write_result, policy_warnings
        self.calls += 1
        if self.fail:
            raise ProviderMalformedJSONError("bad composer json")
        return TurnOutput(final_message="La R4 queda en $62,900 de contado.", confidence=0.9)


def _quote_snapshot() -> QuoteSnapshot:
    product = CanonicalProductReference(
        product_id="prod-r4",
        sku="R4-250",
        display_name="R4 250 CC",
        catalog_id="catalog-1",
        catalog_version_id="v1",
        evidence=["catalog"],
    )
    return QuoteSnapshot(
        snapshot_id="quote-r4-cash",
        tenant_id="tenant-1",
        product=product,
        plan_code="cash",
        plan_name="Contado",
        pricing={"cash_price": 62900},
        quote_payload={"pricing": {"cash_price": 62900}},
        evidence=["QuoteResolver returned R4 cash quote"],
    ).with_integrity_hash()


@pytest.mark.asyncio
async def test_malformed_json_advisor_brain_falls_back_without_tool_or_state_writes() -> None:
    tools = _QuoteToolLayer()
    composer = _CountingComposer()
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_FailingAdvisor(),
        tool_layer=tools,
        composer=composer,
        reliability_config=_config(max_retries=0),
    )

    output = await provider.generate(_context())

    assert output.needs_human is True
    assert output.field_updates == []
    assert tools.calls == 0
    assert composer.calls == 0
    assert "advisor_brain_provider_failed" in output.risk_flags


@pytest.mark.asyncio
async def test_malformed_json_composer_uses_deterministic_quote_fallback() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_QuoteAdvisor(),
        tool_layer=_QuoteToolLayer(),
        composer=_CountingComposer(fail=True),
        reliability_config=_config(max_retries=0),
    )

    output = await provider.generate(_context())
    values = {update.field_key: update.value for update in output.field_updates}

    assert "$62,900" in output.final_message
    assert values["Ultima_Cotizacion"]["snapshot_id"] == "quote-r4-cash"
    assert values["Cotizacion_Enviada"] is True
    assert "composer_provider_failed" in output.risk_flags


@pytest.mark.asyncio
async def test_retry_does_not_duplicate_quote_state_writes() -> None:
    tools = _QuoteToolLayer()
    composer = _CountingComposer(fail=True)
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_QuoteAdvisor(),
        tool_layer=tools,
        composer=composer,
        reliability_config=_config(max_retries=1),
    )

    output = await provider.generate(_context())
    quote_updates = [update for update in output.field_updates if update.field_key == "Ultima_Cotizacion"]
    quote_sent_updates = [
        update for update in output.field_updates if update.field_key == "Cotizacion_Enviada"
    ]

    assert tools.calls == 1
    assert composer.calls == 2
    assert len(quote_updates) == 1
    assert len(quote_sent_updates) == 1


@pytest.mark.asyncio
async def test_quote_safety_still_blocks_price_without_snapshot() -> None:
    provider = AdvisorFirstAgentProvider(
        advisor_brain=_QuoteAdvisor(),
        tool_layer=_NoToolLayer(),
        composer=_CountingComposer(),
        reliability_config=_config(max_retries=0),
    )

    output = await provider.generate(_context())

    assert "$62,900" not in output.final_message
    assert output.trace_metadata["quote_safety"]["allowed"] is False

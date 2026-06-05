from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from atendia.agent_runtime import (
    ActionRequest,
    AdvisorBrainDecision,
    AdvisorFirstAgentProvider,
    PostTurnActionExecutor,
    ProviderReliabilityConfig,
    ProviderReliabilityLayer,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.canonical import CanonicalProductReference, QuoteSnapshot
from atendia.agent_runtime.provider_reliability import (
    ProviderCircuitOpenError,
    ProviderMalformedJSONError,
    ProviderRetryExhaustedError,
)
from atendia.agent_runtime.schemas import CustomerContext, TenantRuntimeConfigContext
from atendia.agent_runtime.shadow_service import SHADOW_ROUTER_TRIGGER, AgentRuntimeShadowService
from atendia.agent_runtime.state_writer import StateWriteResult
from atendia.config import get_settings
from atendia.contact_memory import ContactMemoryService

pytestmark = pytest.mark.integration_db


class _RateLimitError(Exception):
    status_code = 429


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


class _AlwaysBadAdvisor:
    async def decide(self, context: TurnContext) -> AdvisorBrainDecision:
        del context
        raise ProviderMalformedJSONError("bad advisor json")


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


class _ComposerFailsOnce:
    def __init__(self) -> None:
        self.calls = 0

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
        self.calls += 1
        if self.calls == 1:
            raise ProviderMalformedJSONError("bad composer json")
        return TurnOutput(
            final_message="La R4 queda en $62,900 de contado.",
            confidence=0.9,
            field_updates=list(state_write_result.field_updates),
            lifecycle_update=state_write_result.lifecycle_update,
        )


class _AlwaysFailingProvider:
    async def generate(self, context: TurnContext) -> TurnOutput:
        del context
        raise RuntimeError("shadow provider failed")


class _ActionProvider:
    async def generate(self, context: TurnContext) -> TurnOutput:
        return TurnOutput(
            final_message="Propongo accion.",
            confidence=0.9,
            actions=[
                ActionRequest(
                    name="add_tag",
                    payload={"tag": "shadow"},
                    reason="Shadow proposal.",
                    evidence=[context.inbound_text],
                )
            ],
        )


def _run(coro):
    return asyncio.run(coro)


async def _with_session(fn):
    engine = create_async_engine(get_settings().database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await fn(session)
    finally:
        await engine.dispose()


async def _seed_runtime_turn(session: AsyncSession) -> tuple[str, str, str]:
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    policy = {"contact_memory": {"write_policy": "ai_auto", "confidence_threshold": 0.0}}
    await session.execute(
        text("INSERT INTO tenants (id, name) VALUES (:id, :name)"),
        {"id": tenant_id, "name": f"rc4_idempotency_{uuid4().hex[:8]}"},
    )
    await session.execute(
        text(
            "INSERT INTO customers (id, tenant_id, phone_e164, attrs) "
            "VALUES (:id, :tenant_id, :phone, CAST('{}' AS jsonb))"
        ),
        {"id": customer_id, "tenant_id": tenant_id, "phone": f"+52{uuid4().int % 10**10:010d}"},
    )
    await session.execute(
        text(
            "INSERT INTO conversations (id, tenant_id, customer_id, status, current_stage, tags) "
            "VALUES (:id, :tenant_id, :customer_id, 'active', 'new', CAST('[]' AS jsonb))"
        ),
        {"id": conversation_id, "tenant_id": tenant_id, "customer_id": customer_id},
    )
    await session.execute(
        text(
            "INSERT INTO conversation_state (conversation_id, extracted_data) "
            "VALUES (:id, CAST('{}' AS jsonb))"
        ),
        {"id": conversation_id},
    )
    for index, key in enumerate(("Producto", "Ultima_Cotizacion", "Cotizacion_Enviada")):
        await session.execute(
            text(
                "INSERT INTO customer_field_definitions "
                "(id, tenant_id, key, label, field_type, field_options, ordering) "
                "VALUES (:id, :tenant_id, :key, :label, 'text', "
                "CAST(:options AS jsonb), :ordering)"
            ),
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "key": key,
                "label": key,
                "options": json.dumps(policy),
                "ordering": index,
            },
        )
    await session.commit()
    return str(tenant_id), str(customer_id), str(conversation_id)


async def _seed_shadow_conversation(session: AsyncSession) -> tuple[str, str, str]:
    tenant_id = uuid4()
    customer_id = uuid4()
    conversation_id = uuid4()
    agent_id = uuid4()
    message_id = uuid4()
    rollout = {
        "runtime_v2_enabled": True,
        "shadow_mode_enabled": True,
        "preview_enabled": False,
        "send_enabled": False,
        "actions_enabled": False,
        "workflow_events_enabled": False,
        "model_provider_enabled": False,
        "rollout_mode": "shadow",
    }
    await session.execute(
        text("INSERT INTO tenants (id, name, config) VALUES (:id, :name, CAST(:config AS jsonb))"),
        {
            "id": tenant_id,
            "name": f"rc4_shadow_{uuid4().hex[:8]}",
            "config": json.dumps({"agent_runtime_v2": rollout}),
        },
    )
    await session.execute(
        text(
            "INSERT INTO agents (id, tenant_id, name, status, auto_actions) "
            "VALUES (:id, :tenant_id, 'Shadow Agent', 'production', "
            "CAST('{\"enabled_action_ids\":[\"add_tag\"]}' AS jsonb))"
        ),
        {"id": agent_id, "tenant_id": tenant_id},
    )
    await session.execute(
        text("INSERT INTO customers (id, tenant_id, phone_e164) VALUES (:id, :tenant_id, :phone)"),
        {"id": customer_id, "tenant_id": tenant_id, "phone": f"+52155{uuid4().hex[:8]}"},
    )
    await session.execute(
        text(
            "INSERT INTO conversations "
            "(id, tenant_id, customer_id, assigned_agent_id, channel, tags) "
            "VALUES (:id, :tenant_id, :customer_id, :agent_id, 'whatsapp', CAST('[]' AS jsonb))"
        ),
        {
            "id": conversation_id,
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "agent_id": agent_id,
        },
    )
    await session.execute(
        text(
            "INSERT INTO conversation_state (conversation_id, extracted_data) "
            "VALUES (:id, CAST('{}' AS jsonb))"
        ),
        {"id": conversation_id},
    )
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, tenant_id, direction, text, sent_at) "
            "VALUES (:id, :conversation_id, :tenant_id, 'inbound', 'Hola shadow', now())"
        ),
        {"id": message_id, "conversation_id": conversation_id, "tenant_id": tenant_id},
    )
    await session.commit()
    return str(tenant_id), str(conversation_id), str(message_id)


def _context(tenant_id: str, customer_id: str, conversation_id: str) -> TurnContext:
    return TurnContext(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        inbound_text="Cuanto cuesta la R4?",
        customer=CustomerContext(id=customer_id),
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
        metadata={"message_id": "rc4-message"},
    )


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


async def _counts(session: AsyncSession, tenant_id: str, customer_id: str) -> dict[str, int]:
    params = {"tenant_id": UUID(tenant_id), "customer_id": UUID(customer_id)}
    return {
        "outbox": int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :tenant_id"),
                    params,
                )
            ).scalar_one()
        ),
        "evidence": int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM customer_field_update_evidence "
                        "WHERE tenant_id = :tenant_id AND customer_id = :customer_id"
                    ),
                    params,
                )
            ).scalar_one()
        ),
        "quote_sent_evidence": int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM customer_field_update_evidence "
                        "WHERE tenant_id = :tenant_id AND customer_id = :customer_id "
                        "AND field_key = 'Cotizacion_Enviada'"
                    ),
                    params,
                )
            ).scalar_one()
        ),
        "last_quote_evidence": int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM customer_field_update_evidence "
                        "WHERE tenant_id = :tenant_id AND customer_id = :customer_id "
                        "AND field_key = 'Ultima_Cotizacion'"
                    ),
                    params,
                )
            ).scalar_one()
        ),
    }


async def _field_value(session: AsyncSession, customer_id: str, key: str) -> str | None:
    return (
        await session.execute(
            text(
                "SELECT v.value FROM customer_field_values v "
                "JOIN customer_field_definitions d ON d.id = v.field_definition_id "
                "WHERE v.customer_id = :customer_id AND d.key = :key"
            ),
            {"customer_id": UUID(customer_id), "key": key},
        )
    ).scalar_one_or_none()


async def _shadow_count(session: AsyncSession, tenant_id: str, conversation_id: str) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM turn_traces "
                    "WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id "
                    "AND router_trigger = :router_trigger"
                ),
                {
                    "tenant_id": UUID(tenant_id),
                    "conversation_id": UUID(conversation_id),
                    "router_trigger": SHADOW_ROUTER_TRIGGER,
                },
            )
        ).scalar_one()
    )


def _retry_config(**overrides) -> ProviderReliabilityConfig:
    data = {
        "max_retries": 1,
        "timeout_s": 0.2,
        "base_delay_ms": 0,
        "max_delay_ms": 0,
        "jitter_ms": 0,
        "circuit_failure_threshold": 1,
        "circuit_cooldown_s": 60.0,
    }
    data.update(overrides)
    return ProviderReliabilityConfig(**data)


def test_provider_retry_persists_quote_side_effects_once(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_QUOTE_SAFETY_GUARD_MODE", "block")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    get_settings.cache_clear()

    async def scenario(session: AsyncSession):
        tenant_id, customer_id, conversation_id = await _seed_runtime_turn(session)
        tools = _QuoteToolLayer()
        composer = _ComposerFailsOnce()
        output = await AdvisorFirstAgentProvider(
            advisor_brain=_QuoteAdvisor(),
            tool_layer=tools,
            composer=composer,
            reliability_config=_retry_config(),
        ).generate(_context(tenant_id, customer_id, conversation_id))

        await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            contact_memory_service=ContactMemoryService(session),
            require_runtime_enabled=False,
        ).execute(output, context=_context(tenant_id, customer_id, conversation_id))
        await session.commit()

        counts = await _counts(session, tenant_id, customer_id)
        assert tools.calls == 1
        assert composer.calls == 2
        assert counts == {
            "outbox": 0,
            "evidence": 3,
            "quote_sent_evidence": 1,
            "last_quote_evidence": 1,
        }
        last_quote = json.loads(await _field_value(session, customer_id, "Ultima_Cotizacion"))
        assert last_quote["snapshot_id"] == "quote-r4-cash"
        assert await _field_value(session, customer_id, "Cotizacion_Enviada") == "true"

    _run(_with_session(scenario))
    get_settings.cache_clear()


def test_retry_exhausted_and_safe_fallback_write_no_side_effects(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    get_settings.cache_clear()

    async def scenario(session: AsyncSession):
        tenant_id, customer_id, conversation_id = await _seed_runtime_turn(session)
        output = await AdvisorFirstAgentProvider(
            advisor_brain=_AlwaysBadAdvisor(),
            tool_layer=_QuoteToolLayer(),
            composer=_AlwaysBadComposer(),
            reliability_config=_retry_config(max_retries=1),
        ).generate(_context(tenant_id, customer_id, conversation_id))

        assert output.needs_human is True
        assert output.field_updates == []

        await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            contact_memory_service=ContactMemoryService(session),
            require_runtime_enabled=False,
        ).execute(output, context=_context(tenant_id, customer_id, conversation_id))
        await session.commit()

        counts = await _counts(session, tenant_id, customer_id)
        handoffs = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM human_handoffs WHERE tenant_id = :tenant_id"),
                    {"tenant_id": UUID(tenant_id)},
                )
            ).scalar_one()
        )
        assert counts == {
            "outbox": 0,
            "evidence": 0,
            "quote_sent_evidence": 0,
            "last_quote_evidence": 0,
        }
        assert handoffs == 0

    _run(_with_session(scenario))
    get_settings.cache_clear()


class _AlwaysBadComposer:
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
        raise ProviderMalformedJSONError("bad composer json")


def test_circuit_breaker_open_does_not_execute_side_effects():
    async def scenario(session: AsyncSession):
        tenant_id, customer_id, conversation_id = await _seed_runtime_turn(session)
        layer = ProviderReliabilityLayer(
            provider="openai",
            model="gpt-test",
            tenant_id=tenant_id,
            config=_retry_config(max_retries=0, circuit_failure_threshold=1),
        )

        async def operation() -> TurnOutput:
            raise _RateLimitError("429 Too Many Requests")

        with pytest.raises(ProviderRetryExhaustedError):
            await layer.execute(operation, operation_name="first")
        with pytest.raises(ProviderCircuitOpenError):
            await layer.execute(operation, operation_name="second")

        await PostTurnActionExecutor(
            session=session,
            dry_run=False,
            contact_memory_service=ContactMemoryService(session),
            require_runtime_enabled=False,
        ).execute(
            TurnOutput(final_message="", confidence=0.0),
            context=_context(tenant_id, customer_id, conversation_id),
        )
        await session.commit()

        counts = await _counts(session, tenant_id, customer_id)
        assert counts == {
            "outbox": 0,
            "evidence": 0,
            "quote_sent_evidence": 0,
            "last_quote_evidence": 0,
        }

    _run(_with_session(scenario))


def test_rollout_policy_decision_is_stable_within_turn(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    get_settings.cache_clear()

    async def scenario(session: AsyncSession):
        tenant_id, _customer_id, _conversation_id = await _seed_runtime_turn(session)
        await session.execute(
            text(
                "UPDATE tenants SET config = CAST(:config AS jsonb) WHERE id = :tenant_id"
            ),
            {
                "tenant_id": UUID(tenant_id),
                "config": json.dumps(
                    {
                        "agent_runtime_v2": {
                            "runtime_v2_enabled": True,
                            "send_enabled": True,
                            "rollout_mode": "manual_send",
                        }
                    }
                ),
            },
        )
        await session.commit()
        from atendia.agent_runtime.rollout_policy import RolloutPolicyService

        service = RolloutPolicyService(session)
        decision = await service.can_send(tenant_id=UUID(tenant_id))
        frozen_policy = decision.policy
        await session.execute(
            text(
                "UPDATE tenants SET config = CAST(:config AS jsonb) WHERE id = :tenant_id"
            ),
            {
                "tenant_id": UUID(tenant_id),
                "config": json.dumps(
                    {
                        "agent_runtime_v2": {
                            "runtime_v2_enabled": True,
                            "send_enabled": False,
                            "rollout_mode": "preview",
                        }
                    }
                ),
            },
        )
        await session.commit()

        assert decision.allowed is True
        assert frozen_policy["send_enabled"] is True
        assert frozen_policy["rollout_mode"] == "manual_send"

    _run(_with_session(scenario))
    get_settings.cache_clear()


def test_shadow_service_idempotency_and_no_side_effects(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER", "disabled")
    get_settings.cache_clear()

    async def scenario(session: AsyncSession):
        tenant_id, conversation_id, message_id = await _seed_shadow_conversation(session)
        service = AgentRuntimeShadowService(session, provider=_ActionProvider())
        first = await service.run_shadow_for_inbound(
            tenant_id=UUID(tenant_id),
            conversation_id=UUID(conversation_id),
            inbound_message_id=UUID(message_id),
            inbound_text="Hola shadow",
            legacy_output=["Legacy response"],
        )
        second = await service.run_shadow_for_inbound(
            tenant_id=UUID(tenant_id),
            conversation_id=UUID(conversation_id),
            inbound_message_id=UUID(message_id),
            inbound_text="Hola shadow",
            legacy_output=["Legacy response"],
        )
        await session.commit()

        assert first.status == "shadowed"
        assert second.status == "skipped"
        assert await _shadow_count(session, tenant_id, conversation_id) == 1
        outbox = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :tenant_id"),
                    {"tenant_id": UUID(tenant_id)},
                )
            ).scalar_one()
        )
        action_logs = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM action_execution_logs WHERE tenant_id = :tenant_id"),
                    {"tenant_id": UUID(tenant_id)},
                )
            ).scalar_one()
        )
        assert outbox == 0
        assert action_logs == 0

    _run(_with_session(scenario))
    get_settings.cache_clear()

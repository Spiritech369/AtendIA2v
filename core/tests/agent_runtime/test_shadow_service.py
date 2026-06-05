from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.agent_runtime.schemas import ActionRequest, TurnOutput
from atendia.agent_runtime.shadow_service import SHADOW_ROUTER_TRIGGER, AgentRuntimeShadowService
from atendia.config import get_settings

pytestmark = pytest.mark.integration_db


def _run(coro):
    return asyncio.run(coro)


async def _seed_conversation(*, rollout: dict | None = None, assigned_agent: bool = True):
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            tenant_id = (
                await conn.execute(
                    text(
                        "INSERT INTO tenants (name, config) "
                        "VALUES (:n, CAST(:config AS jsonb)) RETURNING id"
                    ),
                    {
                        "n": f"shadow_{uuid4().hex[:8]}",
                        "config": json.dumps({"agent_runtime_v2": rollout or {}}),
                    },
                )
            ).scalar_one()
            agent_id = None
            if assigned_agent:
                agent_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO agents (tenant_id, name, status, auto_actions) "
                            "VALUES (:t, :n, 'production', "
                            "CAST('{\"enabled_action_ids\":[\"add_tag\"]}' AS jsonb)) "
                            "RETURNING id"
                        ),
                        {"t": tenant_id, "n": "Shadow Agent"},
                    )
                ).scalar_one()
            customer_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) "
                        "VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": tenant_id, "p": f"+52155{uuid4().hex[:8]}"},
                )
            ).scalar_one()
            conversation_id = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations "
                        "(tenant_id, customer_id, assigned_agent_id, channel) "
                        "VALUES (:t, :c, :a, 'whatsapp') RETURNING id"
                    ),
                    {"t": tenant_id, "c": customer_id, "a": agent_id},
                )
            ).scalar_one()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conversation_id},
            )
            message_id = (
                await conn.execute(
                    text(
                        "INSERT INTO messages "
                        "(conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, 'inbound', 'Hola shadow', now()) RETURNING id"
                    ),
                    {"c": conversation_id, "t": tenant_id},
                )
            ).scalar_one()
            return str(tenant_id), str(conversation_id), str(message_id), (
                str(agent_id) if agent_id else None
            )
    finally:
        await engine.dispose()


async def _delete_tenant(tenant_id: str) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    finally:
        await engine.dispose()


async def _run_shadow(
    tenant_id: str,
    conversation_id: str,
    message_id: str,
    *,
    provider=None,
):
    engine = create_async_engine(get_settings().database_url)
    try:
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            result = await AgentRuntimeShadowService(
                session,
                provider=provider,
            ).run_shadow_for_inbound(
                tenant_id=UUID(tenant_id),
                conversation_id=UUID(conversation_id),
                inbound_message_id=UUID(message_id),
                inbound_text="Hola shadow",
                legacy_output=["Legacy response"],
            )
            await session.commit()
            return result
    finally:
        await engine.dispose()


def _count(sql: str, params: dict) -> int:
    async def _inner():
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                return int((await conn.execute(text(sql), params)).scalar() or 0)
        finally:
            await engine.dispose()

    return _run(_inner())


def _shadow_count(tenant_id: str, conversation_id: str) -> int:
    return _count(
        "SELECT COUNT(*) FROM turn_traces "
        "WHERE tenant_id = :t AND conversation_id = :c AND router_trigger = :r",
        {"t": tenant_id, "c": conversation_id, "r": SHADOW_ROUTER_TRIGGER},
    )


def _outbox_count(tenant_id: str) -> int:
    return _count("SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :t", {"t": tenant_id})


class _ActionProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="V2 propone una accion.",
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


class _FailingProvider:
    async def generate(self, context):
        raise RuntimeError("shadow boom")


@pytest.fixture(autouse=True)
def _runtime_enabled(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER", "disabled")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _rollout(**overrides):
    policy = {
        "runtime_v2_enabled": True,
        "shadow_mode_enabled": True,
        "preview_enabled": False,
        "send_enabled": False,
        "actions_enabled": False,
        "workflow_events_enabled": False,
        "model_provider_enabled": False,
        "rollout_mode": "shadow",
    }
    policy.update(overrides)
    return policy


def test_shadow_se_ejecuta_cuando_policy_permite():
    tenant_id, conversation_id, message_id, _agent_id = _run(
        _seed_conversation(rollout=_rollout())
    )
    try:
        result = _run(_run_shadow(tenant_id, conversation_id, message_id))
        assert result.status == "shadowed"
        assert _shadow_count(tenant_id, conversation_id) == 1
    finally:
        _run(_delete_tenant(tenant_id))


def test_shadow_no_se_ejecuta_si_policy_disabled():
    tenant_id, conversation_id, message_id, _agent_id = _run(
        _seed_conversation(rollout={"rollout_mode": "disabled"})
    )
    try:
        result = _run(_run_shadow(tenant_id, conversation_id, message_id))
        assert result.status == "skipped"
        assert _shadow_count(tenant_id, conversation_id) == 0
    finally:
        _run(_delete_tenant(tenant_id))


def test_shadow_no_modifica_datos_ni_outbox_y_no_ejecuta_actions():
    tenant_id, conversation_id, message_id, _agent_id = _run(
        _seed_conversation(rollout=_rollout())
    )
    before_outbox = _outbox_count(tenant_id)
    try:
        result = _run(
            _run_shadow(
                tenant_id,
                conversation_id,
                message_id,
                provider=_ActionProvider(),
            )
        )
        assert result.status == "shadowed"
        assert _outbox_count(tenant_id) == before_outbox
        assert _shadow_count(tenant_id, conversation_id) == 1
    finally:
        _run(_delete_tenant(tenant_id))


def test_shadow_failure_no_rompe_y_guarda_trace():
    tenant_id, conversation_id, message_id, _agent_id = _run(
        _seed_conversation(rollout=_rollout())
    )
    try:
        result = _run(
            _run_shadow(
                tenant_id,
                conversation_id,
                message_id,
                provider=_FailingProvider(),
            )
        )
        assert result.status == "failed"
        assert _shadow_count(tenant_id, conversation_id) == 1
    finally:
        _run(_delete_tenant(tenant_id))


def test_shadow_idempotencia_evita_duplicados():
    tenant_id, conversation_id, message_id, _agent_id = _run(
        _seed_conversation(rollout=_rollout())
    )
    try:
        first = _run(_run_shadow(tenant_id, conversation_id, message_id))
        second = _run(_run_shadow(tenant_id, conversation_id, message_id))
        assert first.status == "shadowed"
        assert second.status == "skipped"
        assert _shadow_count(tenant_id, conversation_id) == 1
    finally:
        _run(_delete_tenant(tenant_id))


def test_shadow_tenant_isolation():
    tenant_id, conversation_id, message_id, _agent_id = _run(
        _seed_conversation(rollout=_rollout())
    )
    other_tenant_id, _other_conversation_id, _other_message_id, _other_agent_id = _run(
        _seed_conversation(rollout=_rollout())
    )
    try:
        result = _run(_run_shadow(other_tenant_id, conversation_id, message_id))
        assert result.status == "skipped"
        assert _shadow_count(tenant_id, conversation_id) == 0
    finally:
        _run(_delete_tenant(tenant_id))
        _run(_delete_tenant(other_tenant_id))

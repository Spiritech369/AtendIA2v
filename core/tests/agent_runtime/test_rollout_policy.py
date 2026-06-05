from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.agent_runtime.rollout_policy import RolloutPolicyService
from atendia.config import get_settings

pytestmark = pytest.mark.integration_db


def _run(coro):
    return asyncio.run(coro)


async def _create_tenant(config: dict | None = None) -> str:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            return str(
                (
                    await conn.execute(
                        text(
                            "INSERT INTO tenants (name, config) "
                            "VALUES (:n, CAST(:config AS jsonb)) RETURNING id"
                        ),
                        {
                            "n": f"rollout_policy_{uuid4().hex[:8]}",
                            "config": json.dumps(config or {}),
                        },
                    )
                ).scalar_one()
            )
    finally:
        await engine.dispose()


async def _create_agent(tenant_id: str) -> str:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            return str(
                (
                    await conn.execute(
                        text(
                            "INSERT INTO agents (tenant_id, name, status) "
                            "VALUES (:t, :n, 'production') RETURNING id"
                        ),
                        {"t": tenant_id, "n": f"rollout_agent_{uuid4().hex[:8]}"},
                    )
                ).scalar_one()
            )
    finally:
        await engine.dispose()


async def _insert_readiness_result(
    tenant_id: str,
    agent_id: str,
    *,
    score: float = 1.0,
    passed: bool = True,
) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO agent_readiness_eval_results "
                    "(id, tenant_id, agent_id, suite_id, score, passed, scenario_count, "
                    "failed_scenarios, policy_failures, metadata) "
                    "VALUES (:id, :t, :a, 'agent_runtime_v2_minimum_readiness', "
                    ":score, :passed, 1, CAST('[]' AS jsonb), CAST('[]' AS jsonb), "
                    "CAST('{}' AS jsonb))"
                ),
                {
                    "id": str(uuid4()),
                    "t": tenant_id,
                    "a": agent_id,
                    "score": score,
                    "passed": passed,
                },
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


async def _decision(tenant_id: str, method: str, **kwargs):
    engine = create_async_engine(get_settings().database_url)
    try:
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            service = RolloutPolicyService(session)
            return await getattr(service, method)(tenant_id=UUID(tenant_id), **kwargs)
    finally:
        await engine.dispose()


def _policy(**overrides) -> dict:
    policy = {
        "runtime_v2_enabled": True,
        "shadow_mode_enabled": True,
        "preview_enabled": True,
        "send_enabled": True,
        "actions_enabled": True,
        "workflow_events_enabled": True,
        "model_provider_enabled": True,
        "rollout_mode": "manual_send",
        "metadata": {"eval_suite_passed": True, "eval_score": 1.0},
    }
    policy.update(overrides)
    return {"agent_runtime_v2": policy}


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_tenant_enabled_and_tenant_disabled_are_isolated(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    tenant_a = _run(_create_tenant(_policy(rollout_mode="preview", send_enabled=False)))
    tenant_b = _run(_create_tenant({}))
    try:
        allowed = _run(_decision(tenant_a, "can_preview"))
        blocked = _run(_decision(tenant_b, "can_preview"))
    finally:
        _run(_delete_tenant(tenant_a))
        _run(_delete_tenant(tenant_b))

    assert allowed.allowed is True
    assert blocked.allowed is False
    assert "tenant runtime_v2_enabled is false" in blocked.reasons


def test_global_flag_blocks_even_when_tenant_is_enabled(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "false")
    tenant_id = _run(_create_tenant(_policy(rollout_mode="preview", send_enabled=False)))
    try:
        decision = _run(_decision(tenant_id, "can_preview"))
    finally:
        _run(_delete_tenant(tenant_id))

    assert decision.allowed is False
    assert "global flag blocks preview" in decision.reasons


def test_send_blocks_until_required_eval_passes(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    tenant_id = _run(
        _create_tenant(
            _policy(
                required_eval_suite_passed=True,
                min_eval_score=0.9,
                metadata={"eval_suite_passed": False, "eval_score": 0.8},
            )
        )
    )
    try:
        decision = _run(_decision(tenant_id, "can_send"))
    finally:
        _run(_delete_tenant(tenant_id))

    assert decision.allowed is False
    assert "conversation has no assigned agent" in decision.reasons


def test_preview_can_be_allowed_while_send_is_blocked(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    tenant_id = _run(
        _create_tenant(_policy(rollout_mode="preview", send_enabled=False))
    )
    try:
        preview = _run(_decision(tenant_id, "can_preview"))
        send = _run(_decision(tenant_id, "can_send"))
    finally:
        _run(_delete_tenant(tenant_id))

    assert preview.allowed is True
    assert send.allowed is False
    assert "tenant send is false" in send.reasons


def test_preview_only_rollout_allows_preview_and_blocks_send(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    tenant_id = _run(
        _create_tenant(_policy(rollout_mode="preview_only", send_enabled=False))
    )
    try:
        preview = _run(_decision(tenant_id, "can_preview"))
        send = _run(_decision(tenant_id, "can_send"))
    finally:
        _run(_delete_tenant(tenant_id))

    assert preview.allowed is True
    assert preview.policy["rollout_mode"] == "preview_only"
    assert send.allowed is False
    assert "tenant send is false" in send.reasons


def test_send_allowed_after_readiness_passes(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "true")
    tenant_id = _run(
        _create_tenant(
            _policy(
                required_eval_suite_passed=True,
                min_eval_score=0.9,
                metadata={"eval_suite_passed": False, "eval_score": 0.0},
            )
        )
    )
    agent_id = _run(_create_agent(tenant_id))
    _run(_insert_readiness_result(tenant_id, agent_id, score=0.95, passed=True))
    try:
        send = _run(_decision(tenant_id, "can_send", agent_id=agent_id))
    finally:
        _run(_delete_tenant(tenant_id))

    assert send.allowed is True
    assert "latest readiness result passed" in send.reasons
    assert send.policy["readiness"]["result"]["agent_id"] == agent_id


def test_model_provider_requires_tenant_enablement(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER", "openai")
    tenant_id = _run(_create_tenant(_policy(model_provider_enabled=False)))
    try:
        decision = _run(_decision(tenant_id, "can_use_model_provider"))
    finally:
        _run(_delete_tenant(tenant_id))

    assert decision.allowed is False
    assert "tenant model_provider is false" in decision.reasons


def test_explain_decision_returns_clear_reasons(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    tenant_id = _run(_create_tenant(_policy(allowed_agent_ids=[str(uuid4())])))
    try:
        decision = _run(_decision(tenant_id, "can_preview", agent_id=uuid4()))
    finally:
        _run(_delete_tenant(tenant_id))

    dumped = decision.model_dump(mode="json")
    assert dumped["allowed"] is False
    assert "agent_id is not allowed by tenant rollout policy" in dumped["reasons"]

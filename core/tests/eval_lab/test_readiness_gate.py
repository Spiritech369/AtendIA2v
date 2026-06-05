from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.agent_runtime.schemas import ActionRequest, FieldUpdate, LifecycleUpdate, TurnOutput
from atendia.config import get_settings
from atendia.eval_lab.readiness import ReadinessService


def _run(coro):
    return asyncio.run(coro)


async def _seed_tenant_agent() -> tuple[str, str]:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            tenant_id = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"readiness_{uuid4().hex[:8]}"},
                )
            ).scalar_one()
            agent_id = (
                await conn.execute(
                    text(
                        "INSERT INTO agents (tenant_id, name, status) "
                        "VALUES (:t, :n, 'production') RETURNING id"
                    ),
                    {"t": tenant_id, "n": "Readiness Agent"},
                )
            ).scalar_one()
            return str(tenant_id), str(agent_id)
    finally:
        await engine.dispose()


async def _delete_tenant(tenant_id: str) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    finally:
        await engine.dispose()


async def _run_suite(tenant_id: str, agent_id: str, provider=None):
    engine = create_async_engine(get_settings().database_url)
    try:
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            row = await ReadinessService(session).run_readiness_suite(
                tenant_id=UUID(tenant_id),
                agent_id=UUID(agent_id),
                provider=provider,
            )
            payload = {
                "id": str(row.id),
                "passed": row.passed,
                "score": float(row.score),
                "scenario_count": row.scenario_count,
                "failed_scenarios": row.failed_scenarios,
                "policy_failures": row.policy_failures,
            }
            await session.commit()
            return payload
    finally:
        await engine.dispose()


class _UnknownActionProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            actions=[
                ActionRequest(
                    name="not_registered",
                    reason="Bad action.",
                    evidence=[context.inbound_text],
                )
            ],
        )


class _BadLifecycleProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            lifecycle_update=LifecycleUpdate(target_stage="next"),
        )


class _BadFieldProvider:
    async def generate(self, context):
        return TurnOutput(
            final_message="Listo.",
            confidence=0.9,
            field_updates=[FieldUpdate(field_key="budget", value="5000")],
        )


@pytest.fixture(autouse=True)
def _runtime_flags(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_readiness_pasa_con_escenarios_validos():
    tenant_id, agent_id = _run(_seed_tenant_agent())
    try:
        result = _run(_run_suite(tenant_id, agent_id))
    finally:
        _run(_delete_tenant(tenant_id))

    assert result["passed"] is True
    assert result["score"] == 1.0
    assert result["scenario_count"] >= 8


def test_readiness_falla_si_hay_unknown_action():
    tenant_id, agent_id = _run(_seed_tenant_agent())
    try:
        result = _run(_run_suite(tenant_id, agent_id, provider=_UnknownActionProvider()))
    finally:
        _run(_delete_tenant(tenant_id))

    assert result["passed"] is False
    assert result["score"] == 0.0
    assert result["policy_failures"]


def test_readiness_falla_si_lifecycle_no_tiene_reason():
    tenant_id, agent_id = _run(_seed_tenant_agent())
    try:
        result = _run(_run_suite(tenant_id, agent_id, provider=_BadLifecycleProvider()))
    finally:
        _run(_delete_tenant(tenant_id))

    assert result["passed"] is False
    assert any(
        failure["scorer"] == "runtime_exception" or "lifecycle" in failure["scorer"]
        for failure in result["policy_failures"]
    )


def test_readiness_falla_si_field_update_no_tiene_evidence():
    tenant_id, agent_id = _run(_seed_tenant_agent())
    try:
        result = _run(_run_suite(tenant_id, agent_id, provider=_BadFieldProvider()))
    finally:
        _run(_delete_tenant(tenant_id))

    assert result["passed"] is False
    assert result["policy_failures"]

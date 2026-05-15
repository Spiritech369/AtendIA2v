"""Phase 4 T42-T44 — analytics smokes."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings
from atendia.main import app


def _seed() -> tuple[str, str, str]:
    email = f"phase4_t42_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"phase4_t42_{uuid4().hex[:8]}"},
                )
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, 'operator', :h)"
                ),
                {"t": tid, "e": email, "h": hashed},
            )
        await engine.dispose()
        return str(tid)

    return asyncio.run(_do()), email, plain


@pytest.fixture
def operator_seed() -> Iterator[tuple[str, str, str]]:
    seed = _seed()
    yield seed

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": seed[0]})
        await engine.dispose()

    asyncio.run(_do())


def _login(client: TestClient, email: str, plain: str) -> None:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert resp.status_code == 200


def test_funnel_empty_tenant(operator_seed):
    _, email, plain = operator_seed
    client = TestClient(app)
    _login(client, email, plain)
    resp = client.get("/api/v1/analytics/funnel")
    assert resp.status_code == 200
    assert resp.json() == {
        "total_conversations": 0,
        "quoted": 0,
        "plan_assigned": 0,
        "papeleria_completa": 0,
    }


def test_cost_empty_tenant(operator_seed):
    _, email, plain = operator_seed
    client = TestClient(app)
    _login(client, email, plain)
    resp = client.get("/api/v1/analytics/cost")
    assert resp.status_code == 200
    assert resp.json() == {"points": []}


def test_volume_empty_tenant_returns_24_zero_buckets(operator_seed):
    _, email, plain = operator_seed
    client = TestClient(app)
    _login(client, email, plain)
    resp = client.get("/api/v1/analytics/volume")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["buckets"]) == 24
    assert body["buckets"][0] == {"hour": 0, "inbound": 0, "outbound": 0}


def test_analytics_unauthenticated_401():
    client = TestClient(app)
    assert client.get("/api/v1/analytics/funnel").status_code == 401

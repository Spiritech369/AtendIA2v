"""Phase 4 T28-T30 — tenant config GET/PUT (pipeline, brand_facts, tone)."""
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


def _seed(role: str = "tenant_admin") -> tuple[str, str, str, str]:
    email = f"phase4_t28_{role}_{uuid4().hex[:8]}@dinamo.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"phase4_t28_{uuid4().hex[:8]}"},
                )
            ).scalar()
            uid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                        "VALUES (:t, :e, :r, :h) RETURNING id"
                    ),
                    {"t": tid, "e": email, "r": role, "h": hashed},
                )
            ).scalar()
        await engine.dispose()
        return str(tid), str(uid)

    tid, uid = asyncio.run(_do())
    return tid, uid, email, plain


def _cleanup(tid: str) -> None:
    async def _do():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        await engine.dispose()

    asyncio.run(_do())


@pytest.fixture
def operator_seed_local() -> Iterator[tuple[str, str, str, str]]:
    seed = _seed()
    yield seed
    _cleanup(seed[0])


@pytest.fixture
def plain_operator_seed_local() -> Iterator[tuple[str, str, str, str]]:
    seed = _seed("operator")
    yield seed
    _cleanup(seed[0])


def _login(client: TestClient, email: str, plain: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": plain})
    assert resp.status_code == 200
    return resp.json()["csrf_token"]


def test_get_pipeline_404_when_none(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    _login(client, email, plain)
    resp = client.get("/api/v1/tenants/pipeline")
    assert resp.status_code == 404


def test_put_pipeline_creates_v1_then_v2_keeps_history(operator_seed_local):
    tid, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)

    v1 = {"version": 1, "stages": [{"id": "qualify"}]}
    r1 = client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": v1},
        headers={"X-CSRF-Token": csrf},
    )
    assert r1.status_code == 200
    assert r1.json()["version"] == 1
    assert r1.json()["definition"] == v1
    assert r1.json()["active"] is True

    v2 = {"version": 1, "stages": [{"id": "qualify"}, {"id": "quote"}]}
    r2 = client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": v2},
        headers={"X-CSRF-Token": csrf},
    )
    assert r2.status_code == 200
    assert r2.json()["version"] == 2

    # GET returns the latest active version
    cur = client.get("/api/v1/tenants/pipeline").json()
    assert cur["version"] == 2
    assert cur["definition"] == v2

    # History preserved — v1 row should still be queryable.
    async def _count():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            n = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM tenant_pipelines WHERE tenant_id = :t"),
                    {"t": tid},
                )
            ).scalar()
            active_n = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM tenant_pipelines "
                        "WHERE tenant_id = :t AND active = true"
                    ),
                    {"t": tid},
                )
            ).scalar()
        await engine.dispose()
        return n, active_n

    total, active = asyncio.run(_count())
    assert total == 2
    assert active == 1  # only v2 is active


def test_operator_cannot_put_pipeline(plain_operator_seed_local):
    _, _, email, plain = plain_operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)

    resp = client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": {"version": 1, "stages": [{"id": "qualify"}]}},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 403


def test_brand_facts_round_trip(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)

    # GET on empty tenant returns {}
    initial = client.get("/api/v1/tenants/brand-facts").json()
    assert initial["brand_facts"] == {}

    facts = {"catalog_url": "https://dinamo.test/cat", "address": "Av. Reforma 100"}
    r = client.put(
        "/api/v1/tenants/brand-facts",
        json={"brand_facts": facts},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200
    assert r.json()["brand_facts"] == facts

    # GET reflects PUT
    g = client.get("/api/v1/tenants/brand-facts").json()
    assert g["brand_facts"] == facts


def test_tone_round_trip(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)

    voice = {"register": "informal_mexicano", "energy": "high"}
    r = client.put(
        "/api/v1/tenants/tone",
        json={"voice": voice},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200
    assert r.json()["voice"] == voice

    g = client.get("/api/v1/tenants/tone").json()
    assert g["voice"] == voice


def test_operator_cannot_put_brand_facts_or_tone(plain_operator_seed_local):
    _, _, email, plain = plain_operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)

    facts = client.put(
        "/api/v1/tenants/brand-facts",
        json={"brand_facts": {"address": "Nope"}},
        headers={"X-CSRF-Token": csrf},
    )
    tone = client.put(
        "/api/v1/tenants/tone",
        json={"voice": {"register": "formal"}},
        headers={"X-CSRF-Token": csrf},
    )
    assert facts.status_code == 403
    assert tone.status_code == 403


def test_brand_facts_tenant_scoped(operator_seed_local):
    """Operator A writes facts. Operator B in another tenant gets empty."""
    other_seed = _seed()
    try:
        _, _, email_a, plain_a = operator_seed_local
        client_a = TestClient(app)
        csrf_a = _login(client_a, email_a, plain_a)
        client_a.put(
            "/api/v1/tenants/brand-facts",
            json={"brand_facts": {"address": "Tenant A street"}},
            headers={"X-CSRF-Token": csrf_a},
        )

        _, _, email_b, plain_b = other_seed
        client_b = TestClient(app)
        _login(client_b, email_b, plain_b)
        b_facts = client_b.get("/api/v1/tenants/brand-facts").json()["brand_facts"]
        assert b_facts == {}  # NOT Tenant A's
    finally:
        _cleanup(other_seed[0])


def test_unauthenticated_returns_401():
    client = TestClient(app)
    assert client.get("/api/v1/tenants/pipeline").status_code == 401

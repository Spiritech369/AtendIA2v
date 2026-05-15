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


def test_put_pipeline_stores_history_snapshots(operator_seed_local):
    """Single-row-per-tenant + JSONB history. Each PUT prepends a fresh
    entry to `tenant_pipelines.history` (capped at 10). Row count stays
    at 1; history accumulates newest-first."""
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
    assert r1.json()["definition"] == v1
    assert r1.json()["active"] is True

    v2 = {"version": 1, "stages": [{"id": "qualify"}, {"id": "quote"}]}
    r2 = client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": v2},
        headers={"X-CSRF-Token": csrf},
    )
    assert r2.status_code == 200

    cur = client.get("/api/v1/tenants/pipeline").json()
    assert cur["definition"] == v2

    async def _state():
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            row_count = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM tenant_pipelines WHERE tenant_id = :t"),
                    {"t": tid},
                )
            ).scalar()
            history_len = (
                await conn.execute(
                    text(
                        "SELECT jsonb_array_length(history) FROM tenant_pipelines "
                        "WHERE tenant_id = :t"
                    ),
                    {"t": tid},
                )
            ).scalar()
        await engine.dispose()
        return row_count, history_len

    rows, hist = asyncio.run(_state())
    assert rows == 1  # single-row-per-tenant policy
    assert hist == 2  # both v1 and v2 captured as history entries


def test_pipeline_versions_list_endpoint(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)

    for i, defn in enumerate(
        [
            {"version": 1, "stages": [{"id": "a"}]},
            {"version": 1, "stages": [{"id": "a"}, {"id": "b"}]},
            {"version": 1, "stages": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
        ],
        start=1,
    ):
        r = client.put(
            "/api/v1/tenants/pipeline",
            json={"definition": defn},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200, f"PUT {i} failed: {r.text}"

    resp = client.get("/api/v1/tenants/pipeline/versions")
    assert resp.status_code == 200, resp.text
    versions = resp.json()
    assert len(versions) == 3
    # Newest first; indices strictly decreasing.
    assert versions[0]["is_current"] is True
    assert versions[0]["stage_count"] == 3
    assert versions[1]["stage_count"] == 2
    assert versions[2]["stage_count"] == 1
    assert versions[0]["index"] > versions[1]["index"] > versions[2]["index"]


def test_pipeline_version_detail_endpoint(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)

    v1 = {"version": 1, "stages": [{"id": "x"}]}
    client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": v1},
        headers={"X-CSRF-Token": csrf},
    )
    v2 = {"version": 1, "stages": [{"id": "x"}, {"id": "y"}]}
    client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": v2},
        headers={"X-CSRF-Token": csrf},
    )

    versions = client.get("/api/v1/tenants/pipeline/versions").json()
    older_index = versions[1]["index"]
    detail = client.get(f"/api/v1/tenants/pipeline/versions/{older_index}").json()
    assert detail["definition"] == v1
    assert detail["is_current"] is False


def test_pipeline_version_detail_404_for_missing(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)
    client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": {"stages": []}},
        headers={"X-CSRF-Token": csrf},
    )
    resp = client.get("/api/v1/tenants/pipeline/versions/9999")
    assert resp.status_code == 404


def test_pipeline_rollback_restores_older_definition(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)

    v1 = {"version": 1, "stages": [{"id": "alpha"}]}
    v2 = {"version": 1, "stages": [{"id": "alpha"}, {"id": "beta"}]}
    v3 = {"version": 1, "stages": [{"id": "alpha"}, {"id": "beta"}, {"id": "gamma"}]}
    for defn in (v1, v2, v3):
        client.put(
            "/api/v1/tenants/pipeline",
            json={"definition": defn},
            headers={"X-CSRF-Token": csrf},
        )

    versions = client.get("/api/v1/tenants/pipeline/versions").json()
    v1_index = versions[2]["index"]
    rollback = client.post(
        "/api/v1/tenants/pipeline/rollback",
        json={"index": v1_index},
        headers={"X-CSRF-Token": csrf},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["definition"] == v1

    # The live pipeline now matches v1, and history grew by one entry.
    current = client.get("/api/v1/tenants/pipeline").json()
    assert current["definition"] == v1
    versions_after = client.get("/api/v1/tenants/pipeline/versions").json()
    assert versions_after[0]["is_current"] is True
    assert len(versions_after) == 4  # original 3 + the rollback snapshot


def test_pipeline_rollback_to_current_is_409(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)
    client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": {"stages": [{"id": "a"}]}},
        headers={"X-CSRF-Token": csrf},
    )
    versions = client.get("/api/v1/tenants/pipeline/versions").json()
    current_index = versions[0]["index"]
    resp = client.post(
        "/api/v1/tenants/pipeline/rollback",
        json={"index": current_index},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 409


def test_pipeline_rollback_404_for_missing_index(operator_seed_local):
    _, _, email, plain = operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)
    client.put(
        "/api/v1/tenants/pipeline",
        json={"definition": {"stages": []}},
        headers={"X-CSRF-Token": csrf},
    )
    resp = client.post(
        "/api/v1/tenants/pipeline/rollback",
        json={"index": 9999},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 404


def test_pipeline_rollback_forbidden_for_operator(plain_operator_seed_local):
    _, _, email, plain = plain_operator_seed_local
    client = TestClient(app)
    csrf = _login(client, email, plain)
    resp = client.post(
        "/api/v1/tenants/pipeline/rollback",
        json={"index": 1},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 403


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

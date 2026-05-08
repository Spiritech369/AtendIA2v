"""Step 1 — customer notes CRUD: tenant scoping, CSRF, full lifecycle."""
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


def _seed() -> tuple[str, str, str, str, str]:
    """Create tenant + operator + customer. Returns (tid, uid, cust_id, email, pwd)."""
    email = f"notes_{uuid4().hex[:8]}@test.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"notes_tenant_{uuid4().hex[:8]}"},
                )
            ).scalar()
            uid = (
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                        "VALUES (:t, :e, 'operator', :h) RETURNING id"
                    ),
                    {"t": tid, "e": email, "h": hashed},
                )
            ).scalar()
            cust_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, name) "
                        "VALUES (:t, :p, 'Test Customer') RETURNING id"
                    ),
                    {"t": tid, "p": f"+5215550000{uuid4().hex[:4]}"[:24]},
                )
            ).scalar()
        await engine.dispose()
        return str(tid), str(uid), str(cust_id)

    tid, uid, cust_id = asyncio.run(_do())
    return tid, uid, cust_id, email, plain


def _cleanup(tid: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        await engine.dispose()

    asyncio.run(_do())


@pytest.fixture
def seed() -> Iterator[tuple[str, str, str, str, str]]:
    s = _seed()
    yield s
    _cleanup(s[0])


@pytest.fixture
def two_tenants() -> Iterator[tuple[tuple, tuple]]:
    a = _seed()
    b = _seed()
    yield a, b
    _cleanup(a[0])
    _cleanup(b[0])


def _login(client: TestClient, email: str, password: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]


def test_create_note(seed):
    tid, uid, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.post(
        f"/api/v1/customers/{cust_id}/notes",
        json={"content": "Primera nota", "pinned": False},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["content"] == "Primera nota"
    assert body["pinned"] is False
    assert body["tenant_id"] == tid
    assert body["author_user_id"] == uid
    assert body["customer_id"] == cust_id


def test_list_notes_pinned_first(seed):
    tid, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    c.post(f"/api/v1/customers/{cust_id}/notes", json={"content": "A"})
    c.post(f"/api/v1/customers/{cust_id}/notes", json={"content": "B", "pinned": True})
    c.post(f"/api/v1/customers/{cust_id}/notes", json={"content": "C"})

    resp = c.get(f"/api/v1/customers/{cust_id}/notes")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 3
    assert items[0]["content"] == "B"
    assert items[0]["pinned"] is True


def test_update_note(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    create = c.post(
        f"/api/v1/customers/{cust_id}/notes", json={"content": "original"}
    )
    note_id = create.json()["id"]

    resp = c.patch(
        f"/api/v1/customers/{cust_id}/notes/{note_id}",
        json={"content": "updated", "pinned": True},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "updated"
    assert resp.json()["pinned"] is True


def test_delete_note(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    create = c.post(
        f"/api/v1/customers/{cust_id}/notes", json={"content": "to delete"}
    )
    note_id = create.json()["id"]

    resp = c.delete(f"/api/v1/customers/{cust_id}/notes/{note_id}")
    assert resp.status_code == 204

    listing = c.get(f"/api/v1/customers/{cust_id}/notes")
    assert len(listing.json()) == 0


def test_tenant_isolation(two_tenants):
    (tid_a, _, cust_a, email_a, plain_a), (tid_b, _, cust_b, email_b, plain_b) = two_tenants

    ca = TestClient(app)
    csrf_a = _login(ca, email_a, plain_a)
    ca.headers["X-CSRF-Token"] = csrf_a
    ca.post(f"/api/v1/customers/{cust_a}/notes", json={"content": "tenant A note"})

    cb = TestClient(app)
    csrf_b = _login(cb, email_b, plain_b)
    cb.headers["X-CSRF-Token"] = csrf_b
    cb.post(f"/api/v1/customers/{cust_b}/notes", json={"content": "tenant B note"})

    resp_a = ca.get(f"/api/v1/customers/{cust_a}/notes")
    assert len(resp_a.json()) == 1
    assert resp_a.json()[0]["content"] == "tenant A note"

    # Tenant A cannot see tenant B's customer
    resp_cross = ca.get(f"/api/v1/customers/{cust_b}/notes")
    assert resp_cross.status_code == 404


def test_csrf_required_on_post(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    _login(c, email, plain)
    # No CSRF header set

    resp = c.post(
        f"/api/v1/customers/{cust_id}/notes", json={"content": "should fail"}
    )
    assert resp.status_code == 403


def test_unauthenticated_returns_401(seed):
    _, _, cust_id, _, _ = seed
    c = TestClient(app)
    resp = c.get(f"/api/v1/customers/{cust_id}/notes")
    assert resp.status_code == 401


def test_note_for_nonexistent_customer(seed):
    _, _, _, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    fake_id = str(uuid4())
    resp = c.get(f"/api/v1/customers/{fake_id}/notes")
    assert resp.status_code == 404


def test_delete_nonexistent_note(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.delete(f"/api/v1/customers/{cust_id}/notes/{uuid4()}")
    assert resp.status_code == 404

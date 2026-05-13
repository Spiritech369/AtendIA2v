"""Step 1 — PATCH /customers/:id: basic info edit with tenant scoping + CSRF."""
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
    email = f"patch_{uuid4().hex[:8]}@test.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"patch_tenant_{uuid4().hex[:8]}"},
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
                        "VALUES (:t, :p, 'Original Name') RETURNING id"
                    ),
                    {"t": tid, "p": f"+5215552000{uuid4().hex[:4]}"[:24]},
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


def test_patch_name(seed):
    tid, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.patch(
        f"/api/v1/customers/{cust_id}",
        json={"name": "Updated Name"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Updated Name"
    assert body["id"] == cust_id
    assert body["tenant_id"] == tid


def test_patch_attrs(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.patch(
        f"/api/v1/customers/{cust_id}",
        json={"attrs": {"source": "facebook", "vip": True}},
    )
    assert resp.status_code == 200
    assert resp.json()["attrs"]["source"] == "facebook"
    assert resp.json()["attrs"]["vip"] is True


def test_patch_empty_body_returns_400(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.patch(f"/api/v1/customers/{cust_id}", json={})
    assert resp.status_code == 400


def test_patch_nonexistent_customer_returns_404(seed):
    _, _, _, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.patch(f"/api/v1/customers/{uuid4()}", json={"name": "Ghost"})
    assert resp.status_code == 404


def test_patch_tenant_isolation(two_tenants):
    (_, _, cust_a, email_a, plain_a), (_, _, cust_b, email_b, plain_b) = two_tenants

    ca = TestClient(app)
    csrf_a = _login(ca, email_a, plain_a)
    ca.headers["X-CSRF-Token"] = csrf_a

    resp = ca.patch(f"/api/v1/customers/{cust_b}", json={"name": "Hacked"})
    assert resp.status_code == 404


def test_patch_csrf_required(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    _login(c, email, plain)

    resp = c.patch(f"/api/v1/customers/{cust_id}", json={"name": "No CSRF"})
    assert resp.status_code == 403


def test_patch_unauthenticated_returns_403_or_401(seed):
    """Unauthenticated PATCH — CSRF middleware fires before auth, so 403."""
    _, _, cust_id, _, _ = seed
    c = TestClient(app)
    resp = c.patch(f"/api/v1/customers/{cust_id}", json={"name": "Anon"})
    assert resp.status_code in (401, 403)


def test_patch_preserves_phone(seed):
    """PATCH should not allow changing phone_e164 — it's not in CustomerPatch."""
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    c.patch(f"/api/v1/customers/{cust_id}", json={"name": "New Name"})
    detail = c.get(f"/api/v1/customers/{cust_id}").json()
    assert detail["phone_e164"].startswith("+521555")


def test_patch_customer_attrs_replaces_whole_dict(seed):
    """PATCH /customers/:id with `attrs` REPLACES the dict entirely — keys not
    in the payload are dropped.

    Frontend hooks (useCustomerAttrs) MUST read-modify-write to update a
    single key without losing the rest. This test documents the contract.
    """
    tid, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    # Seed initial attrs via PATCH (so we don't bypass the route under test).
    resp = c.patch(
        f"/api/v1/customers/{cust_id}",
        json={"attrs": {"foo": "1", "bar": "2"}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["attrs"] == {"foo": "1", "bar": "2"}

    # PATCH with only foo=99 → expect bar to be dropped (full overwrite).
    resp = c.patch(
        f"/api/v1/customers/{cust_id}",
        json={"attrs": {"foo": "99"}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["attrs"] == {"foo": "99"}, (
        "Backend replaces the whole attrs dict on PATCH; "
        "frontend hooks must merge client-side."
    )

    # PATCH with empty attrs → result is empty dict.
    resp = c.patch(
        f"/api/v1/customers/{cust_id}",
        json={"attrs": {}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["attrs"] == {}

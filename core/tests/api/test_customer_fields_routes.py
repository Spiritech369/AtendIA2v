"""Step 1 — customer field definitions + values: tenant scoping, CSRF, lifecycle."""
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


def _seed(role: str = "tenant_admin") -> tuple[str, str, str, str, str]:
    """Create tenant + user + customer. Returns (tid, uid, cust_id, email, pwd)."""
    email = f"fields_{role}_{uuid4().hex[:8]}@test.com"
    plain = "test-password-123"
    hashed = hash_password(plain)

    async def _do() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"fields_tenant_{uuid4().hex[:8]}"},
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
            cust_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, name) "
                        "VALUES (:t, :p, 'Fields Customer') RETURNING id"
                    ),
                    {"t": tid, "p": f"+5215551000{uuid4().hex[:4]}"[:24]},
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


# ── Definition tests ─────────────────────────────────────────────────


def test_create_definition(seed):
    tid, _, _, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.post(
        "/api/v1/customer-fields/definitions",
        json={
            "key": "company_size",
            "label": "Company Size",
            "field_type": "select",
            "field_options": {"choices": ["small", "medium", "large"]},
            "ordering": 1,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["key"] == "company_size"
    assert body["field_type"] == "select"
    assert body["tenant_id"] == tid
    assert body["ordering"] == 1


def test_create_definition_rejects_unknown_field_type(seed):
    _, _, _, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "bad_field", "label": "Bad", "field_type": "potato"},
    )
    assert resp.status_code == 422


def test_list_definitions_ordered(seed):
    _, _, _, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "b_field", "label": "B", "field_type": "text", "ordering": 2},
    )
    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "a_field", "label": "A", "field_type": "text", "ordering": 1},
    )

    resp = c.get("/api/v1/customer-fields/definitions")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert items[0]["key"] == "a_field"
    assert items[1]["key"] == "b_field"


def test_update_definition(seed):
    _, _, _, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    create = c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "industry", "label": "Industry", "field_type": "text"},
    )
    def_id = create.json()["id"]

    resp = c.patch(
        f"/api/v1/customer-fields/definitions/{def_id}",
        json={"label": "Sector", "field_type": "select"},
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "Sector"
    assert resp.json()["field_type"] == "select"


def test_delete_definition(seed):
    _, _, _, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    create = c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "temp", "label": "Temp", "field_type": "text"},
    )
    def_id = create.json()["id"]

    resp = c.delete(f"/api/v1/customer-fields/definitions/{def_id}")
    assert resp.status_code == 204

    listing = c.get("/api/v1/customer-fields/definitions")
    assert len(listing.json()) == 0


def test_definitions_tenant_isolation(two_tenants):
    (_, _, _, email_a, plain_a), (_, _, _, email_b, plain_b) = two_tenants

    ca = TestClient(app)
    csrf_a = _login(ca, email_a, plain_a)
    ca.headers["X-CSRF-Token"] = csrf_a
    ca.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "only_a", "label": "Only A", "field_type": "text"},
    )

    cb = TestClient(app)
    csrf_b = _login(cb, email_b, plain_b)
    cb.headers["X-CSRF-Token"] = csrf_b

    resp_b = cb.get("/api/v1/customer-fields/definitions")
    assert len(resp_b.json()) == 0


def test_definitions_csrf_required(seed):
    _, _, _, email, plain = seed
    c = TestClient(app)
    _login(c, email, plain)

    resp = c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "x", "label": "X", "field_type": "text"},
    )
    assert resp.status_code == 403


def test_operator_cannot_create_definition():
    tid, _, _, email, plain = _seed("operator")
    try:
        c = TestClient(app)
        csrf = _login(c, email, plain)
        c.headers["X-CSRF-Token"] = csrf

        resp = c.post(
            "/api/v1/customer-fields/definitions",
            json={"key": "x", "label": "X", "field_type": "text"},
        )
        assert resp.status_code == 403
    finally:
        _cleanup(tid)


# ── Values tests ─────────────────────────────────────────────────────


def test_put_and_get_values(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "color", "label": "Favorite Color", "field_type": "text"},
    )
    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "size", "label": "Size", "field_type": "select"},
    )

    resp = c.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={"values": {"color": "blue", "size": "large"}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2

    get_resp = c.get(f"/api/v1/customers/{cust_id}/field-values")
    assert get_resp.status_code == 200
    items = get_resp.json()
    assert len(items) == 2
    by_key = {v["key"]: v["value"] for v in items}
    assert by_key["color"] == "blue"
    assert by_key["size"] == "large"


def test_put_values_upsert(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "score", "label": "Score", "field_type": "number"},
    )
    c.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={"values": {"score": "10"}},
    )
    c.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={"values": {"score": "20"}},
    )

    items = c.get(f"/api/v1/customers/{cust_id}/field-values").json()
    assert len(items) == 1
    assert items[0]["value"] == "20"


def test_put_values_canonicalizes_typed_fields(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "amount", "label": "Amount", "field_type": "number"},
    )
    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "signed", "label": "Signed", "field_type": "checkbox"},
    )
    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "visit", "label": "Visit", "field_type": "date"},
    )
    c.post(
        "/api/v1/customer-fields/definitions",
        json={
            "key": "interests",
            "label": "Interests",
            "field_type": "multiselect",
            "field_options": {"choices": ["credito", "moto", "seguro"]},
        },
    )

    resp = c.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={
            "values": {
                "amount": "010.500",
                "signed": True,
                "visit": "2026-05-08",
                "interests": ["moto", "credito", "moto"],
            }
        },
    )
    assert resp.status_code == 200, resp.text

    items = c.get(f"/api/v1/customers/{cust_id}/field-values").json()
    by_key = {v["key"]: v["value"] for v in items}
    assert by_key["amount"] == "10.5"
    assert by_key["signed"] == "true"
    assert by_key["visit"] == "2026-05-08"
    assert by_key["interests"] == '["moto","credito"]'


def test_put_values_rejects_invalid_typed_values(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    c.post(
        "/api/v1/customer-fields/definitions",
        json={
            "key": "interest",
            "label": "Interest",
            "field_type": "select",
            "field_options": {"choices": ["moto"]},
        },
    )
    c.post(
        "/api/v1/customer-fields/definitions",
        json={"key": "visit", "label": "Visit", "field_type": "date"},
    )

    bad_choice = c.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={"values": {"interest": "seguro"}},
    )
    bad_date = c.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={"values": {"visit": "08/05/2026"}},
    )
    assert bad_choice.status_code == 400
    assert bad_date.status_code == 400


def test_put_values_unknown_key_returns_400(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={"values": {"nonexistent_key": "val"}},
    )
    assert resp.status_code == 400
    assert "unknown field keys" in resp.json()["detail"]


def test_values_tenant_isolation(two_tenants):
    (_, _, _, email_a, plain_a), (_, _, cust_b, _, _) = two_tenants

    ca = TestClient(app)
    csrf_a = _login(ca, email_a, plain_a)
    ca.headers["X-CSRF-Token"] = csrf_a

    # Tenant A cannot access tenant B's customer field values
    resp = ca.get(f"/api/v1/customers/{cust_b}/field-values")
    assert resp.status_code == 404


def test_values_for_nonexistent_customer(seed):
    _, _, _, email, plain = seed
    c = TestClient(app)
    csrf = _login(c, email, plain)
    c.headers["X-CSRF-Token"] = csrf

    resp = c.get(f"/api/v1/customers/{uuid4()}/field-values")
    assert resp.status_code == 404


def test_values_csrf_required(seed):
    _, _, cust_id, email, plain = seed
    c = TestClient(app)
    _login(c, email, plain)

    resp = c.put(
        f"/api/v1/customers/{cust_id}/field-values",
        json={"values": {"x": "y"}},
    )
    assert resp.status_code == 403


def test_unauthenticated_returns_401(seed):
    _, _, cust_id, _, _ = seed
    c = TestClient(app)
    resp = c.get(f"/api/v1/customers/{cust_id}/field-values")
    assert resp.status_code == 401

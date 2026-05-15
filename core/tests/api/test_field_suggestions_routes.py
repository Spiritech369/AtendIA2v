"""Tests for /customers/:cid/field-suggestions + /:sid/accept|reject."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_customer_with_suggestion(tenant_id: str) -> tuple[str, str]:
    """Return (customer_id, suggestion_id)."""

    async def _do() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cust_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"
                    ),
                    {"t": tenant_id, "p": f"+521555{uuid4().hex[:8]}"},
                )
            ).scalar()
            sid = (
                await conn.execute(
                    text(
                        "INSERT INTO field_suggestions "
                        "(tenant_id, customer_id, key, suggested_value, confidence, evidence_text) "
                        "VALUES (:t, :c, 'plan_credito', '10', 0.72, '...plan del 10%...') "
                        "RETURNING id"
                    ),
                    {"t": tenant_id, "c": cust_id},
                )
            ).scalar()
        await engine.dispose()
        return str(cust_id), str(sid)

    return asyncio.run(_do())


def test_list_pending_suggestions(client_operator):
    cust_id, sid = _seed_customer_with_suggestion(client_operator.tenant_id)

    resp = client_operator.get(f"/api/v1/customers/{cust_id}/field-suggestions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == sid
    assert body[0]["key"] == "plan_credito"
    assert body[0]["suggested_value"] == "10"
    assert body[0]["status"] == "pending"


def test_accept_writes_to_attrs_and_marks_accepted(client_operator):
    cust_id, sid = _seed_customer_with_suggestion(client_operator.tenant_id)

    resp = client_operator.post(f"/api/v1/field-suggestions/{sid}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"

    # Verify attrs updated by re-fetching customer
    detail = client_operator.get(f"/api/v1/customers/{cust_id}").json()
    assert detail["attrs"]["plan_credito"] == "10"


def test_reject_marks_rejected_without_touching_attrs(client_operator):
    cust_id, sid = _seed_customer_with_suggestion(client_operator.tenant_id)

    resp = client_operator.post(f"/api/v1/field-suggestions/{sid}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    detail = client_operator.get(f"/api/v1/customers/{cust_id}").json()
    assert "plan_credito" not in (detail["attrs"] or {})


def test_accept_idempotent_returns_409(client_operator):
    _, sid = _seed_customer_with_suggestion(client_operator.tenant_id)

    r1 = client_operator.post(f"/api/v1/field-suggestions/{sid}/accept")
    r2 = client_operator.post(f"/api/v1/field-suggestions/{sid}/accept")
    assert r1.status_code == 200
    assert r2.status_code == 409


def test_tenant_isolation(client_operator, client_tenant_admin):
    """Suggestion seeded under tenant A must 404 for tenant B."""
    _, sid = _seed_customer_with_suggestion(client_tenant_admin.tenant_id)
    resp = client_operator.post(f"/api/v1/field-suggestions/{sid}/accept")
    assert resp.status_code == 404

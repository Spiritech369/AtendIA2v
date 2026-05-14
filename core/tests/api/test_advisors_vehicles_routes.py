"""Sprint A.2 — POST + GET round-trip for /api/v1/appointments/advisors and /vehicles.

The GET endpoints already exist; they delegate to AdvisorProvider /
VehicleProvider. With non-demo tenants getting a DB-backed provider
(instead of the previous Empty provider), an operator must also have a
way to *populate* their advisors and vehicles. These tests pin:

* POST creates a row scoped to the calling tenant.
* GET immediately reflects the new row.
* RBAC: tenant_admin or superadmin only (operator gets 403).
* Tenants don't see each other's rows.

The endpoints accept a slug `id` chosen by the operator — distinct from
demo fixtures so two tenants can each own "maria_gonzalez" without
collision (composite primary key on (tenant_id, id)).
"""

from __future__ import annotations

from uuid import uuid4


def test_post_advisor_then_get_returns_it(client_tenant_admin) -> None:
    body = {
        "id": f"andrea_{uuid4().hex[:6]}",
        "name": "Andrea Ruiz",
        "phone": "+5218110000111",
        "max_per_day": 7,
        "close_rate": 0.33,
    }
    resp = client_tenant_admin.post("/api/v1/appointments/advisors", json=body)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["id"] == body["id"]
    assert created["name"] == "Andrea Ruiz"
    assert created["max_per_day"] == 7

    listing = client_tenant_admin.get("/api/v1/appointments/advisors").json()
    assert any(a["id"] == body["id"] and a["name"] == "Andrea Ruiz" for a in listing)


def test_post_vehicle_then_get_returns_it(client_tenant_admin) -> None:
    body = {
        "id": f"tcross_{uuid4().hex[:6]}",
        "label": "T-Cross 2024",
        "status": "available",
        "available_for_test_drive": True,
    }
    resp = client_tenant_admin.post("/api/v1/appointments/vehicles", json=body)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["id"] == body["id"]
    assert created["label"] == "T-Cross 2024"

    listing = client_tenant_admin.get("/api/v1/appointments/vehicles").json()
    assert any(v["id"] == body["id"] for v in listing)


def test_post_advisor_operator_forbidden(client_operator) -> None:
    """Operators must not be able to create advisors — that's a tenant_admin
    or superadmin action, same as editing pipeline / tone config."""
    body = {"id": "should_not_be_created", "name": "Should Fail"}
    resp = client_operator.post("/api/v1/appointments/advisors", json=body)
    assert resp.status_code == 403, resp.text


def test_advisors_listing_does_not_leak_across_tenants(
    client_tenant_admin,
    superadmin_seed,
) -> None:
    """Tenant isolation pin: a row created by tenant B must never appear in
    the listing of tenant A. The DBAdvisorProvider must filter by tenant_id
    even when the underlying table grows large."""
    other_tid = superadmin_seed[0]
    slug = f"foreign_{uuid4().hex[:6]}"
    # Seed directly via raw SQL so we don't need a second authenticated client.
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from atendia.config import get_settings

    async def _seed() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO advisors (tenant_id, id, name) "
                        "VALUES (:t, :i, 'Tenant B Advisor')"
                    ),
                    {"t": other_tid, "i": slug},
                )
        finally:
            await engine.dispose()

    asyncio.run(_seed())

    listing = client_tenant_admin.get("/api/v1/appointments/advisors").json()
    assert all(a["id"] != slug for a in listing), (
        f"advisor {slug} from tenant {other_tid} leaked into tenant "
        f"{client_tenant_admin.tenant_id}'s listing"
    )

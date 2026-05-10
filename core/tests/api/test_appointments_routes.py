"""Hardening tests for appointments_routes (Session 8 of v1 parity).

Covers:
- create returns ``{appointment, conflicts}`` shape
- conflict detection: same customer, ±30 min window flags overlap
- conflicts only count ``status=scheduled`` (cancelled/completed don't conflict)
- patch + delete emit audit events; deleting twice → 404
- list ``total`` honors filters (independent of ``limit``)
- ``status`` filter rejects unknown values with 400
- ``scheduled_at`` must be tz-aware (Pydantic validator)
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_customers(tenant_id: str, count: int = 2) -> list[str]:
    async def _do() -> list[str]:
        engine = create_async_engine(get_settings().database_url)
        ids: list[str] = []
        async with engine.begin() as conn:
            for i in range(count):
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, :n) RETURNING id"
                        ),
                        {
                            "t": tenant_id,
                            "p": f"+5215{uuid4().hex[:9]}",
                            "n": f"Cliente {i}",
                        },
                    )
                ).scalar()
                ids.append(str(cid))
        await engine.dispose()
        return ids

    return asyncio.run(_do())


def _audit_actions(tenant_id: str) -> list[str]:
    async def _do() -> list[str]:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT type FROM events WHERE tenant_id = :t "
                        "AND type LIKE 'admin.appointment.%' ORDER BY occurred_at"
                    ),
                    {"t": tenant_id},
                )
            ).all()
        await engine.dispose()
        return [r[0] for r in rows]

    return asyncio.run(_do())


def test_create_response_shape_and_no_conflicts(client_tenant_admin):
    customer_id = _seed_customers(client_tenant_admin.tenant_id, 1)[0]
    when = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
    resp = client_tenant_admin.post(
        "/api/v1/appointments",
        json={"customer_id": customer_id, "scheduled_at": when, "service": "Test"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "appointment" in body
    assert body["conflicts"] == []
    assert body["appointment"]["service"] == "Test"
    assert body["appointment"]["customer_phone"].startswith("+521")


def test_duplicate_create_returns_existing_appointment(client_tenant_admin):
    customer_id = _seed_customers(client_tenant_admin.tenant_id, 1)[0]
    when = (datetime.now(UTC) + timedelta(hours=5)).replace(microsecond=0).isoformat()
    payload = {"customer_id": customer_id, "scheduled_at": when, "service": "Idempotente"}

    first = client_tenant_admin.post("/api/v1/appointments", json=payload)
    second = client_tenant_admin.post("/api/v1/appointments", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["appointment"]["id"] == first.json()["appointment"]["id"]


def test_conflict_detection_within_window(client_tenant_admin):
    customer_id = _seed_customers(client_tenant_admin.tenant_id, 1)[0]
    base = datetime.now(UTC) + timedelta(days=1)
    first = client_tenant_admin.post(
        "/api/v1/appointments",
        json={"customer_id": customer_id, "scheduled_at": base.isoformat(), "service": "A"},
    )
    assert first.status_code == 201
    assert first.json()["conflicts"] == []

    # +20 min: inside ±30 min window — should be flagged.
    overlap = client_tenant_admin.post(
        "/api/v1/appointments",
        json={
            "customer_id": customer_id,
            "scheduled_at": (base + timedelta(minutes=20)).isoformat(),
            "service": "B",
        },
    )
    assert overlap.status_code == 201
    conflicts = overlap.json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["service"] == "A"

    # +90 min: outside the window.
    far = client_tenant_admin.post(
        "/api/v1/appointments",
        json={
            "customer_id": customer_id,
            "scheduled_at": (base + timedelta(minutes=90)).isoformat(),
            "service": "C",
        },
    )
    assert far.status_code == 201
    assert far.json()["conflicts"] == []


def test_cancelled_appointments_do_not_conflict(client_tenant_admin):
    customer_id = _seed_customers(client_tenant_admin.tenant_id, 1)[0]
    base = datetime.now(UTC) + timedelta(days=2)
    first = client_tenant_admin.post(
        "/api/v1/appointments",
        json={"customer_id": customer_id, "scheduled_at": base.isoformat(), "service": "A"},
    )
    appt_id = first.json()["appointment"]["id"]
    # Cancel the first appointment.
    cancel = client_tenant_admin.patch(
        f"/api/v1/appointments/{appt_id}", json={"status": "cancelled"}
    )
    assert cancel.status_code == 200

    # New appointment 10 min later: previous is cancelled, so no conflict.
    new = client_tenant_admin.post(
        "/api/v1/appointments",
        json={
            "customer_id": customer_id,
            "scheduled_at": (base + timedelta(minutes=10)).isoformat(),
            "service": "B",
        },
    )
    assert new.status_code == 201
    assert new.json()["conflicts"] == []


def test_audit_log_emitted_on_full_lifecycle(client_tenant_admin):
    customer_id = _seed_customers(client_tenant_admin.tenant_id, 1)[0]
    when = (datetime.now(UTC) + timedelta(hours=6)).isoformat()
    created = client_tenant_admin.post(
        "/api/v1/appointments",
        json={"customer_id": customer_id, "scheduled_at": when, "service": "Lifecycle"},
    )
    appt_id = created.json()["appointment"]["id"]
    client_tenant_admin.patch(
        f"/api/v1/appointments/{appt_id}", json={"status": "completed"}
    )
    client_tenant_admin.delete(f"/api/v1/appointments/{appt_id}")

    actions = _audit_actions(client_tenant_admin.tenant_id)
    assert "admin.appointment.created" in actions
    assert "admin.appointment.patched" in actions
    assert "admin.appointment.deleted" in actions

    # Deleting twice should 404, not double-log.
    second_delete = client_tenant_admin.delete(f"/api/v1/appointments/{appt_id}")
    assert second_delete.status_code == 404


def test_list_total_honors_filters_independently_of_limit(client_tenant_admin):
    customer_id = _seed_customers(client_tenant_admin.tenant_id, 1)[0]
    base = datetime.now(UTC) + timedelta(days=10)
    for i in range(5):
        resp = client_tenant_admin.post(
            "/api/v1/appointments",
            json={
                "customer_id": customer_id,
                "scheduled_at": (base + timedelta(hours=i * 2)).isoformat(),
                "service": f"S{i}",
            },
        )
        assert resp.status_code == 201

    listing = client_tenant_admin.get("/api/v1/appointments?limit=2").json()
    assert len(listing["items"]) == 2
    assert listing["total"] >= 5

    # status filter narrows total too.
    appt_id = listing["items"][0]["id"]
    client_tenant_admin.patch(f"/api/v1/appointments/{appt_id}", json={"status": "completed"})
    completed = client_tenant_admin.get("/api/v1/appointments?status=completed").json()
    assert completed["total"] == 1
    assert completed["items"][0]["id"] == appt_id


def test_invalid_status_filter_returns_400(client_tenant_admin):
    resp = client_tenant_admin.get("/api/v1/appointments?status=potato")
    assert resp.status_code == 400


def test_naive_datetime_rejected(client_tenant_admin):
    customer_id = _seed_customers(client_tenant_admin.tenant_id, 1)[0]
    naive = datetime.utcnow().replace(tzinfo=None).isoformat()  # noqa: DTZ003
    resp = client_tenant_admin.post(
        "/api/v1/appointments",
        json={"customer_id": customer_id, "scheduled_at": naive, "service": "X"},
    )
    assert resp.status_code == 422

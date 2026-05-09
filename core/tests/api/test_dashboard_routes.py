"""Tests for /dashboard/summary (Session 10 of v1 parity).

The frontend now polls this every 60s and renders 4 stat cards, a 7-day
inbound/outbound chart, today's appointments and the 10 most-recent
conversations. We make sure each piece is correct under realistic seed data.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed(tenant_id: str) -> dict[str, str]:
    """Insert a customer + conversation + messages spanning the last 7 days,
    plus a couple of appointments — one today, one tomorrow."""

    async def _do() -> dict[str, str]:
        engine = create_async_engine(get_settings().database_url)
        ids: dict[str, str] = {}
        now = datetime.now(UTC)
        async with engine.begin() as conn:
            customer_id = (
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, name) "
                        "VALUES (:t, :p, 'Ana') RETURNING id"
                    ),
                    {"t": tenant_id, "p": f"+5215{uuid4().hex[:9]}"},
                )
            ).scalar()
            conv_id = (
                await conn.execute(
                    text(
                        "INSERT INTO conversations (tenant_id, customer_id, current_stage, "
                        "status, last_activity_at, unread_count, created_at) "
                        "VALUES (:t, :c, 'lead', 'active', :now, 2, :now) RETURNING id"
                    ),
                    {"t": tenant_id, "c": customer_id, "now": now},
                )
            ).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
            # Spread 6 inbound + 4 outbound messages across the last 5 days.
            for i in range(6):
                await conn.execute(
                    text(
                        "INSERT INTO messages (conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, 'inbound', 'hola', :s)"
                    ),
                    {"c": conv_id, "t": tenant_id, "s": now - timedelta(days=i % 5, hours=i)},
                )
            for i in range(4):
                await conn.execute(
                    text(
                        "INSERT INTO messages (conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, 'outbound', 'hi', :s)"
                    ),
                    {"c": conv_id, "t": tenant_id, "s": now - timedelta(days=i, hours=i + 1)},
                )

            # One appointment today (within tenant timezone — we use UTC now
            # which falls into the same calendar day for Mexico City unless
            # the test runs around midnight, in which case we skew earlier).
            today_apt = (
                await conn.execute(
                    text(
                        "INSERT INTO appointments "
                        "(tenant_id, customer_id, scheduled_at, service, status, created_by_type) "
                        "VALUES (:t, :c, :s, 'Demo hoy', 'scheduled', 'user') RETURNING id"
                    ),
                    {"t": tenant_id, "c": customer_id, "s": now + timedelta(hours=2)},
                )
            ).scalar()
            # One appointment 3 days away — must NOT appear in todays_appointments.
            await conn.execute(
                text(
                    "INSERT INTO appointments "
                    "(tenant_id, customer_id, scheduled_at, service, status, created_by_type) "
                    "VALUES (:t, :c, :s, 'Demo futura', 'scheduled', 'user')"
                ),
                {"t": tenant_id, "c": customer_id, "s": now + timedelta(days=3)},
            )

            ids["customer_id"] = str(customer_id)
            ids["conversation_id"] = str(conv_id)
            ids["appointment_id"] = str(today_apt)
        await engine.dispose()
        return ids

    return asyncio.run(_do())


def test_empty_tenant_returns_zeros_and_empty_arrays(client_tenant_admin):
    resp = client_tenant_admin.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_customers"] == 0
    assert body["conversations_today"] == 0
    assert body["active_conversations"] == 0
    assert body["unanswered_conversations"] == 0
    assert body["todays_appointments"] == []
    assert body["recent_conversations"] == []
    # Activity chart is always 7 buckets, even when empty.
    assert len(body["activity_chart"]) == 7
    assert all(b["inbound"] == 0 and b["outbound"] == 0 for b in body["activity_chart"])


def test_seeded_tenant_summary(client_tenant_admin):
    seeded = _seed(client_tenant_admin.tenant_id)

    body = client_tenant_admin.get("/api/v1/dashboard/summary").json()

    assert body["total_customers"] == 1
    assert body["active_conversations"] == 1
    assert body["unanswered_conversations"] == 1  # unread_count > 0

    # Today's appointment must include the one scheduled today.
    today_appts = body["todays_appointments"]
    assert any(a["id"] == seeded["appointment_id"] for a in today_appts)
    assert all(a["service"] != "Demo futura" for a in today_appts)

    recent = body["recent_conversations"]
    assert len(recent) == 1
    assert recent[0]["id"] == seeded["conversation_id"]
    assert recent[0]["unread_count"] == 2
    assert recent[0]["customer_name"] == "Ana"

    # Activity chart still 7 buckets, contains some non-zero days.
    assert len(body["activity_chart"]) == 7
    total_inbound = sum(b["inbound"] for b in body["activity_chart"])
    total_outbound = sum(b["outbound"] for b in body["activity_chart"])
    assert total_inbound == 6
    assert total_outbound == 4


def test_dashboard_requires_auth(client):
    resp = client.get("/api/v1/dashboard/summary")
    assert resp.status_code in (401, 403)


def test_recent_conversations_capped_at_10(client_tenant_admin):
    """The frontend table assumes ≤10 rows; verify the backend enforces it."""

    async def _seed_eleven() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            for i in range(11):
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, :n) RETURNING id"
                        ),
                        {
                            "t": client_tenant_admin.tenant_id,
                            "p": f"+5215{uuid4().hex[:9]}",
                            "n": f"C{i}",
                        },
                    )
                ).scalar()
                await conn.execute(
                    text(
                        "INSERT INTO conversations (tenant_id, customer_id, current_stage, "
                        "status, last_activity_at) "
                        "VALUES (:t, :c, 'lead', 'active', :s)"
                    ),
                    {
                        "t": client_tenant_admin.tenant_id,
                        "c": cid,
                        "s": datetime.now(UTC) - timedelta(minutes=i),
                    },
                )
        await engine.dispose()

    asyncio.run(_seed_eleven())
    body = client_tenant_admin.get("/api/v1/dashboard/summary").json()
    assert len(body["recent_conversations"]) == 10

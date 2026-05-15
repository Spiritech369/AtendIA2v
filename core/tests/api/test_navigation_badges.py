"""Tests for GET /api/v1/navigation/badges.

Seeds controlled volume per tenant + user, verifies each count individually.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_data(tenant_id: str, user_id: str) -> None:
    """Insert minimal rows so badges have something to count."""
    now = datetime.now(timezone.utc)

    async def _do() -> None:
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

            # 3 conversations: 2 active + 1 resolved
            for status in ["active", "active", "resolved"]:
                await conn.execute(
                    text(
                        "INSERT INTO conversations "
                        "(tenant_id, customer_id, status, current_stage) "
                        "VALUES (:t, :c, :s, 'new')"
                    ),
                    {"t": tenant_id, "c": cust_id, "s": status},
                )

            conv_id = (
                await conn.execute(
                    text("SELECT id FROM conversations WHERE tenant_id = :t LIMIT 1"),
                    {"t": tenant_id},
                )
            ).scalar()

            # 3 handoffs: 1 open recent, 1 assigned overdue (>2h), 1 resolved
            await conn.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(tenant_id, conversation_id, reason, status, requested_at) "
                    "VALUES (:t, :c, 'r1', 'open', :now)"
                ),
                {"t": tenant_id, "c": conv_id, "now": now},
            )
            await conn.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(tenant_id, conversation_id, reason, status, requested_at) "
                    "VALUES (:t, :c, 'r2', 'assigned', :old)"
                ),
                {"t": tenant_id, "c": conv_id, "old": now - timedelta(hours=3)},
            )
            await conn.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(tenant_id, conversation_id, reason, status, requested_at, resolved_at) "
                    "VALUES (:t, :c, 'r3', 'resolved', :old, :now)"
                ),
                {
                    "t": tenant_id,
                    "c": conv_id,
                    "old": now - timedelta(hours=5),
                    "now": now,
                },
            )

            # 2 appointments today (scheduled + confirmed), 1 tomorrow
            today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
            tomorrow_noon = today_noon + timedelta(days=1)
            for sched, status in [
                (today_noon, "scheduled"),
                (today_noon + timedelta(hours=2), "confirmed"),
                (tomorrow_noon, "scheduled"),
            ]:
                # NOTE: provide created_by_type explicitly — the table's
                # server_default is literally "'user'" with apostrophes
                # (legacy migration quirk) and trips the check constraint.
                await conn.execute(
                    text(
                        "INSERT INTO appointments "
                        "(tenant_id, customer_id, scheduled_at, service, status, created_by_type) "
                        "VALUES (:t, :c, :s, 'visita', :st, 'user')"
                    ),
                    {"t": tenant_id, "c": cust_id, "s": sched, "st": status},
                )

            # 1 turn_trace with errors in last 24h, 1 older, 1 no error
            await conn.execute(
                text(
                    "INSERT INTO turn_traces "
                    "(tenant_id, conversation_id, turn_number, errors, total_cost_usd) "
                    "VALUES (:t, :c, 1, CAST(:e AS jsonb), 0)"
                ),
                {
                    "t": tenant_id,
                    "c": conv_id,
                    "e": json.dumps([{"type": "tool_error"}]),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO turn_traces "
                    "(tenant_id, conversation_id, turn_number, errors, total_cost_usd, created_at) "
                    "VALUES (:t, :c, 2, CAST(:e AS jsonb), 0, :old)"
                ),
                {
                    "t": tenant_id,
                    "c": conv_id,
                    "e": json.dumps([{"type": "policy"}]),
                    "old": now - timedelta(days=2),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO turn_traces "
                    "(tenant_id, conversation_id, turn_number, total_cost_usd) "
                    "VALUES (:t, :c, 3, 0)"
                ),
                {"t": tenant_id, "c": conv_id},
            )

            # 2 unread + 1 read notifications for this user
            for read, title in [(False, "n1"), (False, "n2"), (True, "n3")]:
                await conn.execute(
                    text(
                        "INSERT INTO notifications "
                        "(tenant_id, user_id, title, read) "
                        "VALUES (:t, :u, :title, :r)"
                    ),
                    {"t": tenant_id, "u": user_id, "title": title, "r": read},
                )

        await engine.dispose()

    asyncio.run(_do())


def test_navigation_badges_counts(client_operator):
    _seed_data(client_operator.tenant_id, client_operator.user_id)

    resp = client_operator.get("/api/v1/navigation/badges")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["conversations_open"] == 2
    assert body["handoffs_open"] == 2  # open + assigned
    assert body["handoffs_overdue"] == 1  # the >2h one
    assert body["appointments_today"] == 2
    assert body["ai_debug_warnings"] == 1  # only last-24h with errors
    assert body["unread_notifications"] == 2


def test_navigation_badges_tenant_isolation(client_operator, client_tenant_admin):
    """Tenant A's seed should not leak into tenant B's counts."""
    _seed_data(client_operator.tenant_id, client_operator.user_id)

    resp = client_tenant_admin.get("/api/v1/navigation/badges")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversations_open"] == 0
    assert body["handoffs_open"] == 0
    assert body["appointments_today"] == 0


def test_navigation_badges_requires_auth(client):
    resp = client.get("/api/v1/navigation/badges")
    assert resp.status_code in (401, 403)

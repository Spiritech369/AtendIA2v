"""Session-5 closures on Conversations Enhanced.

- C-1: ``customers.email`` column round-trips through PATCH + detail.
- C-2 backend: ``conversation detail`` returns ``last_inbound_at`` so the
  frontend can render the outside-24h banner.
- C-5: per-tenant rate limit on ``POST /conversations/{id}/force-summary``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import redis.asyncio as redis_async
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _flush_force_summary_keys() -> None:
    async def _do() -> None:
        client = redis_async.Redis.from_url(get_settings().redis_url)
        try:
            cursor = 0
            while True:
                cursor, keys = await client.scan(
                    cursor=cursor, match="convs:force_summary_rl:*", count=200
                )
                if keys:
                    await client.delete(*keys)
                if cursor == 0:
                    break
        finally:
            await client.aclose()

    asyncio.run(_do())


@pytest.fixture(autouse=True)
def _isolate_force_summary_rate_limit() -> None:
    _flush_force_summary_keys()
    yield
    _flush_force_summary_keys()


def _seed_customer(tenant_id: str) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                cust = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Cliente C1') RETURNING id"
                        ),
                        {"t": tenant_id, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                return str(cust)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


def _seed_conversation_with_inbound(tenant_id: str, *, inbound_age_hours: float) -> tuple[str, str]:
    """Insert a conversation whose most-recent inbound is exactly
    ``inbound_age_hours`` ago. Returns (customer_id, conversation_id)."""

    async def _do() -> tuple[str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                cust = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'Cliente') RETURNING id"
                        ),
                        {"t": tenant_id, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
                conv = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id) "
                            "VALUES (:t, :c) RETURNING id"
                        ),
                        {"t": tenant_id, "c": cust},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv},
                )
                sent_at = datetime.now(UTC) - timedelta(hours=inbound_age_hours)
                await conn.execute(
                    text(
                        "INSERT INTO messages "
                        "(conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, 'inbound', 'hola', :s)"
                    ),
                    {"c": conv, "t": tenant_id, "s": sent_at},
                )
            return str(cust), str(conv)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


# ── C-1: customers.email round-trip ─────────────────────────────────


def test_email_round_trips_via_patch(client_tenant_admin) -> None:
    cust_id = _seed_customer(client_tenant_admin.tenant_id)
    detail = client_tenant_admin.get(f"/api/v1/customers/{cust_id}")
    assert detail.status_code == 200
    assert detail.json()["email"] is None  # default

    patched = client_tenant_admin.patch(
        f"/api/v1/customers/{cust_id}",
        json={"email": "  cliente@ejemplo.com  "},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["email"] == "cliente@ejemplo.com"  # stripped

    cleared = client_tenant_admin.patch(
        f"/api/v1/customers/{cust_id}",
        json={"email": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["email"] is None  # blank -> NULL


def test_email_rejects_unknown_fields(client_tenant_admin) -> None:
    """``CustomerPatch`` is now ``extra='forbid'`` after C-1; unknown fields
    must 422 instead of being silently dropped."""
    cust_id = _seed_customer(client_tenant_admin.tenant_id)
    bad = client_tenant_admin.patch(
        f"/api/v1/customers/{cust_id}",
        json={"haxor_field": "ignored?"},
    )
    assert bad.status_code == 422


# ── C-2: last_inbound_at exposed for the 24h banner ────────────────


def test_last_inbound_at_returned_in_detail(client_tenant_admin) -> None:
    _cust, conv_id = _seed_conversation_with_inbound(
        client_tenant_admin.tenant_id,
        inbound_age_hours=2.0,
    )
    resp = client_tenant_admin.get(f"/api/v1/conversations/{conv_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_inbound_at"] is not None
    age_hours = (
        datetime.now(UTC) - datetime.fromisoformat(body["last_inbound_at"].replace("Z", "+00:00"))
    ).total_seconds() / 3600.0
    assert 1.5 <= age_hours <= 2.5  # tolerance for clock drift


def test_last_inbound_at_null_when_no_inbound(client_tenant_admin) -> None:
    """Conversation with only outbound messages -> last_inbound_at is null."""

    async def _seed() -> str:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                cust = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164) "
                            "VALUES (:t, :p) RETURNING id"
                        ),
                        {
                            "t": client_tenant_admin.tenant_id,
                            "p": f"+5215{uuid4().hex[:9]}",
                        },
                    )
                ).scalar()
                conv = (
                    await conn.execute(
                        text(
                            "INSERT INTO conversations (tenant_id, customer_id) "
                            "VALUES (:t, :c) RETURNING id"
                        ),
                        {"t": client_tenant_admin.tenant_id, "c": cust},
                    )
                ).scalar()
                await conn.execute(
                    text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                    {"c": conv},
                )
                # Only an outbound message — no inbound.
                await conn.execute(
                    text(
                        "INSERT INTO messages "
                        "(conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, 'outbound', 'hi', now())"
                    ),
                    {"c": conv, "t": client_tenant_admin.tenant_id},
                )
                return str(conv)
        finally:
            await engine.dispose()

    conv_id = asyncio.run(_seed())
    resp = client_tenant_admin.get(f"/api/v1/conversations/{conv_id}")
    assert resp.json()["last_inbound_at"] is None


# ── C-5: per-tenant force_summary rate limit ───────────────────────


def test_force_summary_rate_limit(client_tenant_admin) -> None:
    """30/min cap. The 31st call within a window must 429."""
    _cust, conv_id = _seed_conversation_with_inbound(
        client_tenant_admin.tenant_id,
        inbound_age_hours=1.0,
    )
    last = None
    for _ in range(31):
        last = client_tenant_admin.post(f"/api/v1/conversations/{conv_id}/force-summary")
    assert last is not None
    assert last.status_code == 429, last.text


def test_force_summary_under_limit_succeeds(client_tenant_admin) -> None:
    _cust, conv_id = _seed_conversation_with_inbound(
        client_tenant_admin.tenant_id,
        inbound_age_hours=1.0,
    )
    resp = client_tenant_admin.post(f"/api/v1/conversations/{conv_id}/force-summary")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] in {"processing", "worker_unavailable"}

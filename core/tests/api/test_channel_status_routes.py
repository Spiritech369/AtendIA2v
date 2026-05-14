"""Tests for `/api/v1/channel/status` — multi-channel (Meta + Baileys).

The endpoint exposes legacy fields (`whatsapp_status`, `circuit_breaker_open`,
`last_webhook_at`) for backward compat with the old badge, plus new fields
(`active_channel`, `channels`) so the badge can render which transport is
serving the tenant.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_baileys_config(
    tenant_id: str,
    *,
    enabled: bool,
    last_status: str,
    prefer_over_meta: bool,
    phone: str | None = "+5215512345678",
) -> None:
    """Sync wrapper — write a tenant_baileys_config row for the test tenant."""

    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenant_baileys_config "
                    "(tenant_id, enabled, last_status, last_status_at, "
                    " prefer_over_meta, connected_phone) "
                    "VALUES (:t, :e, :s, NOW(), :p, :phone) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET "
                    "  enabled = EXCLUDED.enabled, "
                    "  last_status = EXCLUDED.last_status, "
                    "  prefer_over_meta = EXCLUDED.prefer_over_meta, "
                    "  connected_phone = EXCLUDED.connected_phone"
                ),
                {
                    "t": UUID(tenant_id),
                    "e": enabled,
                    "s": last_status,
                    "p": prefer_over_meta,
                    "phone": phone,
                },
            )
        await engine.dispose()

    asyncio.run(_do())


def _seed_recent_webhook(tenant_id: str) -> None:
    """Sync wrapper — set Redis key `webhook:last_at:<tid>` to "now"."""
    from redis.asyncio import Redis

    async def _do() -> None:
        redis = Redis.from_url(get_settings().redis_url)
        try:
            await redis.set(
                f"webhook:last_at:{tenant_id}",
                datetime.now(timezone.utc).isoformat(),
                ex=86400,
            )
        finally:
            await redis.aclose()

    asyncio.run(_do())


def _clear_redis(tenant_id: str) -> None:
    from redis.asyncio import Redis

    async def _do() -> None:
        redis = Redis.from_url(get_settings().redis_url)
        try:
            await redis.delete(f"webhook:last_at:{tenant_id}", f"breaker:open:{tenant_id}")
        finally:
            await redis.aclose()

    asyncio.run(_do())


@pytest.fixture(autouse=True)
def _cleanup_redis(client_operator):
    """Each test starts with a clean redis state for its tenant."""
    yield
    _clear_redis(client_operator.tenant_id)


# ── Scenario 1: tenant without Baileys, no recent webhook → meta/inactive ──


def test_status_returns_meta_inactive_when_no_baileys_no_webhook(client_operator):
    """Default tenant: Baileys unconfigured + Meta idle → active=meta, status=inactive.

    Exercises the most common production case (tenant only uses Meta and
    hasn't received traffic in 5+ minutes).
    """
    resp = client_operator.get("/api/v1/channel/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["active_channel"] == "meta"
    assert body["whatsapp_status"] == "inactive"
    assert body["circuit_breaker_open"] is False
    assert body["channels"]["meta"]["status"] == "inactive"
    assert body["channels"]["baileys"]["status"] == "not_configured"


# ── Scenario 2: meta with recent webhook → connected ──


def test_status_returns_meta_connected_when_webhook_is_fresh(client_operator):
    _seed_recent_webhook(client_operator.tenant_id)
    resp = client_operator.get("/api/v1/channel/status")
    body = resp.json()

    assert body["active_channel"] == "meta"
    assert body["whatsapp_status"] == "connected"
    assert body["channels"]["meta"]["status"] == "connected"
    assert body["channels"]["meta"]["last_seen_at"] is not None


# ── Scenario 3: baileys preferred → active=baileys regardless of meta ──


def test_status_picks_baileys_when_prefer_over_meta_is_true(client_operator):
    """Operator-controlled preference wins even if Meta is the only one
    actually receiving webhooks."""
    _seed_recent_webhook(client_operator.tenant_id)  # Meta is healthy
    _seed_baileys_config(
        client_operator.tenant_id,
        enabled=True,
        last_status="connected",
        prefer_over_meta=True,
    )

    resp = client_operator.get("/api/v1/channel/status")
    body = resp.json()

    assert body["active_channel"] == "baileys"
    assert body["whatsapp_status"] == "connected"  # legacy mapping: baileys connected → connected
    assert body["channels"]["baileys"]["status"] == "connected"
    assert body["channels"]["baileys"]["phone"] == "+5215512345678"
    # Meta detail is still reported in `channels.meta` for the tooltip.
    assert body["channels"]["meta"]["status"] == "connected"


# ── Scenario 4: baileys connected, meta inactive, no preference → auto-failover ──


def test_status_auto_fails_over_to_baileys_when_meta_inactive(client_operator):
    _seed_baileys_config(
        client_operator.tenant_id,
        enabled=True,
        last_status="connected",
        prefer_over_meta=False,
    )
    resp = client_operator.get("/api/v1/channel/status")
    body = resp.json()

    assert body["active_channel"] == "baileys"
    assert body["whatsapp_status"] == "connected"


# ── Scenario 5: baileys pairing maps to "pairing" but legacy falls back to inactive ──


def test_baileys_pairing_state_uses_friendly_label(client_operator):
    """qr_pending in the DB is exposed as "pairing" to the frontend so the
    badge can render a distinct sky-blue pulse instead of an ambiguous amber."""
    _seed_baileys_config(
        client_operator.tenant_id,
        enabled=True,
        last_status="qr_pending",
        prefer_over_meta=True,
        phone=None,
    )

    resp = client_operator.get("/api/v1/channel/status")
    body = resp.json()

    assert body["channels"]["baileys"]["status"] == "pairing"
    # Legacy 3-state mapping: pairing → inactive (paused is Meta-only).
    assert body["active_channel"] == "baileys"
    assert body["whatsapp_status"] == "inactive"


# ── Scenario 6: baileys enabled=False is treated as not_configured ──


def test_disabled_baileys_does_not_steal_active_channel(client_operator):
    """A tenant who toggled Baileys off should not see it as active even if
    a stale row exists in the table."""
    _seed_baileys_config(
        client_operator.tenant_id,
        enabled=False,
        last_status="connected",
        prefer_over_meta=True,
    )
    resp = client_operator.get("/api/v1/channel/status")
    body = resp.json()

    assert body["active_channel"] == "meta"
    assert body["channels"]["baileys"]["status"] == "not_configured"

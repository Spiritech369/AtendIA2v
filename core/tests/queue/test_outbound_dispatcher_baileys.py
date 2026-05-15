"""Verify the outbound worker routes between Meta and Baileys based on
tenant_baileys_config.prefer_over_meta + last_status.

We exercise the pure decision helper `_should_route_baileys` directly to
keep the test deterministic without spinning up arq/redis/Meta adapter.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.queue.worker import _send_via_baileys, _should_route_baileys


@pytest.fixture
def tenant_id():
    """Insert a tenant + baileys config row; yield id; clean up."""
    tid = None

    async def _setup() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            new_id = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                    {"n": f"dispatch_{uuid4().hex[:8]}"},
                )
            ).scalar()
        await engine.dispose()
        return str(new_id)

    tid = asyncio.run(_setup())
    yield tid

    async def _teardown() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        await engine.dispose()

    asyncio.run(_teardown())


def _set_baileys(tid: str, *, enabled: bool, prefer: bool, status_val: str) -> None:
    async def _do() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenant_baileys_config "
                    "(tenant_id, enabled, prefer_over_meta, last_status) "
                    "VALUES (:t, :e, :p, :s) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET "
                    "enabled = EXCLUDED.enabled, "
                    "prefer_over_meta = EXCLUDED.prefer_over_meta, "
                    "last_status = EXCLUDED.last_status"
                ),
                {"t": tid, "e": enabled, "p": prefer, "s": status_val},
            )
        await engine.dispose()

    asyncio.run(_do())


def _check(tid: str) -> bool:
    async def _do() -> bool:
        engine = create_async_engine(get_settings().database_url)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            result = await _should_route_baileys(session, tid)
        await engine.dispose()
        return result

    return asyncio.run(_do())


def test_no_config_routes_to_meta(tenant_id):
    assert _check(tenant_id) is False


def test_enabled_preferred_connected_routes_to_baileys(tenant_id):
    _set_baileys(tenant_id, enabled=True, prefer=True, status_val="connected")
    assert _check(tenant_id) is True


def test_enabled_preferred_but_disconnected_routes_to_meta(tenant_id):
    _set_baileys(tenant_id, enabled=True, prefer=True, status_val="disconnected")
    assert _check(tenant_id) is False


def test_enabled_not_preferred_routes_to_meta(tenant_id):
    _set_baileys(tenant_id, enabled=True, prefer=False, status_val="connected")
    assert _check(tenant_id) is False


def test_disabled_routes_to_meta(tenant_id):
    _set_baileys(tenant_id, enabled=False, prefer=True, status_val="connected")
    assert _check(tenant_id) is False


def test_send_via_baileys_rejects_template():
    """Templates are a Meta concept; Baileys can't fulfill them."""
    from atendia.channels.base import OutboundMessage

    msg = OutboundMessage(
        tenant_id=str(uuid4()),
        to_phone_e164="+5215551234567",
        template={"name": "x", "language": "es"},
        idempotency_key="x",
    )
    receipt = asyncio.run(_send_via_baileys(msg.tenant_id, msg, "internal-id"))
    assert receipt.status == "failed"
    assert "template" in (receipt.error or "")

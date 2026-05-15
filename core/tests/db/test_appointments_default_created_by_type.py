"""D9 — regression guard for migration 026's busted server_default.

The original migration emitted DEFAULT '''user''' (3 single quotes)
for appointments.created_by_type, so any raw INSERT that omitted the
column failed the CHECK constraint. Migration 049 fixes the default
to plain 'user'. This test pins the new behaviour."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.fixture
def tenant_and_customer() -> tuple[str, str]:
    async def _seed() -> tuple[str, str]:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"d9_test_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                cid = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, 'D9 Test') RETURNING id"
                        ),
                        {"t": tid, "p": f"+5215{uuid4().hex[:9]}"},
                    )
                ).scalar()
            return str(tid), str(cid)
        finally:
            await e.dispose()

    async def _cleanup(tid: str) -> None:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await e.dispose()

    tid, cid = asyncio.run(_seed())
    yield tid, cid
    asyncio.run(_cleanup(tid))


def test_raw_insert_without_created_by_type_succeeds(tenant_and_customer):
    """Raw INSERT INTO appointments without explicit created_by_type
    must succeed — the column has a sensible default of 'user'.

    Pre-migration 049 this failed with:
      new row violates check constraint "ck_appointments_created_by_type"
    """
    tid, cid = tenant_and_customer

    async def _do():
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                from datetime import UTC, datetime, timedelta

                # Status default on `appointments` carries the same
                # migration-026 triple-quote bug, but that's out of
                # D9's scope. Supply it explicitly so we isolate
                # the test to the created_by_type default only.
                aid = (
                    (
                        await conn.execute(
                            text(
                                "INSERT INTO appointments "
                                "(tenant_id, customer_id, scheduled_at, service, status) "
                                "VALUES (:t, :c, :sa, 'test', 'scheduled') "
                                "RETURNING id, created_by_type"
                            ),
                            {"t": tid, "c": cid, "sa": datetime.now(UTC) + timedelta(hours=1)},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert aid["created_by_type"] == "user", (
                f"default should resolve to 'user', got {aid['created_by_type']!r}"
            )
        finally:
            await e.dispose()

    asyncio.run(_do())


def test_default_is_plain_user_not_quoted(tenant_and_customer):
    """The actual stored default in information_schema must be
    'user'::character varying (4 chars including the SQL-string
    quotes) and NOT '''user'''::character varying."""

    async def _do():
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                default = (
                    await conn.execute(
                        text(
                            "SELECT column_default FROM information_schema.columns "
                            "WHERE table_name='appointments' AND column_name='created_by_type'"
                        )
                    )
                ).scalar()
            assert default is not None
            assert "'''user'''" not in default, (
                f"default still has the triple-quoted bug: {default!r}"
            )
            # The valid form Postgres reports is either
            # "'user'::character varying" or just "'user'"
            assert "'user'" in default
        finally:
            await e.dispose()

    asyncio.run(_do())

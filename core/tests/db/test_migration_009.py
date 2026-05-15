from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_followups_and_handoffs_tables_exist():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _check(sync_conn):
            insp = inspect(sync_conn)
            tables = set(insp.get_table_names())
            assert {"followups_scheduled", "human_handoffs"} <= tables
            f_cols = {c["name"] for c in insp.get_columns("followups_scheduled")}
            assert {
                "id",
                "conversation_id",
                "tenant_id",
                "run_at",
                "template_id",
                "status",
                "attempts",
                "last_error",
                "created_at",
            } <= f_cols
            h_cols = {c["name"] for c in insp.get_columns("human_handoffs")}
            assert {
                "id",
                "conversation_id",
                "tenant_id",
                "reason",
                "assigned_user_id",
                "status",
                "requested_at",
                "resolved_at",
            } <= h_cols

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_followup_lifecycle():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_t21_f') RETURNING id")
            )
        ).scalar()
        cid = (
            await conn.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550021') RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar()
        conv_id = (
            await conn.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"
                ),
                {"t": tid, "c": cid},
            )
        ).scalar()
        run_at = datetime.now(timezone.utc) + timedelta(hours=6)
        await conn.execute(
            text(
                "INSERT INTO followups_scheduled (conversation_id, tenant_id, run_at) "
                "VALUES (:c, :t, :r)"
            ),
            {"c": conv_id, "t": tid, "r": run_at},
        )
        status = (
            await conn.execute(
                text("SELECT status FROM followups_scheduled WHERE conversation_id = :c"),
                {"c": conv_id},
            )
        ).scalar()
        assert status == "pending"
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t21_f'"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_handoff_default_status_open():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_t21_h') RETURNING id")
            )
        ).scalar()
        cid = (
            await conn.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550022') RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar()
        conv_id = (
            await conn.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"
                ),
                {"t": tid, "c": cid},
            )
        ).scalar()
        await conn.execute(
            text(
                "INSERT INTO human_handoffs (conversation_id, tenant_id, reason) "
                "VALUES (:c, :t, 'sentiment negative')"
            ),
            {"c": conv_id, "t": tid},
        )
        status = (
            await conn.execute(
                text("SELECT status FROM human_handoffs WHERE conversation_id = :c"),
                {"c": conv_id},
            )
        ).scalar()
        assert status == "open"
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t21_h'"))
    await engine.dispose()

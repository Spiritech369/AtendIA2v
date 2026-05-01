import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_events_table_structure():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "events" in insp.get_table_names()
            cols = {c["name"] for c in insp.get_columns("events")}
            assert {"id", "conversation_id", "tenant_id", "type", "payload",
                    "occurred_at", "trace_id", "created_at"} <= cols
            indexed_cols = {c for ix in insp.get_indexes("events") for c in ix["column_names"]}
            assert {"conversation_id", "tenant_id", "type", "occurred_at", "trace_id"} <= indexed_cols

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_events_insert_and_jsonb_payload():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (await conn.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t17') RETURNING id")
        )).scalar()
        cid = (await conn.execute(
            text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550017') RETURNING id"),
            {"t": tid},
        )).scalar()
        conv_id = (await conn.execute(
            text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
            {"t": tid, "c": cid},
        )).scalar()
        await conn.execute(
            text(r"""INSERT INTO events (conversation_id, tenant_id, type, payload, occurred_at)
                    VALUES (:c, :t, 'stage_entered', :p\:\:jsonb, NOW())"""),
            {"c": conv_id, "t": tid, "p": '{"stage": "qualify"}'},
        )
        result = (await conn.execute(
            text("SELECT payload->>'stage' FROM events WHERE conversation_id = :c"),
            {"c": conv_id},
        )).scalar()
        assert result == "qualify"
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t17'"))
    await engine.dispose()

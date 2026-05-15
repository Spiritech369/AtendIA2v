import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_messages_table_structure():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "messages" in insp.get_table_names()
            cols = {c["name"] for c in insp.get_columns("messages")}
            assert {
                "id",
                "conversation_id",
                "tenant_id",
                "direction",
                "text",
                "channel_message_id",
                "delivery_status",
                "metadata_json",
                "sent_at",
                "created_at",
            } <= cols
            checks = {c["name"] for c in insp.get_check_constraints("messages")}
            assert "ck_messages_direction" in checks

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_messages_check_constraint_rejects_invalid_direction():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(text("INSERT INTO tenants (name) VALUES ('test_t16') RETURNING id"))
        ).scalar()
        cid = (
            await conn.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550016') RETURNING id"
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
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO messages (conversation_id, tenant_id, direction, text, sent_at) "
                    "VALUES (:c, :t, 'sideways', 'hi', NOW())"
                ),
                {"c": conv_id, "t": tid},
            )
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t16'"))
    await engine.dispose()

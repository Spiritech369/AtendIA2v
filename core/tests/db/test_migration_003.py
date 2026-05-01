import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_conversations_and_state_tables_exist():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            tables = set(insp.get_table_names())
            assert {"conversations", "conversation_state"} <= tables
            conv_cols = {c["name"] for c in insp.get_columns("conversations")}
            assert {"id", "tenant_id", "customer_id", "channel", "status",
                    "current_stage", "created_at", "last_activity_at"} <= conv_cols
            state_cols = {c["name"] for c in insp.get_columns("conversation_state")}
            assert {"conversation_id", "extracted_data", "pending_confirmation",
                    "last_intent", "stage_entered_at", "followups_sent_count",
                    "total_cost_usd", "updated_at"} <= state_cols

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_with_state_lifecycle():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (await conn.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t15') RETURNING id")
        )).scalar()
        cid = (await conn.execute(
            text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550015') RETURNING id"),
            {"t": tid},
        )).scalar()
        conv_id = (await conn.execute(
            text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
            {"t": tid, "c": cid},
        )).scalar()
        await conn.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv_id},
        )
        # Verify FK CASCADE
        await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        rem_conv = (await conn.execute(
            text("SELECT COUNT(*) FROM conversations WHERE id = :c"), {"c": conv_id}
        )).scalar()
        rem_state = (await conn.execute(
            text("SELECT COUNT(*) FROM conversation_state WHERE conversation_id = :c"), {"c": conv_id}
        )).scalar()
        assert rem_conv == 0
        assert rem_state == 0
    await engine.dispose()

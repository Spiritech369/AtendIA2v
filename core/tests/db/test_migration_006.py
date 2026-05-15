import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_turn_traces_and_tool_calls_tables_exist():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _check(sync_conn):
            insp = inspect(sync_conn)
            tables = set(insp.get_table_names())
            assert {"turn_traces", "tool_calls"} <= tables
            tt_cols = {c["name"] for c in insp.get_columns("turn_traces")}
            assert {
                "id",
                "conversation_id",
                "tenant_id",
                "turn_number",
                "inbound_message_id",
                "inbound_text",
                "nlu_input",
                "nlu_output",
                "nlu_model",
                "nlu_tokens_in",
                "nlu_tokens_out",
                "nlu_cost_usd",
                "nlu_latency_ms",
                "state_before",
                "state_after",
                "stage_transition",
                "composer_input",
                "composer_output",
                "composer_model",
                "composer_tokens_in",
                "composer_tokens_out",
                "composer_cost_usd",
                "composer_latency_ms",
                "outbound_messages",
                "total_cost_usd",
                "total_latency_ms",
                "errors",
                "created_at",
            } <= tt_cols
            tc_cols = {c["name"] for c in insp.get_columns("tool_calls")}
            assert {
                "id",
                "turn_trace_id",
                "tool_name",
                "input",
                "output",
                "latency_ms",
                "error",
                "called_at",
            } <= tc_cols

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_turn_trace_with_tool_calls_lifecycle():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(text("INSERT INTO tenants (name) VALUES ('test_t18') RETURNING id"))
        ).scalar()
        cid = (
            await conn.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550018') RETURNING id"
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
        trace_id = (
            await conn.execute(
                text("""INSERT INTO turn_traces (conversation_id, tenant_id, turn_number)
                    VALUES (:c, :t, 1) RETURNING id"""),
                {"c": conv_id, "t": tid},
            )
        ).scalar()
        await conn.execute(
            text("""INSERT INTO tool_calls (turn_trace_id, tool_name, input)
                    VALUES (:tr, 'search_catalog', '{}'::jsonb)"""),
            {"tr": trace_id},
        )
        # CASCADE deletion: dropping the turn_trace removes its tool_calls
        await conn.execute(text("DELETE FROM turn_traces WHERE id = :tr"), {"tr": trace_id})
        remaining = (
            await conn.execute(
                text("SELECT COUNT(*) FROM tool_calls WHERE turn_trace_id = :tr"),
                {"tr": trace_id},
            )
        ).scalar()
        assert remaining == 0
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t18'"))
    await engine.dispose()

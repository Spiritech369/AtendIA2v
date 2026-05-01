import pytest
from sqlalchemy import text

from atendia.tools.registry import _registry, register_tool
from atendia.tools.runner import run_tool
from atendia.tools.search_catalog import SearchCatalogTool


@pytest.fixture(autouse=True)
def reset_registry():
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


@pytest.mark.asyncio
async def test_run_tool_persists_tool_call_with_latency(db_session):
    register_tool(SearchCatalogTool())

    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t34_runner') RETURNING id")
    )).scalar()
    cid = (await db_session.execute(
        text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550034') RETURNING id"),
        {"t": tid},
    )).scalar()
    conv_id = (await db_session.execute(
        text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
        {"t": tid, "c": cid},
    )).scalar()
    trace_id = (await db_session.execute(
        text("INSERT INTO turn_traces (conversation_id, tenant_id, turn_number) "
             "VALUES (:c, :t, 1) RETURNING id"),
        {"c": conv_id, "t": tid},
    )).scalar()
    await db_session.commit()

    inputs = {"tenant_id": str(tid), "query": "anything"}
    output = await run_tool(
        db_session,
        turn_trace_id=trace_id,
        tool_name="search_catalog",
        inputs=inputs,
    )
    await db_session.commit()

    assert output == {"results": []}

    rows = (await db_session.execute(
        text("SELECT tool_name, input, output, latency_ms, error "
             "FROM tool_calls WHERE turn_trace_id = :tr"),
        {"tr": trace_id},
    )).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "search_catalog"
    assert rows[0][1] == inputs
    assert rows[0][2] == {"results": []}
    assert rows[0][3] is not None and rows[0][3] >= 0
    assert rows[0][4] is None  # no error

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_run_tool_persists_error_when_tool_raises(db_session):
    class FailingTool:
        name = "failing_tool"
        async def run(self, session, **kwargs):
            raise RuntimeError("boom")

    register_tool(FailingTool())

    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t34_failing') RETURNING id")
    )).scalar()
    cid = (await db_session.execute(
        text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550035') RETURNING id"),
        {"t": tid},
    )).scalar()
    conv_id = (await db_session.execute(
        text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
        {"t": tid, "c": cid},
    )).scalar()
    trace_id = (await db_session.execute(
        text("INSERT INTO turn_traces (conversation_id, tenant_id, turn_number) "
             "VALUES (:c, :t, 1) RETURNING id"),
        {"c": conv_id, "t": tid},
    )).scalar()
    await db_session.commit()

    with pytest.raises(RuntimeError, match="boom"):
        await run_tool(
            db_session,
            turn_trace_id=trace_id,
            tool_name="failing_tool",
            inputs={"k": "v"},
        )
    await db_session.commit()

    rows = (await db_session.execute(
        text("SELECT tool_name, input, output, error FROM tool_calls WHERE turn_trace_id = :tr"),
        {"tr": trace_id},
    )).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "failing_tool"
    assert rows[0][1] == {"k": "v"}
    assert rows[0][2] is None  # output should be None on error
    assert rows[0][3] == "boom"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()

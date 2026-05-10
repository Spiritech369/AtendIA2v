import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


TEST_CASE_COLUMNS = [
    "id", "tenant_id", "name", "user_query",
    "expected_sources", "expected_keywords", "forbidden_phrases",
    "agent", "required_customer_fields", "expected_action",
    "minimum_score", "is_critical",
    "created_by", "created_at", "updated_at",
]

TEST_RUN_COLUMNS = [
    "id", "tenant_id", "test_case_id", "run_id", "status",
    "retrieved_sources", "generated_answer", "diff_vs_expected",
    "duration_ms", "failure_reasons", "created_at",
]


@pytest.mark.asyncio
async def test_kb_test_cases_table_shape():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "kb_test_cases" in insp.get_table_names()
            cols = [c["name"] for c in insp.get_columns("kb_test_cases")]
            assert cols == TEST_CASE_COLUMNS, cols
        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_kb_test_runs_table_shape():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "kb_test_runs" in insp.get_table_names()
            cols = [c["name"] for c in insp.get_columns("kb_test_runs")]
            assert cols == TEST_RUN_COLUMNS, cols
        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_kb_test_runs_run_index_exists():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='kb_test_runs'"
        ))).scalars().all()
    await engine.dispose()
    assert any("ix_kb_test_runs_run" in i for i in rows), rows


@pytest.mark.asyncio
async def test_kb_test_cases_array_columns_default_to_empty_array():
    """Inserting a row without providing the ARRAY columns must succeed and
    yield an empty list for each. Catches accidental 'NULL not null' or
    wrong-default mistakes (e.g. server_default='[]' instead of ARRAY[]::text[]).
    """
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (await conn.execute(text(
            "INSERT INTO tenants (name) VALUES ('test_kb_t035') RETURNING id"
        ))).scalar()
        tcid = (await conn.execute(text(
            "INSERT INTO kb_test_cases (tenant_id, name, user_query, agent) "
            "VALUES (:t, 'tc', 'q', 'sales_agent') RETURNING id"
        ), {"t": tid})).scalar()
        row = (await conn.execute(text(
            "SELECT expected_keywords, forbidden_phrases, required_customer_fields "
            "FROM kb_test_cases WHERE id = :i"
        ), {"i": tcid})).one()
        assert row[0] == [] and row[1] == [] and row[2] == [], row
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name='test_kb_t035'"))
    await engine.dispose()

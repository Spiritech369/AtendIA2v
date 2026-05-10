import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_kb_versions_table_exists():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "kb_versions" in insp.get_table_names()
            cols = [c["name"] for c in insp.get_columns("kb_versions")]
            assert cols == [
                "id", "tenant_id", "entity_type", "entity_id",
                "version_number", "changed_by", "change_summary",
                "diff_json", "created_at",
            ]
        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_kb_versions_entity_index_exists():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='kb_versions'"
        ))).all()
    await engine.dispose()
    matched = [r for r in rows if "ix_kb_versions_entity" in r[0]]
    assert matched, [r[0] for r in rows]
    # Ensure the index orders version_number DESC for the timeline-read pattern.
    assert "version_number DESC" in matched[0][1], matched[0][1]

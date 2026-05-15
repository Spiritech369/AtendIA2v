import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_kb_collections_table_exists():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "kb_collections" in insp.get_table_names()
            cols = [c["name"] for c in insp.get_columns("kb_collections")]
            assert cols == [
                "id",
                "tenant_id",
                "name",
                "slug",
                "description",
                "icon",
                "color",
                "created_at",
            ]

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_kb_collections_unique_slug_per_tenant():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename='kb_collections'")
                )
            )
            .scalars()
            .all()
        )
    await engine.dispose()
    assert any("uq_kb_collections_tenant_slug" in i for i in rows), rows

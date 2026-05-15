import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings

SHARED_COLUMNS = {
    "status",
    "visibility",
    "priority",
    "expires_at",
    "created_by",
    "updated_by",
    "updated_at",
    "agent_permissions",
    "collection_id",
    "language",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("table", ["tenant_faqs", "tenant_catalogs", "knowledge_documents"])
async def test_shared_metadata_columns(table: str):
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _cols(sync_conn):
            insp = inspect(sync_conn)
            return {c["name"] for c in insp.get_columns(table)}

        cols = await conn.run_sync(_cols)
    await engine.dispose()
    missing = SHARED_COLUMNS - cols
    assert not missing, f"missing in {table}: {missing}"


@pytest.mark.asyncio
async def test_catalog_specific_columns():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _cols(sync_conn):
            return {c["name"] for c in inspect(sync_conn).get_columns("tenant_catalogs")}

        cols = await conn.run_sync(_cols)
    await engine.dispose()
    assert {"price_cents", "stock_status", "region", "branch", "payment_plans"} <= cols


@pytest.mark.asyncio
async def test_document_extra_columns():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _cols(sync_conn):
            return {c["name"] for c in inspect(sync_conn).get_columns("knowledge_documents")}

        cols = await conn.run_sync(_cols)
    await engine.dispose()
    assert {"progress_percentage", "embedded_chunk_count", "error_count"} <= cols


@pytest.mark.asyncio
async def test_chunk_columns():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _cols(sync_conn):
            return {c["name"] for c in inspect(sync_conn).get_columns("knowledge_chunks")}

        cols = await conn.run_sync(_cols)
    await engine.dispose()
    expected = {
        "chunk_status",
        "marked_critical",
        "error_message",
        "token_count",
        "page",
        "heading",
        "section",
        "last_retrieved_at",
        "retrieval_count",
        "average_score",
    }
    assert expected <= cols


@pytest.mark.asyncio
async def test_chunk_status_index_exists():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename='knowledge_chunks'")
                )
            )
            .scalars()
            .all()
        )
    await engine.dispose()
    assert any("ix_kb_chunks_status" in i for i in rows), rows

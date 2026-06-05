import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings

EXPECTED_TABLES = {
    "knowledge_sources": [
        "id",
        "tenant_id",
        "name",
        "type",
        "content_type",
        "status",
        "owner",
        "valid_from",
        "valid_until",
        "priority",
        "metadata_json",
        "created_at",
        "updated_at",
    ],
    "knowledge_items": [
        "id",
        "tenant_id",
        "source_id",
        "title",
        "content",
        "structured_data",
        "status",
        "active",
        "metadata_json",
        "created_at",
        "updated_at",
    ],
    "knowledge_os_chunks": [
        "id",
        "tenant_id",
        "source_id",
        "item_id",
        "chunk_text",
        "chunk_index",
        "embedding",
        "status",
        "metadata_json",
        "created_at",
    ],
    "knowledge_retrieval_logs": [
        "id",
        "tenant_id",
        "agent_id",
        "query",
        "answerable",
        "confidence",
        "selected_chunk_ids",
        "citations_json",
        "metadata_json",
        "created_at",
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("table,expected_columns", EXPECTED_TABLES.items())
async def test_knowledge_os_v2_table_shapes(table: str, expected_columns: list[str]):
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert table in insp.get_table_names()
            cols = [column["name"] for column in insp.get_columns(table)]
            assert cols == expected_columns, cols

        await conn.run_sync(_check)
    await engine.dispose()

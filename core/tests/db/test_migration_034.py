import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


CONFLICT_COLUMNS = [
    "id", "tenant_id", "title", "detection_type", "severity", "status",
    "entity_a_type", "entity_a_id", "entity_a_excerpt",
    "entity_b_type", "entity_b_id", "entity_b_excerpt",
    "suggested_priority", "assigned_to", "resolved_by", "resolved_at",
    "resolution_action", "created_at", "updated_at",
]

UNANSWERED_COLUMNS = [
    "id", "tenant_id", "query", "query_normalized", "agent",
    "conversation_id", "top_score", "llm_confidence", "escalation_reason",
    "failed_chunks", "suggested_answer", "status",
    "assigned_to", "linked_faq_id",
    "created_at", "updated_at", "resolved_at",
]


@pytest.mark.asyncio
async def test_kb_conflicts_table_shape():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "kb_conflicts" in insp.get_table_names()
            cols = [c["name"] for c in insp.get_columns("kb_conflicts")]
            assert cols == CONFLICT_COLUMNS, cols
        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_kb_unanswered_table_shape():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "kb_unanswered_questions" in insp.get_table_names()
            cols = [c["name"] for c in insp.get_columns("kb_unanswered_questions")]
            assert cols == UNANSWERED_COLUMNS, cols
        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_kb_conflicts_status_index_exists():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='kb_conflicts'"
        ))).scalars().all()
    await engine.dispose()
    assert any("ix_kb_conflicts_status" in i for i in rows), rows


@pytest.mark.asyncio
async def test_kb_unanswered_status_index_orders_created_desc():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename='kb_unanswered_questions'"
        ))).all()
    await engine.dispose()
    matched = [r for r in rows if "ix_kb_unanswered_status" in r[0]]
    assert matched, [r[0] for r in rows]
    assert "created_at DESC" in matched[0][1], matched[0][1]

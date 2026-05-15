import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings

HEALTH_COLUMNS = [
    "id",
    "tenant_id",
    "snapshot_at",
    "score",
    "score_components",
    "main_risks",
    "suggested_actions",
    "per_collection_scores",
]
AGENT_PERM_COLUMNS = [
    "id",
    "tenant_id",
    "agent",
    "allowed_source_types",
    "allowed_collection_slugs",
    "min_score",
    "can_quote_prices",
    "can_quote_stock",
    "required_customer_fields",
    "escalate_on_conflict",
    "fallback_message",
    "updated_at",
    "updated_by",
]
PRIORITY_RULE_COLUMNS = [
    "id",
    "tenant_id",
    "agent",
    "source_type",
    "priority",
    "minimum_score",
    "allow_synthesis",
    "allow_direct_answer",
    "escalation_required_when_conflict",
    "updated_at",
]
SAFE_ANSWER_COLUMNS = [
    "tenant_id",
    "min_score_to_answer",
    "escalate_on_conflict",
    "block_invented_prices",
    "block_invented_stock",
    "risky_phrases",
    "default_fallback_message",
    "updated_at",
    "updated_by",
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,expected",
    [
        ("kb_health_snapshots", HEALTH_COLUMNS),
        ("kb_agent_permissions", AGENT_PERM_COLUMNS),
        ("kb_source_priority_rules", PRIORITY_RULE_COLUMNS),
        ("kb_safe_answer_settings", SAFE_ANSWER_COLUMNS),
    ],
)
async def test_table_shapes(table: str, expected: list[str]):
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert table in insp.get_table_names()
            cols = [c["name"] for c in insp.get_columns(table)]
            assert cols == expected, cols

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_kb_health_tenant_at_index_orders_snapshot_desc():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename='kb_health_snapshots'"
                )
            )
        ).all()
    await engine.dispose()
    matched = [r for r in rows if "ix_kb_health_tenant_at" in r[0]]
    assert matched, [r[0] for r in rows]
    assert "snapshot_at DESC" in matched[0][1], matched[0][1]


@pytest.mark.asyncio
async def test_kb_agent_permissions_unique_per_tenant_agent():
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES ('test_kb_t036') RETURNING id")
                )
            ).scalar()
            await conn.execute(
                text(
                    "INSERT INTO kb_agent_permissions (tenant_id, agent) VALUES (:t, 'sales_agent')"
                ),
                {"t": tid},
            )
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO kb_agent_permissions (tenant_id, agent) VALUES (:t, 'sales_agent')"
                    ),
                    {"t": tid},
                )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE name='test_kb_t036'"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_kb_safe_answer_settings_tenant_id_is_pk():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:

        def _check(sync_conn):
            insp = inspect(sync_conn)
            pk = insp.get_pk_constraint("kb_safe_answer_settings")
            assert pk["constrained_columns"] == ["tenant_id"], pk

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_kb_safe_answer_settings_default_fallback_is_spanish():
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("INSERT INTO tenants (name) VALUES ('test_kb_t036b') RETURNING id")
                )
            ).scalar()
            await conn.execute(
                text("INSERT INTO kb_safe_answer_settings (tenant_id) VALUES (:t)"), {"t": tid}
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT default_fallback_message FROM kb_safe_answer_settings WHERE tenant_id = :t"
                    ),
                    {"t": tid},
                )
            ).scalar_one()
            assert "asesor" in row.lower(), row
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE name='test_kb_t036b'"))
        await engine.dispose()

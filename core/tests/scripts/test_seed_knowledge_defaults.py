import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.scripts.seed_knowledge_defaults import (
    DEFAULT_AGENT_PERMISSIONS,
    DEFAULT_COLLECTIONS,
    DEFAULT_PRIORITY_RULES,
    seed_for_tenant,
)


@pytest.fixture
async def tenant_id():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_kb_seed') RETURNING id")
            )
        ).scalar()
    try:
        yield tid
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE name='test_kb_seed'"))
        await engine.dispose()


@pytest.fixture
async def db_session():
    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_writes_expected_row_counts(db_session, tenant_id):
    counts = await seed_for_tenant(db_session, tenant_id)
    assert counts["collections"] == len(DEFAULT_COLLECTIONS)
    assert counts["agent_permissions"] == len(DEFAULT_AGENT_PERMISSIONS)
    assert counts["safe_answer"] == 1
    assert counts["priority_rules"] == len(DEFAULT_PRIORITY_RULES)


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, tenant_id):
    await seed_for_tenant(db_session, tenant_id)
    second = await seed_for_tenant(db_session, tenant_id)
    assert second == {
        "collections": 0,
        "agent_permissions": 0,
        "safe_answer": 0,
        "priority_rules": 0,
    }
    n_perms = (
        await db_session.execute(
            text("SELECT count(*) FROM kb_agent_permissions WHERE tenant_id=:t"), {"t": tenant_id}
        )
    ).scalar_one()
    assert n_perms == 4


@pytest.mark.asyncio
async def test_seed_agent_permissions_match_design_doc(db_session, tenant_id):
    await seed_for_tenant(db_session, tenant_id)
    rows = (
        await db_session.execute(
            text(
                "SELECT agent, allowed_source_types, allowed_collection_slugs, "
                "can_quote_prices, can_quote_stock, required_customer_fields "
                "FROM kb_agent_permissions WHERE tenant_id=:t ORDER BY agent"
            ),
            {"t": tenant_id},
        )
    ).all()
    by_agent = {r[0]: r for r in rows}
    sales = by_agent["sales_agent"]
    assert "catalog" in sales[1]
    assert sales[3] is True  # can_quote_prices
    assert sales[4] is True  # can_quote_stock
    assert sorted(sales[5]) == ["plan_credito", "tipo_credito"]

    recep = by_agent["recepcionista"]
    assert recep[3] is False
    assert recep[4] is False


@pytest.mark.asyncio
async def test_seed_safe_answer_includes_risky_phrases(db_session, tenant_id):
    await seed_for_tenant(db_session, tenant_id)
    raw = (
        await db_session.execute(
            text("SELECT risky_phrases FROM kb_safe_answer_settings WHERE tenant_id=:t"),
            {"t": tenant_id},
        )
    ).scalar_one()
    phrases = raw if isinstance(raw, list) else json.loads(raw)
    patterns = {p["pattern"] for p in phrases}
    assert any("crédito" in p for p in patterns)
    assert any("entrega" in p for p in patterns)


@pytest.mark.asyncio
async def test_seed_priority_rules_ordered_faq_then_catalog_then_doc(db_session, tenant_id):
    await seed_for_tenant(db_session, tenant_id)
    rows = (
        await db_session.execute(
            text(
                "SELECT source_type, priority FROM kb_source_priority_rules "
                "WHERE tenant_id=:t AND agent IS NULL ORDER BY priority DESC"
            ),
            {"t": tenant_id},
        )
    ).all()
    assert [r[0] for r in rows] == ["faq", "catalog", "document"]
    assert rows[0][1] > rows[1][1] > rows[2][1]

import json

import pytest
from sqlalchemy import text

from atendia.tools.search_catalog import SearchCatalogTool


@pytest.mark.asyncio
async def test_search_catalog_finds_matching_items(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t31_search') RETURNING id")
    )).scalar()
    await db_session.execute(
        text("INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs) "
             "VALUES (:t, 'M150Z', 'Italika 150Z', :a\\:\\:jsonb)"),
        {"t": tid, "a": json.dumps({"price_mxn": 28500})},
    )
    await db_session.execute(
        text("INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs) "
             "VALUES (:t, 'M250FT', 'Italika 250 FT', :a\\:\\:jsonb)"),
        {"t": tid, "a": json.dumps({"price_mxn": 42000})},
    )
    await db_session.commit()

    tool = SearchCatalogTool()
    result = await tool.run(db_session, tenant_id=tid, query="150")
    assert "results" in result
    assert len(result["results"]) == 1
    assert result["results"][0]["sku"] == "M150Z"
    assert result["results"][0]["name"] == "Italika 150Z"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_search_catalog_returns_empty_when_no_match(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t31_search_empty') RETURNING id")
    )).scalar()
    await db_session.execute(
        text("INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs) "
             "VALUES (:t, 'M150Z', 'Italika 150Z', '{}'::jsonb)"),
        {"t": tid},
    )
    await db_session.commit()

    tool = SearchCatalogTool()
    result = await tool.run(db_session, tenant_id=tid, query="moto-no-existe")
    assert result["results"] == []

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()

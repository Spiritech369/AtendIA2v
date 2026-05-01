import json

import pytest
from sqlalchemy import text

from atendia.tools.quote import QuoteTool


@pytest.mark.asyncio
async def test_quote_returns_price_for_known_sku(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t31_quote') RETURNING id")
    )).scalar()
    await db_session.execute(
        text("INSERT INTO tenant_catalogs (tenant_id, sku, name, attrs) "
             "VALUES (:t, 'M150Z', 'Italika 150Z', :a\\:\\:jsonb)"),
        {"t": tid, "a": json.dumps({"price_mxn": 28500})},
    )
    await db_session.commit()

    tool = QuoteTool()
    result = await tool.run(db_session, tenant_id=tid, sku="M150Z")
    assert result["sku"] == "M150Z"
    assert result["name"] == "Italika 150Z"
    assert result["price_mxn"] == "28500"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_quote_returns_error_for_unknown_sku(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t31_quote_unknown') RETURNING id")
    )).scalar()
    await db_session.commit()

    tool = QuoteTool()
    result = await tool.run(db_session, tenant_id=tid, sku="NONEXISTENT")
    assert result["error"] == "sku_not_found"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()

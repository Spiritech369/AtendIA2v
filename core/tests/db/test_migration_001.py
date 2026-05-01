import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_tenants_table_exists_after_upgrade():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            tables = set(insp.get_table_names())
            assert "tenants" in tables
            assert "tenant_users" in tables
            cols = {c["name"] for c in insp.get_columns("tenants")}
            assert {"id", "name", "plan", "status", "meta_business_id", "config", "created_at"} <= cols

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenants_can_insert_and_query():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO tenants (name) VALUES ('test_tenant_001')")
        )
        result = await conn.execute(
            text("SELECT name FROM tenants WHERE name = 'test_tenant_001'")
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "test_tenant_001"
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_tenant_001'"))
    await engine.dispose()

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_customers_table_exists():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        def _check(sync_conn):
            insp = inspect(sync_conn)
            assert "customers" in insp.get_table_names()
            cols = {c["name"] for c in insp.get_columns("customers")}
            assert {"id", "tenant_id", "phone_e164", "name", "attrs", "created_at"} <= cols
            indexes = {i["name"] for i in insp.get_indexes("customers")}
            uniques = {u["name"] for u in insp.get_unique_constraints("customers")}
            assert "uq_customers_tenant_phone" in uniques

        await conn.run_sync(_check)
    await engine.dispose()


@pytest.mark.asyncio
async def test_customers_unique_phone_per_tenant():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        res = await conn.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t14') RETURNING id")
        )
        tid = res.scalar()
        await conn.execute(
            text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550001')"),
            {"t": tid},
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550001')"),
                {"t": tid},
            )
    # cleanup outside the failed transaction
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t14'"))
    await engine.dispose()

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_tenant_pipelines_unique_version_per_tenant():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_t19_p') RETURNING id")
            )
        ).scalar()
        await conn.execute(
            text(
                "INSERT INTO tenant_pipelines (tenant_id, version, definition) "
                "VALUES (:t, 1, :d\\:\\:jsonb)"
            ),
            {"t": tid, "d": json.dumps({"stages": []})},
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO tenant_pipelines (tenant_id, version, definition) "
                    "VALUES (:t, 1, :d\\:\\:jsonb)"
                ),
                {"t": tid, "d": json.dumps({"stages": []})},
            )
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t19_p'"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_catalogs_unique_sku_per_tenant():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_t19_c') RETURNING id")
            )
        ).scalar()
        await conn.execute(
            text(
                "INSERT INTO tenant_catalogs (tenant_id, sku, name) "
                "VALUES (:t, 'M150Z', 'Italika 150Z')"
            ),
            {"t": tid},
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO tenant_catalogs (tenant_id, sku, name) "
                    "VALUES (:t, 'M150Z', 'duplicate')"
                ),
                {"t": tid},
            )
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t19_c'"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_faqs_basic_insert():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_t19_f') RETURNING id")
            )
        ).scalar()
        await conn.execute(
            text(
                "INSERT INTO tenant_faqs (tenant_id, question, answer) "
                "VALUES (:t, '¿Cuánto cuesta el envío?', 'Gratis en pedidos +$500')"
            ),
            {"t": tid},
        )
        cnt = (
            await conn.execute(
                text("SELECT COUNT(*) FROM tenant_faqs WHERE tenant_id = :t"), {"t": tid}
            )
        ).scalar()
        assert cnt == 1
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t19_f'"))
    await engine.dispose()

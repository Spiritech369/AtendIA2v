import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.mark.asyncio
async def test_tenant_templates_meta_unique():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_t20_t') RETURNING id")
            )
        ).scalar()
        await conn.execute(
            text(
                "INSERT INTO tenant_templates_meta "
                "(tenant_id, template_name, category, body_template) "
                "VALUES (:t, 'lead_warm_v2', 'marketing', 'Hola {{1}}')"
            ),
            {"t": tid},
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(
                    "INSERT INTO tenant_templates_meta "
                    "(tenant_id, template_name, category, body_template) "
                    "VALUES (:t, 'lead_warm_v2', 'marketing', 'duplicate')"
                ),
                {"t": tid},
            )
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t20_t'"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_tools_config_default_enabled_true():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_t20_c') RETURNING id")
            )
        ).scalar()
        await conn.execute(
            text(
                "INSERT INTO tenant_tools_config (tenant_id, tool_name) "
                "VALUES (:t, 'search_catalog')"
            ),
            {"t": tid},
        )
        enabled = (
            await conn.execute(
                text("SELECT enabled FROM tenant_tools_config WHERE tenant_id = :t"),
                {"t": tid},
            )
        ).scalar()
        assert enabled is True
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t20_c'"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_branding_pk_is_tenant_id():
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        tid = (
            await conn.execute(
                text("INSERT INTO tenants (name) VALUES ('test_t20_b') RETURNING id")
            )
        ).scalar()
        await conn.execute(
            text("INSERT INTO tenant_branding (tenant_id) VALUES (:t)"),
            {"t": tid},
        )
        bot_name = (
            await conn.execute(
                text("SELECT bot_name FROM tenant_branding WHERE tenant_id = :t"),
                {"t": tid},
            )
        ).scalar()
        assert bot_name == "Asistente"
        with pytest.raises(IntegrityError):
            await conn.execute(
                text("INSERT INTO tenant_branding (tenant_id) VALUES (:t)"),
                {"t": tid},
            )
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM tenants WHERE name = 'test_t20_b'"))
    await engine.dispose()

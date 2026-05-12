import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_demo_tenant_flag_true_for_demo_tenant(db_session):
    unique_name = f"t_demo_flag_true_{uuid.uuid4().hex[:8]}"
    tid = (
        await db_session.execute(
            text(f"INSERT INTO tenants (name, is_demo) VALUES ('{unique_name}', TRUE) RETURNING id")
        )
    ).scalar()
    await db_session.commit()

    from atendia.db.models.tenant import Tenant
    from sqlalchemy import select

    result = await db_session.execute(select(Tenant).where(Tenant.id == tid))
    tenant = result.scalar_one()
    assert tenant.is_demo is True

    # cleanup
    await db_session.execute(text(f"DELETE FROM tenants WHERE id = '{tid}'"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_demo_tenant_flag_false_for_real_tenant(db_session):
    unique_name = f"t_real_flag_false_{uuid.uuid4().hex[:8]}"
    tid = (
        await db_session.execute(
            text(f"INSERT INTO tenants (name) VALUES ('{unique_name}') RETURNING id")
        )
    ).scalar()
    await db_session.commit()

    from atendia.db.models.tenant import Tenant
    from sqlalchemy import select

    result = await db_session.execute(select(Tenant).where(Tenant.id == tid))
    tenant = result.scalar_one()
    assert tenant.is_demo is False

    # cleanup
    await db_session.execute(text(f"DELETE FROM tenants WHERE id = '{tid}'"))
    await db_session.commit()

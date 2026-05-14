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

    from sqlalchemy import select

    from atendia.db.models.tenant import Tenant

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

    from sqlalchemy import select

    from atendia.db.models.tenant import Tenant

    result = await db_session.execute(select(Tenant).where(Tenant.id == tid))
    tenant = result.scalar_one()
    assert tenant.is_demo is False

    # cleanup
    await db_session.execute(text(f"DELETE FROM tenants WHERE id = '{tid}'"))
    await db_session.commit()


def test_get_advisor_provider_returns_demo_instance_for_demo_tenant():
    # Import lazily in the test too, in case providers.py isn't created yet
    from atendia.api._deps import _get_advisor_provider_for

    provider = _get_advisor_provider_for(is_demo=True)
    # Should be a DemoAdvisorProvider
    assert hasattr(provider, "list_advisors")
    assert hasattr(provider, "get_advisor")


# Note: these factories USED to raise 501 for non-demo tenants. As of commit
# d9c7f40 they return EmptyXxxProvider instead (keeps the appointments UI
# usable). As of Sprint A.2 the route-facing FastAPI dep returns a DB-backed
# provider for non-demo tenants — the sessionless factory still returns Empty
# because it has no DB context. See tests/db/test_advisor_vehicle_providers.py
# for the DB-backed coverage.


def test_get_advisor_provider_returns_empty_for_real_tenant():
    from atendia.api._deps import _get_advisor_provider_for
    from atendia.providers.empty import EmptyAdvisorProvider

    assert isinstance(_get_advisor_provider_for(is_demo=False), EmptyAdvisorProvider)


def test_get_vehicle_provider_returns_empty_for_real_tenant():
    from atendia.api._deps import _get_vehicle_provider_for
    from atendia.providers.empty import EmptyVehicleProvider

    assert isinstance(_get_vehicle_provider_for(is_demo=False), EmptyVehicleProvider)


def test_get_messaging_provider_returns_empty_for_real_tenant():
    from atendia.api._deps import _get_messaging_provider_for
    from atendia.providers.empty import EmptyMessageActionProvider

    assert isinstance(_get_messaging_provider_for(is_demo=False), EmptyMessageActionProvider)

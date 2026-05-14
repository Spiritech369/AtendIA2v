"""DB-backed Advisor / Vehicle provider tests (Sprint A.2).

These providers replace the EmptyAdvisorProvider / EmptyVehicleProvider
that non-demo tenants used to get. They read tenant-scoped advisors and
vehicles from the `advisors` / `vehicles` tables (migration 047), so a
real tenant can populate dropdowns in /appointments without being
dependent on the hardcoded demo fixtures.

Contract pinned by these tests:
- `list_advisors()` / `list_vehicles()` return only rows for the
  provider's tenant, in a wire-compatible dict shape matching the demo
  fixtures (so the existing /api/v1/appointments/advisors GET handler
  doesn't need a shape rewrite).
- `get_advisor(id)` / `get_vehicle(id)` look up by composite key
  (tenant_id, id) and return None when not found.
- A row in another tenant must not leak via either method.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings


@pytest.fixture
def two_tenant_ids() -> tuple[UUID, UUID]:
    """Insert two throwaway tenants, yield (a, b), tear them down after."""

    async def _seed() -> tuple[UUID, UUID]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                a = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"advprov_test_a_{uuid4().hex[:8]}"},
                    )
                ).scalar()
                b = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": f"advprov_test_b_{uuid4().hex[:8]}"},
                    )
                ).scalar()
            return UUID(str(a)), UUID(str(b))
        finally:
            await engine.dispose()

    async def _cleanup(a: UUID, b: UUID) -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM tenants WHERE id = ANY(:ids)"),
                    {"ids": [str(a), str(b)]},
                )
        finally:
            await engine.dispose()

    a, b = asyncio.run(_seed())
    yield a, b
    asyncio.run(_cleanup(a, b))


async def _session() -> async_sessionmaker:
    engine = create_async_engine(get_settings().database_url)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def test_db_advisor_provider_lists_only_its_tenants_advisors(
    two_tenant_ids: tuple[UUID, UUID],
) -> None:
    from atendia.providers.db_advisors import DBAdvisorProvider

    tid_a, tid_b = two_tenant_ids
    sm, engine = await _session()
    try:
        async with sm() as s:
            await s.execute(
                text(
                    "INSERT INTO advisors (tenant_id, id, name, phone, max_per_day, "
                    "close_rate) VALUES (:t, 'andrea', 'Andrea Ruiz', '+5215111', "
                    "6, 0.3)"
                ),
                {"t": str(tid_a)},
            )
            await s.execute(
                text("INSERT INTO advisors (tenant_id, id, name) VALUES (:t, 'bruno', 'Bruno B')"),
                {"t": str(tid_b)},
            )
            await s.commit()
            provider = DBAdvisorProvider(session=s, tenant_id=tid_a)
            rows = await provider.list_advisors()
        assert [r["id"] for r in rows] == ["andrea"]
        assert rows[0]["name"] == "Andrea Ruiz"
        assert rows[0]["phone"] == "+5215111"
        assert rows[0]["max_per_day"] == 6
        assert abs(rows[0]["close_rate"] - 0.3) < 1e-6
    finally:
        await engine.dispose()


async def test_db_advisor_provider_get_returns_none_for_other_tenant(
    two_tenant_ids: tuple[UUID, UUID],
) -> None:
    from atendia.providers.db_advisors import DBAdvisorProvider

    tid_a, tid_b = two_tenant_ids
    sm, engine = await _session()
    try:
        async with sm() as s:
            await s.execute(
                text(
                    "INSERT INTO advisors (tenant_id, id, name) "
                    "VALUES (:t, 'shared_slug', 'Owned by B')"
                ),
                {"t": str(tid_b)},
            )
            await s.commit()
            provider = DBAdvisorProvider(session=s, tenant_id=tid_a)
            got = await provider.get_advisor("shared_slug")
        assert got is None, "advisor from another tenant must not leak"
    finally:
        await engine.dispose()


async def test_db_vehicle_provider_lists_only_its_tenants_vehicles(
    two_tenant_ids: tuple[UUID, UUID],
) -> None:
    from atendia.providers.db_vehicles import DBVehicleProvider

    tid_a, tid_b = two_tenant_ids
    sm, engine = await _session()
    try:
        async with sm() as s:
            await s.execute(
                text(
                    "INSERT INTO vehicles (tenant_id, id, label, status, "
                    "available_for_test_drive) VALUES "
                    "(:t, 'tcross_24', 'T-Cross 2024', 'available', true)"
                ),
                {"t": str(tid_a)},
            )
            await s.execute(
                text("INSERT INTO vehicles (tenant_id, id, label) VALUES (:t, 'beetle', 'Beetle')"),
                {"t": str(tid_b)},
            )
            await s.commit()
            provider = DBVehicleProvider(session=s, tenant_id=tid_a)
            rows = await provider.list_vehicles()
        assert [r["id"] for r in rows] == ["tcross_24"]
        assert rows[0]["label"] == "T-Cross 2024"
        assert rows[0]["status"] == "available"
        assert rows[0]["available_for_test_drive"] is True
    finally:
        await engine.dispose()


async def test_db_vehicle_provider_get_returns_none_for_other_tenant(
    two_tenant_ids: tuple[UUID, UUID],
) -> None:
    from atendia.providers.db_vehicles import DBVehicleProvider

    tid_a, tid_b = two_tenant_ids
    sm, engine = await _session()
    try:
        async with sm() as s:
            await s.execute(
                text(
                    "INSERT INTO vehicles (tenant_id, id, label) "
                    "VALUES (:t, 'shared_slug', 'Owned by B')"
                ),
                {"t": str(tid_b)},
            )
            await s.commit()
            provider = DBVehicleProvider(session=s, tenant_id=tid_a)
            got = await provider.get_vehicle("shared_slug")
        assert got is None, "vehicle from another tenant must not leak"
    finally:
        await engine.dispose()


async def test_db_advisor_provider_skips_inactive_rows(
    two_tenant_ids: tuple[UUID, UUID],
) -> None:
    """A soft-deactivated advisor (active=false) must not appear in the
    dropdown list. This lets operators retire an advisor without breaking
    historical appointment rows that still reference the slug."""
    from atendia.providers.db_advisors import DBAdvisorProvider

    tid_a, _ = two_tenant_ids
    sm, engine = await _session()
    try:
        async with sm() as s:
            await s.execute(
                text(
                    "INSERT INTO advisors (tenant_id, id, name, active) "
                    "VALUES (:t, 'active_one', 'Active', true), "
                    "(:t, 'retired_one', 'Retired', false)"
                ),
                {"t": str(tid_a)},
            )
            await s.commit()
            provider = DBAdvisorProvider(session=s, tenant_id=tid_a)
            rows = await provider.list_advisors()
        assert [r["id"] for r in rows] == ["active_one"]
    finally:
        await engine.dispose()

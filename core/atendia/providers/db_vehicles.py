"""DB-backed VehicleProvider — replaces EmptyVehicleProvider for non-demo tenants.

Reads from the `vehicles` table (migration 047). Wire shape matches
DemoVehicleProvider so existing /api/v1/appointments/vehicles handlers
need no rewrite.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.advisor import Vehicle


class DBVehicleProvider:
    def __init__(self, *, session: AsyncSession, tenant_id: UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def list_vehicles(self) -> list[dict]:
        stmt = (
            select(Vehicle)
            .where(Vehicle.tenant_id == self._tenant_id, Vehicle.active.is_(True))
            .order_by(Vehicle.label)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_vehicle_to_dict(v) for v in rows]

    async def get_vehicle(self, vehicle_id: str) -> dict | None:
        stmt = select(Vehicle).where(Vehicle.tenant_id == self._tenant_id, Vehicle.id == vehicle_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _vehicle_to_dict(row) if row is not None else None


def _vehicle_to_dict(v: Vehicle) -> dict:
    return {
        "id": v.id,
        "label": v.label,
        "status": v.status,
        "available_for_test_drive": v.available_for_test_drive,
    }

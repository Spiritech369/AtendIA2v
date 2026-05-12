from __future__ import annotations

from typing import Protocol


class VehicleProvider(Protocol):
    """Provides access to vehicle inventory for test drives and deliveries."""

    async def list_vehicles(self) -> list[dict]: ...
    async def get_vehicle(self, vehicle_id: str) -> dict | None: ...

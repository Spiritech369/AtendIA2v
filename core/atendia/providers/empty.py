"""Empty provider implementations.

Used as a graceful fallback for non-demo tenants that haven't wired their
own data sources yet. Returns empty lists / not-found / no-op acks so
the UI shows an empty state instead of a 501 Internal Server Error.

When a real provider is built (DB-backed advisors, vehicles, WhatsApp
messaging), `_deps.py` should switch from `EmptyXxxProvider` to it.
"""
from __future__ import annotations

from uuid import UUID


class EmptyAdvisorProvider:
    """Returns no advisors. The UI shows an empty state."""

    async def list_advisors(self) -> list[dict]:
        return []

    async def get_advisor(self, advisor_id: str) -> dict | None:
        return None


class EmptyVehicleProvider:
    """Returns no vehicles. The UI shows an empty state."""

    async def list_vehicles(self) -> list[dict]:
        return []

    async def get_vehicle(self, vehicle_id: str) -> dict | None:
        return None


class EmptyMessageActionProvider:
    """No-op WhatsApp actions. Returns a fake-acknowledged shape so the
    UI doesn't blow up, but logs that nothing actually got sent.
    """

    async def send_reminder(self, appointment_id: UUID) -> dict:
        return {
            "status": "noop",
            "appointment_id": str(appointment_id),
            "reason": "messaging_provider_not_configured",
        }

    async def send_location(self, appointment_id: UUID) -> dict:
        return {
            "status": "noop",
            "appointment_id": str(appointment_id),
            "reason": "messaging_provider_not_configured",
        }

    async def request_documents(self, appointment_id: UUID) -> dict:
        return {
            "status": "noop",
            "appointment_id": str(appointment_id),
            "reason": "messaging_provider_not_configured",
        }

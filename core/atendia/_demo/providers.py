"""Demo implementations of provider protocols.

Each class satisfies its corresponding Protocol from atendia.providers.
When a real implementation is ready, swap the import in api/_deps.py.
"""
from __future__ import annotations

from uuid import UUID

from atendia._demo.fixtures import DEMO_ADVISORS, DEMO_VEHICLES


class DemoAdvisorProvider:
    async def list_advisors(self) -> list[dict]:
        return DEMO_ADVISORS

    async def get_advisor(self, advisor_id: str) -> dict | None:
        return next((a for a in DEMO_ADVISORS if a["id"] == advisor_id), None)


class DemoVehicleProvider:
    async def list_vehicles(self) -> list[dict]:
        return DEMO_VEHICLES

    async def get_vehicle(self, vehicle_id: str) -> dict | None:
        return next((v for v in DEMO_VEHICLES if v["id"] == vehicle_id), None)


class DemoMessageActionProvider:
    """No-op WhatsApp provider for demo tenants.

    Records the action in the appointment log (via _action_update in routes)
    but does not send any real message.
    """

    async def send_reminder(self, appointment_id: UUID) -> dict:  # noqa: ARG002
        return {"status": "simulated", "_demo": True}

    async def send_location(self, appointment_id: UUID) -> dict:  # noqa: ARG002
        return {"status": "simulated", "_demo": True}

    async def request_documents(self, appointment_id: UUID) -> dict:  # noqa: ARG002
        return {"status": "simulated", "_demo": True}

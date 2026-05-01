from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.tools.base import Tool


class BookAppointmentInput(BaseModel):
    tenant_id: UUID
    customer_id: UUID
    slot: datetime


class BookAppointmentTool(Tool):
    name = "book_appointment"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        params = BookAppointmentInput.model_validate(kwargs)
        # Stub: real implementation in Phase 3 (calls Google Calendar / Calendly).
        # In Phase 1 we just return a canned confirmation; no DB write.
        booking_id = str(uuid4())
        return {
            "booking_id": booking_id,
            "tenant_id": str(params.tenant_id),
            "customer_id": str(params.customer_id),
            "slot": params.slot.isoformat(),
            "status": "confirmed",
        }

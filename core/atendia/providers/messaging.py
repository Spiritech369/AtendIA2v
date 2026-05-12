from __future__ import annotations

from typing import Protocol
from uuid import UUID


class MessageActionProvider(Protocol):
    """Sends appointment-related WhatsApp messages to customers."""

    async def send_reminder(self, appointment_id: UUID) -> dict: ...
    async def send_location(self, appointment_id: UUID) -> dict: ...
    async def request_documents(self, appointment_id: UUID) -> dict: ...

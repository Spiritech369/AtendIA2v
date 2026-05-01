from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    SYSTEM = "system"


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class Message(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    conversation_id: str
    tenant_id: str
    direction: MessageDirection
    text: str
    sent_at: datetime
    channel_message_id: str | None = None
    delivery_status: DeliveryStatus | None = None
    metadata: dict = Field(default_factory=dict)

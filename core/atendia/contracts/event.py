from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class EventType(str, Enum):
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    STAGE_ENTERED = "stage_entered"
    STAGE_EXITED = "stage_exited"
    FIELD_EXTRACTED = "field_extracted"
    TOOL_CALLED = "tool_called"
    HUMAN_HANDOFF_REQUESTED = "human_handoff_requested"
    FOLLOWUP_SCHEDULED = "followup_scheduled"
    ERROR_OCCURRED = "error_occurred"


class Event(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    conversation_id: str
    tenant_id: str
    type: EventType
    payload: dict
    occurred_at: datetime
    trace_id: str | None = None

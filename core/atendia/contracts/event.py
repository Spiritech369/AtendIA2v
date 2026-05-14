from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class EventType(str, Enum):
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    STAGE_ENTERED = "stage_entered"
    STAGE_EXITED = "stage_exited"
    STAGE_CHANGED = "stage_changed"
    FIELD_EXTRACTED = "field_extracted"
    FIELD_UPDATED = "field_updated"
    TOOL_CALLED = "tool_called"
    HUMAN_HANDOFF_REQUESTED = "human_handoff_requested"
    FOLLOWUP_SCHEDULED = "followup_scheduled"
    ERROR_OCCURRED = "error_occurred"
    CONVERSATION_UPDATED = "conversation_updated"
    CONVERSATION_DELETED = "conversation_deleted"
    CONVERSATION_CLOSED = "conversation_closed"
    WEBHOOK_RECEIVED = "webhook_received"
    TAG_UPDATED = "tag_updated"
    DOCUMENT_ACCEPTED = "document_accepted"
    DOCUMENT_REJECTED = "document_rejected"
    DOCS_COMPLETE_FOR_PLAN = "docs_complete_for_plan"
    BOT_PAUSED = "bot_paused"


class Event(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    id: str
    conversation_id: str
    tenant_id: str
    type: EventType
    payload: dict
    occurred_at: datetime
    trace_id: str | None = None

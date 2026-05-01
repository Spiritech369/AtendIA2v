from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class ExtractedField(BaseModel):
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    source_turn: int = Field(ge=0)


class ConversationState(BaseModel):
    conversation_id: str
    tenant_id: str
    current_stage: str
    extracted_data: dict[str, ExtractedField] = Field(default_factory=dict)
    pending_confirmation: str | None = None
    last_intent: str | None = None
    stage_entered_at: datetime
    followups_sent_count: int = Field(default=0, ge=0)
    total_cost_usd: Decimal = Field(default=Decimal("0.0000"))

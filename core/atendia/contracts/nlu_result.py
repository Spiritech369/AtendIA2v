from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from atendia.contracts.conversation_state import ExtractedField


class Intent(str, Enum):
    GREETING = "GREETING"
    ASK_INFO = "ASK_INFO"
    ASK_PRICE = "ASK_PRICE"
    BUY = "BUY"
    SCHEDULE = "SCHEDULE"
    COMPLAIN = "COMPLAIN"
    OFF_TOPIC = "OFF_TOPIC"
    UNCLEAR = "UNCLEAR"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class NLUResult(BaseModel):
    intent: Intent
    topic: str | None = None
    sub_intent: str | None = None
    sales_signal: Literal["none", "low", "medium", "high"] = "none"
    entities: dict[str, ExtractedField] = Field(default_factory=dict)
    sentiment: Sentiment
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguities: list[str] = Field(default_factory=list)

    @field_validator("intent", mode="before")
    @classmethod
    def _normalize_intent(cls, value):
        if isinstance(value, Intent):
            return value
        if isinstance(value, str):
            return value.strip().upper()
        return value

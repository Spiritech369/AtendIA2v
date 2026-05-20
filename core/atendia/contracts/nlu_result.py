from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from atendia.contracts.conversation_state import ExtractedField


class Intent(str, Enum):
    GREETING = "greeting"
    ASK_INFO = "ask_info"
    ASK_PRICE = "ask_price"
    BUY = "buy"
    SCHEDULE = "schedule"
    COMPLAIN = "complain"
    OFF_TOPIC = "off_topic"
    UNCLEAR = "unclear"


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

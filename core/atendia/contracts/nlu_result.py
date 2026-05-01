from enum import Enum

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
    entities: dict[str, ExtractedField] = Field(default_factory=dict)
    sentiment: Sentiment
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguities: list[str] = Field(default_factory=list)

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutboundMessage(BaseModel):
    """Channel-agnostic outbound message request."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    to_phone_e164: str
    text: str | None = None
    template: dict | None = None  # {name, language, components}
    idempotency_key: str
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_text_or_template(self) -> "OutboundMessage":
        if self.text is None and self.template is None:
            raise ValueError("OutboundMessage requires either `text` or `template`")
        if self.text is not None and self.template is not None:
            raise ValueError("OutboundMessage cannot have both `text` and `template`")
        return self


class InboundMessage(BaseModel):
    """Channel-agnostic inbound message (parsed from a webhook)."""

    tenant_id: str
    from_phone_e164: str
    channel_message_id: str
    text: str | None = None
    media_url: str | None = None
    received_at: str  # ISO8601 or unix timestamp string (channel-dependent)
    metadata: dict = Field(default_factory=dict)


class DeliveryReceipt(BaseModel):
    """Receipt from the channel after sending or status callback."""

    message_id: str  # our internal UUID
    channel_message_id: str | None = None
    status: Literal["queued", "sent", "delivered", "read", "failed"]
    error: str | None = None


class ChannelAdapter(ABC):
    """Abstract channel adapter.

    Implementations:
    - MetaCloudAPIAdapter (Phase 2)
    - Future: TwilioAdapter, InstagramDMAdapter, etc.
    """

    name: str

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> DeliveryReceipt: ...

    @abstractmethod
    def validate_signature(self, body: bytes, signature_header: str) -> bool: ...

    @abstractmethod
    def parse_webhook(self, payload: dict, tenant_id: str) -> list[InboundMessage]: ...

    @abstractmethod
    def parse_status_callback(self, payload: dict) -> list[DeliveryReceipt]: ...

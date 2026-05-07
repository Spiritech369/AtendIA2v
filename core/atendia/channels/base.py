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


class InboundAttachment(BaseModel):
    """Channel-agnostic image/document/audio/video attachment.

    Carried in InboundMessage.metadata so it round-trips through the
    inbound persistence path (messages.metadata_json JSONB column) and
    reaches the runner without bespoke columns.

    `url` is populated only when the channel adapter has a way to resolve
    it (Meta requires a separate Graph API call after parsing). Lookaside
    URLs from Meta have a 1-hour TTL — the runner should call Vision
    promptly, never persist these long-term.
    """

    media_id: str
    mime_type: str
    url: str = ""
    caption: str | None = None


class InboundMessageMetadata(BaseModel):
    """Typed shape for InboundMessage.metadata.

    Defining this here keeps the JSONB column shape discoverable and
    validatable; the runner reads back the same model.
    """

    attachments: list[InboundAttachment] = Field(default_factory=list)


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

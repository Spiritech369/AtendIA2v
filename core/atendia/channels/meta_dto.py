from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MetaText(BaseModel):
    body: str


class MetaMediaNode(BaseModel):
    """Image / document / audio / video payload from Meta webhook.

    Phase 3c.2 — Meta sends only metadata (id + mime_type + sha256). The
    actual download URL is fetched separately via the Graph API media endpoint.
    """

    model_config = ConfigDict(extra="ignore")

    id: str  # media_id used for the Graph API URL fetch
    mime_type: str
    sha256: str | None = None
    caption: str | None = None  # only on image/video/document nodes


class MetaInboundMessage(BaseModel):
    """A single inbound message from Meta. Note: Meta sends the field as `from`,
    which is a Python reserved word — we accept it via alias and expose as `from_`.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    from_: str = Field(alias="from")
    id: str
    timestamp: str
    type: str
    text: MetaText | None = None
    image: MetaMediaNode | None = None
    document: MetaMediaNode | None = None
    audio: MetaMediaNode | None = None
    video: MetaMediaNode | None = None


class MetaStatusCallback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: Literal["sent", "delivered", "read", "failed"]
    timestamp: str
    recipient_id: str | None = None


class MetaWebhookMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_phone_number: str | None = None
    phone_number_id: str


class MetaWebhookValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messaging_product: str
    metadata: MetaWebhookMetadata | None = None
    messages: list[MetaInboundMessage] | None = None
    statuses: list[MetaStatusCallback] | None = None


class MetaWebhookChange(BaseModel):
    field: str
    value: MetaWebhookValue


class MetaWebhookEntry(BaseModel):
    id: str
    changes: list[MetaWebhookChange]


class MetaInboundWebhook(BaseModel):
    object: str
    entry: list[MetaWebhookEntry]

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MetaText(BaseModel):
    body: str


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


class MetaStatusCallback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: Literal["sent", "delivered", "read", "failed"]
    timestamp: str
    recipient_id: str | None = None


class MetaWebhookValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messaging_product: str
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

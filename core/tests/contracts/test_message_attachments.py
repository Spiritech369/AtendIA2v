"""Phase 3c.2 extension: Message can carry image/PDF attachments
from Meta Cloud API. The webhook fetches the URL from Meta Graph
API; the runner passes attachments to Vision."""

from datetime import UTC, datetime
from uuid import uuid4

from atendia.contracts.message import Attachment, Message, MessageDirection


def test_attachment_has_required_fields() -> None:
    a = Attachment(
        media_id="MEDIA_123",
        mime_type="image/jpeg",
        url="https://lookaside.fbsbx.com/whatsapp_business/...",
    )
    assert a.media_id == "MEDIA_123"
    assert a.mime_type.startswith("image/")


def test_message_attachments_default_empty() -> None:
    """Backward compat — text-only messages have no attachments."""
    m = Message(
        id=str(uuid4()),
        conversation_id=str(uuid4()),
        tenant_id=str(uuid4()),
        direction=MessageDirection.INBOUND,
        text="hola",
        sent_at=datetime.now(UTC),
    )
    assert m.attachments == []


def test_message_with_image_attachment() -> None:
    m = Message(
        id=str(uuid4()),
        conversation_id=str(uuid4()),
        tenant_id=str(uuid4()),
        direction=MessageDirection.INBOUND,
        text="aquí va mi INE",
        sent_at=datetime.now(UTC),
        attachments=[
            Attachment(
                media_id="WAID-456",
                mime_type="image/jpeg",
                url="https://...",
            )
        ],
    )
    assert len(m.attachments) == 1
    assert m.attachments[0].media_id == "WAID-456"

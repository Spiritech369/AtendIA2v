from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from atendia.contracts.message import Message, MessageDirection


def test_message_inbound_text_valid():
    msg = Message(
        id="01J3Z6V8N1Q4WZS5MXY9KQHF7C",
        conversation_id="01J3Z6V8N1Q4WZS5MXY9KQHF7D",
        tenant_id="dinamomotos",
        direction=MessageDirection.INBOUND,
        text="Hola, info de la 150Z",
        sent_at=datetime(2026, 4, 30, 14, 0, tzinfo=timezone.utc),
    )
    assert msg.direction == MessageDirection.INBOUND
    assert msg.text == "Hola, info de la 150Z"


def test_message_missing_required_field_raises():
    with pytest.raises(ValidationError):
        Message(  # type: ignore[call-arg]
            id="x",
            conversation_id="y",
            tenant_id="z",
            direction=MessageDirection.INBOUND,
        )


def test_message_invalid_direction_raises():
    with pytest.raises(ValidationError):
        Message(
            id="x",
            conversation_id="y",
            tenant_id="z",
            direction="sideways",  # type: ignore[arg-type]
            text="hi",
            sent_at=datetime.now(timezone.utc),
        )

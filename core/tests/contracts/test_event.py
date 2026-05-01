from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from atendia.contracts.event import Event, EventType


def test_event_message_received_valid():
    evt = Event(
        id="01J3Z6V8N1Q4WZS5MXY9KQHF8A",
        conversation_id="01J3Z6V8N1Q4WZS5MXY9KQHF8B",
        tenant_id="dinamomotos",
        type=EventType.MESSAGE_RECEIVED,
        payload={"message_id": "01J3Z6V8N1Q4WZS5MXY9KQHF8C"},
        occurred_at=datetime.now(timezone.utc),
    )
    assert evt.type == EventType.MESSAGE_RECEIVED


def test_event_invalid_type_raises():
    with pytest.raises(ValidationError):
        Event(
            id="x",
            conversation_id="y",
            tenant_id="z",
            type="banana",  # type: ignore[arg-type]
            payload={},
            occurred_at=datetime.now(timezone.utc),
        )

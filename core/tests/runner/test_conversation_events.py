"""Unit tests for the conversation_events helper.

The helper is a thin orchestrator over `session.add(MessageRow)` and
`EventEmitter.emit(EventRow)`. We don't exercise SQL here — a fake
session that records `.add()` calls and a stubbed EventEmitter let us
assert the SHAPE of the rows the runner asks for, which is the contract
the frontend timeline and the workflows engine consume.

If you change the metadata shape (event_type, payload structure), this
test fails — that's the point. The frontend `SystemEventBubble`
discriminates on `metadata.event_type`; drifting the key here without
updating the bubble would silently downgrade rich events to plain
italic text.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from atendia.contracts.event import EventType
from atendia.db.models import MessageRow
from atendia.runner.conversation_events import (
    emit_document_event,
    emit_field_updated,
    emit_stage_changed,
    emit_system_event,
    is_timeline_worthy_field,
)


class _FakeSession:
    """Captures every .add() call and exposes them by row type."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    def messages(self) -> list[MessageRow]:
        return [o for o in self.added if isinstance(o, MessageRow)]


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    session = _FakeSession()
    # The helper instantiates EventEmitter(session); we stub the class
    # so emit() never tries to write to a real DB. The MessageRow path
    # uses session.add directly so it's unaffected.
    fake_emitter = MagicMock()
    fake_emitter.emit = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "atendia.runner.conversation_events.EventEmitter",
        lambda _s: fake_emitter,
    )
    session._fake_emitter = fake_emitter  # type: ignore[attr-defined]
    return session


@pytest.mark.asyncio
async def test_emit_system_event_inserts_message_row(fake_session):
    tenant_id = uuid4()
    conversation_id = uuid4()
    await emit_system_event(
        fake_session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        event_type=EventType.STAGE_CHANGED,
        text="Sistema: prueba",
        payload={"foo": "bar"},
    )

    msgs = fake_session.messages()
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg.direction == "system"
    assert msg.tenant_id == tenant_id
    assert msg.conversation_id == conversation_id
    assert msg.text == "Sistema: prueba"
    assert msg.metadata_json["event_type"] == "stage_changed"
    assert msg.metadata_json["payload"] == {"foo": "bar"}
    assert msg.metadata_json["source"] == "runner"
    # Channel + delivery_status MUST be None on system rows — the
    # outbound dispatcher uses delivery_status to track WhatsApp acks;
    # leaving it null prevents a system row from ever being misread as
    # a queued outbound.
    assert msg.channel_message_id is None
    assert msg.delivery_status is None

    # Event row also fired.
    fake_session._fake_emitter.emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_field_updated_skips_non_timeline_fields(fake_session):
    """Only fields in _TIMELINE_WORTHY_FIELDS produce a chat bubble —
    'city', 'marca', etc. would spam the operator's timeline."""
    await emit_field_updated(
        fake_session,
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        attr_key="city",
        old_value=None,
        new_value="Guadalajara",
        confidence=0.95,
    )
    assert fake_session.messages() == []
    fake_session._fake_emitter.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_field_updated_fires_for_plan_credito(fake_session):
    await emit_field_updated(
        fake_session,
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        attr_key="plan_credito",
        old_value=None,
        new_value="Nómina Tarjeta 10%",
        confidence=0.92,
    )
    msgs = fake_session.messages()
    assert len(msgs) == 1
    assert msgs[0].metadata_json["event_type"] == "field_updated"
    assert msgs[0].metadata_json["payload"]["field"] == "plan_credito"
    assert msgs[0].metadata_json["payload"]["new_value"] == "Nómina Tarjeta 10%"
    assert "Plan de crédito" in msgs[0].text


@pytest.mark.asyncio
async def test_emit_field_updated_renders_booleans_humanely(fake_session):
    """`cumple_antiguedad=True` should render as 'OK', not 'True'."""
    await emit_field_updated(
        fake_session,
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        attr_key="cumple_antiguedad",
        old_value=None,
        new_value=True,
        confidence=0.91,
    )
    assert "OK" in fake_session.messages()[0].text


@pytest.mark.asyncio
async def test_emit_stage_changed_uses_label_when_provided(fake_session):
    await emit_stage_changed(
        fake_session,
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        from_stage="nuevo",
        to_stage="papeleria_incompleta",
        from_label="Nuevo",
        to_label="Papelería incompleta",
        reason="docs_uploaded",
    )
    msg = fake_session.messages()[0]
    assert "Papelería incompleta" in msg.text
    payload = msg.metadata_json["payload"]
    assert payload["from"] == "nuevo"
    assert payload["to"] == "papeleria_incompleta"
    assert payload["reason"] == "docs_uploaded"


@pytest.mark.asyncio
async def test_emit_document_event_accepted(fake_session):
    await emit_document_event(
        fake_session,
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        accepted=True,
        document_type="ine",
        confidence=0.92,
        metadata={"legible": True, "ambos_lados": True},
    )
    msg = fake_session.messages()[0]
    assert msg.metadata_json["event_type"] == "document_accepted"
    assert "aceptado" in msg.text.lower()
    assert "INE" in msg.text


@pytest.mark.asyncio
async def test_emit_document_event_rejected_with_reason(fake_session):
    await emit_document_event(
        fake_session,
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        accepted=False,
        document_type="ine",
        confidence=0.40,
        reason="ilegible por reflejo",
        metadata={"legible": False},
    )
    msg = fake_session.messages()[0]
    assert msg.metadata_json["event_type"] == "document_rejected"
    assert "ilegible" in msg.text.lower()
    payload = msg.metadata_json["payload"]
    assert payload["reason"] == "ilegible por reflejo"
    assert payload["vision_metadata"] == {"legible": False}


def test_is_timeline_worthy_field_allowlist():
    """Allowlist is intentional — adding a field means deciding it's
    worth showing in the chat. Make this test fail when widening it."""
    assert is_timeline_worthy_field("plan_credito")
    assert is_timeline_worthy_field("tipo_credito")
    assert is_timeline_worthy_field("antiguedad_laboral_meses")
    assert not is_timeline_worthy_field("city")
    assert not is_timeline_worthy_field("marca")
    assert not is_timeline_worthy_field("unknown_field")

"""System-event emitter for the conversation timeline.

Fase 1 (`2026-05-14-inbound-message-flow`) bridges two existing pieces
that previously didn't talk to each other:

  - `EventEmitter` writes structured rows to the `events` table — that's
    what the workflows engine + audit log consume.
  - `messages` already supports `direction='system'` (see the CHECK on
    `MessageRow`) but the runner never inserted such rows, so the
    operator's chat timeline never showed "Sistema: plan actualizado",
    "Sistema: stage cambiado", etc.

This helper does BOTH in one call:

  1. Inserts a `messages` row with `direction='system'`, a human-readable
     `text` (rendered server-side so localization stays consistent), and
     `metadata_json = {event_type, payload}` — the frontend uses
     `metadata.event_type` to swap in a richer bubble (icon, color).
  2. Emits an `events` row via `EventEmitter` so workflows can react.

The system message is INSERTED in the same SQLAlchemy session/transaction
as the rest of the turn. The WebSocket fan-out happens later, when the
outbound dispatch publishes `message_sent` (worker.py) — at that point
the dashboard refetches `/conversations/:id/messages` and the system
rows committed earlier in the transaction are now visible.

Important: rows inserted here MUST NEVER be picked up by the outbound
dispatcher. That's safe today because the dispatcher reads
`composer_output.messages` directly (a Python list of strings produced
by the LLM), never `SELECT FROM messages WHERE direction='outbound'`.
The CHECK constraint on `direction` prevents schema drift.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.event import EventType
from atendia.db.models import MessageRow
from atendia.state_machine.event_emitter import EventEmitter

_log = logging.getLogger(__name__)


# Fields that, when AUTO-applied, are interesting enough to surface in
# the conversation timeline as a system event. Anything outside this
# list still produces an `events` row (for analytics) but no chat
# bubble — otherwise low-signal fields (city, marca) would spam the
# operator's view.
_TIMELINE_WORTHY_FIELDS: frozenset[str] = frozenset(
    {
        "tipo_credito",
        "plan_credito",
        "antiguedad_laboral_meses",
        "cumple_antiguedad",
        "modelo_interes",
        "estimated_value",
        "nombre",
    }
)


# Display labels used in the human-readable `text` of the system message.
# The frontend can still render its own label from `metadata.event_type`
# + `metadata.payload.field` if it wants tighter control.
_FIELD_LABELS: dict[str, str] = {
    "tipo_credito": "Tipo de crédito",
    "plan_credito": "Plan de crédito",
    "antiguedad_laboral_meses": "Antigüedad laboral (meses)",
    "cumple_antiguedad": "Cumple antigüedad",
    "modelo_interes": "Modelo de interés",
    "estimated_value": "Valor estimado",
    "nombre": "Nombre",
    "marca": "Marca",
    "city": "Ciudad",
}


def is_timeline_worthy_field(attr_key: str) -> bool:
    """Public so the runner can decide which fields trigger a system bubble."""
    return attr_key in _TIMELINE_WORTHY_FIELDS


def _format_value(value: Any) -> str:
    """Render a Python value for the human-readable timeline text."""
    if isinstance(value, bool):
        return "OK" if value else "no cumple"
    if value is None:
        return "—"
    return str(value)


async def emit_system_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    event_type: EventType,
    text: str,
    payload: dict | None = None,
) -> None:
    """Insert a `messages` row (`direction='system'`) AND an `events` row.

    `text` is the localized one-liner shown in the chat. `payload` is the
    structured data the frontend uses for rich rendering. Both writes
    share the caller's transaction; if the turn rolls back, neither row
    survives.
    """
    payload = payload or {}
    metadata = {
        "event_type": event_type.value,
        "payload": payload,
        "source": "runner",
    }
    now = datetime.now(timezone.utc)

    msg = MessageRow(
        id=uuid4(),
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        direction="system",
        text=text,
        channel_message_id=None,
        delivery_status=None,
        metadata_json=metadata,
        sent_at=now,
    )
    session.add(msg)

    emitter = EventEmitter(session)
    try:
        await emitter.emit(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
        )
    except Exception:
        # Event-table emission failures must NEVER block the system
        # message — the chat row is the user-visible artifact. We log
        # and move on; the workflows engine will just miss this event.
        _log.exception(
            "emit_system_event: events-row insert failed for conv=%s type=%s",
            conversation_id,
            event_type.value,
        )


async def emit_field_updated(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    attr_key: str,
    old_value: Any,
    new_value: Any,
    confidence: float,
    source: str = "nlu",
) -> None:
    """Convenience wrapper for FIELD_UPDATED events.

    Skips silently when the field is not in `_TIMELINE_WORTHY_FIELDS` —
    callers should still emit the underlying FIELD_EXTRACTED to keep
    analytics intact (see runner). Here we only handle the chat bubble.
    """
    if not is_timeline_worthy_field(attr_key):
        return
    label = _FIELD_LABELS.get(attr_key, attr_key)
    text = f"Sistema: {label} actualizado a {_format_value(new_value)}"
    await emit_system_event(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        event_type=EventType.FIELD_UPDATED,
        text=text,
        payload={
            "field": attr_key,
            "label": label,
            "old_value": old_value,
            "new_value": new_value,
            "confidence": confidence,
            "source": source,
        },
    )


async def emit_stage_changed(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    from_stage: str,
    to_stage: str,
    from_label: str | None = None,
    to_label: str | None = None,
    reason: str | None = None,
) -> None:
    """Convenience wrapper for STAGE_CHANGED events."""
    to_display = to_label or to_stage
    text = f"Sistema: Conversación movida a {to_display}"
    await emit_system_event(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        event_type=EventType.STAGE_CHANGED,
        text=text,
        payload={
            "from": from_stage,
            "to": to_stage,
            "from_label": from_label,
            "to_label": to_label,
            "reason": reason,
        },
    )


async def emit_document_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    accepted: bool,
    document_type: str,
    confidence: float,
    reason: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Convenience wrapper for DOCUMENT_ACCEPTED / DOCUMENT_REJECTED."""
    event_type = EventType.DOCUMENT_ACCEPTED if accepted else EventType.DOCUMENT_REJECTED
    label = document_type.replace("_", " ").upper()
    if accepted:
        text = f"Sistema: Documento aceptado — {label}"
    else:
        suffix = f" — {reason}" if reason else ""
        text = f"Sistema: Documento rechazado — {label}{suffix}"
    await emit_system_event(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        event_type=event_type,
        text=text,
        payload={
            "document_type": document_type,
            "confidence": confidence,
            "reason": reason,
            "vision_metadata": metadata or {},
        },
    )


async def emit_bot_paused(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    reason: str,
) -> None:
    """Convenience wrapper for BOT_PAUSED events."""
    text = f"Sistema: Bot pausado — {reason}"
    await emit_system_event(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        event_type=EventType.BOT_PAUSED,
        text=text,
        payload={"reason": reason},
    )

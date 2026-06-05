from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.operational_intent.risk_policy import OperationalIntentResult


async def apply_operational_handoff(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    intent: OperationalIntentResult,
    inbound_text: str,
    extracted_data: dict[str, Any],
) -> bool:
    if not intent.effects.handoff_required:
        return False
    existing = (
        await session.execute(
            text(
                """
                SELECT id
                FROM human_handoffs
                WHERE conversation_id = :cid
                  AND status IN ('pending', 'open')
                LIMIT 1
                """
            ),
            {"cid": conversation_id},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    payload = {
        "reason_code": intent.reason_code or intent.intent_category,
        "intent_category": intent.intent_category,
        "risk_level": intent.risk_level,
        "signals": intent.signals,
        "destination_team": intent.destination_team,
        "last_inbound_message": inbound_text,
        "customer_fields": _public_field_snapshot(extracted_data),
        "created_by": "conversation_control",
        "created_at": datetime.now(UTC).isoformat(),
    }
    await session.execute(
        text(
            """
            INSERT INTO human_handoffs
            (conversation_id, tenant_id, reason, status, payload)
            VALUES (:cid, :tid, :reason, 'pending', CAST(:payload AS JSONB))
            """
        ),
        {
            "cid": conversation_id,
            "tid": tenant_id,
            "reason": intent.reason_code or intent.intent_category,
            "payload": json.dumps(payload, ensure_ascii=False),
        },
    )
    return True


def _public_field_snapshot(extracted_data: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, raw_value in extracted_data.items():
        value = raw_value.get("value") if isinstance(raw_value, dict) else raw_value
        if isinstance(value, (str, int, float, bool)):
            safe[str(key)] = value
    return safe


__all__ = ["apply_operational_handoff"]

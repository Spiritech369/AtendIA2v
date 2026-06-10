from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.schemas import FieldUpdate, TurnOutput


async def persist_runtime_v2_turn_state(
    session: AsyncSession,
    *,
    tenant_id: str,
    conversation_id: str,
    output: TurnOutput,
) -> dict[str, Any]:
    """Persist validated Runtime V2 state for the next DB-backed turn.

    No-send still persists validated state. Sending/outbox is handled by the
    SendAdapter; this module only records state that StateWriter already
    validated into TurnOutput.field_updates.
    """

    row = (
        await session.execute(
            text(
                """SELECT c.customer_id, cs.extracted_data
                FROM conversations c
                LEFT JOIN conversation_state cs ON cs.conversation_id = c.id
                WHERE c.id = :conversation_id AND c.tenant_id = :tenant_id"""
            ),
            {"conversation_id": conversation_id, "tenant_id": tenant_id},
        )
    ).mappings().first()
    if row is None:
        return {"persisted": False, "reason": "conversation_not_found"}

    customer_id = str(row["customer_id"])
    extracted_data = dict(row["extracted_data"] or {})
    now = datetime.now(UTC).isoformat()
    applied: list[dict[str, Any]] = []
    attrs_patch: dict[str, Any] = {}

    for update in _dedupe_field_updates(output.field_updates):
        payload = _field_payload(update, updated_at=now)
        extracted_data[update.field_key] = payload
        attrs_patch[update.field_key] = _jsonable(update.value)
        applied.append(
            {
                "field_key": update.field_key,
                "source": update.source,
                "confidence": update.confidence,
                "metadata": _jsonable(update.metadata),
            }
        )
        await _persist_customer_field_value(
            session,
            tenant_id=tenant_id,
            customer_id=customer_id,
            update=update,
        )

    runtime_memory = dict(extracted_data.get("_runtime_v2") or {})
    advisor = dict(output.trace_metadata.get("advisor_brain") or {})
    advisor_metadata = dict(advisor.get("metadata") or {})
    question_slot = (
        _validated_response_plan_pending_slot(output.trace_metadata)
        or advisor.get("question_slot")
        or advisor_metadata.get("missing_field")
        or _first(output.trace_metadata, "question_slot", "pending_slot")
    )
    if question_slot:
        runtime_memory["pending_slot"] = str(question_slot)
        runtime_memory["question_slot"] = str(question_slot)
        runtime_memory["last_pending_question"] = output.final_message
    else:
        runtime_memory.pop("pending_slot", None)
        runtime_memory.pop("question_slot", None)

    quote_snapshot = _quote_snapshot_from_trace(output.trace_metadata)
    if quote_snapshot:
        extracted_data["last_quote"] = {
            "value": quote_snapshot,
            "source": "quote.resolve",
            "updated_at": now,
        }
        runtime_memory["last_quote_snapshot_id"] = quote_snapshot.get("snapshot_id")

    runtime_memory["state_writer_decisions"] = _jsonable(
        output.trace_metadata.get("state_writer_decisions") or []
    )
    runtime_memory["last_turn_output"] = {
        "confidence": output.confidence,
        "needs_human": output.needs_human,
        "risk_flags": list(output.risk_flags),
    }
    extracted_data["_runtime_v2"] = runtime_memory

    pending_confirmation = _pending_confirmation_value(output.final_message, question_slot)
    await session.execute(
        text(
            """INSERT INTO conversation_state
                (conversation_id, extracted_data, pending_confirmation, last_intent)
            VALUES (:conversation_id, CAST(:extracted_data AS jsonb), :pending, :intent)
            ON CONFLICT (conversation_id) DO UPDATE SET
                extracted_data = EXCLUDED.extracted_data,
                pending_confirmation = EXCLUDED.pending_confirmation,
                last_intent = EXCLUDED.last_intent,
                updated_at = now()"""
        ),
        {
            "conversation_id": conversation_id,
            "extracted_data": json.dumps(extracted_data, ensure_ascii=False),
            "pending": pending_confirmation,
            "intent": _maybe_text(advisor.get("customer_goal")),
        },
    )
    if attrs_patch:
        await session.execute(
            text(
                """UPDATE customers
                SET attrs = coalesce(attrs, '{}'::jsonb) || CAST(:attrs AS jsonb),
                    updated_at = now()
                WHERE id = :customer_id AND tenant_id = :tenant_id"""
            ),
            {
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "attrs": json.dumps(attrs_patch, ensure_ascii=False),
            },
        )
    return {
        "persisted": True,
        "field_updates_applied": applied,
        "pending_slot": str(question_slot) if question_slot else None,
        "quote_snapshot_persisted": bool(quote_snapshot),
    }


async def _persist_customer_field_value(
    session: AsyncSession,
    *,
    tenant_id: str,
    customer_id: str,
    update: FieldUpdate,
) -> None:
    field_id = (
        await session.execute(
            text(
                """SELECT id FROM customer_field_definitions
                WHERE tenant_id = :tenant_id AND key = :field_key
                LIMIT 1"""
            ),
            {"tenant_id": tenant_id, "field_key": update.field_key},
        )
    ).scalar_one_or_none()
    if field_id is None:
        return
    value_text = _value_text(update.value)
    old_value = (
        await session.execute(
            text(
                """SELECT value FROM customer_field_values
                WHERE customer_id = :customer_id AND field_definition_id = :field_id"""
            ),
            {"customer_id": customer_id, "field_id": field_id},
        )
    ).scalar_one_or_none()
    await session.execute(
        text(
            """INSERT INTO customer_field_values
                (customer_id, field_definition_id, value)
            VALUES (:customer_id, :field_id, :value)
            ON CONFLICT (customer_id, field_definition_id) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = now()"""
        ),
        {"customer_id": customer_id, "field_id": field_id, "value": value_text},
    )
    await session.execute(
        text(
            """INSERT INTO customer_field_update_evidence
                (tenant_id, customer_id, field_definition_id, field_key, old_value,
                 new_value, source, evidence_message_id, evidence_attachment_id,
                 reason, confidence, status, trace_id, created_by, metadata_json)
            VALUES
                (:tenant_id, :customer_id, :field_id, :field_key, :old_value,
                 :new_value, :source, :evidence_message_id, :evidence_attachment_id,
                 :reason, :confidence, 'accepted', :trace_id, 'agent_runtime_v2',
                 CAST(:metadata AS jsonb))"""
        ),
        {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "field_id": field_id,
            "field_key": update.field_key,
            "old_value": old_value,
            "new_value": value_text,
            "source": update.source,
            "evidence_message_id": update.evidence_message_id,
            "evidence_attachment_id": update.evidence_attachment_id,
            "reason": update.reason,
            "confidence": update.confidence or 0.0,
            "trace_id": update.trace_id,
            "metadata": json.dumps(_jsonable(update.metadata), ensure_ascii=False),
        },
    )


def _dedupe_field_updates(updates: list[FieldUpdate]) -> list[FieldUpdate]:
    out: list[FieldUpdate] = []
    seen: set[tuple[str, str]] = set()
    for update in updates:
        key = (update.field_key, json.dumps(_jsonable(update.value), sort_keys=True))
        if key in seen:
            continue
        out.append(update)
        seen.add(key)
    return out


def _field_payload(update: FieldUpdate, *, updated_at: str) -> dict[str, Any]:
    return {
        "value": _jsonable(update.value),
        "reason": update.reason,
        "evidence": list(update.evidence),
        "confidence": update.confidence,
        "source": update.source,
        "metadata": _jsonable(update.metadata),
        "updated_at": updated_at,
    }


def _quote_snapshot_from_trace(trace_metadata: dict[str, Any]) -> dict[str, Any] | None:
    for result in trace_metadata.get("tool_results") or []:
        if not isinstance(result, dict):
            continue
        if result.get("tool_name") != "quote.resolve" or result.get("status") != "succeeded":
            continue
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("quote_snapshot"), dict):
            return data["quote_snapshot"]
    return None


def _first(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _validated_response_plan_pending_slot(trace_metadata: dict[str, Any]) -> str | None:
    plan = trace_metadata.get("validated_response_plan")
    if not isinstance(plan, dict):
        universal = trace_metadata.get("universal_turn_trace")
        if isinstance(universal, dict):
            plan = universal.get("validated_response_plan")
    if not isinstance(plan, dict):
        return None
    pending_slot = str(plan.get("pending_slot") or "").strip()
    if not pending_slot or bool(plan.get("slot_consumed")):
        return None
    message_goal = str(plan.get("message_goal") or "")
    if message_goal not in {
        "ask_one_clarifying_question_for_pending_slot",
        "greet_and_resume_without_consuming_slot",
        "acknowledge_confusion_and_explain_pending_slot",
    }:
        return None
    return pending_slot


def _maybe_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _pending_confirmation_value(
    final_message: str,
    question_slot: Any,
    *,
    max_length: int = 160,
) -> str | None:
    if not question_slot:
        return None
    text = str(final_message or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def _value_text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(_jsonable(value), ensure_ascii=False)
    return str(value)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value

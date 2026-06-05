from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from atendia.agent_runtime.agent_config import action_registry_for_agent
from atendia.agent_runtime.schemas import (
    ActionRequest,
    FieldUpdate,
    TurnContext,
    TurnOutput,
    customer_visible_text_paths,
)

_FIELD_SOURCES = {
    "customer_message",
    "ai_inference",
    "knowledge",
    "action",
    "human",
    "workflow",
    "vision",
}
_LIFECYCLE_SOURCES = {"agent", "workflow", "human", "system", "api"}


def coerce_turn_output_dict(raw: Any) -> dict[str, Any]:
    """Convert a model JSON object into the closest TurnOutput-shaped dict."""
    if not isinstance(raw, dict):
        return {
            "final_message": "",
            "actions": [],
            "field_updates": [],
            "lifecycle_update": None,
            "knowledge_citations": [],
            "confidence": 0.0,
            "needs_human": True,
            "risk_flags": ["invalid_provider_payload"],
            "trace_metadata": {"structured_reconciler": {"invalid_root": True}},
        }

    changes: dict[str, Any] = {"raw_repair": []}
    coerced = {
        "final_message": str(raw.get("final_message") or "").strip(),
        "actions": _coerce_actions(raw.get("actions"), changes),
        "field_updates": _coerce_field_updates(raw.get("field_updates"), changes),
        "lifecycle_update": _coerce_lifecycle(raw.get("lifecycle_update"), changes),
        "knowledge_citations": _coerce_citations(raw.get("knowledge_citations"), changes),
        "confidence": _coerce_confidence(raw.get("confidence"), changes),
        "needs_human": bool(raw.get("needs_human", False)),
        "risk_flags": _string_list(raw.get("risk_flags")),
        "trace_metadata": _dict(raw.get("trace_metadata")),
    }
    if not coerced["final_message"]:
        coerced["needs_human"] = True
        coerced["risk_flags"].append("missing_provider_final_message")
        coerced["final_message"] = (
            "Necesito que una persona del equipo revise esto para responderte con certeza."
        )
        changes["raw_repair"].append("filled_missing_final_message")
    if changes["raw_repair"]:
        coerced["trace_metadata"] = {
            **coerced["trace_metadata"],
            "structured_reconciler": changes,
        }
    return coerced


def parse_turn_output_lenient(raw: Any) -> TurnOutput:
    try:
        return TurnOutput.model_validate(raw)
    except ValidationError:
        return TurnOutput.model_validate(coerce_turn_output_dict(raw))


def reconcile_structured_output(context: TurnContext, output: TurnOutput) -> TurnOutput:
    changes: dict[str, Any] = {
        "dropped_invalid_lifecycle": [],
        "dropped_invalid_actions": [],
        "dropped_invalid_fields": [],
        "dropped_field_updates": [],
        "repaired_confidence": False,
        "handoff_stage_to_needs_human": False,
        "repaired_missing_evidence": [],
        "repaired_missing_update_confidence": [],
    }
    allowed_fields = _visible_fields(context)
    allowed_stages = _allowed_stages(context)
    registry = action_registry_for_agent(context.active_agent)

    confidence = output.confidence
    if confidence < 0 or confidence > 1:
        confidence = min(1.0, max(0.0, confidence))
        changes["repaired_confidence"] = True

    risk_flags = list(dict.fromkeys(output.risk_flags))
    needs_human = output.needs_human

    lifecycle = output.lifecycle_update
    if (
        lifecycle is not None
        and not lifecycle.target_stage
        and not lifecycle.target_status
    ):
        lifecycle = None
        changes["dropped_invalid_lifecycle"].append("empty")
    if lifecycle is not None and lifecycle.target_stage:
        target = str(lifecycle.target_stage)
        if _looks_like_handoff(target):
            lifecycle = None
            needs_human = True
            _append_once(risk_flags, "human_requested")
            changes["handoff_stage_to_needs_human"] = True
        elif allowed_stages and target not in allowed_stages:
            changes["dropped_invalid_lifecycle"].append(target)
            lifecycle = None
        elif lifecycle is not None:
            updates: dict[str, Any] = {}
            if not lifecycle.reason:
                updates["reason"] = "Inferred lifecycle update from customer message."
                changes["repaired_missing_evidence"].append("lifecycle_update.reason")
            if not lifecycle.evidence:
                updates["evidence"] = [context.inbound_text]
                changes["repaired_missing_evidence"].append("lifecycle_update.evidence")
            if lifecycle.confidence is None:
                updates["confidence"] = max(0.5, min(1.0, confidence))
                changes["repaired_missing_update_confidence"].append("lifecycle_update")
            if updates:
                lifecycle = lifecycle.model_copy(update=updates)
    elif lifecycle is not None:
        updates = {}
        if not lifecycle.reason:
            updates["reason"] = "Inferred lifecycle update from customer message."
            changes["repaired_missing_evidence"].append("lifecycle_update.reason")
        if not lifecycle.evidence:
            updates["evidence"] = [context.inbound_text]
            changes["repaired_missing_evidence"].append("lifecycle_update.evidence")
        if lifecycle.confidence is None:
            updates["confidence"] = max(0.5, min(1.0, confidence))
            changes["repaired_missing_update_confidence"].append("lifecycle_update")
        if updates:
            lifecycle = lifecycle.model_copy(update=updates)

    actions: list[ActionRequest] = []
    for action in output.actions:
        if not registry.has_action(action.name):
            changes["dropped_invalid_actions"].append(action.name)
            continue
        if customer_visible_text_paths(action.payload):
            changes["dropped_invalid_actions"].append(f"{action.name}:visible_copy")
            continue
        definition = registry.get(action.name)
        updates: dict[str, Any] = {}
        if definition.requires_evidence and not action.evidence:
            updates["evidence"] = [context.inbound_text]
            changes["repaired_missing_evidence"].append(f"action:{action.name}")
        if definition.requires_approval and not action.requires_approval:
            updates["requires_approval"] = True
            changes["repaired_missing_evidence"].append(f"action:{action.name}:approval")
        if updates:
            action = action.model_copy(update=updates)
        actions.append(action)

    field_updates: list[FieldUpdate] = []
    for update in output.field_updates:
        if allowed_fields and update.field_key not in allowed_fields:
            changes["dropped_invalid_fields"].append(update.field_key)
            changes["dropped_field_updates"].append(
                {"field_key": update.field_key, "reason": "invalid_field"}
            )
            continue
        drop_reasons = _invalid_field_update_reasons(update)
        if drop_reasons and update.source != "customer_message":
            changes["dropped_field_updates"].append(
                {"field_key": update.field_key, "reason": "+".join(drop_reasons)}
            )
            continue
        if update.source == "customer_message":
            updates: dict[str, Any] = {}
            if not update.reason:
                updates["reason"] = "Inferred field update from customer message."
                changes["repaired_missing_evidence"].append(f"field:{update.field_key}:reason")
            if not update.evidence:
                updates["evidence"] = [context.inbound_text]
                changes["repaired_missing_evidence"].append(f"field:{update.field_key}:evidence")
            if update.confidence is None:
                updates["confidence"] = max(0.5, min(1.0, confidence))
                changes["repaired_missing_update_confidence"].append(update.field_key)
            if updates:
                update = update.model_copy(update=updates)
        field_updates.append(update)

    trace_metadata = dict(output.trace_metadata)
    if any(changes.values()):
        trace_metadata["reconciler_changes"] = changes
    return output.model_copy(
        update={
            "actions": actions,
            "field_updates": field_updates,
            "lifecycle_update": lifecycle,
            "confidence": confidence,
            "needs_human": needs_human,
            "risk_flags": risk_flags,
            "trace_metadata": trace_metadata,
        }
    )


def _invalid_field_update_reasons(update: FieldUpdate) -> list[str]:
    reasons = []
    if not (update.reason or update.evidence):
        reasons.append("missing_evidence")
    if update.confidence is None:
        reasons.append("missing_confidence")
    elif not 0 <= float(update.confidence) <= 1:
        reasons.append("invalid_confidence")
    return reasons


def _coerce_actions(value: Any, changes: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    for item in _list(value):
        if not isinstance(item, dict):
            changes["raw_repair"].append("dropped_non_object_action")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            changes["raw_repair"].append("dropped_action_without_name")
            continue
        actions.append(
            {
                "name": name,
                "payload": _dict(item.get("payload")),
                "reason": _nullable_str(item.get("reason")),
                "evidence": _string_list(item.get("evidence")),
                "requires_approval": bool(item.get("requires_approval", False)),
                "idempotency_key": _nullable_str(item.get("idempotency_key")),
                "metadata": _dict(item.get("metadata")),
            }
        )
    return actions


def _coerce_field_updates(value: Any, changes: dict[str, Any]) -> list[dict[str, Any]]:
    updates = []
    for item in _list(value):
        if not isinstance(item, dict):
            changes["raw_repair"].append("dropped_non_object_field_update")
            continue
        field_key = str(item.get("field_key") or "").strip()
        if not field_key:
            changes["raw_repair"].append("dropped_field_update_without_key")
            continue
        confidence = _coerce_optional_confidence(item.get("confidence"), changes)
        source = str(item.get("source") or "customer_message")
        if source not in _FIELD_SOURCES:
            source = "customer_message"
            changes["raw_repair"].append(f"repaired_field_source:{field_key}")
        updates.append(
            {
                "field_key": field_key,
                "value": item.get("value"),
                "reason": _nullable_str(item.get("reason")),
                "evidence": _string_list(item.get("evidence")),
                "confidence": confidence,
                "source": source,
                "evidence_message_id": _nullable_str(item.get("evidence_message_id")),
                "evidence_attachment_id": _nullable_str(item.get("evidence_attachment_id")),
                "trace_id": _nullable_str(item.get("trace_id")),
                "metadata": _dict(item.get("metadata")),
            }
        )
    return updates


def _coerce_lifecycle(value: Any, changes: dict[str, Any]) -> dict[str, Any] | None:
    if value in (None, "", [], {}):
        return None
    if not isinstance(value, dict):
        changes["raw_repair"].append("dropped_non_object_lifecycle")
        return None
    source = str(value.get("source") or "agent")
    if source not in _LIFECYCLE_SOURCES:
        source = "agent"
        changes["raw_repair"].append("repaired_lifecycle_source")
    return {
        "target_stage": _nullable_str(value.get("target_stage")),
        "target_status": _nullable_str(value.get("target_status")),
        "reason": _nullable_str(value.get("reason")) or "Structured provider lifecycle update.",
        "evidence": _string_list(value.get("evidence")),
        "confidence": _coerce_confidence(value.get("confidence"), changes),
        "source": source,
        "trace_id": _nullable_str(value.get("trace_id")),
        "metadata": _dict(value.get("metadata")),
    }


def _coerce_citations(value: Any, changes: dict[str, Any]) -> list[dict[str, Any]]:
    citations = []
    for item in _list(value):
        if not isinstance(item, dict):
            changes["raw_repair"].append("dropped_non_object_citation")
            continue
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            changes["raw_repair"].append("dropped_citation_without_source_id")
            continue
        citations.append(
            {
                "source_id": source_id,
                "title": _nullable_str(item.get("title")),
                "snippet": _nullable_str(item.get("snippet")),
                "score": _nullable_float(item.get("score")),
                "metadata": _dict(item.get("metadata")),
            }
        )
    return citations


def _coerce_confidence(value: Any, changes: dict[str, Any]) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        changes["raw_repair"].append("repaired_confidence_default")
        return 0.0
    if confidence < 0 or confidence > 1:
        changes["raw_repair"].append("clamped_confidence")
    return min(1.0, max(0.0, confidence))


def _coerce_optional_confidence(value: Any, changes: dict[str, Any]) -> float | None:
    if value is None:
        return None
    return _coerce_confidence(value, changes)


def _visible_fields(context: TurnContext) -> set[str]:
    if context.active_agent and context.active_agent.visible_contact_field_keys is not None:
        return set(context.active_agent.visible_contact_field_keys)
    return {field.key for field in context.contact_fields}


def _allowed_stages(context: TurnContext) -> set[str]:
    if context.active_agent and context.active_agent.allowed_lifecycle_stage_ids is not None:
        return set(context.active_agent.allowed_lifecycle_stage_ids)
    return set()


def _looks_like_handoff(value: str) -> bool:
    return value.casefold() in {"handoff", "human", "humano", "asesor", "human_handoff"}


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nullable_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

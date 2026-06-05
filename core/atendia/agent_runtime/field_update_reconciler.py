from __future__ import annotations

import re
import unicodedata
from typing import Any

from atendia.agent_runtime.schemas import FieldUpdate, LifecycleUpdate, TurnContext, TurnOutput

_MONEY_RE = re.compile(r"(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>mil|k)?", re.I)


def reconcile_field_updates(context: TurnContext, output: TurnOutput) -> TurnOutput:
    config = _config(context)
    field_rules = list(config.get("field_update_rules") or [])
    lifecycle_rules = list(config.get("lifecycle_rules") or [])
    if not field_rules and not lifecycle_rules:
        return output

    visible_fields = _visible_fields(context)
    existing = {update.field_key for update in output.field_updates}
    text = _fold(context.inbound_text)
    history_text = _fold(" ".join(message.text for message in context.messages[-4:]))
    updates = list(output.field_updates)
    changes: dict[str, Any] = {"added_field_updates": [], "added_lifecycle_update": None}

    for rule in field_rules:
        field_key = str(rule.get("field_key") or "")
        override_existing = bool(rule.get("override_existing", False))
        if (
            not field_key
            or (field_key in existing and not override_existing)
            or field_key not in visible_fields
        ):
            continue
        inferred = _infer_value(rule, text=text, history_text=history_text)
        if inferred is None:
            continue
        if override_existing and field_key in existing:
            updates = [update for update in updates if update.field_key != field_key]
            existing.discard(field_key)
        update = FieldUpdate(
            field_key=field_key,
            value=inferred,
            reason=str(rule.get("reason") or "Inferred from explicit customer message."),
            evidence=[context.inbound_text],
            confidence=float(rule.get("confidence", 0.9)),
            source="customer_message",
            metadata={"reconciler": True, "rule_id": rule.get("id") or field_key},
        )
        updates.append(update)
        existing.add(field_key)
        changes["added_field_updates"].append(field_key)

    lifecycle = output.lifecycle_update
    allowed_stages = _allowed_stages(context)
    for rule in lifecycle_rules:
        if lifecycle is not None and not bool(rule.get("override_existing", False)):
            continue
        target = str(rule.get("target_stage") or "")
        if not target or target not in allowed_stages:
            continue
        if not _rule_matches(rule, text=text, history_text=history_text):
            continue
        lifecycle = LifecycleUpdate(
            target_stage=target,
            reason=str(rule.get("reason") or "Inferred lifecycle movement."),
            evidence=[context.inbound_text],
            confidence=float(rule.get("confidence", 0.9)),
            source="agent",
            metadata={"reconciler": True, "rule_id": rule.get("id") or target},
        )
        changes["added_lifecycle_update"] = target
        break

    trace_metadata = dict(output.trace_metadata)
    if changes["added_field_updates"] or changes["added_lifecycle_update"]:
        trace_metadata["field_update_reconciler"] = changes
    return output.model_copy(
        update={
            "field_updates": updates,
            "lifecycle_update": lifecycle,
            "trace_metadata": trace_metadata,
        }
    )


def _infer_value(rule: dict[str, Any], *, text: str, history_text: str) -> Any | None:
    kind = str(rule.get("kind") or "term_value")
    if kind == "money_amount":
        if not _rule_matches(rule, text=text, history_text=history_text):
            return None
        amount = _extract_money_amount(text)
        return str(amount) if amount is not None else None
    if kind == "value_map":
        for item in list(rule.get("values") or []):
            if not isinstance(item, dict):
                continue
            if _terms_match(item.get("terms"), text):
                return item.get("value")
        return None
    if _rule_matches(rule, text=text, history_text=history_text):
        return rule.get("value")
    return None


def _rule_matches(rule: dict[str, Any], *, text: str, history_text: str) -> bool:
    if not _terms_match(rule.get("any_terms"), text):
        return False
    all_terms = [_fold(str(term)) for term in list(rule.get("all_terms") or [])]
    if any(term and term not in text for term in all_terms):
        return False
    context_terms = [_fold(str(term)) for term in list(rule.get("context_terms") or [])]
    if context_terms and not any(term in history_text for term in context_terms):
        return False
    return True


def _terms_match(terms: Any, text: str) -> bool:
    values = [_fold(str(term)) for term in list(terms or [])]
    return not values or any(term and term in text for term in values)


def _extract_money_amount(text: str) -> int | None:
    for match in _MONEY_RE.finditer(text):
        raw = match.group("number").replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        if match.group("unit"):
            value *= 1000
        if value >= 1000:
            return int(value)
    return None


def _config(context: TurnContext) -> dict[str, Any]:
    raw = (
        context.metadata.get("structured_reliability")
        or context.metadata.get("field_update_reconciler")
        or {}
    )
    return dict(raw) if isinstance(raw, dict) else {}


def _visible_fields(context: TurnContext) -> set[str]:
    if context.active_agent and context.active_agent.visible_contact_field_keys is not None:
        return set(context.active_agent.visible_contact_field_keys)
    return {field.key for field in context.contact_fields}


def _allowed_stages(context: TurnContext) -> set[str]:
    if context.active_agent and context.active_agent.allowed_lifecycle_stage_ids is not None:
        return set(context.active_agent.allowed_lifecycle_stage_ids)
    return set()


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")

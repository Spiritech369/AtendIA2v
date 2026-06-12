"""Flag-gated canonical CRM persistence for the Respond-Style direct route.

Accepted (already validated, evidence-backed) field writes of the turn are
mirrored into ``customer_field_values`` so the standard CRM/inbox UI shows
them. The mapping is pure tenant config: a canonical
``CustomerFieldDefinition`` opts in by listing the runtime field key in
``field_options.aliases`` (its own key also matches). Derived fields declare
``field_options.derivation = {"from": "<canonical key>", "map": {...}}`` and
are written by the system, never by the LLM.

With the deployment metadata flag off (the default) this module is a pure
no-op, so every other tenant/deployment keeps today's behavior bit-for-bit.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

CANONICAL_FIELDS_FLAG = "respond_style_canonical_fields_enabled"

_CHECKBOX_TRUE = {"true", "si", "1", "yes", "verdadero"}
_CHECKBOX_FALSE = {"false", "no", "0"}


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip().casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _resolve_count_spec(spec: Any, lookup: dict[str, Any]) -> int | None:
    """Resolve one count spec: an int, or {field, map, default}."""
    if isinstance(spec, (int, float)):
        return max(1, int(spec))
    if not isinstance(spec, dict):
        return None
    field = str(spec.get("field") or "")
    mapping = spec.get("map") if isinstance(spec.get("map"), dict) else {}
    raw = lookup.get(field)
    if raw not in (None, ""):
        folded = _fold(raw)
        for key, count in mapping.items():
            if _fold(key) == folded:
                try:
                    return max(1, int(count))
                except (TypeError, ValueError):
                    break
    try:
        return max(1, int(spec.get("default") or 0)) if spec.get("default") else None
    except (TypeError, ValueError):
        return None


def _doc_required_count(
    options: dict[str, Any],
    lookup: dict[str, Any],
    plan_value: str | None = None,
) -> int:
    """How many distinct documents this definition needs. Resolution order:
    ``required_count_by_plan`` (per-plan spec, e.g. Recibos needs 2 months of
    receipts while Tarjeta needs 1 month), then ``required_count_by``
    ({field, map, default}), then static ``required_count`` — pure config."""
    by_plan = options.get("required_count_by_plan")
    if isinstance(by_plan, dict) and plan_value:
        folded_plan = _fold(plan_value)
        for plan_key, spec in by_plan.items():
            if _fold(plan_key) == folded_plan:
                resolved = _resolve_count_spec(spec, lookup)
                if resolved is not None:
                    return resolved
                break
    by = options.get("required_count_by")
    if isinstance(by, dict):
        field = str(by.get("field") or "")
        mapping = by.get("map") if isinstance(by.get("map"), dict) else {}
        raw = lookup.get(field)
        if raw not in (None, ""):
            folded = _fold(raw)
            for key, count in mapping.items():
                if _fold(key) == folded:
                    try:
                        return max(1, int(count))
                    except (TypeError, ValueError):
                        break
        try:
            return max(1, int(by.get("default") or 1))
        except (TypeError, ValueError):
            return 1
    try:
        return max(1, int(options.get("required_count") or 1))
    except (TypeError, ValueError):
        return 1


def _doc_matched_count(options: dict[str, Any], items: Any) -> int:
    """Distinct received items matching this definition's aliases (exact or
    ``alias_`` prefix, e.g. recibo_nomina_semana_14)."""
    if isinstance(items, str):
        items = [part.strip() for part in items.split(",")]
    if not isinstance(items, list):
        return 0
    aliases = [
        _fold(alias) for alias in (options.get("aliases") or []) if str(alias).strip()
    ]
    matched: set[str] = set()
    for item in items:
        folded = _fold(item)
        if not folded:
            continue
        if any(folded == alias or folded.startswith(alias + "_") for alias in aliases):
            matched.add(folded)
    return len(matched)


def _doc_target_state(
    options: dict[str, Any],
    *,
    plan_value: str | None,
    items: Any,
    lookup: dict[str, Any],
) -> str | None:
    """Counter-based document state. Receiving N of M keeps the field in
    ``pendiente (N/M)`` — a document is only ``recibido`` when its full
    count arrived. Vision claims never count as received documents."""
    required_for = options.get("required_for_plans")
    if not isinstance(required_for, list):
        return None
    matched = _doc_matched_count(options, items)
    in_plan = False
    if plan_value:
        folded_plan = _fold(plan_value)
        in_plan = any(_fold(item) == folded_plan for item in required_for)
    if in_plan:
        needed = _doc_required_count(options, lookup, plan_value)
        if matched >= needed:
            return "recibido"
        if matched > 0:
            return f"pendiente ({matched}/{needed})"
        return "pendiente"
    if matched > 0:
        return "recibido"
    if plan_value:
        return "no_aplica"
    return None


def _coerce(definition: Any, value: Any) -> str | None:
    """Coerce a runtime value into the canonical definition's stored text.
    Returns None when the value cannot be represented safely (skip, never
    guess)."""
    if value is None:
        return None
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value if str(item).strip())
    field_type = str(getattr(definition, "field_type", "") or "")
    field_options = getattr(definition, "field_options", None) or {}
    options = field_options.get("choices") or field_options.get("options")
    if field_type == "checkbox":
        folded = _fold(value)
        true_values = {
            _fold(item) for item in field_options.get("true_values") or []
        } or _CHECKBOX_TRUE
        false_values = {
            _fold(item) for item in field_options.get("false_values") or []
        } or _CHECKBOX_FALSE
        if folded in true_values:
            return "true"
        if folded in false_values:
            return "false"
        return None
    if field_type == "select" and isinstance(options, list) and options:
        folded = _fold(value)
        for option in options:
            label = option.get("value") if isinstance(option, dict) else option
            if _fold(label) == folded:
                return str(label)
        return None
    text = str(value).strip()
    return text or None


async def persist_canonical_fields(
    session: Any,
    *,
    deployment: Any,
    tenant_id: str,
    conversation_id: str,
    audit_entries: list[Any],
    runtime_values: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mirror this turn's accepted field writes into the canonical CRM store
    and apply config-declared derivations. Returns ``None`` when the
    deployment did not opt in; otherwise an auditable summary."""
    metadata = dict(getattr(deployment, "metadata_json", None) or {})
    if metadata.get(CANONICAL_FIELDS_FLAG) is not True:
        return None

    from sqlalchemy import select

    from atendia.db.models.conversation import Conversation
    from atendia.db.models.customer_fields import (
        CustomerFieldDefinition,
        CustomerFieldUpdateEvidence,
        CustomerFieldValue,
    )

    conversation = await session.get(Conversation, UUID(str(conversation_id)))
    if conversation is None:
        return {"enabled": True, "applied": [], "derived": [], "reason": "no_conversation"}
    customer_id = conversation.customer_id

    definitions = (
        (
            await session.execute(
                select(CustomerFieldDefinition).where(
                    CustomerFieldDefinition.tenant_id == UUID(str(tenant_id))
                )
            )
        )
        .scalars()
        .all()
    )
    by_alias: dict[str, Any] = {}
    by_key: dict[str, Any] = {}
    for definition in definitions:
        by_key[definition.key] = definition
        by_alias.setdefault(_fold(definition.key), definition)
        aliases = (definition.field_options or {}).get("aliases") or []
        for alias in aliases:
            by_alias.setdefault(_fold(alias), definition)

    async def _upsert(
        definition: Any, value: str, *, source: str, reason: str | None
    ) -> str | None:
        row = await session.get(
            CustomerFieldValue, (customer_id, definition.id)
        )
        old_value = row.value if row is not None else None
        if old_value == value:
            return old_value
        if row is None:
            session.add(
                CustomerFieldValue(
                    customer_id=customer_id,
                    field_definition_id=definition.id,
                    value=value,
                )
            )
        else:
            row.value = value
        session.add(
            CustomerFieldUpdateEvidence(
                tenant_id=UUID(str(tenant_id)),
                customer_id=customer_id,
                field_definition_id=definition.id,
                field_key=definition.key,
                old_value=old_value,
                new_value=value,
                source=source,
                reason=reason,
                confidence=0.9,
                status="applied",
            )
        )
        return old_value

    applied: list[dict[str, Any]] = []
    for entry in audit_entries:
        if getattr(entry, "status", None) != "accepted":
            continue
        definition = by_alias.get(_fold(getattr(entry, "field_key", "")))
        if definition is None:
            continue
        coerced = _coerce(definition, getattr(entry, "new_value", None))
        if coerced is None:
            logger.info(
                "respond_style_canonical_fields skip key=%s (uncoercible)",
                getattr(entry, "field_key", ""),
            )
            continue
        await _upsert(
            definition,
            coerced,
            source="respond_style_runtime",
            reason=str(getattr(entry, "reason", "") or "validated_field_write"),
        )
        applied.append(
            {"key": definition.key, "label": definition.label, "value": coerced}
        )

    derived: list[dict[str, Any]] = []
    applied_by_key = {item["key"]: item["value"] for item in applied}
    for definition in definitions:
        derivation = (definition.field_options or {}).get("derivation")
        if not isinstance(derivation, dict):
            continue
        source_key = str(derivation.get("from") or derivation.get("from_field") or "")
        mapping = derivation.get("map")
        if not source_key or not isinstance(mapping, dict):
            continue
        source_value = applied_by_key.get(source_key)
        if source_value is None:
            source_def = by_key.get(source_key)
            if source_def is None:
                continue
            row = await session.get(
                CustomerFieldValue, (customer_id, source_def.id)
            )
            source_value = row.value if row is not None else None
        if source_value is None:
            continue
        target = None
        for map_key, map_value in mapping.items():
            if _fold(map_key) == _fold(source_value):
                target = str(map_value)
                break
        if target is None:
            continue
        old = await _upsert(
            definition,
            target,
            source="derivation",
            reason=f"derived_from:{source_key}",
        )
        if old != target:
            derived.append(
                {"key": definition.key, "label": definition.label, "value": target}
            )

    # Config-driven document matrix. A definition opts in by declaring in
    # field_options: ``required_for_plans`` (list of plan values),
    # ``plan_field`` (the canonical field holding the plan) and optionally
    # ``received_from`` (the runtime list field carrying received doc names).
    # On every turn: pending/no_aplica follow the assigned plan, and items in
    # the runtime list flip their matching doc to "recibido" (never back).
    docs: list[dict[str, Any]] = []

    async def _stored_value(canonical_key: str) -> str | None:
        if canonical_key in applied_by_key:
            return applied_by_key[canonical_key]
        source_def = by_key.get(canonical_key)
        if source_def is None:
            return None
        row = await session.get(CustomerFieldValue, (customer_id, source_def.id))
        return row.value if row is not None else None

    runtime_values = runtime_values or {}
    for definition in definitions:
        options = definition.field_options or {}
        required_for = options.get("required_for_plans")
        plan_field = str(options.get("plan_field") or "")
        if not isinstance(required_for, list) or not plan_field:
            continue
        current = await _stored_value(definition.key)
        if current == "recibido":
            continue
        plan_value = await _stored_value(plan_field)
        received_from = str(options.get("received_from") or "")
        items = runtime_values.get(received_from) if received_from else None
        target_state = _doc_target_state(
            options,
            plan_value=plan_value,
            items=items,
            lookup=runtime_values,
        )
        if target_state is None or target_state == current:
            continue
        await _upsert(
            definition,
            target_state,
            source="docs_matrix",
            reason=f"plan:{plan_value or 'sin_plan'}",
        )
        docs.append(
            {"key": definition.key, "label": definition.label, "value": target_state}
        )

    return {"enabled": True, "applied": applied, "derived": derived, "docs": docs}


async def record_system_messages(
    session: Any,
    *,
    tenant_id: str,
    conversation_id: str,
    texts: list[str],
) -> None:
    """Internal-only chat notes (direction='system'), same convention the
    legacy runner used. Never customer-visible, never sent anywhere."""
    if not texts:
        return
    from atendia.db.models.message import MessageRow

    now = datetime.now(UTC)
    for text in texts:
        session.add(
            MessageRow(
                conversation_id=UUID(str(conversation_id)),
                tenant_id=UUID(str(tenant_id)),
                direction="system",
                text=text,
                delivery_status=None,
                metadata_json={"source": "respond_style_runtime"},
                sent_at=now,
            )
        )

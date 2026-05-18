"""Apply NLU-extracted entities to customer.attrs or to field_suggestions.

Called from conversation_runner after the per-turn NLU result is merged
into conversation_state.extracted_data. Stays a thin orchestrator over
the pure decision logic in field_extraction_mapping.decide_action.

Returns the list of AUTO-applied changes so the caller can fan out
FIELD_UPDATED system events (see runner/conversation_events.py). The
SUGGEST path is intentionally NOT surfaced — those values aren't on
the customer yet, they're pending operator review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.conversation_state import ExtractedField
from atendia.db.models.customer import Customer
from atendia.db.models.customer_fields import CustomerFieldDefinition, CustomerFieldValue
from atendia.db.models.field_suggestion import FieldSuggestion
from atendia.runner.field_extraction_mapping import (
    Action,
    CONFIDENCE_AUTO_THRESHOLD,
    decide_action,
    map_entity_to_attr,
)

_log = logging.getLogger(__name__)


def _coerce_custom_field_value(
    definition: CustomerFieldDefinition,
    value: Any,
) -> tuple[Any, str]:
    """Normalize AI values before writing tenant-configured fields.

    The public customer-fields endpoint already canonicalizes operator
    edits. AI auto-apply must obey the same shape so a checkbox never
    stores arbitrary text like "15".
    """
    if definition.field_type != "checkbox":
        return value, "" if value is None else str(value)

    normalized: bool
    if isinstance(value, bool):
        normalized = value
    elif isinstance(value, int | float):
        normalized = value >= 6 if "antig" in definition.key.casefold() else value != 0
    elif isinstance(value, str):
        raw = value.strip()
        lowered = raw.casefold()
        if lowered in {"true", "1", "yes", "si", "sí", "s"}:
            normalized = True
        elif lowered in {"false", "0", "no", "n"}:
            normalized = False
        else:
            try:
                number = float(raw.replace(",", "."))
            except ValueError:
                normalized = bool(raw)
            else:
                normalized = number >= 6 if "antig" in definition.key.casefold() else number != 0
    else:
        normalized = bool(value)

    return normalized, "true" if normalized else "false"


@dataclass(frozen=True)
class AppliedFieldChange:
    """A single AUTO-applied entity → attr write.

    `entity_key` is what NLU produced, `attr_key` is the canonical
    customer.attrs key after `map_entity_to_attr`. `old_value` may be
    None when the field was previously empty.
    """

    entity_key: str
    attr_key: str
    old_value: Any
    new_value: Any
    confidence: float


async def apply_ai_extractions(
    *,
    session: AsyncSession,
    tenant_id: UUID | str,
    customer_id: UUID | str,
    conversation_id: UUID | str | None,
    turn_number: int,
    entities: dict[str, ExtractedField],
    inbound_text: str | None = None,
) -> list[AppliedFieldChange]:
    """Walk every entity, classify with decide_action, then persist.

    Reads customer.attrs once, applies all AUTO changes in a single
    UPDATE, then inserts FieldSuggestion rows for each SUGGEST case.

    Returns the list of AUTO changes (in input order) so the caller can
    emit FIELD_UPDATED events / system messages. Returns an empty list
    when nothing changed (customer missing, no entities, all SKIP/NOOP).
    """
    if not entities:
        return []

    customer = (
        await session.execute(select(Customer).where(Customer.id == customer_id))
    ).scalar_one_or_none()
    if customer is None:
        _log.warning("apply_ai_extractions: customer %s not found", customer_id)
        return []

    current_attrs: dict = dict(customer.attrs or {})
    next_attrs = dict(current_attrs)
    custom_defs = {
        row.key: row
        for row in (
            await session.execute(
                select(CustomerFieldDefinition).where(
                    CustomerFieldDefinition.tenant_id == tenant_id,
                    CustomerFieldDefinition.key.in_(list(entities.keys())),
                )
            )
        )
        .scalars()
        .all()
    }
    custom_values = {
        row.field_definition_id: row
        for row in (
            await session.execute(
                select(CustomerFieldValue).where(
                    CustomerFieldValue.customer_id == customer_id,
                    CustomerFieldValue.field_definition_id.in_(
                        [d.id for d in custom_defs.values()]
                    ),
                )
            )
        )
        .scalars()
        .all()
    }
    suggestions: list[FieldSuggestion] = []
    applied: list[AppliedFieldChange] = []
    dirty = False

    for entity_key, field in entities.items():
        custom_def = custom_defs.get(entity_key)
        attr_key = map_entity_to_attr(entity_key) or (custom_def.key if custom_def else None)
        if attr_key is None:
            continue

        current_custom_value = None
        if custom_def and custom_def.id in custom_values:
            current_custom_value = custom_values[custom_def.id].value
        current = current_custom_value if custom_def else current_attrs.get(attr_key)
        action = decide_action(
            current_value=current,
            new_value=field.value,
            confidence=float(field.confidence),
        )
        if (
            custom_def is not None
            and action == Action.SUGGEST
            and float(field.confidence) >= CONFIDENCE_AUTO_THRESHOLD
        ):
            action = Action.AUTO

        if action == Action.AUTO:
            stored_attr_value = field.value
            stored_custom_value = str(field.value)
            if custom_def is not None:
                stored_attr_value, stored_custom_value = _coerce_custom_field_value(
                    custom_def,
                    field.value,
                )
            next_attrs[attr_key] = stored_attr_value
            dirty = True
            if custom_def is not None:
                existing = custom_values.get(custom_def.id)
                if existing is not None:
                    existing.value = stored_custom_value
                    session.add(existing)
                else:
                    new_value = CustomerFieldValue(
                        customer_id=customer_id,
                        field_definition_id=custom_def.id,
                        value=stored_custom_value,
                    )
                    session.add(new_value)
                    custom_values[custom_def.id] = new_value
            applied.append(
                AppliedFieldChange(
                    entity_key=entity_key,
                    attr_key=attr_key,
                    old_value=current,
                    new_value=stored_attr_value,
                    confidence=float(field.confidence),
                )
            )
        elif action == Action.SUGGEST:
            suggestions.append(
                FieldSuggestion(
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    turn_number=turn_number,
                    key=attr_key,
                    suggested_value=str(field.value),
                    confidence=float(field.confidence),
                    evidence_text=inbound_text,
                    status="pending",
                )
            )
        # SKIP and NOOP: nothing to persist

    if dirty:
        customer.attrs = next_attrs
        session.add(customer)

    for sugg in suggestions:
        session.add(sugg)

    return applied

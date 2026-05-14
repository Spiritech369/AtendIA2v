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
from atendia.db.models.field_suggestion import FieldSuggestion
from atendia.runner.field_extraction_mapping import (
    Action,
    decide_action,
    map_entity_to_attr,
)

_log = logging.getLogger(__name__)


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
    suggestions: list[FieldSuggestion] = []
    applied: list[AppliedFieldChange] = []
    dirty = False

    for entity_key, field in entities.items():
        attr_key = map_entity_to_attr(entity_key)
        if attr_key is None:
            continue

        current = current_attrs.get(attr_key)
        action = decide_action(
            current_value=current,
            new_value=field.value,
            confidence=float(field.confidence),
        )

        if action == Action.AUTO:
            next_attrs[attr_key] = field.value
            dirty = True
            applied.append(AppliedFieldChange(
                entity_key=entity_key,
                attr_key=attr_key,
                old_value=current,
                new_value=field.value,
                confidence=float(field.confidence),
            ))
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

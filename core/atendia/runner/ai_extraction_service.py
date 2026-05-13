"""Apply NLU-extracted entities to customer.attrs or to field_suggestions.

Called from conversation_runner after the per-turn NLU result is merged
into conversation_state.extracted_data. Stays a thin orchestrator over
the pure decision logic in field_extraction_mapping.decide_action.
"""
from __future__ import annotations

import logging
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


async def apply_ai_extractions(
    *,
    session: AsyncSession,
    tenant_id: UUID | str,
    customer_id: UUID | str,
    conversation_id: UUID | str | None,
    turn_number: int,
    entities: dict[str, ExtractedField],
    inbound_text: str | None = None,
) -> None:
    """Walk every entity, classify with decide_action, then persist.

    Reads customer.attrs once, applies all AUTO changes in a single
    UPDATE, then inserts FieldSuggestion rows for each SUGGEST case.
    """
    if not entities:
        return

    customer = (
        await session.execute(select(Customer).where(Customer.id == customer_id))
    ).scalar_one_or_none()
    if customer is None:
        _log.warning("apply_ai_extractions: customer %s not found", customer_id)
        return

    current_attrs: dict = dict(customer.attrs or {})
    next_attrs = dict(current_attrs)
    suggestions: list[FieldSuggestion] = []
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

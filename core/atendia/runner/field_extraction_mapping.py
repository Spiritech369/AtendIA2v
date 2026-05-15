"""Pure decision logic for promoting NLU entities to customer.attrs.

The runner imports `decide_action` and `map_entity_to_attr` to choose
between auto-applying, creating a suggestion, or skipping each entity
NLU produced. Rules are documented in
`docs/plans/2026-05-13-ai-field-extraction-design.md`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

CONFIDENCE_AUTO_THRESHOLD = 0.85
CONFIDENCE_SUGGESTION_MIN = 0.60

ENTITY_TO_ATTR: dict[str, str] = {
    "brand": "marca",
    "marca": "marca",
    "model": "modelo_interes",
    "modelo": "modelo_interes",
    "modelo_interes": "modelo_interes",
    "plan": "plan_credito",
    "credit_plan": "plan_credito",
    "plan_credito": "plan_credito",
    "credit_type": "tipo_credito",
    "income_type": "tipo_credito",
    "tipo_credito": "tipo_credito",
    "city": "city",
    "ciudad": "city",
    "estimated_value": "estimated_value",
    "valor_estimado": "estimated_value",
    "labor_seniority": "antiguedad_laboral_meses",
    "antiguedad_laboral_meses": "antiguedad_laboral_meses",
}


class Action(str, Enum):
    AUTO = "auto"  # apply directly to customer.attrs
    SUGGEST = "suggest"  # create a pending suggestion
    SKIP = "skip"  # do nothing
    NOOP = "noop"  # value already present and equal


def map_entity_to_attr(entity_key: str) -> str | None:
    """Return the canonical attr key for an NLU entity, or None if unknown."""
    return ENTITY_TO_ATTR.get(entity_key)


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    return str(value).strip()


def decide_action(*, current_value: Any, new_value: Any, confidence: float) -> Action:
    """Decide what to do with an NLU-detected value for an attr.

    See the design doc for the full rules table. Summary:
    - empty + conf >= 0.85 → AUTO
    - empty + conf 0.60-0.84 → SUGGEST
    - empty + conf < 0.60 → SKIP
    - same value (normalized) → NOOP
    - different value + conf >= 0.60 → SUGGEST (never silent overwrite)
    - different value + conf < 0.60 → SKIP
    """
    new_norm = _norm(new_value)
    if new_norm is None:
        return Action.SKIP

    current_norm = _norm(current_value)

    if current_norm is not None and current_norm == new_norm:
        return Action.NOOP

    if current_norm is None:
        if confidence >= CONFIDENCE_AUTO_THRESHOLD:
            return Action.AUTO
        if confidence >= CONFIDENCE_SUGGESTION_MIN:
            return Action.SUGGEST
        return Action.SKIP

    # Different value already present — never silent overwrite.
    if confidence >= CONFIDENCE_SUGGESTION_MIN:
        return Action.SUGGEST
    return Action.SKIP

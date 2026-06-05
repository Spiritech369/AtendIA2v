from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from atendia.text_normalization import normalize_whatsapp_text

_PERCENT_PLAN_RE = re.compile(
    r"(?<!\d)(?P<percent>\d{1,3})(?:\s*%|\s+por\s+ciento)(?=[^\d]|$)"
)
_CONTEXTUAL_PLAN_RE = re.compile(
    r"(?:\bal\b|\bcon(?:\s+el)?\b)\s+(?P<percent>\d{1,3})(?=[^\d]|$)"
)
_NAMED_DOWN_PAYMENT_RE = re.compile(
    r"(?<!\d)(?P<percent>\d{1,3})\s+(?:de\s+)?(?:enganche|anticipo|inicial)(?=[^\d]|$)"
)
_STRONG_CHANGE_MARKERS = {
    "actualiza",
    "actualizar",
    "cambia",
    "cambiar",
    "cambialo",
    "cambiala",
    "cambio",
    "mejor",
    "prefiero",
}
_SELECTION_MARKERS = {"dame", "quiero"}
_SELECTION_CONTEXT = {"al", "anticipo", "con", "cotiza", "cotizacion", "cotizar", "enganche", "inicial"}


@dataclass(frozen=True)
class ExplicitDownPaymentChange:
    requested_plan_code: str
    requested_percent: Decimal


def extract_explicit_down_payment_change(text: str) -> ExplicitDownPaymentChange | None:
    normalized = normalize_whatsapp_text(text)
    tokens = set(normalized.split())
    if not tokens:
        return None
    explicit_request = bool(tokens & _STRONG_CHANGE_MARKERS) or bool(
        tokens & _SELECTION_MARKERS and tokens & _SELECTION_CONTEXT
    )
    if not explicit_request:
        return None
    match = (
        _PERCENT_PLAN_RE.search(normalized)
        or _CONTEXTUAL_PLAN_RE.search(normalized)
        or _NAMED_DOWN_PAYMENT_RE.search(normalized)
    )
    if match is None:
        return None
    percent = _percent_value(match.group("percent"))
    if percent is None or percent <= 0 or percent > 100:
        return None
    return ExplicitDownPaymentChange(
        requested_plan_code=_plan_code(percent),
        requested_percent=percent,
    )


def minimum_plan_code_for_credit(*, pipeline: Any, credit_value: Any) -> str | None:
    catalog = getattr(pipeline, "selection_catalog", {}) or {}
    if not isinstance(catalog, Mapping):
        return None
    normalized_credit = normalize_whatsapp_text(credit_value)
    for selection_key, raw_entry in catalog.items():
        entry = raw_entry if isinstance(raw_entry, Mapping) else {}
        labels = {
            normalize_whatsapp_text(selection_key),
            normalize_whatsapp_text(entry.get("label")),
        }
        if normalized_credit not in labels:
            continue
        updates = entry.get("field_updates")
        if not isinstance(updates, Mapping):
            return None
        for field_name in ("ENGANCHE", "PLAN", "plan"):
            candidate = updates.get(field_name)
            if candidate not in (None, ""):
                return str(candidate).strip()
    return None


def requested_plan_meets_minimum(
    *,
    requested: ExplicitDownPaymentChange,
    minimum_plan_code: str,
) -> bool:
    minimum_percent = _percent_value(minimum_plan_code)
    return minimum_percent is not None and requested.requested_percent >= minimum_percent


def quote_payload_has_plan(payload: Mapping[str, Any], requested_plan_code: str) -> bool:
    payment_options = payload.get("payment_options")
    if not isinstance(payment_options, Mapping):
        return False
    return any(_same_plan_code(key, requested_plan_code) for key in payment_options)


def _same_plan_code(left: Any, right: Any) -> bool:
    left_percent = _percent_value(left)
    right_percent = _percent_value(right)
    if left_percent is not None and right_percent is not None:
        return left_percent == right_percent
    return normalize_whatsapp_text(left) == normalize_whatsapp_text(right)


def _percent_value(raw: Any) -> Decimal | None:
    match = re.search(r"\d{1,3}(?:[.,]\d+)?", str(raw or ""))
    if match is None:
        return None
    try:
        return Decimal(match.group(0).replace(",", "."))
    except InvalidOperation:
        return None


def _plan_code(percent: Decimal) -> str:
    text = format(percent.normalize(), "f")
    return f"{text}%"


__all__ = [
    "ExplicitDownPaymentChange",
    "extract_explicit_down_payment_change",
    "minimum_plan_code_for_credit",
    "quote_payload_has_plan",
    "requested_plan_meets_minimum",
]

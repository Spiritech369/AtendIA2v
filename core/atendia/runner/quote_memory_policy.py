from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from atendia.text_normalization import normalize_whatsapp_text

_LAST_QUOTE_RE = re.compile(
    r"Ultima cotizacion:\s*(?P<name>[^;.]+);\s*"
    r"plan\s+(?P<plan>[^;.]+);\s*"
    r"contado\s+\$(?P<cash>[\d,]+);\s*"
    r"enganche\s+\$(?P<down_payment>[\d,]+);\s*"
    r"pago\s+\$(?P<installment>[\d,]+)"
    r"(?:;\s*plazo\s+(?P<term_count>[\d,]+)\s+quincenas)?\.",
    flags=re.IGNORECASE,
)
_PREVIOUS_QUOTE_REFERENCES = (
    "la que me cotizaste ayer",
    "la misma que me dijiste",
    "la de la vez pasada",
    "me interesa la que me habias cotizado",
    "la que me habias cotizado",
    "esa que me cotizaste",
    "la que vimos",
)
_CHANGE_MARKERS = {"cambia", "cambiar", "cambio", "mejor", "prefiero", "actualiza"}


@dataclass(frozen=True)
class QuoteMemory:
    name: str
    requested_plan_code: str
    cash_price_mxn: int
    down_payment_mxn: int
    installment_mxn: int
    term_count: int | None = None

    def action_payload(self) -> dict[str, Any]:
        selected_plan: dict[str, Any] = {
            "down_payment_mxn": self.down_payment_mxn,
            "installment_mxn": self.installment_mxn,
            "frequency": "quincenal",
        }
        if self.term_count is not None:
            selected_plan["term_count"] = self.term_count
        return {
            "status": "ok",
            "kind": "quote_memory_recall",
            "name": self.name,
            "requested_plan_code": self.requested_plan_code,
            "cash_price_mxn": self.cash_price_mxn,
            "down_payment_mxn": self.down_payment_mxn,
            "installment_mxn": self.installment_mxn,
            "payment_options": {self.requested_plan_code: selected_plan},
            "source": {"memory": "customer_memory"},
        }


def extract_last_quote_from_summary(summary: str | None) -> QuoteMemory | None:
    matches = list(_LAST_QUOTE_RE.finditer(str(summary or "")))
    if len(matches) != 1:
        return None
    match = matches[0]
    return QuoteMemory(
        name=match.group("name").strip(),
        requested_plan_code=match.group("plan").strip(),
        cash_price_mxn=_money_value(match.group("cash")),
        down_payment_mxn=_money_value(match.group("down_payment")),
        installment_mxn=_money_value(match.group("installment")),
        term_count=(
            _money_value(match.group("term_count"))
            if match.group("term_count") is not None
            else None
        ),
    )


def is_previous_quote_reference(text: str) -> bool:
    normalized = normalize_whatsapp_text(text)
    tokens = set(normalized.split())
    if tokens & _CHANGE_MARKERS:
        return False
    return any(reference in normalized for reference in _PREVIOUS_QUOTE_REFERENCES)


def should_recall_last_quote(
    *,
    inbound_text: str,
    conversation_summary: str | None,
    extracted_data: dict[str, Any],
    credit_field: str = "CREDITO",
) -> QuoteMemory | None:
    if not is_previous_quote_reference(inbound_text):
        return None
    memory = extract_last_quote_from_summary(conversation_summary)
    if memory is None:
        return None
    values = _flat_values(extracted_data)
    if not _same_value(values.get("MOTO"), memory.name):
        return None
    if not _same_value(values.get("ENGANCHE"), memory.requested_plan_code):
        return None
    if values.get(credit_field) in (None, "", [], {}):
        return None
    return memory


def _flat_values(extracted_data: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): raw.get("value") if isinstance(raw, dict) and "value" in raw else raw
        for key, raw in (extracted_data or {}).items()
    }


def _same_value(left: Any, right: Any) -> bool:
    return normalize_whatsapp_text(left) == normalize_whatsapp_text(right)


def _money_value(value: str) -> int:
    return int(value.replace(",", ""))


__all__ = [
    "QuoteMemory",
    "extract_last_quote_from_summary",
    "is_previous_quote_reference",
    "should_recall_last_quote",
]

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from atendia.text_normalization import normalize_whatsapp_text

ANTIGUEDAD_LABORAL_FIELD_KEY = "ANTIGUEDAD_LABORAL"
ANTIGUEDAD_LABORAL_FIELD_TYPE = "duration"
ANTIGUEDAD_LABORAL_FIELD_OPTIONS: dict[str, Any] = {
    "semantic_role": "employment_seniority",
    "source": "user_message",
    "stores": {
        "raw_text": "string",
        "normalized_amount": "number",
        "normalized_unit": "months|years",
        "normalized_months": "number",
        "estimated_start_date": "date",
    },
    "derived_fields": {"FILTRO": {"enabled": True, "threshold_months": 6}},
}

EmploymentSeniorityUnit = Literal["months", "years"]

_DURATION_RE = re.compile(
    r"\b(?P<amount>\d+(?:[.,]\d+)?|un|una|uno|medio|media)\s+"
    r"(?P<unit>anos?|anios?|mes(?:es)?)\b",
    flags=re.IGNORECASE,
)
_AMBIGUOUS_REPLIES = {
    "si",
    "s",
    "ok",
    "okay",
    "va",
    "sale",
    "mas o menos",
    "masomenos",
    "poquito",
    "no se",
    "nose",
}
_WORD_AMOUNTS = {
    "un": 1.0,
    "una": 1.0,
    "uno": 1.0,
    "medio": 0.5,
    "media": 0.5,
}
_MONTH_ALIASES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_SINCE_MONTH_RE = re.compile(
    r"\b(?:desde|entro|entre|entre?\s+a)\s+"
    r"(?P<month>enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
    r"(?:\s+(?:del?|de)\s+(?P<year>(?:ano)\s+pasado|\d{4}))?\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class EmploymentSeniorityDuration:
    raw_text: str
    normalized_amount: float
    normalized_unit: EmploymentSeniorityUnit
    normalized_months: int
    estimated_start_date: str | None = None
    source: str = "user_message"
    confidence: float = 0.95

    @property
    def display_value(self) -> str:
        amount = _format_amount(self.normalized_amount)
        if self.normalized_unit == "months":
            unit = "mes" if self.normalized_amount == 1 else "meses"
        else:
            unit = "año" if self.normalized_amount == 1 else "años"
        return f"{amount} {unit}"

    def as_structured_value(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_amount": self.normalized_amount,
            "normalized_unit": self.normalized_unit,
            "normalized_months": self.normalized_months,
            "estimated_start_date": self.estimated_start_date,
            "source": self.source,
        }


def parse_employment_seniority(
    text: str,
    *,
    reference_date: date | None = None,
) -> EmploymentSeniorityDuration | None:
    raw_text = str(text or "").strip()
    normalized = normalize_whatsapp_text(raw_text, keep_percent=False)
    if not normalized or normalized in _AMBIGUOUS_REPLIES:
        return None

    match = _DURATION_RE.search(normalized)
    if match is not None:
        amount = _parse_amount(match.group("amount"))
        if amount is None or amount <= 0:
            return None

        unit = _normalize_unit(match.group("unit"))
        normalized_months = round(amount * 12) if unit == "years" else round(amount)
        if normalized_months <= 0:
            return None

        return EmploymentSeniorityDuration(
            raw_text=raw_text,
            normalized_amount=amount,
            normalized_unit=unit,
            normalized_months=normalized_months,
        )

    return _parse_since_month_expression(
        raw_text=raw_text,
        normalized=normalized,
        reference_date=reference_date or date.today(),
    )


def is_valid_seniority_duration(text: str) -> bool:
    return parse_employment_seniority(text) is not None


def is_ambiguous_seniority_reply(text: str) -> bool:
    normalized = normalize_whatsapp_text(text, keep_percent=False)
    return bool(normalized) and normalized in _AMBIGUOUS_REPLIES


def employment_seniority_field_updates(text: str) -> dict[str, Any]:
    seniority = parse_employment_seniority(text)
    if seniority is None:
        return {}
    return {
        ANTIGUEDAD_LABORAL_FIELD_KEY: seniority.as_structured_value(),
        "FILTRO": seniority.normalized_months >= 6,
    }


def _parse_amount(value: str) -> float | None:
    normalized = normalize_whatsapp_text(value, keep_percent=False)
    if normalized in _WORD_AMOUNTS:
        return _WORD_AMOUNTS[normalized]
    try:
        return float(normalized.replace(",", "."))
    except ValueError:
        return None


def _normalize_unit(value: str) -> EmploymentSeniorityUnit:
    normalized = normalize_whatsapp_text(value, keep_percent=False)
    return "months" if normalized.startswith("mes") else "years"


def _parse_since_month_expression(
    *,
    raw_text: str,
    normalized: str,
    reference_date: date,
) -> EmploymentSeniorityDuration | None:
    match = _SINCE_MONTH_RE.search(normalized)
    if match is None:
        return None
    month_token = normalize_whatsapp_text(match.group("month"), keep_percent=False)
    month = _MONTH_ALIASES.get(month_token)
    if month is None:
        return None
    year_token = normalize_whatsapp_text(match.group("year") or "", keep_percent=False)
    year = reference_date.year
    if year_token:
        if "pasado" in year_token:
            year -= 1
        elif year_token.isdigit():
            year = int(year_token)
    elif month > reference_date.month:
        year -= 1

    normalized_months = max(
        1,
        (reference_date.year - year) * 12 + (reference_date.month - month),
    )
    normalized_amount, normalized_unit = _amount_and_unit_from_months(normalized_months)
    return EmploymentSeniorityDuration(
        raw_text=raw_text,
        normalized_amount=normalized_amount,
        normalized_unit=normalized_unit,
        normalized_months=normalized_months,
        estimated_start_date=f"{year:04d}-{month:02d}-01",
        confidence=0.9,
    )


def _amount_and_unit_from_months(months: int) -> tuple[float, EmploymentSeniorityUnit]:
    if months >= 12 and months % 12 == 0:
        return months / 12, "years"
    return float(months), "months"


def _format_amount(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value).rstrip("0").rstrip(".")


__all__ = [
    "ANTIGUEDAD_LABORAL_FIELD_KEY",
    "ANTIGUEDAD_LABORAL_FIELD_OPTIONS",
    "ANTIGUEDAD_LABORAL_FIELD_TYPE",
    "EmploymentSeniorityDuration",
    "employment_seniority_field_updates",
    "is_ambiguous_seniority_reply",
    "is_valid_seniority_duration",
    "parse_employment_seniority",
]

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from atendia.runner.employment_seniority_policy import parse_employment_seniority
from atendia.text_normalization import normalize_whatsapp_text

COMMERCIAL_CREDIT_PLAN_ORDER: tuple[str, ...] = (
    "Nomina Tarjeta",
    "Nomina Recibos",
    "Pensionados",
    "Negocio SAT",
    "Sin Comprobantes",
    "Guardia de Seguridad",
)

_COMMERCIAL_CREDIT_PLAN_SPECS: dict[str, dict[str, Any]] = {
    "Nomina Tarjeta": {
        "visible_label": "Me depositan nomina en tarjeta",
        "down_payment": "10%",
        "aliases": [
            "nomina tarjeta",
            "nomina en tarjeta",
            "me depositan nomina",
            "me depositan nomina en tarjeta",
            "depositan nomina",
            "tarjeta",
        ],
    },
    "Nomina Recibos": {
        "visible_label": "Me pagan con recibos de nomina",
        "down_payment": "15%",
        "aliases": [
            "nomina recibos",
            "recibos de nomina",
            "me pagan con recibos",
            "me pagan con recibos de nomina",
        ],
    },
    "Pensionados": {
        "visible_label": "Soy pensionado",
        "down_payment": "10%",
        "aliases": ["pensionado", "pensionados", "soy pensionado"],
    },
    "Negocio SAT": {
        "visible_label": "Tengo negocio registrado en SAT",
        "down_payment": "15%",
        "aliases": [
            "negocio sat",
            "tengo negocio",
            "registrado en sat",
            "sat",
        ],
    },
    "Sin Comprobantes": {
        "visible_label": "Me pagan sin comprobantes",
        "down_payment": "20%",
        "aliases": [
            "sin comprobantes",
            "me pagan sin comprobantes",
            "me pagan por fuera",
            "por fuera",
            "efectivo",
        ],
    },
    "Guardia de Seguridad": {
        "visible_label": "Soy guardia de seguridad",
        "down_payment": "30%",
        "aliases": [
            "guardia",
            "soy guardia",
            "guardia de seguridad",
            "soy guardia de seguridad",
            "seguridad privada",
        ],
    },
}


def build_credit_plan_menu(pipeline: Any) -> list[dict[str, Any]]:
    selection_catalog = getattr(pipeline, "selection_catalog", {}) or {}
    document_requirements = getattr(pipeline, "document_requirements", {}) or {}
    configured_selection_keys = _configured_selection_keys(selection_catalog, document_requirements)

    menu: list[dict[str, Any]] = []
    display_number = 1
    for canonical_credit_plan in COMMERCIAL_CREDIT_PLAN_ORDER:
        requirements_key = _configured_key_for_canonical_plan(
            canonical_credit_plan,
            configured_selection_keys,
            selection_catalog,
        )
        if requirements_key is None:
            continue
        spec = _COMMERCIAL_CREDIT_PLAN_SPECS[canonical_credit_plan]
        configured_entry = _mapping(selection_catalog.get(requirements_key))
        visible_label = str(
            spec.get("visible_label")
            or configured_entry.get("label")
            or canonical_credit_plan
        ).strip()
        down_payment = str(
            spec.get("down_payment")
            or _mapping(configured_entry.get("field_updates")).get("ENGANCHE")
            or ""
        ).strip()
        aliases = _dedupe(
            [
                str(display_number),
                canonical_credit_plan,
                str(configured_entry.get("label") or canonical_credit_plan),
                visible_label,
                *[str(alias) for alias in _as_list(configured_entry.get("aliases"))],
                *[str(alias) for alias in _as_list(spec.get("aliases"))],
            ]
        )
        menu.append(
            {
                "display_number": display_number,
                "visible_label": visible_label,
                "canonical_credit_plan": canonical_credit_plan,
                "down_payment": down_payment or None,
                "aliases": aliases,
                "requirements_key": requirements_key,
                "selection_key": canonical_credit_plan,
                "selection_label": canonical_credit_plan,
                "menu_index": display_number,
                "menu_prompt": visible_label,
                "plan": down_payment or None,
                "field_updates": {
                    "CREDITO": canonical_credit_plan,
                    "ENGANCHE": down_payment,
                },
            }
        )
        display_number += 1

    extra_keys = [
        key
        for key in configured_selection_keys
        if key not in {str(item["requirements_key"]) for item in menu}
    ]
    for extra_key in sorted(extra_keys):
        configured_entry = _mapping(selection_catalog.get(extra_key))
        visible_label = str(configured_entry.get("label") or extra_key).strip()
        down_payment = str(
            _mapping(configured_entry.get("field_updates")).get("ENGANCHE") or ""
        ).strip()
        aliases = _dedupe(
            [
                str(display_number),
                extra_key,
                visible_label,
                *[str(alias) for alias in _as_list(configured_entry.get("aliases"))],
            ]
        )
        menu.append(
            {
                "display_number": display_number,
                "visible_label": visible_label,
                "canonical_credit_plan": extra_key,
                "down_payment": down_payment or None,
                "aliases": aliases,
                "requirements_key": extra_key,
                "selection_key": extra_key,
                "selection_label": visible_label,
                "menu_index": display_number,
                "menu_prompt": visible_label,
                "plan": down_payment or None,
                "field_updates": {
                    "CREDITO": extra_key,
                    **({"ENGANCHE": down_payment} if down_payment else {}),
                },
            }
        )
        display_number += 1
    return menu


def resolve_credit_plan_option(
    input_text: str,
    pipeline: Any,
) -> dict[str, Any] | None:
    normalized_input = _normalize_lookup_key(input_text)
    if not normalized_input:
        return None
    if _looks_like_plain_seniority_text(input_text):
        return None
    menu = build_credit_plan_menu(pipeline)
    if not menu:
        return None

    exact_matches = [
        option
        for option in menu
        if normalized_input in _option_aliases(option)
    ]
    exact_unique = _unique_credit_plan_matches(exact_matches)
    if len(exact_unique) == 1:
        return exact_unique[0]
    if len(exact_unique) > 1:
        return None

    input_tokens = set(normalized_input.split())
    input_digits = set(re.findall(r"\d+", normalized_input))
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for option in menu:
        aliases = _option_aliases(option)
        for alias in aliases:
            score = _alias_match_score(
                normalized_input=normalized_input,
                input_tokens=input_tokens,
                input_digits=input_digits,
                alias=alias,
            )
            if score >= 0.75:
                scored.append((score, len(alias), option))

    if not scored:
        return None

    scored.sort(key=lambda item: (-item[0], -item[1], str(item[2].get("selection_key") or "")))
    top_score = scored[0][0]
    top_matches = _unique_credit_plan_matches(
        option for score, _length, option in scored if score == top_score
    )
    if len(top_matches) != 1:
        return None
    return top_matches[0]


def _looks_like_plain_seniority_text(input_text: str) -> bool:
    normalized_input = _normalize_lookup_key(input_text)
    if not normalized_input:
        return False
    if parse_employment_seniority(input_text) is None:
        return False
    tokens = set(normalized_input.split())
    income_markers = {
        "guardia",
        "policia",
        "pensionado",
        "pensionados",
        "tarjeta",
        "nomina",
        "recibos",
        "sat",
        "negocio",
        "efectivo",
        "didi",
        "uber",
        "fuera",
        "comprobantes",
        "depositan",
    }
    return not bool(tokens & income_markers)


def enforce_credit_plan_invariants(
    credit_plan: Any,
    down_payment: Any,
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    option = canonical_credit_plan_option(credit_plan)
    cleaned_credit_plan = _clean_scalar(credit_plan)
    cleaned_down_payment = _clean_scalar(down_payment)
    if option is None:
        return cleaned_credit_plan, cleaned_down_payment, []

    canonical_credit_plan = str(option.get("canonical_credit_plan") or "").strip() or None
    canonical_down_payment = str(option.get("down_payment") or "").strip() or None
    errors: list[dict[str, Any]] = []
    if cleaned_credit_plan and canonical_credit_plan and cleaned_credit_plan != canonical_credit_plan:
        errors.append(
            {
                "field": "CREDITO",
                "existing_value": cleaned_credit_plan,
                "corrected_value": canonical_credit_plan,
                "reason": "credit_plan_canonicalized",
            }
        )
    if (
        cleaned_down_payment
        and canonical_down_payment
        and _normalize_lookup_key(cleaned_down_payment) != _normalize_lookup_key(canonical_down_payment)
    ):
        errors.append(
            {
                "field": "ENGANCHE",
                "selection_key": canonical_credit_plan,
                "existing_value": cleaned_down_payment,
                "corrected_value": canonical_down_payment,
                "reason": "credit_plan_down_payment_mismatch",
            }
        )
    return canonical_credit_plan, canonical_down_payment or cleaned_down_payment, errors


def canonical_credit_plan_option(selection_key: Any) -> dict[str, Any] | None:
    normalized = _normalize_lookup_key(selection_key)
    if not normalized:
        return None
    for canonical_credit_plan in COMMERCIAL_CREDIT_PLAN_ORDER:
        spec = _COMMERCIAL_CREDIT_PLAN_SPECS[canonical_credit_plan]
        aliases = {
            normalized_alias
            for normalized_alias in (
                _normalize_lookup_key(canonical_credit_plan),
                _normalize_lookup_key(spec.get("visible_label")),
                *[_normalize_lookup_key(alias) for alias in _as_list(spec.get("aliases"))],
            )
            if normalized_alias
        }
        if normalized in aliases:
            return {
                "display_number": COMMERCIAL_CREDIT_PLAN_ORDER.index(canonical_credit_plan) + 1,
                "visible_label": spec["visible_label"],
                "canonical_credit_plan": canonical_credit_plan,
                "down_payment": spec["down_payment"],
                "aliases": _dedupe(
                    [
                        str(COMMERCIAL_CREDIT_PLAN_ORDER.index(canonical_credit_plan) + 1),
                        canonical_credit_plan,
                        spec["visible_label"],
                        *[str(alias) for alias in _as_list(spec.get("aliases"))],
                    ]
                ),
                "requirements_key": canonical_credit_plan,
                "selection_key": canonical_credit_plan,
                "selection_label": canonical_credit_plan,
                "menu_index": COMMERCIAL_CREDIT_PLAN_ORDER.index(canonical_credit_plan) + 1,
                "menu_prompt": spec["visible_label"],
                "plan": spec["down_payment"],
                "field_updates": {
                    "CREDITO": canonical_credit_plan,
                    "ENGANCHE": spec["down_payment"],
                },
            }
    return None


def _configured_selection_keys(
    selection_catalog: Mapping[str, Any],
    document_requirements: Mapping[str, Any],
) -> list[str]:
    configured_selection_keys: list[str] = []
    for key in [*selection_catalog.keys(), *document_requirements.keys()]:
        if isinstance(key, str) and key not in configured_selection_keys:
            configured_selection_keys.append(key)
    return configured_selection_keys


def _configured_key_for_canonical_plan(
    canonical_credit_plan: str,
    configured_selection_keys: list[str],
    selection_catalog: Mapping[str, Any],
) -> str | None:
    canonical_option = canonical_credit_plan_option(canonical_credit_plan)
    if canonical_option is None:
        return None
    aliases = _option_aliases(canonical_option)
    for configured_key in configured_selection_keys:
        if _normalize_lookup_key(configured_key) in aliases:
            return configured_key
        configured_entry = _mapping(selection_catalog.get(configured_key))
        label = _normalize_lookup_key(configured_entry.get("label"))
        if label and label in aliases:
            return configured_key
        for alias in _as_list(configured_entry.get("aliases")):
            normalized_alias = _normalize_lookup_key(alias)
            if normalized_alias and normalized_alias in aliases:
                return configured_key
    return None


def _unique_credit_plan_matches(options: Any) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for option in options:
        selection_key = str(option.get("selection_key") or "").strip()
        if selection_key:
            by_key.setdefault(selection_key, option)
    return list(by_key.values())


def _option_aliases(option: Mapping[str, Any]) -> set[str]:
    aliases = {
        _normalize_lookup_key(alias)
        for alias in [
            option.get("selection_key"),
            option.get("selection_label"),
            option.get("visible_label"),
            option.get("menu_prompt"),
            *list(option.get("aliases") or []),
        ]
        if _normalize_lookup_key(alias)
    }
    display_number = _clean_scalar(option.get("display_number") or option.get("menu_index"))
    if display_number:
        aliases.update(
            {
                display_number,
                _normalize_lookup_key(f"opcion {display_number}"),
                _normalize_lookup_key(f"opción {display_number}"),
            }
        )
    return aliases


def _alias_match_score(
    *,
    normalized_input: str,
    input_tokens: set[str],
    input_digits: set[str],
    alias: str,
) -> float:
    if not alias:
        return 0.0
    if normalized_input == alias:
        return 1.0
    if alias.isdigit():
        return 0.0
    if len(normalized_input) <= 2 and not input_digits:
        return 0.0
    if normalized_input in alias or alias in normalized_input:
        return 0.9

    alias_tokens = set(alias.split())
    alias_digits = set(re.findall(r"\d+", alias))
    token_overlap = len(input_tokens & alias_tokens)
    digit_overlap = len(input_digits & alias_digits)
    if digit_overlap and not (input_tokens - input_digits):
        return 0.82
    if token_overlap and input_tokens and input_tokens <= alias_tokens:
        return 0.8
    if token_overlap >= 2:
        return 0.78
    return 0.0


def _normalize_lookup_key(value: Any) -> str:
    return normalize_whatsapp_text(str(value or ""), keep_percent=False)


def _clean_scalar(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        normalized = _normalize_lookup_key(cleaned)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(cleaned)
    return result


__all__ = [
    "COMMERCIAL_CREDIT_PLAN_ORDER",
    "build_credit_plan_menu",
    "canonical_credit_plan_option",
    "enforce_credit_plan_invariants",
    "resolve_credit_plan_option",
]

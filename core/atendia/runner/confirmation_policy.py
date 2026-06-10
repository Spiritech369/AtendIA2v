from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from atendia.text_normalization import normalize_whatsapp_text


@dataclass(frozen=True)
class ConfirmationResolution:
    answer: Literal["yes", "no"]
    updates: dict[str, Any]
    extracted_data: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ConfirmationPolicyRequest:
    user_message: str
    current_state: dict[str, dict[str, Any]]
    pending_confirmation: str | None
    advisor_decision: Any | None = None
    proposed_updates: dict[str, Any] | None = None
    state_write_result: Any | None = None
    turn_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfirmationPolicyResult:
    confirmation_resolution: ConfirmationResolution | None
    approved_updates: dict[str, Any]
    blocked_updates: list[dict[str, Any]]
    next_pending_confirmation: str | None
    confirmation_trace: dict[str, Any]
    reasons: list[str]
    extracted_data: dict[str, dict[str, Any]]


_AFFIRMATIVE: frozenset[str] = frozenset(
    {
        "si",
        "claro",
        "ok",
        "okay",
        "sale",
        "simon",
        "sip",
        "va",
        "ya",
        "yes",
    }
)
_NEGATIVE: frozenset[str] = frozenset({"no", "nada", "nel", "nop"})
_AFFIRMATIVE_DEICTIC_TERMS: frozenset[str] = frozenset(
    {"esa", "ese", "eso", "esta", "este", "misma", "mismo", "aquella", "aquel"}
)
_AFFIRMATIVE_RAW: frozenset[str] = frozenset({"s\u00ed"})
_LEGACY_PENDING_CONFIRMATION_BRANCHES: dict[str, dict[str, dict[str, Any]]] = {
    "is_nomina_tarjeta": {
        "yes": {"tipo_credito": "N\u00f3mina Tarjeta", "plan_credito": "10%"},
    },
    "is_negocio_sat": {
        "no": {"tipo_credito": "Sin Comprobantes", "plan_credito": "20%"},
    },
}


def apply_confirmation_policy(request: ConfirmationPolicyRequest) -> ConfirmationPolicyResult:
    resolution = resolve_pending_confirmation(
        inbound_text=request.user_message,
        pending_confirmation=request.pending_confirmation,
        extracted_jsonb=request.current_state,
    )
    approved_updates = dict(resolution.updates) if resolution is not None else {}
    trace = (
        {
            "pending_confirmation_resolved": True,
            "answer": resolution.answer,
            "updates": _jsonable(approved_updates),
        }
        if resolution is not None
        else {}
    )
    return ConfirmationPolicyResult(
        confirmation_resolution=resolution,
        approved_updates=approved_updates,
        blocked_updates=[],
        next_pending_confirmation=None,
        confirmation_trace=trace,
        reasons=[],
        extracted_data=(
            resolution.extracted_data if resolution is not None else request.current_state
        ),
    )


def advisor_metadata_from_confirmation(
    result: ConfirmationPolicyResult,
) -> dict[str, Any]:
    if not result.approved_updates:
        return {}
    return {
        "pending_confirmation_resolved": True,
        "pending_confirmation_updates": dict(result.approved_updates),
    }


def next_pending_confirmation_from_sources(
    *,
    protected_state_conflict: dict[str, Any] | None,
    composer_pending_confirmation: str | None,
) -> str | None:
    if protected_state_conflict is not None:
        return pending_confirmation_from_state_conflict(protected_state_conflict)
    if composer_pending_confirmation:
        return composer_pending_confirmation
    return None


def pending_confirmation_from_state_conflict(event: dict[str, Any]) -> str | None:
    field_name = str(event.get("protected_field") or "").strip()
    if not field_name:
        return None
    attempted_value = event.get("attempted_value")
    existing_value = event.get("existing_value")
    if not _state_guard_present(attempted_value):
        return None
    return json.dumps(
        _jsonable(
            {
                "yes": {field_name: attempted_value},
                "no": {field_name: existing_value},
            }
        )
    )


def resolve_pending_confirmation(
    *,
    inbound_text: str,
    pending_confirmation: str | None,
    extracted_jsonb: dict[str, dict[str, Any]],
) -> ConfirmationResolution | None:
    if not pending_confirmation:
        return None

    raw = str(inbound_text or "").strip().casefold()
    normalized = normalize_whatsapp_text(inbound_text)
    if _is_affirmative_confirmation(raw=raw, normalized=normalized):
        answer: Literal["yes", "no"] = "yes"
    elif normalized in _NEGATIVE:
        answer = "no"
    else:
        return None

    updates = _confirmation_side_effects(pending_confirmation, answer)
    if not updates:
        return None

    new_extracted = dict(extracted_jsonb)
    for key, value in updates.items():
        new_extracted[key] = {"value": value, "confidence": 1.0, "source_turn": 0}
    return ConfirmationResolution(
        answer=answer,
        updates=updates,
        extracted_data=new_extracted,
    )


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (datetime, Decimal, UUID)):
        return str(obj)
    return obj


def _state_guard_present(value: Any) -> bool:
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    return value not in (None, "", [], {})


def _is_affirmative_confirmation(*, raw: str, normalized: str) -> bool:
    if normalized in _AFFIRMATIVE or raw in _AFFIRMATIVE_RAW:
        return True
    tokens = normalized.split()
    if not tokens or len(tokens) > 4:
        return False
    token_set = set(tokens)
    if not (token_set & _AFFIRMATIVE):
        return False
    return token_set <= (_AFFIRMATIVE | _AFFIRMATIVE_DEICTIC_TERMS)


def _confirmation_side_effects(
    pending_key: str,
    answer: Literal["yes", "no"],
) -> dict[str, Any]:
    legacy_branch = _LEGACY_PENDING_CONFIRMATION_BRANCHES.get(str(pending_key or ""))
    if legacy_branch is not None:
        return dict(legacy_branch.get(answer) or {})
    try:
        parsed = json.loads(pending_key)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    branch = parsed.get(answer)
    if not isinstance(branch, dict):
        return {}
    updates: dict[str, Any] = {}
    for key, value in branch.items():
        if isinstance(key, str) and key.strip() and value not in (None, ""):
            updates[key.strip()] = value
    return updates


__all__ = [
    "ConfirmationPolicyRequest",
    "ConfirmationPolicyResult",
    "ConfirmationResolution",
    "advisor_metadata_from_confirmation",
    "apply_confirmation_policy",
    "next_pending_confirmation_from_sources",
    "pending_confirmation_from_state_conflict",
    "resolve_pending_confirmation",
]

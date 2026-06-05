import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from atendia.credit_plan_invariants import canonical_credit_plan_option, enforce_credit_plan_invariants

STATE_GUARD_PROTECTED_FIELDS: frozenset[str] = frozenset(
    {"MOTO", "CREDITO", "ENGANCHE", "FILTRO", "ANTIGUEDAD_LABORAL", "PLAN", "plan"}
)
STATE_GUARD_CORRECTION_RE = re.compile(
    "\\b(corrige|corregir|correccion|correcci\u00f3n|cambiar|cambio|actualiza|"
    "actualizar|me equivoque|me equivoqu\u00e9|en realidad|mejor|quise decir|"
    "no tengo recibos|no me dan recibos|no tengo nomina|me pagan por fuera|"
    "no tengo comprobantes)\\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class StateWritePolicyRequest:
    current_state: dict[str, Any]
    proposed_updates: dict[str, Any]
    advisor_decision: Any | None = None
    nlu_entities: dict[str, Any] | None = None
    confirmation_resolution: Any | None = None
    protected_fields: frozenset[str] = STATE_GUARD_PROTECTED_FIELDS
    turn_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StateWritePolicyResult:
    approved_updates: dict[str, Any]
    blocked_updates: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    pending_confirmation: str | None
    state_write_trace: list[dict[str, Any]]
    reasons: list[str]


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (datetime, Decimal, UUID)):
        return str(obj)
    return obj


def state_guard_normalize(value: Any) -> str:
    text_value = str(value or "").strip()
    decomposed = unicodedata.normalize("NFKD", text_value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.casefold()).strip()


def state_guard_present(value: Any) -> bool:
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    return value not in (None, "", [], {})


def state_guard_value(extracted_data: dict[str, Any], key: str) -> Any:
    value = extracted_data.get(key)
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def state_guard_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    return state_guard_normalize(left) == state_guard_normalize(right)


def _model_tokens(value: Any) -> set[str]:
    normalized = state_guard_normalize(value)
    if not normalized:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in {"cc", "de", "la", "el"}
    }


def state_guard_model_canonicalization_match(existing: Any, attempted: Any) -> bool:
    existing_tokens = _model_tokens(existing)
    attempted_tokens = _model_tokens(attempted)
    if len(existing_tokens) < 2 or len(attempted_tokens) < len(existing_tokens):
        return False
    return existing_tokens.issubset(attempted_tokens)


def _configured_document_keys(pipeline: Any) -> set[str]:
    keys: set[str] = set()
    for spec in getattr(pipeline, "documents_catalog", []) or []:
        key = getattr(spec, "key", None)
        if key:
            keys.add(str(key))
    mapping = getattr(pipeline, "vision_doc_mapping", {}) or {}
    if isinstance(mapping, dict):
        for mapped_keys in mapping.values():
            if isinstance(mapped_keys, list):
                keys.update(str(key) for key in mapped_keys if key)
    for required in (getattr(pipeline, "document_requirements", {}) or {}).values():
        if isinstance(required, list):
            keys.update(str(key) for key in required if key)
    return keys


def _is_doc_like_field(key: str, pipeline: Any | None = None) -> bool:
    normalized = key.lower()
    if normalized.startswith("docs_") or normalized.startswith("docs."):
        return True
    if pipeline is None:
        return False
    configured_keys = _configured_document_keys(pipeline)
    return key in configured_keys or key.upper() in configured_keys


def state_guard_is_protected_field(key: str, pipeline: Any | None) -> bool:
    if key in STATE_GUARD_PROTECTED_FIELDS or key.upper() in STATE_GUARD_PROTECTED_FIELDS:
        return True
    return _is_doc_like_field(key, pipeline)


def state_guard_display_value(key: str, value: Any) -> str:
    if key.upper() == "FILTRO":
        # FILTRO is an eligibility boolean. It is not the employment duration;
        # ANTIGUEDAD_LABORAL is the primary source for that contract.
        if value is True:
            return "cumple antiguedad"
        if value is False:
            return "no cumple antiguedad"
    if key.upper() == "ANTIGUEDAD_LABORAL" and isinstance(value, dict):
        raw = value.get("raw_text")
        months = value.get("normalized_months")
        if raw and months:
            return f"{raw} ({months} meses)"
    return str(value)


def state_guard_conflict_message(event: dict[str, Any]) -> str:
    field = str(event.get("protected_field") or "ese dato")
    human_field = {
        "MOTO": "modelo",
        "CREDITO": "plan",
        "ENGANCHE": "enganche",
        "FILTRO": "validacion",
    }.get(field.upper(), field.lower())
    existing = state_guard_display_value(field, event.get("existing_value"))
    attempted = state_guard_display_value(field, event.get("attempted_value"))
    return (
        f"Tenia anotado {existing} como {human_field}. "
        f"Quieres corregirlo a {attempted}?"
    )


def field_updates_proposed_from_resolution(turn_resolution: Any | None) -> list[dict[str, Any]]:
    if turn_resolution is None:
        return []
    attempts = getattr(turn_resolution, "attempts", []) or []
    proposed: list[dict[str, Any]] = []
    for attempt in attempts:
        updates = getattr(attempt, "field_updates", {}) or {}
        if not isinstance(updates, dict):
            continue
        for field_name, value in updates.items():
            proposed.append(
                {
                    "resolver": getattr(attempt, "resolver", None),
                    "field": field_name,
                    "value": _jsonable(value),
                    "confidence": getattr(attempt, "confidence", None),
                    "can_write_state": getattr(attempt, "can_write_state", False),
                    "requires_confirmation": getattr(attempt, "requires_confirmation", False),
                    "blocked_reason": getattr(attempt, "blocked_reason", None),
                }
            )
    return proposed


def field_updates_blocked_from_state_guards(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for event in events:
        if event.get("overwrite_allowed") is True:
            continue
        reason = event.get("overwrite_blocked_reason")
        if event.get("overwrite_allowed") is not False and not reason:
            continue
        blocked.append(
            {
                "field": event.get("protected_field"),
                "existing_value": _jsonable(event.get("existing_value")),
                "attempted_value": _jsonable(event.get("attempted_value")),
                "reason": reason,
                "conflict_detected": event.get("conflict_detected", False),
            }
        )
    return blocked


def explicit_state_correction_requested(inbound_text: str) -> bool:
    return bool(STATE_GUARD_CORRECTION_RE.search(inbound_text or ""))


def _explicit_model_change_evidence(inbound_text: str, attempted_value: Any | None = None) -> bool:
    normalized = state_guard_normalize(inbound_text)
    tokens = normalized.split()
    if not tokens:
        return False
    if set(tokens) & {"primera", "primer", "segunda", "tercera", "esa", "ese"}:
        return True
    if set(tokens) & {"urban", "urbana", "cargo", "heavy", "motocarro"}:
        return True
    attempted_tokens = {
        token
        for token in state_guard_normalize(attempted_value).split()
        if len(token) >= 3 or any(ch.isdigit() for ch in token)
    }
    if attempted_tokens and set(tokens) & attempted_tokens:
        return True
    if any(any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token) for token in tokens):
        return True
    model_terms = {"moto", "motocicleta", "modelo", "modelos"}
    if set(tokens) & model_terms:
        return True
    markers = {"cambio", "cambiar", "cambiala", "mejor", "prefiero", "quiero"}
    if not set(tokens) & markers:
        return False
    stopwords = {
        "a",
        "al",
        "credito",
        "creditos",
        "de",
        "el",
        "la",
        "las",
        "lo",
        "me",
        "saco",
        "si",
        "un",
        "una",
        "y",
    }
    candidates = [
        token
        for token in tokens
        if token not in stopwords and token not in markers and len(token) > 2
    ]
    return bool(candidates)


def _replace_entity_value(entities: dict[str, Any], key: str, value: Any) -> None:
    current = entities.get(key)
    if isinstance(current, dict) and "value" in current:
        current["value"] = value
        return
    if hasattr(current, "value"):
        try:
            setattr(current, "value", value)
            return
        except Exception:
            pass
    entities[key] = value


def _blocked_update_event(
    *,
    key: str,
    attempted_value: Any,
    reason: str,
) -> dict[str, Any]:
    return {
        "protected_field": key,
        "existing_value": None,
        "attempted_value": attempted_value,
        "conflict_detected": False,
        "overwrite_allowed": False,
        "overwrite_blocked_reason": reason,
    }


def _model_value_looks_catalog_canonical(value: Any) -> bool:
    normalized = state_guard_normalize(value)
    if not normalized or normalized in {"moto", "motocicleta", "modelo", "modelos"}:
        return False
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token not in {"de", "del", "la", "el", "los", "las", "un", "una"}
    }
    if not tokens:
        return False
    income_tokens = {
        "nomina",
        "tarjeta",
        "recibos",
        "depositan",
        "deposito",
        "ingresos",
        "pagan",
        "comprobantes",
        "sat",
        "pensionado",
        "pensionados",
        "guardia",
        "seguridad",
        "credito",
        "creditos",
        "pago",
        "pagos",
        "deposito",
        "depositan",
        "fuera",
    }
    generic_model_tokens = {
        "moto",
        "motocicleta",
        "modelo",
        "modelos",
        "otra",
        "otro",
        "otras",
        "otros",
        "esa",
        "ese",
        "esta",
        "este",
        "misma",
        "mismo",
        "quiero",
        "que",
        "manda",
        "mando",
        "primero",
        "donde",
        "estan",
        "ubicacion",
        "direccion",
        "si",
        "va",
    }
    if tokens & income_tokens:
        return False
    if tokens <= generic_model_tokens:
        return False
    if any(char.isdigit() for char in normalized) or "cc" in tokens:
        return True
    return len(tokens) >= 2


def _income_disambiguation_flags(inbound_text: str) -> dict[str, Any]:
    normalized = state_guard_normalize(inbound_text)
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    has_nomina = "nomina" in tokens
    has_card = "tarjeta" in tokens
    has_receipts = "recibos" in tokens or "recibo" in tokens
    has_deposit = "deposito" in tokens or "depositan" in tokens or "transferencia" in tokens
    has_negative = any(
        phrase in normalized
        for phrase in (
            "por fuera",
            "sin comprobante",
            "sin comprobar",
            "no se puede comprobar",
            "no es nomina",
            "no tengo comprobantes",
        )
    )
    dual_income_detected = (
        "dos trabajos" in normalized
        or ("uno" in tokens and "otro" in tokens)
        or (not has_negative and "fuera" in tokens and (has_deposit or has_nomina))
    )
    payroll_ambiguous = has_nomina and not has_card and not has_receipts
    deposit_ambiguous = has_deposit and not has_card and not has_receipts and not has_negative
    needs_income_disambiguation = dual_income_detected or payroll_ambiguous or deposit_ambiguous
    blocked_reason = None
    if dual_income_detected:
        blocked_reason = "dual_income_detected"
    elif payroll_ambiguous:
        blocked_reason = "payroll_ambiguous"
    elif deposit_ambiguous:
        blocked_reason = "deposit_ambiguous"
    return {
        "income_ambiguity": payroll_ambiguous or deposit_ambiguous or dual_income_detected,
        "payroll_ambiguous": payroll_ambiguous,
        "deposit_ambiguous": deposit_ambiguous,
        "dual_income_detected": dual_income_detected,
        "needs_income_disambiguation": needs_income_disambiguation,
        "credit_plan_write_blocked_reason": blocked_reason,
    }


def _policy_income_disambiguation_flags(request: StateWritePolicyRequest) -> dict[str, Any]:
    inbound_flags = _income_disambiguation_flags(str(request.turn_context.get("inbound_text") or ""))
    advisor_payload = getattr(request.advisor_decision, "tool_payload", {}) if request.advisor_decision else {}
    policy_trace = advisor_payload.get("policy_trace") if isinstance(advisor_payload, dict) else None
    if not isinstance(policy_trace, dict):
        return inbound_flags
    if str(policy_trace.get("selected_income_source") or "").strip():
        return {
            **inbound_flags,
            "income_ambiguity": False,
            "payroll_ambiguous": False,
            "deposit_ambiguous": False,
            "dual_income_detected": False,
            "needs_income_disambiguation": False,
            "credit_plan_write_blocked_reason": None,
            "selected_income_source": policy_trace.get("selected_income_source"),
            "selected_income_source_confidence": policy_trace.get(
                "selected_income_source_confidence"
            ),
        }
    merged = dict(inbound_flags)
    for key in (
        "income_ambiguity",
        "payroll_ambiguous",
        "deposit_ambiguous",
        "dual_income_detected",
        "needs_income_disambiguation",
        "credit_plan_write_blocked_reason",
    ):
        if policy_trace.get(key) not in (None, "", [], {}):
            merged[key] = policy_trace.get(key)
    return merged


def _guard_income_ambiguity_writes(
    *,
    request: StateWritePolicyRequest,
    entities: dict[str, Any],
) -> list[dict[str, Any]]:
    flags = _policy_income_disambiguation_flags(request)
    if not bool(flags.get("needs_income_disambiguation")):
        return []
    reason = str(flags.get("credit_plan_write_blocked_reason") or "income_ambiguity_requires_clarification")
    events: list[dict[str, Any]] = []
    for key in ("CREDITO", "ENGANCHE"):
        if key not in entities:
            continue
        attempted_value = getattr(entities.get(key), "value", entities.get(key))
        entities.pop(key, None)
        events.append(
            _blocked_update_event(
                key=key,
                attempted_value=attempted_value,
                reason=reason,
            )
        )
    return events


def _validate_structured_entities(
    *,
    entities: dict[str, Any],
    current_state: dict[str, Any],
    inbound_text: str,
    pipeline: Any | None = None,
    write_source: str | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for key in list(entities.keys()):
        if not _is_doc_like_field(str(key), pipeline):
            continue
        if str(write_source or "").strip().casefold() == "vision":
            continue
        attempted_document = getattr(entities.get(key), "value", entities.get(key))
        entities.pop(key, None)
        events.append(
            _blocked_update_event(
                key=str(key),
                attempted_value=attempted_document,
                reason="documents_cannot_be_marked_received_from_text",
            )
        )

    selector_value = None
    if "CREDITO" in entities:
        attempted_credit = getattr(entities.get("CREDITO"), "value", entities.get("CREDITO"))
        option = canonical_credit_plan_option(attempted_credit)
        if option is None:
            attempted_value = attempted_credit
            entities.pop("CREDITO", None)
            events.append(
                _blocked_update_event(
                    key="CREDITO",
                    attempted_value=attempted_value,
                    reason="invalid_credit_plan_entity_value",
                )
            )
        else:
            selector_value = str(option.get("canonical_credit_plan") or "").strip() or None
            _replace_entity_value(entities, "CREDITO", selector_value)
    else:
        selector_value = state_guard_value(current_state, "CREDITO")

    if "ENGANCHE" in entities:
        attempted_down_payment = getattr(entities.get("ENGANCHE"), "value", entities.get("ENGANCHE"))
        normalized_down_payment = str(attempted_down_payment or "").strip()
        if not re.fullmatch(r"\d{1,2}%", normalized_down_payment):
            entities.pop("ENGANCHE", None)
            events.append(
                _blocked_update_event(
                    key="ENGANCHE",
                    attempted_value=attempted_down_payment,
                    reason="invalid_down_payment_entity_value",
                )
            )
        else:
            coherent_credit, coherent_down_payment, consistency_errors = enforce_credit_plan_invariants(
                selector_value,
                normalized_down_payment,
            )
            if coherent_credit:
                selector_value = coherent_credit
                if "CREDITO" in entities:
                    _replace_entity_value(entities, "CREDITO", coherent_credit)
            mismatch = any(
                item.get("reason") == "credit_plan_down_payment_mismatch"
                for item in consistency_errors
            )
            if mismatch:
                entities.pop("ENGANCHE", None)
                events.append(
                    _blocked_update_event(
                        key="ENGANCHE",
                        attempted_value=attempted_down_payment,
                        reason="credit_plan_down_payment_mismatch",
                    )
                )

    if "MOTO" in entities:
        attempted_model = getattr(entities.get("MOTO"), "value", entities.get("MOTO"))
        if not _model_value_looks_catalog_canonical(attempted_model):
            entities.pop("MOTO", None)
            events.append(
                _blocked_update_event(
                    key="MOTO",
                    attempted_value=attempted_model,
                    reason="invalid_model_entity_value",
                )
            )
        elif not _explicit_model_change_evidence(inbound_text, attempted_model):
            entities.pop("MOTO", None)
            events.append(
                _blocked_update_event(
                    key="MOTO",
                    attempted_value=attempted_model,
                    reason="model_entity_requires_textual_evidence",
                )
            )
    return events


def _allow_explicit_model_change_overwrite(
    *,
    key: str,
    existing_value: Any,
    attempted_value: Any,
    inbound_text: str,
    turn_context: dict[str, Any] | None,
) -> bool:
    if str(key).upper() != "MOTO":
        return False
    if not turn_context or not bool(turn_context.get("allow_model_change_overwrite")):
        return False
    if not _explicit_model_change_evidence(inbound_text, attempted_value):
        return False
    if not state_guard_present(existing_value) or not state_guard_present(attempted_value):
        return False
    return not state_guard_values_equal(existing_value, attempted_value)


def guard_protected_entity_overwrites(
    *,
    entities: dict[str, Any],
    existing_data: dict[str, Any],
    pipeline: Any,
    inbound_text: str,
    turn_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    correction_requested = explicit_state_correction_requested(inbound_text)
    for key, field_item in list(entities.items()):
        if not state_guard_is_protected_field(key, pipeline):
            continue
        existing_value = state_guard_value(existing_data, key)
        if not state_guard_present(existing_value):
            continue
        attempted_value = getattr(field_item, "value", field_item)
        if not state_guard_present(attempted_value):
            continue
        same_value = state_guard_values_equal(existing_value, attempted_value)
        if (
            str(key).upper() == "MOTO"
            and state_guard_model_canonicalization_match(existing_value, attempted_value)
        ):
            events.append(
                {
                    "protected_field": key,
                    "existing_value": existing_value,
                    "attempted_value": attempted_value,
                    "conflict_detected": False,
                    "overwrite_allowed": True,
                    "overwrite_blocked_reason": "catalog_model_canonicalization_allowed",
                }
            )
            continue
        if _allow_explicit_model_change_overwrite(
            key=str(key),
            existing_value=existing_value,
            attempted_value=attempted_value,
            inbound_text=inbound_text,
            turn_context=turn_context,
        ):
            events.append(
                {
                    "protected_field": key,
                    "existing_value": existing_value,
                    "attempted_value": attempted_value,
                    "conflict_detected": True,
                    "overwrite_allowed": True,
                    "overwrite_blocked_reason": "explicit_model_change_selection_allowed",
                }
            )
            continue
        if same_value:
            entities.pop(key, None)
            events.append(
                {
                    "protected_field": key,
                    "existing_value": existing_value,
                    "attempted_value": attempted_value,
                    "conflict_detected": False,
                    "overwrite_allowed": False,
                    "overwrite_blocked_reason": "same_value_already_set",
                }
            )
            continue
        if correction_requested:
            if str(key).upper() == "MOTO" and not _explicit_model_change_evidence(inbound_text, attempted_value):
                entities.pop(key, None)
                events.append(
                    {
                        "protected_field": key,
                        "existing_value": existing_value,
                        "attempted_value": attempted_value,
                        "conflict_detected": False,
                        "overwrite_allowed": False,
                        "overwrite_blocked_reason": "model_change_requires_explicit_model_evidence",
                    }
                )
                continue
            events.append(
                {
                    "protected_field": key,
                    "existing_value": existing_value,
                    "attempted_value": attempted_value,
                    "conflict_detected": True,
                    "overwrite_allowed": True,
                    "overwrite_blocked_reason": None,
                }
            )
            continue
        if str(key).upper() == "MOTO" and not _explicit_model_change_evidence(inbound_text, attempted_value):
            entities.pop(key, None)
            events.append(
                {
                    "protected_field": key,
                    "existing_value": existing_value,
                    "attempted_value": attempted_value,
                    "conflict_detected": False,
                    "overwrite_allowed": False,
                    "overwrite_blocked_reason": "model_change_requires_explicit_model_evidence",
                }
            )
            continue
        entities.pop(key, None)
        events.append(
            {
                "protected_field": key,
                "existing_value": existing_value,
                "attempted_value": attempted_value,
                "conflict_detected": True,
                "overwrite_allowed": False,
                "overwrite_blocked_reason": "protected_field_conflict_requires_confirmation",
                "suggested_clarification": state_guard_conflict_message(
                    {
                        "protected_field": key,
                        "existing_value": existing_value,
                        "attempted_value": attempted_value,
                    }
                ),
            }
        )
    return events


def _approved_update_events(
    *,
    entities: dict[str, Any],
    turn_context: dict[str, Any],
) -> list[dict[str, Any]]:
    source = str(turn_context.get("write_source") or "state_write_policy").strip()
    inbound_text = str(turn_context.get("inbound_text") or "")
    events: list[dict[str, Any]] = []
    for key, field_item in entities.items():
        value = getattr(field_item, "value", field_item)
        confidence = getattr(field_item, "confidence", None)
        source_turn = getattr(field_item, "source_turn", None)
        events.append(
            {
                "field": key,
                "new_value": _jsonable(value),
                "confidence": confidence,
                "source_turn": source_turn,
                "source": source or "state_write_policy",
                "evidence": inbound_text[:240] if inbound_text else None,
                "approved_by": "StateWritePolicy",
                "write_allowed": True,
            }
        )
    return events


def apply_state_write_policy(request: StateWritePolicyRequest) -> StateWritePolicyResult:
    entities = (
        request.nlu_entities
        if request.nlu_entities is not None
        else request.proposed_updates
    )
    ambiguity_events = _guard_income_ambiguity_writes(
        request=request,
        entities=entities,
    )
    validation_events = _validate_structured_entities(
        entities=entities,
        current_state=request.current_state,
        inbound_text=str((request.turn_context or {}).get("inbound_text") or ""),
        pipeline=request.turn_context.get("pipeline"),
        write_source=str((request.turn_context or {}).get("write_source") or ""),
    )
    events = guard_protected_entity_overwrites(
        entities=entities,
        existing_data=request.current_state,
        pipeline=request.turn_context.get("pipeline"),
        inbound_text=str(request.turn_context.get("inbound_text") or ""),
        turn_context=request.turn_context,
    )
    events = [*ambiguity_events, *validation_events, *events]
    blocked = field_updates_blocked_from_state_guards(events)
    conflicts = [event for event in events if event.get("conflict_detected")]
    approved_trace = _approved_update_events(
        entities=entities,
        turn_context=request.turn_context,
    )
    return StateWritePolicyResult(
        approved_updates=dict(entities),
        blocked_updates=blocked,
        conflicts=conflicts,
        pending_confirmation=None,
        state_write_trace=[*events, *approved_trace],
        reasons=[str(item.get("reason")) for item in blocked if item.get("reason")],
    )


def first_blocked_state_conflict(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if event.get("conflict_detected") and event.get("overwrite_allowed") is False:
            return event
    return None

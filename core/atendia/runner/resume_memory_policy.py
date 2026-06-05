"""Pure projections for resume and active quote memory wiring.

This module derives information from values already available to the runner.
It does not mutate payloads, write state, persist data, or publish trace
metadata; those integration choices remain owned by the caller.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from atendia.runner.state_write_policy import state_guard_present, state_guard_value

_RESUME_TARGET_FIELDS: frozenset[str] = frozenset({"MOTO", "CREDITO", "ENGANCHE"})
_PRODUCT_FIELD_PRIORITY: tuple[str, ...] = (
    "sku",
    "SKU",
    "producto_interes",
    "producto",
    "product",
    "selected_product",
    "selected_item",
    "item",
    "modelo",
    "modelo_moto",
    "MOTO",
    "name",
)
_QUOTE_SKIP_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "credito",
        "credit",
        "enganche",
        "down_payment",
        "filtro",
        "selection",
        "selected_option",
        "phone",
        "telefono",
        "email",
        "nombre",
        "name_contact",
    }
)


def _flat_extracted_values(extracted_data: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, raw in extracted_data.items():
        value = raw.get("value") if isinstance(raw, dict) else raw
        if value is not None and value != "":
            values[key] = value
    return values


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


def quote_candidate_queries(
    *,
    extracted_data: dict[str, Any],
    customer_attrs: dict[str, Any],
    inbound_text: str,
    pipeline: Any,
) -> list[str]:
    """Resolve ordered product/search terms without mutating quote context."""
    values = {**_flat_extracted_values(customer_attrs), **_flat_extracted_values(extracted_data)}
    candidates: list[str] = []

    def add(raw: Any) -> None:
        if raw is None or isinstance(raw, bool):
            return
        value = str(raw).strip()
        if not value:
            return
        lowered = value.casefold()
        if lowered in {"true", "false", "ok", "missing", "rejected"}:
            return
        if value not in candidates:
            candidates.append(value)

    for key in _PRODUCT_FIELD_PRIORITY:
        if key in values:
            add(values[key])

    configured_doc_keys = _configured_document_keys(pipeline)
    priority_keys = {key.casefold() for key in _PRODUCT_FIELD_PRIORITY}
    for key, value in values.items():
        key_norm = str(key).casefold()
        if key_norm in priority_keys or key_norm in _QUOTE_SKIP_FIELD_KEYS:
            continue
        if key in configured_doc_keys or str(key).upper() in configured_doc_keys:
            continue
        if isinstance(value, str) and len(value.strip()) <= 120:
            add(value)

    # Last resort: useful when the user asks "cotiza la R4" before NLU
    # has saved the product field. It is still resolved through catalog search.
    add(inbound_text)
    return candidates


def quote_plan_code_from_values(
    extracted_data: dict[str, Any],
    customer_attrs: dict[str, Any],
) -> str | None:
    """Return the first existing plan value using the established priority."""
    values = {**_flat_extracted_values(customer_attrs), **_flat_extracted_values(extracted_data)}
    for key in (
        "plan_code",
        "selected_plan",
        "plan",
        "ENGANCHE",
        "enganche",
        "down_payment_percent",
    ):
        value = values.get(key)
        if value is None or isinstance(value, bool):
            continue
        text_value = str(value).strip()
        if text_value:
            return text_value
    return None


def quote_context_ready_for_recompute(
    *,
    extracted_data: dict[str, Any],
) -> bool:
    """Report whether state already contains both product and plan context."""
    values = _flat_extracted_values(extracted_data)
    has_product = any(values.get(key) not in (None, "", [], {}) for key in _PRODUCT_FIELD_PRIORITY)
    has_plan = quote_plan_code_from_values(extracted_data, {}) not in (None, "")
    return has_product and has_plan


def _document_labels(raw_documents: Any) -> list[str]:
    documents = raw_documents if isinstance(raw_documents, list) else []
    labels: list[str] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        label = document.get("label") or document.get("key")
        if label:
            labels.append(str(label))
    return labels


def missing_documents_context_from_requirements(
    requirements: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Project document labels and completion flags without altering requirements."""
    if not isinstance(requirements, dict):
        return None

    missing = requirements.get("missing") or []
    return {
        "missing": _document_labels(missing),
        "received": _document_labels(requirements.get("received")),
        "rejected": _document_labels(requirements.get("rejected")),
        "has_missing": isinstance(missing, list) and bool(missing),
        "is_complete": bool(requirements.get("complete")),
    }


def resume_pending_action_from_payload(
    *,
    action_payload: dict[str, Any],
    extracted_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Derive the existing FAQ-resume action in its established priority order."""
    documents_context = missing_documents_context_from_requirements(
        action_payload.get("requirements")
    )
    if documents_context is not None and documents_context["has_missing"]:
        return {
            "type": "ask_missing_documents",
            "missing": documents_context["missing"],
        }
    if not state_guard_present(state_guard_value(extracted_data, "MOTO")):
        return {"type": "ask_field", "field": "MOTO"}
    if not state_guard_present(state_guard_value(extracted_data, "CREDITO")):
        return {"type": "ask_field", "field": "CREDITO"}
    if not (
        state_guard_present(state_guard_value(extracted_data, "ENGANCHE"))
        or state_guard_present(state_guard_value(extracted_data, "plan"))
    ):
        return {"type": "ask_field", "field": "ENGANCHE"}
    return None


def _existing_resume_target(candidate: Any) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    if candidate.get("type") == "ask_missing_documents":
        return deepcopy(candidate)
    if candidate.get("type") == "ask_field" and candidate.get("field") in _RESUME_TARGET_FIELDS:
        return deepcopy(candidate)
    return None


def resume_target_from_context(
    *,
    pending_to_resume: dict[str, Any] | None,
    resume_pending_action: dict[str, Any] | None,
    requirements: dict[str, Any] | None,
    current_state: dict[str, Any] | None,
    advisor_decision: Any | None = None,
    action_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Derive an informational resume target without mutating runner state."""
    action_resume = (
        action_payload.get("resume_pending_action")
        if isinstance(action_payload, dict)
        else None
    )
    advisor_pending = (
        advisor_decision.get("pending_to_resume")
        if isinstance(advisor_decision, dict)
        else getattr(advisor_decision, "pending_to_resume", None)
    )
    for candidate in (
        pending_to_resume,
        resume_pending_action,
        action_resume,
        advisor_pending,
    ):
        target = _existing_resume_target(candidate)
        if target is not None:
            return target

    effective_requirements = requirements
    if effective_requirements is None and isinstance(action_payload, dict):
        payload_requirements = action_payload.get("requirements")
        if isinstance(payload_requirements, dict):
            effective_requirements = payload_requirements

    documents_context = missing_documents_context_from_requirements(effective_requirements)
    if documents_context is not None and documents_context["has_missing"]:
        return {
            "type": "ask_missing_documents",
            "missing": documents_context["missing"],
        }
    if current_state is None:
        return None
    return resume_pending_action_from_payload(
        action_payload=(
            {"requirements": effective_requirements}
            if effective_requirements is not None
            else {}
        ),
        extracted_data=current_state,
    )


def resume_memory_trace_metadata_from_context(
    *,
    pending_to_resume: dict[str, Any] | None,
    resume_pending_action: dict[str, Any] | None,
    requirements: dict[str, Any] | None,
    current_state: dict[str, Any] | None,
    advisor_decision: Any | None = None,
    action_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build prospective resume trace metadata without publishing it."""
    effective_requirements = requirements
    if effective_requirements is None and isinstance(action_payload, dict):
        payload_requirements = action_payload.get("requirements")
        if isinstance(payload_requirements, dict):
            effective_requirements = payload_requirements

    return {
        "resume_target": resume_target_from_context(
            pending_to_resume=pending_to_resume,
            resume_pending_action=resume_pending_action,
            requirements=effective_requirements,
            current_state=current_state,
            advisor_decision=advisor_decision,
            action_payload=action_payload,
        ),
        "missing_documents_context": missing_documents_context_from_requirements(
            effective_requirements
        ),
    }


__all__ = [
    "missing_documents_context_from_requirements",
    "quote_candidate_queries",
    "quote_context_ready_for_recompute",
    "quote_plan_code_from_values",
    "resume_memory_trace_metadata_from_context",
    "resume_pending_action_from_payload",
    "resume_target_from_context",
]

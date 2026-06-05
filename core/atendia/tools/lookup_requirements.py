"""Build a structured document checklist for a tenant-configured selection."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.tools.base import ToolNoDataResult


class RequiredDoc(BaseModel):
    """One required document and its current customer status."""

    key: str
    label: str
    hint: str = ""
    status: Literal["ok", "rejected", "missing"]
    rejection_reason: str | None = None


class RequirementsResult(BaseModel):
    """Structured doc-requirements view consumed by the composer."""

    status: Literal["ok"] = "ok"
    selection_key: str
    selection_label: str | None = None
    required: list[RequiredDoc] = Field(default_factory=list)
    received: list[RequiredDoc] = Field(default_factory=list)
    rejected: list[RequiredDoc] = Field(default_factory=list)
    missing: list[RequiredDoc] = Field(default_factory=list)
    complete: bool = False


def _doc_status_from_attrs(
    attrs: dict[str, Any],
    doc_key: str,
) -> tuple[Literal["ok", "rejected", "missing"], str | None]:
    raw = attrs.get(doc_key)
    if raw is None:
        return "missing", None
    if raw is True or (isinstance(raw, str) and raw.lower() == "ok"):
        return "ok", None
    if not isinstance(raw, dict):
        return "missing", None
    status_value = raw.get("status")
    if isinstance(status_value, dict) and "value" in status_value:
        status_value = status_value["value"]
    if status_value is True:
        return "ok", None
    if status_value is False:
        return "missing", None
    if not isinstance(status_value, str):
        return "missing", None
    norm = status_value.lower()
    if norm in {"ok", "true", "received", "approved"}:
        return "ok", None
    if norm in {"rejected", "unreadable", "expired"}:
        reason = raw.get("rejection_reason")
        if isinstance(reason, dict) and "value" in reason:
            reason = reason["value"]
        return "rejected", reason if isinstance(reason, str) else None
    return "missing", None


def _resolve_selection_label(selection_key: str, pipeline: PipelineDefinition) -> str | None:
    catalog = getattr(pipeline, "selection_catalog", None) or {}
    if isinstance(catalog, dict):
        entry = catalog.get(selection_key)
        if isinstance(entry, dict) and entry.get("label"):
            return str(entry["label"])
    return None


def _normalize_selection_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", "_", ascii_only).strip("_").upper()
    return re.sub(r"_+", "_", text)


def _selection_aliases(pipeline: PipelineDefinition) -> dict[str, str]:
    aliases: dict[str, str] = {}
    catalog = getattr(pipeline, "selection_catalog", None) or {}
    if not isinstance(catalog, dict):
        return aliases
    for selection, entry in catalog.items():
        selection_key = str(selection)
        aliases.setdefault(_normalize_selection_key(selection_key), selection_key)
        if not isinstance(entry, dict):
            continue
        label = entry.get("label")
        if label:
            aliases.setdefault(_normalize_selection_key(str(label)), selection_key)
        raw_aliases = entry.get("aliases") or []
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        if isinstance(raw_aliases, list):
            for alias in raw_aliases:
                if alias:
                    aliases.setdefault(_normalize_selection_key(str(alias)), selection_key)
    return aliases


def _resolve_requirement_selection(
    *,
    pipeline: PipelineDefinition,
    selection_key: str,
) -> str | None:
    requirements = pipeline.document_requirements or {}
    if selection_key in requirements:
        return selection_key
    normalized = _normalize_selection_key(selection_key)
    if not normalized:
        return None

    alias_match = _selection_aliases(pipeline).get(normalized)
    if alias_match in requirements:
        return alias_match

    normalized_requirements = {
        _normalize_selection_key(str(requirement_key)): str(requirement_key)
        for requirement_key in requirements
    }
    direct_match = normalized_requirements.get(normalized)
    if direct_match:
        return direct_match

    selection_tokens = {token for token in normalized.split("_") if token and not token.isdigit()}
    selection_digits = set(re.findall(r"\d+", normalized))
    scored: list[tuple[int, str]] = []
    for requirement_key in requirements:
        key = str(requirement_key)
        key_norm = _normalize_selection_key(key)
        if not key_norm:
            continue
        score = 0
        if normalized in key_norm or key_norm in normalized:
            score += 10
        key_tokens = {token for token in key_norm.split("_") if token and not token.isdigit()}
        key_digits = set(re.findall(r"\d+", key_norm))
        score += len(selection_tokens & key_tokens) * 2
        score += len(selection_digits & key_digits) * 5
        if score:
            scored.append((score, key))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def lookup_requirements(
    *,
    pipeline: PipelineDefinition,
    selection_key: str | None,
    customer_attrs: dict[str, Any],
) -> RequirementsResult | ToolNoDataResult:
    """Return document requirements for a configured selection key."""
    if not selection_key or not isinstance(selection_key, str):
        return ToolNoDataResult(
            hint="no selection key on the customer yet; ask for it first",
        )

    resolved_selection_key = _resolve_requirement_selection(
        pipeline=pipeline,
        selection_key=selection_key,
    )
    if not resolved_selection_key:
        return ToolNoDataResult(
            hint=f"selection {selection_key!r} has no required-docs configured",
        )

    doc_keys = pipeline.document_requirements.get(resolved_selection_key)
    if not doc_keys or not isinstance(doc_keys, list):
        return ToolNoDataResult(
            hint=f"selection {selection_key!r} has no required-docs configured",
        )

    catalog_by_key = {spec.key: spec for spec in pipeline.documents_catalog}

    required: list[RequiredDoc] = []
    received: list[RequiredDoc] = []
    rejected: list[RequiredDoc] = []
    missing: list[RequiredDoc] = []

    for key in doc_keys:
        if not isinstance(key, str):
            continue
        spec = catalog_by_key.get(key)
        label = spec.label if spec else key
        hint = spec.hint if spec else ""
        status, reject_reason = _doc_status_from_attrs(customer_attrs, key)
        doc = RequiredDoc(
            key=key,
            label=label,
            hint=hint,
            status=status,
            rejection_reason=reject_reason,
        )
        required.append(doc)
        if status == "ok":
            received.append(doc)
        elif status == "rejected":
            rejected.append(doc)
        else:
            missing.append(doc)

    complete = bool(required) and len(missing) == 0 and len(rejected) == 0

    return RequirementsResult(
        selection_key=resolved_selection_key,
        selection_label=_resolve_selection_label(resolved_selection_key, pipeline),
        required=required,
        received=received,
        rejected=rejected,
        missing=missing,
        complete=complete,
    )

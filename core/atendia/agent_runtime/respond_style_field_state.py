"""Validated, audited application of field proposals (shadow only).

Pure layer: takes VALIDATED field proposals from a direct-route turn,
re-checks them against the tenant's field policies and evidence rules, and
produces the new shadow state plus an audit entry per proposal. It never
touches the DB itself — persistence belongs to an injected store — and it
never writes commercial/live contact state (``shadow_only`` is structural).
"""

from __future__ import annotations

import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JsonDict = dict[str, Any]


class FieldAuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str
    status: Literal["accepted", "rejected"]
    reason: str
    previous_value: Any = None
    new_value: Any = None
    evidence: list[str] = Field(default_factory=list)
    source: str = "llm_field_proposal"
    shadow_only: Literal[True] = True


class FieldApplicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_values: JsonDict = Field(default_factory=dict)
    audit: list[FieldAuditEntry] = Field(default_factory=list)
    accepted_count: int = 0
    rejected_count: int = 0


def _canonical_allowed_value(value: Any, allowed_values: list[Any]) -> Any | None:
    """Case/whitespace/ACCENT-insensitive match in both directions ('nómina'
    matches allowed 'nomina' and vice versa — customers rarely type
    accents). Returns the CANONICAL allowed entry so accepted values are
    normalized, or None when not allowed."""
    normalized = _fold(value)
    if not normalized:
        return None
    for candidate in allowed_values:
        if _fold(candidate) == normalized:
            return candidate
    return None


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value).strip().casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def apply_field_proposals(
    proposals: list[JsonDict],
    *,
    field_policies: list[JsonDict],
    current_values: JsonDict,
) -> FieldApplicationResult:
    """Re-validates each proposal (writable policy + non-empty evidence)
    and applies accepted ones over ``current_values``. Rejected proposals
    never modify state."""
    policy_by_key: dict[str, JsonDict] = {
        str(item.get("field_key") or item.get("key")): item
        for item in field_policies
        if isinstance(item, dict) and item.get("writable", True) is not False
    }
    writable_keys = set(policy_by_key)
    new_values = dict(current_values)
    audit: list[FieldAuditEntry] = []
    accepted = rejected = 0
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        field_key = str(proposal.get("field_key") or "").strip()
        evidence = [str(item) for item in proposal.get("evidence") or [] if str(item)]
        previous_value = new_values.get(field_key)
        if not field_key or field_key not in writable_keys:
            rejected += 1
            audit.append(
                FieldAuditEntry(
                    field_key=field_key or "(missing)",
                    status="rejected",
                    reason="field_not_writable_or_unknown",
                    previous_value=previous_value,
                    evidence=evidence,
                )
            )
            continue
        if not evidence:
            rejected += 1
            audit.append(
                FieldAuditEntry(
                    field_key=field_key,
                    status="rejected",
                    reason="missing_evidence",
                    previous_value=previous_value,
                )
            )
            continue
        new_value = proposal.get("value")
        # F27-ENFORCED: when the policy declares allowed_values, the runtime
        # rejects anything outside them — no matter how confident the LLM
        # sounded. Accepted values are normalized to the canonical entry.
        allowed_values = policy_by_key[field_key].get("allowed_values")
        if isinstance(allowed_values, list) and allowed_values:
            canonical = _canonical_allowed_value(new_value, allowed_values)
            if canonical is None:
                rejected += 1
                audit.append(
                    FieldAuditEntry(
                        field_key=field_key,
                        status="rejected",
                        reason="value_not_allowed",
                        previous_value=previous_value,
                        new_value=new_value,
                        evidence=evidence,
                    )
                )
                continue
            new_value = canonical
        new_values[field_key] = new_value
        accepted += 1
        audit.append(
            FieldAuditEntry(
                field_key=field_key,
                status="accepted",
                reason=(
                    "corrected_previous_value"
                    if previous_value not in (None, new_value)
                    else "new_value_captured"
                ),
                previous_value=previous_value,
                new_value=new_value,
                evidence=evidence,
            )
        )
    return FieldApplicationResult(
        new_values=new_values,
        audit=audit,
        accepted_count=accepted,
        rejected_count=rejected,
    )


__all__ = ["FieldApplicationResult", "FieldAuditEntry", "apply_field_proposals"]

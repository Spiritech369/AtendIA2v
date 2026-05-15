"""`lookup_requirements(pipeline, plan_credito, customer_attrs)` — Fase 2.

Returns the structured doc-requirements view for a plan: which docs the
plan requires, which the customer already sent (status='ok'), which
were rejected, and which are still missing. The composer uses this so
the bot can answer "para tu plan necesito X, Y, Z" without inventing
data and without depending on a FAQ embedding hitting the right
question.

Why this is a separate tool (not just a helper in the runner):

  - `docs_complete_for_plan` (pipeline_evaluator) already decides
    *whether* the plan is complete. It's a boolean — the operator path.
    `lookup_requirements` is the *enumeration* — what to **say** to the
    customer. Different concern.

  - Future Fase 5 workflows will fire on `DOCS_COMPLETE_FOR_PLAN` and
    can call this tool to render the human handoff summary ("recibimos
    INE, comprobante, estados de cuenta — falta verificar nómina").

The tool is pure — it reads the pipeline + customer attrs and returns
a structured result. No DB call. No LLM call. Calling code is in the
runner (action dispatch) and (later) in the workflows engine.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.tools.base import ToolNoDataResult


class RequiredDoc(BaseModel):
    """One doc the plan requires + its current status on the customer.

    `status` reflects the canonical shape `customer.attrs[DOCS_X].status`:
      - "ok"       → received & accepted
      - "rejected" → received but failed Vision quality check
      - "missing"  → not on the customer yet (the dict for this key is
                     absent OR its `status` field is empty)

    `rejection_reason` carries Vision's note when status='rejected', so
    the composer can write "tu INE salió con reflejo, mándala de nuevo"
    instead of a generic "falta INE".
    """

    key: str
    label: str
    hint: str = ""
    status: Literal["ok", "rejected", "missing"]
    rejection_reason: str | None = None


class RequirementsResult(BaseModel):
    """Structured doc-requirements view consumed by the composer."""

    status: Literal["ok"] = "ok"
    plan_key: str
    plan_label: str | None = None
    required: list[RequiredDoc] = Field(default_factory=list)
    received: list[RequiredDoc] = Field(default_factory=list)
    rejected: list[RequiredDoc] = Field(default_factory=list)
    missing: list[RequiredDoc] = Field(default_factory=list)
    complete: bool = False


def _doc_status_from_attrs(
    attrs: dict[str, Any],
    doc_key: str,
) -> tuple[Literal["ok", "rejected", "missing"], str | None]:
    """Extract (status, rejection_reason) from customer.attrs for a doc.

    The runner today (Fase 1) emits DOCUMENT_ACCEPTED/REJECTED events
    but does NOT yet write DOCS_X.status (that's Fase 3 territory).
    We're forward-compatible: if attrs already has the structured
    shape (workflow-written, or future Fase 3 hook), we read it; if
    not, every doc reads as 'missing'.
    """
    raw = attrs.get(doc_key)
    if raw is None:
        return "missing", None
    # Plain boolean True / "ok" → accepted (legacy shape some operators
    # write manually through the contact panel).
    if raw is True or (isinstance(raw, str) and raw.lower() == "ok"):
        return "ok", None
    if not isinstance(raw, dict):
        # Anything truthy-but-unstructured we treat as missing — better
        # to ask again than to silently mark accepted on garbage.
        return "missing", None
    status_value = raw.get("status")
    if isinstance(status_value, dict) and "value" in status_value:
        status_value = status_value["value"]
    if not isinstance(status_value, str):
        return "missing", None
    norm = status_value.lower()
    if norm == "ok":
        return "ok", None
    if norm == "rejected":
        reason = raw.get("rejection_reason")
        if isinstance(reason, dict) and "value" in reason:
            reason = reason["value"]
        return "rejected", reason if isinstance(reason, str) else None
    return "missing", None


def _resolve_plan_label(plan_key: str, pipeline: PipelineDefinition) -> str | None:
    """Look up an operator-friendly label for the plan. Today the
    pipeline schema doesn't carry plan labels — `docs_per_plan` keys
    are bare strings — so we just title-case the key as a fallback.
    Fase 8 (seed for nicho motos) will introduce a labeled catalog;
    this tool is forward-compatible by checking the catalog first.
    """
    # Future: pipeline.plans_catalog[plan_key].label.
    catalog = getattr(pipeline, "plans_catalog", None) or {}
    if isinstance(catalog, dict):
        entry = catalog.get(plan_key)
        if isinstance(entry, dict) and entry.get("label"):
            return str(entry["label"])
    return None


def lookup_requirements(
    *,
    pipeline: PipelineDefinition,
    plan_credito: str | None,
    customer_attrs: dict[str, Any],
) -> RequirementsResult | ToolNoDataResult:
    """Return doc requirements for the customer's plan + current state.

    Returns `ToolNoDataResult` (not raises) when:
      - `plan_credito` is None/empty (customer hasn't picked a plan yet)
      - the plan isn't in `pipeline.docs_per_plan` (operator hasn't
        configured requirements for it)
      - the configured doc list is empty (operator configured the plan
        but left no docs — semantically the same as "no requirements yet")

    The runner uses ToolNoDataResult to fall back to asking for the
    plan first, instead of producing a confusing "no documentos
    requeridos" reply.
    """
    if not plan_credito or not isinstance(plan_credito, str):
        return ToolNoDataResult(
            hint="no plan_credito on the customer yet — ask for it first",
        )

    doc_keys = pipeline.docs_per_plan.get(plan_credito)
    if not doc_keys or not isinstance(doc_keys, list):
        return ToolNoDataResult(
            hint=f"plan {plan_credito!r} has no required-docs configured",
        )

    # Build a lookup from documents_catalog so we can pair each doc_key
    # with its operator-facing label/hint. Catalog entries are tenant-
    # configurable (PipelineEditor → "Documentos requeridos"); a key
    # that's referenced in docs_per_plan but missing from the catalog
    # still renders, just with the raw key as label.
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
        plan_key=plan_credito,
        plan_label=_resolve_plan_label(plan_credito, pipeline),
        required=required,
        received=received,
        rejected=rejected,
        missing=missing,
        complete=complete,
    )

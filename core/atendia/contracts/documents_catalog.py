"""Shared document catalog — labels for the well-known DOCS_* keys.

The Pipeline editor (frontend `DocumentRuleBuilder.tsx`) lists a set of
canonical documents the operator can check off as required-for-stage:
INE, Comprobante de domicilio, etc. Checking them writes
`auto_enter_rules.conditions` with field `DOCS_<KEY>.status equals "ok"`.

The Contact panel needs to render the same human-friendly labels when
showing the customer's checklist, but the backend has no business
importing from `frontend/`. This module is the backend-side
authoritative source so the labels stay in sync. Frontend catalog
lives at `frontend/src/features/pipeline/components/DocumentRuleBuilder.tsx`.

If you add a doc here, mirror it there (or vice-versa). The list is
intentionally small + vertical-specific (Mexican credit) for now;
making it tenant-configurable is tracked in the onboarding plan.
"""
from __future__ import annotations

# DOCS_* key -> human label. The frontend's DOCUMENT_CATALOG keeps
# `hint`/`label` separately; backend only needs the label for rendering.
DOCUMENT_LABELS: dict[str, str] = {
    "DOCS_INE": "INE",
    "DOCS_COMPROBANTE_DOMICILIO": "Comprobante de domicilio",
    "DOCS_ESTADOS_CUENTA": "Estados de cuenta",
    "DOCS_RECIBOS_NOMINA": "Recibos de nómina",
    "DOCS_RESOLUCION_IMSS": "Resolución IMSS",
}


def humanize_doc_key(key: str) -> str:
    """Friendly label for any DOCS_* key — falls back to title-casing
    the underscore-separated suffix when the key isn't in the catalog,
    so a tenant who invents `DOCS_CURP` still gets "Curp" instead of
    the raw uppercase identifier."""
    if key in DOCUMENT_LABELS:
        return DOCUMENT_LABELS[key]
    if key.startswith("DOCS_"):
        return key[len("DOCS_"):].replace("_", " ").title()
    return key.replace("_", " ").title()

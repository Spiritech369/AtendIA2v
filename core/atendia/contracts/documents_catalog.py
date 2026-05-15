"""Label fallback for DOCS_* keys not in the tenant's catalog.

The authoritative source of document labels is each tenant's
`PipelineDefinition.documents_catalog`, edited through the Pipeline
editor's "Catálogo de documentos" section. This module only provides a
**last-resort humanizer** for the contact panel when a stage's
auto_enter_rules references a `DOCS_*` key the operator deleted from
(or never added to) their catalog — so the UI shows "Comprobante
Domicilio" instead of the raw identifier.

No hardcoded label lookup table. Each tenant owns their own.
"""

from __future__ import annotations


def humanize_doc_key(key: str) -> str:
    """Pure title-case humanizer for any `DOCS_*` key.

    Examples:
        DOCS_INE                  -> "Ine"
        DOCS_COMPROBANTE_DOMICILIO -> "Comprobante Domicilio"
        DOCS_CURP                 -> "Curp"

    The output is intentionally generic — operators are expected to set
    proper labels through their catalog. This only fires for orphan
    keys (referenced by a rule but missing from the catalog) so the
    contact panel renders *something* readable instead of `DOCS_INE`.
    """
    if key.startswith("DOCS_"):
        return key[len("DOCS_") :].replace("_", " ").title()
    return key.replace("_", " ").title()

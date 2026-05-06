"""Ingest Dinamo's catalog + FAQs + plans into Postgres with embeddings.

Phase 3c.1 — T13/T14/T15. Reads three JSON files in `docs/`:

  * CATALOGO_MODELOS.json  → tenant_catalogs rows + halfvec embeddings
  * FAQ_CREDITO.json       → tenant_faqs rows + halfvec embeddings
  * REQUISITOS_PLANES.json → tenant_branding.default_messages.planes JSONB

Idempotent: ON CONFLICT (tenant_id, sku) for catalog and (tenant_id,
question) for FAQs do UPDATE in-place, so reruns refresh data without
duplicating rows.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.ingest_dinamo_data \\
        --tenant-id <uuid> --docs-dir ../docs [--dry-run]

T13 ships only the pure helpers (`_slugify`, `_flatten_catalog`,
`_embedding_text_for_catalog_item`). T14 adds the async `_main`.
"""
from typing import Any


def _slugify(name: str) -> str:
    """Convert a model name into a URL-safe SKU.

    Rules (each one observed in real catalog data):
      * Lowercase everything — SKUs are case-insensitive.
      * Treat slash (`/`) as a word separator (NOT as a hyphen) so
        "MotoCross / Doble Propósito" → "motocross-doble-propósito",
        not "motocross---doble-propósito".
      * Existing internal hyphens survive (e.g. "Cab-R" → "cab-r")
        because we only split on whitespace.
      * Multiple whitespace runs collapse to a single hyphen.
    """
    return "-".join(name.lower().replace("/", " ").split())


def _flatten_catalog(catalog_json: dict) -> list[dict[str, Any]]:
    """Flatten the categorised tree in `CATALOGO_MODELOS.json` into rows.

    Input structure (truncated):
        {"catalogo": [
            {"categoria": "Motoneta", "modelos": [
                {"modelo": "Adventure Elite 150 CC", "alias": [...],
                 "ficha_tecnica": {...}, "precios": {...},
                 "planes_credito": {...}},
                ...
            ]},
            ...
        ]}

    Output: one dict per model, ready for `INSERT INTO tenant_catalogs`.
    Prices are stringified (the catalog table stores them in `attrs`
    JSONB, and the `quote()` tool parses them with `Decimal(str(...))`).
    """
    items: list[dict[str, Any]] = []
    for cat_block in catalog_json.get("catalogo", []):
        category = cat_block.get("categoria", "")
        for modelo in cat_block.get("modelos", []):
            sku = _slugify(modelo["modelo"])
            precios = modelo.get("precios") or {}
            items.append({
                "sku": sku,
                "name": modelo["modelo"],
                "category": category,
                "attrs": {
                    "alias": modelo.get("alias", []),
                    "ficha_tecnica": modelo.get("ficha_tecnica", {}),
                    "precio_lista": str(precios.get("lista", "0")),
                    "precio_contado": str(precios.get("contado", "0")),
                    "planes_credito": modelo.get("planes_credito", {}),
                },
            })
    return items


def _embedding_text_for_catalog_item(item: dict[str, Any]) -> str:
    """Build the natural-language text we feed into the embeddings model.

    What you put in here directly affects which user phrases match. We
    include category, model name, alias list, motor cc / hp /
    transmission, and contado price — these are what customers ask
    about. We deliberately omit `ficha_tecnica.peso_kg`, `tanque_l`,
    etc. that don't typically appear in queries.

    Aliases are space-joined (not lowercased here — they were normalised
    at ingestion time) so phrases like "motoneta adventure" still hit.
    """
    attrs = item.get("attrs", {})
    ficha = attrs.get("ficha_tecnica", {}) or {}
    alias_str = ", ".join(attrs.get("alias", []))
    return (
        f"Categoría: {item.get('category', '')}. "
        f"Modelo: {item.get('name', '')}. "
        f"Alias: {alias_str}. "
        f"Motor: {ficha.get('motor_cc', '?')} CC. "
        f"Potencia: {ficha.get('potencia_hp', '?')} HP. "
        f"Transmisión: {ficha.get('transmision', '?')}. "
        f"Precio contado: ${attrs.get('precio_contado', '?')}."
    )

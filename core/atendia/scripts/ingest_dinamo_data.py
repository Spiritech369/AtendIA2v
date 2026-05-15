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
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID


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
            items.append(
                {
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
                }
            )
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


def _embedding_text_for_faq(faq: dict[str, Any]) -> str:
    """Concatenate FAQ pregunta + respuesta for embedding.

    We embed both Q and A so semantic search hits when the customer's
    phrasing matches either side. Detail blocks (`detalle_por_plan`,
    `documentos`) are flattened to text — they often carry the actual
    keywords customers search for.
    """
    parts = [faq.get("pregunta", ""), faq.get("respuesta", "")]
    detalle = faq.get("detalle_por_plan")
    if isinstance(detalle, dict):
        parts.extend(f"{k}: {v}" for k, v in detalle.items())
    documentos = faq.get("documentos")
    if isinstance(documentos, list):
        parts.extend(documentos)
    return " ".join(p for p in parts if p)


_INSERT_CATALOG_SQL = """
INSERT INTO tenant_catalogs (tenant_id, sku, name, category, attrs, embedding, active)
VALUES (:t, :sku, :n, :cat, CAST(:a AS jsonb), CAST(:e AS halfvec), true)
ON CONFLICT (tenant_id, sku) DO UPDATE SET
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    attrs = EXCLUDED.attrs,
    embedding = EXCLUDED.embedding,
    active = true
"""

_INSERT_FAQ_SQL = """
INSERT INTO tenant_faqs (tenant_id, question, answer, tags, embedding)
VALUES (:t, :q, :a, CAST(:tags AS jsonb), CAST(:e AS halfvec))
ON CONFLICT (tenant_id, question) DO UPDATE SET
    answer = EXCLUDED.answer,
    tags = EXCLUDED.tags,
    embedding = EXCLUDED.embedding
"""

_UPDATE_BRANDING_PLANS_SQL = """
UPDATE tenant_branding
SET default_messages = jsonb_set(
    COALESCE(default_messages, '{}'::jsonb),
    '{planes}',
    CAST(:p AS jsonb)
)
WHERE tenant_id = :t
"""


def _vec_to_pg_text(emb: list[float]) -> str:
    """Render a Python float list as the text format pgvector accepts.

    pgvector parses `[0.1, 0.2, 0.3]` as a vector literal. `str(list)`
    produces this exact shape, but we add a tighter formatting (no
    leading zeros from numpy scalars) for safety against weird inputs.
    """
    return "[" + ",".join(repr(float(x)) for x in emb) + "]"


async def _main(tenant_id: UUID, docs_dir: Path, dry_run: bool) -> int:
    """Read JSONs → embed → upsert. Returns exit code (0 OK, non-zero error)."""
    from openai import AsyncOpenAI
    from sqlalchemy import text

    from atendia.config import get_settings
    from atendia.db.session import _get_factory
    from atendia.tools.embeddings import generate_embeddings_batch

    settings = get_settings()
    if not settings.openai_api_key:
        print("ATENDIA_V2_OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    catalog_json = json.loads((docs_dir / "CATALOGO_MODELOS.json").read_text(encoding="utf-8"))
    faq_json = json.loads((docs_dir / "FAQ_CREDITO.json").read_text(encoding="utf-8"))
    plans_json = json.loads((docs_dir / "REQUISITOS_PLANES.json").read_text(encoding="utf-8"))

    catalog_items = _flatten_catalog(catalog_json)
    faqs = faq_json.get("faq", [])
    planes = plans_json.get("planes", [])

    print(f"Ingesting for tenant {tenant_id}:")
    print(f"  Catalog: {len(catalog_items)} items")
    print(f"  FAQs:    {len(faqs)}")
    print(f"  Planes:  {len(planes)}")

    catalog_texts = [_embedding_text_for_catalog_item(it) for it in catalog_items]
    faq_texts = [_embedding_text_for_faq(f) for f in faqs]

    print("Generating embeddings...")
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    cat_embs, cat_tokens, cat_cost = await generate_embeddings_batch(
        client=client,
        texts=catalog_texts,
    )
    faq_embs, faq_tokens, faq_cost = await generate_embeddings_batch(
        client=client,
        texts=faq_texts,
    )
    total_tokens = cat_tokens + faq_tokens
    total_cost = cat_cost + faq_cost
    print(f"  Tokens: {total_tokens}, cost: ${total_cost}")

    if dry_run:
        print("[dry run] not writing to DB")
        return 0

    factory = _get_factory()
    async with factory() as session:
        for item, emb in zip(catalog_items, cat_embs, strict=True):
            await session.execute(
                text(_INSERT_CATALOG_SQL),
                {
                    "t": tenant_id,
                    "sku": item["sku"],
                    "n": item["name"],
                    "cat": item["category"],
                    "a": json.dumps(item["attrs"]),
                    "e": _vec_to_pg_text(emb),
                },
            )
        for faq, emb in zip(faqs, faq_embs, strict=True):
            tags = faq.get("documentos") or []
            await session.execute(
                text(_INSERT_FAQ_SQL),
                {
                    "t": tenant_id,
                    "q": faq["pregunta"],
                    "a": faq["respuesta"],
                    "tags": json.dumps(tags),
                    "e": _vec_to_pg_text(emb),
                },
            )
        await session.execute(
            text(_UPDATE_BRANDING_PLANS_SQL),
            {
                "t": tenant_id,
                "p": json.dumps(planes),
            },
        )
        await session.commit()
    print(f"Done. Total cost: ${total_cost}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--docs-dir", type=Path, required=True)
    parser.add_argument(
        "--dry-run", action="store_true", help="Generate embeddings + report cost, skip DB writes"
    )
    args = parser.parse_args()
    return asyncio.run(_main(args.tenant_id, args.docs_dir, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

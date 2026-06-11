"""Real tenant facts for the Respond-Style tool executor (live/smoke).

Loads the PUBLISHED tenant data the real executor grounds on:
- catalog models from ``catalogs/catalog_items`` (active catalog only)
- credit plan / requirements records from Knowledge OS items

Pure data out; the executor itself stays synchronous and DB-free.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text


async def load_real_tool_facts(session: Any, *, tenant_id: str) -> dict[str, Any]:
    models = await _load_catalog_models(session, tenant_id=tenant_id)
    plans = await _load_requirement_plans(session, tenant_id=tenant_id)
    return {
        "models": models,
        "requirement_plans": plans,
        "counts": {"models": len(models), "requirement_plans": len(plans)},
    }


async def _load_catalog_models(session: Any, *, tenant_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT ci.sku, ci.name, ci.category, ci.base_price, "
                "ci.list_price, ci.attributes_json "
                "FROM catalog_items ci JOIN catalogs c ON c.id = ci.catalog_id "
                "WHERE c.tenant_id = :t AND c.status = 'active' "
                "AND ci.status = 'active' ORDER BY ci.name"
            ),
            {"t": str(UUID(str(tenant_id)))},
        )
    ).mappings()
    models: list[dict[str, Any]] = []
    for row in rows:
        attributes = row["attributes_json"] or {}
        aliases = [
            str(item)
            for item in (
                attributes.get("alias_normalizados")
                or attributes.get("alias")
                or []
            )
        ]
        plans = (
            attributes.get("planes_credito_normalizados")
            or attributes.get("planes_credito")
            or {}
        )
        models.append(
            {
                "model_id": row["sku"],
                "label": row["name"],
                "category": row["category"],
                "aliases": aliases,
                "price_lista_mxn": float(row["list_price"])
                if row["list_price"] is not None
                else attributes.get("precio_lista_mxn"),
                "price_contado_mxn": float(row["base_price"])
                if row["base_price"] is not None
                else attributes.get("precio_contado_mxn"),
                "tags": attributes.get("tags_uso") or [],
                "ficha_tecnica": attributes.get("ficha_tecnica") or {},
                "planes_credito": plans,
                "search_text": str(attributes.get("busqueda_texto") or ""),
            }
        )
    return models


async def _load_requirement_plans(
    session: Any, *, tenant_id: str
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT ki.title, ki.content, ki.structured_data "
                "FROM knowledge_items ki "
                "JOIN knowledge_sources ks ON ks.id = ki.source_id "
                "WHERE ks.tenant_id = :t AND ks.status = 'active' "
                "AND ki.active = true "
                "AND (ki.structured_data->>'tipo_registro') = "
                "'requisitos_plan_credito'"
            ),
            {"t": str(UUID(str(tenant_id)))},
        )
    ).mappings()
    plans: list[dict[str, Any]] = []
    for row in rows:
        data = row["structured_data"] or {}
        plans.append(
            {
                "title": row["title"],
                "plan_id": data.get("plan_id"),
                "tipo_credito": data.get("tipo_credito"),
                "plan_credito": data.get("plan_credito"),
                "aliases_usuario": data.get("aliases_usuario") or [],
                "texto_retrieval": data.get("texto_retrieval")
                or (row["content"] or ""),
                "structured": data,
            }
        )
    return plans


__all__ = ["load_real_tool_facts"]

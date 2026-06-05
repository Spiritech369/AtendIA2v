from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


DINAMO_TENANT_NAME = "Dinamo Motos NL"
QUOTE_SOURCE = "atendia_knowledge_base"
CATALOG_SOURCE = "atendia_catalog_published"
REQUIREMENTS_SOURCE = "atendia_requirements_published"
FAQ_SOURCE = "atendia_faq_published"


@dataclass(frozen=True)
class PublishedKnowledgeMetadata:
    tenant_id: str
    tenant_name: str
    knowledge_version: str
    catalog_version: str
    requirements_version: str
    faq_version: str


class DinamoAtendiaKnowledgeBase:
    def __init__(
        self,
        *,
        metadata: PublishedKnowledgeMetadata,
        catalog_items: list[dict[str, Any]],
        requirements: list[dict[str, Any]],
        faqs: list[dict[str, Any]],
    ) -> None:
        self.metadata = metadata
        self.catalog_items = catalog_items
        self.requirements = requirements
        self.faqs = faqs

    @classmethod
    async def load(
        cls,
        session: AsyncSession,
        *,
        tenant_name: str = DINAMO_TENANT_NAME,
    ) -> "DinamoAtendiaKnowledgeBase":
        tenant = (
            await session.execute(
                text("select id::text as id, name from tenants where name = :name"),
                {"name": tenant_name},
            )
        ).mappings().first()
        if tenant is None:
            raise ValueError(f"tenant {tenant_name!r} not found")
        tenant_id = str(tenant["id"])

        catalog_rows = (
            await session.execute(
                text(
                    """
                    select
                        c.name as catalog_name,
                        cv.version_number,
                        cv.published_at::text as published_at,
                        cv.snapshot_json
                    from catalogs c
                    join catalog_versions cv on cv.id = c.active_version_id
                    where c.tenant_id = cast(:tenant_id as uuid)
                      and c.status = 'active'
                      and cv.status = 'published'
                    order by cv.published_at desc nulls last, cv.version_number desc
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
        if not catalog_rows:
            raise ValueError("Dinamo tenant has no active published catalog")

        catalog_items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in catalog_rows:
            snapshot = row["snapshot_json"] if isinstance(row["snapshot_json"], dict) else {}
            for item in snapshot.get("items") or []:
                if not isinstance(item, dict):
                    continue
                if _norm(item.get("status") or "active") != "active":
                    continue
                key = (_norm(item.get("sku")), _norm(item.get("name")))
                if key in seen:
                    continue
                seen.add(key)
                catalog_items.append(dict(item))

        requirement_rows = (
            await session.execute(
                text(
                    """
                    select kc.text
                    from knowledge_chunks kc
                    join knowledge_documents kd on kd.id = kc.document_id
                    where kc.tenant_id = cast(:tenant_id as uuid)
                      and kd.status in ('indexed', 'published')
                      and kc.text ilike '%tipo_registro: requisitos_plan_credito%'
                    order by kc.chunk_index
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
        requirements = [_parse_kv_text(str(row["text"] or "")) for row in requirement_rows]

        faq_rows = (
            await session.execute(
                text(
                    """
                    select question, answer, status, updated_at::text as updated_at
                    from tenant_faqs
                    where tenant_id = cast(:tenant_id as uuid)
                      and status = 'published'
                    order by question
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
        faqs = [dict(row) for row in faq_rows]

        version_row = (
            await session.execute(
                text(
                    """
                    select
                        max(kd.updated_at)::text as knowledge_version,
                        max(kd.updated_at) filter (
                            where kd.category in ('credit_requirements', 'Documentos')
                              and lower(kd.filename) like '%req%'
                        )::text as requirements_version,
                        max(tf.updated_at)::text as faq_version
                    from tenants t
                    left join knowledge_documents kd on kd.tenant_id = t.id
                    left join tenant_faqs tf on tf.tenant_id = t.id
                    where t.id = cast(:tenant_id as uuid)
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().first()
        first_catalog = catalog_rows[0]
        metadata = PublishedKnowledgeMetadata(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            knowledge_version=str((version_row or {}).get("knowledge_version") or ""),
            catalog_version=(
                f"{first_catalog['catalog_name']}#v{first_catalog['version_number']}"
                f"@{first_catalog['published_at']}"
            ),
            requirements_version=str((version_row or {}).get("requirements_version") or ""),
            faq_version=str((version_row or {}).get("faq_version") or ""),
        )
        return cls(
            metadata=metadata,
            catalog_items=catalog_items,
            requirements=requirements,
            faqs=faqs,
        )

    def source_metadata(self) -> dict[str, Any]:
        return {
            "quote_source": QUOTE_SOURCE,
            "catalog_source": CATALOG_SOURCE,
            "requirements_source": REQUIREMENTS_SOURCE,
            "faq_source": FAQ_SOURCE,
            "tenant_id": self.metadata.tenant_id,
            "tenant": self.metadata.tenant_name,
            "knowledge_version": self.metadata.knowledge_version,
            "catalog_version": self.metadata.catalog_version,
            "requirements_version": self.metadata.requirements_version,
            "faq_version": self.metadata.faq_version,
            "local_downloads_source": False,
            "fake_deterministic_tools": False,
        }

    def find_model(self, query: Any) -> dict[str, Any] | None:
        matches = self.search_models(query, limit=1)
        return matches[0] if matches else None

    def search_models(self, query: Any, *, limit: int = 3) -> list[dict[str, Any]]:
        normalized = _norm(query)
        if not normalized:
            return []
        scored: list[tuple[int, str, dict[str, Any]]] = []
        work_request = any(token in normalized for token in ("trabajo", "chamba", "reparto"))
        cargo_request = any(token in normalized for token in ("cargo", "heavy", "motocarro", "carga"))
        urban_request = any(token in normalized for token in ("urban", "urbana"))
        for item in self.catalog_items:
            aliases = _catalog_aliases(item)
            category = _norm(item.get("category"))
            sku = _norm(item.get("sku"))
            name = _norm(item.get("name"))
            haystack = " ".join([category, *sorted(aliases)])
            score = 0
            if normalized in aliases:
                score += 120
            if any(alias and alias in normalized for alias in aliases):
                score += 90
            if work_request and category == "trabajo":
                score += 80
            if cargo_request and any(token in haystack for token in ("cargo", "heavy", "motocarro")):
                score += 95
            if urban_request and any(token in haystack for token in ("urban", "urbana", "u2", "u5")):
                score += 95
            if urban_request and sku in {"u2_150_cc", "u5_150_cc"}:
                score += 180
            if urban_request and category == "trabajo":
                score += 60
            if (
                urban_request
                and "naked" in " ".join([category, name, haystack])
                and "naked" not in normalized
            ):
                score -= 220
            if score > 0:
                scored.append((score, str(item.get("name") or ""), item))
        if not scored and cargo_request:
            for item in self.catalog_items:
                if _norm(item.get("category")) == "trabajo":
                    scored.append((40, str(item.get("name") or ""), item))
        if not scored and "urban" in normalized:
            for item in self.catalog_items:
                if _norm(item.get("sku")) == "u2_150_cc":
                    scored.append((30, str(item.get("name") or ""), item))
        scored.sort(key=lambda value: (-value[0], value[1]))
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _, _, item in scored:
            sku = str(item.get("sku") or item.get("name") or "")
            if sku in seen:
                continue
            seen.add(sku)
            unique.append(item)
            if len(unique) >= limit:
                break
        return unique

    def resolve_plan_for_credit(self, credit: Any) -> str | None:
        normalized = _norm(credit)
        for req in self.requirements:
            aliases = [_norm(req.get("tipo_credito")), *[_norm(item) for item in _split_aliases(req.get("aliases"))]]
            if normalized in aliases or any(alias and alias in normalized for alias in aliases):
                return str(req.get("plan_credito") or "").strip() or None
        if "nomina" in normalized and "tarjeta" in normalized:
            return self.resolve_plan_for_credit("Nomina Tarjeta")
        if "sin comprobantes" in normalized or "por fuera" in normalized:
            return self.resolve_plan_for_credit("Sin Comprobantes")
        if "guardia" in normalized or "seguridad" in normalized:
            return self.resolve_plan_for_credit("Guardia de Seguridad")
        return None

    def quote_payload(self, *, model_query: Any, plan_code: Any) -> dict[str, Any]:
        item = self.find_model(model_query)
        if item is None:
            return {"status": "no_data", "hint": f"model {model_query!r} not found in AtendIA KB"}
        resolved_plan = _normalize_plan_code(plan_code) or "20%"
        plan = _find_plan(item, resolved_plan)
        if plan is None:
            return {"status": "no_data", "hint": f"plan {resolved_plan!r} not found in AtendIA KB"}
        eligibility = plan.get("eligibility_rules_json") if isinstance(plan.get("eligibility_rules_json"), dict) else {}
        payment = {
            "down_payment_mxn": _int_or_none(plan.get("down_payment_amount")),
            "enganche_mxn": _int_or_none(plan.get("down_payment_amount")),
            "installment_mxn": _int_or_none(plan.get("installment_amount")),
            "pago_quincenal_mxn": _int_or_none(plan.get("installment_amount")),
            "frequency": plan.get("installment_frequency"),
            "term_count": _int_or_none(plan.get("installment_count")),
            "numero_quincenas": _int_or_none(plan.get("installment_count")),
            "plazo_texto": eligibility.get("plazo_texto") or _term_text(plan.get("installment_count")),
        }
        return {
            "status": "ok",
            **self.source_metadata(),
            "sku": item.get("sku"),
            "name": item.get("name"),
            "category": item.get("category") or "",
            "list_price_mxn": _int_or_none(item.get("list_price")),
            "cash_price_mxn": _int_or_none(item.get("base_price") or item.get("list_price")),
            "requested_plan_code": resolved_plan,
            "payment_options": {resolved_plan: payment},
            "product_details": item.get("attributes_json") if isinstance(item.get("attributes_json"), dict) else {},
            "catalog_expected_plan": {
                "precio_contado_mxn": _int_or_none(item.get("base_price") or item.get("list_price")),
                "precio_lista_mxn": _int_or_none(item.get("list_price")),
                **payment,
            },
        }

    def faq_answer(self, text_value: Any) -> dict[str, Any]:
        normalized = _norm(text_value)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for faq in self.faqs:
            question = _norm(faq.get("question"))
            haystack = _norm(f"{faq.get('question')} {faq.get('answer')}")
            score = 0
            if "ubicacion" in normalized or "donde estan" in normalized:
                score += 200 if any(token in question for token in ("ubicacion", "ubicados", "direccion", "donde estan")) else 0
                score += 80 if any(token in haystack for token in ("benito", "direccion", "centro")) else 0
            if "buro" in normalized:
                score += 200 if "buro" in question else 0
                score += 60 if "buro" in haystack else 0
            if any(token in normalized for token in ("liquid", "adelantar", "abonar")):
                score += 200 if any(token in question for token in ("liquid", "adelantar", "abonar")) else 0
                score += 60 if any(token in haystack for token in ("liquid", "adelantar", "abonar")) else 0
            if "document" in normalized or "que mando" in normalized:
                score += 200 if any(token in question for token in ("requisito", "document")) else 0
                score += 60 if any(token in haystack for token in ("requisito", "document", "ine")) else 0
            if score:
                ranked.append((score, faq))
        if not ranked:
            return {"status": "no_data", "hint": "no AtendIA FAQ matched"}
        ranked.sort(key=lambda item: item[0], reverse=True)
        faq = ranked[0][1]
        return {
            "status": "ok",
            **self.source_metadata(),
            "topic": str(faq.get("question") or ""),
            "answer": str(faq.get("answer") or "").strip(),
        }


def _catalog_aliases(item: dict[str, Any]) -> set[str]:
    attrs = item.get("attributes_json") if isinstance(item.get("attributes_json"), dict) else {}
    values = [item.get("sku"), item.get("name"), attrs.get("modelo"), attrs.get("modelo_moto")]
    for key in ("alias", "aliases", "alias_normalizados"):
        raw = attrs.get(key)
        if isinstance(raw, list):
            values.extend(raw)
    return {_norm(value) for value in values if _norm(value)}


def _find_plan(item: dict[str, Any], plan_code: str) -> dict[str, Any] | None:
    for plan in item.get("plans") or []:
        if isinstance(plan, dict) and _normalize_plan_code(plan.get("plan_code")) == plan_code:
            return plan
    return None


def _parse_kv_text(value: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^([a-zA-Z0-9_]+):\s*(.*)$", line)
        if match:
            current_key = match.group(1)
            result[current_key] = match.group(2).strip()
        elif current_key:
            result[current_key] = f"{result[current_key]}\n{line}".strip()
    return result


def _split_aliases(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _normalize_plan_code(value: Any) -> str | None:
    text_value = str(value or "").strip()
    match = re.search(r"(\d{1,2})\s*%?", text_value)
    if not match:
        return None
    return f"{match.group(1)}%"


def _term_text(value: Any) -> str | None:
    number = _int_or_none(value)
    return f"{number} quincenas" if number else None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    text_value = str(value or "").casefold()
    text_value = unicodedata.normalize("NFKD", text_value)
    text_value = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    text_value = text_value.replace("ã³", "o").replace("ã©", "e").replace("ã¡", "a")
    text_value = re.sub(r"[^a-z0-9%]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()

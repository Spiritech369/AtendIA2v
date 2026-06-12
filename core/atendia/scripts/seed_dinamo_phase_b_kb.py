"""Activate Dinamo Phase B approved tenant sources without external APIs.

Phase B of ``DINAMO_TENANT_RUNTIME_PLAN_V1.md`` publishes the three approved
JSON sources into tenant-scoped runtime data. It keeps the existing Phase A
deployment in no-send/dry-run mode and does not call OpenAI, WhatsApp, Google,
or any external API.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_phase_b_kb \
        --tenant-id <uuid> [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.catalog_runtime import build_catalog_attrs
from atendia.db.models.agent import Agent
from atendia.db.models.knowledge_os import KnowledgeItem, KnowledgeOSChunk, KnowledgeSource
from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentKnowledgeSourceBinding,
    AgentToolBinding,
    AgentVersion,
)
from atendia.db.models.tenant_config import TenantBranding, TenantCatalogItem, TenantFAQ
from atendia.scripts.seed_dinamo_v1 import AGENT_NAME
from atendia.scripts.seed_dinamo_v1 import SEED_ID as PHASE_A_SEED_ID

PHASE_B_SEED_ID = "dinamo_tenant_runtime_plan_v1_phase_b"
SOURCE_VERSION_ID = "DINAMO_TENANT_RUNTIME_PLAN_V1:PHASE_B:2026-06-11"
ROOT = Path(__file__).resolve().parents[3]
DINAMO_DIR = ROOT / "docs" / "tenant_sources" / "dinamo"
CONTRACT_PATH = DINAMO_DIR / "dinamo_runtime_contract.json"
APPROVED_AT = "2026-06-11T00:00:00+00:00"
APPROVED_BY = "user_approved_phase_b"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    source_id: str
    name: str
    source_type: str
    content_type: str
    path: Path
    official_docx: str | None
    priority: int
    required: bool


@dataclass
class PhaseBResult:
    tenant_id: str
    dry_run: bool
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    catalog_models: int = 0
    requirement_plans: int = 0
    faqs: int = 0
    knowledge_items: int = 0
    knowledge_chunks: int = 0
    created_sources: list[str] = field(default_factory=list)
    updated_sources: list[str] = field(default_factory=list)
    created_catalog_items: list[str] = field(default_factory=list)
    updated_catalog_items: list[str] = field(default_factory=list)
    created_faqs: list[str] = field(default_factory=list)
    updated_faqs: list[str] = field(default_factory=list)
    created_bindings: list[str] = field(default_factory=list)
    updated_bindings: list[str] = field(default_factory=list)
    tool_policy_action: str = "unchanged"
    branding_action: str = "unchanged"
    deployment_guard: str = "not_checked"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "dry_run": self.dry_run,
            "sources": self.sources,
            "catalog_models": self.catalog_models,
            "requirement_plans": self.requirement_plans,
            "faqs": self.faqs,
            "knowledge_items": self.knowledge_items,
            "knowledge_chunks": self.knowledge_chunks,
            "created_sources": self.created_sources,
            "updated_sources": self.updated_sources,
            "created_catalog_items": self.created_catalog_items,
            "updated_catalog_items": self.updated_catalog_items,
            "created_faqs": self.created_faqs,
            "updated_faqs": self.updated_faqs,
            "created_bindings": self.created_bindings,
            "updated_bindings": self.updated_bindings,
            "tool_policy_action": self.tool_policy_action,
            "branding_action": self.branding_action,
            "deployment_guard": self.deployment_guard,
        }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _slug(value: str) -> str:
    folded = _fold(value)
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", folded)).strip("_")


def _source_metadata(spec: SourceSpec, *, file_hash: str) -> dict[str, Any]:
    logical_source_type = "requirements" if spec.key == "requirements" else spec.content_type
    return {
        "source": PHASE_B_SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "source_id": spec.source_id,
        "source_type": logical_source_type,
        "knowledge_content_type": spec.content_type,
        "version": SOURCE_VERSION_ID,
        "hash": file_hash,
        "approved_by": APPROVED_BY,
        "approved_at": APPROVED_AT,
        "runtime_status": "approved",
        "json_wins_over_docx": True,
        "path": str(spec.path.relative_to(ROOT)).replace("\\", "/"),
        "official_docx": spec.official_docx,
    }


def load_source_specs(contract_path: Path = CONTRACT_PATH) -> list[SourceSpec]:
    contract = _load_json(contract_path)
    sources = ((contract.get("knowledge_os") or {}).get("sources") or {})
    required = [
        ("catalog", "Dinamo Catalogo Junio 2026", "catalog", 100, True),
        (
            "requirements",
            "Dinamo Requisitos Credito Junio 2026",
            "document_rules",
            100,
            True,
        ),
        ("faq", "Dinamo FAQ Junio 2026", "faq", 80, True),
    ]
    specs: list[SourceSpec] = []
    for key, name, content_type, priority, is_required in required:
        raw = sources.get(key) or {}
        path = ROOT / str(raw["path"])
        specs.append(
            SourceSpec(
                key=key,
                source_id=str(raw["source_id"]),
                name=name,
                source_type="file",
                content_type=content_type,
                path=path,
                official_docx=raw.get("official_docx"),
                priority=priority,
                required=is_required,
            )
        )
    return specs


def _plan_option(plan_code: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan": plan_code,
        "name": plan_code,
        "porcentaje_enganche": raw.get("porcentaje_enganche"),
        "down_payment_mxn": raw.get("enganche_mxn"),
        "enganche_mxn": raw.get("enganche_mxn"),
        "installment_mxn": raw.get("pago_quincenal_mxn"),
        "pago_quincenal_mxn": raw.get("pago_quincenal_mxn"),
        "frequency": "quincenal",
        "term_count": raw.get("numero_quincenas"),
        "numero_quincenas": raw.get("numero_quincenas"),
        "plazo_texto": raw.get("plazo_texto"),
        "respuesta_corta": raw.get("respuesta_corta"),
    }


def normalize_catalog_model(raw: dict[str, Any], source_meta: dict[str, Any]) -> dict[str, Any]:
    label = str(raw.get("modelo") or raw.get("modelo_moto") or raw.get("nombre") or raw["id"])
    sku = str(raw.get("id") or _slug(label))
    aliases = [str(item) for item in raw.get("alias_normalizados") or raw.get("alias") or []]
    if label not in aliases:
        aliases.insert(0, label)
    plans_raw = raw.get("planes_credito_normalizados") or raw.get("planes_credito") or {}
    payment_plans = [
        _plan_option(str(plan_code), plan)
        for plan_code, plan in plans_raw.items()
        if isinstance(plan, dict)
    ]
    attrs = copy.deepcopy(raw)
    attrs.update(
        {
            "model_id": sku,
            "label": label,
            "aliases": aliases,
            "category": raw.get("categoria"),
            "search_text": raw.get("busqueda_texto") or raw.get("texto_retrieval"),
            "payment_plans": payment_plans,
            "payment_options": {plan["plan"]: plan for plan in payment_plans},
        }
    )
    attrs = build_catalog_attrs(
        base_attrs=attrs,
        sku=sku,
        name=label,
        category=raw.get("categoria"),
        price_cents=None,
        payment_plans=payment_plans,
        source_meta=source_meta,
    )
    return {
        "sku": sku,
        "name": label,
        "category": raw.get("categoria"),
        "attrs": attrs,
        "tags": [str(item) for item in raw.get("tags_uso") or []],
        "price_cents": int(raw["precio_contado_mxn"]) * 100
        if raw.get("precio_contado_mxn") is not None
        else None,
        "payment_plans": payment_plans,
        "retrieval_text": raw.get("texto_retrieval") or raw.get("busqueda_texto") or label,
        "runtime_fact": {
            "model_id": sku,
            "label": label,
            "category": raw.get("categoria"),
            "aliases": aliases,
            "tags": [str(item) for item in raw.get("tags_uso") or []],
            "search_text": raw.get("busqueda_texto") or raw.get("texto_retrieval"),
            "price_lista_mxn": raw.get("precio_lista_mxn"),
            "price_contado_mxn": raw.get("precio_contado_mxn"),
            "planes_credito": {plan["plan"]: plan for plan in payment_plans},
        },
    }


def normalize_requirement_plan(raw: dict[str, Any], source_meta: dict[str, Any]) -> dict[str, Any]:
    plan_id = str(raw.get("plan_id") or _slug(str(raw.get("nombre_comercial") or "")))
    data = copy.deepcopy(raw)
    data["source"] = source_meta
    return {
        "id": plan_id,
        "title": str(raw.get("nombre_comercial") or raw.get("tipo_credito") or plan_id),
        "content": str(raw.get("texto_retrieval") or raw.get("respuesta_whatsapp") or ""),
        "structured_data": data,
        "runtime_fact": {
            "plan_id": plan_id,
            "tipo_credito": raw.get("tipo_credito"),
            "plan_credito": raw.get("plan_credito"),
            "aliases_usuario": raw.get("aliases_usuario") or raw.get("alias_normalizados") or [],
            "documentos_requeridos": raw.get("documentos_requeridos") or [],
            "texto_retrieval": raw.get("texto_retrieval") or raw.get("respuesta_whatsapp"),
        },
    }


def normalize_faq(raw: dict[str, Any], source_meta: dict[str, Any]) -> dict[str, Any]:
    question = str(raw.get("pregunta") or "")
    answer = str(raw.get("respuesta") or "")
    return {
        "question": question,
        "answer": answer,
        "tags": [
            PHASE_B_SEED_ID,
            source_meta["source_id"],
            source_meta["hash"],
        ],
        "structured_data": {**copy.deepcopy(raw), "source": source_meta},
        "content": "\n".join(part for part in [question, answer] if part),
    }


def load_phase_b_payload(
    specs: list[SourceSpec] | None = None,
) -> tuple[
    list[SourceSpec],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    specs = specs or load_source_specs()
    meta_by_key = {spec.key: _source_metadata(spec, file_hash=_sha256(spec.path)) for spec in specs}
    catalog = _load_json(next(spec.path for spec in specs if spec.key == "catalog"))
    requirements = _load_json(next(spec.path for spec in specs if spec.key == "requirements"))
    faq = _load_json(next(spec.path for spec in specs if spec.key == "faq"))

    models = [
        normalize_catalog_model(raw, meta_by_key["catalog"])
        for raw in catalog.get("modelos", [])
        if isinstance(raw, dict)
    ]
    plans = [
        normalize_requirement_plan(raw, meta_by_key["requirements"])
        for raw in requirements.get("planes", [])
        if isinstance(raw, dict) and raw.get("activo", True)
    ]
    faqs = [
        normalize_faq(raw, meta_by_key["faq"])
        for raw in faq.get("faq", [])
        if isinstance(raw, dict)
    ]
    return specs, meta_by_key, models, plans, faqs


def build_tool_policy_bindings(
    *,
    existing_bindings: list[dict[str, Any]] | None,
    models: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    meta_by_key: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name = {
        str(binding.get("name") or binding.get("tool_name")): copy.deepcopy(binding)
        for binding in existing_bindings or []
        if isinstance(binding, dict)
    }
    runtime_models = [item["runtime_fact"] for item in models]
    runtime_plans = [item["runtime_fact"] for item in plans]
    updates = {
        "catalog.search": {
            "name": "catalog.search",
            "real_source": "catalog_search",
            "dry_facts": {
                "source": PHASE_B_SEED_ID,
                "source_id": meta_by_key["catalog"]["source_id"],
                "source_hash": meta_by_key["catalog"]["hash"],
                "models": runtime_models,
            },
        },
        "quote.resolve": {
            "name": "quote.resolve",
            "real_source": "catalog_quote",
            "dry_facts": {
                "source": PHASE_B_SEED_ID,
                "source_id": meta_by_key["catalog"]["source_id"],
                "source_hash": meta_by_key["catalog"]["hash"],
                "models": runtime_models,
            },
            "preconditions": [],
        },
        "requirements.lookup": {
            "name": "requirements.lookup",
            "real_source": "knowledge_plans",
            "dry_facts": {
                "source": PHASE_B_SEED_ID,
                "source_id": meta_by_key["requirements"]["source_id"],
                "source_hash": meta_by_key["requirements"]["hash"],
                "requirement_plans": runtime_plans,
            },
        },
    }
    for name, update in updates.items():
        current = by_name.get(name, {"name": name})
        current.update(update)
        current["source_version_id"] = SOURCE_VERSION_ID
        by_name[name] = current
    return list(by_name.values())


async def _get_phase_a_version(session: AsyncSession, tenant_id: UUID) -> AgentVersion:
    agent = (
        await session.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == AGENT_NAME).limit(1)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise RuntimeError("Dinamo Phase A agent is missing; run seed_dinamo_v1 first")
    version = (
        await session.execute(
            select(AgentVersion)
            .where(
                AgentVersion.tenant_id == tenant_id,
                AgentVersion.agent_id == agent.id,
                AgentVersion.status == "draft",
            )
            .order_by(AgentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        raise RuntimeError("Dinamo Phase A draft agent version is missing")
    return version


async def _guard_no_send(session: AsyncSession, tenant_id: UUID, version: AgentVersion) -> str:
    rows = (
        await session.execute(
            select(AgentDeployment).where(
                AgentDeployment.tenant_id == tenant_id,
                AgentDeployment.active_version_id == version.id,
            )
        )
    ).scalars().all()
    unsafe = [
        row
        for row in rows
        if row.send_enabled
        or row.outbox_enabled
        or row.live_send_enabled
        or row.single_contact_smoke_enabled
        or row.actions_enabled
        or row.workflow_events_enabled
        or row.workflow_side_effects_enabled
        or row.canary_enabled
        or row.open_production_enabled
        or row.send_scope != "none"
    ]
    if unsafe:
        raise RuntimeError("Phase B refused to run: active deployment is not no-send")
    return f"checked_{len(rows)}_deployments_no_send"


async def seed_dinamo_phase_b_kb(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    dry_run: bool = False,
) -> PhaseBResult:
    specs, meta_by_key, models, plans, faqs = load_phase_b_payload()
    result = PhaseBResult(
        tenant_id=str(tenant_id),
        dry_run=dry_run,
        sources=meta_by_key,
        catalog_models=len(models),
        requirement_plans=len(plans),
        faqs=len(faqs),
        knowledge_items=len(models) + len(plans) + len(faqs),
        knowledge_chunks=len(models) + len(plans) + len(faqs),
    )
    if dry_run:
        result.created_sources = [spec.source_id for spec in specs]
        result.created_catalog_items = [item["sku"] for item in models]
        result.created_faqs = [item["question"] for item in faqs]
        result.created_bindings = [spec.source_id for spec in specs]
        result.tool_policy_action = "would_update"
        result.branding_action = "would_upsert"
        result.deployment_guard = "would_check_no_send"
        return result

    version = await _get_phase_a_version(session, tenant_id)
    result.deployment_guard = await _guard_no_send(session, tenant_id, version)
    sources = await _upsert_sources(
        session,
        tenant_id=tenant_id,
        specs=specs,
        meta_by_key=meta_by_key,
        result=result,
    )
    await _replace_knowledge_items(
        session,
        tenant_id=tenant_id,
        sources=sources,
        models=models,
        plans=plans,
        faqs=faqs,
        result=result,
    )
    await _upsert_catalog_items(session, tenant_id=tenant_id, models=models, result=result)
    await _upsert_faqs(session, tenant_id=tenant_id, faqs=faqs, result=result)
    await _upsert_branding(session, tenant_id=tenant_id, plans=plans, result=result)
    await _bind_sources(
        session,
        tenant_id=tenant_id,
        version=version,
        specs=specs,
        sources=sources,
        meta_by_key=meta_by_key,
        result=result,
    )
    await _update_agent_tool_policy(
        session,
        tenant_id=tenant_id,
        version=version,
        models=models,
        plans=plans,
        meta_by_key=meta_by_key,
        result=result,
    )
    await session.flush()
    return result


async def _upsert_sources(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    specs: list[SourceSpec],
    meta_by_key: dict[str, dict[str, Any]],
    result: PhaseBResult,
) -> dict[str, KnowledgeSource]:
    existing_rows = (
        await session.execute(select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id))
    ).scalars().all()
    by_source_id = {
        (row.metadata_json or {}).get("source_id"): row
        for row in existing_rows
        if (row.metadata_json or {}).get("source_id")
    }
    out: dict[str, KnowledgeSource] = {}
    for spec in specs:
        meta = meta_by_key[spec.key]
        existing = by_source_id.get(spec.source_id)
        if existing is None:
            existing = KnowledgeSource(
                tenant_id=tenant_id,
                name=spec.name,
                type=spec.source_type,
                content_type=spec.content_type,
                status="active",
                owner="tenant",
                priority=spec.priority,
                metadata_json=meta,
            )
            session.add(existing)
            await session.flush()
            result.created_sources.append(spec.source_id)
        else:
            existing.name = spec.name
            existing.type = spec.source_type
            existing.content_type = spec.content_type
            existing.status = "active"
            existing.owner = "tenant"
            existing.priority = spec.priority
            existing.metadata_json = meta
            result.updated_sources.append(spec.source_id)
        out[spec.key] = existing
    return out


async def _replace_items_for_source(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    source: KnowledgeSource,
    rows: list[dict[str, Any]],
    source_key: str,
) -> None:
    existing_items = (
        await session.execute(
            select(KnowledgeItem).where(
                KnowledgeItem.tenant_id == tenant_id,
                KnowledgeItem.source_id == source.id,
            )
        )
    ).scalars().all()
    for item in existing_items:
        item.active = False
        item.status = "archived"
    existing_chunks = (
        await session.execute(
            select(KnowledgeOSChunk).where(
                KnowledgeOSChunk.tenant_id == tenant_id,
                KnowledgeOSChunk.source_id == source.id,
            )
        )
    ).scalars().all()
    for chunk in existing_chunks:
        chunk.status = "archived"
    for index, row in enumerate(rows):
        item = KnowledgeItem(
            tenant_id=tenant_id,
            source_id=source.id,
            title=row["title"],
            content=row["content"],
            structured_data=row["structured_data"],
            status="active",
            active=True,
            metadata_json={
                "source": PHASE_B_SEED_ID,
                "source_key": source_key,
                "source_id": (source.metadata_json or {}).get("source_id"),
                "source_hash": (source.metadata_json or {}).get("hash"),
                "ordinal": index,
            },
        )
        session.add(item)
        await session.flush()
        session.add(
            KnowledgeOSChunk(
                tenant_id=tenant_id,
                source_id=source.id,
                item_id=item.id,
                chunk_text=row["content"],
                chunk_index=0,
                embedding=None,
                status="active",
                metadata_json={
                    "source": PHASE_B_SEED_ID,
                    "source_key": source_key,
                    "source_id": (source.metadata_json or {}).get("source_id"),
                    "source_hash": (source.metadata_json or {}).get("hash"),
                },
            )
        )


async def _replace_knowledge_items(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sources: dict[str, KnowledgeSource],
    models: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    faqs: list[dict[str, Any]],
    result: PhaseBResult,
) -> None:
    await _replace_items_for_source(
        session,
        tenant_id=tenant_id,
        source=sources["catalog"],
        source_key="catalog",
        rows=[
            {
                "title": item["name"],
                "content": item["retrieval_text"],
                "structured_data": item["attrs"],
            }
            for item in models
        ],
    )
    await _replace_items_for_source(
        session,
        tenant_id=tenant_id,
        source=sources["requirements"],
        source_key="requirements",
        rows=[
            {
                "title": item["title"],
                "content": item["content"],
                "structured_data": item["structured_data"],
            }
            for item in plans
        ],
    )
    await _replace_items_for_source(
        session,
        tenant_id=tenant_id,
        source=sources["faq"],
        source_key="faq",
        rows=[
            {
                "title": item["question"],
                "content": item["content"],
                "structured_data": item["structured_data"],
            }
            for item in faqs
        ],
    )
    result.knowledge_items = len(models) + len(plans) + len(faqs)
    result.knowledge_chunks = result.knowledge_items


async def _upsert_catalog_items(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    models: list[dict[str, Any]],
    result: PhaseBResult,
) -> None:
    rows = (
        await session.execute(
            select(TenantCatalogItem).where(TenantCatalogItem.tenant_id == tenant_id)
        )
    ).scalars().all()
    by_sku = {row.sku: row for row in rows}
    for item in models:
        existing = by_sku.get(item["sku"])
        if existing is None:
            session.add(
                TenantCatalogItem(
                    tenant_id=tenant_id,
                    sku=item["sku"],
                    name=item["name"],
                    category=item["category"],
                    attrs=item["attrs"],
                    tags=item["tags"],
                    active=True,
                    embedding=None,
                    status="published",
                    visibility="agents",
                    priority=100,
                    agent_permissions=[],
                    language="es-MX",
                    price_cents=item["price_cents"],
                    stock_status="unknown",
                    payment_plans=item["payment_plans"],
                )
            )
            result.created_catalog_items.append(item["sku"])
            continue
        existing.name = item["name"]
        existing.category = item["category"]
        existing.attrs = item["attrs"]
        existing.tags = item["tags"]
        existing.active = True
        existing.embedding = None
        existing.status = "published"
        existing.visibility = "agents"
        existing.priority = 100
        existing.language = "es-MX"
        existing.price_cents = item["price_cents"]
        existing.stock_status = "unknown"
        existing.payment_plans = item["payment_plans"]
        result.updated_catalog_items.append(item["sku"])


async def _upsert_faqs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    faqs: list[dict[str, Any]],
    result: PhaseBResult,
) -> None:
    rows = (
        await session.execute(select(TenantFAQ).where(TenantFAQ.tenant_id == tenant_id))
    ).scalars().all()
    by_question = {row.question: row for row in rows}
    for item in faqs:
        existing = by_question.get(item["question"])
        if existing is None:
            session.add(
                TenantFAQ(
                    tenant_id=tenant_id,
                    question=item["question"],
                    answer=item["answer"],
                    tags=item["tags"],
                    embedding=None,
                    status="published",
                    visibility="agents",
                    priority=80,
                    language="es-MX",
                )
            )
            result.created_faqs.append(item["question"])
            continue
        existing.answer = item["answer"]
        existing.tags = item["tags"]
        existing.embedding = None
        existing.status = "published"
        existing.visibility = "agents"
        existing.priority = 80
        existing.language = "es-MX"
        result.updated_faqs.append(item["question"])


async def _upsert_branding(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    plans: list[dict[str, Any]],
    result: PhaseBResult,
) -> None:
    row = (
        await session.execute(select(TenantBranding).where(TenantBranding.tenant_id == tenant_id))
    ).scalar_one_or_none()
    messages = dict(row.default_messages if row else {})
    messages["dinamo_phase_b_requirements"] = {
        "source": PHASE_B_SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "plans": [item["runtime_fact"] for item in plans],
    }
    if row is None:
        session.add(
            TenantBranding(
                tenant_id=tenant_id,
                bot_name="Francisco Esparza",
                voice={},
                default_messages=messages,
            )
        )
        result.branding_action = "created"
        return
    row.default_messages = messages
    result.branding_action = "updated"


async def _bind_sources(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    specs: list[SourceSpec],
    sources: dict[str, KnowledgeSource],
    meta_by_key: dict[str, dict[str, Any]],
    result: PhaseBResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentKnowledgeSourceBinding).where(
                AgentKnowledgeSourceBinding.tenant_id == tenant_id,
                AgentKnowledgeSourceBinding.agent_version_id == version.id,
            )
        )
    ).scalars().all()
    by_source = {row.knowledge_source_id: row for row in rows}
    for spec in specs:
        source = sources[spec.key]
        metadata = {
            "source": PHASE_B_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "source_id": spec.source_id,
            "source_hash": meta_by_key[spec.key]["hash"],
            "content_type": spec.content_type,
        }
        existing = by_source.get(source.id)
        if existing is None:
            session.add(
                AgentKnowledgeSourceBinding(
                    tenant_id=tenant_id,
                    agent_version_id=version.id,
                    knowledge_source_id=source.id,
                    binding_mode="read",
                    required=spec.required,
                    priority=spec.priority,
                    metadata_json=metadata,
                )
            )
            result.created_bindings.append(spec.source_id)
            continue
        existing.binding_mode = "read"
        existing.required = spec.required
        existing.priority = spec.priority
        existing.metadata_json = metadata
        result.updated_bindings.append(spec.source_id)


async def _update_agent_tool_policy(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    models: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    meta_by_key: dict[str, dict[str, Any]],
    result: PhaseBResult,
) -> None:
    knowledge_policy = dict(version.knowledge_policy or {})
    knowledge_policy.update(
        {
            "phase": "B",
            "required_source_ids": [
                meta_by_key["catalog"]["source_id"],
                meta_by_key["requirements"]["source_id"],
            ],
            "optional_source_ids": [meta_by_key["faq"]["source_id"]],
            "source_hashes": {key: meta["hash"] for key, meta in meta_by_key.items()},
            "json_wins_over_docx": True,
        }
    )
    version.knowledge_policy = knowledge_policy
    version.snapshot = {
        **(version.snapshot or {}),
        "phase": "B",
        "source": PHASE_A_SEED_ID,
        "phase_b_source": PHASE_B_SEED_ID,
        "phase_b_source_version_id": SOURCE_VERSION_ID,
    }
    version.change_summary = "Dinamo V1 Phase B approved tenant sources active in no-send."

    tool_policy = dict(version.tool_policy or {})
    bindings = build_tool_policy_bindings(
        existing_bindings=tool_policy.get("bindings"),
        models=models,
        plans=plans,
        meta_by_key=meta_by_key,
    )
    tool_policy["bindings"] = bindings
    tool_policy["required_tools"] = ["catalog.search", "quote.resolve", "requirements.lookup"]
    tool_policy["phase"] = "B"
    version.tool_policy = tool_policy
    result.tool_policy_action = "updated"

    tool_rows = (
        await session.execute(
            select(AgentToolBinding).where(
                AgentToolBinding.tenant_id == tenant_id,
                AgentToolBinding.agent_version_id == version.id,
            )
        )
    ).scalars().all()
    by_name = {row.tool_name: row for row in tool_rows}
    policy_by_name = {binding["name"]: binding for binding in bindings}
    for name in ("catalog.search", "quote.resolve", "requirements.lookup"):
        row = by_name.get(name)
        if row is None:
            continue
        row.enabled = True
        row.required = True
        row.metadata_json = {
            **(row.metadata_json or {}),
            "source": PHASE_B_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "real_source": policy_by_name[name].get("real_source"),
        }


async def _main(tenant_id: UUID, dry_run: bool) -> int:
    if dry_run:
        result = await seed_dinamo_phase_b_kb(_DryRunSession(), tenant_id=tenant_id, dry_run=True)  # type: ignore[arg-type]
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
        print(f"completed_at={datetime.now(UTC).isoformat()}")
        return 0

    from atendia.db.session import _get_factory  # type: ignore[attr-defined]

    factory = _get_factory()
    async with factory() as session:
        result = await seed_dinamo_phase_b_kb(session, tenant_id=tenant_id, dry_run=False)
        await session.commit()
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    print(f"completed_at={datetime.now(UTC).isoformat()}")
    return 0


class _DryRunSession:
    """Marker object; dry-run returns before DB access."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main(args.tenant_id, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

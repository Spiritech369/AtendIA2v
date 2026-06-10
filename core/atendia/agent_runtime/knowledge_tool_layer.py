from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atendia.agent_runtime.canonical import CanonicalProductReference, QuoteSnapshot
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    ToolExecutionResult,
    TurnContext,
)

_LOW_SIGNAL_TOKENS = frozenset(
    {
        "a",
        "al",
        "como",
        "con",
        "de",
        "del",
        "el",
        "en",
        "esta",
        "estan",
        "estar",
        "estoy",
        "la",
        "las",
        "le",
        "lo",
        "los",
        "me",
        "mi",
        "mis",
        "para",
        "pagan",
        "pago",
        "por",
        "recibo",
        "reciben",
        "recibir",
        "recibes",
        "su",
        "sueldo",
        "te",
        "tengo",
        "tu",
        "un",
        "una",
        "y",
    }
)


class TenantKnowledgeToolLayer:
    """Execute only tools requested by ChatGPT's semantic interpretation."""

    async def execute(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
    ) -> list[ToolExecutionResult]:
        facts: dict[str, dict[str, Any]] = {}
        results: list[ToolExecutionResult] = []
        sources = _sources(context)
        for request in decision.required_tools:
            if request.name == "catalog.search":
                result = _catalog_search(context, sources, request.payload)
            elif request.name == "credit_plan.resolve":
                result = _credit_plan_resolve(context, sources, request.payload)
            elif request.name == "requirements.lookup":
                result = _requirements_lookup(context, sources, request.payload)
            elif request.name == "document.check":
                result = _document_check(context, request.payload)
            elif request.name == "expediente.evaluate":
                result = _expediente_evaluate(context, sources, request.payload, facts)
            elif request.name == "faq.lookup":
                result = _faq_lookup(context, sources, request.payload)
            elif request.name == "quote.resolve":
                result = _quote_resolve(context, sources, request.payload, facts)
            else:
                result = ToolExecutionResult(
                    tool_name=request.name,
                    status="skipped",
                    data={"reason": "tool handler not configured"},
                    trace_metadata={"required": request.required},
                )
            if result.status == "succeeded":
                facts[result.tool_name] = dict(result.data)
            results.append(result)
        return results


def _catalog_search(
    context: TurnContext,
    sources: dict[str, Path],
    payload: dict[str, Any],
) -> ToolExecutionResult:
    query = str(
        payload.get("query")
        or payload.get("model")
        or payload.get("category")
        or payload.get("usage")
        or ""
    ).strip()
    path = sources.get("catalog")
    if path is None or not query:
        return _skipped("catalog.search", "catalog source and explicit query required")
    catalog = _read_json(path)
    records = [item for item in _list(catalog.get("modelos")) if isinstance(item, dict)]
    category_matches = _category_catalog_matches(
        records,
        [item for item in _list(catalog.get("categorias")) if isinstance(item, dict)],
        query,
    )
    if category_matches:
        return ToolExecutionResult(
            tool_name="catalog.search",
            status="succeeded",
            data={
                "tenant_id": context.tenant_id,
                "query": query,
                "source_path": _display_path(path),
                "category_matches": [
                    _catalog_payload(item, 1.0) for item in category_matches[:5]
                ],
            },
            trace_metadata={"tenant_id": context.tenant_id, "safe_inputs": {"query": query}},
        )
    matches = _catalog_matches(records, query)
    data: dict[str, Any] = {
        "tenant_id": context.tenant_id,
        "query": query,
        "source_path": _display_path(path),
        "matches": [_catalog_payload(item, score) for item, score in matches[:3]],
    }
    if len(matches) == 1:
        ref = _product_ref(context, path, matches[0][0])
        data["canonical_product_ref"] = ref.model_dump(mode="json")
        data["field_updates"] = [
            {
                "key": "product_selection",
                "value": ref.model_dump(mode="json"),
                "reason": "catalog.search validated model from tenant catalog.",
                "evidence": list(ref.evidence),
                "confidence": 1.0,
            },
            {
                "key": "product_catalog_id",
                "value": ref.product_id,
                "reason": "catalog.search validated model id from tenant catalog.",
                "evidence": list(ref.evidence),
                "confidence": 1.0,
            },
        ]
    return ToolExecutionResult(
        tool_name="catalog.search",
        status="succeeded" if matches else "skipped",
        data=data if matches else {**data, "reason": "no catalog match"},
        trace_metadata={"tenant_id": context.tenant_id, "safe_inputs": {"query": query}},
    )


def _requirements_lookup(
    context: TurnContext,
    sources: dict[str, Path],
    payload: dict[str, Any],
) -> ToolExecutionResult:
    query = str(
        payload.get("income_type")
        or payload.get("tipo_credito")
        or payload.get("plan_credito")
        or payload.get("query")
        or ""
    ).strip()
    path = sources.get("requirements")
    if path is None or not query:
        return _skipped("requirements.lookup", "requirements source and explicit query required")
    plans = [item for item in _list(_read_json(path).get("planes")) if isinstance(item, dict)]
    match = _best_requirement_match(plans, query)
    if match is None:
        return ToolExecutionResult(
            tool_name="requirements.lookup",
            status="skipped",
            data={
                "tenant_id": context.tenant_id,
                "query": query,
                "source_path": _display_path(path),
                "reason": "no validated requirements plan match",
            },
            trace_metadata={"tenant_id": context.tenant_id, "safe_inputs": {"query": query}},
        )
    documents = [
        {
            "key": str(doc.get("documento_id") or _slug(doc.get("nombre"))),
            "label": str(doc.get("nombre") or ""),
            "required": bool(doc.get("obligatorio", True)),
            "detail": str(doc.get("detalle") or ""),
        }
        for doc in _list(match.get("documentos_requeridos"))
        if isinstance(doc, dict)
    ]
    plan = str(match.get("plan_credito") or "")
    down_payment = _int(match.get("enganche_porcentaje")) or _int(plan)
    data = {
        "tenant_id": context.tenant_id,
        "query": query,
        "source_path": _display_path(path),
        "plan_id": match.get("plan_id"),
        "tipo_credito": match.get("tipo_credito"),
        "plan_credito": plan,
        "down_payment_percent": down_payment,
        "requirements": [doc["label"] for doc in documents],
        "documents": documents,
        "field_updates": [
            {
                "key": "plan_selection",
                "value": plan,
                "reason": "requirements.lookup validated income-to-plan mapping.",
                "evidence": [f"requirements:{match.get('plan_id')}"],
                "confidence": 1.0,
            },
            {
                "key": "down_payment_percent",
                "value": down_payment,
                "reason": "requirements.lookup validated down payment percent.",
                "evidence": [f"requirements:{match.get('plan_id')}"],
                "confidence": 1.0,
            },
            {
                "key": "requirements_checklist",
                "value": documents,
                "reason": "requirements.lookup returned documents for validated plan.",
                "evidence": [f"requirements:{match.get('plan_id')}"],
                "confidence": 1.0,
            },
        ],
    }
    return ToolExecutionResult(
        tool_name="requirements.lookup",
        status="succeeded",
        data=data,
        trace_metadata={"tenant_id": context.tenant_id, "safe_inputs": {"query": query}},
    )


def _document_check(
    context: TurnContext,
    payload: dict[str, Any],
) -> ToolExecutionResult:
    attachments = _list(payload.get("attachments")) or _list(context.metadata.get("attachments"))
    if not attachments:
        return _skipped("document.check", "document attachment required")
    detected: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        document_type = _document_type_from_attachment(attachment)
        if not document_type:
            continue
        detected.append(
            {
                "attachment_id": str(attachment.get("id") or attachment.get("attachment_id") or ""),
                "document_type": document_type,
                "status": "accepted_for_review",
                "confidence": float(attachment.get("confidence") or 0.95),
                "metadata": {
                    key: value
                    for key, value in attachment.items()
                    if key
                    in {
                        "period",
                        "month",
                        "side",
                        "sides",
                        "pay_periodicity",
                        "payroll_periodicity",
                    }
                },
            }
        )
    if not detected:
        return ToolExecutionResult(
            tool_name="document.check",
            status="skipped",
            data={
                "tenant_id": context.tenant_id,
                "reason": "no supported document type detected",
                "attachments_seen": len(attachments),
            },
            trace_metadata={"tenant_id": context.tenant_id},
        )
    return ToolExecutionResult(
        tool_name="document.check",
        status="succeeded",
        data={
            "tenant_id": context.tenant_id,
            "documents_detected": detected,
            "classification_only": True,
        },
        trace_metadata={
            "tenant_id": context.tenant_id,
            "attachments_seen": len(attachments),
            "safe_inputs": {"attachment_count": len(attachments)},
        },
    )


def _expediente_evaluate(
    context: TurnContext,
    sources: dict[str, Path],
    payload: dict[str, Any],
    facts: dict[str, dict[str, Any]],
) -> ToolExecutionResult:
    path = sources.get("requirements")
    plan_query = str(
        payload.get("plan_credito")
        or payload.get("tipo_credito")
        or payload.get("income_type")
        or _current_context_value(context, "plan_selection")
        or ""
    ).strip()
    if path is None or not plan_query:
        return _skipped("expediente.evaluate", "requirements source and validated plan required")
    plans = [item for item in _list(_read_json(path).get("planes")) if isinstance(item, dict)]
    match = _best_requirement_match(plans, plan_query)
    if match is None:
        return _skipped("expediente.evaluate", "no expediente plan match")
    existing_documents_value = payload.get("existing_documents") or _current_context_value(
        context,
        "Docs_Checklist",
    )
    existing_documents = _documents_from_existing_checklist(existing_documents_value)
    documents_detected = [
        *[item for item in existing_documents if isinstance(item, dict)],
        *[
            item
            for item in _list(_dict(facts.get("document.check")).get("documents_detected"))
            if isinstance(item, dict)
        ],
    ]
    periodicity = str(
        payload.get("payroll_periodicity")
        or payload.get("pay_periodicity")
        or _current_context_value(context, "payroll_periodicity")
        or _detected_periodicity(documents_detected)
        or "semanal"
    ).strip()
    checklist = _expediente_checklist(
        tenant_id=context.tenant_id,
        source_path=path,
        plan=match,
        documents_detected=documents_detected,
        periodicity=periodicity,
    )
    requirements_complete = bool(checklist["requirements_complete"])
    field_updates = [
        {
            "key": "Docs_Checklist",
            "value": checklist,
            "reason": "expediente.evaluate calculated document checklist from Expedientes.",
            "evidence": [f"requirements:{match.get('plan_id')}", "tool_result:document.check"],
            "confidence": 1.0,
        },
        {
            "key": "requirements_complete",
            "value": requirements_complete,
            "reason": "expediente.evaluate is the authority for document completeness.",
            "evidence": [f"requirements:{match.get('plan_id')}", "tool_result:expediente.evaluate"],
            "confidence": 1.0,
        },
        {
            "key": "requirements_missing",
            "value": checklist["missing_documents"],
            "reason": "expediente.evaluate calculated missing documents.",
            "evidence": [f"requirements:{match.get('plan_id')}", "tool_result:expediente.evaluate"],
            "confidence": 1.0,
        },
    ]
    return ToolExecutionResult(
        tool_name="expediente.evaluate",
        status="succeeded",
        data={
            "tenant_id": context.tenant_id,
            "source_path": _display_path(path),
            "contract": "Expedientes",
            "plan_id": match.get("plan_id"),
            "tipo_credito": match.get("tipo_credito"),
            "plan_credito": match.get("plan_credito"),
            "documents_detected": documents_detected,
            "rules_applied": checklist["rules_applied"],
            "missing_documents": checklist["missing_documents"],
            "requirements_complete": requirements_complete,
            "Doc_Completos": requirements_complete,
            "Docs_Checklist": checklist,
            "field_updates": field_updates,
        },
        trace_metadata={
            "tenant_id": context.tenant_id,
            "contract": "Expedientes",
            "source_path": _display_path(path),
        },
    )


def _credit_plan_resolve(
    context: TurnContext,
    sources: dict[str, Path],
    payload: dict[str, Any],
) -> ToolExecutionResult:
    raw_answer = str(payload.get("raw_answer") or "").strip()
    candidate = str(payload.get("income_candidate") or "").strip()
    evidence = str(payload.get("evidence") or "").strip()
    query = (
        candidate
        or evidence
        or raw_answer
        or str(
            payload.get("income_signal")
            or payload.get("income_type")
            or payload.get("tipo_credito")
            or payload.get("query")
            or payload.get("text")
            or ""
        ).strip()
    )
    path = sources.get("requirements")
    if path is None or not query:
        return _skipped(
            "credit_plan.resolve",
            "requirements source and explicit income signal required",
        )
    requirements = _read_json(path)
    plans = [item for item in _list(requirements.get("planes")) if isinstance(item, dict)]
    policy = _income_resolution_policy(context, requirements)
    policy_text = " ".join(item for item in (query, evidence, raw_answer) if item)
    policy_plan_id = _plan_id_from_income_policy(policy, policy_text, candidate)
    if policy_plan_id:
        match = _requirement_by_plan_id(plans, policy_plan_id)
    elif _candidate_requires_clarification_without_evidence(policy, policy_text, candidate):
        return _income_clarification_result(
            context=context,
            path=path,
            query=query,
            raw_answer=raw_answer,
            candidate=candidate,
            payload=payload,
            policy=policy,
        )
    elif _income_policy_needs_clarification(policy, policy_text, candidate):
        return _income_clarification_result(
            context=context,
            path=path,
            query=query,
            raw_answer=raw_answer,
            candidate=candidate,
            payload=payload,
            policy=policy,
        )
    else:
        match = None
    if match is None:
        match = _best_requirement_match(plans, query)
    if match is None and raw_answer:
        match = _best_requirement_match(plans, raw_answer)
    if match is None:
        return ToolExecutionResult(
            tool_name="credit_plan.resolve",
            status="skipped",
            data={
                "tenant_id": context.tenant_id,
                "query": query,
                "raw_answer": raw_answer,
                "income_candidate": candidate,
                "source_path": _display_path(path),
                "reason": "no validated credit plan match",
            },
            trace_metadata={"tenant_id": context.tenant_id, "safe_inputs": {"query": query}},
        )
    plan = str(match.get("plan_credito") or "")
    down_payment = _int(match.get("enganche_porcentaje")) or _int(plan)
    data = {
        "tenant_id": context.tenant_id,
        "query": query,
        "raw_answer": raw_answer,
        "income_candidate": candidate,
        "pending_slot": payload.get("pending_slot"),
        "last_bot_question": payload.get("last_bot_question"),
        "source_path": _display_path(path),
        "plan_id": match.get("plan_id"),
        "tipo_credito": match.get("tipo_credito"),
        "plan_credito": plan,
        "down_payment_percent": down_payment,
        "field_updates": [
            {
                "key": "plan_selection",
                "value": plan,
                "reason": "credit_plan.resolve validated income-to-plan mapping.",
                "evidence": [f"requirements:{match.get('plan_id')}"],
                "confidence": 1.0,
            },
            {
                "key": "down_payment_percent",
                "value": down_payment,
                "reason": "credit_plan.resolve validated down payment percent.",
                "evidence": [f"requirements:{match.get('plan_id')}"],
                "confidence": 1.0,
            },
        ],
    }
    return ToolExecutionResult(
        tool_name="credit_plan.resolve",
        status="succeeded",
        data=data,
        trace_metadata={"tenant_id": context.tenant_id, "safe_inputs": {"query": query}},
    )


def _income_clarification_result(
    *,
    context: TurnContext,
    path: Path,
    query: str,
    raw_answer: str,
    candidate: str,
    payload: dict[str, Any],
    policy: dict[str, Any],
) -> ToolExecutionResult:
    pending_slot = policy.get("ambiguous_pending_slot") or payload.get("pending_slot")
    return ToolExecutionResult(
        tool_name="credit_plan.resolve",
        status="succeeded",
        data={
            "tenant_id": context.tenant_id,
            "query": query,
            "raw_answer": raw_answer,
            "income_candidate": candidate,
            "pending_slot": pending_slot,
            "last_bot_question": payload.get("last_bot_question"),
            "source_path": _display_path(path),
            "needs_clarification": True,
            "clarification": {
                "code": "income_business_tax_status_required",
                "pending_slot": pending_slot,
                "source": "tenant_income_resolution_policy",
            },
            "field_updates": [],
        },
        trace_metadata={
            "tenant_id": context.tenant_id,
            "safe_inputs": {"query": query},
            "income_resolution_policy": "needs_clarification",
        },
    )


def _document_type_from_attachment(attachment: dict[str, Any]) -> str | None:
    raw = _fold(
        attachment.get("document_type")
        or attachment.get("kind")
        or attachment.get("name")
        or attachment.get("filename")
        or attachment.get("id")
        or ""
    )
    if not raw:
        return None
    if "ine" in raw or "identificacion" in raw:
        return "ine_ambos_lados"
    if "nomina" in raw or "payroll" in raw or "recibo" in raw:
        return "nomina_1_mes_dentro_estado_cuenta"
    if "cfe" in raw or "domicilio" in raw or "comprobante" in raw:
        return "comprobante_domicilio"
    if "estado" in raw or "cuenta" in raw or "bank" in raw:
        return "estados_cuenta_recientes"
    return None


def _expediente_checklist(
    *,
    tenant_id: str,
    source_path: Path,
    plan: dict[str, Any],
    documents_detected: list[dict[str, Any]],
    periodicity: str,
) -> dict[str, Any]:
    received_by_type: dict[str, list[dict[str, Any]]] = {}
    for item in documents_detected:
        doc_type = str(item.get("document_type") or "")
        if doc_type:
            received_by_type.setdefault(doc_type, []).append(item)
    rules_applied: list[dict[str, Any]] = []
    missing_documents: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for requirement in _list(plan.get("documentos_requeridos")):
        if not isinstance(requirement, dict):
            continue
        key = str(requirement.get("documento_id") or _slug(requirement.get("nombre")))
        label = str(requirement.get("nombre") or key)
        docs = received_by_type.get(key, [])
        required_count = _required_document_count(requirement, periodicity)
        received_count = _received_document_count(key, docs)
        missing_count = max(required_count - received_count, 0)
        status = "received" if missing_count == 0 else ("partial" if received_count else "missing")
        accepted_for_review = received_count > 0
        item = {
            "key": key,
            "label": label,
            "required": bool(requirement.get("obligatorio", True)),
            "status": status,
            "accepted_for_review": accepted_for_review,
            "received_count": received_count,
            "required_count": required_count,
            "missing_count": missing_count,
            "detail": str(requirement.get("detalle") or ""),
        }
        if "nomina" in key:
            item.update(
                {
                    "periodicity": periodicity,
                    "nominas_requeridas": required_count,
                    "nominas_recibidas": received_count,
                    "nominas_faltantes": missing_count,
                }
            )
            rules_applied.append(
                {
                    "rule": "nomina_count_by_periodicity",
                    "document_key": key,
                    "periodicity": periodicity,
                    "required_count": required_count,
                    "received_count": received_count,
                    "missing_count": missing_count,
                }
            )
        if missing_count:
            missing_documents.append(
                {
                    "key": key,
                    "label": label,
                    "missing_count": missing_count,
                    "required_count": required_count,
                    "received_count": received_count,
                }
            )
        items.append(item)
    return {
        "tenant_id": tenant_id,
        "contract": "Expedientes",
        "source_path": _display_path(source_path),
        "plan_id": plan.get("plan_id"),
        "tipo_credito": plan.get("tipo_credito"),
        "plan_credito": plan.get("plan_credito"),
        "items": items,
        "documents_detected": documents_detected,
        "missing_documents": missing_documents,
        "rules_applied": rules_applied,
        "requirements_complete": not any(
            item["missing_count"] for item in items if item["required"]
        ),
    }


def _required_document_count(requirement: dict[str, Any], periodicity: str) -> int:
    quantity = _dict(requirement.get("cantidad_segun_periodicidad"))
    if quantity:
        return _int(quantity.get(_fold(periodicity))) or 1
    key = _fold(requirement.get("documento_id") or requirement.get("nombre"))
    if "2 estados" in _fold(requirement.get("nombre")) or "estados_cuenta_recientes" in key:
        return 2
    return 1


def _received_document_count(key: str, documents: list[dict[str, Any]]) -> int:
    if key == "ine_ambos_lados":
        return 1 if documents else 0
    return len(documents)


def _detected_periodicity(documents: list[dict[str, Any]]) -> str | None:
    for document in documents:
        metadata = _dict(document.get("metadata"))
        value = metadata.get("payroll_periodicity") or metadata.get("pay_periodicity")
        if value:
            return str(value)
    return None


def _documents_from_existing_checklist(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        docs = value.get("documents_detected")
        if isinstance(docs, list):
            return [item for item in docs if isinstance(item, dict)]
    return []


def _current_context_value(context: TurnContext, key: str) -> Any:
    aliases = {
        "Docs_Checklist": "requirements_checklist",
        "Doc_Completos": "requirements_complete",
    }
    alias = aliases.get(key)
    if key in context.customer.attrs:
        return context.customer.attrs.get(key)
    if key in context.memory.salient_facts:
        return context.memory.salient_facts.get(key)
    if key in context.memory.documents:
        return context.memory.documents.get(key)
    if alias:
        if alias in context.customer.attrs:
            return context.customer.attrs.get(alias)
        if alias in context.memory.salient_facts:
            return context.memory.salient_facts.get(alias)
        if alias in context.memory.documents:
            return context.memory.documents.get(alias)
    return None


def _faq_lookup(
    context: TurnContext,
    sources: dict[str, Path],
    payload: dict[str, Any],
) -> ToolExecutionResult:
    query = str(payload.get("query") or payload.get("policy_topic") or "").strip()
    path = sources.get("faq")
    if path is None or not query:
        return _skipped("faq.lookup", "faq source and explicit query required")
    records = [item for item in _list(_read_json(path).get("faq")) if isinstance(item, dict)]
    matches = _faq_matches(records, query)
    data = {
        "tenant_id": context.tenant_id,
        "query": query,
        "source_path": _display_path(path),
        "matches": [
            {
                "question": item.get("pregunta"),
                "answer_facts": {
                    "policy": item.get("respuesta"),
                    "details_by_plan": item.get("detalle_por_plan") or {},
                    "documents": item.get("documentos") or [],
                    "url": item.get("enlace") or item.get("maps"),
                    "address": item.get("direccion"),
                },
                "score": score,
            }
            for item, score in matches[:3]
        ],
    }
    return ToolExecutionResult(
        tool_name="faq.lookup",
        status="succeeded" if matches else "skipped",
        data=data if matches else {**data, "reason": "no faq match"},
        trace_metadata={"tenant_id": context.tenant_id, "safe_inputs": {"query": query}},
    )


def _quote_resolve(
    context: TurnContext,
    sources: dict[str, Path],
    payload: dict[str, Any],
    facts: dict[str, dict[str, Any]],
) -> ToolExecutionResult:
    product_query = str(
        payload.get("model")
        or payload.get("product_query")
        or _dict(_dict(facts.get("catalog.search")).get("canonical_product_ref")).get(
            "display_name"
        )
        or ""
    ).strip()
    plan_percent = _int(
        payload.get("down_payment_percent")
        or payload.get("plan_credito")
        or _dict(facts.get("credit_plan.resolve")).get("down_payment_percent")
        or _dict(facts.get("requirements.lookup")).get("down_payment_percent")
    )
    path = sources.get("catalog")
    if path is None or not product_query or plan_percent is None:
        return _skipped("quote.resolve", "catalog source, model and plan required")
    records = [item for item in _list(_read_json(path).get("modelos")) if isinstance(item, dict)]
    matches = _catalog_matches(records, product_query)
    if len(matches) != 1:
        return _skipped("quote.resolve", "single validated catalog model required")
    product = matches[0][0]
    plan = _catalog_plan(product, plan_percent)
    if plan is None:
        return _skipped("quote.resolve", "validated catalog plan required")
    ref = _product_ref(context, path, product)
    snapshot = QuoteSnapshot(
        snapshot_id=f"quote-{ref.product_id}-plan-{plan_percent}",
        tenant_id=context.tenant_id,
        product=ref,
        plan_id=f"plan_{plan_percent}",
        plan_code=f"{plan_percent}%",
        plan_name=f"{plan_percent}% credito",
        pricing={
            "cash_price": product.get("precio_contado_mxn")
            or _dict(product.get("precios_mxn")).get("contado"),
            "list_price": product.get("precio_lista_mxn")
            or _dict(product.get("precios_mxn")).get("lista"),
            "down_payment": plan.get("enganche_mxn"),
            "installment": plan.get("pago_quincenal_mxn"),
            "installments": plan.get("numero_quincenas"),
            "period_label": "quincenas",
        },
        requirements=_dict(facts.get("requirements.lookup")),
        source_tool="quote.resolve",
        source_version="tenant_knowledge_tool_layer_v1",
        evidence=[*ref.evidence, f"plan:{plan_percent}%"],
        created_at=datetime.now(UTC).isoformat(),
    ).with_integrity_hash()
    return ToolExecutionResult(
        tool_name="quote.resolve",
        status="succeeded",
        data={"tenant_id": context.tenant_id, "quote_snapshot": snapshot.model_dump(mode="json")},
        trace_metadata={"tenant_id": context.tenant_id},
    )


def _sources(context: TurnContext) -> dict[str, Path]:
    raw_sources = _dict(_dict(context.tenant_config.metadata.get("knowledge_os")).get("sources"))
    out: dict[str, Path] = {}
    for key, value in raw_sources.items():
        path_value = value.get("path") if isinstance(value, dict) else value
        if isinstance(path_value, str):
            path = _resolve(path_value)
            if path.exists():
                out[_canonical_source_key(key, path)] = path
    for value in context.tenant_config.knowledge_sources:
        path = _resolve(value)
        if not path.exists():
            continue
        folded = _fold(path.name)
        if "catalog" in folded or "catalogo" in folded:
            out.setdefault("catalog", path)
        elif "requisito" in folded or "expediente" in folded:
            out.setdefault("requirements", path)
        elif "faq" in folded:
            out.setdefault("faq", path)
    return out


def _canonical_source_key(key: Any, path: Path) -> str:
    folded = _fold(key)
    path_folded = _fold(path.name)
    if folded in {"requirements", "requisitos", "expedientes", "expediente"}:
        return "requirements"
    if folded in {"catalog", "catalogo"}:
        return "catalog"
    if folded == "faq":
        return "faq"
    if "requisito" in path_folded or "expediente" in path_folded:
        return "requirements"
    if "catalog" in path_folded or "catalogo" in path_folded:
        return "catalog"
    return str(key)


def _catalog_matches(
    records: list[dict[str, Any]],
    query: str,
) -> list[tuple[dict[str, Any], float]]:
    normalized = _fold(query)
    matches: list[tuple[dict[str, Any], float]] = []
    for item in records:
        aliases = _aliases(
            item,
            "modelo_moto",
            "modelo",
            "id",
            "alias",
            "alias_normalizados",
            "aliases_modelo_moto",
        )
        score = 1.0 if normalized in aliases else _best_overlap(normalized, aliases)
        if score >= 0.72:
            matches.append((item, score))
    matches.sort(key=lambda item: item[1], reverse=True)
    if len(matches) > 1 and matches[0][1] == 1.0:
        return [matches[0]]
    return matches[:3]


def _category_catalog_matches(
    records: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    normalized = _fold(query)
    category_tokens: set[str] = set()
    for category in categories:
        aliases = _aliases(category, "id", "nombre", "aliases", "alias_normalizados")
        if normalized in aliases or _best_overlap(normalized, aliases) >= 0.72:
            category_tokens.update(aliases)
    if not category_tokens:
        return []
    matches: list[dict[str, Any]] = []
    for item in records:
        item_category = _fold(item.get("categoria") or item.get("category"))
        if item_category and any(
            token == item_category or token in item_category or item_category in token
            for token in category_tokens
        ):
            matches.append(item)
    return matches


def _best_requirement_match(records: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    normalized = _fold(query)
    best: tuple[dict[str, Any], float] | None = None
    for item in records:
        aliases = _aliases(
            item,
            "tipo_credito",
            "plan_credito",
            "plan_id",
            "aliases_usuario",
            "alias_normalizados",
        )
        score = 1.0 if normalized in aliases else _best_overlap(normalized, aliases)
        if score >= 0.72 and (best is None or score > best[1]):
            best = (item, score)
    return best[0] if best else None


def _requirement_by_plan_id(records: list[dict[str, Any]], plan_id: str) -> dict[str, Any] | None:
    wanted = _fold(plan_id)
    for item in records:
        if _fold(item.get("plan_id")) == wanted:
            return item
    return None


def _income_resolution_policy(
    context: TurnContext,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    contract = _dict(context.tenant_config.tenant_domain_contract)
    return {
        **_dict(requirements.get("income_resolution_policy")),
        **_dict(contract.get("income_resolution_policy")),
    }


def _plan_id_from_income_policy(
    policy: dict[str, Any],
    text: str,
    candidate: str,
) -> str | None:
    folded_text = _fold(text)
    folded_candidate = _fold(candidate)
    best: tuple[int, str] | None = None
    for rule in _list(policy.get("resolution_rules")):
        if not isinstance(rule, dict):
            continue
        plan_id = str(rule.get("plan_id") or "").strip()
        if not plan_id:
            continue
        rule_candidate = _fold(rule.get("candidate"))
        evidence_score = _income_signal_match_score(folded_text, rule.get("evidence_any"))
        candidate_score = 1 if rule_candidate and folded_candidate == rule_candidate else 0
        if evidence_score <= 0 and candidate_score <= 0:
            continue
        if evidence_score <= 0 and rule.get("evidence_any"):
            continue
        score = evidence_score * 10 + candidate_score
        if best is None or score > best[0]:
            best = (score, plan_id)
    return best[1] if best else None


def _income_policy_needs_clarification(
    policy: dict[str, Any],
    text: str,
    candidate: str,
) -> bool:
    folded_text = _fold(text)
    if not folded_text:
        return False
    if _matches_any_income_signal(folded_text, policy.get("ambiguous_signals")):
        return True
    for rule in _list(policy.get("clarification_rules")):
        if not isinstance(rule, dict):
            continue
        rule_candidate = _fold(rule.get("candidate"))
        if rule_candidate and _fold(candidate) and rule_candidate != _fold(candidate):
            continue
        if _matches_any_income_signal(folded_text, rule.get("signals")):
            return True
    return False


def _candidate_requires_clarification_without_evidence(
    policy: dict[str, Any],
    text: str,
    candidate: str,
) -> bool:
    if not policy.get("ambiguous_pending_slot"):
        return False
    folded_candidate = _fold(candidate)
    if not folded_candidate:
        return False
    folded_text = _fold(text)
    for rule in _list(policy.get("resolution_rules")):
        if not isinstance(rule, dict):
            continue
        if _fold(rule.get("candidate")) != folded_candidate:
            continue
        evidence = rule.get("evidence_any")
        return bool(evidence) and not _matches_any_income_signal(folded_text, evidence)
    return False


def _matches_any_income_signal(folded_text: str, signals: Any) -> bool:
    return _income_signal_match_score(folded_text, signals) > 0


def _income_signal_match_score(folded_text: str, signals: Any) -> int:
    if not folded_text:
        return 0
    best = 0
    for signal in _list(signals):
        folded_signal = _fold(signal)
        if not folded_signal:
            continue
        if folded_signal == folded_text:
            best = max(best, 1000 + len(folded_signal))
        elif folded_signal in folded_text:
            best = max(best, 100 + len(folded_signal))
    return best


def _faq_matches(records: list[dict[str, Any]], query: str) -> list[tuple[dict[str, Any], float]]:
    normalized = _fold(query)
    matches: list[tuple[dict[str, Any], float]] = []
    for item in records:
        haystack = _fold(" ".join(str(item.get(key) or "") for key in ("pregunta", "respuesta")))
        score = _best_overlap(normalized, {haystack})
        if score >= 0.35:
            matches.append((item, score))
    matches.sort(key=lambda item: item[1], reverse=True)
    return matches[:3]


def _aliases(item: dict[str, Any], *keys: str) -> set[str]:
    values: list[Any] = []
    for key in keys:
        value = item.get(key)
        values.extend(value if isinstance(value, list) else [value])
    return {_fold(value) for value in values if _fold(value)}


def _best_overlap(query: str, aliases: set[str]) -> float:
    query_tokens = set(query.split())
    meaningful_query = _meaningful_tokens(query)
    scores: list[float] = []
    for alias in aliases:
        alias_tokens = set(alias.split())
        meaningful_alias = _meaningful_tokens(alias)
        if meaningful_query and meaningful_query <= meaningful_alias:
            scores.append(0.94)
            continue
        if meaningful_alias and meaningful_alias <= meaningful_query:
            scores.append(0.9)
            continue
        if meaningful_query and meaningful_alias:
            scores.append(
                len(meaningful_query & meaningful_alias)
                / min(len(meaningful_query), len(meaningful_alias))
            )
        if query and (query in alias or alias in query):
            scores.append(min(len(query), len(alias)) / max(len(query), len(alias)))
            continue
        if query_tokens and alias_tokens:
            scores.append(len(query_tokens & alias_tokens) / len(query_tokens | alias_tokens))
    return max(scores, default=0.0)


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token
        for token in value.split()
        if len(token) >= 3 and token not in _LOW_SIGNAL_TOKENS
    }


def _catalog_payload(item: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "product_id": str(item.get("id") or _slug(item.get("modelo_moto") or item.get("modelo"))),
        "name": item.get("modelo_moto") or item.get("modelo"),
        "category": item.get("categoria"),
        "score": score,
    }


def _product_ref(
    context: TurnContext,
    path: Path,
    item: dict[str, Any],
) -> CanonicalProductReference:
    product_id = str(item.get("id") or _slug(item.get("modelo_moto") or item.get("modelo")))
    return CanonicalProductReference(
        product_id=product_id,
        sku=product_id,
        display_name=str(item.get("modelo_moto") or item.get("modelo") or product_id),
        catalog_id=path.stem,
        evidence=[f"tenant:{context.tenant_id}", f"catalog:{product_id}"],
    )


def _catalog_plan(item: dict[str, Any], percent: int) -> dict[str, Any] | None:
    plans = _dict(item.get("planes_credito_normalizados")) or _dict(item.get("planes_credito"))
    for key, value in plans.items():
        if _int(key) == percent and isinstance(value, dict):
            return value
    return None


def _skipped(tool_name: str, reason: str) -> ToolExecutionResult:
    return ToolExecutionResult(tool_name=tool_name, status="skipped", data={"reason": reason})


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (_repo_root() / path).resolve()


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "docs" / "tenant_sources" / "dinamo").exists():
            return parent
    for parent in path.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return path.parents[3]


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_repo_root())).replace("\\", "/")
    except ValueError:
        return str(path)


def _fold(value: Any) -> str:
    text = _repair_mojibake(str(value or "")).casefold().strip()
    normalized = unicodedata.normalize("NFD", text)
    folded = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _repair_mojibake(value: str) -> str:
    try:
        return value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value


def _slug(value: Any) -> str:
    return _fold(value).replace(" ", "_")


def _int(value: Any) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


__all__ = ["TenantKnowledgeToolLayer"]

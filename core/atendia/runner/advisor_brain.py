"""Legacy advisor brain kept for ConversationRunner fallback only.

AgentRuntime v2 owns customer-visible final copy for v2 tenants. This module is
classified KEEP_FALLBACK/DEPRECATE and must not be wired into v2 send paths.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI, BadRequestError

from atendia.config import Settings, get_settings
from atendia.credit_plan_invariants import (
    COMMERCIAL_CREDIT_PLAN_ORDER,
    build_credit_plan_menu,
    canonical_credit_plan_option,
    enforce_credit_plan_invariants,
)
from atendia.runner._openai_errors import _NON_RETRIABLE, _RETRIABLE
from atendia.runner.advisor_brain_prompt import build_advisor_brain_messages
from atendia.runner.advisor_brain_protocol import (
    AgentBrainCommercialGoal,
    AgentBrainPlan,
    AgentBrainPlanUnderstanding,
    AgentBrainToolPlanStep,
    AdvisorBrainInput,
    AdvisorBrainMode,
    AdvisorBrainOutput,
    AdvisorBrainResult,
    AdvisorBrainStateWritePlan,
    AdvisorBrainToolRequest,
)
from atendia.runner.quote_memory_policy import extract_last_quote_from_summary
from atendia.runner.sales_advisor_decision_policy import _pending_acknowledgement_field
from atendia.tools.base import ToolNoDataResult
from atendia.tools.deterministic import get_missing_documents
from atendia.tools.lookup_requirements import lookup_requirements

_SOFT_CLOSE_PATTERNS = {
    "gracias lo veo",
    "lo veo",
    "lo reviso",
    "ok va despues te aviso",
    "lo checo y te aviso",
    "dejame verlo y te digo",
    "lo pienso y te aviso",
    "te aviso despues",
    "despues te digo",
    "nada",
    "luego te digo",
}
_DOC_PATTERNS = {
    "que ocupo",
    "que necesito",
    "que te mando",
    "que mando",
    "te mando que",
    "que documentos",
    "documentos",
    "requisitos",
    "que sigue",
    "quiero avanzar",
    "me interesa",
    "seguimos",
    "le seguimos",
}
_REQUIREMENTS_PATTERNS = {
    "que ocupo",
    "que necesito",
    "que documentos",
    "documentos",
    "requisitos",
}
_SEND_DOCUMENTS_PATTERNS = {
    "que te mando",
    "que mando",
    "te mando que",
    "que sigue",
}
_POST_QUOTE_PROGRESS_PATTERNS = {
    "me interesa",
    "quiero avanzar",
    "le seguimos",
    "seguimos",
    "va",
    "si",
    "sí",
}
_POST_QUOTE_REPEAT_PATTERNS = {
    "si ya me dijiste",
    "ya me dijiste",
    "eso ya lo dijiste",
}
_QUOTE_REFRESH_PATTERNS = (
    "precio",
    "pago",
    "enganche",
    "cuanto queda",
    "cuanto sale",
    "cotizacion",
    "cotizacion",
    "cotiza",
    "cotizar",
)
_SENSITIVE_PATTERNS = (
    "ya di enganche",
    "ya pague",
    "te deposite",
    "te deposité",
    "deposito",
    "transferencia",
    "fraude",
    "denuncia",
    "profeco",
    "legal",
    "abogado",
    "demanda",
    "quiero hablar con un asesor",
    "quiero hablar con asesor",
    "quiero hablar con humano",
    "quiero hablar con un humano",
    "humano",
)
_QUOTE_STEP_KEYS = {"cotizar", "quote", "present_quote", "give_quote"}
_DOCUMENT_STEP_KEYS = {
    "documentos",
    "documents",
    "collect_documents",
    "request_documents",
    "ask_first_missing_document",
    "explain_required_documents",
}
_QUOTE_TEXT_MARKERS = ("enganche", "quincenal", "contado", "plazo")
_CLARIFICATION_MARKERS = (
    "a que te refieres",
    "a qué te refieres",
    "mas detalle",
    "más detalle",
    "me confirmas",
    "cual de las dos",
    "cuál de las dos",
)
_DOCUMENT_TEXT_MARKERS = ("document", "requisito", "ine", "comprobante", "papel")
_SENIORITY_FIELD_KEYS = {"FILTRO", "CUMPLE_ANTIGUEDAD", "ANTIGUEDAD_LABORAL"}
_SENIORITY_PROMPT_MARKERS = ("antiguedad", "empleo actual", "cuanto tiempo", "cuánto tiempo")
_CATALOG_REQUEST_PATTERNS = (
    "catalogo",
    "catálogo",
    "que motos tienes",
    "que modelos tienes",
    "quiero ver motos",
    "quiero ver modelos",
    "ver motos",
    "ver modelos",
    "muestrame motos",
    "muestrame modelos",
)
_GENERIC_MODEL_PATTERNS = (
    "que motos tienes",
    "que modelos tienes",
    "catalogo",
    "catálogo",
    "quiero ver",
    "opciones",
)
_CREDIT_PLAN_MENU_ORDER = COMMERCIAL_CREDIT_PLAN_ORDER
_CREDIT_PLAN_MENU_VARIANTS = {
    "Nomina Tarjeta": {
        "menu_prompt": "Me depositan nomina en tarjeta",
        "plan": "10%",
        "aliases": ["1", "nomina tarjeta", "nomina en tarjeta", "me depositan nomina", "tarjeta"],
    },
    "Nomina Recibos": {
        "menu_prompt": "Me pagan con recibos de nomina",
        "plan": "15%",
        "aliases": ["2", "nomina recibos", "recibos de nomina", "me pagan con recibos"],
    },
    "Pensionados": {
        "menu_prompt": "Soy pensionado",
        "plan": "10%",
        "aliases": ["3", "pensionado", "pensionados", "soy pensionado"],
    },
    "Negocio SAT": {
        "menu_prompt": "Tengo negocio registrado en SAT",
        "plan": "15%",
        "aliases": ["4", "negocio sat", "sat", "tengo negocio", "registrado en sat"],
    },
    "Sin Comprobantes": {
        "menu_prompt": "Me pagan sin comprobantes",
        "plan": "20%",
        "aliases": ["5", "sin comprobantes", "por fuera", "me pagan por fuera", "efectivo"],
    },
    "Guardia de Seguridad": {
        "menu_prompt": "Soy guardia de seguridad",
        "plan": "30%",
        "aliases": ["6", "guardia", "guardia de seguridad", "soy guardia"],
    },
}


def _normalize(value: str | None) -> str:
    raw = str(value or "").strip().casefold()
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_only).strip()


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _render_recent_history(history: list[tuple[str, str]], *, limit: int = 8) -> list[str]:
    rendered: list[str] = []
    for role, text in history[-limit:]:
        cleaned = str(text or "").strip()
        if cleaned:
            rendered.append(f"{role}: {cleaned}")
    return rendered


def _extract_seniority_evidence_from_text(text: str | None) -> str | None:
    normalized = _normalize(text)
    if not normalized:
        return None
    if any(token in normalized for token in ("anos", "ano", "meses", "mes", "trabaj", "empleo", "jubil")):
        return str(text or "").strip() or None
    return None


def _history_seniority_evidence(history: list[tuple[str, str]], conversation_summary: str | None) -> str | None:
    for _role, text in reversed(history):
        evidence = _extract_seniority_evidence_from_text(text)
        if evidence:
            return evidence
    return _extract_seniority_evidence_from_text(conversation_summary)


def _last_bot_message(history: list[tuple[str, str]]) -> str | None:
    for role, text in reversed(history):
        if _normalize(role) in {"assistant", "bot", "outbound", "system"}:
            cleaned = str(text or "").strip()
            if cleaned:
                return cleaned
    return None


def _last_bot_question(history: list[tuple[str, str]]) -> str | None:
    for role, text in reversed(history):
        if _normalize(role) not in {"assistant", "bot", "outbound", "system"}:
            continue
        cleaned = str(text or "").strip()
        normalized = _normalize(cleaned)
        if not cleaned:
            continue
        if "?" in cleaned or any(marker in normalized for marker in ("dime", "me confirmas", "mandame", "mándame")):
            return cleaned
    return None


def _looks_like_quote_text(text: str | None) -> bool:
    raw = str(text or "").strip()
    normalized = _normalize(raw)
    return "$" in raw and any(marker in normalized for marker in _QUOTE_TEXT_MARKERS)


def _last_quote_signature(history: list[tuple[str, str]], active_quote: dict[str, Any] | None) -> str | None:
    if isinstance(active_quote, dict) and active_quote:
        name = str(active_quote.get("name") or active_quote.get("sku") or "").strip()
        plan = str(active_quote.get("requested_plan_code") or "").strip()
        if name or plan:
            return _normalize(f"{name} {plan}")
    for role, text in reversed(history[-8:]):
        if _normalize(role) not in {"assistant", "bot", "outbound", "system"}:
            continue
        candidate = str(text or "").strip()
        if _looks_like_quote_text(candidate):
            return _normalize(candidate)
    return None


def _contact_fields(
    extracted_data: dict[str, Any],
    *,
    active_quote: dict[str, Any] | None = None,
    documents_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in (
        "MOTO",
        "CREDITO",
        "ENGANCHE",
        "plan",
        "PLAN",
        "FILTRO",
        "CUMPLE_ANTIGUEDAD",
        "ANTIGUEDAD_LABORAL",
    ):
        value = _unwrap_value(extracted_data.get(key))
        if value not in (None, "", [], {}):
            fields[key] = value
    if active_quote:
        if fields.get("MOTO") in (None, "", [], {}):
            value = active_quote.get("name") or active_quote.get("sku")
            if value not in (None, "", [], {}):
                fields["MOTO"] = value
        if fields.get("ENGANCHE") in (None, "", [], {}):
            value = active_quote.get("requested_plan_code")
            if value not in (None, "", [], {}):
                fields["ENGANCHE"] = value
    if documents_state:
        selection_key = documents_state.get("selection_key")
        if fields.get("CREDITO") in (None, "", [], {}) and selection_key not in (None, "", [], {}):
            fields["CREDITO"] = selection_key
    return fields


def _missing_contact_fields(
    contact_fields: dict[str, Any],
    *,
    history_seniority_evidence: str | None = None,
) -> list[str]:
    expected = ["MOTO", "CREDITO", "ENGANCHE", "ANTIGUEDAD_LABORAL"]
    missing = [key for key in expected if contact_fields.get(key) in (None, "", [], {})]
    seniority_known = bool(
        history_seniority_evidence
        or contact_fields.get("ANTIGUEDAD_LABORAL")
        or contact_fields.get("FILTRO")
        or contact_fields.get("CUMPLE_ANTIGUEDAD")
    )
    if seniority_known and "ANTIGUEDAD_LABORAL" in missing:
        missing.remove("ANTIGUEDAD_LABORAL")
    return missing


def _active_quote(
    action_payload: dict[str, Any],
    *,
    conversation_summary: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(action_payload, dict):
        action_payload = {}
    if action_payload.get("status") == "ok" and (
        action_payload.get("payment_options") or action_payload.get("requested_plan_code")
    ):
        return {
            "sku": action_payload.get("sku"),
            "name": action_payload.get("name"),
            "requested_plan_code": action_payload.get("requested_plan_code"),
            "payment_options": action_payload.get("payment_options") or {},
            "cash_price_mxn": action_payload.get("cash_price_mxn"),
            "list_price_mxn": action_payload.get("list_price_mxn"),
            "requirements": action_payload.get("requirements") or {},
        }
    memory = extract_last_quote_from_summary(conversation_summary)
    if memory is None:
        return None
    return memory.action_payload()


def _catalog_context(
    *,
    action_payload: dict[str, Any],
    brand_facts: dict[str, Any] | None,
    knowledge_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if isinstance(action_payload, dict):
        for key in ("query", "results", "total_results", "catalog_url", "request_type", "name", "sku"):
            value = action_payload.get(key)
            if value not in (None, "", [], {}):
                context[key] = value
    if brand_facts and brand_facts.get("catalog_url") and "catalog_url" not in context:
        context["catalog_url"] = brand_facts.get("catalog_url")
    if isinstance(knowledge_pack, dict) and knowledge_pack.get("catalog"):
        context.setdefault("knowledge_pack_catalog", "available")
    return context


def _requirements_context(
    *,
    pipeline: Any,
    extracted_data: dict[str, Any],
    action_payload: dict[str, Any],
    active_quote: dict[str, Any] | None,
    knowledge_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    requirements = action_payload.get("requirements")
    if isinstance(requirements, dict):
        return dict(requirements)
    quote_requirements = (active_quote or {}).get("requirements")
    if isinstance(quote_requirements, dict) and quote_requirements:
        return dict(quote_requirements)
    try:
        selection_key = _unwrap_value(extracted_data.get(getattr(pipeline, "document_requirements_field", "CREDITO")))
        if selection_key in (None, "", [], {}):
            selection_key = _unwrap_value(extracted_data.get("CREDITO"))
        looked_up = lookup_requirements(
            pipeline=pipeline,
            selection_key=str(selection_key) if selection_key not in (None, "", [], {}) else None,
            customer_attrs={key: _unwrap_value(value) for key, value in extracted_data.items()},
        )
        if not isinstance(looked_up, ToolNoDataResult):
            return looked_up.model_dump(mode="json")
    except Exception:
        pass
    if isinstance(knowledge_pack, dict) and isinstance(knowledge_pack.get("credit_requirements"), dict):
        return {"knowledge_pack_credit_requirements": "available"}
    return {}


def _documents_state(
    *,
    pipeline: Any,
    extracted_data: dict[str, Any],
    action_payload: dict[str, Any],
) -> dict[str, Any]:
    documents_state = _documents_state(
        pipeline=pipeline,
        extracted_data=extracted_data,
        action_payload=action_payload,
    )

    requirements = action_payload.get("requirements")
    if isinstance(requirements, dict):
        for key in ("selection_key", "selection_label", "required", "received", "missing", "complete"):
            value = requirements.get(key)
            if value not in (None, "", [], {}):
                documents_state.setdefault(key, value)
    for key in ("received_this_turn", "pending_after", "received_documents", "accepted_documents"):
        value = action_payload.get(key)
        if value not in (None, "", [], {}):
            documents_state[key] = value
    return documents_state


def _attachment_context(*, attachments: list[Any], vision_result: Any | None) -> dict[str, Any]:
    payload = {
        "attachment_count": len(attachments),
        "attachments": [
            {
                "mime_type": getattr(item, "mime_type", None),
                "caption": getattr(item, "caption", None),
                "has_url": bool(getattr(item, "url", None)),
            }
            for item in attachments
        ],
    }
    if vision_result is not None:
        try:
            payload["vision_result"] = vision_result.model_dump(mode="json")
        except AttributeError:
            payload["vision_result"] = str(vision_result)
    return payload


def _operational_risk_flags(operational_intent: Any | None, inbound_text: str) -> list[str]:
    flags: list[str] = []
    if operational_intent is not None:
        for attr in ("intent_category", "risk_level", "reason_code"):
            value = getattr(operational_intent, attr, None)
            if value:
                flags.append(f"{attr}:{value}")
        for signal in list(getattr(operational_intent, "signals", []) or []):
            flags.append(f"signal:{signal}")
        effects = getattr(operational_intent, "effects", None)
        if effects is not None:
            if getattr(effects, "pause_bot", False):
                flags.append("effect:pause_bot")
            if getattr(effects, "handoff_required", False):
                flags.append("effect:handoff_required")
    normalized = _normalize(inbound_text)
    for pattern in _SENSITIVE_PATTERNS:
        if pattern in normalized:
            flags.append(f"message:{pattern}")
    return sorted(set(flags))


def _business_rules(
    *,
    brand_facts: dict[str, Any] | None,
    customer_field_context: dict[str, Any] | None,
    history_seniority_evidence: str | None,
    credit_plan_options: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rules = {
        "persona": "Francisco Esparza",
        "tenant_brand": "Dinamo Motos NL",
        "language": "es-MX",
        "style": "informal, breve, claro, sin emojis",
        "do_not_invent": [
            "precios",
            "pagos",
            "enganches",
            "plazos",
            "requisitos",
            "disponibilidad",
            "aprobacion",
        ],
        "commercial_flow_order": [
            "ask_seniority",
            "resolve_credit_plan",
            "resolve_model",
            "quote",
            "ask_first_missing_document",
        ],
    }
    if brand_facts:
        if brand_facts.get("agent_goal"):
            rules["agent_goal"] = brand_facts.get("agent_goal")
        if brand_facts.get("catalog_url"):
            rules["catalog_url"] = brand_facts.get("catalog_url")
    if customer_field_context:
        rules["customer_field_context"] = customer_field_context
    if history_seniority_evidence:
        rules["history_memory_hints"] = {
            "seniority_mentioned_in_history": history_seniority_evidence,
        }
    if credit_plan_options:
        rules["credit_plan_options"] = credit_plan_options
    return rules


def _credit_plan_option_catalog(pipeline: Any) -> list[dict[str, Any]]:
    return build_credit_plan_menu(pipeline)


def build_advisor_brain_input(
    *,
    tenant_id: UUID | str,
    agent_row: Any | None,
    inbound_text: str,
    history: list[tuple[str, str]],
    conversation_summary: str | None,
    current_stage: str,
    extracted_data: dict[str, Any],
    action_payload: dict[str, Any],
    pipeline: Any,
    attachments: list[Any],
    vision_result: Any | None,
    operational_intent: Any | None,
    brand_facts: dict[str, Any] | None,
    knowledge_pack: dict[str, Any] | None,
    customer_field_context: dict[str, Any] | None,
    hard_guardrails: list[str],
) -> AdvisorBrainInput:
    history_seniority_evidence = _history_seniority_evidence(history, conversation_summary)
    active_quote = _active_quote(
        action_payload,
        conversation_summary=conversation_summary,
    )
    last_bot_message = _last_bot_message(history)
    last_bot_question = _last_bot_question(history)
    extracted_values = {key: _unwrap_value(value) for key, value in extracted_data.items()}
    pending_field = _pending_acknowledgement_field(last_bot_message, {
        "income_type": extracted_values.get("CREDITO"),
        "plan": extracted_values.get("ENGANCHE") or extracted_values.get("plan"),
        "model": extracted_values.get("MOTO"),
        "employment_seniority": extracted_values.get("ANTIGUEDAD_LABORAL"),
    })
    documents_state: dict[str, Any] = {}
    try:
        missing_docs = get_missing_documents(
            pipeline=pipeline,
            state={"extracted_data": extracted_data},
        )
        if not isinstance(missing_docs, ToolNoDataResult):
            documents_state = missing_docs.model_dump(mode="json")
    except Exception:
        documents_state = {}
    contact_fields = _contact_fields(
        extracted_data,
        active_quote=active_quote,
        documents_state=documents_state,
    )
    credit_options = []
    if active_quote:
        payment_options = active_quote.get("payment_options") or {}
        if isinstance(payment_options, dict):
            for code, payload in payment_options.items():
                if isinstance(payload, dict):
                    credit_options.append({"plan_code": code, **payload})
    credit_plan_options = _credit_plan_option_catalog(pipeline)
    persona = (
        str(getattr(agent_row, "system_prompt", "") or "").strip()
        or "Francisco Esparza, asesor humano de Dinamo Motos NL."
    )
    return AdvisorBrainInput(
        tenant_id=str(tenant_id),
        agent_id=str(getattr(agent_row, "id", "")) or None,
        agent_name=str(getattr(agent_row, "name", "") or "").strip() or "Francisco Esparza",
        agent_persona=persona,
        user_message=inbound_text,
        recent_history=_render_recent_history(history, limit=12),
        conversation_summary=conversation_summary,
        current_stage=current_stage,
        last_bot_message=last_bot_message,
        last_bot_question=last_bot_question or last_bot_message,
        extracted_data=extracted_values,
        contact_fields=contact_fields,
        missing_contact_fields=_missing_contact_fields(
            contact_fields,
            history_seniority_evidence=history_seniority_evidence,
        ),
        pending_field=pending_field,
        seniority_evidence=history_seniority_evidence,
        active_quote=active_quote,
        last_quote_signature=_last_quote_signature(history, active_quote),
        catalog_context=_catalog_context(
            action_payload=action_payload,
            brand_facts=brand_facts,
            knowledge_pack=knowledge_pack,
        ),
        credit_options=credit_options,
        requirements_context=_requirements_context(
            pipeline=pipeline,
            extracted_data=extracted_data,
            action_payload=action_payload,
            active_quote=active_quote,
            knowledge_pack=knowledge_pack,
        ),
        documents_state=documents_state,
        attachment_context=_attachment_context(
            attachments=attachments,
            vision_result=vision_result,
        ),
        operational_risk_flags=_operational_risk_flags(operational_intent, inbound_text),
        business_rules=_business_rules(
            brand_facts=brand_facts,
            customer_field_context=customer_field_context,
            history_seniority_evidence=history_seniority_evidence,
            credit_plan_options=credit_plan_options,
        ),
        hard_guardrails=list(hard_guardrails),
    )


def summarize_advisor_brain_input(input: AdvisorBrainInput) -> dict[str, Any]:
    requirements = input.requirements_context if isinstance(input.requirements_context, dict) else {}
    documents = input.documents_state if isinstance(input.documents_state, dict) else {}
    return {
        "user_message": input.user_message,
        "current_stage": input.current_stage,
        "known_contact_fields": input.contact_fields,
        "missing_contact_fields": input.missing_contact_fields,
        "pending_field": input.pending_field,
        "seniority_evidence": input.seniority_evidence,
        "has_active_quote": bool(input.active_quote),
        "last_quote_signature": input.last_quote_signature,
        "last_bot_question": input.last_bot_question,
        "selection_key": documents.get("selection_key") or requirements.get("selection_key"),
        "missing_documents": [
            str(item.get("label") or item.get("key"))
            for item in list(documents.get("missing") or [])[:3]
            if isinstance(item, dict)
        ],
        "has_documents_state": bool(input.documents_state),
        "attachment_count": int(input.attachment_context.get("attachment_count") or 0),
        "operational_risk_flags": input.operational_risk_flags,
    }


def _credit_plan_options(context: AdvisorBrainInput) -> list[dict[str, Any]]:
    options = list((context.business_rules or {}).get("credit_plan_options") or [])
    return [dict(option) for option in options if isinstance(option, dict)]


def _credit_plan_canonical(selection_key: str | None) -> dict[str, Any] | None:
    return canonical_credit_plan_option(selection_key)


def _coherent_credit_plan(
    selection_key: str | None,
    down_payment: str | None,
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    return enforce_credit_plan_invariants(selection_key, down_payment)


def _credit_plan_menu_response(context: AdvisorBrainInput) -> str:
    options = _credit_plan_options(context)
    if not options:
        return "Perfecto, para ver tu plan dime como recibes tus ingresos."
    rendered = [
        f"{int(option.get('menu_index') or index)}. {str(option.get('menu_prompt') or option.get('selection_label') or '').strip()}"
        for index, option in enumerate(options, start=1)
        if str(option.get("menu_prompt") or option.get("selection_label") or "").strip()
    ]
    return (
        "Perfecto, para ver que plan te conviene mas, dime como recibes tus ingresos:\n\n"
        + "\n".join(rendered)
        + "\n\nPuedes mandarme el numero o escribir el metodo."
    )


def _catalog_url(context: AdvisorBrainInput) -> str | None:
    for source in (context.catalog_context, context.business_rules):
        if not isinstance(source, dict):
            continue
        value = str(source.get("catalog_url") or "").strip()
        if value:
            return value
    return None


def _brain_plan_tool_name(tool_name: str | None) -> str | None:
    normalized = _normalize(tool_name)
    mapping = {
        "resolve_catalog_model": "catalog.resolve_model",
        "resolve_credit_plan": "credit_plan.resolve",
        "compute_quote": "quote.generate",
        "lookup_requirements": "requirements.resolve",
        "get_missing_documents": "requirements.resolve",
        "classify_attachment": "document.classify",
        "request_handoff": "handoff.request",
    }
    return mapping.get(normalized)


def _brain_plan_payload(
    *,
    input: AdvisorBrainInput,
    next_step: str,
    natural_response: str,
    known_facts: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    normalized_step = _normalize(next_step)
    prompt_payload = {"prompt_override": natural_response} if natural_response else {}
    if normalized_step == "quote":
        return "quote", {}
    if normalized_step == "handoff":
        return "handoff", {
            "status": "ok",
            "request_type": "handoff",
            **prompt_payload,
        }
    if normalized_step == "soft_close":
        return "soft_close", {
            "status": "ok",
            "request_type": "soft_close",
            **prompt_payload,
        }
    if normalized_step == "resolve_model":
        request_type = "resolve_model" if _looks_like_model_candidate(input.user_message) else "catalog_browse"
        payload = {
            "status": "ok",
            "request_type": request_type,
            "query": str(input.user_message or "").strip(),
            **prompt_payload,
        }
        catalog_url = _catalog_url(input)
        if catalog_url:
            payload["catalog_url"] = catalog_url
        return "search_catalog", payload
    if normalized_step in {"resolve_credit_plan", "ask_seniority"}:
        payload = {
            "status": "ok",
            "request_type": (
                "ask_employment_seniority"
                if normalized_step == "ask_seniority"
                else "ask_income_type"
            ),
            "field_name": (
                "ANTIGUEDAD_LABORAL"
                if normalized_step == "ask_seniority"
                else "CREDITO"
            ),
            **prompt_payload,
        }
        if normalized_step != "ask_seniority":
            payload["options"] = _credit_plan_options(input)
        return "ask_credit_context", payload
    if normalized_step in {"ask_first_missing_document", "explain_required_documents"}:
        return "classify_document", {
            "status": "ok",
            "request_type": normalized_step,
            "selection_key": (
                input.documents_state.get("selection_key")
                or input.requirements_context.get("selection_key")
            ),
            "missing": list(input.documents_state.get("missing") or []),
            "requirements": dict(input.requirements_context or {}),
            **prompt_payload,
        }
    if normalized_step == "follow_up":
        missing_fields = list(input.missing_contact_fields or [])
        if missing_fields:
            return "ask_field", {
                "status": "ok",
                "request_type": "ask_missing_field",
                "field_name": missing_fields[0],
                **prompt_payload,
            }
    if known_facts.get("MOTO") not in (None, "", [], {}):
        return "search_catalog", {
            "status": "ok",
            "request_type": "resolve_model",
            "query": str(known_facts.get("MOTO") or "").strip(),
            **prompt_payload,
        }
    return "ask_clarification", {
        "status": "ok",
        "request_type": "clarification_required",
        "suggested_clarification": natural_response,
        **prompt_payload,
    }


def _build_agent_brain_plan(
    *,
    input: AdvisorBrainInput,
    customer_understanding: str,
    detected_intent: str,
    next_step: str,
    known_facts: dict[str, Any],
    state_write_plan: AdvisorBrainStateWritePlan,
    tool_requests: list[AdvisorBrainToolRequest],
    confidence: float,
    natural_response: str,
    trace_reasoning_summary: str,
    handoff_required: bool,
    forbidden_actions: list[str],
) -> AgentBrainPlan:
    proposed_state_updates = {
        **dict(state_write_plan.new_facts_to_write or {}),
        **dict(state_write_plan.corrected_facts or {}),
    }
    proposed_final_action, proposed_final_action_payload = _brain_plan_payload(
        input=input,
        next_step=next_step,
        natural_response=natural_response,
        known_facts=known_facts,
    )
    tool_plan: list[AgentBrainToolPlanStep] = []
    for request in tool_requests:
        plan_tool = _brain_plan_tool_name(getattr(request, "tool_name", None))
        if not plan_tool:
            continue
        tool_plan.append(
            AgentBrainToolPlanStep(
                tool=plan_tool,
                input=dict(getattr(request, "args", {}) or {}),
                required=True,
                reason=str(getattr(request, "reason", "") or "").strip(),
            )
        )
    if proposed_final_action == "quote" and not tool_plan:
        tool_plan.append(
            AgentBrainToolPlanStep(
                tool="quote.generate",
                input={
                    "model": str(known_facts.get("MOTO") or "").strip(),
                    "plan_code": str(known_facts.get("ENGANCHE") or "").strip(),
                },
                required=True,
                reason="La conversacion ya tiene contexto suficiente para cotizar.",
            )
        )
    return AgentBrainPlan(
        understanding=AgentBrainPlanUnderstanding(
            customer_message_summary=str(customer_understanding or "").strip(),
            detected_intents=[str(detected_intent or "").strip()] if str(detected_intent or "").strip() else [],
            entities={key: value for key, value in known_facts.items() if value not in (None, "", [], {})},
            context_resolution={
                "pending_field": input.pending_field,
                "last_bot_question": input.last_bot_question,
                "has_active_quote": bool(input.active_quote or input.last_quote_signature),
                "missing_contact_fields": list(input.missing_contact_fields or []),
            },
            confidence=float(confidence),
        ),
        commercial_goal=AgentBrainCommercialGoal(
            current_goal=str(detected_intent or next_step or "follow_up").strip(),
            next_required_step=str(next_step or "follow_up").strip(),
            reason=str(trace_reasoning_summary or customer_understanding or "").strip(),
        ),
        tool_plan=tool_plan,
        proposed_state_updates=proposed_state_updates,
        proposed_pipeline_update=None,
        proposed_final_action=proposed_final_action,
        proposed_final_action_payload=proposed_final_action_payload,
        customer_response_goal=(
            str(natural_response or "").strip()
            or str(customer_understanding or "").strip()
        ),
        safety_notes=[
            *[str(item).strip() for item in forbidden_actions if str(item).strip()],
            *(
                [str(input.hard_guardrails[0]).strip()]
                if input.hard_guardrails
                else []
            ),
        ],
        needs_human_handoff=bool(handoff_required),
    )


def _is_catalog_request(user_message: str) -> bool:
    normalized = _normalize(user_message)
    return any(pattern in normalized for pattern in _CATALOG_REQUEST_PATTERNS)


def _looks_like_model_candidate(user_message: str) -> bool:
    normalized = _normalize(user_message)
    if not normalized or len(normalized) < 2:
        return False
    if any(pattern in normalized for pattern in _GENERIC_MODEL_PATTERNS):
        return False
    if normalized in {"quiero una moto", "quiero moto", "una moto", "moto"}:
        return False
    if any(
        marker in normalized
        for marker in (
            "credito",
            "ingresos",
            "nomina",
            "pension",
            "sat",
            "guardia",
            "por fuera",
            "sin comprobantes",
            "ano",
            "anos",
            "mes",
            "meses",
            "trabajo",
            "empleo",
        )
    ):
        return False
    if "?" in str(user_message or ""):
        return False
    if any(pattern in normalized for pattern in _DOC_PATTERNS):
        return False
    if any(pattern in normalized for pattern in _SENSITIVE_PATTERNS):
        return False
    return True


def _extract_seniority_months(value: str | None) -> int | None:
    normalized = _normalize(value)
    if not normalized:
        return None
    if "medio ano" in normalized or "medio año" in normalized:
        return 6
    match = re.search(r"(\d+)\s*(ano|anos|mes|meses)", normalized)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("ano"):
        return amount * 12
    return amount


def _seniority_updates(raw_value: str, *, qualifies: bool) -> dict[str, Any]:
    return {
        "ANTIGUEDAD_LABORAL": raw_value,
        "CUMPLE_ANTIGUEDAD": qualifies,
        "FILTRO": "true" if qualifies else "false",
    }


def _credit_plan_choice_from_message(context: AdvisorBrainInput) -> dict[str, Any] | None:
    normalized = _normalize(context.user_message)
    if not normalized:
        return None
    for option in _credit_plan_options(context):
        menu_index = str(option.get("menu_index") or "").strip()
        aliases = {
            _normalize(str(alias))
            for alias in (option.get("aliases") or [])
            if _normalize(str(alias))
        }
        aliases.add(_normalize(str(option.get("selection_key") or "")))
        aliases.add(_normalize(str(option.get("selection_label") or "")))
        if menu_index and normalized in {menu_index, f"opcion {menu_index}", f"opción {menu_index}"}:
            return option
        padded = f" {normalized} "
        for alias in aliases:
            if not alias or alias.isdigit():
                continue
            if normalized == alias or f" {alias} " in padded:
                return option
    return None


def _canonical_document_label(item: dict[str, Any] | None) -> str | None:
    if not isinstance(item, dict):
        return None
    key = _normalize(item.get("key"))
    label = str(item.get("label") or item.get("key") or "").strip()
    label_norm = _normalize(label)
    if key in {"ine_frente", "ine_atras"} or (
        "ine" in label_norm and ("frente" in label_norm or "atras" in label_norm)
    ):
        return "INE por ambos lados"
    return label or None


def _document_key(item: dict[str, Any] | None) -> str | None:
    if not isinstance(item, dict):
        return None
    key = _normalize(item.get("key") or item.get("document_key") or item.get("label"))
    return key or None


def _specific_document_prompt(item: dict[str, Any] | None) -> str | None:
    key = _document_key(item)
    if key == "ine_frente":
        return "el frente de tu INE"
    if key == "ine_atras":
        return "la parte de atras"
    if key == "comprobante_domicilio":
        return "tu comprobante de domicilio"
    label = str((item or {}).get("label") or (item or {}).get("key") or "").strip()
    return f"tu {label}" if label else None


def _current_response_source(*, composer_provider: str | None, composer_fallback_used: bool) -> str:
    provider = _normalize(composer_provider)
    if composer_fallback_used:
        return "fallback_composer"
    if "scripted" in provider:
        return "scripted_composer"
    return "current_runner"


def _requested_field_from_text(message: str) -> str | None:
    normalized = _normalize(message)
    checks = {
        "MOTO": ("modelo", "moto te interesa", "que moto", "cual moto"),
        "CREDITO": ("como recibes tus ingresos", "como te pagan", "ingresos"),
        "ENGANCHE": ("enganche", "anticipo", "plan quieres"),
        "ANTIGUEDAD_LABORAL": ("antiguedad", "empleo actual", "cuanto tiempo"),
    }
    for field, patterns in checks.items():
        if any(pattern in normalized for pattern in patterns):
            return field
    return None


def _is_documents_request(user_message: str, has_quote: bool) -> bool:
    normalized = _normalize(user_message)
    if not has_quote:
        return False
    return any(pattern in normalized for pattern in _DOC_PATTERNS)


def _is_requirements_request(user_message: str, has_quote: bool) -> bool:
    normalized = _normalize(user_message)
    if not has_quote:
        return False
    return any(pattern in normalized for pattern in _REQUIREMENTS_PATTERNS)


def _is_send_documents_request(user_message: str, has_quote: bool) -> bool:
    normalized = _normalize(user_message)
    if not has_quote:
        return False
    return any(pattern in normalized for pattern in _SEND_DOCUMENTS_PATTERNS)


def _is_post_quote_progress_request(user_message: str, has_quote: bool) -> bool:
    normalized = _normalize(user_message)
    if not has_quote:
        return False
    return any(pattern == normalized or pattern in normalized for pattern in _POST_QUOTE_PROGRESS_PATTERNS)


def _is_repeat_quote_complaint(user_message: str, has_quote: bool) -> bool:
    normalized = _normalize(user_message)
    if not has_quote:
        return False
    return any(pattern in normalized for pattern in _POST_QUOTE_REPEAT_PATTERNS)


def _is_explicit_quote_refresh_request(user_message: str, has_quote: bool) -> bool:
    normalized = _normalize(user_message)
    if not has_quote:
        return False
    return any(pattern in normalized for pattern in _QUOTE_REFRESH_PATTERNS)


def _is_soft_close(user_message: str, has_quote: bool) -> bool:
    normalized = _normalize(user_message)
    if not has_quote:
        return False
    return any(pattern == normalized or pattern in normalized for pattern in _SOFT_CLOSE_PATTERNS)


def _has_pending_documents_context(input: AdvisorBrainInput) -> bool:
    for payload in (input.documents_state, input.requirements_context):
        if not isinstance(payload, dict):
            continue
        if payload.get("missing") or payload.get("required") or payload.get("selection_key"):
            return True
    return False


def _is_runner_documents_response(action: str, text: str) -> bool:
    normalized = _normalize(f"{action} {text}")
    return any(marker in normalized for marker in _DOCUMENT_TEXT_MARKERS) or "classify_document" in normalized


def _is_runner_clarification_response(action: str, text: str) -> bool:
    normalized = _normalize(f"{action} {text}")
    return "clarif" in normalized or any(marker in normalized for marker in _CLARIFICATION_MARKERS)


def _is_runner_quote_repeat(text: str) -> bool:
    return _looks_like_quote_text(text)


def _field_present_or_inferred(field_name: str, context: AdvisorBrainInput) -> bool:
    value = context.contact_fields.get(field_name)
    if value not in (None, "", [], {}):
        return True
    if field_name == "ANTIGUEDAD_LABORAL":
        return bool(context.business_rules.get("history_memory_hints"))
    if field_name.startswith("DOC:"):
        document_key = field_name.removeprefix("DOC:")
        for item in list(context.documents_state.get("received") or []):
            if not isinstance(item, dict):
                continue
            if document_key in {_normalize(item.get("key")), _normalize(item.get("label"))}:
                return True
    return False


def _seniority_known(context: AdvisorBrainInput) -> bool:
    return any(_field_present_or_inferred(field, context) for field in _SENIORITY_FIELD_KEYS) or _field_present_or_inferred(
        "ANTIGUEDAD_LABORAL",
        context,
    ) or bool(context.seniority_evidence)


def _credit_value(context: AdvisorBrainInput) -> str:
    return str(
        context.contact_fields.get("CREDITO")
        or context.documents_state.get("selection_key")
        or context.requirements_context.get("selection_key")
        or ""
    ).strip()


def _credit_requires_seniority(context: AdvisorBrainInput) -> bool:
    credit_norm = _normalize(_credit_value(context))
    if not credit_norm:
        return True
    return not any(marker in credit_norm for marker in ("pension", "jubil", "retirad"))


def _quote_context_ready(context: AdvisorBrainInput) -> bool:
    if not context.contact_fields.get("MOTO"):
        return False
    if not context.contact_fields.get("CREDITO"):
        return False
    if not context.contact_fields.get("ENGANCHE"):
        return False
    if _credit_requires_seniority(context) and not _seniority_known(context):
        return False
    return True


def _brain_requests_seniority(brain_output: AdvisorBrainOutput | None) -> bool:
    if brain_output is None:
        return False
    if "ANTIGUEDAD_LABORAL" in set(brain_output.missing_required_facts):
        return True
    return any(marker in _normalize(brain_output.next_human_step) for marker in _SENIORITY_PROMPT_MARKERS)


def compare_advisor_brain_with_runner(
    *,
    brain_output: AdvisorBrainOutput | None,
    current_runner_result: dict[str, Any],
    hydrated_context: AdvisorBrainInput,
) -> dict[str, Any]:
    runner_text = str(current_runner_result.get("response_text") or "")
    runner_action = str(current_runner_result.get("runtime_action") or current_runner_result.get("selected_action") or "")
    selected_action = str(current_runner_result.get("selected_action") or "")
    runner_combined = f"{runner_action} {selected_action} {runner_text}"
    requested_field = _requested_field_from_text(runner_text) or _requested_field_from_text(runner_action)
    repeated_question = bool(
        requested_field
        and _field_present_or_inferred(requested_field, hydrated_context)
        and (brain_output is None or requested_field not in set(brain_output.missing_required_facts))
    )
    has_quote = bool(hydrated_context.active_quote or hydrated_context.last_quote_signature)
    documents_request = _is_documents_request(hydrated_context.user_message, has_quote)
    soft_close_request = _is_soft_close(hydrated_context.user_message, has_quote)
    runner_is_documents = _is_runner_documents_response(runner_action, runner_text)
    runner_is_clarification = _is_runner_clarification_response(runner_action, runner_text)
    unnecessary_quote_repeat = has_quote and _is_runner_quote_repeat(runner_text)
    wrong_post_quote_documents = documents_request and not runner_is_documents
    quote_instead_of_documents = documents_request and unnecessary_quote_repeat
    clarification_instead_of_documents = documents_request and runner_is_clarification
    runner_asks_seniority = any(marker in _normalize(runner_combined) for marker in _SENIORITY_PROMPT_MARKERS)
    seniority_known = _seniority_known(hydrated_context)
    missed_existing_seniority = seniority_known and (
        runner_asks_seniority or _brain_requests_seniority(brain_output)
    )
    post_quote_soft_close = bool(
        soft_close_request
        and brain_output is not None
        and "soft_close" in _normalize(brain_output.next_human_step)
    )
    brain_would_handoff = bool(
        brain_output is not None
        and brain_output.handoff_required
        and not bool(current_runner_result.get("handoff_required"))
    )
    state_ignored = bool(
        repeated_question
        or wrong_post_quote_documents
        or missed_existing_seniority
        or (documents_request and has_quote and not hydrated_context.documents_state and not hydrated_context.requirements_context)
    )
    disagreed = bool(
        brain_output is not None
        and (
            repeated_question
            or state_ignored
            or wrong_post_quote_documents
            or quote_instead_of_documents
            or clarification_instead_of_documents
            or missed_existing_seniority
            or unnecessary_quote_repeat
            or brain_would_handoff
            or (
                soft_close_request
                and "soft_close" in _normalize(brain_output.next_human_step)
                and "soft_close" not in _normalize(runner_combined)
            )
            or _normalize(brain_output.next_human_step) not in _normalize(runner_combined)
        )
    )
    return {
        "advisor_brain_disagreed_with_runner": disagreed,
        "advisor_brain_detected_repeated_question": repeated_question,
        "advisor_brain_detected_state_ignored": state_ignored,
        "advisor_brain_wrong_post_quote_documents": wrong_post_quote_documents,
        "advisor_brain_quote_instead_of_documents": quote_instead_of_documents,
        "advisor_brain_clarification_instead_of_documents": clarification_instead_of_documents,
        "advisor_brain_missed_existing_seniority": missed_existing_seniority,
        "advisor_brain_unnecessary_quote_repeat": unnecessary_quote_repeat,
        "advisor_brain_would_handoff": brain_would_handoff,
        "advisor_brain_post_quote_soft_close": post_quote_soft_close,
    }


def advisor_brain_feature_config(tenant_config: dict[str, Any]) -> dict[str, Any]:
    raw = tenant_config.get("advisor_brain")
    if not isinstance(raw, dict):
        return {
            "enabled": False,
            "mode": AdvisorBrainMode.SHADOW.value,
            "canary": False,
            "allowed_tenant_ids": [],
            "allowed_contact_ids": [],
            "allowed_phone_numbers": [],
        }
    enabled = bool(raw.get("enabled"))
    mode = str(raw.get("mode") or AdvisorBrainMode.SHADOW.value).strip().lower()
    if mode not in {item.value for item in AdvisorBrainMode}:
        mode = AdvisorBrainMode.SHADOW.value
    return {
        "enabled": enabled,
        "mode": mode,
        "canary": bool(raw.get("canary")),
        "allowed_tenant_ids": [str(item).strip() for item in list(raw.get("allowed_tenant_ids") or []) if str(item).strip()],
        "allowed_contact_ids": [str(item).strip() for item in list(raw.get("allowed_contact_ids") or []) if str(item).strip()],
        "allowed_phone_numbers": [str(item).strip() for item in list(raw.get("allowed_phone_numbers") or []) if str(item).strip()],
    }


def _normalize_phone(value: str | None) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    if str(value or "").strip().startswith("+"):
        return f"+{digits}"
    return digits


def advisor_brain_canary_allowed(
    *,
    feature_config: dict[str, Any],
    tenant_id: UUID | str,
    customer_id: UUID | str | None,
    phone_e164: str | None,
    customer_attrs: dict[str, Any] | None,
    customer_tags: list[Any] | None,
) -> tuple[bool, str]:
    mode = str(feature_config.get("mode") or AdvisorBrainMode.SHADOW.value).strip().lower()
    if mode != AdvisorBrainMode.PRIMARY.value:
        return False, "primary_mode_disabled"
    if not bool(feature_config.get("canary")):
        return False, "primary_canary_disabled"
    allowed_tenant_ids = {str(item).strip() for item in list(feature_config.get("allowed_tenant_ids") or []) if str(item).strip()}
    allowed_contact_ids = {str(item).strip() for item in list(feature_config.get("allowed_contact_ids") or []) if str(item).strip()}
    allowed_phone_numbers = {
        _normalize_phone(str(item))
        for item in list(feature_config.get("allowed_phone_numbers") or [])
        if _normalize_phone(str(item))
    }
    tenant_id_str = str(tenant_id)
    customer_id_str = str(customer_id) if customer_id is not None else ""
    phone_norm = _normalize_phone(phone_e164)
    attrs = dict(customer_attrs or {})
    tags = {_normalize(str(item)) for item in list(customer_tags or []) if str(item).strip()}

    if allowed_tenant_ids and tenant_id_str not in allowed_tenant_ids:
        return False, "tenant_not_allowlisted"

    test_flag_markers = {"test_client", "no_real_customer"}
    attr_markers = {_normalize(key) for key, value in attrs.items() if bool(value)}
    if any(marker in attr_markers for marker in test_flag_markers):
        return True, "customer_attr_test_flag"
    if tags.intersection(test_flag_markers):
        return True, "customer_tag_test_flag"
    if customer_id_str and customer_id_str in allowed_contact_ids:
        return True, "contact_id_allowlisted"
    if phone_norm and phone_norm in allowed_phone_numbers:
        return True, "phone_allowlisted"
    if tenant_id_str in allowed_tenant_ids and not (allowed_contact_ids or allowed_phone_numbers):
        return False, "tenant_only_allowlist_requires_test_marker"
    return False, "customer_not_allowlisted"


def _brain_schema() -> dict[str, Any]:
    return {
        "name": "advisor_brain_output",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "customer_understanding": {"type": "string"},
                "conversation_memory_used": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "detected_intent": {"type": "string"},
                "known_facts": {"type": "object", "additionalProperties": True},
                "new_facts_to_write": {"type": "object", "additionalProperties": True},
                "corrected_facts": {"type": "object", "additionalProperties": True},
                "missing_required_facts": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "next_human_step": {"type": "string"},
                "tool_requests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool_name": {
                                "type": "string",
                                "enum": [
                                    "resolve_catalog_model",
                                    "resolve_credit_plan",
                                    "compute_quote",
                                    "lookup_requirements",
                                    "get_missing_documents",
                                    "classify_attachment",
                                    "request_handoff",
                                ],
                            },
                            "args": {"type": "object", "additionalProperties": True},
                            "reason": {"type": "string"},
                        },
                        "required": ["tool_name", "args", "reason"],
                        "additionalProperties": False,
                    },
                },
                "forbidden_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "natural_response": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "handoff_required": {"type": "boolean"},
                "handoff_reason": {"type": ["string", "null"]},
                "state_write_plan": {
                    "type": "object",
                    "properties": {
                        "new_facts_to_write": {"type": "object", "additionalProperties": True},
                        "corrected_facts": {"type": "object", "additionalProperties": True},
                        "facts_requiring_confirmation": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "facts_to_leave_unchanged": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "new_facts_to_write",
                        "corrected_facts",
                        "facts_requiring_confirmation",
                        "facts_to_leave_unchanged",
                    ],
                    "additionalProperties": False,
                },
                "plan": {
                    "type": ["object", "null"],
                    "properties": {
                        "understanding": {
                            "type": "object",
                            "properties": {
                                "customer_message_summary": {"type": "string"},
                                "detected_intents": {"type": "array", "items": {"type": "string"}},
                                "entities": {"type": "object", "additionalProperties": True},
                                "context_resolution": {"type": "object", "additionalProperties": True},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "required": [
                                "customer_message_summary",
                                "detected_intents",
                                "entities",
                                "context_resolution",
                                "confidence",
                            ],
                            "additionalProperties": False,
                        },
                        "commercial_goal": {
                            "type": "object",
                            "properties": {
                                "current_goal": {"type": "string"},
                                "next_required_step": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": ["current_goal", "next_required_step", "reason"],
                            "additionalProperties": False,
                        },
                        "tool_plan": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "tool": {"type": "string"},
                                    "input": {"type": "object", "additionalProperties": True},
                                    "required": {"type": "boolean"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["tool", "input", "required", "reason"],
                                "additionalProperties": False,
                            },
                        },
                        "proposed_state_updates": {"type": "object", "additionalProperties": True},
                        "proposed_pipeline_update": {"type": ["string", "null"]},
                        "proposed_final_action": {"type": ["string", "null"]},
                        "proposed_final_action_payload": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "customer_response_goal": {"type": "string"},
                        "safety_notes": {"type": "array", "items": {"type": "string"}},
                        "needs_human_handoff": {"type": "boolean"},
                    },
                    "required": [
                        "understanding",
                        "commercial_goal",
                        "tool_plan",
                        "proposed_state_updates",
                        "proposed_pipeline_update",
                        "proposed_final_action",
                        "proposed_final_action_payload",
                        "customer_response_goal",
                        "safety_notes",
                        "needs_human_handoff",
                    ],
                    "additionalProperties": False,
                },
                "trace_reasoning_summary": {"type": "string"},
            },
            "required": [
                "customer_understanding",
                "conversation_memory_used",
                "detected_intent",
                "known_facts",
                "new_facts_to_write",
                "corrected_facts",
                "missing_required_facts",
                "next_human_step",
                "tool_requests",
                "forbidden_actions",
                "natural_response",
                "confidence",
                "handoff_required",
                "handoff_reason",
                "state_write_plan",
                "trace_reasoning_summary",
            ],
            "additionalProperties": False,
        },
    }


class AdvisorBrain:
    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        timeout_s: float = 8.0,
        retry_delays_ms: tuple[int, ...] = (500, 2000),
        use_local_fallback: bool = True,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self._retry_delays = (0, *retry_delays_ms)
        self._use_local_fallback = use_local_fallback
        self._client = (
            AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s) if api_key else None
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "AdvisorBrain":
        current = settings or get_settings()
        return cls(
            api_key=current.openai_api_key,
            model=current.composer_model,
            timeout_s=current.composer_timeout_s,
            retry_delays_ms=tuple(current.composer_retry_delays_ms),
        )

    @property
    def llm_configured(self) -> bool:
        return self._client is not None

    @property
    def model_name(self) -> str:
        return self._model

    async def run(
        self,
        *,
        input: AdvisorBrainInput,
        mode: AdvisorBrainMode,
        final_response_source: str,
    ) -> AdvisorBrainResult:
        llm_error: str | None = None
        validation_error: str | None = None
        fallback_used = False
        output: AdvisorBrainOutput | None = None
        if self._client is not None:
            try:
                raw_text = await self._invoke_llm_content(input)
            except Exception as exc:
                llm_error = self._summarize_exception(exc)
            else:
                try:
                    output = self._parse_llm_output(raw_text)
                except Exception as exc:
                    validation_error = self._summarize_exception(exc)
        else:
            llm_error = "advisor_brain_llm_not_configured"
        if output is None and validation_error is None and self._client is not None and llm_error is None:
            validation_error = "advisor_brain_output_missing"
        if output is None and self._use_local_fallback:
            fallback_used = True
            output = self._local_shadow_fallback(input)
        if output is not None:
            try:
                output = self._normalize_output(output, input=input)
            except Exception as exc:
                validation_error = self._summarize_exception(exc)
                if self._use_local_fallback and not fallback_used:
                    fallback_used = True
                    output = self._local_shadow_fallback(input)
                else:
                    output = None
        guardrail_blocked, guardrail_reason = self._guardrail_check(output, input=input)
        return AdvisorBrainResult(
            output=output,
            llm_error=llm_error,
            validation_error=validation_error,
            guardrail_blocked=guardrail_blocked,
            guardrail_reason=guardrail_reason,
            fallback_used=fallback_used,
            final_response_source=(
                final_response_source
                if mode == AdvisorBrainMode.SHADOW
                else "advisor_brain"
            ),
        )

    async def _invoke_llm_content(self, input: AdvisorBrainInput) -> str:
        assert self._client is not None
        messages = build_advisor_brain_messages(input)
        last_exc: Exception | None = None
        for delay_ms in self._retry_delays:
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)
            try:
                return await self._request_llm(messages, response_format={
                    "type": "json_schema",
                    "json_schema": _brain_schema(),
                })
            except BadRequestError as exc:
                # Some OpenAI strict-mode validators reject open-ended objects.
                # Fall back to JSON object mode instead of disabling the LLM path.
                if "response_format" in str(exc).lower() or "json_schema" in str(exc).lower():
                    try:
                        return await self._request_llm(
                            messages,
                            response_format={"type": "json_object"},
                        )
                    except Exception as fallback_exc:  # pragma: no cover - exercised via upper layer
                        last_exc = fallback_exc
                        continue
                last_exc = exc
                break
            except _RETRIABLE as exc:
                last_exc = exc
                continue
            except _NON_RETRIABLE as exc:
                last_exc = exc
                break
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("advisor brain llm call failed")

    async def _request_llm(
        self,
        messages: list[dict[str, str]],
        *,
        response_format: dict[str, Any],
    ) -> str:
        assert self._client is not None
        response = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=self._model,
            messages=messages,
            response_format=response_format,
            temperature=0,
        )
        return str(response.choices[0].message.content or "").strip()

    def _parse_llm_output(self, raw_text: str) -> AdvisorBrainOutput:
        payload_text = self._extract_json_object(raw_text)
        payload = json.loads(payload_text)
        if isinstance(payload, dict):
            trace_summary = str(payload.get("trace_reasoning_summary") or "").strip()
            if not trace_summary:
                understanding = str(payload.get("customer_understanding") or "").strip()
                step = str(payload.get("next_human_step") or "follow_up").strip() or "follow_up"
                intent = str(payload.get("detected_intent") or "follow_up").strip() or "follow_up"
                if understanding:
                    payload["trace_reasoning_summary"] = (
                        f"{understanding[:140]}. Paso sugerido: {step}. Intent detectado: {intent}."
                    )[:280]
                else:
                    payload["trace_reasoning_summary"] = (
                        f"Paso sugerido: {step}. Intent detectado: {intent}."
                    )[:280]
        return AdvisorBrainOutput.model_validate(payload)

    def _extract_json_object(self, raw_text: str) -> str:
        text = str(raw_text or "").strip()
        if not text:
            raise ValueError("advisor_brain_empty_response")
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        if text.startswith("{") and text.endswith("}"):
            return text
        start = text.find("{")
        if start == -1:
            raise ValueError("advisor_brain_json_not_found")
        decoder = json.JSONDecoder()
        candidate = text[start:]
        payload, offset = decoder.raw_decode(candidate)
        if not isinstance(payload, dict):
            raise ValueError("advisor_brain_json_root_not_object")
        return candidate[:offset]

    def _summarize_exception(self, exc: Exception) -> str:
        detail = str(exc).strip().replace("\n", " ")
        detail = re.sub(r"\s+", " ", detail)
        if detail:
            return f"{type(exc).__name__}: {detail[:200]}"
        return type(exc).__name__

    def _normalize_output(
        self,
        output: AdvisorBrainOutput,
        *,
        input: AdvisorBrainInput,
    ) -> AdvisorBrainOutput:
        has_quote = bool(input.active_quote or input.last_quote_signature)
        pending_documents_context = _has_pending_documents_context(input)
        soft_close_request = _is_soft_close(input.user_message, has_quote)
        requirements_request = _is_requirements_request(input.user_message, has_quote)
        send_documents_request = _is_send_documents_request(input.user_message, has_quote)
        post_quote_progress_request = _is_post_quote_progress_request(input.user_message, has_quote)
        repeat_quote_complaint = _is_repeat_quote_complaint(input.user_message, has_quote)
        explicit_quote_refresh_request = _is_explicit_quote_refresh_request(input.user_message, has_quote)
        document_received_detected = self._document_received_detected(input)
        seniority_known = _seniority_known(input)
        step = _normalize(output.next_human_step)
        intent = _normalize(output.detected_intent)
        if "handoff" in step or "humano" in step or output.handoff_required:
            next_step = "handoff"
        elif (
            not pending_documents_context
            and (
                soft_close_request
                or "soft" in step
                or step in {"close", "cierre", "soft close"}
                or "soft_close" in intent
            )
        ):
            next_step = "soft_close"
        elif (
            send_documents_request
            or "ask_first_missing_document" in step
            or "first_missing_document" in step
            or "primer documento" in step
            or "send_documents" in intent
        ):
            next_step = "ask_first_missing_document"
        elif (
            requirements_request
            or step in {"documents", "documentos", "requirements", "requirement"}
            or "document" in step
            or "requisito" in step
            or "ine" in step
            or "requirements" in intent
        ):
            next_step = "explain_required_documents"
        elif "cotiz" in step or "quote" in step:
            next_step = "quote"
        elif "resolve_model" in step or "modelo" in step:
            next_step = "resolve_model"
        elif "credit" in step or "ingresos" in step:
            next_step = "resolve_credit_plan"
        elif any(marker in step for marker in _SENIORITY_PROMPT_MARKERS):
            next_step = "ask_seniority"
        else:
            next_step = output.next_human_step.strip() or "follow_up"
        detected_intent = str(output.detected_intent or "").strip()
        natural_response = str(output.natural_response or "").strip()
        missing_required_facts = [
            str(item).strip()
            for item in output.missing_required_facts
            if str(item).strip()
        ]
        conversation_memory_used = [
            str(item).strip()
            for item in output.conversation_memory_used
            if str(item).strip()
        ]
        known_facts = dict(output.known_facts or input.contact_fields)
        tool_requests: list[dict[str, Any] | AdvisorBrainToolRequest] = list(output.tool_requests or [])

        if input.seniority_evidence:
            if "ANTIGUEDAD_LABORAL" not in known_facts and not any(
                key in known_facts for key in ("FILTRO", "CUMPLE_ANTIGUEDAD")
            ):
                known_facts["ANTIGUEDAD_LABORAL"] = input.seniority_evidence
            memory_marker = f"ANTIGUEDAD_HISTORIAL={input.seniority_evidence}"
            if memory_marker not in conversation_memory_used:
                conversation_memory_used.append(memory_marker)
        if seniority_known:
            missing_required_facts = [
                item
                for item in missing_required_facts
                if _normalize(item) not in {"antiguedad_laboral", "antiguedad"}
            ]
        contact_credit = input.contact_fields.get("CREDITO")
        contact_model = input.contact_fields.get("MOTO")
        contact_down_payment = input.contact_fields.get("ENGANCHE")
        credit_requires_seniority = _credit_requires_seniority(input)
        current_seniority_evidence = _extract_seniority_evidence_from_text(input.user_message)
        current_seniority_months = _extract_seniority_months(current_seniority_evidence)
        selected_credit_plan = _credit_plan_choice_from_message(input)
        sensitive_request = any(pattern in _normalize(input.user_message) for pattern in _SENSITIVE_PATTERNS)
        quote_ready = bool(
            contact_credit
            and contact_model
            and contact_down_payment
            and (
                not credit_requires_seniority
                or seniority_known
                or bool(current_seniority_evidence)
            )
        )
        handoff_required = bool(output.handoff_required)
        handoff_reason = output.handoff_reason

        if sensitive_request:
            detected_intent = "handoff"
            next_step = "handoff"
            natural_response = "Te apoyo, pero ese tema si lo tiene que revisar un asesor humano para no darte mal seguimiento."
            tool_requests = [
                {
                    "tool_name": "request_handoff",
                    "args": {"reason": "sensitive_payment_or_human_request"},
                    "reason": "Hay riesgo operativo o pago sensible.",
                }
            ]
            handoff_required = True
            handoff_reason = "sensitive_payment_or_human_request"
        elif document_received_detected:
            detected_intent, natural_response, tool_requests = self._document_received_response(input)
            next_step = "ask_first_missing_document"
        elif explicit_quote_refresh_request and quote_ready:
            detected_intent = "quote_request"
            next_step = "quote"
            natural_response = "Tienes razon, primero te paso la cotizacion correcta."
            tool_requests = [
                {
                    "tool_name": "compute_quote",
                    "args": {
                        "model": contact_model,
                        "down_payment": contact_down_payment,
                    },
                    "reason": "El cliente pidio precio, enganche, pago o cotizacion y ya existe contexto suficiente.",
                }
            ]
        elif repeat_quote_complaint and has_quote:
            detected_intent = "quote_already_shared"
            next_step = "ask_first_missing_document"
            first_missing = self._first_missing_document_label(input) or "INE por ambos lados"
            natural_response = (
                "Tienes razon, ya te la habia pasado. "
                f"Para avanzar, primero mandame tu {first_missing}, completa y bien legible."
            )
            tool_requests = [
                {
                    "tool_name": "get_missing_documents",
                    "args": {},
                    "reason": "Retomar el siguiente documento faltante sin repetir la cotizacion.",
                }
            ]
        elif (post_quote_progress_request or send_documents_request) and has_quote:
            detected_intent = "send_documents_request"
            next_step = "ask_first_missing_document"
            _detected_intent, natural_response, tool_requests = self._documents_response(input)
        elif soft_close_request and has_quote and not pending_documents_context:
            detected_intent = "soft_close"
            next_step = "soft_close"
            tool_requests = []
            natural_response = "Va, revisalo con calma. Si quieres avanzar, te digo que documentos ocupamos."
        elif requirements_request and has_quote:
            detected_intent = "requirements_request"
            next_step = "explain_required_documents"
            _detected_intent, natural_response, tool_requests = self._documents_response(input)
        elif current_seniority_evidence and current_seniority_months is not None and current_seniority_months < 6:
            detected_intent = "handoff"
            next_step = "handoff"
            natural_response = (
                "Gracias. Para este tramite ocupamos minimo 6 meses en tu empleo actual. "
                "Te paso con un asesor para revisar si hay otra opcion."
            )
            tool_requests = [
                {
                    "tool_name": "request_handoff",
                    "args": {"reason": "insufficient_seniority"},
                    "reason": "La antiguedad reportada no cumple el minimo comercial.",
                }
            ]
            handoff_required = True
            handoff_reason = "insufficient_seniority"
            known_facts.update(_seniority_updates(current_seniority_evidence, qualifies=False))
        else:
            if current_seniority_evidence and not seniority_known:
                known_facts.update(_seniority_updates(current_seniority_evidence, qualifies=True))
                seniority_known = True
                memory_marker = f"ANTIGUEDAD_ACTUAL={current_seniority_evidence}"
                if memory_marker not in conversation_memory_used:
                    conversation_memory_used.append(memory_marker)
                missing_required_facts = [
                    item
                    for item in missing_required_facts
                    if _normalize(item) not in {"antiguedad_laboral", "antiguedad"}
                ]

            if selected_credit_plan and (
                not contact_credit or str(contact_credit).strip() != str(selected_credit_plan.get("selection_key") or "").strip()
            ):
                contact_credit = str(selected_credit_plan.get("selection_key") or "").strip() or contact_credit
                contact_down_payment = (
                    str(selected_credit_plan.get("plan") or "").strip() or contact_down_payment
                )
                if contact_credit:
                    known_facts["CREDITO"] = contact_credit
                if contact_down_payment:
                    known_facts["ENGANCHE"] = contact_down_payment
                missing_required_facts = [
                    item
                    for item in missing_required_facts
                    if _normalize(item) not in {"credito", "enganche"}
                ]
            contact_credit, contact_down_payment, consistency_errors = _coherent_credit_plan(
                contact_credit,
                contact_down_payment,
            )
            if contact_credit:
                known_facts["CREDITO"] = contact_credit
            if contact_down_payment:
                known_facts["ENGANCHE"] = contact_down_payment
            if consistency_errors:
                for error in consistency_errors:
                    marker = f"CONSISTENCY:{error['reason']}:{error['selection_key']}"
                    if marker not in conversation_memory_used:
                        conversation_memory_used.append(marker)

            quote_ready = bool(
                contact_model
                and contact_credit
                and contact_down_payment
                and (not credit_requires_seniority or seniority_known)
            )

            if credit_requires_seniority and not seniority_known:
                detected_intent = "collect_seniority"
                next_step = "ask_seniority"
                natural_response = self._seniority_response(input)
                if _is_catalog_request(input.user_message):
                    catalog_url = _catalog_url(input)
                    if catalog_url:
                        natural_response = (
                            "Claro, aqui puedes ver el catalogo completo:\n\n"
                            f"Catalogo: {catalog_url}\n\n"
                            f"{self._seniority_response(input)}"
                        )
                tool_requests = []
                if "ANTIGUEDAD_LABORAL" not in missing_required_facts:
                    missing_required_facts.append("ANTIGUEDAD_LABORAL")
            elif not contact_credit:
                detected_intent = "resolve_credit_plan"
                next_step = "resolve_credit_plan"
                natural_response = _credit_plan_menu_response(input)
                tool_requests = []
                for field_name in ("CREDITO", "ENGANCHE"):
                    missing_required_facts = [
                        item for item in missing_required_facts if _normalize(item) != _normalize(field_name)
                    ]
                missing_required_facts.extend(
                    [field for field in ("CREDITO", "ENGANCHE") if field not in missing_required_facts]
                )
            elif not contact_model:
                if (
                    _looks_like_model_candidate(input.user_message)
                    and not _is_catalog_request(input.user_message)
                    and not selected_credit_plan
                ):
                    contact_model = str(input.user_message or "").strip()
                    known_facts["MOTO"] = contact_model
                    detected_intent = "quote_request"
                    next_step = "quote"
                    natural_response = "Va, te cotizo ese modelo con tu plan."
                    tool_requests = [
                        {
                            "tool_name": "compute_quote",
                            "args": {
                                "model": contact_model,
                                "down_payment": contact_down_payment,
                            },
                            "reason": "Ya existe antiguedad y plan; toca cotizar el modelo pedido.",
                        }
                    ]
                    missing_required_facts = [
                        item for item in missing_required_facts if _normalize(item) != "moto"
                    ]
                else:
                    detected_intent = "resolve_model"
                    next_step = "resolve_model"
                    natural_response = self._model_resolution_response(input)
                    tool_requests = []
                    if "MOTO" not in missing_required_facts:
                        missing_required_facts.append("MOTO")
            elif (
                quote_ready
                and (
                    not has_quote
                    or explicit_quote_refresh_request
                    or bool(current_seniority_evidence)
                    or bool(selected_credit_plan)
                )
            ):
                detected_intent = "quote_request"
                next_step = "quote"
                natural_response = "Ya tengo el contexto base. Te cotizo la opcion correcta en el siguiente paso."
                tool_requests = [
                    {
                        "tool_name": "compute_quote",
                        "args": {
                            "model": contact_model,
                            "down_payment": contact_down_payment,
                        },
                        "reason": "Todavia no hay cotizacion valida y ya existe contexto suficiente para calcularla.",
                    }
                ]
                missing_required_facts = [
                    item
                    for item in missing_required_facts
                    if _normalize(item) not in {"moto", "credito", "enganche", "antiguedad_laboral", "antiguedad"}
                ]
        proposed_new_facts = dict(output.new_facts_to_write)
        proposed_corrected_facts = dict(output.corrected_facts)
        if current_seniority_evidence and current_seniority_months is not None:
            proposed_new_facts.update(
                _seniority_updates(
                    current_seniority_evidence,
                    qualifies=current_seniority_months >= 6,
                )
            )
        if contact_credit:
            proposed_new_facts["CREDITO"] = contact_credit
        if contact_down_payment:
            proposed_new_facts["ENGANCHE"] = contact_down_payment
        if contact_model and _looks_like_model_candidate(input.user_message) and not input.contact_fields.get("MOTO"):
            proposed_new_facts.setdefault("MOTO", contact_model)

        state_write_plan = output.state_write_plan.model_copy(
            update={
                "new_facts_to_write": proposed_new_facts,
                "corrected_facts": proposed_corrected_facts,
            }
        )
        plan = _build_agent_brain_plan(
            input=input,
            customer_understanding=str(output.customer_understanding or "").strip(),
            detected_intent=detected_intent,
            next_step=next_step,
            known_facts=known_facts,
            state_write_plan=state_write_plan,
            tool_requests=[
                item
                if isinstance(item, AdvisorBrainToolRequest)
                else AdvisorBrainToolRequest.model_validate(item)
                for item in tool_requests
            ],
            confidence=float(output.confidence),
            natural_response=natural_response,
            trace_reasoning_summary=str(output.trace_reasoning_summary or "").strip()[:280],
            handoff_required=handoff_required,
            forbidden_actions=[
                str(item).strip()
                for item in list(output.forbidden_actions or [])
                if str(item).strip()
            ],
        )
        return output.model_copy(
            update={
                "next_human_step": next_step,
                "detected_intent": detected_intent,
                "natural_response": natural_response,
                "state_write_plan": state_write_plan,
                "missing_required_facts": missing_required_facts,
                "conversation_memory_used": conversation_memory_used,
                "known_facts": known_facts,
                "handoff_required": handoff_required,
                "handoff_reason": handoff_reason,
                "tool_requests": [
                    item
                    if isinstance(item, AdvisorBrainToolRequest)
                    else AdvisorBrainToolRequest.model_validate(item)
                    for item in tool_requests
                ],
                "trace_reasoning_summary": str(output.trace_reasoning_summary or "").strip()[:280],
                "plan": plan,
            }
        )

    def _guardrail_check(
        self,
        output: AdvisorBrainOutput | None,
        *,
        input: AdvisorBrainInput,
    ) -> tuple[bool, str | None]:
        if output is None:
            return False, None
        response_norm = _normalize(output.natural_response)
        proposed_facts = {
            **dict(output.known_facts or {}),
            **dict(output.new_facts_to_write or {}),
            **dict(output.corrected_facts or {}),
            **dict((output.state_write_plan.new_facts_to_write if output.state_write_plan else {}) or {}),
            **dict((output.state_write_plan.corrected_facts if output.state_write_plan else {}) or {}),
        }

        def _fact_value(field_name: str) -> Any:
            return (
                input.contact_fields.get(field_name)
                if input.contact_fields.get(field_name) not in (None, "", [], {})
                else proposed_facts.get(field_name)
            )

        if any(word in response_norm for word in ("aprobado", "autorizado", "garantizado")):
            return True, "approval_claim_blocked"
        if output.next_human_step in _QUOTE_STEP_KEYS:
            if _fact_value("MOTO") in (None, "", [], {}):
                return True, "quote_without_model"
            if _fact_value("CREDITO") in (None, "", [], {}):
                return True, "quote_without_credit"
            if _fact_value("ENGANCHE") in (None, "", [], {}):
                return True, "quote_without_down_payment"
            proposed_input = input.model_copy(
                update={
                    "contact_fields": {
                        **input.contact_fields,
                        **{k: v for k, v in proposed_facts.items() if v not in (None, "", [], {})},
                    }
                }
            )
            if _credit_requires_seniority(proposed_input) and not (
                _fact_value("FILTRO")
                or _fact_value("CUMPLE_ANTIGUEDAD")
                or _fact_value("ANTIGUEDAD_LABORAL")
                or input.business_rules.get("history_memory_hints")
            ):
                return True, "quote_without_seniority"
        if (
            output.next_human_step in _DOCUMENT_STEP_KEYS
            and not (input.active_quote or input.last_quote_signature)
            and _normalize(input.user_message) not in {_normalize(item) for item in _DOC_PATTERNS}
        ):
            return True, "documents_before_valid_quote"
        return False, None

    def _document_label(self, item: Any) -> str | None:
        if not isinstance(item, dict):
            return None
        return _canonical_document_label(item)

    def _first_missing_document_label(self, input: AdvisorBrainInput) -> str | None:
        for source in (input.documents_state, input.requirements_context):
            missing = list((source or {}).get("missing") or [])
            for item in missing:
                label = self._document_label(item)
                if label:
                    return label
        return None

    def _first_missing_document_item(self, input: AdvisorBrainInput) -> dict[str, Any] | None:
        for source in (input.documents_state, input.requirements_context):
            missing = list((source or {}).get("missing") or [])
            for item in missing:
                if isinstance(item, dict):
                    return item
        return None

    def _received_document_items(self, input: AdvisorBrainInput) -> list[dict[str, Any]]:
        seen: list[dict[str, Any]] = []
        for source in (input.documents_state, input.requirements_context):
            for key in ("received_this_turn", "received", "received_documents", "accepted_documents"):
                for item in list((source or {}).get(key) or []):
                    if isinstance(item, dict):
                        seen.append(item)
        return seen

    def _document_received_detected(self, input: AdvisorBrainInput) -> bool:
        has_quote = bool(input.active_quote or input.last_quote_signature)
        if not has_quote:
            return False
        if int(input.attachment_context.get("attachment_count") or 0) <= 0:
            return False
        return bool(self._received_document_items(input) or (input.documents_state or {}).get("missing"))

    def _document_received_response(
        self,
        input: AdvisorBrainInput,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        missing_item = self._first_missing_document_item(input)
        received_keys = {
            key
            for key in (_document_key(item) for item in self._received_document_items(input))
            if key
        }
        missing_key = _document_key(missing_item)
        if "ine_frente" in received_keys and missing_key == "ine_atras":
            response = "Listo, ya recibi el frente de tu INE. Ahora mandame la parte de atras, bien legible."
        elif {"ine_frente", "ine_atras"}.issubset(received_keys) and missing_key == "comprobante_domicilio":
            response = "Listo, ya recibi tu INE. Ahora mandame comprobante de domicilio."
        elif missing_item is not None:
            prompt = _specific_document_prompt(missing_item) or "tu siguiente documento"
            response = f"Listo, ya recibi tu documento. Ahora mandame {prompt}, bien legible."
        else:
            response = "Listo, ya recibi tu documento."
        return (
            "document_received",
            response,
            [
                {
                    "tool_name": "get_missing_documents",
                    "args": {},
                    "reason": "Confirmar el siguiente documento faltante despues del archivo recibido.",
                }
            ],
        )

    def _requirements_labels(self, input: AdvisorBrainInput) -> list[str]:
        labels: list[str] = []
        for item in list((input.requirements_context or {}).get("required") or []):
            label = self._document_label(item)
            if label and label not in labels:
                labels.append(label)
        return labels

    def _seniority_response(self, input: AdvisorBrainInput) -> str:
        if input.contact_fields.get("MOTO"):
            return (
                f"Va, para darte el mejor plan de la {input.contact_fields['MOTO']}, "
                "dime ¿cuanto tiempo llevas en tu empleo actual?"
            )
        return "Para darte el mejor plan, dime ¿cuanto tiempo llevas en tu empleo actual?"

    def _model_resolution_response(self, input: AdvisorBrainInput) -> str:
        catalog_url = _catalog_url(input)
        if _is_catalog_request(input.user_message):
            if catalog_url:
                return (
                    "Va, aqui puedes ver el catalogo completo para elegir modelo:\n\n"
                    f"Catalogo: {catalog_url}\n\n"
                    "Cuando lo tengas, dime que modelo te interesa para cotizarte."
                )
            return "Va, dime que modelo o categoria te interesa para cotizarte."
        if catalog_url:
            return (
                "Va, ya tengo tu plan. Ahora dime que modelo te interesa para cotizarte.\n\n"
                f"Catalogo: {catalog_url}"
            )
        return "Va, ya tengo tu plan. Ahora dime que modelo te interesa para cotizarte."

    def _documents_response(self, input: AdvisorBrainInput) -> tuple[str, str, list[dict[str, Any]]]:
        has_quote = bool(input.active_quote or input.last_quote_signature)
        if _is_post_quote_progress_request(input.user_message, has_quote) or _is_send_documents_request(
            input.user_message,
            has_quote,
        ):
            first_missing = self._first_missing_document_label(input)
            if first_missing:
                return (
                    "send_documents_request",
                    f"Va, para avanzar primero mandame tu {first_missing}, completa y bien legible.",
                    [
                        {
                            "tool_name": "get_missing_documents",
                            "args": {},
                            "reason": "Confirmar el primer documento faltante del plan actual.",
                        }
                    ],
                )
            return (
                "send_documents_request",
                "Va, para avanzar primero mandame tu INE por ambos lados, completa y bien legible.",
                [
                    {
                        "tool_name": "get_missing_documents",
                        "args": {},
                        "reason": "Confirmar el primer documento faltante del plan actual.",
                    }
                ],
            )
        if _is_requirements_request(input.user_message, has_quote):
            labels = self._requirements_labels(input)
            if labels:
                rendered = "; ".join(labels[:4])
                return (
                    "requirements_request",
                    f"Para tu plan ocupamos {rendered}. Si quieres avanzar, te voy pidiendo uno por uno.",
                    [
                        {
                            "tool_name": "lookup_requirements",
                            "args": {},
                            "reason": "Confirmar los requisitos exactos del plan actual.",
                        }
                    ],
                )
            return (
                "requirements_request",
                "Te digo los requisitos exactos de tu plan y de ahi seguimos con el primero.",
                [
                    {
                        "tool_name": "lookup_requirements",
                        "args": {},
                        "reason": "Confirmar los requisitos exactos del plan actual.",
                    }
                ],
            )
        return (
            "requirements_request",
            "Va, te digo los documentos del plan actual y de ahi seguimos con el primero que falte.",
            [
                {
                    "tool_name": "lookup_requirements",
                    "args": {},
                    "reason": "Confirmar requisitos del plan actual.",
                }
            ],
        )

    def _local_shadow_fallback(self, input: AdvisorBrainInput) -> AdvisorBrainOutput:
        user_norm = _normalize(input.user_message)
        known_facts = dict(input.contact_fields)
        missing = list(input.missing_contact_fields)
        handoff_required = any(pattern in user_norm for pattern in _SENSITIVE_PATTERNS)
        handoff_reason = "sensitive_payment_or_human_request" if handoff_required else None
        tool_requests: list[dict[str, Any]] = []
        forbidden_actions = [
            "no_inventar_precios",
            "no_prometer_aprobacion",
        ]
        next_step = "follow_up"
        response = "Te ayudo con eso. Dime el dato que falta para seguir."
        understanding = "Cliente quiere avanzar con su tramite de moto."
        detected_intent = "follow_up"
        memory_used: list[str] = []
        if input.contact_fields.get("MOTO"):
            memory_used.append(f"MOTO={input.contact_fields['MOTO']}")
        if input.contact_fields.get("CREDITO"):
            memory_used.append(f"CREDITO={input.contact_fields['CREDITO']}")
        if input.contact_fields.get("ENGANCHE"):
            memory_used.append(f"ENGANCHE={input.contact_fields['ENGANCHE']}")
        if input.business_rules.get("history_memory_hints"):
            seniority_hint = input.business_rules["history_memory_hints"].get("seniority_mentioned_in_history")
            if seniority_hint:
                memory_used.append(f"ANTIGUEDAD_HISTORIAL={seniority_hint}")
        if handoff_required:
            next_step = "handoff"
            response = "Te apoyo, pero ese tema si lo tiene que revisar un asesor humano para no darte mal seguimiento."
            understanding = "Cliente menciona pago sensible o pide humano."
            detected_intent = "handoff_sensitive"
            tool_requests.append(
                {
                    "tool_name": "request_handoff",
                    "args": {"reason": handoff_reason},
                    "reason": "Hay riesgo operativo o pago sensible.",
                }
            )
        elif self._document_received_detected(input):
            detected_intent, response, tool_requests = self._document_received_response(input)
            next_step = "ask_first_missing_document"
            understanding = "Cliente envio documento y toca pedir solo el siguiente faltante."
            missing = []
        elif _is_explicit_quote_refresh_request(input.user_message, bool(input.active_quote or input.last_quote_signature)):
            next_step = "quote"
            response = "Tienes razon, primero te paso la cotizacion correcta."
            understanding = "Cliente pide precio, enganche o pago y corresponde resumir la cotizacion completa."
            detected_intent = "quote_request"
            tool_requests.append(
                {
                    "tool_name": "compute_quote",
                    "args": {
                        "model": input.contact_fields.get("MOTO"),
                        "down_payment": input.contact_fields.get("ENGANCHE"),
                    },
                    "reason": "Responder la pregunta de precio con una cotizacion completa.",
                }
            )
            missing = []
        elif _is_repeat_quote_complaint(input.user_message, bool(input.active_quote or input.last_quote_signature)):
            next_step = "ask_first_missing_document"
            first_missing = self._first_missing_document_label(input) or "INE por ambos lados"
            response = (
                "Tienes razon, ya te la habia pasado. "
                f"Para avanzar, primero mandame tu {first_missing}, completa y bien legible."
            )
            understanding = "Cliente reclama repeticion de quote y se retoma el siguiente documento."
            detected_intent = "quote_already_shared"
            tool_requests.append(
                {
                    "tool_name": "get_missing_documents",
                    "args": {},
                    "reason": "Retomar el siguiente documento faltante sin repetir la cotizacion.",
                }
            )
            missing = []
        elif _is_soft_close(input.user_message, bool(input.active_quote or input.last_quote_signature)):
            next_step = "soft_close"
            response = "Va, revisalo con calma. Si quieres avanzar, te digo que documentos ocupamos."
            understanding = "Cliente ya tiene cotizacion y responde con cierre suave."
            detected_intent = "soft_close"
            missing = []
        elif _is_documents_request(input.user_message, bool(input.active_quote or input.last_quote_signature)):
            detected_intent, response, tool_requests = self._documents_response(input)
            next_step = (
                "ask_first_missing_document"
                if detected_intent == "send_documents_request"
                else "explain_required_documents"
            )
            understanding = "Cliente ya tiene cotizacion y pregunta por requisitos o documentos."
            missing = []
        elif "ya te dije" in user_norm or "ya me dijiste" in user_norm:
            next_step = "acknowledge_and_continue"
            response = "Si, ya lo tengo presente. Solo avanzamos con lo que realmente falta."
            understanding = "Cliente muestra friccion por repeticion de preguntas."
            detected_intent = "friction_repeated_question"
        elif (
            _extract_seniority_months(input.user_message) is not None
            and int(_extract_seniority_months(input.user_message) or 0) < 6
        ):
            next_step = "handoff"
            response = (
                "Gracias. Para este tramite ocupamos minimo 6 meses en tu empleo actual. "
                "Te paso con un asesor para revisar si hay otra opcion."
            )
            understanding = "La antiguedad laboral reportada no cumple el minimo comercial."
            detected_intent = "handoff_insufficient_seniority"
            handoff_required = True
            handoff_reason = "insufficient_seniority"
            tool_requests.append(
                {
                    "tool_name": "request_handoff",
                    "args": {"reason": handoff_reason},
                    "reason": "La antiguedad reportada no cumple el minimo comercial.",
                }
            )
        elif (
            not input.contact_fields.get("ANTIGUEDAD_LABORAL")
            and not input.contact_fields.get("FILTRO")
            and not input.contact_fields.get("CUMPLE_ANTIGUEDAD")
            and not input.business_rules.get("history_memory_hints")
        ):
            next_step = "ask_seniority"
            response = self._seniority_response(input)
            if _is_catalog_request(input.user_message):
                catalog_url = _catalog_url(input)
                if catalog_url:
                    response = (
                        "Claro, aqui puedes ver el catalogo completo:\n\n"
                        f"Catalogo: {catalog_url}\n\n"
                        f"{self._seniority_response(input)}"
                    )
            understanding = "Falta antiguedad laboral para decidir el siguiente paso comercial."
            detected_intent = "collect_seniority"
            missing = ["ANTIGUEDAD_LABORAL"]
        elif not input.contact_fields.get("CREDITO"):
            credit_choice = _credit_plan_choice_from_message(input)
            if credit_choice:
                selection_key, plan, _consistency_errors = _coherent_credit_plan(
                    str(credit_choice.get("selection_key") or "").strip(),
                    str(credit_choice.get("plan") or "").strip(),
                )
                if selection_key:
                    known_facts["CREDITO"] = selection_key
                if plan:
                    known_facts["ENGANCHE"] = plan
                next_step = "resolve_model"
                response = self._model_resolution_response(
                    input.model_copy(
                        update={
                            "contact_fields": {
                                **input.contact_fields,
                                "CREDITO": selection_key,
                                "ENGANCHE": plan,
                            }
                        }
                    )
                )
                understanding = "Cliente ya eligio plan y sigue seleccionar modelo."
                detected_intent = "resolve_credit_plan"
                missing = ["MOTO"]
            else:
                next_step = "resolve_credit_plan"
                response = _credit_plan_menu_response(input)
                understanding = "Falta resolver el tipo de credito o perfil de ingresos."
                detected_intent = "resolve_credit_plan"
                missing = ["CREDITO", "ENGANCHE"]
        elif not input.contact_fields.get("MOTO"):
            if _looks_like_model_candidate(input.user_message) and not _is_catalog_request(input.user_message):
                next_step = "quote"
                response = "Ya tengo el contexto base. Te cotizo la opcion correcta en el siguiente paso."
                understanding = "Cliente ya dio el modelo y toca cotizar."
                detected_intent = "quote_request"
                known_facts["MOTO"] = str(input.user_message or "").strip()
                tool_requests.append(
                    {
                        "tool_name": "compute_quote",
                        "args": {
                            "model": str(input.user_message or "").strip(),
                            "down_payment": input.contact_fields.get("ENGANCHE"),
                        },
                        "reason": "Ya existe antiguedad y plan; toca cotizar el modelo pedido.",
                    }
                )
                missing = []
            else:
                next_step = "resolve_model"
                response = self._model_resolution_response(input)
                understanding = "Ya hay contexto comercial, pero falta modelo."
                detected_intent = "collect_model"
                missing = ["MOTO"]
        elif "moto de la foto" in user_norm and int(input.attachment_context.get("attachment_count") or 0) == 0:
            next_step = "resolve_model"
            response = "Claro, mandame la foto o dime el modelo para ubicarla bien."
            understanding = "Cliente refiere una moto en imagen, pero no hay adjunto util."
            detected_intent = "resolve_model_from_photo_reference"
        elif not input.contact_fields.get("ENGANCHE"):
            next_step = "resolve_credit_plan"
            response = _credit_plan_menu_response(input)
            understanding = "Falta enganche para poder cotizar bien."
            detected_intent = "resolve_credit_plan"
            missing = ["ENGANCHE"]
        elif bool(input.active_quote or input.last_quote_signature) and not _is_explicit_quote_refresh_request(
            input.user_message,
            True,
        ):
            next_step = "ask_first_missing_document"
            first_missing = self._first_missing_document_label(input) or "INE por ambos lados"
            response = f"Va, para avanzar primero mandame tu {first_missing}, completa y bien legible."
            understanding = "Ya existe cotizacion valida; se retoma documentacion en vez de recotizar."
            detected_intent = "send_documents_request"
            tool_requests.append(
                {
                    "tool_name": "get_missing_documents",
                    "args": {},
                    "reason": "Retomar el siguiente documento faltante despues de la cotizacion.",
                }
            )
            missing = []
        else:
            next_step = "quote"
            response = "Ya tengo lo necesario para cotizarte. Te saco el numero exacto."
            understanding = "Ya existe suficiente contexto comercial para cotizar o avanzar."
            detected_intent = "quote_ready"
            tool_requests.append(
                {
                    "tool_name": "compute_quote",
                    "args": {
                        "model": input.contact_fields.get("MOTO"),
                        "credit": input.contact_fields.get("CREDITO"),
                        "down_payment": input.contact_fields.get("ENGANCHE"),
                    },
                    "reason": "Se necesita cotizacion exacta validada por tool.",
                }
            )
            missing = []
        return AdvisorBrainOutput(
            customer_understanding=understanding,
            conversation_memory_used=memory_used,
            detected_intent=detected_intent,
            known_facts=known_facts,
            new_facts_to_write={},
            corrected_facts={},
            missing_required_facts=missing,
            next_human_step=next_step,
            tool_requests=tool_requests,
            forbidden_actions=forbidden_actions,
            natural_response=response,
            confidence=0.72 if not handoff_required else 0.9,
            handoff_required=handoff_required,
            handoff_reason=handoff_reason,
            state_write_plan=AdvisorBrainStateWritePlan(
                new_facts_to_write={},
                corrected_facts={},
                facts_requiring_confirmation={},
                facts_to_leave_unchanged=list(known_facts.keys()),
            ),
            trace_reasoning_summary=(
                "Analisis shadow basado en memoria, quote activa, requisitos y riesgo operativo."
            ),
        )


def _credit_plan_choice_from_message(context: AdvisorBrainInput) -> dict[str, Any] | None:
    normalized = _normalize(context.user_message)
    if not normalized:
        return None
    for option in _credit_plan_options(context):
        menu_index = str(option.get("menu_index") or "").strip()
        aliases = {
            _normalize(str(alias))
            for alias in (option.get("aliases") or [])
            if _normalize(str(alias))
        }
        aliases.add(_normalize(str(option.get("selection_key") or "")))
        aliases.add(_normalize(str(option.get("selection_label") or "")))
        if menu_index and normalized in {menu_index, f"opcion {menu_index}", f"opcion {menu_index}"}:
            return {
                **option,
                "selection_source": "menu_index",
                "selected_raw": context.user_message,
            }
        padded = f" {normalized} "
        for alias in aliases:
            if not alias or alias.isdigit():
                continue
            if normalized == alias or f" {alias} " in padded:
                return {
                    **option,
                    "selection_source": "alias",
                    "selected_raw": context.user_message,
                }
    return None


__all__ = [
    "AdvisorBrain",
    "advisor_brain_feature_config",
    "build_advisor_brain_input",
    "compare_advisor_brain_with_runner",
    "summarize_advisor_brain_input",
    "_current_response_source",
]

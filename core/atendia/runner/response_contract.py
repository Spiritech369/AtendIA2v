"""Legacy response contract used by ConversationRunner fallback.

AgentRuntime v2 validates TurnOutput directly and should not call this contract
to rewrite or replace customer-visible final copy.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from atendia.runner.composer_protocol import ComposerOutput
from atendia.runner.document_language import (
    humanize_document_labels,
    join_humanized_documents,
)
from atendia.runner.response_frame import ResponseFrame, render_response_frame_fallback_message

_CATALOG_BROWSE_PREVIEW_LIMIT = 10
_STATE_GUARD_FIELD_QUESTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "MOTO": (
        "que modelo",
        "cual modelo",
        "modelo exacto",
        "modelo de moto",
        "moto te interesa",
        "modelo quieres",
        "moto quieres",
    ),
    "CREDITO": (
        "como recibes tus ingresos",
        "como te pagan",
        "dime como recibes tus ingresos",
        "metodo de ingresos",
        "forma de ingresos",
    ),
    "ENGANCHE": (
        "que enganche",
        "cuanto enganche",
        "enganche quieres",
        "porcentaje de enganche",
        "plan quieres",
    ),
    "FILTRO": (
        "cuanto tiempo",
        "cuantos meses",
        "cuantos anos",
        "antiguedad",
        "empleo actual",
        "tiempo llevas",
        "tienes trabajando",
    ),
    "ANTIGUEDAD_LABORAL": (
        "cuanto tiempo",
        "cuantos meses",
        "cuantos anos",
        "antiguedad",
        "empleo actual",
        "tiempo llevas",
        "tienes trabajando",
    ),
}


@dataclass(frozen=True)
class RenderedResponse:
    text: str
    mode: str
    reason: str


@dataclass(frozen=True)
class ResponseContractRequest:
    action: str
    action_payload: dict[str, Any]
    composer_output: ComposerOutput | None
    state: dict[str, Any]
    response_frame: ResponseFrame | None = None
    inbound_text: str = ""
    history: list[tuple[str, str]] | None = None
    brand_facts: dict[str, Any] | None = None
    advisor_decision: dict[str, Any] | None = None
    tool_payload: dict[str, Any] | None = None
    pending_to_resume: dict[str, Any] | None = None
    conversation_control: dict[str, Any] | None = None
    operational_intent: dict[str, Any] | None = None


@dataclass(frozen=True)
class ResponseContractResult:
    outbound_messages: list[str] | None
    final_composer_output: ComposerOutput | None
    contract_applied: bool
    contract_reason: str | None
    blocked_or_rewritten: bool
    trace_metadata: dict[str, Any] | None


def apply_response_contract(request: ResponseContractRequest) -> ResponseContractResult:
    event = _guard_composer_output(
        composer_output=request.composer_output,
        decision_action=request.action,
        action_payload=request.action_payload,
        response_frame=request.response_frame,
        extracted_data=request.state,
        advisor_decision=request.advisor_decision,
        inbound_text=request.inbound_text,
        history=request.history,
        brand_facts=request.brand_facts,
    )
    messages = (
        list(request.composer_output.messages)
        if request.composer_output is not None and request.composer_output.messages
        else None
    )
    return ResponseContractResult(
        outbound_messages=messages,
        final_composer_output=request.composer_output,
        contract_applied=event is not None,
        contract_reason=(
            str(event.get("overwrite_blocked_reason"))
            if isinstance(event, dict) and event.get("overwrite_blocked_reason")
            else None
        ),
        blocked_or_rewritten=event is not None,
        trace_metadata=event,
    )


def render_quote_response(
    *,
    action_payload: dict[str, Any],
    inbound_text: str,
    history: list[tuple[str, str]] | None = None,
) -> RenderedResponse:
    recent_history = history or []
    if action_payload.get("kind") == "quote_memory_recall":
        return RenderedResponse(
            text=_render_quote_memory_recall(action_payload),
            mode="summary",
            reason="quote_memory_recall_rendered_from_payload",
        )
    if _quote_payload_mode(action_payload) == "cash":
        return RenderedResponse(
            text=_render_cash_quote(action_payload),
            mode="cash",
            reason="cash_quote_rendered_from_payload",
        )
    if _prefer_followup_quote_summary(inbound_text):
        return RenderedResponse(
            text=_render_quote_followup_summary(action_payload),
            mode="summary",
            reason="quote_followup_summary_for_followup_reference",
        )
    if _should_render_quote_summary(
        action_payload=action_payload,
        inbound_text=inbound_text,
        history=recent_history,
    ):
        text = _render_quote_summary(action_payload)
        if _recent_exact_outbound(text=text, history=recent_history):
            text = _render_quote_followup_summary(action_payload)
        return RenderedResponse(
            text=_append_requirements_context_to_quote(
                text=text,
                action_payload=action_payload,
                inbound_text=inbound_text,
            ),
            mode="summary",
            reason="quote_summary_for_recent_quote_context",
        )
    if _history_contains_quote_signature(action_payload=action_payload, history=recent_history):
        return RenderedResponse(
            text=_append_requirements_context_to_quote(
                text=_render_quote_followup_summary(action_payload),
                action_payload=action_payload,
                inbound_text=inbound_text,
            ),
            mode="summary",
            reason="quote_followup_summary_for_matching_quote_signature",
        )
    full_text = _render_full_quote(action_payload)
    if _recent_exact_outbound(text=full_text, history=recent_history):
        return RenderedResponse(
            text=_append_requirements_context_to_quote(
                text=_render_quote_followup_summary(action_payload),
                action_payload=action_payload,
                inbound_text=inbound_text,
            ),
            mode="summary",
            reason="quote_followup_summary_for_duplicate_full_quote",
        )
    return RenderedResponse(
        text=_append_requirements_context_to_quote(
            text=full_text,
            action_payload=action_payload,
            inbound_text=inbound_text,
        ),
        mode="full",
        reason="full_quote_response",
    )


def is_valid_quote_summary(message: str) -> bool:
    normalized = _normalize(message)
    if "enganche" not in normalized or "quincenal" not in normalized:
        return False
    if "$" not in str(message or ""):
        return False
    return len(normalized.split()) <= 45


def _quote_payload_mode(action_payload: dict[str, Any]) -> str | None:
    mode = str(
        action_payload.get("active_purchase_mode")
        or action_payload.get("quote_mode")
        or ""
    ).strip().casefold()
    return mode or None


def _render_cash_quote(action_payload: dict[str, Any]) -> str:
    name = action_payload.get("name") or action_payload.get("sku") or "el modelo"
    cash_price = action_payload.get("cash_price_mxn") or action_payload.get("list_price_mxn")
    list_price = action_payload.get("list_price_mxn") or action_payload.get("cash_price_mxn")
    if str(cash_price or "") != str(list_price or ""):
        return (
            f"La {name} de contado queda en {_format_money(cash_price)}. "
            f"Precio de lista: {_format_money(list_price)}."
        )
    return f"La {name} de contado queda en {_format_money(cash_price)}."


def _message_text(messages: list[str] | None) -> str:
    return "\n".join(str(message or "") for message in (messages or []))


def _state_guard_normalize(value: Any) -> str:
    text_value = str(value or "").strip()
    decomposed = unicodedata.normalize("NFKD", text_value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.casefold()).strip()


def _state_guard_present(value: Any) -> bool:
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    return value not in (None, "", [], {})


def _state_guard_value(extracted_data: dict[str, Any], key: str) -> Any:
    value = extracted_data.get(key)
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _protected_question_field(
    *,
    messages: list[str] | None,
    extracted_data: dict[str, Any],
    require_existing: bool,
) -> str | None:
    normalized = _state_guard_normalize(_message_text(messages))
    for field, patterns in _STATE_GUARD_FIELD_QUESTION_PATTERNS.items():
        if require_existing and not _state_guard_present(_state_guard_value(extracted_data, field)):
            continue
        if any(pattern in normalized for pattern in patterns):
            return field
    return None


def _quote_payload_ok(action_payload: dict[str, Any]) -> bool:
    return isinstance(action_payload, dict) and action_payload.get("status") == "ok"


def _append_requirements_context_to_quote(
    *,
    text: str,
    action_payload: dict[str, Any],
    inbound_text: str,
) -> str:
    if not _requirements_question_in_text(inbound_text):
        return text
    requirements = action_payload.get("requirements")
    if not isinstance(requirements, dict):
        return text
    missing = requirements.get("missing") or requirements.get("required") or []
    labels = [
        str(item.get("label") or item.get("key")).strip()
        for item in missing
        if isinstance(item, dict) and str(item.get("label") or item.get("key") or "").strip()
    ]
    if not labels:
        return text
    return "\n\n".join(
        [
            text,
            "Para avanzar despues de la cotizacion necesitarias: " + ", ".join(labels) + ".",
        ]
    )


def _requirements_question_in_text(text: str) -> bool:
    normalized = _state_guard_normalize(text)
    return any(
        token in normalized
        for token in ("requisito", "requisitos", "documento", "documentos", "papel", "papeles")
    )


def _catalog_browse_payload_ok(action_payload: dict[str, Any]) -> bool:
    return (
        isinstance(action_payload, dict)
        and action_payload.get("status") == "ok"
        and action_payload.get("request_type") == "catalog_browse"
    )


def _quote_message_contains_quote(messages: list[str] | None) -> bool:
    normalized = _state_guard_normalize(_message_text(messages))
    return "$" in _message_text(messages) and (
        "enganche" in normalized
        or "quincenal" in normalized
        or "contado" in normalized
    )


def _render_guarded_catalog_browse_message(action_payload: dict[str, Any]) -> str:
    results = action_payload.get("results") if isinstance(action_payload, dict) else []
    results = results if isinstance(results, list) else []
    names = [
        str(item.get("name") or item.get("sku") or "").strip()
        for item in results
        if isinstance(item, dict) and str(item.get("name") or item.get("sku") or "").strip()
    ]
    total = action_payload.get("total_results")
    try:
        total_count = int(total)
    except (TypeError, ValueError):
        total_count = len(names)
    browse_intent = str(action_payload.get("browse_intent") or "catalog_overview")
    catalog_url = str(action_payload.get("catalog_url") or "").strip()
    query = str(action_payload.get("query") or "").strip()

    if browse_intent == "catalog_more":
        if query and total_count:
            intro = f"Si, tenemos mas opciones de {query}. Te paso estas:"
        else:
            intro = (
                f"No, tenemos {total_count} modelos activos."
                if total_count
                else "No, tenemos mas modelos."
            )
    elif browse_intent == "catalog_style":
        intro = (
            f"Si, tenemos estas opciones de {query}:"
            if query and total_count
            else "Si, te paso opciones del catalogo:"
        )
    elif browse_intent == "ad_reference":
        intro = (
            "Para ubicar esa moto necesito foto, link o nombre. "
            "Mientras, te paso opciones del catalogo:"
        )
    elif browse_intent == "full_catalog":
        intro = (
            f"Claro, tenemos {total_count} modelos activos en catalogo."
            if total_count
            else "Claro, te paso el catalogo."
        )
    else:
        intro = (
            f"Claro, estas son algunas motos del catalogo ({total_count} modelos activos):"
            if total_count
            else "Claro, estas son algunas motos del catalogo:"
        )

    lines = [intro]
    if names:
        lines.extend(f"- {name}" for name in names[:_CATALOG_BROWSE_PREVIEW_LIMIT])
    if catalog_url:
        lines.extend(["", f"Catalogo completo: {catalog_url}"])
    if action_payload.get("has_more") and not catalog_url:
        lines.append("Tengo mas modelos; dime que estilo o cilindrada buscas y te filtro opciones.")
    lines.extend(["", "Dime cual te interesa y te ayudo a cotizarla."])
    return "\n".join(lines)


def _render_state_aware_next_message(
    *,
    extracted_data: dict[str, Any],
    action_payload: dict[str, Any],
) -> str:
    requirements = action_payload.get("requirements") if isinstance(action_payload, dict) else None
    if isinstance(requirements, dict):
        missing = requirements.get("missing") or []
        labels = [
            str(item.get("label") or item.get("key"))
            for item in missing
            if isinstance(item, dict) and (item.get("label") or item.get("key"))
        ]
        if labels:
            return "Ya tengo ese dato. Para avanzar, mandame: " + ", ".join(labels)
    if not _state_guard_present(_state_guard_value(extracted_data, "MOTO")):
        return "Para avanzar, dime que modelo te interesa."
    if not _state_guard_present(_state_guard_value(extracted_data, "CREDITO")):
        return "Para avanzar, dime como recibes tus ingresos."
    if not _state_guard_present(_state_guard_value(extracted_data, "ENGANCHE")):
        return "Para avanzar, dime que enganche quieres manejar."
    return "Ya tengo ese dato registrado. Sigo con el siguiente paso del tramite."


def _render_income_type_question(action_payload: dict[str, Any]) -> str:
    override = str(action_payload.get("prompt_override") or "").strip()
    if override:
        return override
    raw_options = action_payload.get("options") if isinstance(action_payload, dict) else []
    options = raw_options if isinstance(raw_options, list) else []
    numbered_lines = [
        f"{item.get('display_number')}. {_income_option_public_label(item)}"
        for item in options
        if isinstance(item, dict)
        and str(item.get("display_number") or "").strip()
        and _income_option_public_label(item)
    ]
    if numbered_lines:
        intro = "Perfecto, para ver que plan te conviene mas, dime como recibes tus ingresos:"
        acknowledged_seniority = str(
            action_payload.get("acknowledged_employment_seniority") or ""
        ).strip()
        if acknowledged_seniority:
            intro = (
                f"Perfecto, con {acknowledged_seniority} si cumples la antiguedad. "
                "Ahora dime como recibes tus ingresos:"
            )
        return (
            f"{intro}\n\n"
            + "\n".join(numbered_lines)
            + "\n\nPuedes mandarme el numero o escribir el metodo."
        )
    labels = [
        _income_option_public_label(item)
        for item in options
        if isinstance(item, dict) and _income_option_public_label(item)
    ]
    suffix = f" Opciones: {', '.join(labels[:5])}." if labels else ""
    acknowledged_seniority = str(
        action_payload.get("acknowledged_employment_seniority") or ""
    ).strip()
    if acknowledged_seniority:
        return (
            f"Perfecto, con {acknowledged_seniority} si cumples la antiguedad. "
            "Dime como recibes tus ingresos: nomina, con recibos o por fuera."
            f"{suffix}"
        )
    return (
        "Para elegir el credito correcto, dime como recibes tus ingresos: "
        "nomina, con recibos o por fuera."
        f"{suffix}"
    )


def _income_option_public_label(item: dict[str, Any]) -> str:
    raw = str(item.get("visible_label") or item.get("label") or item.get("key") or "").strip()
    normalized = raw.casefold()
    if "sin comprobantes" in normalized:
        return "Me pagan por fuera"
    if "con comprobantes" in normalized:
        return raw.replace("con comprobantes", "con recibos").replace("Con comprobantes", "Con recibos")
    return raw


def _render_credit_plan_resolution(
    action_payload: dict[str, Any],
    extracted_data: dict[str, Any],
    advisor_decision: dict[str, Any] | None = None,
) -> str:
    override = str(action_payload.get("prompt_override") or "").strip()
    if override:
        return override
    label = (
        action_payload.get("selection_label")
        or action_payload.get("selection_key")
        or action_payload.get("field_updates", {}).get("CREDITO")
        or "ese plan"
    )
    updates = action_payload.get("field_updates") if isinstance(action_payload, dict) else {}
    plan = updates.get("ENGANCHE") if isinstance(updates, dict) else None
    plan_text = f" con plan {plan}" if plan else ""
    approved_updates = (
        advisor_decision.get("field_updates_approved")
        if isinstance(advisor_decision, dict)
        else None
    )
    if isinstance(approved_updates, dict) and "MOTO" in approved_updates:
        model = str(_state_guard_value(extracted_data, "MOTO") or "").strip()
        if model:
            return f"Listo, queda como {label}{plan_text} para el modelo {model}."
        return f"Listo, queda como {label}{plan_text} para ese modelo."
    return f"Listo, queda como {label}{plan_text}. Dime que modelo o categoria quieres revisar."


def _render_ask_field_message(action_payload: dict[str, Any]) -> str | None:
    override = str(action_payload.get("prompt_override") or "").strip()
    if override:
        return override
    field_name = str(action_payload.get("field_name") or "").strip().upper()
    if field_name == "ANTIGUEDAD_LABORAL":
        return "Cuanto tiempo llevas en tu empleo actual?"
    if field_name == "MOTO":
        return "Ya tengo tu plan. Solo falta saber que modelo quieres cotizar para decirte bien como avanzar."
    return None


def _render_document_processing(action_payload: dict[str, Any]) -> str:
    if (
        isinstance(action_payload, dict)
        and action_payload.get("request_type") == "ask_missing_document"
    ):
        override = str(action_payload.get("prompt_override") or "").strip()
        if override:
            return override
        pending = action_payload.get("pending_to_resume")
        if isinstance(pending, dict) and pending.get("type") == "ask_missing_documents":
            missing = humanize_document_labels(pending.get("missing") or [])
            if missing:
                return "Para avanzar faltaria: " + join_humanized_documents(missing) + "."
        requirements = action_payload.get("requirements")
        if isinstance(requirements, dict):
            labels = humanize_document_labels(requirements.get("missing") or requirements.get("required") or [])
            if labels:
                return "Para avanzar necesito estos documentos: " + join_humanized_documents(labels) + "."
        return "Te comparto los documentos necesarios para avanzar."

    rejected = (
        action_payload.get("rejected_attachments")
        if isinstance(action_payload, dict)
        else []
    )
    rejected_labels = [
        label
        for label in humanize_document_labels(rejected or [])
        if str(label).strip()
    ]
    if rejected_labels:
        return "La foto no se alcanza a validar bien. Me la puedes reenviar mas clara?"

    received = action_payload.get("received_documents") if isinstance(action_payload, dict) else []
    labels = humanize_document_labels(received or [])
    pending = action_payload.get("pending_to_resume") if isinstance(action_payload, dict) else None
    if labels:
        intro = "Recibi tu documento: " + join_humanized_documents(labels) + "."
    else:
        intro = "Recibi tu documento y lo dejo para validacion."
    if isinstance(pending, dict) and pending.get("type") == "ask_missing_documents":
        missing = humanize_document_labels(pending.get("missing") or [])
        if missing:
            return intro + " Para avanzar faltaria: " + join_humanized_documents(missing) + "."
    return intro


def _render_advisor_clarification(action_payload: dict[str, Any]) -> str:
    suggested = (
        action_payload.get("suggested_clarification")
        if isinstance(action_payload, dict)
        else None
    )
    if isinstance(suggested, str) and suggested.strip():
        return suggested.strip()
    return "Me confirmas a que te refieres para seguir?"


def _render_soft_close(action_payload: dict[str, Any]) -> str:
    suggested = (
        action_payload.get("suggested_response")
        if isinstance(action_payload, dict)
        else None
    )
    if isinstance(suggested, str) and suggested.strip():
        return suggested.strip()
    return "Claro, revisalo con calma. Si decides avanzar, aqui te ayudo."


def _catalog_text_key(text_value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text_value or "").casefold())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", without_accents)).strip()


def _model_question_needs_catalog(
    *,
    messages: list[str] | None,
    extracted_data: dict[str, Any],
    brand_facts: dict[str, Any] | None,
) -> bool:
    if _state_guard_present(_state_guard_value(extracted_data, "MOTO")):
        return False
    if not (
        _state_guard_present(_state_guard_value(extracted_data, "CREDITO"))
        or _state_guard_present(_state_guard_value(extracted_data, "ENGANCHE"))
        or _state_guard_present(_state_guard_value(extracted_data, "PLAN"))
        or _state_guard_present(_state_guard_value(extracted_data, "plan"))
    ):
        return False
    if _protected_question_field(
        messages=messages,
        extracted_data=extracted_data,
        require_existing=False,
    ) != "MOTO":
        return False
    normalized = _catalog_text_key(_message_text(messages))
    if "catalogo" in normalized or "catalog" in normalized or "http" in normalized:
        return False
    return bool((brand_facts or {}).get("catalog_url"))


def _render_model_question_with_catalog(
    *,
    extracted_data: dict[str, Any],
    brand_facts: dict[str, Any] | None,
) -> str:
    enganche = _state_guard_value(extracted_data, "ENGANCHE")
    intro = (
        f"Perfecto, ese plan maneja {enganche} de enganche."
        if _state_guard_present(enganche)
        else "Perfecto, ya tengo el tipo de credito."
    )
    catalog_url = str((brand_facts or {}).get("catalog_url") or "").strip()
    return "\n".join(
        [
            intro,
            "",
            f"Te paso el catalogo para que elijas modelo: {catalog_url}",
            "",
            "Dime cual moto te interesa y te la cotizo.",
        ]
    )


def _faq_payload_ok(action_payload: dict[str, Any]) -> bool:
    return (
        isinstance(action_payload, dict)
        and (
            action_payload.get("status") == "ok"
            or bool(action_payload.get("answered_intents"))
            or bool(str(action_payload.get("requirements_summary") or "").strip())
        )
        and (
            bool(str(action_payload.get("answer") or "").strip())
            or bool(action_payload.get("answers"))
            or bool(str(action_payload.get("requirements_summary") or "").strip())
        )
    )


def _render_guarded_faq_message(action_payload: dict[str, Any]) -> str:
    answers = action_payload.get("answers") if isinstance(action_payload.get("answers"), list) else []
    answer = str(action_payload.get("answer") or "").strip()
    if not answer and answers:
        answer = "\n".join(
            f"{str(item.get('topic') or '').capitalize()}: {str(item.get('answer') or '').strip()}"
            for item in answers
            if isinstance(item, dict) and str(item.get("answer") or "").strip()
        ).strip()
    resume = action_payload.get("resume_pending_action")
    requirements_summary = str(action_payload.get("requirements_summary") or "").strip()
    if not isinstance(resume, dict):
        if requirements_summary and answer:
            return "\n\n".join([answer, requirements_summary])
        return answer or requirements_summary
    if resume.get("type") == "ask_missing_documents":
        missing = humanize_document_labels(resume.get("missing") or [])
        if missing:
            base = "\n\n".join(item for item in [answer, requirements_summary] if item)
            return "\n\n".join(
                [
                    base,
                    "Para avanzar solo faltaria: " + join_humanized_documents(missing) + ".",
                ]
            )
    field = resume.get("field")
    if resume.get("type") == "ask_field" and field:
        prompt = f"Para avanzar, dime el dato de {field}."
        if str(field).strip() == "CREDITO":
            prompt = "Para avanzar, dime como recibes tus ingresos."
        elif str(field).strip() == "MOTO":
            prompt = "Para avanzar, dime que modelo quieres revisar."
        return "\n\n".join(item for item in [answer, requirements_summary, prompt] if item)
    return "\n\n".join(item for item in [answer, requirements_summary] if item)


def _faq_message_covers_payload(
    *,
    messages: list[str] | None,
    action_payload: dict[str, Any],
) -> bool:
    def _normalized_tokens(value: str) -> set[str]:
        return set(re.findall(r"[\w-]+", _state_guard_normalize(value), flags=re.UNICODE))

    text = _state_guard_normalize(_message_text(messages))
    text_tokens = _normalized_tokens(text)
    answer = _state_guard_normalize(str(action_payload.get("answer") or ""))
    if answer and answer not in text:
        answer_tokens = _normalized_tokens(answer)
        if not answer_tokens or len(answer_tokens & text_tokens) < max(2, len(answer_tokens) // 2):
            return False
    requirements_summary = _state_guard_normalize(
        str(action_payload.get("requirements_summary") or "")
    )
    if requirements_summary and requirements_summary not in text:
        summary_tokens = _normalized_tokens(requirements_summary)
        if not summary_tokens or len(summary_tokens & text_tokens) < max(2, len(summary_tokens) // 2):
            return False
    resume = action_payload.get("resume_pending_action")
    if isinstance(resume, dict) and resume.get("type") == "ask_missing_documents":
        missing = humanize_document_labels(resume.get("missing") or [])
        for label in missing:
            label_tokens = _normalized_tokens(label)
            if label_tokens and not (label_tokens & text_tokens):
                return False
    return True


def _answer_payload_to_preserve(
    *,
    action_payload: dict[str, Any],
    advisor_decision: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if _faq_payload_ok(action_payload) or action_payload.get("answers"):
        return action_payload
    if not isinstance(advisor_decision, dict):
        return None
    advisor_payload = advisor_decision.get("tool_payload")
    if not isinstance(advisor_payload, dict):
        return None
    if not (_faq_payload_ok(advisor_payload) or advisor_payload.get("answers")):
        return None
    next_action = str(advisor_decision.get("next_action") or "").strip()
    if next_action in {"answer_faq_and_resume", "answer_and_resume_flow", "lookup_faq"}:
        return advisor_payload
    if advisor_payload.get("answered_intents"):
        return advisor_payload
    return None


def _render_answer_and_resume_message(
    *,
    answer_payload: dict[str, Any],
    resume_text: str,
) -> str:
    answer_text = _render_guarded_faq_message(answer_payload).strip()
    resume_text = str(resume_text or "").strip()
    if answer_text and resume_text:
        return "\n\n".join([answer_text, resume_text])
    return answer_text or resume_text


def _resume_prompt_is_covered(
    *,
    messages: list[str] | None,
    resume_text: str,
    expected_field: str | None,
) -> bool:
    if expected_field:
        resolved_field = _protected_question_field(
            messages=messages,
            extracted_data={},
            require_existing=False,
        )
        if resolved_field == expected_field:
            return True
    prompt_text = _state_guard_normalize(resume_text)
    message_text = _state_guard_normalize(_message_text(messages))
    if not prompt_text or not message_text:
        return False
    prompt_tokens = {token for token in prompt_text.split() if len(token) > 2}
    message_tokens = set(message_text.split())
    return bool(prompt_tokens) and len(prompt_tokens & message_tokens) >= max(
        2,
        min(4, len(prompt_tokens)),
    )


def _composer_output_covers_answer_and_resume(
    *,
    messages: list[str] | None,
    answer_payload: dict[str, Any],
    resume_text: str,
    expected_field: str | None,
) -> bool:
    return _faq_message_covers_payload(
        messages=messages,
        action_payload=answer_payload,
    ) and _resume_prompt_is_covered(
        messages=messages,
        resume_text=resume_text,
        expected_field=expected_field,
    )


def _response_frame_valid(response_frame: ResponseFrame | None) -> bool:
    return bool(response_frame is not None and response_frame.trace.frame_valid)


def _response_frame_text_is_covered(
    *,
    messages: list[str] | None,
    expected_text: str,
) -> bool:
    expected = _state_guard_normalize(expected_text)
    message_text = _state_guard_normalize(_message_text(messages))
    if not expected:
        return True
    if expected in message_text:
        return True
    expected_tokens = set(re.findall(r"[\w-]+", expected, flags=re.UNICODE))
    message_tokens = set(re.findall(r"[\w-]+", message_text, flags=re.UNICODE))
    if not expected_tokens or not message_tokens:
        return False
    overlap = expected_tokens & message_tokens
    return len(overlap) >= max(2, len(expected_tokens) // 2)


def _response_frame_answers_covered(
    *,
    messages: list[str] | None,
    response_frame: ResponseFrame,
) -> bool:
    if not response_frame.validated_answers:
        return True
    for answer in response_frame.validated_answers.values():
        if answer.must_include and not _response_frame_text_is_covered(
            messages=messages,
            expected_text=answer.text,
        ):
            return False
    return True


def _response_frame_current_questions_covered(
    *,
    messages: list[str] | None,
    response_frame: ResponseFrame,
) -> bool:
    if not response_frame.current_questions:
        return True
    if not response_frame.missing_answer_targets:
        return True
    rendered = render_response_frame_fallback_message(response_frame).strip()
    if rendered and _response_frame_text_is_covered(
        messages=messages,
        expected_text=rendered,
    ):
        return True
    message_text = _state_guard_normalize(_message_text(messages))
    for target in response_frame.missing_answer_targets:
        if target == "approval" and ("no puedo prometer" in message_text or "revision" in message_text):
            continue
        if target == "human_handoff" and any(token in message_text for token in ("asesor", "persona", "humano")):
            continue
        if target == "documents" and any(token in message_text for token in ("ine", "document", "comprobante")):
            continue
        if target == "requirements" and any(token in message_text for token in ("requisito", "document", "depende")):
            continue
        if target == "timing" and any(token in message_text for token in ("tiempo", "revision", "validar")):
            continue
        if target == "payoff" and any(token in message_text for token in ("liquid", "adelantar", "penalizacion")):
            continue
        return False
    return True


def _response_frame_pending_flow_covered(
    *,
    messages: list[str] | None,
    response_frame: ResponseFrame,
) -> bool:
    pending = response_frame.pending_flow
    if pending is None or not response_frame.composer_instructions.must_resume_pending_flow:
        return True
    payload = pending.payload if isinstance(pending.payload, dict) else {}
    if pending.type == "ask_missing_documents":
        missing = humanize_document_labels(payload.get("missing") or [])
        if not missing:
            return True
        return all(
            _response_frame_text_is_covered(messages=messages, expected_text=item)
            for item in missing
        )
    if pending.type == "ask_field":
        field_name = str(payload.get("field") or "").strip().upper()
        resume_text = _response_frame_pending_field_prompt(
            field_name=field_name,
            human_name=pending.human_name,
            prefix="Para avanzar,",
        )
        return _resume_prompt_is_covered(
            messages=messages,
            resume_text=resume_text,
            expected_field=field_name or None,
        )
    if pending.type == "quote":
        message_text = _state_guard_normalize(_message_text(messages))
        return any(
            token in message_text
            for token in ("cotizacion", "cotizar", "enganche", "quincenal")
        )
    return True


def _response_frame_anti_repeat_ok(
    *,
    messages: list[str] | None,
    response_frame: ResponseFrame,
) -> bool:
    if not response_frame.composer_instructions.avoid_exact_repeat:
        return True
    previous = str(response_frame.anti_repetition.last_similar_bot_message or "").strip()
    if not previous:
        return True
    return _state_guard_normalize(_message_text(messages)) != _state_guard_normalize(previous)


def _response_frame_recent_duplicate(
    *,
    messages: list[str] | None,
    history: list[tuple[str, str]] | None,
) -> bool:
    normalized = _state_guard_normalize(_message_text(messages))
    if not normalized:
        return False
    for role, previous in reversed(list(history or [])[-8:]):
        if not _is_outbound_history_role(role):
            continue
        prior = _state_guard_normalize(previous)
        if not prior:
            continue
        if prior == normalized:
            return True
        if SequenceMatcher(None, prior, normalized).ratio() >= 0.94:
            return True
    return False


def _response_frame_output_is_acceptable(
    *,
    composer_output: ComposerOutput | None,
    response_frame: ResponseFrame,
) -> bool:
    if composer_output is None or not composer_output.messages:
        return False
    current_question_ok = _response_frame_current_questions_covered(
        messages=composer_output.messages,
        response_frame=response_frame,
    )
    answers_ok = _response_frame_answers_covered(
        messages=composer_output.messages,
        response_frame=response_frame,
    )
    pending_ok = _response_frame_pending_flow_covered(
        messages=composer_output.messages,
        response_frame=response_frame,
    )
    repeat_ok = _response_frame_anti_repeat_ok(
        messages=composer_output.messages,
        response_frame=response_frame,
    )
    strategy = response_frame.response_strategy
    if strategy in {"answer_and_resume_flow", "quote_and_resume", "quote_and_answer"}:
        return current_question_ok and answers_ok and pending_ok and repeat_ok
    if strategy in {"answer_only", "quote", "quote_cash", "answer_cash_price", "handoff", "operational_safe_reply"}:
        if not response_frame.validated_answers and response_frame.current_intents:
            return False
        return current_question_ok and answers_ok and repeat_ok
    if strategy == "ask_missing_field":
        return current_question_ok and pending_ok and repeat_ok
    if strategy in {"document_request", "document_feedback"}:
        return current_question_ok and answers_ok and pending_ok and repeat_ok
    return current_question_ok and repeat_ok


def _response_frame_resume_text(response_frame: ResponseFrame) -> str:
    pending = response_frame.pending_flow
    if pending is None:
        return ""
    payload = pending.payload if isinstance(pending.payload, dict) else {}
    if pending.type == "ask_missing_documents":
        missing = humanize_document_labels(payload.get("missing") or [])
        if missing:
            return "Y para seguir, todavia faltaria: " + join_humanized_documents(missing) + "."
        return "Y para seguir, necesito los documentos pendientes."
    if pending.type == "ask_field":
        field_name = str(payload.get("field") or "").strip().upper()
        return _response_frame_pending_field_prompt(
            field_name=field_name,
            human_name=pending.human_name,
            prefix="Y para seguir,",
        )
    if pending.human_name:
        return f"Y para seguir, continuamos con {pending.human_name}."
    return ""


def _response_frame_pending_field_prompt(
    *,
    field_name: str,
    human_name: str | None,
    prefix: str,
) -> str:
    if field_name == "CREDITO":
        return f"{prefix} dime como recibes tus ingresos."
    if field_name == "MOTO":
        return f"{prefix} dime que modelo quieres revisar."
    if field_name in {"ANTIGUEDAD_LABORAL", "FILTRO"}:
        return f"{prefix} dime cuanto tiempo llevas trabajando ahi."
    if human_name:
        return f"{prefix} continuamos con {human_name}."
    if field_name:
        return f"{prefix} dime el dato que falta."
    return prefix.rstrip(",") + "."


def _render_response_frame_message(response_frame: ResponseFrame) -> str:
    return render_response_frame_fallback_message(response_frame)


def _response_frame_guard_event(
    *,
    composer_output: ComposerOutput,
    response_frame: ResponseFrame,
    reason_override: str | None = None,
    force_render: bool = False,
) -> dict[str, Any] | None:
    if not force_render and _response_frame_output_is_acceptable(
        composer_output=composer_output,
        response_frame=response_frame,
    ):
        return None
    rendered = _render_response_frame_message(response_frame)
    if not rendered:
        return None
    original_text = _message_text(composer_output.messages)
    if _state_guard_normalize(original_text) == _state_guard_normalize(rendered):
        return None
    composer_output.messages = [rendered]
    composer_output.pending_confirmation_set = None
    reason = reason_override or "response_frame_missing_required_content"
    if not _response_frame_anti_repeat_ok(messages=[original_text], response_frame=response_frame):
        reason = "response_frame_exact_repeat_rephrased"
    return {
        "repeated_question_blocked": False,
        "protected_field": "RESPONSE_FRAME",
        "existing_value": None,
        "attempted_question": original_text,
        "conflict_detected": False,
        "overwrite_allowed": None,
        "overwrite_blocked_reason": reason,
        "current_question_detected": bool(response_frame.current_questions),
        "current_question_type": (
            response_frame.required_answer_targets[0]
            if response_frame.required_answer_targets
            else None
        ),
        "current_question_answered": not bool(response_frame.missing_answer_targets),
        "current_question_guard_applied": bool(response_frame.missing_answer_targets),
        "current_question_guard_reason": (
            "missing_required_answer_target"
            if response_frame.missing_answer_targets
            else None
        ),
        "current_question_unresolved_reason": (
            str(response_frame.trace.current_question_unresolved_reason or "")
            or None
        ),
        "outbound_blocked_missing_answer": bool(response_frame.missing_answer_targets),
        "regenerated_response_frame_reason": (
            "current_question_answer_guard"
            if response_frame.missing_answer_targets
            else None
        ),
    }


def _guard_composer_output(
    *,
    composer_output: ComposerOutput | None,
    decision_action: str,
    action_payload: dict[str, Any],
    response_frame: ResponseFrame | None = None,
    extracted_data: dict[str, Any],
    advisor_decision: dict[str, Any] | None = None,
    inbound_text: str = "",
    history: list[tuple[str, str]] | None = None,
    brand_facts: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if composer_output is None:
        return None
    frame_valid = _response_frame_valid(response_frame)
    if (
        frame_valid
        and response_frame is not None
        and response_frame.missing_answer_targets
    ):
        frame_event = _response_frame_guard_event(
            composer_output=composer_output,
            response_frame=response_frame,
            reason_override="current_question_missing_required_answer",
            force_render=True,
        )
        if frame_event is not None:
            return frame_event
    if (
        frame_valid
        and response_frame is not None
        and _response_frame_output_is_acceptable(
            composer_output=composer_output,
            response_frame=response_frame,
        )
    ):
        if _response_frame_recent_duplicate(
            messages=composer_output.messages,
            history=history,
        ):
            frame_event = _response_frame_guard_event(
                composer_output=composer_output,
                response_frame=response_frame,
                reason_override="response_frame_recent_duplicate_rephrased",
                force_render=True,
            )
            if frame_event is not None:
                return frame_event
        return None
    if frame_valid and response_frame is not None and decision_action != "quote":
        frame_event = _response_frame_guard_event(
            composer_output=composer_output,
            response_frame=response_frame,
        )
        if frame_event is not None:
            return frame_event
    if (
        decision_action == "ask_credit_context"
        and not (
            frame_valid
            and response_frame is not None
            and response_frame.response_strategy == "answer_and_resume_flow"
        )
    ):
        original_text = _message_text(composer_output.messages)
        resume_text = _render_income_type_question(action_payload)
        answer_payload = _answer_payload_to_preserve(
            action_payload=action_payload,
            advisor_decision=advisor_decision,
        )
        expected_field = str(action_payload.get("field_name") or "").strip().upper() or None
        if (
            answer_payload is not None
            and _composer_output_covers_answer_and_resume(
                messages=composer_output.messages,
                answer_payload=answer_payload,
                resume_text=resume_text,
                expected_field=expected_field,
            )
        ):
            return None
        composer_output.messages = [
            _render_answer_and_resume_message(
                answer_payload=answer_payload,
                resume_text=resume_text,
            )
            if answer_payload is not None
            else resume_text
        ]
        composer_output.pending_confirmation_set = None
        return {
            "repeated_question_blocked": False,
            "protected_field": "CREDITO",
            "existing_value": action_payload.get("options"),
            "attempted_question": original_text,
            "conflict_detected": False,
            "overwrite_allowed": None,
            "overwrite_blocked_reason": (
                "advisor_answer_and_resume_rendered_from_payload"
                if answer_payload is not None
                else "advisor_income_type_question_rendered_from_payload"
            ),
        }
    if decision_action == "resolve_credit_plan" and not frame_valid:
        original_text = _message_text(composer_output.messages)
        composer_output.messages = [
            _render_credit_plan_resolution(
                action_payload,
                extracted_data,
                advisor_decision,
            )
        ]
        composer_output.pending_confirmation_set = None
        return {
            "repeated_question_blocked": False,
            "protected_field": "CREDITO",
            "existing_value": action_payload.get("selection_key"),
            "attempted_question": original_text,
            "conflict_detected": False,
            "overwrite_allowed": None,
            "overwrite_blocked_reason": "advisor_credit_plan_rendered_from_payload",
        }
    if (
        decision_action == "ask_field"
        and not (
            frame_valid
            and response_frame is not None
            and response_frame.response_strategy == "answer_and_resume_flow"
        )
    ):
        rendered = _render_ask_field_message(action_payload)
        if rendered is not None:
            original_text = _message_text(composer_output.messages)
            answer_payload = _answer_payload_to_preserve(
                action_payload=action_payload,
                advisor_decision=advisor_decision,
            )
            expected_field = str(action_payload.get("field_name") or "").strip().upper() or None
            if (
                answer_payload is not None
                and _composer_output_covers_answer_and_resume(
                    messages=composer_output.messages,
                    answer_payload=answer_payload,
                    resume_text=rendered,
                    expected_field=expected_field,
                )
            ):
                return None
            composer_output.messages = [
                _render_answer_and_resume_message(
                    answer_payload=answer_payload,
                    resume_text=rendered,
                )
                if answer_payload is not None
                else rendered
            ]
            composer_output.pending_confirmation_set = None
            return {
                "repeated_question_blocked": False,
                "protected_field": action_payload.get("field_name"),
                "existing_value": None,
                "attempted_question": original_text,
                "conflict_detected": False,
                "overwrite_allowed": None,
                "overwrite_blocked_reason": (
                    "advisor_answer_and_resume_rendered_from_payload"
                    if answer_payload is not None
                    else "advisor_ask_field_rendered_from_payload"
                ),
            }
    if (
        decision_action == "classify_document"
        and not (
            frame_valid
            and response_frame is not None
            and response_frame.response_strategy == "answer_and_resume_flow"
        )
    ):
        original_text = _message_text(composer_output.messages)
        composer_output.messages = [_render_document_processing(action_payload)]
        composer_output.pending_confirmation_set = None
        return {
            "repeated_question_blocked": False,
            "protected_field": "DOCUMENTO",
            "existing_value": action_payload.get("received_documents"),
            "attempted_question": original_text,
            "conflict_detected": False,
            "overwrite_allowed": None,
            "overwrite_blocked_reason": "advisor_document_rendered_from_payload",
        }
    if (
        decision_action == "ask_clarification"
        and isinstance(action_payload, dict)
        and action_payload.get("request_type") == "clarify_ambiguous_yes_no"
    ):
        original_text = _message_text(composer_output.messages)
        composer_output.messages = [_render_advisor_clarification(action_payload)]
        pending_confirmation = action_payload.get("pending_confirmation_set")
        if isinstance(pending_confirmation, dict):
            composer_output.pending_confirmation_set = json.dumps(pending_confirmation)
        else:
            composer_output.pending_confirmation_set = None
        return {
            "repeated_question_blocked": False,
            "protected_field": "ambiguous_yes_no",
            "existing_value": None,
            "attempted_question": original_text,
            "conflict_detected": False,
            "overwrite_allowed": None,
            "overwrite_blocked_reason": "advisor_clarification_rendered_from_payload",
        }
    if decision_action == "soft_close" and not frame_valid:
        original_text = _message_text(composer_output.messages)
        composer_output.messages = [_render_soft_close(action_payload)]
        composer_output.pending_confirmation_set = None
        return {
            "repeated_question_blocked": False,
            "protected_field": "soft_close",
            "existing_value": None,
            "attempted_question": original_text,
            "conflict_detected": False,
            "overwrite_allowed": None,
            "overwrite_blocked_reason": "soft_close_rendered_from_payload",
        }
    if decision_action == "search_catalog" and _catalog_browse_payload_ok(action_payload):
        original_text = _message_text(composer_output.messages)
        composer_output.messages = [_render_guarded_catalog_browse_message(action_payload)]
        composer_output.pending_confirmation_set = None
        return {
            "repeated_question_blocked": False,
            "protected_field": "catalog_browse",
            "existing_value": action_payload.get("total_results"),
            "attempted_question": original_text,
            "conflict_detected": False,
            "overwrite_allowed": None,
            "overwrite_blocked_reason": "catalog_browse_output_rendered_from_payload",
        }
    if decision_action == "lookup_faq" and _faq_payload_ok(action_payload):
        if not _faq_message_covers_payload(
            messages=composer_output.messages,
            action_payload=action_payload,
        ):
            original_text = _message_text(composer_output.messages)
            composer_output.messages = [_render_guarded_faq_message(action_payload)]
            composer_output.pending_confirmation_set = None
            return {
                "repeated_question_blocked": False,
                "protected_field": "FAQ",
                "existing_value": action_payload.get("topic"),
                "attempted_question": original_text,
                "conflict_detected": False,
                "overwrite_allowed": None,
                "overwrite_blocked_reason": "faq_output_rendered_from_payload",
            }
        return None
    if decision_action == "quote" and _quote_payload_ok(action_payload):
        rendered_quote = render_quote_response(
            action_payload=action_payload,
            inbound_text=inbound_text,
            history=history or [],
        )
        asked_field = _protected_question_field(
            messages=composer_output.messages,
            extracted_data=extracted_data,
            require_existing=False,
        )
        if (
            asked_field
            or rendered_quote.mode == "cash"
            or rendered_quote.mode == "summary"
            or not _quote_message_contains_quote(composer_output.messages)
        ):
            original_text = _message_text(composer_output.messages)
            composer_output.messages = [rendered_quote.text]
            composer_output.pending_confirmation_set = None
            return {
                "repeated_question_blocked": bool(asked_field),
                "protected_field": asked_field,
                "existing_value": (
                    _state_guard_value(extracted_data, asked_field) if asked_field else None
                ),
                "attempted_question": original_text,
                "conflict_detected": False,
                "overwrite_allowed": None,
                "overwrite_blocked_reason": (
                    "quote_output_replaced_repeated_question"
                    if asked_field
                    else rendered_quote.reason
                ),
            }
        return None
    if _model_question_needs_catalog(
        messages=composer_output.messages,
        extracted_data=extracted_data,
        brand_facts=brand_facts,
    ):
        original_text = _message_text(composer_output.messages)
        composer_output.messages = [
            _render_model_question_with_catalog(
                extracted_data=extracted_data,
                brand_facts=brand_facts,
            )
        ]
        composer_output.pending_confirmation_set = None
        return {
            "repeated_question_blocked": False,
            "protected_field": "MOTO",
            "existing_value": None,
            "attempted_question": original_text,
            "conflict_detected": False,
            "overwrite_allowed": None,
            "overwrite_blocked_reason": "model_question_catalog_link_added",
        }
    asked_field = _protected_question_field(
        messages=composer_output.messages,
        extracted_data=extracted_data,
        require_existing=True,
    )
    if not asked_field:
        return None
    original_text = _message_text(composer_output.messages)
    composer_output.messages = [
        _render_state_aware_next_message(
            extracted_data=extracted_data,
            action_payload=action_payload,
        )
    ]
    composer_output.pending_confirmation_set = None
    return {
        "repeated_question_blocked": True,
        "protected_field": asked_field,
        "existing_value": _state_guard_value(extracted_data, asked_field),
        "attempted_question": original_text,
        "conflict_detected": False,
        "overwrite_allowed": None,
        "overwrite_blocked_reason": "resolved_field_question_blocked",
    }


def _should_render_quote_summary(
    *,
    action_payload: dict[str, Any],
    inbound_text: str,
    history: list[tuple[str, str]],
) -> bool:
    if _explicit_full_quote_request(inbound_text):
        return False
    return _recent_quote_sent(action_payload=action_payload, history=history)


def _explicit_full_quote_request(text: str) -> bool:
    normalized = _normalize(text)
    full_terms = {
        "cotizacion completa",
        "mandame la cotizacion",
        "pasame la cotizacion",
        "otra vez completa",
        "completa",
    }
    return any(term in normalized for term in full_terms)


def _prefer_followup_quote_summary(text: str) -> bool:
    normalized = _normalize(text)
    tokens = set(normalized.split())
    if _explicit_full_quote_request(text):
        return False
    return bool(tokens & {"mejor", "igual", "entonces"})


def _recent_quote_sent(
    *,
    action_payload: dict[str, Any],
    history: list[tuple[str, str]],
) -> bool:
    name = _normalize(str(action_payload.get("name") or action_payload.get("sku") or ""))
    recent_outbound = [
        _normalize(text)
        for direction, text in history[-8:]
        if _is_outbound_history_role(direction) and text
    ]
    for text in reversed(recent_outbound):
        if "$" not in text:
            continue
        if not ("enganche" in text or "quincenal" in text or "contado" in text):
            continue
        if not name or _model_token_overlap(name, text):
            return True
        # A recent quote for another model still makes a full quote feel
        # repetitive; summarize the refreshed numbers instead.
        return True
    return False


def _model_token_overlap(left: str, right: str) -> bool:
    tokens = {token for token in left.split() if len(token) > 1}
    return bool(tokens and tokens <= set(right.split()))


def _render_full_quote(action_payload: dict[str, Any]) -> str:
    name = action_payload.get("name") or action_payload.get("sku") or "el modelo"
    cash_price = action_payload.get("cash_price_mxn") or action_payload.get("list_price_mxn")
    list_price = action_payload.get("list_price_mxn") or action_payload.get("cash_price_mxn")
    requested_plan = str(action_payload.get("requested_plan_code") or "").strip()
    selected_plan = _selected_plan(action_payload)
    lines = [f"La {name} queda en {_format_money(list_price)} de lista."]
    if str(cash_price or "") != str(list_price or ""):
        lines.append(f"De contado queda en {_format_money(cash_price)}.")
    else:
        lines[0] = f"La {name} de contado queda en {_format_money(cash_price)}."
    if selected_plan:
        plan_label = _quote_plan_label(action_payload, requested_plan)
        lines.extend(
            [
                "",
                f"Con tu plan {plan_label}:",
                f"Enganche: {_format_money(selected_plan.get('down_payment_mxn'))}",
                f"Pago quincenal: {_format_money(selected_plan.get('installment_mxn'))}",
                f"Plazo: {selected_plan.get('term_count')} quincenas",
                "",
                "Puedes liquidar antes sin penalizacion.",
            ]
        )
    return "\n".join(lines)


def _render_quote_summary(action_payload: dict[str, Any]) -> str:
    name = action_payload.get("name") or action_payload.get("sku") or "el modelo"
    cash_price = action_payload.get("cash_price_mxn") or action_payload.get("list_price_mxn")
    list_price = action_payload.get("list_price_mxn") or action_payload.get("cash_price_mxn")
    requested_plan = str(action_payload.get("requested_plan_code") or "").strip()
    selected_plan = _selected_plan(action_payload)
    plan_label = _quote_plan_label(action_payload, requested_plan)
    plan_text = f" con plan {plan_label}" if plan_label else ""
    if selected_plan:
        down_payment = _format_money(selected_plan.get("down_payment_mxn"))
        installment = _format_money(selected_plan.get("installment_mxn"))
        term_count = selected_plan.get("term_count")
        return (
            f"Para {name}{plan_text}: lista {_format_money(list_price)}, contado {_format_money(cash_price)}, "
            f"enganche {down_payment}, pago quincenal {installment} y plazo {term_count} quincenas."
        )
    return f"Para {name}: lista {_format_money(list_price)} y contado {_format_money(cash_price)}."


def _render_quote_followup_summary(action_payload: dict[str, Any]) -> str:
    name = action_payload.get("name") or action_payload.get("sku") or "el modelo"
    cash_price = action_payload.get("cash_price_mxn") or action_payload.get("list_price_mxn")
    list_price = action_payload.get("list_price_mxn") or action_payload.get("cash_price_mxn")
    requested_plan = str(action_payload.get("requested_plan_code") or "").strip()
    selected_plan = _selected_plan(action_payload)
    plan_label = _quote_plan_label(action_payload, requested_plan)
    plan_text = f" con plan {plan_label}" if plan_label else ""
    if selected_plan:
        term_count = selected_plan.get("term_count")
        return (
            f"Sigue igual para {name}{plan_text}: enganche "
            f"{_format_money(selected_plan.get('down_payment_mxn'))}, pago quincenal "
            f"{_format_money(selected_plan.get('installment_mxn'))}, plazo {term_count} quincenas, "
            f"contado {_format_money(cash_price)} y lista {_format_money(list_price)}."
        )
    return f"Sigue igual para {name}: lista {_format_money(list_price)} y contado {_format_money(cash_price)}."


def _render_quote_memory_recall(action_payload: dict[str, Any]) -> str:
    name = action_payload.get("name") or action_payload.get("sku") or "el modelo"
    cash_price = action_payload.get("cash_price_mxn") or action_payload.get("list_price_mxn")
    requested_plan = str(action_payload.get("requested_plan_code") or "").strip()
    selected_plan = _selected_plan(action_payload)
    plan_text = f" con plan {requested_plan}" if requested_plan else ""
    if selected_plan:
        return (
            f"La ultima cotizacion que te comparti para {name}{plan_text} fue: enganche "
            f"{_format_money(selected_plan.get('down_payment_mxn'))}, pago quincenal "
            f"{_format_money(selected_plan.get('installment_mxn'))} y contado "
            f"{_format_money(cash_price)}."
        )
    return (
        f"La ultima cotizacion que te comparti para {name} fue de contado "
        f"{_format_money(cash_price)}."
    )


def _quote_plan_label(action_payload: dict[str, Any], requested_plan: str | None = None) -> str:
    source = action_payload.get("source") if isinstance(action_payload, dict) else None
    selection = ""
    if isinstance(source, dict):
        selection = str(source.get("selection_label") or source.get("selection_key") or "").strip()
    if not selection:
        requirements = action_payload.get("requirements") if isinstance(action_payload, dict) else None
        if isinstance(requirements, dict):
            selection = str(
                requirements.get("selection_label") or requirements.get("selection_key") or ""
            ).strip()
    plan = str(requested_plan or action_payload.get("requested_plan_code") or "").strip()
    if selection and plan and plan not in selection:
        return f"{selection} {plan}"
    return selection or plan or "seleccionado"


def _recent_exact_outbound(*, text: str, history: list[tuple[str, str]]) -> bool:
    normalized = _normalize(text)
    for direction, previous in reversed(history[-4:]):
        if not _is_outbound_history_role(direction):
            continue
        return _normalize(previous) == normalized
    return False


def _history_contains_quote_signature(
    *,
    action_payload: dict[str, Any],
    history: list[tuple[str, str]],
) -> bool:
    signature_parts = _quote_signature_parts(action_payload)
    if len(signature_parts) < 4:
        return False
    for direction, previous in reversed(history[-8:]):
        if not _is_outbound_history_role(direction):
            continue
        normalized_previous = _normalize(previous)
        if normalized_previous and all(part in normalized_previous for part in signature_parts):
            return True
    return False


def _quote_signature_parts(action_payload: dict[str, Any]) -> list[str]:
    name = _normalize(str(action_payload.get("name") or action_payload.get("sku") or ""))
    cash_price = _normalize(
        _format_money(action_payload.get("cash_price_mxn") or action_payload.get("list_price_mxn"))
    )
    requested_plan = _normalize(str(action_payload.get("requested_plan_code") or "").strip())
    selected_plan = _selected_plan(action_payload)
    if not selected_plan:
        return [part for part in (name, requested_plan, cash_price) if part]
    return [
        part
        for part in (
            name,
            requested_plan,
            _normalize(_format_money(selected_plan.get("down_payment_mxn"))),
            _normalize(_format_money(selected_plan.get("installment_mxn"))),
            _normalize(str(selected_plan.get("term_count") or "")),
            cash_price,
        )
        if part
    ]


def _is_outbound_history_role(direction: Any) -> bool:
    normalized = _normalize(str(direction or ""))
    return normalized in {"assistant", "bot", "outbound", "system"}


def _selected_plan(action_payload: dict[str, Any]) -> dict[str, Any]:
    requested_plan = str(action_payload.get("requested_plan_code") or "").strip()
    payment_options = action_payload.get("payment_options") or {}
    selected_plan = payment_options.get(requested_plan) if requested_plan else None
    if not isinstance(selected_plan, dict) and isinstance(payment_options, dict):
        selected_plan = next(
            (value for value in payment_options.values() if isinstance(value, dict)),
            {},
        )
    return selected_plan if isinstance(selected_plan, dict) else {}


def _format_money(value: Any) -> str:
    try:
        amount = int(Decimal(str(value or "0")))
    except Exception:
        return f"${value}"
    return f"${amount:,}"


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).strip()


__all__ = [
    "RenderedResponse",
    "ResponseContractRequest",
    "ResponseContractResult",
    "_faq_payload_ok",
    "apply_response_contract",
    "is_valid_quote_summary",
    "render_quote_response",
]

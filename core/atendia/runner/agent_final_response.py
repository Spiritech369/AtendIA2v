from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from atendia.runner.composer_protocol import ComposerOutput
from atendia.runner.response_frame import ResponseFrame, render_response_frame_fallback_message


INTERNAL_LANGUAGE_RE = re.compile(
    r"\b(stay_in_stage|turn_resolver|pipeline|recomputed)\b"
    r"|registrad[oa]\s+.*\s+como|corregirl[oa]\s+a|catalogo\s+activo|cat[aá]logo\s+activo|modelo\s+activo",
    re.IGNORECASE,
)
STATE_SLOT_LANGUAGE_RE = re.compile(r"\b(MOTO|CREDITO|FILTRO|ENGANCHE)\b")
CATALOG_ERROR_RE = re.compile(r"no\s+encontr[eé]\s+.*(catalogo|cat[aá]logo|modelo)", re.IGNORECASE)
DOC_REQUEST_RE = re.compile(
    r"\b(ine|documentos?|papeles|comprobante\s+de\s+domicilio|estado[s]?\s+de\s+cuenta|nomina|n[oó]mina)\b",
    re.IGNORECASE,
)
INCOME_MENU_RE = re.compile(
    r"1\.\s*me\s+depositan.*2\.\s*me\s+pagan.*3\.\s*soy\s+pensionado",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class AgentFinalResponseRequest:
    user_message: str
    history: list[tuple[str, str]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    tool_results: dict[str, Any] = field(default_factory=dict)
    final_action: str | None = None
    advisor_brain_result: dict[str, Any] | None = None
    response_frame: ResponseFrame | None = None
    composer_output: ComposerOutput | None = None
    brand_facts: dict[str, Any] = field(default_factory=dict)
    allow_document_resume: bool = True


@dataclass(frozen=True)
class AgentFinalResponse:
    text: str
    source: str
    rewrote: bool
    reasons: list[str]
    answered_intents: list[str]


@dataclass(frozen=True)
class FinalizedAgentResponse:
    composer_output: ComposerOutput
    final_response: AgentFinalResponse
    original_text: str
    trace: dict[str, Any]


def finalize_agent_visible_response(
    request: AgentFinalResponseRequest,
) -> FinalizedAgentResponse:
    """Apply the final customer-visible authority and return trace metadata.

    Composer, response-contract and deterministic renderers may prepare draft
    text, but this is the boundary that turns any draft into sendable text.
    Callers should use the returned ``composer_output`` for traces/outbox.
    """

    original_text = _composer_output_text(request.composer_output)
    final_response = build_agent_final_response(request)
    composer_output = composer_output_with_agent_final_response(
        request.composer_output,
        final_response,
    )
    trace = {
        "agent_final_authority_applied": True,
        "agent_final_authority_rewrote": final_response.rewrote,
        "agent_final_authority_source": final_response.source,
        "agent_final_authority_reasons": list(final_response.reasons),
        "agent_final_authority_answered_intents": list(final_response.answered_intents),
        "agent_final_authority_original_text": original_text,
    }
    return FinalizedAgentResponse(
        composer_output=composer_output,
        final_response=final_response,
        original_text=original_text,
        trace=trace,
    )


def build_agent_final_response(request: AgentFinalResponseRequest) -> AgentFinalResponse:
    """Return the only customer-visible text allowed for a runner turn.

    This layer treats runner/tool/composer output as draft material. It keeps
    valid LLM text when it is safe, but rewrites drafts that leak internals,
    skip the current question, route non-catalog questions to catalog errors,
    or restart document/menu templates.
    """

    candidate = _candidate_text(request)
    questions = _question_intents(request.user_message)
    required_answers = _direct_answers(request, questions)
    answered = _answered_intents(candidate, questions)
    reasons: list[str] = []

    if _has_internal_language(candidate) and not _is_safe_state_clarification(candidate, request):
        reasons.append("internal_language_blocked")
    if _catalog_error_for_non_catalog_question(candidate, questions):
        reasons.append("catalog_error_for_non_catalog_question")
    missing = [intent for intent in questions if intent not in answered]
    if missing:
        reasons.append("current_question_not_answered")
    if _looks_like_default_income_menu(candidate):
        reasons.append("default_menu_rewritten")
    if _document_loop_risk(candidate, request):
        reasons.append("document_loop_blocked")

    if reasons:
        text = _compose_human_response(
            request=request,
            required_answers=required_answers,
            include_resume=not _document_loop_risk(candidate, request),
        )
        return AgentFinalResponse(
            text=_sanitize(text),
            source="agent_final_authority",
            rewrote=True,
            reasons=_dedupe(reasons),
            answered_intents=_question_intents(request.user_message),
        )

    text = _sanitize(candidate)
    if required_answers:
        still_missing = [
            intent for intent in questions if intent not in _answered_intents(text, questions)
        ]
        if still_missing:
            text = _sanitize(
                _compose_human_response(
                    request=request,
                    required_answers=required_answers,
                    include_resume=True,
                )
            )
            reasons.append("current_question_answer_prepended")
    return AgentFinalResponse(
        text=text or "Claro, te ayudo. Me dices un poquito mas para orientarte bien?",
        source="agent_final_authority",
        rewrote=bool(reasons),
        reasons=_dedupe(reasons),
        answered_intents=_answered_intents(text, questions),
    )


def composer_output_with_agent_final_response(
    composer_output: ComposerOutput | None,
    final_response: AgentFinalResponse,
) -> ComposerOutput:
    raw_llm_response = composer_output.raw_llm_response if composer_output is not None else None
    suggested_handoff = composer_output.suggested_handoff if composer_output is not None else None
    pending_confirmation = (
        composer_output.pending_confirmation_set if composer_output is not None else None
    )
    return ComposerOutput(
        messages=[final_response.text],
        pending_confirmation_set=pending_confirmation,
        raw_llm_response=raw_llm_response,
        suggested_handoff=suggested_handoff,
    )


def _composer_output_text(composer_output: ComposerOutput | None) -> str:
    if composer_output is None:
        return ""
    return "\n".join(str(message or "") for message in list(composer_output.messages or [])).strip()


def _candidate_text(request: AgentFinalResponseRequest) -> str:
    if request.final_action == "ask_clarification":
        action_text = _action_payload_text(request)
        if action_text:
            return action_text
    if request.final_action == "agent_response" and _has_explicit_document_resume(request):
        action_text = _action_payload_text(request)
        if action_text:
            return action_text
    if request.composer_output is not None:
        text = "\n\n".join(str(message or "").strip() for message in request.composer_output.messages)
        if text.strip():
            return text.strip()
    advisor = request.advisor_brain_result or {}
    for key in ("natural_response", "advisor_brain_natural_response"):
        value = advisor.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    output = advisor.get("output")
    if isinstance(output, dict):
        value = output.get("natural_response")
        if isinstance(value, str) and value.strip():
            return value.strip()
    if request.response_frame is not None and request.response_frame.trace.frame_valid:
        rendered = render_response_frame_fallback_message(request.response_frame).strip()
        if rendered:
            return rendered
    return ""


def _question_intents(text: str) -> list[str]:
    normalized = _normalize(text)
    intents: list[str] = []
    if any(token in normalized for token in ("donde estan", "ubicacion", "direccion", "sucursal")):
        intents.append("ubicacion")
    if any(token in normalized for token in ("buro", "historial crediticio")):
        intents.append("buro")
    if any(token in normalized for token in ("liquidar", "liquido", "liquide", "pagar antes", "adelantar", "penalizacion")):
        intents.append("liquidacion")
    if any(token in normalized for token in ("aprueban", "aprobacion", "aprobado", "autorizan", "seguro")):
        intents.append("aprobacion")
    if any(
        token in normalized
        for token in (
            "cuanto sale",
            "cuanto cuesta",
            "cuanto vale",
            "cuanto es",
            "precio",
            "cotizacion",
            "cotizar",
            "cuanto queda",
        )
    ):
        intents.append("precio")
    if any(
        token in normalized
        for token in (
            "document",
            "papel",
            "papeles",
            "ine",
            "comprobante",
            "requisito",
            "requisitos",
            "que mando",
            "que te mando",
        )
    ):
        intents.append("documentos")
    if _is_document_question(normalized):
        intents.append("documentos")
    if any(token in normalized for token in ("hablar con alguien", "humano", "asesor")):
        intents.append("humano")
    return _dedupe(intents)


def _direct_answers(
    request: AgentFinalResponseRequest,
    questions: list[str],
) -> list[tuple[str, str]]:
    answers: list[tuple[str, str]] = []
    tool_answers = _tool_answers(request.tool_results)
    for intent in questions:
        answer = tool_answers.get(intent)
        if not answer and request.response_frame is not None:
            answer = _response_frame_answer(request.response_frame, intent)
        if not answer:
            answer = _default_answer(request, intent)
        if answer:
            answers.append((intent, answer))
    return answers


def _tool_answers(tool_results: dict[str, Any]) -> dict[str, str]:
    answers: dict[str, str] = {}
    raw_answers = tool_results.get("answers")
    if isinstance(raw_answers, list):
        for item in raw_answers:
            if not isinstance(item, dict):
                continue
            topic = _normalize(item.get("topic"))
            text = str(item.get("answer") or "").strip()
            if not text:
                continue
            if "ubic" in topic:
                answers["ubicacion"] = text
            elif "buro" in topic:
                answers["buro"] = text
            elif "liquid" in topic:
                answers["liquidacion"] = text
    topic = _normalize(tool_results.get("topic") or tool_results.get("source_topic"))
    answer = str(tool_results.get("answer") or "").strip()
    if answer:
        answered_intents = tool_results.get("answered_intents")
        detected_intents = tool_results.get("detected_intents")
        if (
            isinstance(answered_intents, list)
            and any(_normalize(item) == "documents" for item in answered_intents)
        ) or (
            isinstance(detected_intents, list)
            and any(_normalize(item) == "documents" for item in detected_intents)
        ):
            answers.setdefault("documentos", answer)
        if "ubic" in topic:
            answers.setdefault("ubicacion", answer)
        elif "buro" in topic:
            answers.setdefault("buro", answer)
        elif "liquid" in topic:
            answers.setdefault("liquidacion", answer)
    return answers


def _response_frame_answer(response_frame: ResponseFrame, intent: str) -> str | None:
    keys = {
        "ubicacion": ("ubicacion", "location"),
        "buro": ("buro",),
        "aprobacion": ("approval", "aprobacion"),
        "liquidacion": ("payoff", "liquidacion"),
        "precio": ("quote", "price", "cash_price"),
        "documentos": ("documents", "documentos", "requirements", "requisitos"),
    }.get(intent, (intent,))
    for key, answer in response_frame.validated_answers.items():
        normalized_key = _normalize(key)
        if any(target in normalized_key for target in keys) and answer.text.strip():
            return answer.text.strip()
    return None


def _default_answer(request: AgentFinalResponseRequest, intent: str) -> str:
    if intent == "ubicacion":
        address = (
            request.brand_facts.get("address")
            or request.brand_facts.get("direccion")
            or request.brand_facts.get("location")
        )
        if address:
            return f"Estamos en {address}."
        return "Estamos en Monterrey, Nuevo Leon."
    if intent == "buro":
        max_amount = request.brand_facts.get("buro_max_amount")
        if max_amount:
            return f"Si, revisamos buro; puede aplicar de forma flexible hasta {max_amount}, sujeto a revision."
        return "Si, se revisa buro dentro del expediente."
    if intent == "aprobacion":
        return "No puedo prometer aprobacion; se revisa con el expediente completo."
    if intent == "liquidacion":
        return "Si, puedes liquidar antes; se recalcula lo pendiente a la fecha de pago."
    if intent == "humano":
        return "Si, puedo dejarlo para que lo revise un asesor."
    if intent == "precio":
        quote = request.tool_results if request.final_action == "quote" else _state_value(request.state, "last_quote")
        if not isinstance(quote, dict):
            quote = {}
        rendered = _render_quote(quote)
        if rendered:
            return rendered
    if intent == "documentos":
        if request.final_action == "quote" and not _previous_bot_requested_documents(request):
            return ""
        normalized = _normalize(request.user_message)
        credit_plan = _normalize(_state_value(request.state, "CREDITO"))
        if "estado" in normalized and "cuenta" in normalized and "sin comprobantes" in credit_plan:
            return (
                "No te estoy pidiendo estados de cuenta para ese plan. "
                "Lo pendiente es INE por ambos lados y comprobante de domicilio reciente."
            )
        if _is_document_status_question(normalized):
            return (
                "No me aparece cargado todavia. Mandamelo otra vez como foto o archivo "
                "y te confirmo cuando entre."
            )
        return "Sobre los documentos, lo primero es mandar INE por ambos lados y comprobante de domicilio reciente si aplica a tu plan."
    return ""


def _compose_human_response(
    *,
    request: AgentFinalResponseRequest,
    required_answers: list[tuple[str, str]],
    include_resume: bool,
) -> str:
    parts = [answer for _intent, answer in required_answers if answer.strip()]
    advisor = _advisor_natural_response(request.advisor_brain_result)
    field = str((request.tool_results or {}).get("field_name") or "").upper()
    if (
        parts
        and request.final_action == "ask_field"
        and field == "MOTO"
        and _state_value(request.state, "recent_catalog_candidates")
        and advisor
    ):
        parts.append(advisor)
    if not parts:
        if advisor:
            parts.append(advisor)
    if not parts:
        action_text = _action_payload_text(request)
        if action_text:
            parts.append(action_text)
    if include_resume:
        resume = _resume_text(request)
        if resume:
            parts.append(resume)
    if not parts:
        parts.append("Claro, te ayudo con eso.")
    return " ".join(_dedupe(parts))


def _advisor_natural_response(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return ""
    for key in ("natural_response", "advisor_brain_natural_response"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    output = result.get("output")
    if isinstance(output, dict):
        value = output.get("natural_response")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _resume_text(request: AgentFinalResponseRequest) -> str:
    if request.response_frame is not None and request.response_frame.trace.frame_valid:
        rendered = render_response_frame_fallback_message(request.response_frame).strip()
        if rendered and not _has_internal_language(rendered):
            if not _document_loop_risk(rendered, request):
                return rendered
    if request.final_action == "ask_credit_context":
        if _state_value(request.state, "last_quote"):
            return "Seguimos con la cotizacion que ya te pase; si quieres avanzar te dejo con un asesor."
        if _state_value(request.state, "CREDITO") and _state_value(request.state, "ENGANCHE"):
            return "Ya tengo tu plan. Si quieres, te reviso la cotizacion con el modelo que elegiste."
        return "Para ubicarte en el plan correcto, dime como recibes tus ingresos."
    if request.final_action == "answer_faq":
        model = _state_value(request.state, "MOTO") or (request.tool_results or {}).get("resolved_model")
        credit = _state_value(request.state, "CREDITO")
        if _state_value(request.state, "last_quote"):
            return "Seguimos con la cotizacion que ya tienes; si quieres avanzar, vemos documentos."
        if model and not credit:
            return "Y seguimos con esa moto; dime como recibes tus ingresos para cotizarla bien."
        if model and credit:
            return "Seguimos con la cotizacion que ya tienes; si quieres avanzar, vemos documentos."
    if request.final_action == "ask_field":
        field = str((request.tool_results or {}).get("field_name") or "").upper()
        if field == "MOTO" and not _state_value(request.state, "MOTO"):
            recent_candidates = _state_value(request.state, "recent_catalog_candidates")
            if recent_candidates:
                return ""
            return "Y dime que modelo o estilo de moto te interesa."
        if field == "ENGANCHE":
            return "Y dime con cuanto enganche te gustaria empezar."
    if request.final_action == "classify_document" and request.allow_document_resume:
        normalized = _normalize(request.user_message)
        credit_plan = _normalize(_state_value(request.state, "CREDITO"))
        if "estado" in normalized and "cuenta" in normalized and "sin comprobantes" in credit_plan:
            return (
                "No te estoy pidiendo estados de cuenta para ese plan. "
                "Lo pendiente es INE por ambos lados y comprobante de domicilio reciente."
            )
        return "Si quieres avanzar con el tramite, mandame tu INE por ambos lados cuando la tengas a la mano."
    return ""


def _action_payload_text(request: AgentFinalResponseRequest) -> str:
    payload = request.tool_results if isinstance(request.tool_results, dict) else {}
    prompt = str(payload.get("prompt_override") or "").strip()
    if prompt and not _has_internal_language(prompt):
        return prompt
    suggested = str(payload.get("suggested_clarification") or "").strip()
    if suggested and not _has_internal_language(suggested):
        return suggested
    if request.final_action == "quote":
        return _render_quote(payload)
    if request.final_action == "search_catalog":
        if payload.get("request_type") == "catalog_browse":
            total = payload.get("total_results")
            url = payload.get("catalog_url") or request.brand_facts.get("catalog_url")
            if url:
                return f"Claro, puedes ver el catalogo aqui: {url}."
            if total:
                return f"Claro, tengo {total} opciones para mostrarte. Dime que estilo buscas y te oriento."
            return "Claro, te paso opciones de motos. Dime si buscas trabajo, ciudad o algo mas deportivo."
        results = payload.get("results")
        if isinstance(results, list) and results:
            names = [
                str(item.get("name") or item.get("model") or "").strip()
                for item in results
                if isinstance(item, dict)
            ]
            names = [name for name in names if name]
            if names:
                return "Estas opciones te pueden servir: " + ", ".join(names[:3]) + "."
    if request.final_action == "agent_response":
        missing_documents = _render_missing_documents_from_payload(payload, request)
        if missing_documents:
            return missing_documents
    if request.final_action in {"resolve_credit_plan", "ask_credit_context"}:
        field_updates = payload.get("field_updates") if isinstance(payload.get("field_updates"), dict) else {}
        plan = (
            payload.get("credit_plan")
            or payload.get("plan")
            or payload.get("CREDITO")
            or payload.get("selection_key")
            or payload.get("selection_label")
            or field_updates.get("CREDITO")
        )
        down = (
            payload.get("down_payment")
            or payload.get("down_payment_percent")
            or payload.get("ENGANCHE")
            or field_updates.get("ENGANCHE")
        )
        model = _state_value(request.state, "MOTO")
        if plan and down and model:
            return f"Perfecto, con ese esquema la {model} va con {down} de enganche. Quieres que te la cotice asi?"
        if plan and down:
            return f"Perfecto, con ese esquema tu plan queda con {down} de enganche. Ahora dime que modelo quieres cotizar."
        return "Para ubicarte en el plan correcto, dime como recibes tus ingresos."
    if request.final_action == "ask_field":
        field = str(payload.get("field_name") or payload.get("field") or "").upper()
        if field == "MOTO" and not _state_value(request.state, "MOTO"):
            return "Dime que modelo o estilo de moto te interesa y te ayudo a cotizarlo."
    return ""


def _answered_intents(text: str, questions: list[str]) -> list[str]:
    normalized = _normalize(text)
    answered: list[str] = []
    for intent in questions:
        if intent == "ubicacion" and any(
            token in normalized for token in ("ubicacion", "direccion", "monterrey", "nuevo leon", "estamos en")
        ):
            answered.append(intent)
        elif intent == "buro" and "buro" in normalized:
            answered.append(intent)
        elif intent == "aprobacion" and any(
            token in normalized for token in ("aprobacion", "aprobado", "autoriza", "prometer")
        ):
            answered.append(intent)
        elif intent == "liquidacion" and any(
            token in normalized for token in ("liquid", "pagar antes", "adelantar", "penalizacion")
        ):
            answered.append(intent)
        elif intent == "precio" and any(
            token in normalized for token in ("$", "enganche", "pago quincenal", "contado", "precio")
        ):
            answered.append(intent)
        elif intent == "documentos" and any(
            token in normalized
            for token in (
                "ine",
                "document",
                "papel",
                "requisito",
                "estado de cuenta",
                "estados de cuenta",
                "cargado",
                "expediente",
                "comprobante",
            )
        ):
            answered.append(intent)
        elif intent == "humano" and any(token in normalized for token in ("asesor", "humano")):
            answered.append(intent)
    return _dedupe(answered)


def _has_internal_language(text: str) -> bool:
    ascii_text = _ascii(text)
    return bool(INTERNAL_LANGUAGE_RE.search(ascii_text) or STATE_SLOT_LANGUAGE_RE.search(ascii_text))


def _catalog_error_for_non_catalog_question(text: str, questions: list[str]) -> bool:
    if not questions:
        return False
    return bool(CATALOG_ERROR_RE.search(_ascii(text)))


def _looks_like_default_income_menu(text: str) -> bool:
    return bool(INCOME_MENU_RE.search(_ascii(text)))


def _document_loop_risk(text: str, request: AgentFinalResponseRequest) -> bool:
    if not _looks_like_document_request_text(text):
        return False
    questions = _question_intents(request.user_message)
    if request.final_action == "quote":
        return "documentos" not in questions
    if _has_explicit_document_resume(request):
        return False
    if "documentos" in questions:
        return False
    previous_bot = [
        previous
        for role, previous in request.history[-6:]
        if str(role).lower() in {"outbound", "bot", "assistant"}
    ]
    repeated = any(DOC_REQUEST_RE.search(str(previous or "")) for previous in previous_bot)
    if repeated:
        return True
    if request.final_action == "quote":
        return True
    if questions:
        return True
    return False


def _looks_like_document_request_text(text: str) -> bool:
    normalized = _normalize(text)
    if any(token in normalized for token in ("ine", "document", "papel")):
        return True
    if "comprobante de domicilio" in normalized:
        return True
    if "estado de cuenta" in normalized or "estados de cuenta" in normalized:
        return True
    if "requisito" in normalized:
        return True
    return False


def _render_missing_documents_from_payload(
    payload: dict[str, Any],
    request: AgentFinalResponseRequest,
) -> str:
    requirements = payload.get("requirements")
    if not isinstance(requirements, dict):
        return ""
    missing = requirements.get("missing")
    if not isinstance(missing, list) or not missing:
        return ""
    labels: list[str] = []
    for item in missing:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("key") or "").strip()
        else:
            label = str(item or "").strip()
        if label:
            labels.append(label)
    labels = _dedupe(labels)
    if not labels:
        return ""

    plan = (
        requirements.get("selection_label")
        or requirements.get("selection_key")
        or _state_value(request.state, "Plan_Credito")
        or _state_value(request.state, "CREDITO")
    )
    down = _state_value(request.state, "ENGANCHE")
    prefix = "Perfecto"
    if plan and down:
        prefix = f"Perfecto, para {plan} con {down} de enganche"
    elif plan:
        prefix = f"Perfecto, para {plan}"
    docs = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + f" y {labels[-1]}"
    return f"{prefix}, lo que falta para avanzar es: {docs}."


def _is_safe_state_clarification(text: str, request: AgentFinalResponseRequest) -> bool:
    if request.final_action != "ask_clarification":
        return False
    payload = request.tool_results if isinstance(request.tool_results, dict) else {}
    suggested = str(payload.get("suggested_clarification") or "").strip()
    if suggested and _normalize(suggested) == _normalize(text):
        return True
    return bool(
        "quieres corregirlo" in _normalize(text)
        and "como" in _normalize(text)
        and "?" in str(text or "")
    )


def _has_explicit_document_resume(request: AgentFinalResponseRequest) -> bool:
    frame = request.response_frame
    if frame is not None and frame.pending_flow is not None:
        pending_type = str(getattr(frame.pending_flow, "type", "") or "").strip()
        if pending_type == "ask_missing_documents":
            return True
    payload = request.tool_results if isinstance(request.tool_results, dict) else {}
    pending = payload.get("resume_pending_action")
    if isinstance(pending, dict) and pending.get("type") == "ask_missing_documents":
        return True
    requirements = payload.get("requirements")
    return isinstance(requirements, dict) and bool(requirements.get("missing"))


def _render_quote(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return ""
    name = payload.get("name")
    cash = payload.get("cash_price_mxn") or payload.get("list_price_mxn")
    if not name or not cash:
        return ""
    parts = [f"La {name} de contado esta en ${int(cash):,}."]
    payment_options = payload.get("payment_options")
    option: dict[str, Any] = {}
    if isinstance(payment_options, dict):
        requested = str(payload.get("requested_plan_code") or "").strip()
        if requested and isinstance(payment_options.get(requested), dict):
            option = payment_options[requested]
        else:
            option = next(
                (item for item in payment_options.values() if isinstance(item, dict)),
                {},
            )
    elif isinstance(payment_options, list) and payment_options:
        option = payment_options[0] if isinstance(payment_options[0], dict) else {}
    if option:
        down = option.get("down_payment_mxn")
        payment = (
            option.get("payment_mxn")
            or option.get("biweekly_payment_mxn")
            or option.get("installment_mxn")
        )
        term = (
            option.get("term")
            or option.get("term_label")
            or option.get("term_quincenas")
            or option.get("term_count")
        )
        details = []
        if down:
            details.append(f"Enganche: ${int(down):,}.")
        if payment:
            details.append(f"Pago quincenal: ${int(payment):,}.")
        if term:
            details.append(f"Plazo: {_term_text(term)}.")
        if details:
            requested = str(payload.get("requested_plan_code") or "").strip()
            plan_label = f" con tu plan del {requested}" if requested else ""
            parts.append(f"A credito{plan_label}:")
            parts.extend(details)
    return "\n".join(parts)


def _term_text(term: Any) -> str:
    if isinstance(term, int):
        return f"{term} quincenas"
    text = str(term).strip()
    if text.isdigit():
        return f"{text} quincenas"
    return text


def _sanitize(text: str) -> str:
    cleaned = str(text or "").strip()
    if any(marker in cleaned for marker in ("Ã", "Â", "â")):
        replacements = {
            "SÃ­": "Si",
            "sÃ­": "si",
            "crÃ©dito": "credito",
            "CrÃ©dito": "Credito",
            "penalizaciÃ³n": "penalizacion",
            "PenalizaciÃ³n": "Penalizacion",
            "tambiÃ©n": "tambien",
            "TambiÃ©n": "Tambien",
            "automÃ¡tica": "automatica",
            "AutomÃ¡tica": "Automatica",
            "â€“": "-",
            "Â¿": "",
        }
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\bMOTO\b", "modelo", cleaned)
    cleaned = re.sub(r"\bCREDITO\b", "plan", cleaned)
    cleaned = re.sub(r"\bENGANCHE\b", "enganche", cleaned)
    cleaned = re.sub(r"\bFILTRO\b", "validacion", cleaned)
    cleaned = re.sub(r"cat[aá]logo\s+activo", "catalogo", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r" *\n+ *", "\n", cleaned).strip()
    return cleaned


def _normalize(value: Any) -> str:
    return _ascii(str(value or "")).casefold().strip()


def _state_value(state: dict[str, Any], key: str) -> Any:
    value = state.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _is_document_question(normalized: str) -> bool:
    if "precio" in normalized or "cuanto sale" in normalized or "cuanto queda" in normalized:
        return False
    if "no mando" in normalized and ("precio" in normalized or "entender" in normalized):
        return False
    if any(
        token in normalized
        for token in (
            "que documentos",
            "documentos siguen",
            "que papeles",
            "papeles siguen",
            "que requisitos",
            "requisitos ocupo",
            "que mando",
            "mando primero",
            "que te mando",
            "te mando primero",
            "solo confirmame cuales",
            "estados de cuenta",
            "estado de cuenta",
            "ya te mande",
            "ya mande",
            "no me aparece",
            "si llego",
            "se mando",
            "te llego",
        )
    ):
        return True
    return "ine" in normalized and any(
        token in normalized for token in ("mando", "mande", "primero", "ocupo", "falta")
    )


def _is_document_status_question(normalized: str) -> bool:
    return any(
        token in normalized
        for token in (
            "ya te mande",
            "ya mande",
            "no me aparece",
            "si llego",
            "llego?",
            "se mando",
            "se envio",
            "te llego",
        )
    )


def _previous_bot_requested_documents(request: AgentFinalResponseRequest) -> bool:
    return any(
        DOC_REQUEST_RE.search(str(previous or ""))
        for role, previous in request.history[-6:]
        if str(role).lower() in {"outbound", "bot", "assistant"}
    )


def _ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = _normalize(cleaned)
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


__all__ = [
    "AgentFinalResponse",
    "AgentFinalResponseRequest",
    "FinalizedAgentResponse",
    "build_agent_final_response",
    "composer_output_with_agent_final_response",
    "finalize_agent_visible_response",
]

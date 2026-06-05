"""Legacy response frame used by ConversationRunner fallback.

For AgentRuntime v2 tenants, TurnOutput.final_message is the visible-copy
authority and this frame must not be used to generate outbound copy.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atendia.runner.document_language import (
    humanize_document_labels,
    join_humanized_documents,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


ResponseStrategy = Literal[
    "answer_only",
    "answer_and_resume_flow",
    "ask_missing_field",
    "quote",
    "quote_cash",
    "quote_and_answer",
    "answer_cash_price",
    "quote_and_resume",
    "clarify",
    "soft_close",
    "handoff",
    "operational_safe_reply",
    "document_request",
    "document_feedback",
]


class ResponseFrameValidatedAnswer(_StrictModel):
    text: str
    source: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    must_include: bool = True


class ResponseFramePendingFlow(_StrictModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    human_name: str | None = None
    reason: str | None = None


class ResponseFrameComposerInstructions(_StrictModel):
    style: str = "warm_whatsapp_advisor"
    must_answer_current_question_first: bool = True
    must_resume_pending_flow: bool = True
    avoid_exact_repeat: bool = False
    do_not_expose_internal_fields: bool = True
    do_not_promise_approval: bool = True
    do_not_invent: bool = True
    max_whatsapp_length: int = 320


class ResponseFrameAntiRepetition(_StrictModel):
    last_similar_bot_message: str | None = None
    repeated_prompt_count: int = 0
    document_prompt_count: int = 0
    customer_repeated_question: bool = False
    avoid_same_opening: bool = False
    avoid_same_document_prompt: bool = False
    last_document_prompt: str | None = None
    last_answered_intents: list[str] = Field(default_factory=list)
    last_customer_question: str | None = None


class ResponseFrameTrace(_StrictModel):
    response_frame_source: str
    response_frame_reason: str
    frame_valid: bool
    frame_rejected_reason: str | None = None
    next_real_step: dict[str, Any] | None = None
    next_real_step_reason: str | None = None
    active_purchase_mode: str | None = None
    cash_credit_context_switch: str | None = None
    cash_mode_blocked_credit_flow_reason: str | None = None
    quote_mode: str | None = None
    quote_memory_source: str | None = None
    model_change_detected: bool | None = None
    previous_model: str | None = None
    new_model: str | None = None
    active_model: str | None = None
    last_quote_model: str | None = None
    model_change_source: str | None = None
    dual_income_resolution_required: bool | None = None
    selected_income_source: str | None = None
    selected_income_source_confidence: float | None = None
    documents_blocked_by_dual_income: bool | None = None
    quote_blocked_by_dual_income: bool | None = None
    pending_flow_forced_to_income_disambiguation: bool | None = None
    pending_flow_original: dict[str, Any] | None = None
    pending_flow_recomputed: dict[str, Any] | None = None
    pending_flow_recompute_reason: str | None = None
    resume_missing_blocked_reason: str | None = None
    soft_close_blocked_reason: str | None = None
    current_question_detected: bool | None = None
    current_question_type: str | None = None
    current_question_answered: bool | None = None
    current_question_unresolved_reason: str | None = None
    current_question_guard_applied: bool | None = None
    current_question_guard_reason: str | None = None
    outbound_blocked_missing_answer: bool | None = None
    regenerated_response_frame_reason: str | None = None


class ResponseFrame(_StrictModel):
    current_customer_message: str
    recent_history: list[str] = Field(default_factory=list)
    last_bot_message: str | None = None
    current_intents: list[str] = Field(default_factory=list)
    current_questions: list[dict[str, Any]] = Field(default_factory=list)
    required_answer_targets: list[str] = Field(default_factory=list)
    answered_intents: list[str] = Field(default_factory=list)
    unresolved_intents: list[str] = Field(default_factory=list)
    missing_answer_targets: list[str] = Field(default_factory=list)
    known_customer_state: dict[str, Any] = Field(default_factory=dict)
    validated_answers: dict[str, ResponseFrameValidatedAnswer] = Field(default_factory=dict)
    pending_flow: ResponseFramePendingFlow | None = None
    response_strategy: ResponseStrategy
    composer_instructions: ResponseFrameComposerInstructions = Field(
        default_factory=ResponseFrameComposerInstructions
    )
    guardrails: list[str] = Field(default_factory=list)
    anti_repetition: ResponseFrameAntiRepetition = Field(
        default_factory=ResponseFrameAntiRepetition
    )
    trace: ResponseFrameTrace


def build_response_frame(
    *,
    user_message: str,
    recent_history: list[tuple[str, str]],
    action: str,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
    extracted_data: dict[str, Any],
    current_stage: str,
    guardrails: list[str],
    conversation_summary: str | None = None,
) -> ResponseFrame:
    rendered_history = _render_recent_history(recent_history)
    last_bot_message = _last_message_for_role(recent_history, "outbound")
    answered_intents = _answered_intents(action_payload)
    current_intents = _current_intents(
        action=action,
        action_payload=action_payload,
        decision_payload=decision_payload,
        answered_intents=answered_intents,
        user_message=user_message,
    )
    known_customer_state = _known_customer_state(
        extracted_data=extracted_data,
        action=action,
        action_payload=action_payload,
        current_stage=current_stage,
        conversation_summary=conversation_summary,
        recent_history=recent_history,
    )
    pending_flow_original = _pending_flow(
        action=action,
        action_payload=action_payload,
        decision_payload=decision_payload,
    )
    next_step, next_step_reason = compute_next_real_step(
        state=known_customer_state,
        response_frame=None,
        final_action_payload=action_payload,
        action=action,
    )
    pending_flow, pending_trace = _recompute_pending_flow(
        original=pending_flow_original,
        next_step=next_step,
        next_step_reason=next_step_reason,
        action=action,
        user_message=user_message,
        known_customer_state=known_customer_state,
    )
    validated_answers = _validated_answers(
        action=action,
        action_payload=action_payload,
        decision_payload=decision_payload,
    )
    current_questions = _current_questions(
        user_message=user_message,
        action=action,
        action_payload=action_payload,
        current_intents=current_intents,
    )
    required_answer_targets = _required_answer_targets(current_questions)
    answered_targets = _answered_answer_targets(
        action=action,
        action_payload=action_payload,
        answered_intents=answered_intents,
        validated_answers=validated_answers,
    )
    missing_answer_targets = [
        target for target in required_answer_targets if target not in answered_targets
    ]
    unresolved_intents = _unresolved_intents(
        current_intents=current_intents,
        answered_intents=answered_intents,
        validated_answers=validated_answers,
        missing_answer_targets=missing_answer_targets,
    )
    anti_repetition = _anti_repetition(
        user_message=user_message,
        recent_history=recent_history,
        last_bot_message=last_bot_message,
        answered_intents=answered_intents,
        pending_flow=pending_flow,
    )
    response_strategy = _response_strategy(
        action=action,
        current_intents=current_intents,
        current_questions=current_questions,
        validated_answers=validated_answers,
        pending_flow=pending_flow,
        missing_answer_targets=missing_answer_targets,
    )
    frame_valid = bool(str(user_message or "").strip()) and bool(response_strategy)
    rejected_reason = None if frame_valid else "missing_current_customer_message"
    return ResponseFrame(
        current_customer_message=str(user_message or "").strip(),
        recent_history=rendered_history,
        last_bot_message=last_bot_message,
        current_intents=current_intents,
        current_questions=current_questions,
        required_answer_targets=required_answer_targets,
        answered_intents=answered_intents,
        unresolved_intents=unresolved_intents,
        missing_answer_targets=missing_answer_targets,
        known_customer_state=known_customer_state,
        validated_answers=validated_answers,
        pending_flow=pending_flow,
        response_strategy=response_strategy,
        composer_instructions=ResponseFrameComposerInstructions(
            must_resume_pending_flow=pending_flow is not None,
            avoid_exact_repeat=anti_repetition.repeated_prompt_count > 0
            or anti_repetition.customer_repeated_question
            or anti_repetition.avoid_same_document_prompt,
        ),
        guardrails=[str(item).strip() for item in guardrails if str(item).strip()],
        anti_repetition=anti_repetition,
        trace=ResponseFrameTrace(
            response_frame_source="runner_builder",
            response_frame_reason="built_from_action_payload_history_and_state",
            frame_valid=frame_valid,
            frame_rejected_reason=rejected_reason,
            next_real_step=_pending_to_dict(next_step),
            next_real_step_reason=next_step_reason,
            active_purchase_mode=str(known_customer_state.get("active_purchase_mode") or "") or None,
            cash_credit_context_switch=str(action_payload.get("cash_credit_context_switch") or "") or None,
            cash_mode_blocked_credit_flow_reason=pending_trace.get("cash_mode_blocked_credit_flow_reason"),
            quote_mode=str(known_customer_state.get("quote_mode") or "") or None,
            quote_memory_source=str(action_payload.get("quote_memory_source") or "") or None,
            model_change_detected=(
                bool(action_payload.get("model_change_detected"))
                if "model_change_detected" in action_payload
                else None
            ),
            previous_model=str(action_payload.get("previous_model") or "") or None,
            new_model=str(action_payload.get("new_model") or "") or None,
            active_model=str(action_payload.get("active_model") or action_payload.get("new_model") or "") or None,
            last_quote_model=str(action_payload.get("last_quote_model") or "") or None,
            model_change_source=str(action_payload.get("model_change_source") or "") or None,
            dual_income_resolution_required=(
                bool(action_payload.get("dual_income_resolution_required"))
                if "dual_income_resolution_required" in action_payload
                else None
            ),
            selected_income_source=str(action_payload.get("selected_income_source") or "") or None,
            selected_income_source_confidence=(
                float(action_payload.get("selected_income_source_confidence"))
                if action_payload.get("selected_income_source_confidence") not in (None, "")
                else None
            ),
            documents_blocked_by_dual_income=(
                bool(action_payload.get("documents_blocked_by_dual_income"))
                if "documents_blocked_by_dual_income" in action_payload
                else None
            ),
            quote_blocked_by_dual_income=(
                bool(action_payload.get("quote_blocked_by_dual_income"))
                if "quote_blocked_by_dual_income" in action_payload
                else None
            ),
            pending_flow_forced_to_income_disambiguation=(
                bool(action_payload.get("pending_flow_forced_to_income_disambiguation"))
                if "pending_flow_forced_to_income_disambiguation" in action_payload
                else None
            ),
            pending_flow_original=_pending_to_dict(pending_flow_original),
            pending_flow_recomputed=_pending_to_dict(pending_flow),
            pending_flow_recompute_reason=pending_trace.get("pending_flow_recompute_reason"),
            resume_missing_blocked_reason=pending_trace.get("resume_missing_blocked_reason"),
            soft_close_blocked_reason=(
                pending_trace.get("soft_close_blocked_reason")
                if action == "soft_close"
                else None
            ),
            current_question_detected=bool(current_questions),
            current_question_type=required_answer_targets[0] if required_answer_targets else None,
            current_question_answered=bool(current_questions) and not missing_answer_targets,
            current_question_unresolved_reason=(
                _missing_answer_reason(missing_answer_targets[0])
                if missing_answer_targets
                else None
            ),
            current_question_guard_applied=bool(missing_answer_targets),
            current_question_guard_reason=(
                "missing_required_answer_target" if missing_answer_targets else None
            ),
            outbound_blocked_missing_answer=bool(missing_answer_targets),
            regenerated_response_frame_reason=(
                "current_question_answer_guard" if missing_answer_targets else None
            ),
        ),
    )


def build_minimal_response_frame(
    *,
    user_message: str,
    answer_text: str = "",
    response_strategy: ResponseStrategy = "answer_only",
    guardrails: list[str] | None = None,
    response_frame_source: str = "runner_minimal_builder",
    response_frame_reason: str = "minimal_fallback_frame",
    answer_source: str = "fallback",
    current_intents: list[str] | None = None,
) -> ResponseFrame:
    clean_message = str(user_message or "").strip()
    clean_answer = str(answer_text or "").strip()
    answers: dict[str, ResponseFrameValidatedAnswer] = {}
    answered_intents: list[str] = []
    unresolved_intents: list[str] = []
    if clean_answer:
        answers["primary"] = ResponseFrameValidatedAnswer(
            text=clean_answer,
            source=answer_source,
            confidence=1.0,
            must_include=True,
        )
        answered_intents = ["primary"]
    if current_intents is None:
        current_intents = ["handoff"] if response_strategy == "handoff" else ["customer_message"]
    if not answers and response_strategy not in {"handoff", "clarify", "ask_missing_field"}:
        unresolved_intents = list(current_intents)
    frame_valid = bool(clean_message) and bool(response_strategy)
    return ResponseFrame(
        current_customer_message=clean_message,
        recent_history=[],
        last_bot_message=None,
        current_intents=list(current_intents),
        current_questions=[],
        required_answer_targets=[],
        answered_intents=answered_intents,
        unresolved_intents=unresolved_intents,
        missing_answer_targets=[],
        known_customer_state={},
        validated_answers=answers,
        pending_flow=None,
        response_strategy=response_strategy,
        composer_instructions=ResponseFrameComposerInstructions(
            must_resume_pending_flow=False,
            avoid_exact_repeat=False,
        ),
        guardrails=[str(item).strip() for item in list(guardrails or []) if str(item).strip()],
        anti_repetition=ResponseFrameAntiRepetition(),
        trace=ResponseFrameTrace(
            response_frame_source=response_frame_source,
            response_frame_reason=response_frame_reason,
            frame_valid=frame_valid,
            frame_rejected_reason=None if frame_valid else "missing_current_customer_message",
        ),
    )


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


def _response_frame_resume_text(response_frame: ResponseFrame) -> str:
    pending = response_frame.pending_flow
    if pending is None:
        return ""
    payload = pending.payload if isinstance(pending.payload, dict) else {}
    if pending.type == "ask_missing_documents":
        missing = humanize_document_labels(payload.get("missing") or [])
        if missing:
            if response_frame.anti_repetition.avoid_same_document_prompt:
                if response_frame.anti_repetition.document_prompt_count % 2 == 0:
                    return (
                        "Cuando quieras avanzar, lo primero seria "
                        + join_humanized_documents(missing)
                        + "."
                    )
                return (
                    "El siguiente paso sigue siendo enviarnos "
                    + join_humanized_documents(missing)
                    + "."
                )
            return "Y para seguir, todavia faltaria: " + join_humanized_documents(missing) + "."
        return "Y para seguir, necesito los documentos pendientes."
    if pending.type == "ask_field":
        field_name = str(payload.get("field") or "").strip().upper()
        return _response_frame_pending_field_prompt(
            field_name=field_name,
            human_name=pending.human_name,
            prefix="Y para seguir,",
        )
    if pending.type == "quote":
        return "Y para seguir, te preparo la cotizacion."
    if pending.human_name:
        return f"Y para seguir, continuamos con {pending.human_name}."
    return ""


def render_response_frame_fallback_message(response_frame: ResponseFrame) -> str:
    missing_answers = [
        _missing_answer_text(target)
        for target in response_frame.missing_answer_targets
        if _missing_answer_text(target)
    ]
    required_targets = set(response_frame.required_answer_targets)
    answers = [
        answer.text.strip()
        for key, answer in response_frame.validated_answers.items()
        if answer.must_include
        and answer.text.strip()
        and (
            not response_frame.missing_answer_targets
            or key in required_targets
            or answer.source != "decision_payload"
        )
    ]
    answer_text = "\n\n".join(dict.fromkeys([*missing_answers, *answers]))
    resume_text = _response_frame_resume_text(response_frame).strip()
    prefix = ""
    if (
        response_frame.anti_repetition.avoid_same_opening
        or response_frame.anti_repetition.avoid_same_document_prompt
    ):
        variants = ("Sobre eso, ", "Te confirmo: ", "Para que quede claro, ")
        index = response_frame.anti_repetition.document_prompt_count % len(variants)
        prefix = variants[index]
    strategy = response_frame.response_strategy
    if strategy in {"answer_and_resume_flow", "quote_and_resume", "quote_and_answer"}:
        lead = f"{prefix}{answer_text}".strip(", ") if answer_text else ""
        return "\n\n".join(item for item in [lead, resume_text] if item).strip()
    if strategy == "operational_safe_reply":
        operational_prefix = prefix or "Sobre eso, "
        return f"{operational_prefix}{answer_text}".strip(", ").strip()
    if strategy in {"answer_only", "quote", "quote_cash", "answer_cash_price", "handoff"}:
        return f"{prefix}{answer_text}".strip(", ").strip()
    if strategy == "ask_missing_field":
        return resume_text or f"{prefix}{answer_text}".strip(", ").strip()
    if strategy in {"document_request", "document_feedback"}:
        lead = f"{prefix}{answer_text}".strip(", ").strip()
        return "\n\n".join(item for item in [lead, resume_text] if item).strip()
    if strategy == "soft_close":
        return answer_text or "Claro, aqui sigo para ayudarte."
    if strategy == "clarify":
        return answer_text or "Me confirmas a que te refieres para seguir?"
    return "\n\n".join(item for item in [answer_text, resume_text] if item).strip()


def _missing_answer_text(target: str) -> str:
    if target == "approval":
        return "No puedo prometer aprobacion; se revisa con el expediente completo."
    if target == "timing":
        return "El tiempo depende de la revision del expediente y de que la informacion este completa."
    if target == "human_handoff":
        return "Si quieres hablar con una persona, lo dejo claro para que un asesor lo revise contigo."
    if target == "payoff":
        return "Sobre liquidar antes, lo revisamos con el plan vigente para no darte un dato incorrecto."
    if target == "documents":
        return "Sobre los documentos, lo primero es mandar INE por ambos lados y comprobante de domicilio reciente si aplica a tu plan."
    if target == "requirements":
        return "Los requisitos exactos dependen del plan y se revisan con tu expediente; no quiero inventarte uno."
    if target == "income_clarification":
        return "Para decirte el plan correcto necesito confirmar como compruebas ese ingreso."
    if target == "catalog_request":
        return "Para orientarte bien necesito ubicar el modelo o categoria que quieres revisar."
    if target == "buro":
        return "Si, se revisa buro dentro del expediente."
    if target == "ubicacion":
        return "Estamos en Monterrey, Nuevo Leon."
    if target in {"credit_quote_request", "cash_price_request", "quote_request"}:
        return "Para darte precio correcto necesito tener modelo y plan confirmados."
    return "Sobre eso, necesito revisarlo o que me confirmes un poco mas para no inventarte informacion."


def _render_recent_history(history: list[tuple[str, str]]) -> list[str]:
    rendered: list[str] = []
    for role, text in history[-8:]:
        clean = str(text or "").strip()
        if clean:
            rendered.append(f"{role}: {clean}")
    return rendered


def _answered_intents(action_payload: dict[str, Any]) -> list[str]:
    raw = action_payload.get("answered_intents")
    if not isinstance(raw, list):
        raw = []
    values = [str(item).strip() for item in raw if str(item).strip()]
    return _dedupe(values)


def _current_intents(
    *,
    action: str,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
    answered_intents: list[str],
    user_message: str,
) -> list[str]:
    values = list(answered_intents)
    topic = str(action_payload.get("topic") or "").strip()
    if topic:
        values.append(topic)
    answers = action_payload.get("answers") if isinstance(action_payload.get("answers"), list) else []
    for item in answers:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        if topic:
            values.append(topic)
    suggested = str(decision_payload.get("suggested_clarification") or "").strip()
    if suggested:
        values.append("clarification")
    request_type = str(action_payload.get("request_type") or "").strip()
    if action_payload.get("model_change_detected"):
        values.append("model_change")
    if action == "search_catalog" and request_type == "catalog_browse":
        values.append("catalog_request")
    if action == "resolve_credit_plan":
        values.append("credit_plan_resolution")
    if action == "classify_document" and request_type in {
        "ask_missing_document",
        "process_document",
    }:
        values.append("document_follow_up")
    if not values and _looks_like_question(user_message):
        values.append(
            {
                "lookup_faq": "customer_question",
                "quote": "quote_request",
                "search_catalog": "catalog_request",
                "classify_document": "document_follow_up",
            }.get(action, "customer_message")
        )
    if str(action_payload.get("active_purchase_mode") or "").strip() == "cash":
        values.append("cash_price_request")
    if str(action_payload.get("active_purchase_mode") or "").strip() == "credit":
        values.append("credit_quote_request")
    return _dedupe(values)


def _current_questions(
    *,
    user_message: str,
    action: str,
    action_payload: dict[str, Any],
    current_intents: list[str],
) -> list[dict[str, Any]]:
    normalized = _normalize(user_message)
    if not normalized:
        return []
    targets: list[tuple[str, str]] = []
    if _contains_any(normalized, "hablar con", "persona", "humano", "asesor"):
        targets.append(("human_handoff", "explicit_human_request"))
    if _contains_any(normalized, "aprueban", "aprobacion", "autorizan", "seguro"):
        targets.append(("approval", "approval_or_guarantee_question"))
    if _contains_any(normalized, "cuanto tarda", "cuando", "hoy si o no", "tiempo"):
        targets.append(("timing", "timing_question"))
    if _contains_any(normalized, "buro", "buró", "historial"):
        targets.append(("buro", "buro_question"))
    if _contains_any(normalized, "donde", "ubicacion", "direccion"):
        targets.append(("ubicacion", "location_question"))
    if _contains_any(normalized, "liquid", "adelantar", "penalizacion", "anticip"):
        targets.append(("payoff", "payoff_question"))
    if _contains_any(normalized, "estado de cuenta", "estados de cuenta"):
        targets.append(("requirements", "bank_statement_question"))
    if _contains_any(normalized, "requisito", "requisitos", "papel", "papeles"):
        targets.append(("requirements", "requirements_question"))
    if _contains_any(
        normalized,
        "que mando primero",
        "cual va primero",
        "mando primero",
        "confirmame cuales",
        "te mando",
        "la ine",
        "comprobante puede",
        "comprobante esta",
        "estados de cuenta",
        "estado de cuenta",
    ):
        targets.append(("documents", "document_order_question"))
    if (
        _contains_any(normalized, "enganche", "quincenal", "contado", "precio", "sale")
        or ("cuanto" in normalized and "cuanto tarda" not in normalized)
    ):
        mode = str(action_payload.get("active_purchase_mode") or action_payload.get("quote_mode") or "")
        targets.append(("cash_price_request" if mode == "cash" else "credit_quote_request", "price_question"))
    if _contains_any(normalized, "como recibes", "como compruebas", "cual me conviene", "no es nomina", "dos trabajos"):
        targets.append(("income_clarification", "income_question"))
    if _contains_any(
        normalized,
        "que motos",
        "que motonetas",
        "que modelos",
        "cual custom",
        "otra mas barata",
        "otra opcion",
        "opcion mas barata",
        "tienes otra",
    ):
        targets.append(("catalog_request", "model_or_catalog_question"))
    if not targets and _looks_like_question(user_message):
        targets.append((
            current_intents[0] if current_intents else "customer_message",
            "explicit_or_consultative_message",
        ))
    questions: list[dict[str, Any]] = []
    for target, reason in targets:
        questions.append(
            {
                "target": target,
                "type": target,
                "text": str(user_message or "").strip(),
                "reason": reason,
            }
        )
    return _dedupe_questions(questions)


def _required_answer_targets(current_questions: list[dict[str, Any]]) -> list[str]:
    return _dedupe(
        str(item.get("target") or "").strip()
        for item in current_questions
        if str(item.get("target") or "").strip()
    )


def _answered_answer_targets(
    *,
    action: str,
    action_payload: dict[str, Any],
    answered_intents: list[str],
    validated_answers: dict[str, ResponseFrameValidatedAnswer],
) -> set[str]:
    answered = set(answered_intents) | set(validated_answers.keys())
    if action == "lookup_faq":
        topic = str(action_payload.get("topic") or "").strip()
        if topic:
            answered.add(topic)
        for item in action_payload.get("answers") if isinstance(action_payload.get("answers"), list) else []:
            if isinstance(item, dict) and str(item.get("topic") or "").strip():
                answered.add(str(item.get("topic")).strip())
    if action == "quote" and action_payload.get("status") == "ok":
        mode = str(action_payload.get("active_purchase_mode") or action_payload.get("quote_mode") or "")
        answered.add("cash_price_request" if mode == "cash" else "credit_quote_request")
        answered.add("quote_request")
        answered.add("requirements")
    if action == "search_catalog" and action_payload.get("status") == "ok":
        answered.add("catalog_request")
    if action == "ask_clarification" and "clarification" in validated_answers:
        answered.add("catalog_request")
        answered.add("customer_message")
    if action == "resolve_credit_plan":
        answered.add("income_clarification")
        answered.add("credit_plan_resolution")
    if action in {"classify_document", "ask_missing_document"} and validated_answers:
        answered.add("documents")
        answered.add("requirements")
        answered.add("document_follow_up")
    normalized_answers = _normalize(" ".join(answer.text for answer in validated_answers.values()))
    if "buro" in normalized_answers:
        answered.add("buro")
    if "monterrey" in normalized_answers or "ubicacion" in normalized_answers:
        answered.add("ubicacion")
    if "liquid" in normalized_answers or "penalizacion" in normalized_answers:
        answered.add("payoff")
    if "revision" in normalized_answers and ("tiempo" in normalized_answers or "aprob" in normalized_answers):
        answered.add("timing")
        answered.add("approval")
    if "document" in normalized_answers or "ine" in normalized_answers:
        answered.add("documents")
        answered.add("requirements")
    return answered


def _missing_answer_reason(target: str) -> str:
    if target in {"approval", "timing"}:
        return "requires_human_or_process_confirmation"
    if target == "human_handoff":
        return "handoff_request_must_be_acknowledged"
    if target in {"documents", "requirements"}:
        return "document_requirement_answer_missing"
    if target in {"cash_price_request", "credit_quote_request"}:
        return "quote_answer_missing"
    return "no_validated_answer_for_current_question"


def _contains_any(text: str, *tokens: str) -> bool:
    return any(token in text for token in tokens)


def _dedupe_questions(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = str(value.get("target") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def compute_next_real_step(
    state: dict[str, Any],
    response_frame: ResponseFrame | None = None,
    final_action_payload: dict[str, Any] | None = None,
    *,
    action: str | None = None,
) -> tuple[ResponseFramePendingFlow | None, str | None]:
    """Return the next customer-visible step from validated state."""

    del response_frame
    payload = final_action_payload if isinstance(final_action_payload, dict) else {}
    action_name = str(action or "").strip()
    moto = _string_state_value(state, "moto", "MOTO")
    credit = _string_state_value(state, "credito", "CREDITO")
    down_payment = _string_state_value(state, "enganche", "ENGANCHE", "plan", "PLAN")
    seniority = _string_state_value(state, "antiguedad_laboral", "filtro", "FILTRO")
    quote_valid = bool(state.get("quote_valid"))
    active_purchase_mode = str(state.get("active_purchase_mode") or "").strip()

    if active_purchase_mode == "cash":
        if not moto:
            return _ask_field_step("MOTO", reason="cash_missing_model"), "cash_missing_model"
        return None, None

    policy_trace = payload.get("policy_trace") if isinstance(payload.get("policy_trace"), dict) else {}
    income_ambiguous = bool(
        policy_trace.get("income_ambiguity")
        or policy_trace.get("needs_income_disambiguation")
        or policy_trace.get("dual_income_detected")
        or policy_trace.get("payroll_ambiguous")
        or policy_trace.get("deposit_ambiguous")
    )
    if income_ambiguous:
        return ResponseFramePendingFlow(
            type="ask_field",
            payload={"type": "ask_income_disambiguation", "field": "CREDITO"},
            human_name="aclaracion de ingresos",
            reason="income_ambiguity",
        ), "income_ambiguity"

    if not moto:
        return _ask_field_step("MOTO", reason="missing_model"), "missing_model"
    if not credit or not down_payment:
        return _ask_field_step("CREDITO", reason="missing_credit_plan"), "missing_credit_plan"
    if _credit_plan_needs_seniority(credit) and not seniority:
        return _ask_field_step("FILTRO", reason="missing_seniority"), "missing_seniority"
    if not quote_valid and action_name != "quote":
        return ResponseFramePendingFlow(
            type="quote",
            payload={"type": "quote"},
            human_name="cotizacion",
            reason="quote_missing",
        ), "quote_missing"

    requirements = payload.get("requirements")
    if isinstance(requirements, dict) and requirements.get("missing"):
        missing = requirements.get("missing") or []
        return ResponseFramePendingFlow(
            type="ask_missing_documents",
            payload={"type": "ask_missing_documents", "missing": missing},
            human_name="documentos pendientes",
            reason="quote_valid_documents_pending",
        ), "quote_valid_documents_pending"
    return None, None


def _ask_field_step(field_name: str, *, reason: str) -> ResponseFramePendingFlow:
    payload = {"type": "ask_field", "field": field_name}
    return ResponseFramePendingFlow(
        type="ask_field",
        payload=payload,
        human_name=_field_human_name(field_name),
        reason=reason,
    )


def _pending_to_dict(pending: ResponseFramePendingFlow | None) -> dict[str, Any] | None:
    if pending is None:
        return None
    return {
        "type": pending.type,
        "payload": dict(pending.payload),
        "human_name": pending.human_name,
        "reason": pending.reason,
    }


def _pending_key(pending: ResponseFramePendingFlow | None) -> tuple[str, str]:
    if pending is None:
        return ("", "")
    payload = pending.payload if isinstance(pending.payload, dict) else {}
    if pending.type == "ask_field":
        return (pending.type, str(payload.get("field") or "").strip().upper())
    return (pending.type, "")


def _recompute_pending_flow(
    *,
    original: ResponseFramePendingFlow | None,
    next_step: ResponseFramePendingFlow | None,
    next_step_reason: str | None,
    action: str,
    user_message: str,
    known_customer_state: dict[str, Any],
) -> tuple[ResponseFramePendingFlow | None, dict[str, str]]:
    trace: dict[str, str] = {}
    has_commercial_state = any(
        _string_state_value(known_customer_state, key)
        for key in ("moto", "credito", "enganche", "plan", "filtro", "antiguedad_laboral")
    )
    if str(known_customer_state.get("active_purchase_mode") or "").strip() == "cash":
        if original is not None and original.type in {"ask_missing_documents", "ask_field"}:
            trace["cash_mode_blocked_credit_flow_reason"] = (
                next_step_reason or "cash_mode_blocks_credit_flow"
            )
        return None, trace
    if next_step is None:
        return original, trace
    if action == "ask_field" and original is not None and original.type == "ask_field":
        return original, trace
    if action == "soft_close":
        trace["soft_close_blocked_reason"] = next_step_reason or "next_real_step_exists"
    if (
        action == "ask_clarification"
        and original is None
        and next_step.type == "ask_missing_documents"
        and _looks_like_document_flow_question(user_message)
    ):
        trace["pending_flow_recompute_reason"] = "document_question_after_quote"
        return next_step, trace
    if action == "ask_clarification" and original is None:
        return original, trace
    if (
        original is not None
        and original.type == "ask_missing_documents"
        and original.reason == "resume_pending_action"
    ):
        return original, trace
    if original is not None and original.type == "ask_missing_documents" and not has_commercial_state:
        return original, trace
    if original is None:
        trace["pending_flow_recompute_reason"] = "pending_flow_absent"
        return next_step, trace
    if original.type == "ask_missing_documents" and next_step.type != "ask_missing_documents":
        trace["resume_missing_blocked_reason"] = next_step_reason or "next_real_step_not_documents"
    if _pending_key(original) != _pending_key(next_step):
        trace["pending_flow_recompute_reason"] = "pending_flow_contradicts_validated_state"
        return next_step, trace
    return original, trace


def _looks_like_document_flow_question(message: str) -> bool:
    text = _normalize(message)
    if not text:
        return False
    document_terms = {
        "documento",
        "documentos",
        "papel",
        "papeles",
        "ine",
        "domicilio",
        "comprobante",
        "foto",
        "mandar",
        "mando",
        "mando primero",
        "enviar",
        "envio",
        "subir",
        "minimo",
        "primero",
        "ocupan",
        "piden",
        "requieren",
    }
    return any(term in text for term in document_terms)


def _pending_flow(
    *,
    action: str,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
) -> ResponseFramePendingFlow | None:
    pending = (
        decision_payload.get("resume_pending_action")
        or action_payload.get("resume_pending_action")
        or decision_payload.get("pending_to_resume")
        or action_payload.get("pending_to_resume")
    )
    if (
        action == "resolve_credit_plan"
        and isinstance(pending, dict)
        and str(pending.get("type") or "").strip() == "ask_missing_documents"
    ):
        pending = None
    if _payload_is_cash_mode(action_payload):
        pending = None
    if isinstance(pending, dict) and pending:
        pending_payload = dict(pending)
        if (
            str(pending_payload.get("type") or "").strip() == "ask_field"
            and str(pending_payload.get("field") or "").strip().upper() == "CREDITO"
            and bool(action_payload.get("dual_income_resolution_required"))
        ):
            pending_payload["type"] = "ask_income_disambiguation"
        return ResponseFramePendingFlow(
            type=str(pending.get("type") or "resume_flow"),
            payload=pending_payload,
            human_name=_pending_flow_human_name(pending),
            reason="resume_pending_action",
        )
    field_name = str(action_payload.get("field_name") or "").strip()
    if action in {"ask_field", "ask_credit_context"} and field_name:
        payload = {
            "type": "ask_field",
            "field": field_name,
            "description": action_payload.get("field_description"),
        }
        return ResponseFramePendingFlow(
            type="ask_field",
            payload=payload,
            human_name=_field_human_name(field_name),
            reason="runner_missing_field",
        )
    target_field = str(action_payload.get("target_field") or "").strip().casefold()
    if action == "ask_clarification" and target_field in {"model", "moto"}:
        payload = {
            "type": "ask_field",
            "field": "MOTO",
            "description": action_payload.get("suggested_clarification"),
        }
        return ResponseFramePendingFlow(
            type="ask_field",
            payload=payload,
            human_name=_field_human_name("MOTO"),
            reason="clarification_targets_model",
        )
    requirements = action_payload.get("requirements")
    if _payload_is_cash_mode(action_payload):
        return None
    if action in {"resolve_credit_plan", "ask_clarification"}:
        return None
    if isinstance(requirements, dict) and requirements.get("missing"):
        missing = requirements.get("missing") or []
        payload = {"type": "ask_missing_documents", "missing": missing}
        return ResponseFramePendingFlow(
            type="ask_missing_documents",
            payload=payload,
            human_name="documentos pendientes",
            reason="requirements_missing_documents",
        )
    return None


def _validated_answers(
    *,
    action: str,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
) -> dict[str, ResponseFrameValidatedAnswer]:
    validated: dict[str, ResponseFrameValidatedAnswer] = {}
    answers = action_payload.get("answers") if isinstance(action_payload.get("answers"), list) else []
    for index, item in enumerate(answers):
        if not isinstance(item, dict):
            continue
        answer_text = str(item.get("answer") or "").strip()
        if not answer_text:
            continue
        key = str(item.get("topic") or f"answer_{index + 1}").strip() or f"answer_{index + 1}"
        validated[key] = ResponseFrameValidatedAnswer(
            text=answer_text,
            source=str(item.get("source") or action or "payload"),
            confidence=float(item.get("confidence") or 1.0),
            must_include=True,
        )
    answer = str(action_payload.get("answer") or "").strip()
    if answer:
        key = str(action_payload.get("topic") or action or "answer").strip() or "answer"
        validated.setdefault(
            key,
            ResponseFrameValidatedAnswer(
                text=answer,
                source=str(action_payload.get("source") or action or "payload"),
                confidence=1.0,
                must_include=True,
            ),
        )
    requirements_summary = str(action_payload.get("requirements_summary") or "").strip()
    if requirements_summary:
        validated["requirements_summary"] = ResponseFrameValidatedAnswer(
            text=requirements_summary,
            source="requirements_summary",
            confidence=1.0,
            must_include=True,
        )
    prompt_override = str(action_payload.get("prompt_override") or "").strip()
    if prompt_override and action not in {"quote", "lookup_faq"}:
        validated.setdefault(
            "prompt_override",
            ResponseFrameValidatedAnswer(
                text=prompt_override,
                source="prompt_override",
                confidence=0.9,
                must_include=False,
            ),
        )
    suggested_clarification = str(decision_payload.get("suggested_clarification") or "").strip()
    if suggested_clarification and action == "ask_clarification":
        validated.setdefault(
            "clarification",
            ResponseFrameValidatedAnswer(
                text=suggested_clarification,
                source="decision_payload",
                confidence=1.0,
                must_include=True,
            ),
        )
    if action == "resolve_credit_plan":
        resolution_text = _credit_plan_resolution_answer(action_payload)
        if resolution_text:
            validated.setdefault(
                "credit_plan_resolution",
                ResponseFrameValidatedAnswer(
                    text=resolution_text,
                    source="credit_plan_resolution",
                    confidence=1.0,
                    must_include=True,
                ),
            )
    if action == "search_catalog" and str(action_payload.get("request_type") or "").strip() == "catalog_browse":
        catalog_text = _catalog_browse_answer(action_payload)
        if catalog_text:
            validated.setdefault(
                "catalog_browse",
                ResponseFrameValidatedAnswer(
                    text=catalog_text,
                    source="catalog_browse",
                    confidence=1.0,
                    must_include=True,
                ),
            )
    if action == "classify_document":
        document_text = _document_feedback_answer(
            action_payload=action_payload,
            decision_payload=decision_payload,
        )
        if document_text:
            validated.setdefault(
                "document_feedback",
                ResponseFrameValidatedAnswer(
                    text=document_text,
                    source="document_feedback",
                    confidence=1.0,
                    must_include=True,
                ),
            )
    return validated


def _unresolved_intents(
    *,
    current_intents: list[str],
    answered_intents: list[str],
    validated_answers: dict[str, ResponseFrameValidatedAnswer],
    missing_answer_targets: list[str] | None = None,
) -> list[str]:
    resolved = set(answered_intents) | set(validated_answers.keys())
    unresolved = [item for item in current_intents if item not in resolved]
    unresolved.extend(list(missing_answer_targets or []))
    return _dedupe(unresolved)


def _known_customer_state(
    *,
    extracted_data: dict[str, Any],
    action: str,
    action_payload: dict[str, Any],
    current_stage: str,
    conversation_summary: str | None,
    recent_history: list[tuple[str, str]],
) -> dict[str, Any]:
    known: dict[str, Any] = {
        "pipeline_stage": current_stage,
    }
    active_purchase_mode = str(action_payload.get("active_purchase_mode") or "").strip()
    quote_mode = str(action_payload.get("quote_mode") or "").strip()
    if active_purchase_mode:
        known["active_purchase_mode"] = active_purchase_mode
    if quote_mode:
        known["quote_mode"] = quote_mode
    for source_key, known_key in (
        ("active_model", "active_model"),
        ("last_quote_model", "last_quote_model"),
        ("previous_model", "previous_model"),
        ("new_model", "new_model"),
        ("model_change_source", "model_change_source"),
        ("selected_income_source", "selected_income_source"),
    ):
        value = str(action_payload.get(source_key) or "").strip()
        if value:
            known[known_key] = value
    if action_payload.get("model_change_detected"):
        known["model_change_detected"] = True
    if action_payload.get("dual_income_resolution_required"):
        known["dual_income_resolution_required"] = True
    for key in ("ANTIGUEDAD_LABORAL", "FILTRO", "CREDITO", "ENGANCHE", "MOTO", "PLAN"):
        value = _unwrap_value(extracted_data.get(key))
        if value not in (None, "", [], {}):
            known[key.casefold()] = value
    if (
        action == "quote"
        and action_payload.get("status") == "ok"
    ) or _recent_history_has_quote(recent_history) or _recent_history_has_document_prompt(recent_history) or _summary_has_quote(conversation_summary):
        known["quote_valid"] = True
        if action == "quote" and action_payload.get("status") == "ok":
            known["last_quote_payload"] = dict(action_payload)
            if _payload_is_cash_mode(action_payload):
                known["cash_quote_valid"] = True
                known["last_cash_quote_payload"] = dict(action_payload)
            else:
                known.setdefault("active_purchase_mode", "credit")
                known.setdefault("quote_mode", "credit")
                known["credit_quote_valid"] = True
                known["last_credit_quote_payload"] = dict(action_payload)
    requirements = action_payload.get("requirements")
    if (
        action != "resolve_credit_plan"
        and not _payload_is_cash_mode(action_payload)
        and isinstance(requirements, dict)
    ):
        known["missing_documents"] = _doc_labels(requirements.get("missing"))
        missing_docs = known.get("missing_documents") or []
        known["next_missing_document"] = missing_docs[0] if missing_docs else None
    if conversation_summary:
        known["conversation_summary"] = conversation_summary
    return known


def _string_state_value(state: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _unwrap_value(state.get(key))
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""


def _payload_is_cash_mode(payload: dict[str, Any]) -> bool:
    return str(
        payload.get("active_purchase_mode")
        or payload.get("quote_mode")
        or ""
    ).strip() == "cash"


def _credit_plan_needs_seniority(credit_plan: str) -> bool:
    normalized = _normalize(credit_plan)
    if not normalized:
        return False
    return "sin comprobantes" not in normalized


def _recent_history_has_quote(history: list[tuple[str, str]]) -> bool:
    return any(
        role == "outbound" and _looks_like_quote_text(text)
        for role, text in history[-8:]
    )


def _recent_history_has_document_prompt(history: list[tuple[str, str]]) -> bool:
    return any(
        role == "outbound" and _looks_like_document_prompt(str(text or ""))
        for role, text in history[-4:]
    )


def _summary_has_quote(summary: str | None) -> bool:
    return _looks_like_quote_text(summary or "")


def _looks_like_quote_text(text: str) -> bool:
    normalized = _normalize(text)
    return bool(
        "$" in str(text or "")
        and "enganche" in normalized
        and ("quincenal" in normalized or "contado" in normalized)
    )


def _anti_repetition(
    *,
    user_message: str,
    recent_history: list[tuple[str, str]],
    last_bot_message: str | None,
    answered_intents: list[str],
    pending_flow: ResponseFramePendingFlow | None,
) -> ResponseFrameAntiRepetition:
    normalized_user = _normalize(user_message)
    previous_inbound = _last_message_for_role(recent_history[:-1], "inbound")
    customer_repeated_question = bool(
        normalized_user
        and any(
            _normalize(text) == normalized_user
            for role, text in recent_history[:-1]
            if role == "inbound" and str(text or "").strip()
        )
    )
    repeated_prompt_count = 0
    last_similar_bot_message = None
    if last_bot_message:
        target = _normalize(last_bot_message)
        for role, text in reversed(recent_history):
            if role != "outbound":
                continue
            if _normalize(text) != target:
                break
            repeated_prompt_count += 1
            last_similar_bot_message = str(text)
    last_document_prompt = None
    document_prompt_count = 0
    for role, text in reversed(recent_history):
        if role != "outbound":
            continue
        value = str(text or "").strip()
        if value and _looks_like_document_prompt(value):
            document_prompt_count += 1
            last_document_prompt = value
    avoid_same_document_prompt = bool(
        last_document_prompt
        and pending_flow is not None
        and pending_flow.type == "ask_missing_documents"
    )
    return ResponseFrameAntiRepetition(
        last_similar_bot_message=last_similar_bot_message,
        repeated_prompt_count=repeated_prompt_count,
        document_prompt_count=document_prompt_count,
        customer_repeated_question=customer_repeated_question,
        avoid_same_opening=customer_repeated_question or repeated_prompt_count > 0,
        avoid_same_document_prompt=avoid_same_document_prompt,
        last_document_prompt=last_document_prompt,
        last_answered_intents=list(answered_intents),
        last_customer_question=previous_inbound,
    )


def _response_strategy(
    *,
    action: str,
    current_intents: list[str],
    current_questions: list[dict[str, Any]],
    validated_answers: dict[str, ResponseFrameValidatedAnswer],
    pending_flow: ResponseFramePendingFlow | None,
    missing_answer_targets: list[str],
) -> ResponseStrategy:
    has_validated_answer = bool(validated_answers)
    has_current_intent = bool(current_intents)
    if current_questions and missing_answer_targets:
        if pending_flow is not None:
            return "answer_and_resume_flow"
        return "clarify"
    if action == "quote":
        if current_questions and has_validated_answer:
            return "quote_and_answer"
        if pending_flow is None and "cash_price_request" in current_intents:
            return "quote_cash"
        return "quote_and_resume" if pending_flow is not None else "quote"
    if action == "lookup_faq":
        return "answer_and_resume_flow" if pending_flow is not None else "answer_only"
    if action == "search_catalog":
        return "answer_and_resume_flow" if pending_flow is not None else "answer_only"
    if action == "resolve_credit_plan":
        return "answer_and_resume_flow" if pending_flow is not None else "answer_only"
    if action == "ask_credit_context":
        if has_current_intent and has_validated_answer:
            return "answer_and_resume_flow"
        return "ask_missing_field"
    if action in {"classify_document", "ask_missing_document"}:
        if has_validated_answer and pending_flow is not None:
            return "answer_and_resume_flow"
        if has_current_intent and has_validated_answer:
            return "answer_only"
        if pending_flow is not None and pending_flow.type == "ask_missing_documents":
            return "document_request"
        return "document_feedback"
    if action == "ask_field":
        if has_current_intent and has_validated_answer:
            return "answer_and_resume_flow"
        return "ask_missing_field"
    if action == "ask_clarification":
        if pending_flow is not None and pending_flow.type in {"ask_missing_documents", "quote"}:
            return "answer_and_resume_flow"
        if pending_flow is not None and pending_flow.type == "ask_field":
            return "ask_missing_field"
        return "clarify"
    if action == "soft_close":
        if pending_flow is not None:
            return "answer_and_resume_flow"
        return "soft_close"
    if action == "handoff":
        return "handoff"
    if has_current_intent and has_validated_answer and pending_flow is not None:
        return "answer_and_resume_flow"
    if has_validated_answer:
        return "answer_only"
    return "ask_missing_field" if pending_flow is not None else "clarify"


def _pending_flow_human_name(pending: dict[str, Any]) -> str | None:
    flow_type = str(pending.get("type") or "").strip()
    if flow_type == "ask_field":
        return _field_human_name(str(pending.get("field") or "").strip())
    if flow_type == "ask_missing_documents":
        return "documentos pendientes"
    return flow_type or None


def _field_human_name(field_name: str) -> str:
    values = {
        "CREDITO": "plan de credito",
        "ENGANCHE": "enganche",
        "MOTO": "modelo",
        "ANTIGUEDAD_LABORAL": "antiguedad laboral",
        "FILTRO": "antiguedad laboral",
    }
    return values.get(field_name.upper(), field_name.casefold() or "dato faltante")


def _doc_labels(raw_docs: Any) -> list[str]:
    return humanize_document_labels(raw_docs)


def _credit_plan_resolution_answer(action_payload: dict[str, Any]) -> str:
    label = str(
        action_payload.get("selection_label")
        or action_payload.get("selection_key")
        or action_payload.get("field_updates", {}).get("CREDITO")
        or ""
    ).strip()
    down_payment = str(
        action_payload.get("down_payment")
        or action_payload.get("field_updates", {}).get("ENGANCHE")
        or ""
    ).strip()
    alias = _credit_plan_user_facing_alias(action_payload)
    if label and down_payment and alias:
        return f"Perfecto, {alias} entra como {label} y maneja {down_payment} de enganche."
    if label and down_payment:
        return f"Perfecto, ese perfil entra como {label} y maneja {down_payment} de enganche."
    if label:
        return f"Perfecto, ese perfil entra como {label}."
    return ""


def _credit_plan_user_facing_alias(action_payload: dict[str, Any]) -> str:
    candidates = [
        action_payload.get("visible_label"),
        action_payload.get("matched_alias"),
        action_payload.get("input"),
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        normalized = value.casefold()
        if normalized.endswith("_signal") or normalized.startswith("negative_"):
            continue
        if "override" in normalized and "_" in normalized:
            continue
        return value
    return ""


def _catalog_browse_answer(action_payload: dict[str, Any]) -> str:
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
    catalog_url = str(action_payload.get("catalog_url") or "").strip()
    browse_intent = str(action_payload.get("browse_intent") or "catalog_overview").strip()
    query = str(action_payload.get("query") or "").strip()
    if browse_intent == "catalog_more":
        intro = (
            f"Si, tenemos mas opciones de {query}."
            if query and total_count
            else f"No, tenemos {total_count} modelos activos."
            if total_count
            else "No, tenemos mas modelos."
        )
    elif browse_intent == "catalog_style":
        intro = (
            f"Si, tenemos estas opciones de {query}."
            if query and total_count
            else "Si, te paso opciones del catalogo."
        )
    elif browse_intent == "full_catalog":
        intro = (
            f"Claro, tenemos {total_count} modelos activos en catalogo."
            if total_count
            else "Claro, te paso el catalogo."
        )
    else:
        intro = (
            f"Claro, te paso opciones del catalogo ({total_count} modelos activos)."
            if total_count
            else "Claro, te paso opciones del catalogo."
        )
    lines = [intro]
    if names:
        lines.append("Modelos: " + ", ".join(names[:3]) + ".")
    if catalog_url:
        lines.append(f"Catalogo completo: {catalog_url}")
    lines.append("Dime cual te interesa y te ayudo a cotizarla.")
    return " ".join(lines)


def _document_feedback_answer(
    *,
    action_payload: dict[str, Any],
    decision_payload: dict[str, Any],
) -> str:
    rejected = action_payload.get("rejected_attachments") if isinstance(action_payload, dict) else []
    if _doc_labels(rejected):
        return "La imagen no se alcanza a validar bien. Me la puedes reenviar mas clara?"
    received = action_payload.get("received_documents") if isinstance(action_payload, dict) else []
    received_labels = _doc_labels(received)
    if received_labels:
        return "Recibi tu documento: " + join_humanized_documents(received) + "."
    request_type = str(action_payload.get("request_type") or "").strip()
    evidence = str(decision_payload.get("evidence") or "").strip()
    if request_type == "ask_missing_document" and evidence == "documents_cannot_be_marked_received_from_text":
        return "Todavia no me aparece cargado en el expediente."
    if request_type == "ask_missing_document":
        return "Revise tu expediente y todavia me faltan estos documentos."
    return ""


def _looks_like_document_prompt(text: str | None) -> bool:
    normalized = _normalize(text)
    return any(token in normalized for token in ("document", "ine", "domicilio", "papel"))


def _looks_like_question(text: str | None) -> bool:
    value = str(text or "").strip()
    return "?" in value or any(
        token in _normalize(value)
        for token in ("que", "como", "donde", "cuando", "puedo", "revisan", "ubicacion")
    )


def _last_message_for_role(
    history: list[tuple[str, str]],
    role_name: str,
) -> str | None:
    for role, text in reversed(history):
        if role == role_name and str(text or "").strip():
            return str(text).strip()
    return None


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value and "status" not in value:
        return value.get("value")
    return value


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(value).strip())
    return out


def _normalize(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.casefold()).strip()


__all__ = [
    "ResponseFrame",
    "ResponseFrameAntiRepetition",
    "ResponseFrameComposerInstructions",
    "ResponseFramePendingFlow",
    "ResponseFrameTrace",
    "ResponseFrameValidatedAnswer",
    "build_response_frame",
]

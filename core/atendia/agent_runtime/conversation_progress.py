from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from atendia.agent_runtime.quote_safety import visible_quote_signal
from atendia.agent_runtime.schemas import TurnContext, TurnOutput
from atendia.config import get_settings

_SENIORITY_ASK_RE = re.compile(
    r"(?:cuanto tiempo|antiguedad|tiempo llevas trabajando)",
    re.IGNORECASE,
)
_INCOME_ASK_RE = re.compile(
    r"(?:como recibes tus ingresos|tipo de ingreso|te pagan|recibes ingreso)",
    re.IGNORECASE,
)
_PRODUCT_ASK_RE = re.compile(
    r"(?:que modelo|que moto|modelo quieres|elige una)",
    re.IGNORECASE,
)
_QUOTE_REPEAT_RE = re.compile(
    r"(?:cuanto era|repiteme.*precio|otra vez.*precio|de nuevo.*precio)",
    re.IGNORECASE,
)
_QUOTE_INTENT_RE = re.compile(
    r"(?:precio|presio|prescio|cotiza|cotizacion|cuanto|sale|cuesta|queda)",
    re.IGNORECASE,
)
_DOC_INTENT_RE = re.compile(r"(?:documentos?|requisitos?|papeles?)", re.IGNORECASE)
_DOC_SIGNAL_RE = re.compile(
    r"(?:documentos?|requisitos?|papeles?|ine|comprobante|mando|envio|adjunto|foto|archivo)",
    re.IGNORECASE,
)
_DOC_ACK_RE = re.compile(r"(?:va|ok|sale|los junto|los consigo|los mando)", re.IGNORECASE)
_ACK_RE = re.compile(r"^\s*(?:ok|va|si|sale|listo|gracias)\b", re.IGNORECASE)
_GENERIC_CTA_RE = re.compile(
    r"(?:te puedo decir que documentos|si te interesa|dime si quieres|"
    r"te ayudo con el siguiente paso)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConversationProgressContext:
    latest_customer_act: str
    last_assistant_action: str | None
    last_question_slot: str | None
    answered_slots: dict[str, Any]
    must_not_ask_slots: list[str]
    must_not_repeat_actions: list[str]
    allowed_repeat: bool

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConversationProgressMetrics:
    similarity_to_last_assistant: float
    repeated_slot: str | None
    repeated_action: str | None


@dataclass(frozen=True)
class ConversationProgressEvaluation:
    allowed: bool
    repeat_detected: bool
    repeat_type: str | None
    failures: list[str]
    sanitized_message: str
    metrics: ConversationProgressMetrics

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConversationProgressGuard:
    def __init__(self, mode: Literal["shadow", "block"] | None = None) -> None:
        self._mode = mode

    def evaluate(
        self,
        *,
        context: TurnContext,
        output: TurnOutput,
    ) -> ConversationProgressEvaluation:
        message = str(output.final_message or "")
        prior_messages = _assistant_messages(context)
        last = prior_messages[-1] if prior_messages else None
        product_changed = _product_changed_signal(context.inbound_text)
        inbound_folded = _fold(context.inbound_text)
        allowed_repeat = bool(
            _QUOTE_REPEAT_RE.search(inbound_folded)
            or _QUOTE_INTENT_RE.search(inbound_folded)
            or _DOC_INTENT_RE.search(inbound_folded)
        )
        similarity = 0.0 if product_changed or allowed_repeat else _similarity(message, last)
        exact_prior_repeat = any(_fold(message) == _fold(prior) for prior in prior_messages)
        failures: list[str] = []
        repeat_type: str | None = None
        repeated_slot = _repeated_answered_slot(context, message)
        repeated_action = _repeated_action(context, message)
        product_change_ack_missing = _product_change_ack_required(context, output, message)

        if repeated_action == "guard_fallback_repeated":
            repeat_type = "guard_fallback_repeated"
            failures.append("guard_fallback_repeated")
        elif not product_changed and not allowed_repeat and exact_prior_repeat:
            repeat_type = "exact_response_repeat"
            failures.append("exact_response_repeat")
        elif (
            not product_changed
            and not allowed_repeat
            and last
            and similarity >= 0.88
            and len(_fold(message)) > 24
        ):
            repeat_type = "exact_response_repeat"
            failures.append("exact_response_repeat")
        if repeated_slot:
            repeat_type = repeat_type or "same_slot_question_repeated"
            failures.append("same_slot_question_repeated")
        if repeated_action and repeated_action != "guard_fallback_repeated":
            repeat_type = repeat_type or repeated_action
            failures.append(repeated_action)
        if product_change_ack_missing:
            repeat_type = repeat_type or "product_change_ack_missing"
            failures.append("product_change_ack_missing")

        allowed = not failures
        sanitized = message if allowed else _progress_fallback(
            context,
            repeat_type,
            prior_messages,
            original_message=message,
        )
        return ConversationProgressEvaluation(
            allowed=allowed,
            repeat_detected=bool(failures),
            repeat_type=repeat_type,
            failures=_dedupe(failures),
            sanitized_message=sanitized,
            metrics=ConversationProgressMetrics(
                similarity_to_last_assistant=similarity,
                repeated_slot=repeated_slot,
                repeated_action=repeated_action,
            ),
        )

    def apply(self, *, context: TurnContext, output: TurnOutput) -> ConversationProgressEvaluation:
        mode = self._mode or get_settings().conversation_progress_guard_mode
        evaluation = self.evaluate(context=context, output=output)
        trace = dict(output.trace_metadata)
        payload = {
            **evaluation.to_dict(),
            "mode": mode,
            "action": (
                "allowed"
                if evaluation.allowed
                else ("shadow" if mode == "shadow" else "sanitized")
            ),
        }
        trace["conversation_progress_guard"] = payload
        if not evaluation.allowed and mode == "block":
            output = output.model_copy(
                update={
                    "final_message": evaluation.sanitized_message,
                    "risk_flags": _append_unique(
                        output.risk_flags,
                        "conversation_progress_sanitized",
                    ),
                    "trace_metadata": trace,
                }
            )
        else:
            output = output.model_copy(update={"trace_metadata": trace})
        object.__setattr__(evaluation, "_output", output)
        return evaluation


def normalize_composer_progress(context: TurnContext, output: TurnOutput) -> TurnOutput:
    """Rewrite avoidable repetition before the blocking progress guard runs."""

    if not _progress_normalizer_enabled(context, output):
        return output

    message = str(output.final_message or "")
    latest_act = latest_customer_act(context.inbound_text)
    replacement: str | None = None
    reason: str | None = None

    if latest_act in {"qualification_income", "qualification_seniority"} and (
        _message_has_requirements(message)
        or visible_quote_signal(message)
        or _matches_any_prior(context, message)
        or _is_generic_sanitizer_fallback(message)
    ):
        replacement = _progress_fallback(context, latest_act)
        reason = f"normalized_{latest_act}"
    elif latest_act == "documents_question" and (
        _matches_any_prior(context, message)
        and not _explicit_documents_request(context.inbound_text)
    ):
        replacement = _document_update_ack(context)
        reason = "normalized_document_update"
    elif latest_act == "documents_question" and not _documents_answered_or_explained(message):
        replacement = _document_answer_or_explanation(context)
        reason = "normalized_documents_question"
    elif latest_act == "acknowledgement" and (
        visible_quote_signal(message)
        or _message_has_requirements(message)
        or _matches_any_prior(context, message)
    ):
        replacement = _progress_fallback(context, "acknowledgement")
        reason = "normalized_acknowledgement"
    elif latest_act == "quote_request" and not (
        visible_quote_signal(message) or _quote_explanation_present(message)
    ):
        replacement = _quote_request_explanation(context)
        reason = "normalized_quote_request"
    elif _message_has_requirements(message) and latest_act != "documents_question":
        replacement = _progress_fallback(context, latest_act)
        reason = "normalized_unrequested_requirements"
    elif _matches_any_prior(context, message) or _is_generic_sanitizer_fallback(message):
        replacement = _progress_fallback(context, latest_act)
        reason = "normalized_repeated_or_generic_message"
    elif latest_act == "handoff_request" and not _handoff_confirmed(message):
        replacement = "Claro, te paso con una persona del equipo para que lo revise directo."
        reason = "normalized_handoff_request"

    if _product_change_ack_required(context, output, replacement or message):
        replacement = _with_product_change_ack(replacement or message)
        reason = "normalized_product_change_ack"

    if not replacement or replacement == message:
        return output

    trace = dict(output.trace_metadata)
    trace["conversation_progress_normalizer"] = {
        "action": "rewritten",
        "reason": reason,
        "latest_customer_act": latest_act,
    }
    return output.model_copy(update={"final_message": replacement, "trace_metadata": trace})


def output_from_progress_result(result: ConversationProgressEvaluation) -> TurnOutput:
    return result._output  # type: ignore[attr-defined]


def build_conversation_progress_context(context: TurnContext) -> ConversationProgressContext:
    answered = _answered_slots(context)
    last_action = _last_assistant_action(context)
    latest_act = latest_customer_act(context.inbound_text)
    must_not_repeat: list[str] = []
    if _last_assistant_had_quote(context):
        must_not_repeat.append("quote")
    if _last_assistant_had_requirements(context):
        must_not_repeat.append("requirements")
    return ConversationProgressContext(
        latest_customer_act=latest_act,
        last_assistant_action=last_action,
        last_question_slot=_question_slot(_last_assistant_message(context)),
        answered_slots=answered,
        must_not_ask_slots=sorted(answered),
        must_not_repeat_actions=must_not_repeat,
        allowed_repeat=bool(_QUOTE_REPEAT_RE.search(_fold(context.inbound_text))),
    )


def conversation_progress_memory(context: TurnContext, output: TurnOutput) -> dict[str, Any]:
    message = str(output.final_message or "")
    guard = output.trace_metadata.get("conversation_progress_guard") or {}
    return {
        "last_assistant_message_hash": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "last_assistant_action": _message_action(message),
        "last_question_slot": _question_slot(message),
        "asked_slots": {slot: True for slot in [_question_slot(message)] if slot},
        "answered_slots": _answered_slots(context),
        "last_quote_snapshot_sent": _last_quote_snapshot_id(output),
        "last_requirements_sent_for_plan": _requirements_plan(output),
        "last_guard_repeat_type": guard.get("repeat_type"),
    }


def latest_customer_act(text: str | None) -> str:
    value = _fold(text)
    if _QUOTE_REPEAT_RE.search(value):
        return "repeat_quote_request"
    if _QUOTE_INTENT_RE.search(value):
        return "quote_request"
    if _DOC_SIGNAL_RE.search(value):
        return "documents_question"
    if re.search(r"(?:humano|asesor|francisco|fransisko|persona)", value, re.IGNORECASE):
        return "handoff_request"
    if _ACK_RE.search(value):
        return "acknowledgement"
    if re.search(r"(?:ano|mes|trabaj)", value, re.IGNORECASE):
        return "qualification_seniority"
    if re.search(r"(?:tarjeta|nomina|por fuera|efectivo|recibos)", value, re.IGNORECASE):
        return "qualification_income"
    return "message"


def _repeated_answered_slot(context: TurnContext, message: str) -> str | None:
    answered = _answered_slots(context)
    folded_message = _fold(message)
    checks = {
        "Antiguedad_Laboral": _SENIORITY_ASK_RE,
        "Ingreso": _INCOME_ASK_RE,
        "Producto": _PRODUCT_ASK_RE,
    }
    for slot, pattern in checks.items():
        if slot in answered and pattern.search(folded_message):
            return slot
    return None


def _repeated_action(context: TurnContext, message: str) -> str | None:
    inbound = _fold(context.inbound_text)
    folded_message = _fold(message)
    folded_last = _fold(_last_assistant_message(context))
    if folded_message == folded_last and "cotizacion del sistema" in folded_message:
        return "guard_fallback_repeated"
    if visible_quote_signal(message) and _last_assistant_had_quote(context) and not (
        _QUOTE_INTENT_RE.search(inbound) or _QUOTE_REPEAT_RE.search(inbound)
    ):
        return "quote_repeated_without_user_asking"
    if (
        _message_has_requirements(message)
        and _last_assistant_had_requirements(context)
        and not _DOC_SIGNAL_RE.search(inbound)
    ):
        return "requirements_repeated_without_user_asking"
    if _GENERIC_CTA_RE.search(folded_message) and _GENERIC_CTA_RE.search(folded_last):
        return "generic_cta_repeated"
    return None


def _progress_fallback(
    context: TurnContext,
    repeat_type: str | None,
    prior_messages: list[str] | None = None,
    original_message: str = "",
) -> str:
    inbound = context.inbound_text or ""
    latest_act = latest_customer_act(inbound)
    prior_messages = prior_messages or _assistant_messages(context)
    if repeat_type == "product_change_ack_missing":
        return _with_product_change_ack(original_message)
    if _product_changed_signal(inbound):
        return _first_new(
            [
                "Perfecto, cambio al nuevo modelo y reviso esa opcion con datos validados.",
                "Listo, tomo el cambio de modelo y recalculo desde datos validados.",
            ],
            prior_messages,
        )
    if latest_act == "qualification_income" or repeat_type == "qualification_income":
        return _first_new(
            [
                "Perfecto, tomo ese dato de ingresos y avanzo con el siguiente paso.",
                "Recibido, dejo ese tipo de ingreso en contexto y continuo con la validacion.",
            ],
            prior_messages,
        )
    if latest_act == "qualification_seniority" or repeat_type == "qualification_seniority":
        return _first_new(
            [
                "Perfecto, tomo tu antiguedad laboral y seguimos con la validacion.",
                "Gracias, ya considero tu antiguedad laboral para avanzar.",
            ],
            prior_messages,
        )
    if latest_act == "acknowledgement" or repeat_type == "acknowledgement":
        return _first_new(
            [
                (
                    "Va, el siguiente paso es confirmar documentos "
                    "o revisar si quieres otra opcion."
                ),
                "Va, te doy continuidad con el siguiente paso disponible.",
                "Va, seguimos con el avance sin volver a listar lo mismo.",
            ],
            prior_messages,
        )
    if repeat_type == "guard_fallback_repeated":
        return _first_new(
            [
                (
                    "Para avanzar sin inventar datos necesito confirmar el modelo exacto "
                    "o el plan que quieres revisar."
                ),
                "Necesito confirmar modelo y plan en sistema antes de dar precio.",
            ],
            prior_messages,
        )
    if _DOC_ACK_RE.search(_fold(inbound)):
        return _first_new(
            [
                "Va, juntalos y cuando los tengas los revisamos sobre el checklist.",
                "Va, cuando los tengas los reviso contra el checklist.",
                "Va, manda el archivo cuando lo tengas y lo valido contra el checklist.",
            ],
            prior_messages,
        )
    if "no tengo" in _fold(inbound) or "no se" in _fold(inbound) or "foto" in _fold(inbound):
        return _first_new(
            [
                "No hay problema; cuando tengas claro el documento o archivo, lo revisamos.",
                "Sin problema, dejamos pendiente el archivo y seguimos con lo que ya tenemos.",
            ],
            prior_messages,
        )
    return _first_new(
        [
            "Tomo tu mensaje y reviso el siguiente paso con el contexto actual.",
            "Te doy continuidad con lo que ya tenemos en la conversacion.",
            "Listo, sigo desde el contexto actual y cuido no duplicar informacion.",
        ],
        prior_messages,
    )


def _answered_slots(context: TurnContext) -> dict[str, Any]:
    facts = context.memory.salient_facts
    answered: dict[str, Any] = {}
    for key in ("Ingreso", "Antiguedad_Laboral", "Producto"):
        value = facts.get(key)
        if value:
            answered[key] = value
    progress = context.memory.metadata.get("conversation_progress")
    if isinstance(progress, dict) and isinstance(progress.get("answered_slots"), dict):
        answered.update(progress["answered_slots"])
    return answered


def _last_assistant_message(context: TurnContext) -> str | None:
    messages = _assistant_messages(context)
    return messages[-1] if messages else None


def _assistant_messages(context: TurnContext) -> list[str]:
    result: list[str] = []
    for message in context.messages:
        if message.role == "agent" and str(message.text or "").strip():
            result.append(message.text)
    return result


def _first_new(candidates: list[str], prior_messages: list[str]) -> str:
    prior = {_fold(message) for message in prior_messages}
    for candidate in candidates:
        if _fold(candidate) not in prior:
            return candidate
    return candidates[-1]


def _last_assistant_action(context: TurnContext) -> str | None:
    progress = context.memory.metadata.get("conversation_progress")
    if isinstance(progress, dict) and progress.get("last_assistant_action"):
        return str(progress["last_assistant_action"])
    return _message_action(_last_assistant_message(context) or "")


def _message_action(message: str) -> str | None:
    if visible_quote_signal(message):
        return "quote"
    if _message_has_requirements(message):
        return "requirements"
    question_slot = _question_slot(message)
    if question_slot:
        return f"ask_{question_slot}"
    return None


def _question_slot(message: str | None) -> str | None:
    text = _fold(message)
    if _SENIORITY_ASK_RE.search(text):
        return "Antiguedad_Laboral"
    if _INCOME_ASK_RE.search(text):
        return "Ingreso"
    if _PRODUCT_ASK_RE.search(text):
        return "Producto"
    return None


def _last_assistant_had_quote(context: TurnContext) -> bool:
    return visible_quote_signal(_last_assistant_message(context) or "")


def _last_assistant_had_requirements(context: TurnContext) -> bool:
    return _message_has_requirements(_last_assistant_message(context) or "")


def _message_has_requirements(message: str) -> bool:
    folded = _fold(message)
    return "ine" in folded and ("comprobante" in folded or "document" in folded)


def _matches_any_prior(context: TurnContext, message: str) -> bool:
    folded = _fold(message)
    return folded in {_fold(prior) for prior in _assistant_messages(context)}


def _progress_normalizer_enabled(context: TurnContext, output: TurnOutput) -> bool:
    if output.trace_metadata.get("advisor_brain") or output.trace_metadata.get("quote_context"):
        return True
    enabled_actions = context.active_agent.enabled_action_ids if context.active_agent else None
    return bool(enabled_actions and "quote.resolve" in enabled_actions)


def _is_generic_sanitizer_fallback(message: str) -> bool:
    folded = _fold(message)
    return any(
        phrase in folded
        for phrase in (
            "avanzo con lo nuevo",
            "evito repetir",
            "sigo con ese contexto",
        )
    )


def _documents_answered_or_explained(message: str) -> bool:
    folded = _fold(message)
    return _message_has_requirements(message) or (
        ("document" in folded or "requisito" in folded or "papel" in folded)
        and ("confirm" in folded or "plan" in folded or "falta" in folded)
    )


def _document_answer_or_explanation(context: TurnContext) -> str:
    last = _last_assistant_message(context) or ""
    if _message_has_requirements(last):
        return last
    return (
        "De base ocupas INE y comprobante de domicilio. "
        "Segun el plan puede aplicar referencia adicional."
    )


def _document_update_ack(context: TurnContext) -> str:
    inbound = _fold(context.inbound_text)
    if "no tengo" in inbound or "foto" in inbound or "archivo" in inbound:
        return "No hay problema; dejamos ese archivo pendiente y seguimos con lo que ya tenemos."
    if "comprobante" in inbound:
        return "Recibido, tomo el comprobante en cuenta y reviso el checklist."
    if "ine" in inbound:
        return "Recibido, tomo tu INE en cuenta y reviso el checklist."
    return "Recibido, tomo ese documento en cuenta y reviso el checklist."


def _explicit_documents_request(text: str | None) -> bool:
    return bool(_DOC_INTENT_RE.search(_fold(text)))


def _quote_explanation_present(message: str) -> bool:
    folded = _fold(message)
    return "cotizacion" in folded and (
        "confirm" in folded or "sistema" in folded or "modelo" in folded or "plan" in folded
    )


def _quote_request_explanation(context: TurnContext) -> str:
    if context.memory.salient_facts.get("Producto"):
        return (
            "Ya tengo el modelo, pero necesito confirmar la cotizacion del sistema "
            "antes de darte precio."
        )
    return "Para cotizarte bien, dime que modelo quieres o elige una de las opciones."


def _handoff_confirmed(message: str) -> bool:
    folded = _fold(message)
    return any(
        word in folded
        for word in ("humano", "asesor", "francisco", "fransisko", "persona", "equipo")
    )


def _last_quote_snapshot_id(output: TurnOutput) -> str | None:
    for update in output.field_updates:
        if isinstance(update.value, dict) and update.value.get("snapshot_id"):
            return str(update.value["snapshot_id"])
    return None


def _requirements_plan(output: TurnOutput) -> str | None:
    for result in output.trace_metadata.get("tool_results") or []:
        if result.get("tool_name") == "requirements.resolve":
            data = result.get("data") or {}
            return str(data.get("plan") or "default")
    return None


def _product_change_ack_required(context: TurnContext, output: TurnOutput, message: str) -> bool:
    if _acknowledged_product_change(message):
        return False
    previous_product_id = _product_id(context.memory.salient_facts.get("Producto"))
    previous_quote_product_id = _product_id(
        context.memory.last_quote_snapshot.get("product")
        if isinstance(context.memory.last_quote_snapshot, dict)
        else None
    )
    new_product_id = _output_product_id(output)
    if not new_product_id:
        return False
    prior_product_ids = {item for item in (previous_product_id, previous_quote_product_id) if item}
    return bool(prior_product_ids and new_product_id not in prior_product_ids)


def _output_product_id(output: TurnOutput) -> str | None:
    for update in output.field_updates:
        if update.field_key == "Producto":
            product_id = _product_id(update.value)
            if product_id:
                return product_id
        if update.field_key == "Ultima_Cotizacion" and isinstance(update.value, dict):
            product_id = _product_id(update.value.get("product"))
            if product_id:
                return product_id
    return None


def _product_id(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("product_id"):
        return str(value["product_id"])
    return None


def _acknowledged_product_change(message: str) -> bool:
    folded = _fold(message)
    return any(
        phrase in folded
        for phrase in (
            "cotizacion anterior",
            "ya no aplica",
            "actualizo",
            "nuevo modelo",
            "otra cotizacion",
            "recalcular",
        )
    )


def _with_product_change_ack(message: str) -> str:
    folded = _fold(message)
    if _acknowledged_product_change(message):
        return message
    prefix = "Actualizo al nuevo modelo; la cotizacion anterior ya no aplica."
    return f"{prefix} {message.strip()}" if folded else prefix


def _product_changed_signal(text: str | None) -> bool:
    return bool(
        re.search(
            r"(?:mejor|cambio|otra|ahora).*(?:r4|u5|adventure|comando)",
            _fold(text),
            re.IGNORECASE,
        )
    )


def _similarity(a: str, b: str | None) -> float:
    if not b:
        return 0.0
    return round(SequenceMatcher(None, _fold(a), _fold(b)).ratio(), 4)


def _fold(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text).strip()


def _append_unique(values: list[str], item: str) -> list[str]:
    return values if item in values else [*values, item]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


__all__ = [
    "ConversationProgressContext",
    "ConversationProgressEvaluation",
    "ConversationProgressGuard",
    "build_conversation_progress_context",
    "conversation_progress_memory",
    "latest_customer_act",
    "output_from_progress_result",
]

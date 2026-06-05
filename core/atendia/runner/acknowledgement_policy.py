from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from atendia.text_normalization import normalize_whatsapp_text

AcknowledgementClassification = Literal[
    "valid_confirmation",
    "insufficient_answer_to_concrete_question",
    "soft_close",
    "nonsense_clarification",
    "no_ack_match",
]


@dataclass(frozen=True)
class AcknowledgementPolicyRequest:
    user_message: str
    last_bot_message: str | None = None
    recent_history: list[tuple[str, str]] = field(default_factory=list)
    current_state: dict[str, Any] = field(default_factory=dict)
    pending_confirmation: str | None = None
    pending_confirmation_updates: dict[str, Any] = field(default_factory=dict)
    pending_question_payload: dict[str, Any] | None = None
    previous_action: str | None = None
    previous_tool_payload: dict[str, Any] | None = None
    advisor_decision: dict[str, Any] | None = None
    operational_intent_category: str | None = None
    nlu_intent: str | None = None


@dataclass(frozen=True)
class AcknowledgementPolicyResult:
    classification: AcknowledgementClassification
    action_override: str | None = None
    outbound_hint: str | None = None
    should_block_quote: bool = False
    should_block_state_write: bool = False
    reason: str | None = None
    target_field: str | None = None


_ACKNOWLEDGEMENTS = {
    "ok",
    "okay",
    "va",
    "sale",
    "claro",
    "dale",
    "perfecto",
    "listo",
    "correcto",
    "si",
    "sí",
    "simon",
}
_SOFT_CLOSE_REPLIES = {
    "ok",
    "okay",
    "va",
    "sale",
    "claro",
    "dale",
    "perfecto",
    "correcto",
    "gracias",
    "gracias lo veo",
    "gracias lo reviso",
    "gracias te aviso",
    "muchas gracias",
    "lo checo",
    "lo reviso",
    "lo veo",
    "yo te aviso",
    "te aviso",
    "dejame verlo",
    "dejame revisar",
    "dejame checarlo",
    "lo pienso",
    "entonces seguimos",
    "me interesa",
    "ahi esta",
    "ya quedo",
    "listo",
}
_EXPLICIT_DEFERRAL_AFTER_QUOTE_REPLIES = {
    "ok va despues te aviso",
    "lo checo y te aviso",
    "dejame verlo y te digo",
    "lo pienso y te aviso",
    "te aviso despues",
    "despues te digo",
}
_AFFIRMATIVE_REPLIES = {
    "si",
    "sí",
    "claro",
    "correcto",
    "adelante",
    "va",
    "sale",
    "ok",
    "okay",
}
_GREETING_TERMS = {"hola", "buenas", "buen", "dia", "tarde", "noches"}
_DEICTIC_TERMS = {"esa", "ese", "eso", "misma", "mismo", "mero", "mera"}
_SOFT_OFF_TOPIC_TERMS = {"jaja", "jajaja", "compa", "primo", "prima", "gana", "corre"}
_COMMERCIAL_TERMS = {
    "credito",
    "creditos",
    "financiamiento",
    "financiar",
    "pagos",
    "quincenas",
    "catalogo",
    "modelos",
    "opciones",
    "motos",
    "moto",
    "r4",
    "skeleton",
    "comando",
    "precio",
    "cotiza",
    "cotizacion",
    "cuesta",
    "enganche",
    "anticipo",
    "buro",
    "historial",
    "requisitos",
    "papeles",
    "documentos",
    "ine",
    "comprobante",
    "domicilio",
}


def classify_acknowledgement(
    request: AcknowledgementPolicyRequest,
) -> AcknowledgementPolicyResult:
    normalized = _normalize(request.user_message)
    last_bot = request.last_bot_message or _last_outbound(request.recent_history)
    last_bot_norm = _normalize(last_bot or "")

    if _is_affirmative(normalized) and _confirmation_requests_requirements(request):
        return AcknowledgementPolicyResult(
            classification="valid_confirmation",
            action_override="answer_requirements",
            should_block_quote=True,
            reason="yes_to_requirements_pending_confirmation",
        )

    if _is_explicit_deferral_after_quote(normalized) and _recent_quote_context(
        last_bot_norm=last_bot_norm,
        history=request.recent_history,
    ):
        return _soft_close_result("explicit_deferral_after_quote")

    if _is_short_acknowledgement(normalized):
        if not last_bot_norm and not request.current_state:
            return AcknowledgementPolicyResult(
                classification="no_ack_match",
                reason="short_acknowledgement_without_context",
            )
        concrete_target = _concrete_question_target(last_bot_norm)
        if concrete_target is not None:
            return AcknowledgementPolicyResult(
                classification="insufficient_answer_to_concrete_question",
                action_override="ask_clarification",
                outbound_hint=_concrete_question_hint(concrete_target),
                should_block_quote=True,
                should_block_state_write=True,
                reason=f"acknowledgement_does_not_answer_{concrete_target}",
                target_field=concrete_target,
            )
        if _is_affirmative(normalized) and _is_yes_no_question(last_bot_norm):
            return AcknowledgementPolicyResult(
                classification="valid_confirmation",
                action_override="contextual_yes_no_followup",
                should_block_quote=False,
                reason="affirmative_yes_no_followup",
            )
        option_target = _option_question_target(last_bot_norm)
        if option_target is not None:
            return AcknowledgementPolicyResult(
                classification="insufficient_answer_to_concrete_question",
                action_override="ask_clarification",
                outbound_hint=_option_question_hint(option_target),
                should_block_quote=True,
                should_block_state_write=True,
                reason=f"acknowledgement_does_not_answer_{option_target}_option",
                target_field=option_target,
            )
        if _last_bot_was_complete_information(last_bot_norm):
            if _is_soft_close_reply(normalized) or _is_affirmative(normalized):
                return _soft_close_result("ack_after_complete_information")
            return AcknowledgementPolicyResult(
                classification="no_ack_match",
                reason="preserve_existing_non_soft_close_ack_handling",
            )
        if _is_yes_no_question(last_bot_norm):
            return AcknowledgementPolicyResult(
                classification="no_ack_match",
                reason="yes_no_question_without_supported_side_effect",
            )
        return _soft_close_result("contextual_short_acknowledgement")

    if _is_deictic_affirmation(normalized):
        return AcknowledgementPolicyResult(
            classification="no_ack_match",
            reason="preserve_existing_deictic_affirmation_handling",
        )
    if _is_soft_close_reply(normalized) and _last_bot_was_complete_information(last_bot_norm):
        return _soft_close_result("soft_close_after_complete_information")

    if _is_nonsense_without_commercial_signal(normalized, request):
        return AcknowledgementPolicyResult(
            classification="nonsense_clarification",
            action_override="ask_clarification",
            outbound_hint=(
                "No estoy seguro de que quieres confirmar. "
                "Me confirmas a que te refieres?"
            ),
            should_block_quote=True,
            should_block_state_write=True,
            reason="unknown_message_without_commercial_signal",
        )

    return AcknowledgementPolicyResult(classification="no_ack_match")


def _soft_close_result(reason: str) -> AcknowledgementPolicyResult:
    return AcknowledgementPolicyResult(
        classification="soft_close",
        action_override=None,
        outbound_hint="Claro, revisalo con calma. Si decides avanzar, aqui te ayudo.",
        should_block_quote=True,
        should_block_state_write=True,
        reason=reason,
    )


def _normalize(value: str) -> str:
    return normalize_whatsapp_text(value)


def _last_outbound(history: list[tuple[str, str]]) -> str | None:
    for direction, text in reversed(history or []):
        if str(direction).lower() == "outbound" and str(text or "").strip():
            return str(text)
    return None


def _is_short_acknowledgement(normalized: str) -> bool:
    if _is_soft_close_reply(normalized):
        return True
    if normalized in {_normalize(item) for item in _ACKNOWLEDGEMENTS}:
        return True
    tokens = normalized.split()
    if not tokens or len(tokens) > 3:
        return False
    ack_terms = {_normalize(item) for item in _ACKNOWLEDGEMENTS}
    return set(tokens) <= ack_terms


def _is_affirmative(normalized: str) -> bool:
    return normalized in {_normalize(item) for item in _AFFIRMATIVE_REPLIES}


def _is_soft_close_reply(normalized: str) -> bool:
    soft_close_replies = {_normalize(item) for item in _SOFT_CLOSE_REPLIES}
    if normalized in soft_close_replies:
        return True
    removable_tokens = {"gracias", "muchas", "ok", "okay", "va", "sale", "claro", "perfecto"}
    stripped_tokens = [token for token in normalized.split() if token not in removable_tokens]
    stripped = " ".join(stripped_tokens).strip()
    return bool(stripped) and stripped in soft_close_replies


def _is_explicit_deferral_after_quote(normalized: str) -> bool:
    return normalized in {
        _normalize(item) for item in _EXPLICIT_DEFERRAL_AFTER_QUOTE_REPLIES
    }


def _is_deictic_affirmation(normalized: str) -> bool:
    tokens = set(normalized.split())
    return bool(tokens & _DEICTIC_TERMS) and bool(
        tokens & {_normalize(item) for item in _AFFIRMATIVE_REPLIES}
    )


def _confirmation_requests_requirements(request: AcknowledgementPolicyRequest) -> bool:
    if _updates_request_requirements(request.pending_confirmation_updates):
        return True
    try:
        parsed = json.loads(request.pending_confirmation or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(parsed, dict):
        return False
    yes_branch = parsed.get("yes")
    return isinstance(yes_branch, dict) and _updates_request_requirements(yes_branch)


def _updates_request_requirements(updates: dict[str, Any]) -> bool:
    return any(
        str(key).strip().upper() in {"REQUISITOS_SOLICITADOS", "DOCUMENTOS_SOLICITADOS"}
        for key in updates
    )


def _concrete_question_target(last_bot_norm: str) -> str | None:
    if not last_bot_norm:
        return None
    if _is_yes_no_question(last_bot_norm):
        return None
    if (
        ("modelo" in last_bot_norm or "moto" in last_bot_norm or "categoria" in last_bot_norm)
        and any(term in last_bot_norm for term in ("dime", "que", "cual", "interesa", "quieres"))
    ):
        return "model"
    if (
        any(term in last_bot_norm for term in ("ingresos", "nomina", "por fuera"))
        and any(term in last_bot_norm for term in ("dime", "como", "recibes", "pagan"))
    ):
        return "income_type"
    if "antiguedad" in last_bot_norm or "cuanto tiempo" in last_bot_norm:
        return "employment_seniority"
    if (
        ("enganche" in last_bot_norm or "anticipo" in last_bot_norm)
        and any(
            term in last_bot_norm
            for term in (
                "dime",
                "cuanto enganche",
                "que enganche",
                "cual enganche",
                "quieres manejar",
            )
        )
    ):
        return "down_payment"
    return None


def _option_question_target(last_bot_norm: str) -> str | None:
    if not last_bot_norm:
        return None
    if "opciones" in last_bot_norm and any(
        term in last_bot_norm
        for term in (
            "nomina tarjeta",
            "nomina recibos",
            "sin comprobantes",
            "pensionados",
            "negocio sat",
            "guardia de seguridad",
        )
    ):
        return "income_type_options"
    if " o " not in f" {last_bot_norm} ":
        return None
    if any(term in last_bot_norm for term in ("modelo", "moto", "r4", "skeleton", "comando")):
        return "model"
    if any(
        term in last_bot_norm
        for term in ("tarjeta", "efectivo", "nomina", "por fuera", "comprobantes")
    ):
        return "income_type"
    if any(term in last_bot_norm for term in ("banco", "bbva", "banamex", "santander")):
        return "bank"
    if any(term in last_bot_norm for term in ("documento", "ine", "comprobante", "recibo")):
        return "document"
    return None


def _concrete_question_hint(target: str) -> str:
    if target == "income_type":
        return (
            "Va, para avanzar con el credito solo me falta saber como recibes tus ingresos: "
            "nomina o por fuera."
        )
    if target == "model":
        return "Va, para avanzar solo me falta saber que modelo o moto te interesa."
    if target == "down_payment":
        return "Va, para avanzar solo me falta saber que enganche quieres manejar."
    if target == "employment_seniority":
        return "Va, para avanzar solo me falta saber cuanto tiempo llevas en tu empleo actual."
    return "Va, para avanzar solo me falta ese dato concreto."


def _option_question_hint(target: str) -> str:
    if target == "income_type_options":
        return (
            "Va, pero para ubicarte bien dime cual opcion aplica: "
            "nomina, con recibos o por fuera."
        )
    if target == "income_type":
        return "Va, pero para ubicarte bien dime si te pagan con tarjeta o en efectivo."
    if target == "model":
        return "Va, pero confirmame cual opcion quieres: dime el modelo exacto."
    if target == "bank":
        return "Va, pero confirmame cual banco aplica."
    if target == "document":
        return "Va, pero confirmame cual documento me estas indicando."
    return "Va, pero confirmame cual opcion aplica para seguir."


def _is_yes_no_question(last_bot_norm: str) -> bool:
    if not last_bot_norm:
        return False
    return "?" in last_bot_norm and any(
        term in last_bot_norm
        for term in (
            "quieres",
            "te mando",
            "te paso",
            "avanzar",
            "confirmas",
            "uso",
            "usar",
        )
    )


def _last_bot_was_complete_information(last_bot_norm: str) -> bool:
    if not last_bot_norm:
        return False
    if _last_bot_was_quote(last_bot_norm):
        return True
    if any(term in last_bot_norm for term in ("buro", "historial", "revision")):
        return True
    if "catalogo" in last_bot_norm or "modelos disponibles" in last_bot_norm:
        return True
    if "opciones" in last_bot_norm and any(
        term in last_bot_norm for term in ("motos", "modelos", "catalogo")
    ):
        return True
    return False


def _last_bot_was_quote(message: str) -> bool:
    return "enganche" in message and any(
        term in message for term in ("quincenal", "contado", "pago")
    )


def _recent_quote_context(
    *,
    last_bot_norm: str,
    history: list[tuple[str, str]],
) -> bool:
    if _last_bot_was_quote(last_bot_norm):
        return True
    outbound = [
        _normalize(text)
        for direction, text in history[-6:]
        if str(direction).lower() == "outbound"
    ]
    return any(_last_bot_was_quote(text) for text in outbound)


def _is_nonsense_without_commercial_signal(
    normalized: str,
    request: AcknowledgementPolicyRequest,
) -> bool:
    if not normalized or _is_short_acknowledgement(normalized):
        return False
    tokens = set(normalized.split())
    if tokens & {"que", "como", "cual", "cuanto", "ocupo", "necesito"}:
        return False
    if tokens & _GREETING_TERMS:
        return False
    if tokens & _SOFT_OFF_TOPIC_TERMS:
        return False
    if tokens & _COMMERCIAL_TERMS:
        return False
    category = str(request.operational_intent_category or "").strip().lower()
    if category not in {"", "unknown", "none"}:
        return False
    if request.current_state:
        return False
    return len(tokens) >= 2


__all__ = [
    "AcknowledgementPolicyRequest",
    "AcknowledgementPolicyResult",
    "classify_acknowledgement",
]

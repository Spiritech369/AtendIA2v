from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from atendia.text_normalization import normalize_whatsapp_text


ComplaintClassification = Literal[
    "unclassified",
    "no_complaint",
    "mild_frustration",
    "process_complaint",
    "human_request",
    "payment_sensitive",
    "strong_complaint",
    "legal_threat",
    "advisor_promise_conflict",
]


_SHORT_CONFIRMATIONS = {"si", "ok", "okay", "va", "claro", "correcto", "sale", "simon"}
_PROTECTED_STAGES = {
    "nuevos",
    "plan",
    "cliente potencial",
    "clientepotencial",
    "potencialcliente",
    "cotizacion",
}
_NO_COMPLAINT_PHRASES = (
    "me pagan por fuera",
    "por fuera",
    "sin comprobantes",
    "no tengo recibos",
    "no me dan recibos",
    "no tengo comprobantes",
    "soy guardia",
    "soy guardia de seguridad",
    "cuanto sale",
    "que ocupo",
    "que necesito",
    "puedo dar menos",
    "esta caro",
)
_COMMERCIAL_TERMS = {
    "credito",
    "enganche",
    "guardia",
    "modelo",
    "moto",
    "nomina",
    "precio",
    "recibos",
    "comprobantes",
    "documentos",
}
_MILD_FRUSTRATION_PHRASES = (
    "no entiendo",
    "ya te dije",
    "me estas preguntando otra vez",
    "otra vez me preguntas",
    "que complicado",
)
_PROCESS_COMPLAINT_PHRASES = (
    "ya te mande eso",
    "ya te lo dije",
    "me estas preguntando lo mismo",
    "no estas entendiendo",
    "nadie me explico",
    "ya te dije eso",
)
_HUMAN_REQUEST_PHRASES = (
    "pasame con alguien",
    "pasame con una persona",
    "quiero hablar con asesor",
    "quiero hablar con una persona",
    "quiero una persona",
    "comunicame con francisco",
    "quiero un humano",
)
_PAYMENT_SENSITIVE_PHRASES = (
    "ya pague",
    "ya di enganche",
    "ya deposite",
    "tengo comprobante de pago",
    "aparte la moto",
    "aparté la moto",
)
_LEGAL_THREAT_TERMS = {"profeco", "demanda", "fraude", "denuncia", "reportar", "reporto"}
_STRONG_COMPLAINT_PHRASES = (
    "pesimo servicio",
    "me estan haciendo perder tiempo",
    "me están haciendo perder tiempo",
    "esto es una estafa",
    "quiero cancelar",
    "me voy a quejar",
)
_ADVISOR_PROMISE_PHRASES = (
    "francisco me dijo otra cosa",
    "en agencia me dijeron que si",
    "ya me habian aprobado",
    "ya me habían aprobado",
    "me prometieron 10",
    "otro asesor me dijo",
)


@dataclass(frozen=True)
class ComplaintPolicyResult:
    classification: ComplaintClassification = "unclassified"
    severity: Literal["none", "low", "high"] = "none"
    handoff_required: bool = False
    pause_bot: bool = False
    runtime_action: str = "continue_sales_funnel"
    confidence: float = 0.0
    matched_terms: list[str] = field(default_factory=list)

    @property
    def policy_signal(self) -> str | None:
        if self.classification == "unclassified":
            return None
        return f"complaint_policy:{self.classification}"

    @property
    def pattern_signals(self) -> list[str]:
        out: list[str] = []
        for term in self.matched_terms:
            out.append(f"complaint_pattern:{term.replace(' ', '_')}")
        return out

    @property
    def is_strong_trigger(self) -> bool:
        return self.classification in {
            "human_request",
            "payment_sensitive",
            "strong_complaint",
            "legal_threat",
            "advisor_promise_conflict",
        }


def classify_complaint_policy(
    *,
    text: str,
    current_stage: str | None = None,
    state: dict[str, object] | None = None,
) -> ComplaintPolicyResult:
    del state
    normalized = _normalize(text)
    if not normalized:
        return ComplaintPolicyResult()

    if _contains_phrase(normalized, _HUMAN_REQUEST_PHRASES):
        return ComplaintPolicyResult(
            classification="human_request",
            severity="high",
            handoff_required=True,
            pause_bot=True,
            runtime_action="handoff",
            confidence=0.98,
            matched_terms=_matched_terms(normalized, _HUMAN_REQUEST_PHRASES),
        )

    if _contains_phrase(normalized, _PAYMENT_SENSITIVE_PHRASES):
        return ComplaintPolicyResult(
            classification="payment_sensitive",
            severity="high",
            handoff_required=True,
            pause_bot=True,
            runtime_action="handoff",
            confidence=0.98,
            matched_terms=_matched_terms(normalized, _PAYMENT_SENSITIVE_PHRASES),
        )

    if _has_legal_threat(normalized):
        return ComplaintPolicyResult(
            classification="legal_threat",
            severity="high",
            handoff_required=True,
            pause_bot=True,
            runtime_action="handoff",
            confidence=0.98,
            matched_terms=_matched_terms(normalized, tuple(_LEGAL_THREAT_TERMS)),
        )

    if _contains_phrase(normalized, _ADVISOR_PROMISE_PHRASES):
        return ComplaintPolicyResult(
            classification="advisor_promise_conflict",
            severity="high",
            handoff_required=True,
            pause_bot=True,
            runtime_action="handoff",
            confidence=0.96,
            matched_terms=_matched_terms(normalized, _ADVISOR_PROMISE_PHRASES),
        )

    if _contains_phrase(normalized, _STRONG_COMPLAINT_PHRASES):
        return ComplaintPolicyResult(
            classification="strong_complaint",
            severity="high",
            handoff_required=True,
            pause_bot=True,
            runtime_action="handoff",
            confidence=0.96,
            matched_terms=_matched_terms(normalized, _STRONG_COMPLAINT_PHRASES),
        )

    if _is_short_confirmation(normalized):
        return ComplaintPolicyResult(
            classification="no_complaint",
            severity="none",
            runtime_action="continue_sales_funnel",
            confidence=0.98,
            matched_terms=[normalized],
        )

    if _contains_phrase(normalized, _NO_COMPLAINT_PHRASES) or _is_commercial_only(normalized):
        return ComplaintPolicyResult(
            classification="no_complaint",
            severity="none",
            runtime_action="continue_sales_funnel",
            confidence=0.9,
            matched_terms=_matched_terms(normalized, _NO_COMPLAINT_PHRASES),
        )

    if _contains_phrase(normalized, _PROCESS_COMPLAINT_PHRASES):
        return ComplaintPolicyResult(
            classification="process_complaint",
            severity="low",
            runtime_action="continue_sales_with_state_ack",
            confidence=0.9,
            matched_terms=_matched_terms(normalized, _PROCESS_COMPLAINT_PHRASES),
        )

    if _contains_phrase(normalized, _MILD_FRUSTRATION_PHRASES):
        return ComplaintPolicyResult(
            classification="mild_frustration",
            severity="low",
            runtime_action="continue_sales_with_empathy",
            confidence=0.86,
            matched_terms=_matched_terms(normalized, _MILD_FRUSTRATION_PHRASES),
        )

    if _normalize_stage(current_stage) in _PROTECTED_STAGES and _has_commercial_hint(normalized):
        return ComplaintPolicyResult(
            classification="no_complaint",
            severity="none",
            runtime_action="continue_sales_funnel",
            confidence=0.82,
            matched_terms=[],
        )

    return ComplaintPolicyResult()


def _normalize(value: str) -> str:
    return normalize_whatsapp_text(value)


def _normalize_stage(value: str | None) -> str:
    return _normalize(str(value or ""))


def _contains_phrase(normalized: str, phrases: tuple[str, ...]) -> bool:
    return any(_normalize(phrase) in normalized for phrase in phrases)


def _matched_terms(normalized: str, phrases: tuple[str, ...]) -> list[str]:
    return [_normalize(phrase) for phrase in phrases if _normalize(phrase) in normalized]


def _is_short_confirmation(normalized: str) -> bool:
    return normalized in _SHORT_CONFIRMATIONS


def _has_commercial_hint(normalized: str) -> bool:
    tokens = set(normalized.split())
    return bool(tokens & _COMMERCIAL_TERMS)


def _is_commercial_only(normalized: str) -> bool:
    return _has_commercial_hint(normalized) and not (
        _has_legal_threat(normalized)
        or _contains_phrase(normalized, _HUMAN_REQUEST_PHRASES)
        or _contains_phrase(normalized, _PAYMENT_SENSITIVE_PHRASES)
        or _contains_phrase(normalized, _ADVISOR_PROMISE_PHRASES)
        or _contains_phrase(normalized, _STRONG_COMPLAINT_PHRASES)
    )


def _has_legal_threat(normalized: str) -> bool:
    tokens = set(normalized.split())
    return bool(tokens & _LEGAL_THREAT_TERMS)


__all__ = ["ComplaintPolicyResult", "classify_complaint_policy"]

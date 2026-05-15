"""Keyword-based NLU fallback for dev/tests when OpenAI is off.

Phase 3a substitutes this with `OpenAINLU` for production. KeywordNLU stays
available via the `nlu_provider="keyword"` Settings toggle as a kill-switch.
"""

from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_protocol import UsageMetadata

# Keyword tables — order = priority. First match wins.
_INTENT_KEYWORDS: list[tuple[Intent, list[str]]] = [
    (Intent.GREETING, ["hola", "buenos días", "buenas", "qué tal", "saludos"]),
    (Intent.BUY, ["la quiero", "lo quiero", "dame el link", "comprar", "pagar"]),
    (Intent.ASK_PRICE, ["cuánto cuesta", "cuanto cuesta", "precio", "costo", "valor"]),
    (Intent.COMPLAIN, ["mal servicio", "horrible", "terrible", "queja", "no me responden"]),
    (Intent.SCHEDULE, ["agendar", "cita", "horario", "cuándo puedo"]),
    (Intent.ASK_INFO, ["info", "información", "detalles", "qué incluye", "cómo funciona"]),
]


_NEGATIVE_KEYWORDS = ["mal", "horrible", "terrible", "fatal", "pésimo"]


class KeywordNLU:
    """Stateless keyword-based NLU. Conforms to NLUProvider Protocol."""

    async def classify(
        self,
        *,
        text: str,
        current_stage: str,
        required_fields: list[FieldSpec],
        optional_fields: list[FieldSpec],
        history: list[tuple[str, str]],
    ) -> tuple[NLUResult, UsageMetadata | None]:
        return self._classify(text), None

    def _classify(self, text: str) -> NLUResult:
        lowered = text.lower()
        intent = Intent.OFF_TOPIC
        confidence = 0.4
        for candidate_intent, keywords in _INTENT_KEYWORDS:
            if any(kw in lowered for kw in keywords):
                intent = candidate_intent
                confidence = 0.85
                break

        sentiment = Sentiment.NEUTRAL
        if intent == Intent.COMPLAIN or any(kw in lowered for kw in _NEGATIVE_KEYWORDS):
            sentiment = Sentiment.NEGATIVE

        return NLUResult(
            intent=intent,
            entities={},
            sentiment=sentiment,
            confidence=confidence,
            ambiguities=[],
        )

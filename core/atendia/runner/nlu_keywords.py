"""Keyword-based NLU fallback for Phase 2 (no LLM yet).

Replaces `CannedNLU` for production use during Phase 2. Phase 3 will replace
this with a real `gpt-4o-mini` extractor — same `next()` API contract.
"""
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment


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
    """Stateful keyword-based NLU. Feed text, then call next() to get NLUResult."""

    def __init__(self) -> None:
        self._queue: list[NLUResult] = []

    def feed(self, text: str) -> None:
        """Classify a text and queue the result for `next()`."""
        self._queue.append(self._classify(text))

    def next(self) -> NLUResult:
        if not self._queue:
            raise IndexError("no NLU result available; call feed() first")
        return self._queue.pop(0)

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

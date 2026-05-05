"""Canned Composer: returns hardcoded text per action.

Used as:
- Default when composer_provider="canned" (Phase 2 behavior preserved).
- Fallback when OpenAIComposer's retries exhaust (T16+).
"""
from atendia.runner.composer_protocol import (
    ComposerInput, ComposerOutput, UsageMetadata,
)


class CannedComposer:
    _TEXTS: dict[str, str] = {
        "greet": "¡Hola! Soy tu asistente. ¿En qué te puedo ayudar?",
        "ask_field": "Me podrías compartir más detalles?",
        "lookup_faq": "Déjame revisar nuestra información para responderte.",
        "ask_clarification": "Disculpa, no te entendí del todo. ¿Podrías reformular?",
        "quote": "El precio depende del modelo y opciones. ¿Cuál te interesa? Te paso el costo exacto.",
        "explain_payment_options": "Aceptamos efectivo, transferencia y crédito. ¿Cuál te conviene?",
        "close": "¡Perfecto! Te paso el siguiente paso para cerrar.",
    }

    async def compose(
        self, *, input: ComposerInput,
    ) -> tuple[ComposerOutput, UsageMetadata | None]:
        text = self._TEXTS.get(
            input.action,
            "Disculpa, déjame consultar y te paso la info.",
        )
        return ComposerOutput(messages=[text]), None

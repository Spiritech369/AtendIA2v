from __future__ import annotations

import re

from atendia.contracts.turn_resolution import Evidence, ResolverAttempt, TurnResolverInput

_REFERENCE_RE = re.compile(
    r"\b(esa|ese|eso|la otra|el otro|la roja|el rojo|la azul|el azul|la negra|el negro)\b",
    flags=re.IGNORECASE,
)


class ReferenceResolver:
    """Handle deictic references without writing state automatically."""

    name = "reference_resolver"

    async def resolve(self, input: TurnResolverInput) -> ResolverAttempt | None:
        text = (input.inbound_text or "").strip()
        if not text or _REFERENCE_RE.search(text) is None:
            return None

        current_product = self._current_product(input)
        if current_product:
            clarification = f"Te refieres a {current_product}? Te lo confirmo antes de avanzar."
            evidence_value = current_product
            blocked_reason = "reference_requires_confirmation"
            confidence = 0.62
        else:
            clarification = (
                "Que modelo quieres revisar? Mandame el nombre para buscarlo en catalogo."
            )
            evidence_value = None
            blocked_reason = "no_clear_last_product"
            confidence = 0.45

        return ResolverAttempt(
            resolver=self.name,
            input=text,
            understood_as="product_reference",
            evidence=[
                Evidence(
                    type="history",
                    source="conversation_context",
                    value=evidence_value,
                    confidence=confidence,
                )
            ],
            confidence=confidence,
            can_write_state=False,
            requires_confirmation=True,
            suggested_clarification=clarification,
            blocked_reason=blocked_reason,
        )

    @staticmethod
    def _current_product(input: TurnResolverInput) -> str | None:
        for key in ("MOTO", "PRODUCTO", "PRODUCTO_INTERES", "producto_interes"):
            value = input.extracted_data.get(key)
            if isinstance(value, dict):
                value = value.get("value")
            if value not in (None, "", [], {}):
                return str(value)
        return None

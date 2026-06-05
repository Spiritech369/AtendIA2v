from __future__ import annotations

import json
import unicodedata
from typing import Any

from atendia.contracts.turn_resolution import Evidence, ResolverAttempt, TurnResolverInput

_AFFIRMATIVE = frozenset({"si", "s", "claro", "ok", "okay", "yes", "ya", "sip", "simon"})
_NEGATIVE = frozenset({"no", "n", "nop", "nada", "nel"})


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.strip().casefold()


def _yes_no(value: str) -> str | None:
    normalized = _normalize(value)
    if normalized in _AFFIRMATIVE:
        return "yes"
    if normalized in _NEGATIVE:
        return "no"
    return None


def _pending_side_effects(pending_confirmation: str | None, branch: str) -> dict[str, Any]:
    if not pending_confirmation:
        return {}
    try:
        parsed = json.loads(pending_confirmation)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    side_effects = parsed.get(branch)
    if not isinstance(side_effects, dict):
        return {}
    return {
        str(key).strip(): value
        for key, value in side_effects.items()
        if str(key).strip() and value not in (None, "")
    }


class LastQuestionResolver:
    """Resolve yes/no only when pending_confirmation encodes side effects."""

    name = "last_question_resolver"

    async def resolve(self, input: TurnResolverInput) -> ResolverAttempt | None:
        branch = _yes_no(input.inbound_text)
        if branch is None:
            return None
        if not input.pending_confirmation:
            return ResolverAttempt(
                resolver=self.name,
                input=input.inbound_text,
                understood_as=branch,
                evidence=[
                    Evidence(
                        type="last_question",
                        source="pending_confirmation",
                        value="missing",
                        confidence=0.4,
                    )
                ],
                confidence=0.4,
                can_write_state=False,
                blocked_reason="no_pending_confirmation",
            )

        field_updates = _pending_side_effects(input.pending_confirmation, branch)
        if not field_updates:
            return ResolverAttempt(
                resolver=self.name,
                input=input.inbound_text,
                understood_as=branch,
                evidence=[
                    Evidence(
                        type="last_question",
                        source="pending_confirmation",
                        value="no_side_effects",
                        confidence=0.55,
                    )
                ],
                confidence=0.55,
                can_write_state=False,
                requires_confirmation=True,
                blocked_reason="pending_confirmation_without_side_effects",
                suggested_clarification=(
                    "Me confirmas con un poco mas de detalle para avanzar bien?"
                ),
            )

        return ResolverAttempt(
            resolver=self.name,
            input=input.inbound_text,
            understood_as=branch,
            evidence=[
                Evidence(
                    type="last_question",
                    source="pending_confirmation",
                    value=branch,
                    confidence=0.98,
                )
            ],
            confidence=0.98,
            can_write_state=True,
            requires_confirmation=False,
            field_updates=field_updates,
            next_action="continue_flow",
        )

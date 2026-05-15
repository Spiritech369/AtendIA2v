"""Regex-only risky-phrase detector.

Flags claims a Spanish-MX dealer-bot must not make verbatim (e.g. "crédito
aprobado", "entrega garantizada", "precio fijo"). Each entry has a
``pattern`` and a ``rewrite`` — the rewrite is a hint shown to the
operator in the PromptPreviewDrawer so they can replace the source text.

TODO(kb-followup-10): the full design called for an LLM rewrite pass.
B2 ships regex-only flagging — the rewrite suggestion is the seeded
canonical phrase, not a per-context LLM completion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_RISKY_PHRASES: list[dict[str, str]] = [
    {"pattern": r"crédito\s+aprobado", "rewrite": "Podemos revisar tu crédito"},
    {"pattern": r"aprobado\s+seguro", "rewrite": "Sujeto a validación"},
    {"pattern": r"sin\s+revisar\s+buró", "rewrite": "Sujeto a evaluación crediticia"},
    {"pattern": r"entrega\s+garantizada", "rewrite": "Sujeto a disponibilidad"},
    {"pattern": r"precio\s+fijo", "rewrite": "Depende del plan y documentación"},
    {
        "pattern": r"no\s+necesitas\s+comprobar\s+ingresos",
        "rewrite": "Un asesor confirma documentación",
    },
]


@dataclass(slots=True)
class Risk:
    type: str
    description: str
    pattern: str


def detect_risky_phrases(
    text: str,
    custom: list[dict[str, str]] | None = None,
) -> list[Risk]:
    """Scan ``text`` for risky-phrase patterns.

    ``custom`` overrides the seeded defaults entirely (per-tenant
    customization comes from ``kb_safe_answer_settings.risky_phrases``).
    """
    risks: list[Risk] = []
    for entry in custom if custom is not None else DEFAULT_RISKY_PHRASES:
        if re.search(entry["pattern"], text, re.IGNORECASE):
            risks.append(
                Risk(
                    type="risky_phrase",
                    description=entry.get("rewrite", ""),
                    pattern=entry["pattern"],
                )
            )
    return risks

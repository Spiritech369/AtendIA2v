from __future__ import annotations

import re
import unicodedata
from typing import Any

from atendia.contracts.turn_resolution import Evidence, ResolverAttempt, TurnResolverInput

_AFFIRMATIVE_SELECTIONS = frozenset(
    {"si", "claro", "ok", "sale", "va", "esa", "ese", "eso", "esta", "este"}
)
_ORDINAL_INDEX = {
    "1": 0,
    "uno": 0,
    "primera": 0,
    "primero": 0,
    "2": 1,
    "dos": 1,
    "segunda": 1,
    "segundo": 1,
    "3": 2,
    "tres": 2,
    "tercera": 2,
    "tercero": 2,
}
_SELECTION_STOPWORDS = frozenset(
    {
        "de",
        "del",
        "el",
        "esa",
        "ese",
        "eso",
        "esta",
        "este",
        "la",
        "las",
        "lo",
        "los",
        "me",
        "quiero",
        "la",
        "una",
        "un",
    }
)
_CATALOG_CONTEXT_HINTS = (
    "catalogo",
    "modelo",
    "modelos",
    "opciones",
    "te refieres",
    "cual quieres revisar",
    "te ayudo a cotizarla",
)
_CATALOG_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$")
_QUOTE_LINE_RE = re.compile(r"\b(?:la|el)\s+(.+?)\s+de contado\b", flags=re.IGNORECASE)
_STRUCTURED_CANDIDATE_KEYS = ("_LAST_CATALOG_CANDIDATES", "LAST_CATALOG_CANDIDATES")
_STRUCTURED_PREVIOUS_MODEL_KEYS = ("_LAST_CATALOG_PREVIOUS_MODEL", "LAST_CATALOG_PREVIOUS_MODEL")


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[\W_]+", " ", text.casefold(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _selection_tokens(value: str) -> list[str]:
    tokens = []
    for token in _normalize(value).split():
        if token in _SELECTION_STOPWORDS:
            continue
        if len(token) <= 1 and not token.isdigit():
            continue
        tokens.append(token)
    return tokens


def _candidate_lines(message: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(message or "").splitlines():
        match = _CATALOG_LINE_RE.match(raw_line.strip())
        if match is None:
            continue
        value = match.group(1).strip()
        normalized = _normalize(value)
        if not value or normalized.startswith("catalogo completo"):
            continue
        lines.append(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = _normalize(line)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(line)
    return deduped


def _recent_quote_model(history: list[tuple[str, str]]) -> str | None:
    for role, text in reversed(history[-8:]):
        if role != "outbound" or not text:
            continue
        raw = str(text or "").strip()
        normalized = _normalize(raw)
        if "$" not in raw or not any(
            marker in normalized for marker in ("enganche", "quincenal", "contado", "plazo")
        ):
            continue
        match = _QUOTE_LINE_RE.search(raw.replace("\n", " "))
        if match is not None:
            candidate = str(match.group(1) or "").strip(" .,:;!?")
            if candidate:
                return candidate
    return None


def _recent_catalog_candidates(history: list[tuple[str, str]]) -> list[str]:
    for role, text in reversed(history[-6:]):
        if role != "outbound" or not text:
            continue
        candidates = _candidate_lines(text)
        if not candidates:
            continue
        normalized_text = _normalize(text)
        if any(hint in normalized_text for hint in _CATALOG_CONTEXT_HINTS):
            return candidates[:3]
    return []


def _state_value(raw: Any) -> Any:
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    if hasattr(raw, "value"):
        return getattr(raw, "value")
    return raw


def _structured_catalog_candidates(extracted_data: dict[str, Any]) -> list[str]:
    for key in _STRUCTURED_CANDIDATE_KEYS:
        raw = _state_value(extracted_data.get(key))
        if not isinstance(raw, list):
            continue
        candidates: list[str] = []
        seen: set[str] = set()
        for item in raw:
            name = str(item or "").strip()
            normalized = _normalize(name)
            if not name or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(name)
        if candidates:
            return candidates[:3]
    return []


def _structured_previous_model(extracted_data: dict[str, Any]) -> str | None:
    for key in _STRUCTURED_PREVIOUS_MODEL_KEYS:
        raw = _state_value(extracted_data.get(key))
        value = str(raw or "").strip()
        if value:
            return value
    return None


def _ordinal_selection_index(inbound_text: str) -> int | None:
    normalized = _normalize(inbound_text)
    if normalized in _ORDINAL_INDEX:
        return _ORDINAL_INDEX[normalized]
    if normalized.startswith("la "):
        tail = normalized[3:].strip()
        return _ORDINAL_INDEX.get(tail)
    if normalized.startswith("el "):
        tail = normalized[3:].strip()
        return _ORDINAL_INDEX.get(tail)
    return None


def _matching_candidates(inbound_text: str, candidates: list[str]) -> list[str]:
    normalized_inbound = _normalize(inbound_text)
    if normalized_inbound in _AFFIRMATIVE_SELECTIONS:
        return list(candidates[:1]) if len(candidates) == 1 else []

    query_tokens = _selection_tokens(inbound_text)
    if not query_tokens:
        return []

    matches: list[str] = []
    for candidate in candidates:
        candidate_tokens = set(_selection_tokens(candidate))
        if not candidate_tokens:
            continue
        if all(token in candidate_tokens for token in query_tokens):
            matches.append(candidate)
    return matches


def _clarification_text(candidates: list[str]) -> str:
    options = "\n".join(
        f"{index}. {candidate}" for index, candidate in enumerate(candidates[:3], start=1)
    )
    return f"Te paso las opciones que tengo:\n{options}\n\nDime cual quieres revisar."


class CatalogContextResolver:
    """Resolve catalog follow-ups from recent outbound options."""

    name = "catalog_context_resolver"

    async def resolve(self, input: TurnResolverInput) -> ResolverAttempt | None:
        candidates = _recent_catalog_candidates(input.history)
        if not candidates:
            candidates = _structured_catalog_candidates(input.extracted_data)
        if not candidates:
            return None
        previous_model = _recent_quote_model(input.history) or _structured_previous_model(
            input.extracted_data
        )

        selection_index = _ordinal_selection_index(input.inbound_text)
        if selection_index is not None:
            if 0 <= selection_index < len(candidates):
                selected = candidates[selection_index]
                metadata = {
                    "catalog_candidates": candidates,
                    "resolved_from_context": True,
                    "selection_mode": "ordinal",
                    "selected_candidate_index": selection_index,
                    "selected_catalog_candidate": selected,
                }
                if previous_model:
                    metadata["previous_model"] = previous_model
                    metadata["new_model"] = selected
                    metadata["model_change_candidate"] = _normalize(previous_model) != _normalize(
                        selected
                    )
                return ResolverAttempt(
                    resolver=self.name,
                    input=input.inbound_text,
                    understood_as=selected,
                    evidence=[
                        Evidence(
                            type="history",
                            source="recent_catalog_candidates",
                            value=selected,
                            confidence=0.96,
                            metadata=metadata,
                        )
                    ],
                    confidence=0.96,
                    can_write_state=True,
                    requires_confirmation=False,
                    field_updates={"MOTO": selected},
                    next_action="quote_or_ask_missing_plan",
                )
            return ResolverAttempt(
                resolver=self.name,
                input=input.inbound_text,
                understood_as="catalog_selection_out_of_range",
                evidence=[
                    Evidence(
                        type="history",
                        source="recent_catalog_candidates",
                        value=candidates,
                        confidence=0.52,
                    )
                ],
                confidence=0.52,
                can_write_state=False,
                requires_confirmation=True,
                suggested_clarification=_clarification_text(candidates),
                blocked_reason="catalog_selection_out_of_range",
            )

        matches = _matching_candidates(input.inbound_text, candidates)
        if len(matches) == 1:
            selected = matches[0]
            metadata = {
                "catalog_candidates": candidates,
                "resolved_from_context": True,
                "selection_mode": "semantic_followup",
                "selected_catalog_candidate": selected,
                "selected_candidate_index": candidates.index(selected),
            }
            if previous_model:
                metadata["previous_model"] = previous_model
                metadata["new_model"] = selected
                metadata["model_change_candidate"] = _normalize(previous_model) != _normalize(
                    selected
                )
            return ResolverAttempt(
                resolver=self.name,
                input=input.inbound_text,
                understood_as=selected,
                evidence=[
                    Evidence(
                            type="history",
                            source="recent_catalog_candidates",
                            value=selected,
                            confidence=0.94,
                            metadata=metadata,
                        )
                    ],
                    confidence=0.94,
                can_write_state=True,
                requires_confirmation=False,
                field_updates={"MOTO": selected},
                next_action="quote_or_ask_missing_plan",
            )
        if len(matches) > 1:
            return ResolverAttempt(
                resolver=self.name,
                input=input.inbound_text,
                understood_as="catalog_selection_ambiguous",
                evidence=[
                    Evidence(
                        type="history",
                        source="recent_catalog_candidates",
                        value=matches,
                        confidence=0.58,
                    )
                ],
                confidence=0.58,
                can_write_state=False,
                requires_confirmation=True,
                suggested_clarification=_clarification_text(matches),
                blocked_reason="catalog_selection_ambiguous",
            )
        return None

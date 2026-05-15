"""Regex-only conflict detector for the KB module.

Three detection types per design §6:

* ``price_mismatch`` — different ``$<amount>`` patterns across chunks
* ``enum_disagreement`` — different ``N%`` figures qualified by
  ``enganche / down / cuota`` across chunks
* ``text_overlap_with_negation`` — Jaccard similarity ≥ 0.4 between two
  chunks where exactly one contains a negation token (``no | sin | nunca``)

No LLM calls. Designed to run synchronously over the top-K retrieval
result on every /test-query, plus periodically (worker job) to surface
conflicts the operator hasn't seen yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

from pydantic import BaseModel


# TODO(kb-followup-10): expand price detector to handle EUR/USD currency
# variants and locale-specific separators (1.234,56 etc).
_PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:[.,]\d{3})*(?:\.\d{2})?)")
# Match either order: "10% enganche" or "Enganche desde 10%". The keyword
# may sit up to ~30 chars from the percentage so phrases like
# "Enganche mínimo 15%" still trigger.
_ENUM_KEYWORDS = r"(?:enganche|down\s+payment|cuota)"
_ENUM_RE = re.compile(
    rf"(?:(\d{{1,3}})\s*%\s*(?:de\s+)?{_ENUM_KEYWORDS}"
    rf"|{_ENUM_KEYWORDS}[^%\n]{{0,30}}?(\d{{1,3}})\s*%)",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"\b(no|sin|nunca)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-záéíóúñ0-9]+", re.IGNORECASE)

_NEGATION_JACCARD_THRESHOLD = 0.4
_EXCERPT_MAX_CHARS = 240


class ChunkLike(BaseModel):
    """Minimal shape the detector needs from a retrieved chunk.

    Real ``KnowledgeChunk`` rows can be adapted to this via a
    factory method or kept as-is — the detector only reads ``text``,
    ``source_type``, and ``source_id``.
    """

    text: str
    source_type: str
    source_id: str


@dataclass(slots=True)
class DetectedConflict:
    detection_type: str
    title: str
    severity: str
    entity_a_type: str
    entity_a_id: str
    entity_a_excerpt: str
    entity_b_type: str
    entity_b_id: str
    entity_b_excerpt: str


def _excerpt(text: str) -> str:
    return text[:_EXCERPT_MAX_CHARS].strip()


def _normalize_price(raw: str) -> str:
    """Strip thousand separators so '$45,000' and '$45.000' compare equal."""
    return raw.replace(",", "").replace(".", "").lstrip("0") or "0"


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _has_negation(text: str) -> bool:
    return bool(_NEGATION_RE.search(text))


def _detect_price_mismatch(a: ChunkLike, b: ChunkLike) -> DetectedConflict | None:
    prices_a = _PRICE_RE.findall(a.text)
    prices_b = _PRICE_RE.findall(b.text)
    if not prices_a or not prices_b:
        return None
    norm_a = {_normalize_price(p) for p in prices_a}
    norm_b = {_normalize_price(p) for p in prices_b}
    if norm_a == norm_b or norm_a & norm_b:
        return None
    return DetectedConflict(
        detection_type="price_mismatch",
        title=f"Precios distintos: ${prices_a[0]} vs ${prices_b[0]}",
        severity="high",
        entity_a_type=a.source_type,
        entity_a_id=a.source_id,
        entity_a_excerpt=_excerpt(a.text),
        entity_b_type=b.source_type,
        entity_b_id=b.source_id,
        entity_b_excerpt=_excerpt(b.text),
    )


def _detect_enum_disagreement(a: ChunkLike, b: ChunkLike) -> DetectedConflict | None:
    enums_a = {(m.group(1) or m.group(2)) for m in _ENUM_RE.finditer(a.text)}
    enums_b = {(m.group(1) or m.group(2)) for m in _ENUM_RE.finditer(b.text)}
    if not enums_a or not enums_b:
        return None
    if enums_a & enums_b:
        return None
    return DetectedConflict(
        detection_type="enum_disagreement",
        title=f"Porcentaje distinto: {sorted(enums_a)[0]}% vs {sorted(enums_b)[0]}%",
        severity="high",
        entity_a_type=a.source_type,
        entity_a_id=a.source_id,
        entity_a_excerpt=_excerpt(a.text),
        entity_b_type=b.source_type,
        entity_b_id=b.source_id,
        entity_b_excerpt=_excerpt(b.text),
    )


def _detect_text_overlap_negation(a: ChunkLike, b: ChunkLike) -> DetectedConflict | None:
    tokens_a, tokens_b = _tokens(a.text), _tokens(b.text)
    if _jaccard(tokens_a, tokens_b) < _NEGATION_JACCARD_THRESHOLD:
        return None
    neg_a, neg_b = _has_negation(a.text), _has_negation(b.text)
    if neg_a == neg_b:
        return None
    return DetectedConflict(
        detection_type="text_overlap_with_negation",
        title="Posible contradicción: una fuente niega lo que otra afirma",
        severity="medium",
        entity_a_type=a.source_type,
        entity_a_id=a.source_id,
        entity_a_excerpt=_excerpt(a.text),
        entity_b_type=b.source_type,
        entity_b_id=b.source_id,
        entity_b_excerpt=_excerpt(b.text),
    )


_DETECTORS = (
    _detect_price_mismatch,
    _detect_enum_disagreement,
    _detect_text_overlap_negation,
)


def detect_conflicts_in_results(chunks: list[ChunkLike]) -> list[DetectedConflict]:
    """Run all three detectors over the pairwise combinations of ``chunks``.

    Returns at most one conflict per (chunk_a, chunk_b, detection_type)
    triple — short-circuits to the first detector that fires for a pair.
    """
    out: list[DetectedConflict] = []
    for a, b in combinations(chunks, 2):
        for det in _DETECTORS:
            conflict = det(a, b)
            if conflict is not None:
                out.append(conflict)
                # Don't break — same pair can hit multiple detectors
                # (e.g. price and enum disagreement in the same chunk pair).
    return out

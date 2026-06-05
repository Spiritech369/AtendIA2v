"""Phase 3c.1 — semantic FAQ lookup using cosine similarity (pgvector).

`lookup_faq(session, tenant_id, embedding, top_k=3, score_threshold=0.5)`
is the function-style interface the runner (T18) calls directly. The
caller is responsible for generating `embedding` (typically via
`generate_embedding(text=user_message)`) and for accumulating its cost
into `turn_traces.tool_cost_usd`.

Cosine similarity is computed via pgvector's `<=>` operator (cosine
distance, in [0, 2]). We expose `score = 1 - distance` in [-1, 1] but in
practice it lives in [0, 1] for normalized embeddings. The default
threshold 0.5 (design doc decision #10) keeps spurious matches out of
the Composer prompt — when the best FAQ is too far, we'd rather redirect
than answer the wrong question.

`LookupFAQTool(Tool)` is the registry adapter for callers that use the
tool registry instead of importing `lookup_faq()` directly.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantFAQ
from atendia.text_normalization import normalize_whatsapp_text
from atendia.tools.base import FAQMatch, Tool, ToolNoDataResult

_FAQ_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "al",
        "con",
        "cual",
        "cuales",
        "de",
        "del",
        "el",
        "en",
        "es",
        "la",
        "las",
        "lo",
        "los",
        "me",
        "para",
        "por",
        "que",
        "se",
        "si",
        "te",
        "tienen",
        "tiene",
        "un",
        "una",
    }
)


def answer_faq_from_pack(
    *,
    question: str,
    knowledge_pack: Mapping[str, Any] | None,
    score_threshold: float = 0.55,
    allow_tag_only_match: bool = False,
) -> dict[str, Any] | ToolNoDataResult:
    """Resolve a compiled Knowledge Pack FAQ without embeddings."""
    if not isinstance(knowledge_pack, Mapping):
        return ToolNoDataResult(hint="tenant has no knowledge_pack configured")
    faq_policies = knowledge_pack.get("faq_policies")
    if not isinstance(faq_policies, Mapping) or not faq_policies:
        return ToolNoDataResult(hint="knowledge_pack has no faq_policies")

    match = _best_pack_faq_match(
        question=question,
        faq_policies=faq_policies,
        allow_tag_only_match=allow_tag_only_match,
    )
    if match is None or match["score"] < score_threshold:
        return ToolNoDataResult(hint="no knowledge_pack FAQ policy matched the question")

    entry = match["entry"]
    answer = str(entry.get("answer") or "").strip()
    if not answer:
        return ToolNoDataResult(hint=f"knowledge_pack FAQ topic {match['topic']!r} has no answer")
    pack_version = knowledge_pack.get("pack_version")
    question_text = str(entry.get("question") or question).strip()
    topic = str(entry.get("topic") or match["topic"]).strip()
    return {
        "status": "ok",
        "answer": answer,
        "topic": topic,
        "matches": [
            {
                "pregunta": question_text,
                "respuesta": answer,
                "score": match["score"],
                "faq_id": None,
                "collection_id": None,
                "source": "knowledge_pack",
            }
        ],
        "source": {
            "type": "knowledge_pack",
            "topic": topic,
            "knowledge_pack_version": str(pack_version) if pack_version else None,
        },
    }


def answer_faqs_from_pack(
    *,
    question: str,
    knowledge_pack: Mapping[str, Any] | None,
    score_threshold: float = 0.55,
    allow_tag_only_match: bool = False,
    max_matches: int = 3,
) -> list[dict[str, Any]]:
    if not isinstance(knowledge_pack, Mapping):
        return []
    faq_policies = knowledge_pack.get("faq_policies")
    if not isinstance(faq_policies, Mapping) or not faq_policies:
        return []

    question_norm = _faq_text_key(question)
    if not question_norm:
        return []
    question_tokens = _faq_tokens(question_norm)
    ranked: list[dict[str, Any]] = []
    for raw_topic, raw_entries in faq_policies.items():
        entries = raw_entries if isinstance(raw_entries, list) else [raw_entries]
        for raw_entry in entries:
            if not isinstance(raw_entry, Mapping):
                continue
            score = _pack_faq_score(
                question_norm=question_norm,
                question_tokens=question_tokens,
                topic=str(raw_topic),
                entry=raw_entry,
                allow_tag_only_match=allow_tag_only_match,
            )
            if score < score_threshold:
                continue
            answer = str(raw_entry.get("answer") or "").strip()
            if not answer:
                continue
            topic = str(raw_entry.get("topic") or raw_topic).strip()
            question_text = str(raw_entry.get("question") or question).strip()
            ranked.append(
                {
                    "topic": topic,
                    "question": question_text,
                    "answer": answer,
                    "score": score,
                }
            )

    ranked.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    deduped: list[dict[str, Any]] = []
    seen_topics: set[str] = set()
    for item in ranked:
        topic_key = _faq_text_key(str(item.get("topic") or ""))
        if not topic_key or topic_key in seen_topics:
            continue
        seen_topics.add(topic_key)
        deduped.append(item)
        if len(deduped) >= max(1, max_matches):
            break
    return deduped


def _best_pack_faq_match(
    *,
    question: str,
    faq_policies: Mapping[str, Any],
    allow_tag_only_match: bool = False,
) -> dict[str, Any] | None:
    question_norm = _faq_text_key(question)
    if not question_norm:
        return None
    question_tokens = _faq_tokens(question_norm)
    best: dict[str, Any] | None = None
    for raw_topic, raw_entries in faq_policies.items():
        entries = raw_entries if isinstance(raw_entries, list) else [raw_entries]
        for raw_entry in entries:
            if not isinstance(raw_entry, Mapping):
                continue
            score = _pack_faq_score(
                question_norm=question_norm,
                question_tokens=question_tokens,
                topic=str(raw_topic),
                entry=raw_entry,
                allow_tag_only_match=allow_tag_only_match,
            )
            if best is None or score > best["score"]:
                best = {
                    "topic": str(raw_topic),
                    "entry": dict(raw_entry),
                    "score": score,
                }
    return best


def _pack_faq_score(
    *,
    question_norm: str,
    question_tokens: set[str],
    topic: str,
    entry: Mapping[str, Any],
    allow_tag_only_match: bool = False,
) -> float:
    topic_norm = _faq_text_key(str(entry.get("topic") or topic).replace("_", " "))
    entry_question = _faq_text_key(str(entry.get("question") or ""))
    tags = entry.get("tags")
    tag_values = tags if isinstance(tags, list) else []
    tag_norms = [_faq_text_key(str(tag)) for tag in tag_values]

    primary_candidates = [topic_norm, entry_question]
    candidates = [*primary_candidates, *tag_norms]
    if any(candidate and candidate in question_norm for candidate in primary_candidates):
        return 1.0
    if entry_question and question_norm in entry_question:
        return 0.95

    tag_tokens: set[str] = set()
    for tag_norm in tag_norms:
        tag_tokens.update(_faq_tokens(tag_norm))

    candidate_tokens: set[str] = set()
    for candidate in candidates:
        candidate_tokens.update(_faq_tokens(candidate))
    if not candidate_tokens:
        return 0.0
    overlap = question_tokens & candidate_tokens
    if not overlap:
        return 0.0
    topic_tokens = _faq_tokens(topic_norm)
    if len(overlap) == 1 and not (overlap & topic_tokens):
        if allow_tag_only_match and overlap & tag_tokens:
            return 0.72
        return 0.0
    return min(0.9, 0.45 + (len(overlap) / max(len(candidate_tokens), 1)))


def _faq_text_key(value: str) -> str:
    return normalize_whatsapp_text(value, keep_percent=False)


def _faq_tokens(value: str) -> set[str]:
    return {
        token
        for token in _faq_text_key(value).split(" ")
        if token and token not in _FAQ_STOPWORDS and len(token) > 1
    }


async def lookup_faq(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    embedding: list[float],
    top_k: int = 3,
    score_threshold: float = 0.5,
    collection_ids: list[UUID] | None = None,
) -> list[FAQMatch] | ToolNoDataResult:
    """Return the top-k FAQs whose embedding is closest to `embedding`.

    Filters to rows whose cosine similarity score >= `score_threshold`.
    If no row clears the threshold (or the tenant has no embedded FAQs),
    returns `ToolNoDataResult` so the Composer can redirect.

    Rows with `embedding IS NULL` are excluded — the partial-ingestion
    case where some FAQs aren't embedded yet shouldn't break ranking.

    When ``collection_ids`` is non-empty, results are restricted to FAQs
    whose ``collection_id`` is in that list — the runner uses this to
    enforce ``agent.knowledge_config.collection_ids`` so different
    agents on the same tenant can be scoped to different knowledge sets
    (e.g. a "Soporte" agent only sees soporte collections, never sales).
    Empty/None means "no scoping" — every FAQ in the tenant is fair game.
    """
    distance = TenantFAQ.embedding.cosine_distance(embedding)
    stmt = (
        select(TenantFAQ, (1 - distance).label("score"))
        .where(
            TenantFAQ.tenant_id == tenant_id,
            TenantFAQ.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(top_k)
    )
    if collection_ids:
        stmt = stmt.where(TenantFAQ.collection_id.in_(collection_ids))
    rows = (await session.execute(stmt)).all()
    matches = [
        FAQMatch(
            pregunta=faq.question,
            respuesta=faq.answer,
            score=float(score),
            faq_id=faq.id,
            collection_id=faq.collection_id,
        )
        for faq, score in rows
        if float(score) >= score_threshold
    ]
    if not matches:
        return ToolNoDataResult(hint=f"no FAQ above similarity threshold {score_threshold}")
    return matches


class LookupFAQTool(Tool):  # pragma: no cover
    """Registry adapter for the function-style FAQ lookup."""

    name = "lookup_faq"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        # Generating an embedding here would couple this method to the
        # OpenAI client configuration, so callers pass `embedding` directly.
        # If they don't, return ToolNoDataResult so the action_resolver
        # path doesn't crash on a missing key.
        embedding = kwargs.get("embedding")
        if not embedding:
            return ToolNoDataResult(
                hint="lookup_faq requires `embedding` kwarg in Phase 3c.1+",
            ).model_dump(mode="json")
        result = await lookup_faq(
            session=session,
            tenant_id=kwargs["tenant_id"],
            embedding=embedding,
            top_k=kwargs.get("top_k", 3),
            score_threshold=kwargs.get("score_threshold", 0.5),
        )
        if isinstance(result, ToolNoDataResult):
            return result.model_dump(mode="json")
        return {"matches": [m.model_dump(mode="json") for m in result]}

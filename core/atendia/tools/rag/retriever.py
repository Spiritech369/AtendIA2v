"""Agent-scoped retriever for the KB module.

Loads per-(tenant, agent) permissions / priority rules / safe-answer
settings, embeds the query via the configured provider, vector-searches
the three source types (FAQ, Catalog, Document chunks), filters by
agent permissions + publication state + expiration + chunk_status,
applies the min_score gate, sorts by (priority DESC, score DESC), takes
the top 6, and runs the regex conflict detector over the result.

Returns a ``RetrievalResult`` shape that the prompt builder + answer
synthesizer in Tasks 14-15 consume directly.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.kb_agent_permission import KbAgentPermission
from atendia.db.models.kb_collection import KbCollection
from atendia.db.models.kb_safe_answer_setting import KbSafeAnswerSetting
from atendia.db.models.kb_source_priority_rule import KbSourcePriorityRule
from atendia.db.models.knowledge_document import KnowledgeChunk, KnowledgeDocument
from atendia.db.models.tenant_config import TenantCatalogItem, TenantFAQ
from atendia.tools.rag.conflict_detector import (
    ChunkLike,
    DetectedConflict,
    detect_conflicts_in_results,
)


_DEFAULT_TOP_K = 6
_DEFAULT_PRIORITY_BY_SOURCE = {"faq": 100, "catalog": 80, "document": 60}
_DEFAULT_MIN_SCORE = 0.7


class _ProviderLike(Protocol):
    async def create_embedding(self, text: str) -> list[float]: ...


class AgentPermissions(BaseModel):
    agent: str
    allowed_source_types: list[str]
    allowed_collection_slugs: list[str]
    min_score: float
    can_quote_prices: bool
    can_quote_stock: bool
    required_customer_fields: list[str]
    escalate_on_conflict: bool
    fallback_message: str | None = None


class SourcePriorityRule(BaseModel):
    agent: str | None
    source_type: str
    priority: int
    minimum_score: float
    allow_synthesis: bool
    allow_direct_answer: bool
    escalation_required_when_conflict: bool


class SafeAnswerSettings(BaseModel):
    min_score_to_answer: float = _DEFAULT_MIN_SCORE
    escalate_on_conflict: bool = True
    block_invented_prices: bool = True
    block_invented_stock: bool = True
    risky_phrases: list[dict] = []
    default_fallback_message: str = "Déjame validarlo con un asesor para darte la información correcta."


class RetrievedChunk(BaseModel):
    """One ranked chunk in the retrieval result."""

    source_type: str
    source_id: UUID
    text: str
    score: float
    collection: str | None = None
    page: int | None = None
    heading: str | None = None
    document_id: UUID | None = None


class RetrievalResult(BaseModel):
    chunks: list[RetrievedChunk]
    conflicts: list[dict]
    total_candidates: int


# ---------------------------------------------------------------------------
# Settings loaders


async def load_agent_permissions(
    session: AsyncSession, tenant_id: UUID, agent: str
) -> AgentPermissions:
    row = (
        await session.execute(
            select(KbAgentPermission).where(
                KbAgentPermission.tenant_id == tenant_id,
                KbAgentPermission.agent == agent,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        # Tenant never seeded → fall back to a permissive baseline so a
        # bare-DB /test-query still works for dev. Production tenants are
        # always seeded; this branch protects integration tests.
        return AgentPermissions(
            agent=agent,
            allowed_source_types=["faq", "catalog", "document"],
            allowed_collection_slugs=[],
            min_score=_DEFAULT_MIN_SCORE,
            can_quote_prices=False,
            can_quote_stock=False,
            required_customer_fields=[],
            escalate_on_conflict=True,
        )
    return AgentPermissions(
        agent=row.agent,
        allowed_source_types=list(row.allowed_source_types or []),
        allowed_collection_slugs=list(row.allowed_collection_slugs or []),
        min_score=row.min_score,
        can_quote_prices=row.can_quote_prices,
        can_quote_stock=row.can_quote_stock,
        required_customer_fields=list(row.required_customer_fields or []),
        escalate_on_conflict=row.escalate_on_conflict,
        fallback_message=row.fallback_message,
    )


async def load_source_priority_rules(
    session: AsyncSession, tenant_id: UUID, agent: str
) -> list[SourcePriorityRule]:
    """Tenant rules for ``agent``, falling back to the agent=NULL defaults."""
    rows = (
        await session.execute(
            select(KbSourcePriorityRule).where(
                KbSourcePriorityRule.tenant_id == tenant_id,
                or_(
                    KbSourcePriorityRule.agent == agent,
                    KbSourcePriorityRule.agent.is_(None),
                ),
            )
        )
    ).scalars().all()
    out = [
        SourcePriorityRule(
            agent=r.agent,
            source_type=r.source_type,
            priority=r.priority,
            minimum_score=r.minimum_score,
            allow_synthesis=r.allow_synthesis,
            allow_direct_answer=r.allow_direct_answer,
            escalation_required_when_conflict=r.escalation_required_when_conflict,
        )
        for r in rows
    ]
    # Per-agent rules win over agent=NULL defaults — keep both, sorted
    # so the agent rule is consulted first by callers.
    out.sort(key=lambda r: (r.agent is None, r.source_type))
    return out


async def load_safe_answer_settings(
    session: AsyncSession, tenant_id: UUID
) -> SafeAnswerSettings:
    row = (
        await session.execute(
            select(KbSafeAnswerSetting).where(
                KbSafeAnswerSetting.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return SafeAnswerSettings()
    return SafeAnswerSettings(
        min_score_to_answer=row.min_score_to_answer,
        escalate_on_conflict=row.escalate_on_conflict,
        block_invented_prices=row.block_invented_prices,
        block_invented_stock=row.block_invented_stock,
        risky_phrases=list(row.risky_phrases or []),
        default_fallback_message=row.default_fallback_message,
    )


# ---------------------------------------------------------------------------
# Source-specific candidate fetchers


async def _fetch_faq_candidates(
    session: AsyncSession,
    tenant_id: UUID,
    embedding: list[float],
    *,
    allowed_collection_ids: list[UUID] | None,
    include_drafts: bool,
    limit: int,
) -> list[RetrievedChunk]:
    stmt = (
        select(
            TenantFAQ,
            TenantFAQ.embedding.cosine_distance(embedding).label("distance"),
            KbCollection.slug.label("collection_slug"),
        )
        .join(KbCollection, TenantFAQ.collection_id == KbCollection.id, isouter=True)
        .where(
            TenantFAQ.tenant_id == tenant_id,
            TenantFAQ.embedding.is_not(None),
        )
        .order_by("distance")
        .limit(limit)
    )
    if not include_drafts:
        stmt = stmt.where(TenantFAQ.status == "published")
    stmt = stmt.where(
        or_(TenantFAQ.expires_at.is_(None), TenantFAQ.expires_at > datetime.now(UTC))
    )
    if allowed_collection_ids is not None:
        # Empty list = no collection restriction; non-empty = whitelist.
        stmt = stmt.where(TenantFAQ.collection_id.in_(allowed_collection_ids))
    rows = (await session.execute(stmt)).all()
    return [
        RetrievedChunk(
            source_type="faq",
            source_id=row.id,
            text=f"{row.question}\n{row.answer}"[:600],
            score=max(0.0, 1.0 - float(distance or 0.0)),
            collection=collection_slug,
        )
        for row, distance, collection_slug in rows
    ]


async def _fetch_catalog_candidates(
    session: AsyncSession,
    tenant_id: UUID,
    embedding: list[float],
    *,
    allowed_collection_ids: list[UUID] | None,
    include_drafts: bool,
    limit: int,
) -> list[RetrievedChunk]:
    stmt = (
        select(
            TenantCatalogItem,
            TenantCatalogItem.embedding.cosine_distance(embedding).label("distance"),
            KbCollection.slug.label("collection_slug"),
        )
        .join(KbCollection, TenantCatalogItem.collection_id == KbCollection.id, isouter=True)
        .where(
            TenantCatalogItem.tenant_id == tenant_id,
            TenantCatalogItem.embedding.is_not(None),
        )
        .order_by("distance")
        .limit(limit)
    )
    if not include_drafts:
        stmt = stmt.where(TenantCatalogItem.status == "published")
    stmt = stmt.where(
        or_(
            TenantCatalogItem.expires_at.is_(None),
            TenantCatalogItem.expires_at > datetime.now(UTC),
        )
    )
    if allowed_collection_ids is not None:
        stmt = stmt.where(TenantCatalogItem.collection_id.in_(allowed_collection_ids))
    rows = (await session.execute(stmt)).all()
    return [
        RetrievedChunk(
            source_type="catalog",
            source_id=row.id,
            text=f"{row.name} (sku={row.sku})",
            score=max(0.0, 1.0 - float(distance or 0.0)),
            collection=collection_slug,
        )
        for row, distance, collection_slug in rows
    ]


async def _fetch_document_chunk_candidates(
    session: AsyncSession,
    tenant_id: UUID,
    embedding: list[float],
    *,
    allowed_collection_ids: list[UUID] | None,
    include_drafts: bool,
    limit: int,
) -> list[RetrievedChunk]:
    stmt = (
        select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(embedding).label("distance"),
            KbCollection.slug.label("collection_slug"),
        )
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .join(KbCollection, KnowledgeDocument.collection_id == KbCollection.id, isouter=True)
        .where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeChunk.embedding.is_not(None),
            KnowledgeChunk.chunk_status.notin_(["excluded", "error"]),
            KnowledgeDocument.status == "ready",
        )
        .order_by("distance")
        .limit(limit)
    )
    if not include_drafts:
        # Document-level publication state lives on KnowledgeDocument.status,
        # which is already filtered above to 'ready'. No KB-module status
        # field on documents in B2.
        pass
    stmt = stmt.where(
        or_(
            KnowledgeDocument.expires_at.is_(None),
            KnowledgeDocument.expires_at > datetime.now(UTC),
        )
    )
    if allowed_collection_ids is not None:
        stmt = stmt.where(KnowledgeDocument.collection_id.in_(allowed_collection_ids))
    rows = (await session.execute(stmt)).all()
    return [
        RetrievedChunk(
            source_type="document",
            source_id=row.id,
            text=row.text[:600],
            score=max(0.0, 1.0 - float(distance or 0.0)),
            collection=collection_slug,
            page=row.page,
            heading=row.heading,
            document_id=row.document_id,
        )
        for row, distance, collection_slug in rows
    ]


# ---------------------------------------------------------------------------
# Top-level entry


async def _resolve_collection_ids(
    session: AsyncSession, tenant_id: UUID, slugs: list[str]
) -> list[UUID]:
    if not slugs:
        return []
    rows = (
        await session.execute(
            select(KbCollection.id).where(
                KbCollection.tenant_id == tenant_id,
                KbCollection.slug.in_(slugs),
            )
        )
    ).scalars().all()
    return list(rows)


async def retrieve(
    session: AsyncSession,
    tenant_id: UUID,
    query: str,
    agent: str,
    *,
    provider: _ProviderLike,
    selected_sources: list[str] | None = None,
    minimum_score: float | None = None,
    include_drafts: bool = False,
    top_k: int = _DEFAULT_TOP_K,
) -> RetrievalResult:
    """Run the agent-scoped retrieval pipeline."""
    perms = await load_agent_permissions(session, tenant_id, agent)
    rules = await load_source_priority_rules(session, tenant_id, agent)

    # Source-type filter: per-request override beats agent permission.
    sources = selected_sources or perms.allowed_source_types or list(_DEFAULT_PRIORITY_BY_SOURCE)
    sources = [s for s in sources if s in perms.allowed_source_types or not perms.allowed_source_types]

    # Score floor: per-request override beats agent permission beats global default.
    floor = minimum_score if minimum_score is not None else perms.min_score

    # Collection filter — resolve slug list to ids; empty means no restriction.
    allowed_ids: list[UUID] | None
    if perms.allowed_collection_slugs:
        allowed_ids = await _resolve_collection_ids(
            session, tenant_id, perms.allowed_collection_slugs
        )
    else:
        allowed_ids = None

    embedding = await provider.create_embedding(query)

    # Per-source priority resolution: agent-specific rule > agent=NULL > default.
    priority_by_source: dict[str, int] = dict(_DEFAULT_PRIORITY_BY_SOURCE)
    for r in rules:
        if r.agent is None and r.source_type not in priority_by_source:
            priority_by_source[r.source_type] = r.priority
    for r in rules:
        if r.agent is None:
            priority_by_source[r.source_type] = r.priority
    for r in rules:
        if r.agent == agent:
            priority_by_source[r.source_type] = r.priority

    # Fetch candidates per source type.
    candidates: list[RetrievedChunk] = []
    fetch_limit = max(top_k * 2, 12)
    if "faq" in sources:
        candidates.extend(
            await _fetch_faq_candidates(
                session, tenant_id, embedding,
                allowed_collection_ids=allowed_ids,
                include_drafts=include_drafts,
                limit=fetch_limit,
            )
        )
    if "catalog" in sources:
        candidates.extend(
            await _fetch_catalog_candidates(
                session, tenant_id, embedding,
                allowed_collection_ids=allowed_ids,
                include_drafts=include_drafts,
                limit=fetch_limit,
            )
        )
    if "document" in sources:
        candidates.extend(
            await _fetch_document_chunk_candidates(
                session, tenant_id, embedding,
                allowed_collection_ids=allowed_ids,
                include_drafts=include_drafts,
                limit=fetch_limit,
            )
        )

    total_candidates = len(candidates)

    # Apply min_score floor.
    candidates = [c for c in candidates if c.score >= floor]

    # Sort by (priority DESC, score DESC); priority falls back to 0 for
    # any unexpected source_type.
    candidates.sort(
        key=lambda c: (-priority_by_source.get(c.source_type, 0), -c.score)
    )

    top = candidates[:top_k]

    # Run regex conflict detector over the top-K result.
    chunk_likes = [
        ChunkLike(text=c.text, source_type=c.source_type, source_id=str(c.source_id))
        for c in top
    ]
    conflicts: list[DetectedConflict] = detect_conflicts_in_results(chunk_likes)

    return RetrievalResult(
        chunks=top,
        conflicts=[
            {
                "detection_type": c.detection_type,
                "title": c.title,
                "severity": c.severity,
                "entity_a_type": c.entity_a_type,
                "entity_a_id": c.entity_a_id,
                "entity_a_excerpt": c.entity_a_excerpt,
                "entity_b_type": c.entity_b_type,
                "entity_b_id": c.entity_b_id,
                "entity_b_excerpt": c.entity_b_excerpt,
            }
            for c in conflicts
        ],
        total_candidates=total_candidates,
    )

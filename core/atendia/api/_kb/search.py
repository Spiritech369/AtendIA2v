"""Unified semantic + keyword search across FAQ / Catalog / Document chunks.

Behind the scenes it calls the same retriever the /test-query endpoint
uses. Without an ``agent`` query param it runs in a permissive mode
(all source types allowed); with an agent, it uses that agent's
allowed_source_types and allowed_collection_slugs.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.session import get_db_session
from atendia.tools.rag import get_provider
from atendia.tools.rag.retriever import retrieve

router = APIRouter()


class SearchHit(BaseModel):
    source_type: str
    source_id: UUID
    text: str
    score: float
    collection: str | None = None
    page: int | None = None
    document_id: UUID | None = None


class SearchResponse(BaseModel):
    query: str
    agent: str | None
    grouped: dict[str, list[SearchHit]]  # keys: faq | catalog | document
    total_candidates: int


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=500),
    agent: str | None = Query(default=None, max_length=40),
    source_types: list[Literal["faq", "catalog", "document"]] | None = Query(default=None),
    min_score: float | None = Query(default=None, ge=0.0, le=1.0),
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> SearchResponse:
    """Unified search.

    Without ``agent`` the retriever falls back to a permissive baseline
    (all source types allowed, no collection restriction). With an
    agent it scopes to the seeded agent permissions.
    """
    provider = get_provider()
    # When no agent is given we still need a string to pass to the
    # retriever; "_admin_search" is a sentinel that has no seeded
    # permissions row, so the retriever's fall-back-to-permissive path
    # kicks in.
    effective_agent = agent or "_admin_search"
    result = await retrieve(
        session,
        tenant_id,
        q,
        effective_agent,
        provider=provider,
        selected_sources=list(source_types) if source_types else None,
        minimum_score=min_score,
        include_drafts=False,
    )

    grouped: dict[str, list[SearchHit]] = {"faq": [], "catalog": [], "document": []}
    for c in result.chunks:
        grouped.setdefault(c.source_type, []).append(
            SearchHit(
                source_type=c.source_type,
                source_id=c.source_id,
                text=c.text,
                score=c.score,
                collection=c.collection,
                page=c.page,
                document_id=c.document_id,
            )
        )
    return SearchResponse(
        query=q,
        agent=agent,
        grouped=grouped,
        total_candidates=result.total_candidates,
    )

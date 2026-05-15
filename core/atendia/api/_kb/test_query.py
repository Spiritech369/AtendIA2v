"""POST /api/v1/knowledge/test-query — full structured RAG response.

This is the keystone of the KB module: it wires the entire Phase 2
pipeline (retriever → prompt builder → answer synthesizer) behind a
single endpoint that the operator hits from the PromptPreviewDrawer.

Returns retrieved chunks + the assembled prompt + the LLM answer +
confidence + action + risks + citations + mode, plus auto-logs an
``kb_unanswered_questions`` row when the result is escalate/low.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user
from atendia.db.models.kb_unanswered_question import KbUnansweredQuestion
from atendia.db.session import get_db_session
from atendia.tools.rag import get_provider
from atendia.tools.rag.answer_synthesizer import synthesize
from atendia.tools.rag.prompt_builder import build_prompt
from atendia.tools.rag.retriever import (
    load_safe_answer_settings,
    retrieve,
    RetrievedChunk,
)


router = APIRouter()


class TestQueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    agent: str = Field(min_length=1, max_length=40)
    selected_sources: list[Literal["faq", "catalog", "document"]] | None = None
    minimum_score: float | None = Field(default=None, ge=0.0, le=1.0)
    include_drafts: bool = False


class PromptPreview(BaseModel):
    system: str
    user: str
    context: str
    response_instructions: str


class Citation(BaseModel):
    source_type: str
    source_id: UUID
    score: float
    collection: str | None = None
    page: int | None = None


class RiskOut(BaseModel):
    type: str
    description: str
    pattern: str | None = None


class TestQueryResponse(BaseModel):
    query: str
    agent: str
    retrieved_chunks: list[RetrievedChunk]
    prompt: PromptPreview
    answer: str
    confidence: Literal["low", "medium", "high"]
    action: Literal["answer", "clarify", "escalate"]
    risks: list[RiskOut]
    citations: list[Citation]
    mode: Literal["llm", "sources_only", "empty", "mock"]


def _build_citations(chunks: list[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            source_type=c.source_type,
            source_id=c.source_id,
            score=c.score,
            collection=c.collection,
            page=c.page,
        )
        for c in chunks
    ]


@router.post("/test-query", response_model=TestQueryResponse)
async def test_query(
    body: TestQueryBody,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> TestQueryResponse:
    if body.include_drafts and user.role not in ("tenant_admin", "superadmin"):
        # include_drafts exposes unpublished content — admins only.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "include_drafts requires tenant_admin",
        )
    provider = get_provider()
    settings = await load_safe_answer_settings(session, tenant_id)
    retrieval = await retrieve(
        session,
        tenant_id,
        body.query,
        body.agent,
        provider=provider,
        selected_sources=list(body.selected_sources) if body.selected_sources else None,
        minimum_score=body.minimum_score,
        include_drafts=body.include_drafts,
    )
    prompt = build_prompt(body.query, body.agent, retrieval.chunks, settings)
    answer = await synthesize(retrieval, prompt, settings, body.agent, provider)

    # Auto-capture into the unanswered queue when the bot would have
    # punted on this query — the operator can then promote it to a draft
    # FAQ or add it to the regression suite.
    if answer.action == "escalate" or answer.confidence == "low":
        top_score = max((c.score for c in retrieval.chunks), default=None)
        await session.execute(
            insert(KbUnansweredQuestion).values(
                tenant_id=tenant_id,
                query=body.query,
                query_normalized=body.query.strip().lower(),
                agent=body.agent,
                top_score=top_score,
                llm_confidence=answer.confidence,
                escalation_reason=answer.action,
                failed_chunks=[c.model_dump(mode="json") for c in retrieval.chunks[:3]],
            )
        )
        await session.commit()

    return TestQueryResponse(
        query=body.query,
        agent=body.agent,
        retrieved_chunks=retrieval.chunks,
        prompt=PromptPreview(
            system=prompt.system,
            user=prompt.user,
            context=prompt.context,
            response_instructions=prompt.response_instructions,
        ),
        answer=answer.answer,
        confidence=answer.confidence,
        action=answer.action,
        risks=[
            RiskOut(type=r.type, description=r.description, pattern=r.pattern) for r in answer.risks
        ],
        citations=_build_citations(retrieval.chunks),
        mode=answer.mode,
    )

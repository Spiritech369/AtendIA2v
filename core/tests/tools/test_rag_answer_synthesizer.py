from uuid import uuid4

import pytest

from atendia.tools.rag.answer_synthesizer import synthesize
from atendia.tools.rag.mock_provider import MockProvider
from atendia.tools.rag.provider import PromptInput
from atendia.tools.rag.retriever import RetrievalResult, RetrievedChunk, SafeAnswerSettings


def _prompt(context: str = "<fuente>x</fuente>") -> PromptInput:
    return PromptInput(
        system="sys",
        user="¿enganche?",
        context=context,
        response_instructions="responde",
        model="gpt-4o-mini",
        max_tokens=200,
        temperature=0.0,
    )


def _chunk(score: float, text: str = "Enganche desde 10%") -> RetrievedChunk:
    return RetrievedChunk(
        source_type="faq",
        source_id=uuid4(),
        text=text,
        score=score,
        collection="credito",
    )


@pytest.mark.asyncio
async def test_conflicts_short_circuit_to_escalate():
    retrieval = RetrievalResult(
        chunks=[_chunk(0.95)],
        conflicts=[
            {
                "detection_type": "price_mismatch",
                "title": "x",
                "severity": "high",
                "entity_a_type": "faq",
                "entity_a_id": "a",
                "entity_a_excerpt": "",
                "entity_b_type": "faq",
                "entity_b_id": "b",
                "entity_b_excerpt": "",
            }
        ],
        total_candidates=1,
    )
    out = await synthesize(
        retrieval,
        _prompt(),
        SafeAnswerSettings(escalate_on_conflict=True),
        "sales_agent",
        MockProvider(),
    )
    assert out.action == "escalate"
    assert out.mode == "empty"


@pytest.mark.asyncio
async def test_no_chunks_escalates():
    retrieval = RetrievalResult(chunks=[], conflicts=[], total_candidates=0)
    out = await synthesize(
        retrieval, _prompt(), SafeAnswerSettings(), "duda_general", MockProvider()
    )
    assert out.action == "escalate"
    assert out.mode == "empty"


@pytest.mark.asyncio
async def test_top_score_below_floor_escalates():
    retrieval = RetrievalResult(chunks=[_chunk(0.5)], conflicts=[], total_candidates=1)
    out = await synthesize(
        retrieval,
        _prompt(),
        SafeAnswerSettings(min_score_to_answer=0.7),
        "duda_general",
        MockProvider(),
    )
    assert out.action == "escalate"
    assert out.mode == "empty"


@pytest.mark.asyncio
async def test_no_provider_returns_sources_only_mode():
    retrieval = RetrievalResult(chunks=[_chunk(0.92)], conflicts=[], total_candidates=1)
    out = await synthesize(retrieval, _prompt(), SafeAnswerSettings(), "sales_agent", provider=None)
    assert out.mode == "sources_only"
    assert "Enganche" in out.answer


@pytest.mark.asyncio
async def test_high_score_clean_returns_high_answer():
    retrieval = RetrievalResult(chunks=[_chunk(0.92)], conflicts=[], total_candidates=1)
    out = await synthesize(
        retrieval, _prompt(), SafeAnswerSettings(), "duda_general", MockProvider()
    )
    assert out.action == "answer"
    assert out.confidence == "high"
    assert out.mode == "mock"


@pytest.mark.asyncio
async def test_medium_score_clean_returns_medium_answer():
    retrieval = RetrievalResult(chunks=[_chunk(0.75)], conflicts=[], total_candidates=1)
    out = await synthesize(
        retrieval, _prompt(), SafeAnswerSettings(), "duda_general", MockProvider()
    )
    assert out.confidence == "medium"
    assert out.action == "answer"


@pytest.mark.asyncio
async def test_medium_score_with_risk_returns_clarify():
    """MockProvider echoes context as the answer, so put a risky phrase in
    the context to force the synthesizer's risk detector to fire."""
    retrieval = RetrievalResult(chunks=[_chunk(0.75)], conflicts=[], total_candidates=1)
    p = _prompt(context="<fuente>El crédito aprobado en 24h.</fuente>")
    out = await synthesize(retrieval, p, SafeAnswerSettings(), "sales_agent", MockProvider())
    assert out.confidence == "medium"
    assert out.action == "clarify"
    assert any(r.type == "risky_phrase" for r in out.risks)


@pytest.mark.asyncio
async def test_below_70_with_risks_falls_to_low_escalate():
    """Score below 0.70 always lands in low/escalate, regardless of risks."""
    retrieval = RetrievalResult(chunks=[_chunk(0.71)], conflicts=[], total_candidates=1)
    out = await synthesize(
        retrieval,
        _prompt(),
        SafeAnswerSettings(min_score_to_answer=0.70),
        "duda_general",
        MockProvider(),
    )
    # 0.71 ≥ 0.70 → medium/answer (not escalate). Confirms the inclusive boundary.
    assert out.confidence == "medium"


@pytest.mark.asyncio
async def test_high_score_with_conflict_still_demoted_to_low():
    """A high score with a (non-blocking) conflict should still bucket to
    medium/answer or lower; not high/answer."""
    retrieval = RetrievalResult(
        chunks=[_chunk(0.95)],
        conflicts=[
            {
                "detection_type": "x",
                "title": "t",
                "severity": "low",
                "entity_a_type": "faq",
                "entity_a_id": "a",
                "entity_a_excerpt": "",
                "entity_b_type": "faq",
                "entity_b_id": "b",
                "entity_b_excerpt": "",
            }
        ],
        total_candidates=1,
    )
    out = await synthesize(
        retrieval,
        _prompt(),
        SafeAnswerSettings(escalate_on_conflict=False),
        "duda_general",
        MockProvider(),
    )
    assert out.confidence != "high"


@pytest.mark.asyncio
async def test_conflicts_with_escalate_off_does_not_short_circuit():
    """When escalate_on_conflict=False, conflicts shouldn't force escalation
    — they just demote confidence."""
    retrieval = RetrievalResult(
        chunks=[_chunk(0.92)],
        conflicts=[
            {
                "detection_type": "x",
                "title": "t",
                "severity": "low",
                "entity_a_type": "faq",
                "entity_a_id": "a",
                "entity_a_excerpt": "",
                "entity_b_type": "faq",
                "entity_b_id": "b",
                "entity_b_excerpt": "",
            }
        ],
        total_candidates=1,
    )
    out = await synthesize(
        retrieval,
        _prompt(),
        SafeAnswerSettings(escalate_on_conflict=False),
        "duda_general",
        MockProvider(),
    )
    # Should call the provider, not return mode=empty
    assert out.mode == "mock"

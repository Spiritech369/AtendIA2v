"""Decision tree that turns a (RetrievalResult, prompt) into an answer.

Implements design §6's decision tree:

* conflicts + escalate_on_conflict   → escalate, mode=empty, fallback text
* no chunks                          → escalate, mode=empty, fallback text
* top_score < min_score_to_answer    → escalate, mode=empty, fallback text
* (any other failure to call provider — we treat the missing-key case as
  ``mode=sources_only``: list the sources without LLM synthesis)
* otherwise: call provider.generate_answer, then bucket by score+risks:
    - top ≥ 0.85, no risks, no conflicts → high  / answer
    - top ≥ 0.70, no risks                → medium / answer
    - top ≥ 0.70, with risks              → medium / clarify
    - else                                → low    / escalate
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

from atendia.tools.rag.provider import AnswerOutput, PromptInput
from atendia.tools.rag.retriever import RetrievalResult, SafeAnswerSettings
from atendia.tools.rag.risky_phrase_detector import Risk, detect_risky_phrases


Mode = Literal["llm", "sources_only", "empty", "mock"]
Confidence = Literal["low", "medium", "high"]
Action = Literal["answer", "clarify", "escalate"]


class _ProviderLike(Protocol):
    async def generate_answer(self, prompt: PromptInput) -> AnswerOutput: ...


class _RiskRecord(BaseModel):
    type: str
    description: str
    pattern: str | None = None


class AnswerResult(BaseModel):
    answer: str
    confidence: Confidence
    action: Action
    risks: list[_RiskRecord]
    mode: Mode
    raw_provider: AnswerOutput | None = None


def _risks_to_records(risks: list[Risk]) -> list[_RiskRecord]:
    return [_RiskRecord(type=r.type, description=r.description, pattern=r.pattern) for r in risks]


def _bucket(top_score: float, has_risks: bool, has_conflicts: bool) -> tuple[Confidence, Action]:
    if top_score >= 0.85 and not has_risks and not has_conflicts:
        return "high", "answer"
    if top_score >= 0.70 and not has_risks:
        return "medium", "answer"
    if top_score >= 0.70 and has_risks:
        return "medium", "clarify"
    return "low", "escalate"


async def synthesize(
    retrieval: RetrievalResult,
    prompt: PromptInput,
    settings: SafeAnswerSettings,
    agent: str,  # noqa: ARG001 — kept for future per-agent overrides
    provider: _ProviderLike | None,
) -> AnswerResult:
    """Apply the decision tree and return an AnswerResult."""
    if retrieval.conflicts and settings.escalate_on_conflict:
        return AnswerResult(
            answer=settings.default_fallback_message,
            confidence="low",
            action="escalate",
            risks=[
                _RiskRecord(
                    type="conflict",
                    description=f"{len(retrieval.conflicts)} conflicto(s) detectado(s)",
                )
            ],
            mode="empty",
        )

    if not retrieval.chunks:
        return AnswerResult(
            answer=settings.default_fallback_message,
            confidence="low",
            action="escalate",
            risks=[_RiskRecord(type="no_sources", description="Sin fuentes recuperadas")],
            mode="empty",
        )

    top_score = max((c.score for c in retrieval.chunks), default=0.0)

    if top_score < settings.min_score_to_answer:
        return AnswerResult(
            answer=settings.default_fallback_message,
            confidence="low",
            action="escalate",
            risks=[
                _RiskRecord(
                    type="low_score",
                    description=f"top score {top_score:.2f} < min {settings.min_score_to_answer:.2f}",
                )
            ],
            mode="empty",
        )

    if provider is None:
        # No provider configured (e.g. missing API key in dev) — return the
        # sources verbatim so the operator at least sees what retrieval
        # found. The UI surfaces ``mode=sources_only`` so the operator
        # knows no LLM ran.
        joined = "\n\n".join(f"- {c.text[:200]}" for c in retrieval.chunks[:3])
        return AnswerResult(
            answer=f"Fuentes encontradas (sin síntesis LLM):\n{joined}",
            confidence="low",
            action="escalate",
            risks=[],
            mode="sources_only",
        )

    output = await provider.generate_answer(prompt)
    risks = detect_risky_phrases(output.text, settings.risky_phrases or None)
    has_conflicts = bool(retrieval.conflicts)
    confidence, action = _bucket(top_score, has_risks=bool(risks), has_conflicts=has_conflicts)

    # Mock provider's ``raw_response={"mock": True}`` is the signal we use
    # to surface mode=mock in the UI without a separate flag on every call.
    mode: Mode = (
        "mock"
        if isinstance(output.raw_response, dict) and output.raw_response.get("mock")
        else "llm"
    )

    return AnswerResult(
        answer=output.text,
        confidence=confidence,
        action=action,
        risks=_risks_to_records(risks),
        mode=mode,
        raw_provider=output,
    )

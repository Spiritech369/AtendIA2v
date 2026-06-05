from __future__ import annotations

from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.conversation import Conversation
from atendia.db.models.turn_trace import TurnTrace

SHADOW_TRIGGERS = {"agent_runtime_v2_shadow", "agent_runtime_v2_shadow_auto"}
GENERIC_NON_ANSWERS = {
    "recibido",
    "listo",
    "ok",
    "te ayudo",
    "gracias",
    "lo reviso",
    "permiteme revisarlo",
    "no tengo ese dato",
}


class ShadowReportFilters(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
    agent_id: UUID | None = None
    conversation_id: UUID | None = None
    channel: str | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    include_examples: bool = False
    limit: int = Field(default=20, ge=1, le=200)


class AgentRuntimeV2ShadowAnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build_report(
        self,
        *,
        tenant_id: UUID,
        filters: ShadowReportFilters | None = None,
    ) -> dict[str, Any]:
        resolved = filters or ShadowReportFilters()
        traces = await self._shadow_traces(tenant_id=tenant_id, filters=resolved)
        rows = [_row(trace) for trace in traces]
        summary = _summary(rows)
        legacy_vs_v2 = _legacy_vs_v2(rows)
        return {
            "summary": summary,
            "legacy_vs_v2": legacy_vs_v2,
            "top_risk_flags": _top_counter(
                flag for row in rows for flag in row["risk_flags"]
            ),
            "top_policy_issues": _top_counter(
                issue for row in rows for issue in row["policy_issue_codes"]
            ),
            "top_knowledge_sources": _top_counter(
                source for row in rows for source in row["knowledge_sources"]
            ),
            "pilot_inputs": self.pilot_inputs_from_summary(summary),
            "examples": (
                [_example(row) for row in rows[: resolved.limit]]
                if resolved.include_examples
                else []
            ),
        }

    async def shadow_quality_metrics(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Reusable pilot-policy inputs derived from shadow traces only."""
        filters = ShadowReportFilters(agent_id=agent_id)
        traces = await self._shadow_traces(tenant_id=tenant_id, filters=filters)
        return self.pilot_inputs_from_summary(_summary([_row(trace) for trace in traces]))

    @staticmethod
    def pilot_inputs_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
        shadow_turns = int(summary.get("shadow_turns") or 0)
        policy_blocked = int(summary.get("policy_blocked_count") or 0)
        needs_human = int(summary.get("needs_human_count") or 0)
        return {
            "shadow_sample_size": shadow_turns,
            "avg_shadow_confidence": summary.get("avg_confidence"),
            "policy_block_rate": (
                round(policy_blocked / shadow_turns, 4) if shadow_turns else 0.0
            ),
            "needs_human_rate": (
                round(needs_human / shadow_turns, 4) if shadow_turns else 0.0
            ),
        }

    async def _shadow_traces(
        self,
        *,
        tenant_id: UUID,
        filters: ShadowReportFilters,
    ) -> list[TurnTrace]:
        stmt = (
            select(TurnTrace)
            .join(Conversation, Conversation.id == TurnTrace.conversation_id)
            .where(
                TurnTrace.tenant_id == tenant_id,
                TurnTrace.router_trigger.in_(SHADOW_TRIGGERS),
            )
            .order_by(TurnTrace.created_at.desc(), TurnTrace.turn_number.desc())
        )
        if filters.date_from is not None:
            stmt = stmt.where(TurnTrace.created_at >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(TurnTrace.created_at <= filters.date_to)
        if filters.agent_id is not None:
            stmt = stmt.where(TurnTrace.agent_id == filters.agent_id)
        if filters.conversation_id is not None:
            stmt = stmt.where(TurnTrace.conversation_id == filters.conversation_id)
        if filters.channel:
            stmt = stmt.where(Conversation.channel == filters.channel)
        rows = (await self._session.execute(stmt)).scalars().all()
        if filters.min_confidence is None:
            return rows
        return [
            trace
            for trace in rows
            if (_trace_confidence(trace) or 0.0) >= filters.min_confidence
        ]


def _row(trace: TurnTrace) -> dict[str, Any]:
    output = trace.composer_output or {}
    comparison = _comparison(trace)
    final_message = _string(output.get("final_message") or comparison.get("v2_final_message"))
    legacy_message = _string(comparison.get("legacy_final_message"))
    policy_issues = _policy_issues(trace)
    citations = _citations(trace)
    actions = _list(output.get("actions")) or _list(comparison.get("actions_proposed"))
    field_updates = _list(output.get("field_updates")) or _list(
        comparison.get("field_updates_proposed")
    )
    lifecycle_update = output.get("lifecycle_update") or comparison.get(
        "lifecycle_update_proposed"
    )
    lifecycle_update = lifecycle_update if isinstance(lifecycle_update, dict) else None
    confidence = _trace_confidence(trace)
    needs_human = bool(output.get("needs_human"))
    heuristics = _heuristics(
        legacy_message=legacy_message,
        v2_message=final_message,
        confidence=confidence,
        needs_human=needs_human,
        citations_count=len(citations),
        actions_count=len(actions),
        field_updates_count=len(field_updates),
        lifecycle_update=lifecycle_update,
    )
    return {
        "trace": trace,
        "final_message": final_message,
        "legacy_message": legacy_message,
        "confidence": confidence,
        "needs_human": needs_human,
        "risk_flags": [str(item) for item in _list(output.get("risk_flags"))],
        "actions": actions,
        "field_updates": field_updates,
        "lifecycle_update": lifecycle_update,
        "policy_issues": policy_issues,
        "policy_issue_codes": [_issue_code(issue) for issue in policy_issues],
        "citations": citations,
        "knowledge_sources": [_citation_source(citation) for citation in citations],
        "errors": _trace_errors(trace, comparison),
        "comparison": comparison,
        "heuristics": heuristics,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    confidences = [row["confidence"] for row in rows if row["confidence"] is not None]
    return {
        "shadow_turns": len(rows),
        "avg_confidence": round(sum(confidences) / len(confidences), 4)
        if confidences
        else 0.0,
        "needs_human_count": sum(1 for row in rows if row["needs_human"]),
        "policy_blocked_count": sum(1 for row in rows if row["policy_issues"]),
        "knowledge_gap_count": sum(
            1 for row in rows if "knowledge_gap" in set(row["risk_flags"])
        ),
        "actions_proposed_count": sum(len(row["actions"]) for row in rows),
        "field_updates_proposed_count": sum(len(row["field_updates"]) for row in rows),
        "lifecycle_updates_proposed_count": sum(
            1 for row in rows if row["lifecycle_update"] is not None
        ),
        "errors_count": sum(1 for row in rows if row["errors"]),
    }


def _legacy_vs_v2(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "legacy_message_available_count": sum(1 for row in rows if row["legacy_message"]),
        "v2_message_available_count": sum(1 for row in rows if row["final_message"]),
        "same_or_similar_count": sum(
            1
            for row in rows
            if _similar(row["legacy_message"], row["final_message"])
        ),
        "v2_empty_count": sum(1 for row in rows if not row["final_message"]),
        "legacy_empty_count": sum(1 for row in rows if not row["legacy_message"]),
        "needs_human_when_legacy_answered_count": sum(
            1 for row in rows if row["needs_human"] and row["legacy_message"]
        ),
    }


def _heuristics(
    *,
    legacy_message: str,
    v2_message: str,
    confidence: float | None,
    needs_human: bool,
    citations_count: int,
    actions_count: int,
    field_updates_count: int,
    lifecycle_update: Any,
) -> list[dict[str, Any]]:
    checks = [
        ("both_have_message", bool(legacy_message and v2_message)),
        ("v2_empty", not bool(v2_message)),
        ("legacy_empty", not bool(legacy_message)),
        ("v2_needs_human", needs_human),
        ("v2_low_confidence", confidence is not None and confidence < 0.5),
        ("v2_has_citations", citations_count > 0),
        ("v2_proposed_action", actions_count > 0),
        ("v2_proposed_field_update", field_updates_count > 0),
        ("v2_proposed_lifecycle_update", bool(lifecycle_update)),
        ("length_delta_extreme", _length_delta_extreme(legacy_message, v2_message)),
        ("possible_generic_non_answer", _possible_non_answer(v2_message)),
    ]
    return [{"name": name, "matched": matched} for name, matched in checks]


def _example(row: dict[str, Any]) -> dict[str, Any]:
    trace = row["trace"]
    return {
        "trace_id": str(trace.id),
        "conversation_id": str(trace.conversation_id),
        "agent_id": str(trace.agent_id) if trace.agent_id else None,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
        "legacy_message": row["legacy_message"],
        "v2_message": row["final_message"],
        "confidence": row["confidence"],
        "needs_human": row["needs_human"],
        "risk_flags": row["risk_flags"],
        "policy_issues": row["policy_issues"],
        "knowledge_sources": row["knowledge_sources"],
        "heuristics": row["heuristics"],
    }


def _comparison(trace: TurnTrace) -> dict[str, Any]:
    state_after = trace.state_after if isinstance(trace.state_after, dict) else {}
    comparison = state_after.get("comparison")
    return comparison if isinstance(comparison, dict) else {}


def _policy_issues(trace: TurnTrace) -> list[dict[str, Any]]:
    comparison = _comparison(trace)
    issues = comparison.get("policy_issues")
    if isinstance(issues, list):
        parsed = [item for item in issues if isinstance(item, dict)]
        if parsed:
            return parsed
    if comparison.get("policy_valid") is False:
        return [{"code": "policy_blocked", "message": "Shadow policy reported invalid"}]
    parsed_errors = [
        item
        for item in _list(trace.errors)
        if isinstance(item, dict) and (item.get("code") or item.get("where") == "policy")
    ]
    if parsed_errors:
        return parsed_errors
    rules = _list(trace.rules_evaluated)
    if any(
        isinstance(rule, dict)
        and rule.get("rule") == "policy_valid"
        and rule.get("passed") is False
        for rule in rules
    ):
        return [{"code": "policy_blocked", "message": "Trace policy_valid rule failed"}]
    return []


def _citations(trace: TurnTrace) -> list[dict[str, Any]]:
    output = trace.composer_output if isinstance(trace.composer_output, dict) else {}
    output_citations = output.get("knowledge_citations")
    if isinstance(output_citations, list):
        parsed = [item for item in output_citations if isinstance(item, dict)]
        if parsed:
            return parsed
    kb = trace.kb_evidence if isinstance(trace.kb_evidence, dict) else {}
    citations = kb.get("citations")
    return (
        [item for item in citations if isinstance(item, dict)]
        if isinstance(citations, list)
        else []
    )


def _trace_errors(trace: TurnTrace, comparison: dict[str, Any]) -> list[Any]:
    errors = _list(trace.errors)
    error_count = comparison.get("error_count")
    if not errors and isinstance(error_count, int) and error_count > 0:
        return [{"code": "shadow_error", "count": error_count}]
    return errors


def _top_counter(values: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    counter = Counter(value for value in values if value)
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def _issue_code(issue: dict[str, Any]) -> str:
    return str(issue.get("code") or issue.get("where") or issue.get("message") or "unknown")


def _citation_source(citation: dict[str, Any]) -> str:
    return str(
        citation.get("source_name")
        or citation.get("title")
        or citation.get("source_id")
        or "unknown"
    )


def _similar(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left.strip().casefold() == right.strip().casefold():
        return True
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio() >= 0.82


def _length_delta_extreme(left: str, right: str) -> bool:
    if not left or not right:
        return False
    shorter = max(1, min(len(left), len(right)))
    longer = max(len(left), len(right))
    return longer / shorter >= 3.0


def _possible_non_answer(message: str) -> bool:
    normalized = message.strip().casefold()
    if not normalized:
        return True
    if len(normalized.split()) <= 4:
        return True
    return any(value in normalized for value in GENERIC_NON_ANSWERS)


def _confidence(output: dict | None) -> float | None:
    if not isinstance(output, dict):
        return None
    try:
        return float(output.get("confidence"))
    except (TypeError, ValueError):
        return None


def _trace_confidence(trace: TurnTrace) -> float | None:
    confidence = _confidence(trace.composer_output)
    if confidence is not None:
        return confidence
    comparison = _comparison(trace)
    try:
        return float(comparison.get("v2_confidence"))
    except (TypeError, ValueError):
        return None


def _string(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []

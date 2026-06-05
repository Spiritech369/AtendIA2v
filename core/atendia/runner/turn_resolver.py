"""Legacy turn resolver kept for ConversationRunner fallback only.

AgentRuntime v2 must not depend on this module for customer-visible final copy.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.turn_resolution import (
    FinalDecisionPayload,
    ResolverAttempt,
    TurnResolverInput,
    TurnResolverResult,
)
from atendia.runner.resolvers.catalog_context_resolver import CatalogContextResolver
from atendia.runner.resolvers.catalog_resolver import CatalogResolver
from atendia.runner.resolvers.credit_plan_resolver import CreditPlanResolver
from atendia.runner.resolvers.document_expectation_resolver import DocumentExpectationResolver
from atendia.runner.resolvers.last_question_resolver import LastQuestionResolver
from atendia.runner.resolvers.numeric_answer_resolver import NumericAnswerResolver
from atendia.runner.resolvers.pending_field_resolver import PendingFieldResolver
from atendia.runner.resolvers.reference_resolver import ReferenceResolver

_AUTO_WRITE_THRESHOLD = 0.90


class TurnResolver:
    """Resolve short WhatsApp turns before the state machine asks clarification.

    Resolvers never mutate state. They return evidence-backed attempts; the
    runner decides which proposed updates are safe enough to pass through the
    existing state application path.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._resolvers = [
            LastQuestionResolver(),
            DocumentExpectationResolver(),
            CatalogContextResolver(),
            ReferenceResolver(),
            CreditPlanResolver(),
            NumericAnswerResolver(session),
            PendingFieldResolver(session),
            CatalogResolver(session),
        ]

    async def resolve(self, input: TurnResolverInput) -> TurnResolverResult:
        attempts: list[ResolverAttempt] = []
        for resolver in self._resolvers:
            attempt = await resolver.resolve(input)
            if attempt is not None:
                attempts.append(attempt)

        selected = self._select_writable(attempts)
        if selected is not None:
            return TurnResolverResult(
                resolved=True,
                selected_attempt=selected,
                attempts=attempts,
                field_updates=dict(selected.field_updates),
                effective_intent="ASK_INFO",
                requires_confirmation=False,
                final_decision_payload=_payload_for_writable(selected),
            )

        clarification_attempt = self._select_clarification(attempts)
        if clarification_attempt is not None:
            return TurnResolverResult(
                resolved=False,
                selected_attempt=clarification_attempt,
                attempts=attempts,
                requires_confirmation=clarification_attempt.requires_confirmation,
                suggested_clarification=clarification_attempt.suggested_clarification,
                final_decision_payload=_payload_for_clarification(clarification_attempt),
            )

        return TurnResolverResult(attempts=attempts)

    @staticmethod
    def _select_writable(attempts: list[ResolverAttempt]) -> ResolverAttempt | None:
        for attempt in attempts:
            if (
                attempt.can_write_state
                and not attempt.requires_confirmation
                and attempt.field_updates
                and attempt.confidence >= _AUTO_WRITE_THRESHOLD
            ):
                return attempt
        return None

    @staticmethod
    def _select_clarification(attempts: list[ResolverAttempt]) -> ResolverAttempt | None:
        for attempt in attempts:
            if attempt.suggested_clarification:
                return attempt
        return None


def _payload_for_writable(attempt: ResolverAttempt) -> FinalDecisionPayload:
    field_updated: str | None = None
    value = None
    if attempt.field_updates:
        field_updated, value = next(iter(attempt.field_updates.items()))
    evidence = (
        attempt.evidence[0].type
        if attempt.evidence
        else attempt.blocked_reason
        or attempt.resolver
    )
    decision_by_resolver = {
        "catalog_resolver": "product_detected",
        "credit_plan_resolver": "credit_plan_detected",
        "last_question_resolver": "last_question_answered",
        "numeric_answer_resolver": "numeric_answer_detected",
    }
    decision = decision_by_resolver.get(attempt.resolver, "field_detected")
    metadata = {
        "resolver": attempt.resolver,
        "understood_as": attempt.understood_as,
        "field_updates": attempt.field_updates,
    }
    if attempt.resolver in {"catalog_resolver", "catalog_context_resolver"}:
        metadata.update(_catalog_trace_metadata(attempt))
    return FinalDecisionPayload(
        decision=decision,
        field_updated=field_updated,
        value=value,
        evidence=str(evidence),
        next_action=attempt.next_action,
        confidence=attempt.confidence,
        metadata=metadata,
    )


def _payload_for_clarification(attempt: ResolverAttempt) -> FinalDecisionPayload:
    decision = "clarification_required"
    if attempt.blocked_reason == "no_catalog_match":
        decision = "product_not_found"
    elif attempt.resolver == "document_expectation_resolver":
        decision = "document_state_check_required"
    metadata = {
        "resolver": attempt.resolver,
        "understood_as": attempt.understood_as,
    }
    if attempt.resolver in {"catalog_resolver", "catalog_context_resolver"}:
        metadata.update(_catalog_trace_metadata(attempt))
    return FinalDecisionPayload(
        decision=decision,
        evidence=attempt.blocked_reason or attempt.resolver,
        next_action="ask_concrete_clarification",
        confidence=attempt.confidence,
        requires_confirmation=attempt.requires_confirmation,
        suggested_clarification=attempt.suggested_clarification,
        metadata=metadata,
    )


def _catalog_trace_metadata(attempt: ResolverAttempt) -> dict[str, object]:
    tool_result = attempt.tool_results[0] if attempt.tool_results else {}
    query = str(tool_result.get("query") or "").strip() if isinstance(tool_result, dict) else ""
    output = tool_result.get("output") if isinstance(tool_result, dict) else None
    candidate_names = []
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("sku") or "").strip()
                if name:
                    candidate_names.append(name)
    evidence_metadata = attempt.evidence[0].metadata if attempt.evidence else {}
    if isinstance(evidence_metadata, dict):
        for item in evidence_metadata.get("catalog_candidates") or []:
            name = str(item).strip()
            if name and name not in candidate_names:
                candidate_names.append(name)
    status = "selected" if attempt.can_write_state and attempt.field_updates else "unresolved"
    if attempt.blocked_reason in {
        "multiple_catalog_matches",
        "catalog_selection_ambiguous",
        "catalog_selection_out_of_range",
    }:
        status = "ambiguous"
    elif attempt.blocked_reason in {
        "catalog_match_below_threshold",
        "catalog_query_low_coverage",
        "no_catalog_match",
    }:
        status = "no_match"
    return {
        "catalog_resolution_status": status,
        "catalog_query": query,
        "catalog_candidates": candidate_names[:3],
        "catalog_candidate_count": len(candidate_names),
        "catalog_selected_model": next(iter(attempt.field_updates.values()), None)
        if attempt.field_updates
        else None,
        "catalog_resolution_confidence": attempt.confidence,
        "resolved_from_context": attempt.resolver == "catalog_context_resolver",
    }

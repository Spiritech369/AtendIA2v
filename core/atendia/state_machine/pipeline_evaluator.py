"""M3 of the pipeline-automation editor plan.

Evaluates per-stage ``auto_enter_rules`` against the conversation's known
fields and decides whether the conversation should move to a new stage.
This is the deterministic counterpart to the LLM-driven composer: the
bot extracts structured fields into ``customer.attrs`` /
``conversation_state.extracted_data``; this evaluator reads those and
moves the conversation between stages without prompt-time guesswork.

Design choices baked in here:

- ``evaluate_condition`` is a pure function — takes a flat dict of fields
  and a condition spec, returns bool. Cheap to test, no DB.
- ``resolve_field_path`` walks dot-separated paths
  (``DOCS_INE.status`` -> ``fields["DOCS_INE"]["status"]``) and also
  unwraps the ``{value, confidence, source_turn}`` shape used by
  ``conversation_state.extracted_data`` so callers don't have to handle
  both shapes themselves.
- ``select_best_stage`` honors stage ``order``, ``is_terminal``, and the
  ``allow_auto_backward`` flag. Terminal stages always block backward
  regardless of the flag.
- ``evaluate_pipeline_rules`` is the async DB-aware wrapper. It loads
  the active pipeline, merges field sources, picks a target stage if any
  match, and atomically updates ``conversations.current_stage`` +
  ``conversation_state.stage_entered_at`` + emits an audit event.
- Loop guard: each call moves at most one stage. The caller is the loop
  control — every trigger event causes one evaluation cycle. Workflow
  events / multi-hop transitions are out of scope (could be added by
  iterating until ``moved=False``, capped at ``MAX_CHAIN``, but for now
  one transition per trigger is enough).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.pipeline_definition import (
    AutoEnterRules,
    Condition,
    PipelineDefinition,
    StageDefinition,
)
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer

# Hard cap for one evaluator call. The current implementation only moves
# one stage per call, so this is informational; left here for the day we
# allow multi-hop chaining.
MAX_CHAIN: int = 5


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def resolve_field_path(fields: dict[str, Any], path: str) -> Any:
    """Walk a dot-separated path through ``fields``, unwrapping any
    ``{value, ...}`` shape on the way.

    Examples:
        >>> resolve_field_path({"plan_credito": "36m"}, "plan_credito")
        '36m'
        >>> resolve_field_path(
        ...     {"plan_credito": {"value": "36m", "confidence": 0.9}},
        ...     "plan_credito",
        ... )
        '36m'
        >>> resolve_field_path(
        ...     {"DOCS_INE": {"status": "ok"}}, "DOCS_INE.status"
        ... )
        'ok'

    Returns ``None`` when any segment is missing.
    """
    segments = path.split(".")
    current: Any = fields
    for seg in segments:
        if isinstance(current, dict):
            # Unwrap the canonical ExtractedField shape — if the operator
            # ran on extracted_data, the per-key value is itself a dict
            # of {value, confidence, source_turn}. We treat .value as
            # the canonical inner.
            if "value" in current and seg not in current and not _is_field_payload_segment(seg, current):
                # Try unwrapping then looking up
                inner = current.get("value")
                if isinstance(inner, dict) and seg in inner:
                    current = inner[seg]
                    continue
                # Or maybe the value IS the thing we want and there's no
                # further segment to descend
                return None
            if seg in current:
                current = current[seg]
                continue
            return None
        return None
    # Final unwrap: if the leaf is a {value: x} dict (typical for
    # extracted_data leaves), return x.
    if isinstance(current, dict) and "value" in current and "confidence" in current:
        return current["value"]
    return current


def _is_field_payload_segment(seg: str, current: dict) -> bool:
    """Heuristic: a segment is a 'real' payload key (not a metadata key)
    if it appears directly in the current dict. Used by
    ``resolve_field_path`` to decide whether to unwrap ``{value: ...}``
    or descend by key."""
    return seg in current


def evaluate_condition(
    condition: Condition,
    fields: dict[str, Any],
    *,
    docs_per_plan: dict[str, list] | None = None,
) -> bool:
    """Pure operator dispatch. Mirrors the FE OperatorSelector contract.

    ``docs_per_plan`` is required only by ``docs_complete_for_plan`` —
    the evaluator passes the active pipeline's mapping down through
    ``evaluate_rule_group`` / ``evaluate_pipeline_rules``. Other
    operators ignore it.
    """
    value = resolve_field_path(fields, condition.field)
    op = condition.operator
    expected = condition.value

    if op == "exists":
        return value is not None and value != ""
    if op == "not_exists":
        return value is None or value == ""
    if op == "equals":
        return value == expected
    if op == "not_equals":
        return value != expected
    if op == "contains":
        if value is None:
            return False
        return str(expected) in str(value)
    if op == "greater_than":
        try:
            return float(value) > float(expected)
        except (TypeError, ValueError):
            return False
    if op == "less_than":
        try:
            return float(value) < float(expected)
        except (TypeError, ValueError):
            return False
    if op == "in":
        return isinstance(expected, list) and value in expected
    if op == "not_in":
        return isinstance(expected, list) and value not in expected
    if op == "docs_complete_for_plan":
        # Plan-aware aggregate: "every document this plan requires has
        # status=ok on the customer". `condition.field` names the field
        # that holds the plan id (typically `plan_credito`). The list of
        # required docs comes from `pipeline.docs_per_plan[plan]`. Each
        # doc key resolves to `customer.attrs.<KEY>.status` (via
        # `resolve_field_path`).
        if not docs_per_plan:
            return False
        # `resolve_field_path` only unwraps the canonical
        # `{value, confidence}` extraction shape. Customer.attrs can hold
        # the raw value or a one-key `{value: ...}` partial. Tolerate
        # both so the operator works in production data.
        plan = value
        if isinstance(plan, dict) and "value" in plan:
            plan = plan["value"]
        if not isinstance(plan, str) or not plan:
            return False
        required = docs_per_plan.get(plan)
        if not isinstance(required, list) or not required:
            return False
        for doc_key in required:
            if not isinstance(doc_key, str):
                continue
            status = resolve_field_path(fields, f"{doc_key}.status")
            if isinstance(status, dict) and "value" in status:
                status = status["value"]
            if not (isinstance(status, str) and status.lower() == "ok"):
                return False
        return True
    return False


def evaluate_rule_group(
    rules: AutoEnterRules,
    fields: dict[str, Any],
    *,
    docs_per_plan: dict[str, list] | None = None,
) -> bool:
    """Run every condition under ``rules.match`` semantics."""
    if not rules.enabled or not rules.conditions:
        return False
    results = (
        evaluate_condition(c, fields, docs_per_plan=docs_per_plan)
        for c in rules.conditions
    )
    if rules.match == "all":
        return all(results)
    return any(results)


@dataclass(frozen=True)
class _StagePick:
    stage_id: str
    order: int


def _stage_order_index(pipeline: PipelineDefinition) -> dict[str, int]:
    """The wire stages list is the authoritative order. Index it once so
    look-ups are O(1)."""
    return {s.id: idx for idx, s in enumerate(pipeline.stages)}


def select_best_stage(
    *,
    matching: list[StageDefinition],
    current_stage_id: str,
    pipeline: PipelineDefinition,
) -> StageDefinition | None:
    """Among the stages whose rules matched, pick the one we should move
    to. Returns None if no valid target exists.

    Rules:
    - Never re-enter the current stage (no-op).
    - Never move out of a terminal stage.
    - Prefer the *latest* matching stage by ``order`` — moving forward
      reflects the funnel direction (lead -> qualified -> closed).
    - Skip stages whose ``order`` is earlier than the current stage's
      unless the target stage has ``allow_auto_backward=True``.
    - Terminal target stages still apply; the conversation can be
      auto-moved INTO a terminal stage by a rule, just not OUT of one.
    """
    if not matching:
        return None

    order = _stage_order_index(pipeline)
    current_idx = order.get(current_stage_id)
    if current_idx is None:
        # Current stage doesn't exist in the pipeline (orphan). The
        # operator probably renamed it; auto-evaluator should not try to
        # heal that — surface as no-move.
        return None

    # Block backward moves from a terminal stage.
    current_stage = next((s for s in pipeline.stages if s.id == current_stage_id), None)
    if current_stage is not None and current_stage.is_terminal:
        return None

    candidates: list[tuple[int, StageDefinition]] = []
    for stage in matching:
        stage_idx = order.get(stage.id)
        if stage_idx is None:
            continue  # mis-referenced, ignore
        if stage_idx == current_idx:
            continue  # already there
        if stage_idx < current_idx and not stage.allow_auto_backward:
            continue  # backward without permission
        candidates.append((stage_idx, stage))

    if not candidates:
        return None

    # Forward-bias: pick the highest index. Tie-breaking by spec order is
    # already stable because we sort on (idx, ...) ascending and take the
    # last.
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


# ---------------------------------------------------------------------------
# Async wrapper (DB-aware)
# ---------------------------------------------------------------------------


@dataclass
class EvaluationResult:
    moved: bool
    reason: str
    from_stage: str | None = None
    to_stage: str | None = None
    matched_stage_ids: list[str] | None = None
    # Migration 045 — every auto_enter_rule condition we evaluated this turn,
    # with its pass/fail. Lets the DebugPanel render a per-rule audit so the
    # operator can see exactly why a stage advanced (or didn't).
    rules_evaluated: list[dict] | None = None


def _merge_fields(
    customer_attrs: dict[str, Any] | None,
    extracted_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the flat field dict the evaluator reads.

    Why merge: some fields are stored on the customer (modelo_interes,
    plan_credito persisted across conversations), others live in
    conversation_state.extracted_data (per-turn AI extractions before
    they're flushed to customer.attrs). Whichever wins — we prefer the
    extracted_data view because it's the freshest per-turn snapshot.
    """
    merged: dict[str, Any] = {}
    if customer_attrs:
        merged.update(customer_attrs)
    if extracted_data:
        # extracted_data values are {value, confidence, source_turn}; the
        # evaluator unwraps via resolve_field_path. Merge raw so the
        # nested-doc resolution path works ("DOCS_INE.status" finds
        # extracted_data["DOCS_INE"]["status"] OR
        # customer_attrs["DOCS_INE"]["status"], whichever exists).
        for k, v in extracted_data.items():
            merged[k] = v
    return merged


async def evaluate_pipeline_rules(
    session: AsyncSession,
    conversation_id: UUID,
    pipeline: PipelineDefinition,
    *,
    trigger_event: str = "field_updated",
) -> EvaluationResult:
    """Load the conversation + customer, run the evaluator, and apply the
    transition if any. Caller passes the already-loaded pipeline (the
    runner has it in scope, so we avoid a second round-trip).
    """
    conv = (
        await session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
    ).scalar_one_or_none()
    if conv is None:
        return EvaluationResult(moved=False, reason="conversation_not_found")

    customer = (
        await session.execute(
            select(Customer).where(Customer.id == conv.customer_id)
        )
    ).scalar_one_or_none()

    state = (
        await session.execute(
            select(ConversationStateRow).where(
                ConversationStateRow.conversation_id == conv.id,
            )
        )
    ).scalar_one_or_none()

    fields = _merge_fields(
        customer.attrs if customer else None,
        state.extracted_data if state else None,
    )

    # Plan-aware aggregate operators need the docs_per_plan table to
    # resolve "all required docs for this plan are ok". Built once here
    # so we don't re-read the pipeline JSON per condition.
    docs_per_plan = pipeline.docs_per_plan or {}

    # Run each enabled rule group; collect the stages that match. Along
    # the way, record per-condition pass/fail into rules_evaluated so the
    # DebugPanel can show the rule-by-rule outcome (migration 045).
    matching: list[StageDefinition] = []
    rules_evaluated: list[dict] = []
    for stage in pipeline.stages:
        if not stage.auto_enter_rules:
            continue
        for idx, cond in enumerate(stage.auto_enter_rules.conditions or []):
            passed = evaluate_condition(cond, fields, docs_per_plan=docs_per_plan)
            rules_evaluated.append(
                {
                    "stage_id": stage.id,
                    "condition_index": idx,
                    "operator": cond.operator,
                    "field": cond.field,
                    "value": cond.value,
                    "passed": passed,
                },
            )
        if evaluate_rule_group(
            stage.auto_enter_rules,
            fields,
            docs_per_plan=docs_per_plan,
        ):
            matching.append(stage)

    target = select_best_stage(
        matching=matching,
        current_stage_id=conv.current_stage,
        pipeline=pipeline,
    )
    matched_ids = [s.id for s in matching]

    if target is None:
        return EvaluationResult(
            moved=False,
            reason=(
                "current_stage_is_terminal"
                if _is_current_terminal(pipeline, conv.current_stage)
                else "no_valid_matching_stage"
            ),
            from_stage=conv.current_stage,
            matched_stage_ids=matched_ids,
            rules_evaluated=rules_evaluated,
        )

    if target.id == conv.current_stage:
        return EvaluationResult(
            moved=False,
            reason="already_in_stage",
            from_stage=conv.current_stage,
            matched_stage_ids=matched_ids,
            rules_evaluated=rules_evaluated,
        )

    # Apply the transition. Both conversation and state are updated in
    # the same session/transaction so a crash mid-update doesn't leave
    # the row half-moved.
    now = datetime.now(UTC)
    previous = conv.current_stage
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conv.id)
        .values(current_stage=target.id, last_activity_at=now),
    )
    if state is not None:
        await session.execute(
            update(ConversationStateRow)
            .where(ConversationStateRow.conversation_id == conv.id)
            .values(stage_entered_at=now),
        )

    return EvaluationResult(
        moved=True,
        reason="auto_rule_matched",
        from_stage=previous,
        to_stage=target.id,
        matched_stage_ids=matched_ids,
        rules_evaluated=rules_evaluated,
    )


def _is_current_terminal(pipeline: PipelineDefinition, current_id: str) -> bool:
    stage = next((s for s in pipeline.stages if s.id == current_id), None)
    return bool(stage and stage.is_terminal)

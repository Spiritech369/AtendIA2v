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

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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
from atendia.db.models.customer_fields import CustomerFieldDefinition, CustomerFieldValue

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
        >>> resolve_field_path({"selection": "premium"}, "selection")
        'premium'
        >>> resolve_field_path(
        ...     {"selection": {"value": "premium", "confidence": 0.9}},
        ...     "selection",
        ... )
        'premium'
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
            if (
                "value" in current
                and seg not in current
                and not _is_field_payload_segment(seg, current)
            ):
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


def _string_value(value: Any) -> str | None:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _normalize_selection_key(value: Any) -> str:
    text_value = _string_value(value)
    if not text_value:
        return ""
    normalized = text_value.casefold()
    normalized = (
        normalized.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
        .replace("ñ", "n")
    )
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_")


def _resolve_document_selection_key(
    fields: dict[str, Any],
    *,
    condition_field: str,
    document_requirements: dict[str, list],
    document_requirements_field: str | None = None,
) -> str | None:
    """Find the document_requirements key for the current customer state.

    Tenants can choose whether requirements are keyed by case type,
    service tier, or any custom field. The explicit rule field and
    document_requirements_field are the only sources; no vertical-specific field names
    are implied by the evaluator.
    """
    if not document_requirements:
        return None

    candidate_fields: list[str] = [condition_field]
    if document_requirements_field:
        candidate_fields.append(document_requirements_field)

    candidates: list[str] = []
    seen_fields: set[str] = set()
    for field in candidate_fields:
        if not field or field in seen_fields:
            continue
        seen_fields.add(field)
        value = _string_value(resolve_field_path(fields, field))
        if value and value not in candidates:
            candidates.append(value)

    if not candidates:
        return None

    for value in candidates:
        if value in document_requirements:
            return value

    normalized_keys = {_normalize_selection_key(key): key for key in document_requirements}
    for value in candidates:
        normalized = _normalize_selection_key(value)
        if normalized and normalized in normalized_keys:
            return str(normalized_keys[normalized])

    scored: list[tuple[int, str]] = []
    candidate_norms = [
        _normalize_selection_key(v) for v in candidates if _normalize_selection_key(v)
    ]
    candidate_tokens = set()
    candidate_digits = set()
    for norm in candidate_norms:
        candidate_tokens.update(t for t in norm.split("_") if t and not t.isdigit())
        candidate_digits.update(re.findall(r"\d+", norm))

    for raw_key in document_requirements:
        key = str(raw_key)
        key_norm = _normalize_selection_key(key)
        if not key_norm:
            continue
        score = 0
        for norm in candidate_norms:
            if norm == key_norm:
                return key
            if norm in key_norm or key_norm in norm:
                score += 10
        key_tokens = set(t for t in key_norm.split("_") if t and not t.isdigit())
        key_digits = set(re.findall(r"\d+", key_norm))
        score += len(candidate_tokens & key_tokens) * 2
        score += len(candidate_digits & key_digits) * 5
        if score:
            scored.append((score, key))

    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _is_field_payload_segment(seg: str, current: dict) -> bool:
    """Heuristic: a segment is a 'real' payload key (not a metadata key)
    if it appears directly in the current dict. Used by
    ``resolve_field_path`` to decide whether to unwrap ``{value: ...}``
    or descend by key."""
    return seg in current


def _bool_like(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "si", "sí", "s"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _decimal_like(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    raw = str(value).replace(",", "").strip()
    if raw == "":
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _semantic_equals(left: Any, right: Any) -> bool:
    left_bool = _bool_like(left)
    right_bool = _bool_like(right)
    if left_bool is not None and right_bool is not None:
        return left_bool == right_bool

    left_number = _decimal_like(left)
    right_number = _decimal_like(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number

    return left == right


def _canonical_doc_status(value: Any) -> str | None:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    if isinstance(value, bool):
        return "ok" if value else "missing"
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in {
        "ok",
        "true",
        "1",
        "yes",
        "si",
        "sí",
        "received",
        "recibido",
        "approved",
        "aprobado",
    }:
        return "ok"
    if normalized in {"missing", "false", "0", "no", "pending", "pendiente", "pending_review"}:
        return "missing"
    if normalized in {"rejected", "rechazado", "rechazada", "unreadable", "expired"}:
        return "rejected"
    return None


def _resolve_doc_status(fields: dict[str, Any], doc_key: str) -> str | None:
    status = _canonical_doc_status(resolve_field_path(fields, f"{doc_key}.status"))
    if status is not None:
        return status
    return _canonical_doc_status(resolve_field_path(fields, doc_key))


def evaluate_condition(
    condition: Condition,
    fields: dict[str, Any],
    *,
    document_requirements: dict[str, list] | None = None,
    document_requirements_field: str | None = None,
) -> bool:
    """Pure operator dispatch. Mirrors the FE OperatorSelector contract.

    ``document_requirements`` is required only by ``documents_complete_for_selection`` —
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
    if condition.field.endswith(".status"):
        if value is None:
            value = resolve_field_path(fields, condition.field.rsplit(".", 1)[0])
        value = _canonical_doc_status(value) or value
        expected = _canonical_doc_status(expected) or expected
    if op == "equals":
        return _semantic_equals(value, expected)
    if op == "not_equals":
        return not _semantic_equals(value, expected)
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
    if op == "documents_complete_for_selection":
        # Selection-aware aggregate: every document configured for the
        # current customer selection must have status=ok. `condition.field`
        # names the selector field; document keys come from
        # `pipeline.document_requirements[selection]`. Each
        # doc key resolves to `customer.attrs.<KEY>.status` (via
        # `resolve_field_path`).
        if not document_requirements:
            return False
        selection = _resolve_document_selection_key(
            fields,
            condition_field=condition.field,
            document_requirements=document_requirements,
            document_requirements_field=document_requirements_field,
        )
        if not selection:
            return False
        required = document_requirements.get(selection)
        if not isinstance(required, list) or not required:
            return False
        for doc_key in required:
            if not isinstance(doc_key, str):
                continue
            if _resolve_doc_status(fields, doc_key) != "ok":
                return False
        return True
    return False


def evaluate_rule_group(
    rules: AutoEnterRules,
    fields: dict[str, Any],
    *,
    document_requirements: dict[str, list] | None = None,
    document_requirements_field: str | None = None,
) -> bool:
    """Run every condition under ``rules.match`` semantics."""
    if not rules.enabled or not rules.conditions:
        return False
    results = (
        evaluate_condition(
            c,
            fields,
            document_requirements=document_requirements,
            document_requirements_field=document_requirements_field,
        )
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
    customer_field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the flat field dict the evaluator reads.

    Why merge: some fields are stored on the customer, others live in
    conversation_state.extracted_data before they are flushed to the
    customer. Whichever wins, we prefer the extracted_data view because
    it is the freshest per-turn snapshot.
    """
    merged: dict[str, Any] = {}
    if customer_attrs:
        merged.update(customer_attrs)
    if customer_field_values:
        merged.update(customer_field_values)
    if extracted_data:
        # extracted_data values are {value, confidence, source_turn}; the
        # evaluator unwraps via resolve_field_path. Merge raw so the
        # nested-doc resolution path works ("DOCS_INE.status" finds
        # extracted_data["DOCS_INE"]["status"] OR
        # customer_attrs["DOCS_INE"]["status"], whichever exists).
        for k, v in extracted_data.items():
            merged[k] = v
    return merged


async def _load_customer_field_values(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    customer_id: UUID,
) -> dict[str, str | None]:
    rows = (
        await session.execute(
            select(CustomerFieldDefinition.key, CustomerFieldValue.value)
            .select_from(CustomerFieldValue)
            .join(
                CustomerFieldDefinition,
                CustomerFieldDefinition.id == CustomerFieldValue.field_definition_id,
            )
            .where(
                CustomerFieldValue.customer_id == customer_id,
                CustomerFieldDefinition.tenant_id == tenant_id,
            )
        )
    ).all()
    return {str(r.key): r.value for r in rows}


async def evaluate_pipeline_rules(
    session: AsyncSession,
    conversation_id: UUID,
    pipeline: PipelineDefinition,
    *,
    trigger_event: str = "field_updated",
    extra_fields: dict | None = None,
) -> EvaluationResult:
    """Load the conversation + customer, run the evaluator, and apply the
    transition if any. Caller passes the already-loaded pipeline (the
    runner has it in scope, so we avoid a second round-trip).

    ``extra_fields`` lets a caller merge in field values that live outside
    the three persisted stores (e.g. the Respond-Style direct route's
    validated shadow fields). They take precedence: they are the freshest
    accepted state of the turn being evaluated.
    """
    conv = (
        await session.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if conv is None:
        return EvaluationResult(moved=False, reason="conversation_not_found")

    customer = (
        await session.execute(select(Customer).where(Customer.id == conv.customer_id))
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
        (
            await _load_customer_field_values(
                session,
                tenant_id=conv.tenant_id,
                customer_id=conv.customer_id,
            )
            if customer
            else None
        ),
    )
    if extra_fields:
        fields = {
            **fields,
            **{k: v for k, v in extra_fields.items() if v is not None},
        }

    # Selection-aware aggregate operators need the document_requirements table.
    # so we don't re-read the pipeline JSON per condition.
    document_requirements = pipeline.document_requirements or {}

    # Run each enabled rule group; collect the stages that match. Along
    # the way, record per-condition pass/fail into rules_evaluated so the
    # DebugPanel can show the rule-by-rule outcome (migration 045).
    matching: list[StageDefinition] = []
    rules_evaluated: list[dict] = []
    for stage in pipeline.stages:
        if not stage.auto_enter_rules:
            continue
        for idx, cond in enumerate(stage.auto_enter_rules.conditions or []):
            passed = evaluate_condition(
                cond,
                fields,
                document_requirements=document_requirements,
                document_requirements_field=pipeline.document_requirements_field,
            )
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
            document_requirements=document_requirements,
            document_requirements_field=pipeline.document_requirements_field,
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

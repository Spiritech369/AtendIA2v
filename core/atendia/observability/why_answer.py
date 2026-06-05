from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.action_execution import ActionExecutionLog
from atendia.db.models.conversation import Conversation
from atendia.db.models.customer_fields import CustomerFieldUpdateEvidence
from atendia.db.models.eval_readiness import AgentReadinessEvalResult
from atendia.db.models.event import EventRow
from atendia.db.models.lifecycle import LifecycleStageHistory
from atendia.db.models.turn_trace import TurnTrace
from atendia.db.models.workflow import WorkflowExecution
from atendia.eval_lab.readiness import readiness_result_payload


class WhyAnswerNotFoundError(LookupError):
    pass


class WhyAnswerAggregator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def explain(
        self,
        *,
        tenant_id: UUID,
        trace_id: UUID,
        conversation_id: UUID | None = None,
    ) -> dict[str, Any]:
        trace = await self._get_trace(
            tenant_id=tenant_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
        )
        output = _as_dict(trace.composer_output)
        kb_evidence = _as_dict(trace.kb_evidence)
        citations = _citations(output=output, kb_evidence=kb_evidence)
        action_logs = await self._action_logs(trace)
        field_evidence = await self._field_evidence(trace)
        lifecycle_history = await self._lifecycle_history(trace)
        workflow_events = await self._workflow_events(trace)
        workflow_executions = await self._workflow_executions(workflow_events)
        readiness = await self._readiness(trace)
        policy = _policy(trace, output)
        rollout = _rollout(trace)
        side_effects = _side_effects(
            trace=trace,
            action_logs=action_logs,
            field_evidence=field_evidence,
            lifecycle_history=lifecycle_history,
            workflow_events=workflow_events,
            workflow_executions=workflow_executions,
        )
        final_message = _final_message(trace, output)
        confidence = _float_or_none(output.get("confidence"))
        actions = _actions(output=output, action_logs=action_logs)
        lifecycle_update = _lifecycle_update(output, lifecycle_history)
        field_updates = _field_updates(output, field_evidence)
        explanation = {
            "trace_id": str(trace.id),
            "tenant_id": str(trace.tenant_id),
            "conversation_id": str(trace.conversation_id),
            "agent_id": str(trace.agent_id) if trace.agent_id else None,
            "final_message": final_message,
            "confidence": confidence,
            "knowledge": {
                "citations": citations,
                "source_cards": [_source_card(item) for item in citations],
            },
            "field_updates": field_updates,
            "lifecycle_update": lifecycle_update,
            "actions": actions,
            "workflow_events": [
                _event_payload(event, workflow_executions) for event in workflow_events
            ],
            "policy": policy,
            "rollout_policy": rollout,
            "readiness": readiness_result_payload(readiness) or {},
            "side_effects": side_effects,
            "human_summary": _human_summary(
                final_message=final_message,
                citations=citations,
                actions=actions,
                field_updates=field_updates,
                lifecycle_update=lifecycle_update,
                policy=policy,
                workflow_events=workflow_events,
            ),
        }
        return _jsonable(explanation)

    async def _get_trace(
        self,
        *,
        tenant_id: UUID,
        trace_id: UUID,
        conversation_id: UUID | None,
    ) -> TurnTrace:
        stmt = select(TurnTrace).where(
            TurnTrace.id == trace_id,
            TurnTrace.tenant_id == tenant_id,
        )
        if conversation_id is not None:
            stmt = stmt.where(TurnTrace.conversation_id == conversation_id)
        trace = (await self._session.execute(stmt)).scalar_one_or_none()
        if trace is None:
            raise WhyAnswerNotFoundError(str(trace_id))
        return trace

    async def _action_logs(self, trace: TurnTrace) -> list[ActionExecutionLog]:
        rows = (
            await self._session.execute(
                select(ActionExecutionLog)
                .where(
                    ActionExecutionLog.tenant_id == trace.tenant_id,
                    ActionExecutionLog.trace_id == str(trace.id),
                )
                .order_by(ActionExecutionLog.created_at.asc())
            )
        ).scalars().all()
        if rows:
            return list(rows)
        return (
            (
                await self._session.execute(
                    select(ActionExecutionLog)
                    .where(
                        ActionExecutionLog.tenant_id == trace.tenant_id,
                        ActionExecutionLog.conversation_id == trace.conversation_id,
                    )
                    .order_by(ActionExecutionLog.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _field_evidence(self, trace: TurnTrace) -> list[CustomerFieldUpdateEvidence]:
        return (
            (
                await self._session.execute(
                    select(CustomerFieldUpdateEvidence)
                    .join(
                        Conversation,
                        Conversation.customer_id == CustomerFieldUpdateEvidence.customer_id,
                    )
                    .where(
                        CustomerFieldUpdateEvidence.tenant_id == trace.tenant_id,
                        Conversation.id == trace.conversation_id,
                        CustomerFieldUpdateEvidence.trace_id == str(trace.id),
                    )
                    .order_by(CustomerFieldUpdateEvidence.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _lifecycle_history(self, trace: TurnTrace) -> list[LifecycleStageHistory]:
        return (
            (
                await self._session.execute(
                    select(LifecycleStageHistory)
                    .where(
                        LifecycleStageHistory.tenant_id == trace.tenant_id,
                        LifecycleStageHistory.conversation_id == trace.conversation_id,
                        LifecycleStageHistory.trace_id == str(trace.id),
                    )
                    .order_by(LifecycleStageHistory.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _workflow_events(self, trace: TurnTrace) -> list[EventRow]:
        candidates = (
            (
                await self._session.execute(
                    select(EventRow)
                    .where(
                        EventRow.tenant_id == trace.tenant_id,
                        EventRow.conversation_id == trace.conversation_id,
                    )
                    .order_by(EventRow.occurred_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return [
            event
            for event in candidates
            if event.type.startswith("agent_")
            and str((event.payload or {}).get("trace_id") or "") == str(trace.id)
        ]

    async def _workflow_executions(self, events: list[EventRow]) -> list[WorkflowExecution]:
        event_ids = [event.id for event in events]
        if not event_ids:
            return []
        return (
            (
                await self._session.execute(
                    select(WorkflowExecution)
                    .where(WorkflowExecution.trigger_event_id.in_(event_ids))
                    .order_by(WorkflowExecution.started_at.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _readiness(self, trace: TurnTrace) -> AgentReadinessEvalResult | None:
        if trace.agent_id is None:
            return None
        return (
            await self._session.execute(
                select(AgentReadinessEvalResult)
                .where(
                    AgentReadinessEvalResult.tenant_id == trace.tenant_id,
                    AgentReadinessEvalResult.agent_id == trace.agent_id,
                )
                .order_by(AgentReadinessEvalResult.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


def _final_message(trace: TurnTrace, output: dict[str, Any]) -> str:
    if isinstance(output.get("final_message"), str):
        return output["final_message"]
    outbound = trace.outbound_messages or []
    if outbound and isinstance(outbound[0], dict):
        return str(outbound[0].get("text") or outbound[0].get("body") or "")
    return ""


def _citations(*, output: dict[str, Any], kb_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    raw = kb_evidence.get("citations") or output.get("knowledge_citations") or []
    if not isinstance(raw, list):
        return []
    return [_jsonable(item) for item in raw if isinstance(item, dict)]


def _source_card(citation: dict[str, Any]) -> dict[str, Any]:
    metadata = _as_dict(citation.get("metadata"))
    return {
        "source_id": citation.get("source_id"),
        "title": citation.get("title") or metadata.get("source_name"),
        "snippet": citation.get("snippet"),
        "score": citation.get("score"),
        "metadata": metadata,
    }


def _field_updates(
    output: dict[str, Any],
    evidence_rows: list[CustomerFieldUpdateEvidence],
) -> list[dict[str, Any]]:
    updates = [
        _jsonable(item)
        for item in output.get("field_updates", [])
        if isinstance(item, dict)
    ]
    updates.extend(
        {
            "id": str(row.id),
            "field_key": row.field_key,
            "old_value": row.old_value,
            "new_value": row.new_value,
            "source": row.source,
            "reason": row.reason,
            "confidence": row.confidence,
            "status": row.status,
            "evidence_message_id": (
                str(row.evidence_message_id) if row.evidence_message_id else None
            ),
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
        }
        for row in evidence_rows
    )
    return _dedupe(updates, keys=("id", "field_key", "new_value", "status"))


def _lifecycle_update(
    output: dict[str, Any],
    history_rows: list[LifecycleStageHistory],
) -> dict[str, Any]:
    base = _as_dict(output.get("lifecycle_update"))
    history = [
        {
            "id": str(row.id),
            "from_stage": row.from_stage,
            "to_stage": row.to_stage,
            "reason": row.reason,
            "evidence": row.evidence or [],
            "confidence": row.confidence,
            "source": row.source,
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
        }
        for row in history_rows
    ]
    if not base and history:
        base = dict(history[-1])
    if history:
        base["history"] = history
    return _jsonable(base)


def _actions(
    *,
    output: dict[str, Any],
    action_logs: list[ActionExecutionLog],
) -> dict[str, list[dict[str, Any]]]:
    planned = [
        _jsonable(item) for item in output.get("actions", []) if isinstance(item, dict)
    ]
    executed: list[dict[str, Any]] = []
    dry_run: list[dict[str, Any]] = []
    for row in action_logs:
        payload = {
            "id": str(row.id),
            "action_id": row.action_id,
            "input": row.input or {},
            "status": row.status,
            "result": row.result or {},
            "error": row.error,
            "dry_run": row.dry_run,
            "created_at": row.created_at,
        }
        if row.dry_run:
            dry_run.append(payload)
        else:
            executed.append(payload)
    return {
        "planned": planned,
        "executed": _jsonable(executed),
        "dry_run": _jsonable(dry_run),
    }


def _policy(trace: TurnTrace, output: dict[str, Any]) -> dict[str, Any]:
    issues = _policy_issues(trace.errors)
    for rule in trace.rules_evaluated or []:
        if isinstance(rule, dict) and rule.get("rule") == "policy_valid" and not rule.get("passed"):
            issues.append({"code": "policy_valid_false", "message": "policy_valid rule failed"})
    debug_policy = _as_dict(output.get("debug")).get("policy")
    if isinstance(debug_policy, dict):
        issues.extend(
            item for item in debug_policy.get("issues", []) if isinstance(item, dict)
        )
    return {"valid": not issues, "issues": _jsonable(issues)}


def _policy_issues(errors: Any) -> list[dict[str, Any]]:
    if not errors:
        return []
    raw_errors = errors if isinstance(errors, list) else [errors]
    issues: list[dict[str, Any]] = []
    for item in raw_errors:
        if isinstance(item, dict) and "code" in item:
            issues.append(_jsonable(item))
        elif isinstance(item, dict) and "policy_issues" in item:
            issues.extend(
                _jsonable(issue)
                for issue in item.get("policy_issues", [])
                if isinstance(issue, dict)
            )
        elif "policy" in str(item).lower():
            issues.append({"code": "policy_error", "message": str(item)})
    return issues


def _rollout(trace: TurnTrace) -> dict[str, Any]:
    state_after = _as_dict(trace.state_after)
    if isinstance(state_after.get("rollout"), dict):
        return _jsonable(state_after["rollout"])
    decisions = [
        rule
        for rule in trace.rules_evaluated or []
        if isinstance(rule, dict) and "rollout_capability" in rule
    ]
    return {"decisions": _jsonable(decisions)} if decisions else {}


def _side_effects(
    *,
    trace: TurnTrace,
    action_logs: list[ActionExecutionLog],
    field_evidence: list[CustomerFieldUpdateEvidence],
    lifecycle_history: list[LifecycleStageHistory],
    workflow_events: list[EventRow],
    workflow_executions: list[WorkflowExecution],
) -> dict[str, Any]:
    raw = _as_dict(_as_dict(trace.state_after).get("side_effects"))
    return {
        **raw,
        "persisted_action_logs": len(action_logs),
        "executed_actions": sum(1 for row in action_logs if not row.dry_run),
        "dry_run_actions": sum(1 for row in action_logs if row.dry_run),
        "field_evidence_rows": len(field_evidence),
        "lifecycle_history_rows": len(lifecycle_history),
        "workflow_events": len(workflow_events),
        "workflow_executions": len(workflow_executions),
    }


def _event_payload(
    event: EventRow,
    executions: list[WorkflowExecution],
) -> dict[str, Any]:
    event_executions = [
        row
        for row in executions
        if row.trigger_event_id is not None and row.trigger_event_id == event.id
    ]
    return _jsonable(
        {
            "id": str(event.id),
            "type": event.type,
            "payload": event.payload or {},
            "occurred_at": event.occurred_at,
            "source_workflow_execution_id": (
                str(event.source_workflow_execution_id)
                if event.source_workflow_execution_id
                else None
            ),
            "workflow_executions": [
                {
                    "id": str(row.id),
                    "workflow_id": str(row.workflow_id),
                    "status": row.status,
                    "current_node_id": row.current_node_id,
                    "error": row.error,
                    "started_at": row.started_at,
                    "finished_at": row.finished_at,
                }
                for row in event_executions
            ],
        }
    )


def _human_summary(
    *,
    final_message: str,
    citations: list[dict[str, Any]],
    actions: dict[str, list[dict[str, Any]]],
    field_updates: list[dict[str, Any]],
    lifecycle_update: dict[str, Any],
    policy: dict[str, Any],
    workflow_events: list[EventRow],
) -> str:
    parts = [
        "The agent produced a final message"
        if final_message
        else "The trace has no final message",
        f"using {len(citations)} knowledge citation(s)",
        f"with {len(field_updates)} field update(s)",
        "and a lifecycle update" if lifecycle_update else "and no lifecycle update",
        f"; policy {'passed' if policy.get('valid') else 'reported issues'}",
        f"; actions planned/executed/dry-run: {len(actions['planned'])}/"
        f"{len(actions['executed'])}/{len(actions['dry_run'])}",
        f"; workflow events: {len(workflow_events)}.",
    ]
    return " ".join(parts)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _dedupe(items: list[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = tuple(str(item.get(part)) for part in keys)
        if key in seen:
            continue
        seen.add(key)
        result.append(_jsonable(item))
    return result


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value

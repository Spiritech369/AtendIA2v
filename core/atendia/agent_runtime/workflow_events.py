from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.schemas import ActionResult, TurnContext, TurnOutput
from atendia.db.models.event import EventRow

AGENT_WORKFLOW_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "agent_turn_completed",
        "agent_confidence_low",
        "agent_needs_human",
        "agent_field_update_suggested",
        "agent_lifecycle_update_suggested",
        "agent_action_executed",
        "agent_knowledge_gap_detected",
        "agent_policy_blocked",
    }
)

LOW_CONFIDENCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class AgentWorkflowEvent:
    type: str
    payload: dict[str, Any]
    event_id: str | None = None
    workflow_execution_ids: list[str] | None = None
    simulated: bool = True

    def model_dump(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "payload": self.payload,
            "event_id": self.event_id,
            "workflow_execution_ids": self.workflow_execution_ids or [],
            "simulated": self.simulated,
        }


class AgentWorkflowEventEmitter:
    """Translate AgentRuntime v2 outputs into workflow trigger events.

    Preview/test paths can keep these as simulated payloads. Real EventRow
    insertion is explicit so workflows do not fire during dry-run UX.
    """

    async def emit_for_turn(
        self,
        session: AsyncSession,
        *,
        context: TurnContext,
        output: TurnOutput,
        action_results: list[ActionResult | dict[str, Any]] | None = None,
        policy_issues: list[dict[str, Any]] | None = None,
        dry_run: bool = True,
        emit_real: bool = False,
    ) -> list[AgentWorkflowEvent]:
        events = self.build_for_turn(
            context=context,
            output=output,
            action_results=action_results or [],
            policy_issues=policy_issues or [],
            dry_run=dry_run,
        )
        if dry_run or not emit_real:
            return events

        emitted: list[AgentWorkflowEvent] = []
        for event in events:
            emitted.append(
                await _persist_event(
                    session,
                    event,
                    context=context,
                    trace_id=_trace_id(output),
                )
            )
        return emitted

    async def emit_policy_blocked(
        self,
        session: AsyncSession,
        *,
        context: TurnContext,
        policy_issues: list[dict[str, Any]],
        dry_run: bool = True,
        emit_real: bool = False,
        trace_id: str | None = None,
    ) -> list[AgentWorkflowEvent]:
        event = AgentWorkflowEvent(
            type="agent_policy_blocked",
            payload={
                "source": "agent_runtime_v2",
                "tenant_id": context.tenant_id,
                "conversation_id": context.conversation_id,
                "customer_id": context.customer.id or context.metadata.get("customer_id"),
                "agent_id": context.active_agent.id if context.active_agent else None,
                "trace_id": trace_id,
                "confidence": None,
                "needs_human": True,
                "risk_flags": ["policy_blocked"],
                "dry_run": dry_run,
                "policy_issues": policy_issues,
            },
        )
        if dry_run or not emit_real:
            return [event]
        return [
            await _persist_event(
                session,
                event,
                context=context,
                trace_id=trace_id,
            )
        ]

    def build_for_turn(
        self,
        *,
        context: TurnContext,
        output: TurnOutput,
        action_results: list[ActionResult | dict[str, Any]],
        policy_issues: list[dict[str, Any]],
        dry_run: bool,
    ) -> list[AgentWorkflowEvent]:
        base = _base_payload(context, output, dry_run=dry_run)
        events: list[AgentWorkflowEvent] = [
            AgentWorkflowEvent(
                type="agent_turn_completed",
                payload={
                    **base,
                    "final_message_present": bool(output.final_message.strip()),
                    "field_update_count": len(output.field_updates),
                    "action_count": len(output.actions),
                    "citation_count": len(output.knowledge_citations),
                },
            )
        ]
        if output.confidence < LOW_CONFIDENCE_THRESHOLD:
            events.append(
                AgentWorkflowEvent(
                    type="agent_confidence_low",
                    payload={
                        **base,
                        "threshold": LOW_CONFIDENCE_THRESHOLD,
                    },
                )
            )
        if output.needs_human:
            events.append(
                AgentWorkflowEvent(
                    type="agent_needs_human",
                    payload={**base, "reason": "turn_output_needs_human"},
                )
            )
        for update in output.field_updates:
            events.append(
                AgentWorkflowEvent(
                    type="agent_field_update_suggested",
                    payload={
                        **base,
                        "field_key": update.field_key,
                        "confidence": (
                            update.confidence
                            if update.confidence is not None
                            else output.confidence
                        ),
                        "reason": update.reason,
                        "evidence": list(update.evidence),
                        "field_update": update.model_dump(mode="json"),
                    },
                )
            )
        if output.lifecycle_update is not None:
            update = output.lifecycle_update
            events.append(
                AgentWorkflowEvent(
                    type="agent_lifecycle_update_suggested",
                    payload={
                        **base,
                        "lifecycle_stage": update.target_stage,
                        "to": update.target_stage,
                        "confidence": (
                            update.confidence
                            if update.confidence is not None
                            else output.confidence
                        ),
                        "reason": update.reason,
                        "evidence": list(update.evidence),
                        "lifecycle_update": update.model_dump(mode="json"),
                    },
                )
            )
        for result in action_results:
            payload = result.model_dump(mode="json") if isinstance(result, ActionResult) else result
            events.append(
                AgentWorkflowEvent(
                    type="agent_action_executed",
                    payload={
                        **base,
                        "action_id": payload.get("action_name"),
                        "action_name": payload.get("action_name"),
                        "status": payload.get("status"),
                        "error": payload.get("error"),
                        "result": payload,
                    },
                )
            )
        if _knowledge_gap_detected(context, output):
            events.append(
                AgentWorkflowEvent(
                    type="agent_knowledge_gap_detected",
                    payload={
                        **base,
                        "missing_info": _knowledge_missing_info(context),
                    },
                )
            )
        if policy_issues:
            events.append(
                AgentWorkflowEvent(
                    type="agent_policy_blocked",
                    payload={**base, "policy_issues": policy_issues},
                )
            )
        return events


def _base_payload(
    context: TurnContext,
    output: TurnOutput,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "source": "agent_runtime_v2",
        "tenant_id": context.tenant_id,
        "conversation_id": context.conversation_id,
        "customer_id": context.customer.id or context.metadata.get("customer_id"),
        "agent_id": context.active_agent.id if context.active_agent else None,
        "trace_id": _trace_id(output),
        "confidence": output.confidence,
        "needs_human": output.needs_human,
        "risk_flags": list(output.risk_flags),
        "dry_run": dry_run,
    }


def _trace_id(output: TurnOutput) -> str | None:
    raw = output.trace_metadata.get("trace_id")
    return str(raw) if raw else None


def _knowledge_gap_detected(context: TurnContext, output: TurnOutput) -> bool:
    if "knowledge_gap" in output.risk_flags:
        return True
    retrieval = context.metadata.get("knowledge")
    return isinstance(retrieval, dict) and retrieval.get("answerable") is False


def _knowledge_missing_info(context: TurnContext) -> Any:
    retrieval = context.metadata.get("knowledge")
    if isinstance(retrieval, dict):
        return retrieval.get("missing_info")
    return None


def _maybe_uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _persist_event(
    session: AsyncSession,
    event: AgentWorkflowEvent,
    *,
    context: TurnContext,
    trace_id: str | None,
) -> AgentWorkflowEvent:
    from atendia.workflows.engine import evaluate_event

    row = EventRow(
        tenant_id=UUID(str(context.tenant_id)),
        conversation_id=_maybe_uuid(context.conversation_id),
        type=event.type,
        payload=event.payload,
        occurred_at=datetime.now(UTC),
        trace_id=trace_id,
    )
    session.add(row)
    await session.flush()
    execution_ids = await evaluate_event(session, row.id)
    return AgentWorkflowEvent(
        type=event.type,
        payload=event.payload,
        event_id=str(row.id),
        workflow_execution_ids=[str(item) for item in execution_ids],
        simulated=False,
    )

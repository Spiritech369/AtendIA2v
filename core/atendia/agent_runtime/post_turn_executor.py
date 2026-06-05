from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from atendia.agent_runtime.action_registry import ActionRegistry, default_action_registry
from atendia.agent_runtime.agent_config import action_registry_for_agent
from atendia.agent_runtime.business_event_ledger import record_business_event
from atendia.agent_runtime.business_events import BusinessEvent
from atendia.agent_runtime.policy_validator import PolicyIssue, PolicyValidator
from atendia.agent_runtime.schemas import ActionRequest, ActionResult, TurnContext, TurnOutput
from atendia.agent_runtime.workflow_bridge import (
    WorkflowBridgeResult,
    WorkflowBridgeRuntimeFlags,
    attach_workflow_bridge_results_to_trace,
    consume_business_event_ledger_row,
    evaluate_workflow_bridge,
)
from atendia.config import get_settings
from atendia.contact_memory.schemas import ContactMemoryWriteRequest
from atendia.contact_memory.service import ContactMemoryService
from atendia.db.models.action_execution import ActionExecutionLog
from atendia.db.models.agent import Agent
from atendia.db.models.business_event_ledger import BusinessEventLedgerRow
from atendia.db.models.conversation import Conversation
from atendia.db.models.tenant import TenantUser
from atendia.db.models.workflow import Workflow, WorkflowExecution
from atendia.lifecycle.schemas import LifecycleStageUpdateRequest
from atendia.lifecycle.service import LifecycleService

logger = logging.getLogger(__name__)

FailurePolicy = Literal["continue", "stop"]


async def attach_workflow_bridge_post_turn_preview(
    output: TurnOutput,
    context: TurnContext,
    *,
    session: AsyncSession | None = None,
) -> TurnOutput:
    """Attach workflow bridge previews from structured business events only.

    This post-turn bridge intentionally never executes workflows, actions, outbox
    writes, followups, handoffs or WhatsApp sends. A DB session only enables
    idempotent ledger recording for auditability.
    """
    events = _business_events_from_trace(output.trace_metadata)
    if not events:
        return output

    flags = WorkflowBridgeRuntimeFlags(
        actions_enabled=False,
        workflow_side_effects_enabled=False,
        workflow_events_enabled=True,
        tenant_workflows_enabled=False,
        allow_test_execution=False,
    )
    results: list[WorkflowBridgeResult] = []
    for event in events:
        if session is None:
            result = evaluate_workflow_bridge(
                tenant_id=context.tenant_id,
                conversation_id=context.conversation_id,
                ledger_entry=_preview_ledger_entry(event),
                tenant_config=context.tenant_config,
                runtime_flags=flags,
            ).model_copy(
                update={
                    "ledger_status": "not_available",
                    "side_effects_allowed": False,
                    "executed": False,
                }
            )
            results.append(result)
            continue

        ledger_record = await record_business_event(
            session,
            event=event,
            side_effects_allowed=False,
        )
        if ledger_record.duplicate:
            results.append(
                evaluate_workflow_bridge(
                    tenant_id=context.tenant_id,
                    conversation_id=context.conversation_id,
                    ledger_entry=ledger_record,
                    tenant_config=context.tenant_config,
                    runtime_flags=flags,
                ).model_copy(
                    update={
                        "ledger_status": "duplicate",
                        "side_effects_allowed": False,
                        "executed": False,
                    }
                )
            )
            continue

        ledger_row = await _business_event_ledger_row(session, ledger_record.ledger_id)
        if ledger_row is None:
            results.append(
                evaluate_workflow_bridge(
                    tenant_id=context.tenant_id,
                    conversation_id=context.conversation_id,
                    ledger_entry=ledger_record,
                    tenant_config=context.tenant_config,
                    runtime_flags=flags,
                ).model_copy(
                    update={
                        "ledger_status": "not_available",
                        "side_effects_allowed": False,
                        "executed": False,
                    }
                )
            )
            continue

        result = await consume_business_event_ledger_row(
            session,
            tenant_id=context.tenant_id,
            conversation_id=context.conversation_id,
            ledger_row=ledger_row,
            tenant_config=context.tenant_config,
            runtime_flags=flags,
        )
        result = result.model_copy(
            update={
                "ledger_status": "inserted",
                "side_effects_allowed": False,
                "executed": False,
            }
        )
        ledger_row.workflow_result = result.model_dump(mode="json")
        ledger_row.status = result.status
        ledger_row.reason = result.reason
        ledger_row.side_effects_allowed = False
        session.add(ledger_row)
        results.append(result)

    return attach_workflow_bridge_results_to_trace(output, results, replace=True)


class PostTurnActionExecutor:
    """Execute TurnOutput actions after response composition.

    The executor validates, isolates and audits action side effects. It never
    returns or sends customer-visible copy; final text stays in TurnOutput.
    """

    def __init__(
        self,
        registry: ActionRegistry | None = None,
        *,
        dry_run: bool = True,
        policy_validator: PolicyValidator | None = None,
        session: AsyncSession | None = None,
        contact_memory_service: ContactMemoryService | None = None,
        lifecycle_service: LifecycleService | None = None,
        max_actions_per_turn: int | None = None,
        failure_policy: FailurePolicy | None = None,
        require_runtime_enabled: bool = True,
    ) -> None:
        settings = get_settings()
        self._registry = registry or default_action_registry()
        self._dry_run = dry_run
        self._policy_validator = policy_validator or PolicyValidator(self._registry)
        self._session = session
        self._contact_memory_service = contact_memory_service
        self._lifecycle_service = lifecycle_service
        self._max_actions_per_turn = (
            max_actions_per_turn or settings.agent_runtime_v2_max_actions_per_turn
        )
        self._failure_policy: FailurePolicy = (
            failure_policy or settings.agent_runtime_v2_action_failure_policy
        )
        self._require_runtime_enabled = require_runtime_enabled
        self._runtime_enabled = settings.agent_runtime_v2_enabled

    async def execute(
        self,
        output: TurnOutput,
        context: TurnContext | None = None,
    ) -> list[ActionResult]:
        policy_validator = self._policy_validator
        if context and context.active_agent and context.active_agent.enabled_action_ids is not None:
            policy_validator = PolicyValidator(
                action_registry_for_agent(context.active_agent, self._registry)
            )
        policy_issues = policy_validator.validate(output)
        if policy_issues:
            results = [_blocked_result(action, policy_issues) for action in output.actions]
            await self._log_results(output.actions, results, context=context)
            return results

        runtime_disabled = (
            self._require_runtime_enabled
            and not self._runtime_enabled
            and not self._dry_run
        )
        if runtime_disabled:
            results = [
                ActionResult(
                    action_name=action.name,
                    status="failed",
                    error="agent_runtime_v2 is disabled; action execution skipped.",
                    trace_metadata={"executed": False, "runtime_disabled": True},
                )
                for action in output.actions
            ]
            await self._log_results(output.actions, results, context=context)
            return results

        results: list[ActionResult] = []
        if (
            self._contact_memory_service is not None
            and context is not None
            and not self._dry_run
        ):
            decisions = await self._contact_memory_service.apply_turn_output(
                output,
                context=context,
            )
            if decisions:
                results.append(
                    ActionResult(
                        action_name="contact_memory.field_updates",
                        status=(
                            "succeeded"
                            if any(decision.applied for decision in decisions)
                            else "skipped"
                        ),
                        data={
                            "decisions": [
                                decision.model_dump(mode="json")
                                for decision in decisions
                            ]
                        },
                        trace_metadata={
                            "executed": any(decision.applied for decision in decisions),
                            "dry_run": self._dry_run,
                        },
                    )
                )
                await self._log_result(
                    action_id="contact_memory.field_updates",
                    input_payload={
                        "field_updates": [
                            item.model_dump(mode="json") for item in output.field_updates
                        ]
                    },
                    result=results[-1],
                    context=context,
                    trace_id=str(output.trace_metadata.get("trace_id") or ""),
                )
        if self._lifecycle_service is not None and context is not None and not self._dry_run:
            lifecycle_result = await self._execute_lifecycle_update(output, context)
            if lifecycle_result is not None:
                results.append(lifecycle_result)
                await self._log_result(
                    action_id="lifecycle.update",
                    input_payload=(
                        output.lifecycle_update.model_dump(mode="json")
                        if output.lifecycle_update
                        else {}
                    ),
                    result=lifecycle_result,
                    context=context,
                    trace_id=str(output.trace_metadata.get("trace_id") or ""),
                )
        for index, action in enumerate(output.actions):
            if index >= self._max_actions_per_turn:
                result = ActionResult(
                    action_name=action.name,
                    status="failed",
                    error=f"max_actions_per_turn exceeded ({self._max_actions_per_turn}).",
                    trace_metadata={"executed": False, "max_actions_exceeded": True},
                )
            else:
                result = await self.execute_action(action, context=context)
            results.append(result)
            await self._log_result(
                action_id=_action_id(action),
                input_payload=action.model_dump(mode="json"),
                result=result,
                context=context,
                trace_id=_trace_id(action, output),
            )
            if result.status == "failed" and self._failure_policy == "stop":
                break
        return results

    async def execute_action(
        self,
        action: ActionRequest,
        context: TurnContext | None = None,
    ) -> ActionResult:
        registry = self._registry
        policy_validator = self._policy_validator
        if context and context.active_agent and context.active_agent.enabled_action_ids is not None:
            registry = action_registry_for_agent(context.active_agent, self._registry)
            policy_validator = PolicyValidator(registry)
        if not registry.has_action(action.name):
            return ActionResult(
                action_name=action.name,
                status="failed",
                error=f"Unknown action {action.name!r}; skipped.",
                trace_metadata={"executed": False},
            )

        policy_issues = policy_validator.validate(
            TurnOutput(
                final_message="policy-validation-placeholder",
                confidence=1.0,
                actions=[action],
            )
        )
        if policy_issues:
            return _blocked_result(action, policy_issues)

        if action.name == "update_contact_field":
            return await self._execute_update_contact_field_action(action, context)

        if (
            action.name == "move_lifecycle"
            and self._lifecycle_service is not None
            and context is not None
            and not self._dry_run
        ):
            return await self._execute_move_lifecycle_action(action, context)

        if action.name == "add_tag":
            return await self._execute_add_tag_action(action, context)
        if action.name == "assign_conversation":
            return await self._execute_assign_conversation_action(action, context)
        if action.name == "close_conversation":
            return await self._execute_close_conversation_action(action, context)
        if action.name == "trigger_workflow":
            return await self._execute_trigger_workflow_action(action, context)
        if action.name == "call_webhook":
            return _stub_result(action, self._dry_run)

        handler = registry.handler_for(action.name)
        if handler is not None and not self._dry_run:
            try:
                return await handler(action, context)
            except (ValidationError, ValueError) as exc:
                return ActionResult(
                    action_name=action.name,
                    status="failed",
                    error=str(exc),
                    trace_metadata={"executed": False},
                )

        logger.info(
            "agent_runtime_v2_action_stub",
            extra={
                "action_name": action.name,
                "tenant_id": context.tenant_id if context else None,
                "conversation_id": context.conversation_id if context else None,
            },
        )
        return _stub_result(action, self._dry_run)

    async def _execute_update_contact_field_action(
        self,
        action: ActionRequest,
        context: TurnContext | None,
    ) -> ActionResult:
        if self._dry_run:
            return _dry_run_result(action)
        if context is None:
            return _failed_result(action, "TurnContext is required.")
        service = self._contact_memory_service
        if service is None and self._session is not None:
            service = ContactMemoryService(self._session)
        if service is None:
            return _stub_result(action, self._dry_run)

        customer_id = _context_customer_id(context)
        if customer_id is None:
            return _failed_result(action, "customer id missing from TurnContext.")
        field_key = str(action.payload.get("field_key") or action.payload.get("key") or "").strip()
        if not field_key:
            return _failed_result(action, "update_contact_field requires field_key.")
        if "value" not in action.payload and "new_value" not in action.payload:
            return _failed_result(action, "update_contact_field requires value.")
        confidence = action.metadata.get("confidence", action.payload.get("confidence", 1.0))
        decision = await service.apply_update(
            ContactMemoryWriteRequest(
                tenant_id=UUID(str(context.tenant_id)),
                customer_id=customer_id,
                field_key=field_key,
                new_value=action.payload.get("value", action.payload.get("new_value")),
                source=_contact_memory_source(action.payload.get("source")),
                reason=action.reason,
                evidence=list(action.evidence),
                confidence=float(confidence),
                trace_id=action.metadata.get("trace_id"),
                created_by=str(action.metadata.get("created_by") or "agent_runtime_v2"),
                metadata={"action_payload": action.payload},
            )
        )
        return ActionResult(
            action_name=action.name,
            status="succeeded" if decision.applied else "skipped",
            data={"decision": decision.model_dump(mode="json")},
            error=None if decision.status != "rejected" else decision.reason,
            trace_metadata={
                "executed": decision.applied,
                "evidence_id": str(decision.evidence_id) if decision.evidence_id else None,
            },
        )

    async def _execute_move_lifecycle_action(
        self,
        action: ActionRequest,
        context: TurnContext,
    ) -> ActionResult:
        target_stage = str(
            action.payload.get("target_stage")
            or action.payload.get("stage")
            or action.payload.get("to_stage")
            or ""
        ).strip()
        if not target_stage:
            return ActionResult(
                action_name=action.name,
                status="failed",
                error="move_lifecycle requires target_stage.",
                trace_metadata={"executed": False},
            )
        if not action.reason:
            return ActionResult(
                action_name=action.name,
                status="failed",
                error="move_lifecycle requires reason.",
                trace_metadata={"executed": False},
            )
        confidence = action.metadata.get("confidence")
        if confidence is None:
            confidence = action.payload.get("confidence")
        decision = await self._lifecycle_service.apply_stage_update(
            LifecycleStageUpdateRequest(
                tenant_id=UUID(str(context.tenant_id)),
                conversation_id=UUID(str(context.conversation_id)),
                target_stage=target_stage,
                reason=action.reason,
                evidence=list(action.evidence),
                confidence=float(confidence if confidence is not None else 1.0),
                source="agent",
                trace_id=action.metadata.get("trace_id"),
                created_by=str(action.metadata.get("created_by") or "agent_runtime_v2"),
                metadata={"action_payload": action.payload},
            )
        )
        return ActionResult(
            action_name=action.name,
            status="succeeded" if decision.applied else "skipped",
            data={"decision": decision.model_dump(mode="json")},
            error=None if decision.valid else decision.reason,
            trace_metadata={
                "executed": decision.applied,
                "history_id": str(decision.history_id) if decision.history_id else None,
            },
        )

    async def _execute_add_tag_action(
        self,
        action: ActionRequest,
        context: TurnContext | None,
    ) -> ActionResult:
        if self._dry_run:
            return _dry_run_result(action)
        conversation = await self._conversation_for_context(action, context)
        if not isinstance(conversation, Conversation):
            return conversation
        tags = _tags_from_action(action)
        if not tags:
            return _failed_result(action, "add_tag requires tag or tags.")
        current = [str(item) for item in (conversation.tags or [])]
        added: list[str] = []
        for tag in tags:
            if tag not in current:
                current.append(tag)
                added.append(tag)
        conversation.tags = current
        flag_modified(conversation, "tags")
        conversation.last_activity_at = datetime.now(UTC)
        return ActionResult(
            action_name=action.name,
            status="succeeded" if added else "skipped",
            data={"changed_tags": added, "tags": current},
            trace_metadata={"executed": bool(added)},
        )

    async def _execute_assign_conversation_action(
        self,
        action: ActionRequest,
        context: TurnContext | None,
    ) -> ActionResult:
        if self._dry_run:
            return _dry_run_result(action)
        conversation = await self._conversation_for_context(action, context)
        if not isinstance(conversation, Conversation):
            return conversation
        if action.payload.get("unassign") is True:
            conversation.assigned_user_id = None
            conversation.assigned_agent_id = None
            conversation.last_activity_at = datetime.now(UTC)
            return ActionResult(
                action_name=action.name,
                status="succeeded",
                data={"assigned_user_id": None, "assigned_agent_id": None},
                trace_metadata={"executed": True},
            )
        user_id = _maybe_uuid(action.payload.get("user_id"))
        agent_id = _maybe_uuid(action.payload.get("agent_id"))
        if user_id is None and agent_id is None:
            return _failed_result(
                action,
                "assign_conversation requires user_id or agent_id.",
            )
        if user_id is not None:
            user = (
                await self._session.execute(
                    select(TenantUser).where(
                        TenantUser.id == user_id,
                        TenantUser.tenant_id == UUID(str(context.tenant_id)),
                    )
                )
            ).scalar_one_or_none()
            if user is None:
                return _failed_result(action, "assigned user not found for tenant.")
            conversation.assigned_user_id = user_id
        if agent_id is not None:
            agent = (
                await self._session.execute(
                    select(Agent).where(
                        Agent.id == agent_id,
                        Agent.tenant_id == UUID(str(context.tenant_id)),
                    )
                )
            ).scalar_one_or_none()
            if agent is None:
                return _failed_result(action, "assigned agent not found for tenant.")
            conversation.assigned_agent_id = agent_id
        conversation.last_activity_at = datetime.now(UTC)
        return ActionResult(
            action_name=action.name,
            status="succeeded",
            data={
                "assigned_user_id": (
                    str(conversation.assigned_user_id)
                    if conversation.assigned_user_id
                    else None
                ),
                "assigned_agent_id": (
                    str(conversation.assigned_agent_id)
                    if conversation.assigned_agent_id
                    else None
                ),
            },
            trace_metadata={"executed": True},
        )

    async def _execute_close_conversation_action(
        self,
        action: ActionRequest,
        context: TurnContext | None,
    ) -> ActionResult:
        if self._dry_run:
            return _dry_run_result(action)
        conversation = await self._conversation_for_context(action, context)
        if not isinstance(conversation, Conversation):
            return conversation
        status = str(action.payload.get("status") or "closed").strip()
        if status not in {"closed", "resolved"}:
            return _failed_result(
                action,
                "close_conversation status must be closed or resolved.",
            )
        conversation.status = status
        conversation.last_activity_at = datetime.now(UTC)
        return ActionResult(
            action_name=action.name,
            status="succeeded",
            data={"status": conversation.status, "category": action.payload.get("category")},
            trace_metadata={"executed": True},
        )

    async def _execute_trigger_workflow_action(
        self,
        action: ActionRequest,
        context: TurnContext | None,
    ) -> ActionResult:
        if self._dry_run:
            return _dry_run_result(action)
        if self._session is None or context is None:
            return _stub_result(action, self._dry_run)
        workflow_id = _maybe_uuid(action.payload.get("workflow_id"))
        if workflow_id is None:
            return _failed_result(action, "trigger_workflow requires workflow_id.")
        workflow = (
            await self._session.execute(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.tenant_id == UUID(str(context.tenant_id)),
                    Workflow.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if workflow is None:
            return _failed_result(action, "workflow not found or inactive for tenant.")
        conversation = await self._conversation_for_context(action, context)
        if not isinstance(conversation, Conversation):
            return conversation
        first_node_id = _first_workflow_node_id(workflow.definition or {})
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            conversation_id=conversation.id,
            customer_id=conversation.customer_id,
            status="running",
            current_node_id=first_node_id,
        )
        self._session.add(execution)
        await self._session.flush()
        return ActionResult(
            action_name=action.name,
            status="succeeded",
            data={
                "workflow_id": str(workflow.id),
                "execution_id": str(execution.id),
                "queued": False,
                "note": "Execution row created; worker enqueue remains P2.",
            },
            trace_metadata={"executed": True, "workflow_execution_id": str(execution.id)},
        )

    async def _conversation_for_context(
        self,
        action: ActionRequest,
        context: TurnContext | None,
    ) -> Conversation | ActionResult:
        if self._session is None:
            return _stub_result(action, self._dry_run)
        if context is None:
            return _failed_result(action, "TurnContext is required.")
        conversation_id = _maybe_uuid(context.conversation_id)
        if conversation_id is None:
            return _failed_result(action, "conversation_id is required.")
        conversation = (
            await self._session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == UUID(str(context.tenant_id)),
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            return _failed_result(action, "conversation not found for tenant.")
        return conversation

    async def _execute_lifecycle_update(
        self,
        output: TurnOutput,
        context: TurnContext,
    ) -> ActionResult | None:
        request = _lifecycle_request_from_output(output, context)
        if request is None:
            return None
        decision = await self._lifecycle_service.apply_stage_update(request)
        return ActionResult(
            action_name="lifecycle.update",
            status="succeeded" if decision.applied else "skipped",
            data={"decision": decision.model_dump(mode="json")},
            error=None if decision.valid else decision.reason,
            trace_metadata={
                "executed": decision.applied,
                "dry_run": self._dry_run,
                "history_id": str(decision.history_id) if decision.history_id else None,
            },
        )

    async def _log_results(
        self,
        actions: list[ActionRequest],
        results: list[ActionResult],
        *,
        context: TurnContext | None,
    ) -> None:
        for action, result in zip(actions, results, strict=False):
            await self._log_result(
                action_id=_action_id(action),
                input_payload=action.model_dump(mode="json"),
                result=result,
                context=context,
                trace_id=str(action.metadata.get("trace_id") or ""),
            )

    async def _log_result(
        self,
        *,
        action_id: str,
        input_payload: dict,
        result: ActionResult,
        context: TurnContext | None,
        trace_id: str | None,
    ) -> None:
        if self._session is None or context is None:
            return
        self._session.add(
            ActionExecutionLog(
                tenant_id=UUID(str(context.tenant_id)),
                conversation_id=_maybe_uuid(context.conversation_id),
                action_id=action_id,
                input=input_payload,
                status=result.status,
                result=result.model_dump(mode="json"),
                error=result.error,
                dry_run=self._dry_run,
                trace_id=trace_id or None,
            )
        )
        await self._session.flush()


def _future_connector(action_name: str) -> str:
    return {
        "update_contact_field": "customer_field_values",
        "move_lifecycle": "pipeline/lifecycle transitioner",
        "assign_conversation": "handoffs/assignment service",
        "add_tag": "customer/conversation tags",
        "trigger_workflow": "workflows.engine",
        "call_webhook": "integrations/webhook dispatcher",
        "close_conversation": "conversation status service",
    }.get(action_name, "unknown")


def _failed_result(action: ActionRequest, error: str) -> ActionResult:
    return ActionResult(
        action_name=action.name,
        status="failed",
        error=error,
        trace_metadata={"executed": False},
    )


def _dry_run_result(action: ActionRequest) -> ActionResult:
    return ActionResult(
        action_name=action.name,
        status="skipped",
        data={
            "dry_run": True,
            "connects_to": _future_connector(action.name),
        },
        trace_metadata={"executed": False, "dry_run": True},
    )


def _stub_result(action: ActionRequest, dry_run: bool) -> ActionResult:
    return ActionResult(
        action_name=action.name,
        status="skipped",
        data={
            "stub": True,
            "connects_to": _future_connector(action.name),
        },
        trace_metadata={"executed": False, "dry_run": dry_run},
    )


def _action_id(action: ActionRequest) -> str:
    raw = action.metadata.get("action_id") or action.name
    return str(raw)


def _trace_id(action: ActionRequest, output: TurnOutput) -> str:
    return str(action.metadata.get("trace_id") or output.trace_metadata.get("trace_id") or "")


def _business_events_from_trace(trace_metadata: dict[str, Any]) -> list[BusinessEvent]:
    raw_events = trace_metadata.get("business_events")
    if not isinstance(raw_events, list):
        universal_trace = trace_metadata.get("universal_turn_trace")
        if isinstance(universal_trace, dict):
            raw_events = universal_trace.get("business_events")
    if not isinstance(raw_events, list):
        return []

    events: list[BusinessEvent] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, dict):
            continue
        try:
            events.append(BusinessEvent.model_validate(raw_event))
        except ValidationError:
            logger.warning("Skipping invalid business event in post-turn workflow preview")
    return events


def _preview_ledger_entry(event: BusinessEvent) -> dict[str, Any]:
    return {
        "tenant_id": event.tenant_id,
        "conversation_id": event.conversation_id,
        "event_type": event.event_type,
        "idempotency_key": event.idempotency_key,
        "status": event.status,
        "reason": event.reason,
        "trace_id": event.triggered_by.trace_id,
        "side_effects_allowed": False,
    }


async def _business_event_ledger_row(
    session: AsyncSession,
    ledger_id: str | None,
) -> BusinessEventLedgerRow | None:
    row_id = _maybe_uuid(ledger_id)
    if row_id is None:
        return None
    return (
        await session.execute(
            select(BusinessEventLedgerRow).where(BusinessEventLedgerRow.id == row_id)
        )
    ).scalar_one_or_none()


def _context_customer_id(context: TurnContext) -> UUID | None:
    if context.customer.id:
        return _maybe_uuid(context.customer.id)
    raw = context.metadata.get("customer_id")
    return _maybe_uuid(raw) if raw else None


def _maybe_uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _tags_from_action(action: ActionRequest) -> list[str]:
    values: list[object] = []
    if "tag" in action.payload:
        values.append(action.payload.get("tag"))
    raw_tags = action.payload.get("tags")
    if isinstance(raw_tags, list):
        values.extend(raw_tags)
    normalized: list[str] = []
    for value in values:
        tag = str(value or "").strip()
        if tag and tag not in normalized:
            normalized.append(tag)
    return normalized


def _first_workflow_node_id(definition: dict) -> str | None:
    nodes = definition.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None
    first = nodes[0]
    if not isinstance(first, dict):
        return None
    raw = first.get("id")
    return str(raw) if raw else None


def _contact_memory_source(value: object) -> str:
    allowed = {
        "customer_message",
        "ai_inference",
        "knowledge",
        "action",
        "human",
        "workflow",
        "vision",
    }
    raw = str(value or "ai_inference")
    return raw if raw in allowed else "ai_inference"


def _lifecycle_request_from_output(
    output: TurnOutput,
    context: TurnContext,
) -> LifecycleStageUpdateRequest | None:
    update = output.lifecycle_update
    if update is None or not update.target_stage:
        return None
    return LifecycleStageUpdateRequest(
        tenant_id=UUID(str(context.tenant_id)),
        conversation_id=UUID(str(context.conversation_id)),
        target_stage=update.target_stage,
        reason=update.reason or "Lifecycle update requested.",
        evidence=list(update.evidence),
        confidence=float(update.confidence if update.confidence is not None else output.confidence),
        source=update.source,
        trace_id=update.trace_id or str(output.trace_metadata.get("trace_id") or ""),
        created_by=str(update.metadata.get("created_by") or "agent_runtime_v2"),
        metadata={
            **update.metadata,
            "target_status": update.target_status,
        },
    )


def _blocked_result(action: ActionRequest, issues: list[PolicyIssue]) -> ActionResult:
    return ActionResult(
        action_name=action.name,
        status="failed",
        error="Policy blocked action execution.",
        trace_metadata={
            "executed": False,
            "policy_blocked": True,
            "policy_issues": [
                {"code": issue.code, "message": issue.message}
                for issue in issues
            ],
        },
    )

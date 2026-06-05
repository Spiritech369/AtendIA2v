from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.canonical import coerce_quote_snapshot
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    ToolExecutionResult,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.state_writer import StateWriteResult

BusinessEventStatus = Literal["emitted", "blocked", "dry_run", "executed"]
BusinessEventSource = Literal["state_writer", "tool", "guard", "lifecycle", "system"]

UNIVERSAL_BUSINESS_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "lead_started",
        "intent_identified",
        "selection_identified",
        "plan_identified",
        "offer_quoted",
        "requirements_requested",
        "document_received",
        "requirements_partial",
        "requirements_complete",
        "human_handoff_requested",
        "followup_scheduled",
        "policy_blocked",
        "conversation_closed",
    }
)


class TriggeredBy(BaseModel):
    turn_id: str
    trace_id: str | None = None
    field_keys: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    guard_ids: list[str] = Field(default_factory=list)


class BusinessEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    tenant_id: str
    agent_id: str | None = None
    conversation_id: str
    contact_id: str | None = None
    domain: str | None = None
    source: BusinessEventSource
    triggered_by: TriggeredBy
    evidence_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    status: BusinessEventStatus = "dry_run"
    reason: str


class WorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    idempotency_key: str
    status: Literal["blocked", "dry-run", "executed"]
    dry_run: bool = True
    reason: str
    side_effects_allowed: bool = False


@dataclass(frozen=True)
class BusinessEventBundle:
    business_events: list[BusinessEvent]
    workflow_results: list[WorkflowResult]

    def trace_payload(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "business_events": [
                event.model_dump(mode="json") for event in self.business_events
            ],
            "workflow_results": [
                result.model_dump(mode="json") for result in self.workflow_results
            ],
        }


def derive_business_event_bundle(
    *,
    context: TurnContext,
    decision: AdvisorBrainDecision,
    tool_results: list[ToolExecutionResult],
    state_write_result: StateWriteResult,
    output: TurnOutput,
) -> BusinessEventBundle:
    builder = _BusinessEventBuilder(
        context=context,
        decision=decision,
        tool_results=tool_results,
        state_write_result=state_write_result,
        output=output,
    )
    events = builder.build()
    workflow_results = [_workflow_result(context, event) for event in events]
    return BusinessEventBundle(business_events=events, workflow_results=workflow_results)


class _BusinessEventBuilder:
    def __init__(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[ToolExecutionResult],
        state_write_result: StateWriteResult,
        output: TurnOutput,
    ) -> None:
        self.context = context
        self.decision = decision
        self.tool_results = list(tool_results)
        self.state_write_result = state_write_result
        self.output = output
        self.field_metadata = {
            str(key): _dict(value)
            for key, value in context.tenant_config.field_metadata.items()
        }
        self.allowed_event_metadata = {
            str(key): _dict(value)
            for key, value in context.tenant_config.workflow_event_metadata.items()
        }
        self.events: list[BusinessEvent] = []
        self.seen_idempotency_keys: set[str] = set()

    def build(self) -> list[BusinessEvent]:
        self._lead_started()
        self._intent_identified()
        self._field_role_events()
        self._offer_quoted()
        self._requirements_requested()
        self._document_events()
        self._human_handoff_requested()
        self._followup_scheduled()
        self._policy_blocked()
        self._conversation_closed()
        self._tenant_declared_lifecycle_event()
        return list(self.events)

    def _lead_started(self) -> None:
        turn_number = self.context.metadata.get("turn_number")
        if turn_number not in (1, "1", None):
            return
        if self.context.messages and len(self.context.messages) > 1 and turn_number is None:
            return
        self._append(
            event_type="lead_started",
            source="system",
            field_keys=[],
            tool_ids=[],
            guard_ids=[],
            evidence_refs=_evidence_from_context(self.context),
            payload={"turn_number": turn_number},
            idempotency_parts=[
                "lead_started",
                self.context.tenant_id,
                self.context.conversation_id,
            ],
            reason="first_turn_or_new_conversation",
        )

    def _intent_identified(self) -> None:
        intent = (
            self.decision.latest_customer_act
            or self.decision.customer_goal
            or self.decision.next_best_action
        )
        if not intent:
            return
        self._append(
            event_type="intent_identified",
            source="system",
            field_keys=[],
            tool_ids=[],
            guard_ids=[],
            evidence_refs=_evidence_from_context(self.context),
            payload={
                "intent": str(intent),
                "confidence": self.decision.confidence,
            },
            idempotency_parts=[
                "intent_identified",
                self.context.tenant_id,
                self.context.conversation_id,
                str(intent),
            ],
            reason="runtime_accepted_structured_intent",
        )

    def _field_role_events(self) -> None:
        for accepted in _list_of_dicts(self.state_write_result.accepted):
            field = _field_key(accepted)
            if not field:
                continue
            role = _field_role(self.field_metadata, field)
            if role == "selection":
                self._append_field_event(
                    event_type="selection_identified",
                    source="state_writer",
                    accepted=accepted,
                    reason="state_writer_accepted_selection_field",
                )
            elif role == "plan":
                self._append_field_event(
                    event_type="plan_identified",
                    source="state_writer",
                    accepted=accepted,
                    reason="state_writer_accepted_plan_field",
                )

    def _offer_quoted(self) -> None:
        quote_fields = [
            accepted
            for accepted in _list_of_dicts(self.state_write_result.accepted)
            if _field_role(self.field_metadata, _field_key(accepted)) == "quote"
        ]
        if not quote_fields:
            return
        snapshot = _quote_snapshot_from_tools(self.tool_results)
        if snapshot is None:
            return
        if _mandatory_tool_blocked(self.output, "quote.resolve"):
            return
        if _guard_blocked(self.output, "quote_safety"):
            return
        if self.output.trace_metadata.get("fallback"):
            return
        snapshot_id = snapshot.snapshot_id or _value_hash(snapshot.model_dump(mode="json"))
        self._append(
            event_type="offer_quoted",
            source="tool",
            field_keys=[_field_key(item) for item in quote_fields if _field_key(item)],
            tool_ids=["quote.resolve"],
            guard_ids=_guard_ids(self.output),
            evidence_refs=_event_evidence(*quote_fields, fallback=["tool_result:quote.resolve"]),
            payload={
                "quote_snapshot_id": snapshot.snapshot_id,
                "quote_snapshot_hash": snapshot.with_integrity_hash().integrity_hash,
                "source_tool": snapshot.source_tool,
            },
            idempotency_parts=[
                "offer_quoted",
                self.context.tenant_id,
                self.context.conversation_id,
                snapshot_id,
            ],
            reason="quote_snapshot_accepted_from_quote_resolve",
        )

    def _requirements_requested(self) -> None:
        if not _tool_succeeded(self.tool_results, "requirements.lookup"):
            return
        if _mandatory_tool_blocked(self.output, "requirements.lookup"):
            return
        payload = _tool_data(self.tool_results, "requirements.lookup")
        self._append(
            event_type="requirements_requested",
            source="tool",
            field_keys=[],
            tool_ids=["requirements.lookup"],
            guard_ids=_guard_ids(self.output),
            evidence_refs=_tool_evidence(payload, fallback=["tool_result:requirements.lookup"]),
            payload={"requirements_hash": _value_hash(payload), "requirements": payload},
            idempotency_parts=[
                "requirements_requested",
                self.context.tenant_id,
                self.context.conversation_id,
                _value_hash(payload),
            ],
            reason="requirements_lookup_executed",
        )

    def _document_events(self) -> None:
        has_document_evidence = _has_document_evidence(self.context, self.state_write_result)
        document_check = _tool_succeeded(self.tool_results, "document.check")
        if has_document_evidence and document_check:
            attachment_id = _attachment_id(self.context) or _value_hash(
                _tool_data(self.tool_results, "document.check")
            )
            self._append(
                event_type="document_received",
                source="tool",
                field_keys=[],
                tool_ids=["document.check"],
                guard_ids=[],
                evidence_refs=_evidence_from_context(self.context)
                or ["tool_result:document.check"],
                payload={"attachment_id": _attachment_id(self.context)},
                idempotency_parts=[
                    "document_received",
                    self.context.tenant_id,
                    self.context.conversation_id,
                    attachment_id,
                ],
                reason="document_evidence_validated",
            )

        document_payload = _tool_data(self.tool_results, "document.check")
        if document_payload:
            complete = _checklist_complete(document_payload)
            if complete is False:
                checklist_hash = _value_hash(document_payload)
                self._append(
                    event_type="requirements_partial",
                    source="tool",
                    field_keys=[],
                    tool_ids=["document.check"],
                    guard_ids=[],
                    evidence_refs=_tool_evidence(
                        document_payload,
                        fallback=["tool_result:document.check"],
                    ),
                    payload={"checklist_hash": checklist_hash},
                    idempotency_parts=[
                        "requirements_partial",
                        self.context.tenant_id,
                        self.context.conversation_id,
                        checklist_hash,
                    ],
                    reason="document_checklist_incomplete",
                )

        complete_fields = [
            accepted
            for accepted in _list_of_dicts(self.state_write_result.accepted)
            if _field_role(self.field_metadata, _field_key(accepted)) == "document"
            and _truthy_complete(accepted.get("proposed_value") or accepted.get("value"))
        ]
        if (
            complete_fields
            and _tool_succeeded(self.tool_results, "requirements.lookup")
            and _tool_succeeded(self.tool_results, "document.check")
        ):
            checklist_hash = _value_hash(
                {
                    "fields": complete_fields,
                    "requirements": _tool_data(self.tool_results, "requirements.lookup"),
                    "documents": _tool_data(self.tool_results, "document.check"),
                }
            )
            self._append(
                event_type="requirements_complete",
                source="state_writer",
                field_keys=[_field_key(item) for item in complete_fields if _field_key(item)],
                tool_ids=["requirements.lookup", "document.check"],
                guard_ids=[],
                evidence_refs=_event_evidence(
                    *complete_fields,
                    fallback=["tool_result:document.check"],
                ),
                payload={"checklist_hash": checklist_hash},
                idempotency_parts=[
                    "requirements_complete",
                    self.context.tenant_id,
                    self.context.conversation_id,
                    checklist_hash,
                ],
                reason="system_derived_requirements_complete_accepted",
            )

    def _human_handoff_requested(self) -> None:
        reason = _handoff_reason(self.decision, self.output)
        if not reason:
            return
        self._append(
            event_type="human_handoff_requested",
            source="system",
            field_keys=[],
            tool_ids=[],
            guard_ids=[],
            evidence_refs=_evidence_from_context(self.context),
            payload={"handoff_reason": reason},
            idempotency_parts=[
                "human_handoff_requested",
                self.context.tenant_id,
                self.context.conversation_id,
                reason,
            ],
            reason="structured_handoff_reason_present",
        )

    def _followup_scheduled(self) -> None:
        for action in self.output.actions:
            if action.name not in {"followup.schedule", "followup_scheduled"}:
                continue
            followup_type = str(action.payload.get("followup_type") or action.name)
            self._append(
                event_type="followup_scheduled",
                source="system",
                field_keys=[],
                tool_ids=[],
                guard_ids=[],
                evidence_refs=list(action.evidence),
                payload={
                    "action": action.model_dump(mode="json"),
                    "followup_type": followup_type,
                },
                idempotency_parts=[
                    "followup_scheduled",
                    self.context.tenant_id,
                    self.context.conversation_id,
                    followup_type,
                ],
                reason="structured_followup_action_requested",
            )

    def _policy_blocked(self) -> None:
        guard_ids = _blocked_guard_ids(self.output)
        if not guard_ids:
            return
        for guard_id in guard_ids:
            self._append(
                event_type="policy_blocked",
                source="guard",
                field_keys=[],
                tool_ids=[],
                guard_ids=[guard_id],
                evidence_refs=[],
                payload={"guard_id": guard_id},
                idempotency_parts=[
                    "policy_blocked",
                    self.context.tenant_id,
                    self.context.conversation_id,
                    guard_id,
                ],
                reason="guard_blocked_critical_output_or_state",
            )

    def _conversation_closed(self) -> None:
        update = self.state_write_result.lifecycle_update or self.output.lifecycle_update
        if update is None:
            return
        status = str(update.target_status or "").casefold()
        stage = str(update.target_stage or "").casefold()
        if status not in {"resolved", "closed", "archived"} and stage not in {
            "resolved",
            "closed",
            "archived",
        }:
            return
        reason = update.reason or "structured_lifecycle_close"
        self._append(
            event_type="conversation_closed",
            source="lifecycle",
            field_keys=[],
            tool_ids=[],
            guard_ids=[],
            evidence_refs=list(update.evidence),
            payload=update.model_dump(mode="json"),
            idempotency_parts=[
                "conversation_closed",
                self.context.tenant_id,
                self.context.conversation_id,
                status or stage,
            ],
            reason=reason,
        )

    def _tenant_declared_lifecycle_event(self) -> None:
        update = self.state_write_result.lifecycle_update or self.output.lifecycle_update
        if update is None:
            return
        candidates = {str(update.target_stage or ""), str(update.target_status or "")}
        for event_type in sorted(candidates & set(self.allowed_event_metadata)):
            if event_type in UNIVERSAL_BUSINESS_EVENT_TYPES or not event_type:
                continue
            self._append(
                event_type=event_type,
                source="lifecycle",
                field_keys=[],
                tool_ids=[],
                guard_ids=[],
                evidence_refs=list(update.evidence),
                payload=update.model_dump(mode="json"),
                idempotency_parts=[
                    event_type,
                    self.context.tenant_id,
                    self.context.conversation_id,
                    _value_hash(update.model_dump(mode="json")),
                ],
                reason="tenant_declared_lifecycle_event",
            )

    def _append_field_event(
        self,
        *,
        event_type: str,
        source: BusinessEventSource,
        accepted: dict[str, Any],
        reason: str,
    ) -> None:
        field = _field_key(accepted)
        value = accepted.get("proposed_value", accepted.get("value"))
        self._append(
            event_type=event_type,
            source=source,
            field_keys=[field] if field else [],
            tool_ids=_source_tool_ids(accepted),
            guard_ids=[],
            evidence_refs=_event_evidence(accepted),
            payload={"field": field, "value_hash": _value_hash(value)},
            idempotency_parts=[
                event_type,
                self.context.tenant_id,
                self.context.conversation_id,
                field or "field",
                _value_hash(value),
            ],
            reason=reason,
        )

    def _append(
        self,
        *,
        event_type: str,
        source: BusinessEventSource,
        field_keys: list[str],
        tool_ids: list[str],
        guard_ids: list[str],
        evidence_refs: list[str],
        payload: dict[str, Any],
        idempotency_parts: list[Any],
        reason: str,
    ) -> None:
        idempotency_key = ":".join(str(part) for part in idempotency_parts)
        if idempotency_key in self.seen_idempotency_keys:
            return
        self.seen_idempotency_keys.add(idempotency_key)
        allowed, block_reason = _event_allowed(
            self.context,
            event_type,
            self.allowed_event_metadata,
        )
        status: BusinessEventStatus = "dry_run" if allowed else "blocked"
        final_reason = reason if allowed else block_reason
        event_id = str(uuid5(NAMESPACE_URL, idempotency_key))
        self.events.append(
            BusinessEvent(
                event_id=event_id,
                event_type=event_type,
                tenant_id=self.context.tenant_id,
                agent_id=_agent_id(self.context),
                conversation_id=self.context.conversation_id,
                contact_id=self.context.customer.id,
                domain=_domain(self.context),
                source=source,
                triggered_by=TriggeredBy(
                    turn_id=_turn_id(self.context, self.output),
                    trace_id=_trace_id(self.output),
                    field_keys=[key for key in field_keys if key],
                    tool_ids=[tool_id for tool_id in tool_ids if tool_id],
                    guard_ids=[guard_id for guard_id in guard_ids if guard_id],
                ),
                evidence_refs=[str(item) for item in evidence_refs if str(item).strip()],
                payload=_jsonable(payload),
                idempotency_key=idempotency_key,
                status=status,
                reason=final_reason,
            )
        )


def _event_allowed(
    context: TurnContext,
    event_type: str,
    allowed_event_metadata: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    if not context.tenant_config.tenant_domain_contract:
        return True, "missing_contract_trace_only"
    if context.tenant_config.safe_mode:
        return True, "safe_mode_trace_only"
    if not allowed_event_metadata:
        return event_type in UNIVERSAL_BUSINESS_EVENT_TYPES, "event_not_declared_in_tenant_contract"
    if event_type in allowed_event_metadata:
        return True, "declared_in_tenant_contract"
    return False, "event_not_declared_in_tenant_contract"


def _workflow_result(context: TurnContext, event: BusinessEvent) -> WorkflowResult:
    if event.status == "blocked":
        return WorkflowResult(
            event_type=event.event_type,
            idempotency_key=event.idempotency_key,
            status="blocked",
            reason=event.reason,
        )
    if context.tenant_config.safe_mode:
        return WorkflowResult(
            event_type=event.event_type,
            idempotency_key=event.idempotency_key,
            status="blocked",
            reason="safe_mode_blocks_workflow_execution",
        )
    return WorkflowResult(
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        status="dry-run",
        reason="workflow_execution_disabled_for_business_events_phase",
    )


def _field_key(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    return str(value.get("field") or value.get("key") or "")


def _field_role(field_metadata: dict[str, dict[str, Any]], field: str) -> str:
    metadata = field_metadata.get(str(field or ""))
    return str((metadata or {}).get("domain_role") or "")


def _quote_snapshot_from_tools(tool_results: list[ToolExecutionResult]) -> Any:
    for result in tool_results:
        if result.tool_name != "quote.resolve" or result.status != "succeeded":
            continue
        snapshot = coerce_quote_snapshot(result.data.get("quote_snapshot"))
        if snapshot is not None and snapshot.snapshot_id:
            return snapshot.with_integrity_hash()
    return None


def _mandatory_tool_blocked(output: TurnOutput, tool_id: str) -> bool:
    decisions = _list_of_dicts(output.trace_metadata.get("mandatory_tool_decisions"))
    return any(
        str(decision.get("tool_id") or "") == tool_id
        and (decision.get("blocking") is True or str(decision.get("status")) == "missing")
        for decision in decisions
    )


def _guard_blocked(output: TurnOutput, guard_id: str) -> bool:
    guard = _dict(output.trace_metadata.get(guard_id))
    if not guard:
        return False
    if guard.get("allowed") is False:
        return True
    action = str(guard.get("action") or "")
    return action in {"rewritten", "blocked", "sanitized"}


def _blocked_guard_ids(output: TurnOutput) -> list[str]:
    ids: list[str] = []
    mandatory = _dict(output.trace_metadata.get("mandatory_tool_guard"))
    if mandatory:
        decisions = _list_of_dicts(mandatory.get("decisions"))
        if any(decision.get("blocking") for decision in decisions):
            ids.append("mandatory_tool_guard")
    for guard_id in ("quote_safety", "conversation_progress_guard", "guard_result"):
        if _guard_blocked(output, guard_id):
            ids.append(guard_id)
    return _dedupe(ids)


def _guard_ids(output: TurnOutput) -> list[str]:
    return [
        guard_id
        for guard_id in ("mandatory_tool_guard", "quote_safety", "conversation_progress_guard")
        if guard_id in output.trace_metadata
    ]


def _tool_succeeded(tool_results: list[ToolExecutionResult], tool_id: str) -> bool:
    return any(
        result.tool_name == tool_id and result.status == "succeeded" for result in tool_results
    )


def _tool_data(tool_results: list[ToolExecutionResult], tool_id: str) -> dict[str, Any]:
    for result in tool_results:
        if result.tool_name == tool_id and isinstance(result.data, dict):
            return result.data
    return {}


def _tool_evidence(payload: dict[str, Any], *, fallback: list[str]) -> list[str]:
    for key in ("evidence_refs", "evidence", "citations", "sources"):
        values = payload.get(key)
        if isinstance(values, list) and values:
            return [str(item) for item in values]
    return fallback


def _event_evidence(*items: dict[str, Any], fallback: list[str] | None = None) -> list[str]:
    refs: list[str] = []
    for item in items:
        for key in ("evidence_refs", "evidence"):
            values = item.get(key)
            if isinstance(values, list):
                refs.extend(str(value) for value in values)
    return _dedupe(refs or list(fallback or []))


def _source_tool_ids(item: dict[str, Any]) -> list[str]:
    source = str(item.get("source") or "")
    return [source] if "." in source else []


def _has_document_evidence(context: TurnContext, state_write_result: StateWriteResult) -> bool:
    if _attachment_id(context):
        return True
    attachments = context.metadata.get("attachments")
    if isinstance(attachments, list) and attachments:
        return True
    for message in context.messages:
        metadata = message.metadata
        if metadata.get("attachment_id") or metadata.get("attachments"):
            return True
    return any(
        str(item.get("source") or "") in {"human", "human_review"}
        for item in _list_of_dicts(state_write_result.accepted)
    )


def _attachment_id(context: TurnContext) -> str | None:
    for key in ("attachment_id", "evidence_attachment_id", "document_attachment_id"):
        value = context.metadata.get(key)
        if value:
            return str(value)
    attachments = context.metadata.get("attachments")
    if isinstance(attachments, list) and attachments:
        first = attachments[0]
        if isinstance(first, dict):
            value = first.get("id") or first.get("attachment_id")
            if value:
                return str(value)
    return None


def _checklist_complete(payload: dict[str, Any]) -> bool | None:
    for key in ("complete", "requirements_complete", "all_complete"):
        if isinstance(payload.get(key), bool):
            return bool(payload[key])
    checklist = payload.get("checklist") or payload.get("documents") or payload.get("items")
    if isinstance(checklist, list) and checklist:
        statuses = [
            str(item.get("status") or "").casefold()
            for item in checklist
            if isinstance(item, dict)
        ]
        if statuses:
            return all(status in {"ok", "accepted", "valid", "validated"} for status in statuses)
    return None


def _truthy_complete(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.casefold() in {"true", "complete", "completed", "ok", "accepted", "validated"}
    if isinstance(value, dict):
        complete = _checklist_complete(value)
        return complete is True
    return False


def _handoff_reason(decision: AdvisorBrainDecision, output: TurnOutput) -> str | None:
    for source in (output.trace_metadata, decision.metadata):
        for key in ("handoff_reason", "handoff_requested_reason", "escalation_reason"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if output.trace_metadata.get("handoff_requested") is True:
        value = output.trace_metadata.get("reason")
        return str(value) if value else "structured_handoff_requested"
    return None


def _agent_id(context: TurnContext) -> str | None:
    if context.active_agent and context.active_agent.id:
        return context.active_agent.id
    value = context.metadata.get("agent_id")
    return str(value) if value else None


def _domain(context: TurnContext) -> str | None:
    if context.tenant_config.domain:
        return context.tenant_config.domain
    metadata = _dict(context.metadata.get("tenant_domain_contract"))
    value = metadata.get("domain")
    return str(value) if value else None


def _turn_id(context: TurnContext, output: TurnOutput) -> str:
    for value in (
        context.metadata.get("turn_id"),
        context.metadata.get("message_id"),
        context.metadata.get("inbound_message_id"),
        output.trace_metadata.get("trace_id"),
    ):
        if value:
            return str(value)
    return f"{context.conversation_id}:{context.metadata.get('turn_number') or 'unknown'}"


def _trace_id(output: TurnOutput) -> str | None:
    value = output.trace_metadata.get("trace_id")
    return str(value) if value else None


def _evidence_from_context(context: TurnContext) -> list[str]:
    values: list[str] = []
    for key in ("message_id", "inbound_message_id", "attachment_id", "evidence_id"):
        value = context.metadata.get(key)
        if value:
            values.append(str(value))
    return _dedupe(values)


def _value_hash(value: Any) -> str:
    serial = json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()[:16]


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    return value


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


__all__ = [
    "UNIVERSAL_BUSINESS_EVENT_TYPES",
    "BusinessEvent",
    "BusinessEventBundle",
    "BusinessEventStatus",
    "TriggeredBy",
    "WorkflowResult",
    "derive_business_event_bundle",
]

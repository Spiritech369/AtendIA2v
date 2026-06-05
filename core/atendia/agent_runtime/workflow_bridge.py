from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.business_event_ledger import BusinessEventLedgerRecord
from atendia.agent_runtime.schemas import TenantRuntimeConfigContext, TurnOutput
from atendia.db.models.business_event_ledger import BusinessEventLedgerRow

WorkflowBridgeStatus = Literal[
    "dry_run",
    "blocked",
    "eligible",
    "duplicate",
    "not_configured",
    "executed",
]
WorkflowBridgeLedgerStatus = Literal["inserted", "duplicate", "not_available"]


class WorkflowBridgeRuntimeFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions_enabled: bool = False
    workflow_side_effects_enabled: bool = False
    workflow_events_enabled: bool = True
    tenant_workflows_enabled: bool = False
    allow_test_execution: bool = False


class WorkflowBridgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    idempotency_key: str
    workflow_id: str | None = None
    status: WorkflowBridgeStatus
    reason: str
    side_effects_allowed: bool = False
    actions: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str | None = None
    ledger_status: WorkflowBridgeLedgerStatus | None = None
    executed: bool = False


def evaluate_workflow_bridge(
    *,
    tenant_id: str,
    conversation_id: str,
    ledger_entry: Any,
    tenant_config: TenantRuntimeConfigContext,
    runtime_flags: WorkflowBridgeRuntimeFlags | None = None,
) -> WorkflowBridgeResult:
    flags = runtime_flags or WorkflowBridgeRuntimeFlags()
    event_type = _entry_text(ledger_entry, "event_type")
    idempotency_key = _entry_text(ledger_entry, "idempotency_key")
    trace_id = _entry_optional_text(ledger_entry, "trace_id")
    entry_tenant_id = _entry_optional_text(ledger_entry, "tenant_id")
    entry_conversation_id = _entry_optional_text(ledger_entry, "conversation_id")
    entry_status = _entry_text(ledger_entry, "status")

    base = {
        "event_type": event_type,
        "idempotency_key": idempotency_key,
        "trace_id": trace_id,
    }

    if _is_duplicate(ledger_entry):
        return WorkflowBridgeResult(
            **base,
            status="duplicate",
            reason="duplicate_idempotency_key",
        )
    if entry_tenant_id and entry_tenant_id != str(tenant_id):
        return WorkflowBridgeResult(**base, status="blocked", reason="tenant_mismatch")
    if entry_conversation_id and entry_conversation_id != str(conversation_id):
        return WorkflowBridgeResult(**base, status="blocked", reason="conversation_mismatch")
    if entry_status == "blocked":
        return WorkflowBridgeResult(**base, status="blocked", reason=_entry_reason(ledger_entry))
    if not flags.workflow_events_enabled:
        return WorkflowBridgeResult(**base, status="blocked", reason="workflow_events_disabled")

    event_config = _workflow_event_config(tenant_config, event_type)
    if not event_config:
        return WorkflowBridgeResult(
            **base,
            status="not_configured",
            reason="workflow_not_configured",
        )

    workflow_id = _optional_text(event_config.get("workflow_id"))
    actions = _actions(event_config)
    side_effects_allowed = _side_effects_allowed(
        ledger_entry=ledger_entry,
        event_config=event_config,
        flags=flags,
        tenant_config=tenant_config,
    )
    configured = {
        **base,
        "workflow_id": workflow_id,
        "actions": actions,
        "side_effects_allowed": side_effects_allowed,
    }

    if tenant_config.safe_mode:
        return WorkflowBridgeResult(
            **configured,
            status="blocked",
            reason="safe_mode_blocks_workflow",
        )
    if not bool(event_config.get("enabled", False)):
        return WorkflowBridgeResult(
            **configured,
            status="dry_run",
            reason="tenant_workflow_disabled",
        )
    if not flags.tenant_workflows_enabled:
        return WorkflowBridgeResult(
            **configured,
            status="dry_run",
            reason="tenant_workflows_disabled",
        )
    if not flags.workflow_side_effects_enabled:
        return WorkflowBridgeResult(
            **configured,
            status="dry_run",
            reason="workflow_side_effects_disabled",
        )
    if not flags.actions_enabled:
        return WorkflowBridgeResult(**configured, status="dry_run", reason="actions_disabled")
    if not _entry_bool(ledger_entry, "side_effects_allowed"):
        return WorkflowBridgeResult(
            **configured,
            status="dry_run",
            reason="ledger_side_effects_disabled",
        )
    if not bool(event_config.get("side_effects_allowed", False)):
        return WorkflowBridgeResult(
            **configured,
            status="dry_run",
            reason="tenant_side_effects_disabled",
        )
    if bool(event_config.get("dry_run_by_default", True)):
        return WorkflowBridgeResult(**configured, status="dry_run", reason="dry_run_by_default")
    if flags.allow_test_execution:
        return WorkflowBridgeResult(
            **configured,
            status="executed",
            reason="fake_executor_completed",
        )
    return WorkflowBridgeResult(**configured, status="eligible", reason="workflow_eligible_preview")


async def consume_business_event_ledger_row(
    session: AsyncSession,
    *,
    tenant_id: str,
    conversation_id: str,
    ledger_row: BusinessEventLedgerRow,
    tenant_config: TenantRuntimeConfigContext,
    runtime_flags: WorkflowBridgeRuntimeFlags | None = None,
) -> WorkflowBridgeResult:
    result = evaluate_workflow_bridge(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        ledger_entry=ledger_row,
        tenant_config=tenant_config,
        runtime_flags=runtime_flags,
    )
    if result.status != "duplicate":
        ledger_row.workflow_result = result.model_dump(mode="json")
        ledger_row.status = result.status
        ledger_row.reason = result.reason
        ledger_row.side_effects_allowed = result.side_effects_allowed
        session.add(ledger_row)
    return result


def attach_workflow_bridge_results_to_trace(
    output: TurnOutput,
    results: list[WorkflowBridgeResult],
    *,
    replace: bool = False,
) -> TurnOutput:
    trace = dict(output.trace_metadata)
    existing = [] if replace else [_jsonable(item) for item in _list(trace.get("workflow_results"))]
    trace["workflow_results"] = [
        *existing,
        *[result.model_dump(mode="json") for result in results],
    ]
    universal_trace = trace.get("universal_turn_trace")
    if isinstance(universal_trace, dict):
        trace["universal_turn_trace"] = {
            **universal_trace,
            "workflow_results": trace["workflow_results"],
        }
    return output.model_copy(update={"trace_metadata": trace})


def workflow_bridge_trace_payload(results: list[WorkflowBridgeResult]) -> dict[str, Any]:
    return {"workflow_results": [result.model_dump(mode="json") for result in results]}


def _workflow_event_config(
    tenant_config: TenantRuntimeConfigContext,
    event_type: str,
) -> dict[str, Any]:
    raw = tenant_config.workflow_event_metadata.get(event_type)
    return dict(raw) if isinstance(raw, dict) else {}


def _side_effects_allowed(
    *,
    ledger_entry: Any,
    event_config: dict[str, Any],
    flags: WorkflowBridgeRuntimeFlags,
    tenant_config: TenantRuntimeConfigContext,
) -> bool:
    return all(
        [
            not tenant_config.safe_mode,
            flags.actions_enabled,
            flags.workflow_side_effects_enabled,
            flags.workflow_events_enabled,
            flags.tenant_workflows_enabled,
            _entry_bool(ledger_entry, "side_effects_allowed"),
            bool(event_config.get("enabled", False)),
            bool(event_config.get("side_effects_allowed", False)),
            not bool(event_config.get("dry_run_by_default", True)),
        ]
    )


def _is_duplicate(entry: Any) -> bool:
    if isinstance(entry, BusinessEventLedgerRecord):
        return entry.duplicate
    return _entry_text(entry, "status") == "duplicate" or _entry_bool(entry, "duplicate")


def _entry_reason(entry: Any) -> str:
    return _entry_optional_text(entry, "reason") or "ledger_event_blocked"


def _entry_text(entry: Any, key: str) -> str:
    value = _entry_value(entry, key)
    return str(value) if value is not None else ""


def _entry_optional_text(entry: Any, key: str) -> str | None:
    value = _entry_value(entry, key)
    if value in (None, ""):
        return None
    return str(value)


def _entry_bool(entry: Any, key: str) -> bool:
    value = _entry_value(entry, key)
    return bool(value)


def _entry_value(entry: Any, key: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(key)
    value = getattr(entry, key, None)
    if isinstance(value, UUID):
        return str(value)
    return value


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _actions(event_config: dict[str, Any]) -> list[dict[str, Any]]:
    value = event_config.get("actions")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


__all__ = [
    "WorkflowBridgeLedgerStatus",
    "WorkflowBridgeResult",
    "WorkflowBridgeRuntimeFlags",
    "WorkflowBridgeStatus",
    "attach_workflow_bridge_results_to_trace",
    "consume_business_event_ledger_row",
    "evaluate_workflow_bridge",
    "workflow_bridge_trace_payload",
]

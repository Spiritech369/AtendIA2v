from __future__ import annotations

from inspect import isawaitable
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atendia.agent_runtime.respond_style_context_builder import (
    ContextSnapshotError,
    RespondStyleContextPackageBuilder,
    RespondStyleContextSnapshot,
)
from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoop
from atendia.agent_runtime.respond_style_turn_contract import (
    FinalTurnDecision,
    JsonDict,
)

NO_SIDE_EFFECTS: dict[str, bool] = {
    "delivery": False,
    "workflows": False,
    "actions": False,
    "field_writes": False,
}


class ProductAgentRuntimeInput(BaseModel):
    """Identifies one inbound turn for a published Product Agent.

    The runtime input carries only turn identity and the inbound event; all
    configuration and state are resolved by the snapshot adapter.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    agent_id: str
    conversation_id: str
    contact_id: str | None = None
    channel: str = "no_send_direct"
    inbound_text: str
    inbound_event_id: str | None = None
    attachments: list[JsonDict] = Field(default_factory=list)
    requested_mode: Literal["no_send"] = "no_send"
    trace_context: JsonDict = Field(default_factory=dict)

    @field_validator("tenant_id", "agent_id", "conversation_id", "inbound_text")
    @classmethod
    def require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("runtime input text field cannot be blank")
        return cleaned


class ProductAgentRuntimeResult(BaseModel):
    """Auditable no-send result of one direct-path Product Agent turn.

    Nothing in this result has been delivered, persisted, or executed:
    field updates, workflow events, actions, and handoff are proposals for
    a later validated execution layer.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    tenant_id: str
    agent_id: str
    agent_version_id: str | None = None
    conversation_id: str
    final_message: str | None = None
    send_decision: str = "no_send"
    validation_result: JsonDict = Field(default_factory=dict)
    tool_results: list[JsonDict] = Field(default_factory=list)
    field_update_proposals: list[JsonDict] = Field(default_factory=list)
    workflow_event_proposals: list[JsonDict] = Field(default_factory=list)
    action_proposals: list[JsonDict] = Field(default_factory=list)
    handoff_proposal: JsonDict | None = None
    retry_instruction: JsonDict | None = None
    blocked_reason: str | None = None
    trace: JsonDict = Field(default_factory=dict)
    side_effects_allowed: Literal[False] = False
    side_effects: dict[str, bool] = Field(default_factory=lambda: dict(NO_SIDE_EFFECTS))

    @field_validator("send_decision")
    @classmethod
    def require_no_send(cls, value: str) -> str:
        if value != "no_send":
            raise ValueError("product agent runtime direct path must remain no_send")
        return value


class ProductAgentRuntimeSnapshotAdapter(Protocol):
    """Resolves Product Agent config + conversation state into a snapshot.

    Implementations own all I/O (DB, config services). The runtime and the
    builder stay pure.
    """

    def load_snapshot(
        self,
        runtime_input: ProductAgentRuntimeInput,
    ) -> RespondStyleContextSnapshot: ...


class ProductAgentRuntime:
    """Direct no-send path for published Product Agents.

    Pipeline: ProductAgentRuntimeInput -> snapshot adapter ->
    RespondStyleContextPackageBuilder -> RespondStyleToolLoop ->
    ProductAgentRuntimeResult. It never enqueues, never persists, never
    runs workflow/action side effects, and never touches legacy
    composition paths. Any non-no_send mode fails closed.
    """

    def __init__(
        self,
        *,
        snapshot_adapter: ProductAgentRuntimeSnapshotAdapter,
        tool_loop: RespondStyleToolLoop,
        builder: RespondStyleContextPackageBuilder | None = None,
    ) -> None:
        self._snapshot_adapter = snapshot_adapter
        self._tool_loop = tool_loop
        self._builder = builder or RespondStyleContextPackageBuilder()

    async def run_turn(
        self,
        runtime_input: ProductAgentRuntimeInput,
    ) -> ProductAgentRuntimeResult:
        try:
            snapshot = await self._load_snapshot(runtime_input)
        except ContextSnapshotError as exc:
            return _blocked_result(runtime_input, reason=exc.code)
        except Exception as exc:  # fail closed: adapter errors must never crash live-ward
            return _blocked_result(
                runtime_input,
                reason=f"snapshot_adapter_failed:{type(exc).__name__}",
            )

        if snapshot.send_mode != "no_send":
            return _blocked_result(
                runtime_input,
                reason="send_mode_not_no_send",
                agent_version_id=snapshot.agent_version_id,
            )
        if snapshot.runtime_mode not in ("test_lab_no_send", "readiness_no_send"):
            return _blocked_result(
                runtime_input,
                reason="runtime_mode_not_no_send",
                agent_version_id=snapshot.agent_version_id,
            )

        try:
            built = self._builder.build(snapshot)
        except ContextSnapshotError as exc:
            return _blocked_result(
                runtime_input,
                reason=exc.code,
                agent_version_id=snapshot.agent_version_id,
            )

        decision = await self._tool_loop.run(
            turn_input=built.turn_input,
            context=built.context_package,
        )
        return _result_from_decision(
            runtime_input=runtime_input,
            snapshot=snapshot,
            decision=decision,
        )

    async def _load_snapshot(
        self,
        runtime_input: ProductAgentRuntimeInput,
    ) -> RespondStyleContextSnapshot:
        snapshot = self._snapshot_adapter.load_snapshot(runtime_input)
        if isawaitable(snapshot):
            snapshot = await snapshot
        return snapshot


def _blocked_result(
    runtime_input: ProductAgentRuntimeInput,
    *,
    reason: str,
    agent_version_id: str | None = None,
) -> ProductAgentRuntimeResult:
    return ProductAgentRuntimeResult(
        run_id=_run_id(),
        tenant_id=runtime_input.tenant_id,
        agent_id=runtime_input.agent_id,
        agent_version_id=agent_version_id,
        conversation_id=runtime_input.conversation_id,
        final_message=None,
        send_decision="no_send",
        blocked_reason=reason,
        trace={
            "respond_style_product_agent_runtime": {
                "mode": "no_send",
                "blocked": reason,
            }
        },
    )


def _result_from_decision(
    *,
    runtime_input: ProductAgentRuntimeInput,
    snapshot: RespondStyleContextSnapshot,
    decision: FinalTurnDecision,
) -> ProductAgentRuntimeResult:
    validation = (
        decision.validation.model_dump(mode="json")
        if decision.validation is not None
        else {}
    )
    retry = (
        decision.retry_instruction.model_dump(mode="json")
        if decision.retry_instruction is not None
        else None
    )
    loop_trace = decision.trace_metadata.get("respond_style_tool_loop", {})
    tool_results = [
        item for item in (loop_trace.get("tool_results") or []) if isinstance(item, dict)
    ]
    handoff = (
        decision.accepted_handoff.model_dump(mode="json")
        if decision.accepted_handoff is not None
        else None
    )
    blocked_reason = None
    if decision.validation is not None and decision.validation.status == "blocked":
        blocked_reason = decision.validation.blocked_reason
    return ProductAgentRuntimeResult(
        run_id=_run_id(),
        tenant_id=runtime_input.tenant_id,
        agent_id=runtime_input.agent_id,
        agent_version_id=snapshot.agent_version_id,
        conversation_id=runtime_input.conversation_id,
        final_message=decision.final_message,
        send_decision="no_send",
        validation_result=validation,
        tool_results=tool_results,
        field_update_proposals=[
            item.model_dump(mode="json") for item in decision.accepted_field_writes
        ],
        workflow_event_proposals=[
            item.model_dump(mode="json") for item in decision.accepted_workflow_events
        ],
        action_proposals=[
            item.model_dump(mode="json") for item in decision.accepted_actions
        ],
        handoff_proposal=handoff,
        retry_instruction=retry,
        blocked_reason=blocked_reason,
        trace={
            "respond_style_product_agent_runtime": {
                "mode": "no_send",
                "runtime_path": "respond_style_no_send_direct",
                "agent_version_id": snapshot.agent_version_id,
                "deployment_id": snapshot.deployment_id,
            },
            **decision.trace_metadata,
        },
    )


def _run_id() -> str:
    return f"product-agent-direct-{uuid4().hex}"


__all__ = [
    "NO_SIDE_EFFECTS",
    "ProductAgentRuntime",
    "ProductAgentRuntimeInput",
    "ProductAgentRuntimeResult",
    "ProductAgentRuntimeSnapshotAdapter",
]

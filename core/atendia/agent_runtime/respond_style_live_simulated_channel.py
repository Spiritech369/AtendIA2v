from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.respond_style_context_builder import TranscriptMessage
from atendia.agent_runtime.respond_style_product_agent_config_adapter import (
    ConversationStateSnapshot,
    ProductAgentConfigSnapshotAdapter,
    ProductAgentPublishedConfig,
)
from atendia.agent_runtime.respond_style_product_agent_runtime import (
    NO_SIDE_EFFECTS,
    ProductAgentRuntime,
    ProductAgentRuntimeInput,
    ProductAgentRuntimeResult,
)
from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoop

JsonDict = dict[str, Any]


class SimulatedTurnRecord(BaseModel):
    """Full audit capture of one simulated live turn. Nothing here was
    delivered, persisted, or executed."""

    model_config = ConfigDict(extra="forbid")

    turn_number: int
    inbound_text: str
    final_message_candidate: str | None = None
    simulated_outbound: bool = False
    send_decision: str = "no_send"
    blocked_reason: str | None = None
    validation_result: JsonDict = Field(default_factory=dict)
    tool_results: list[JsonDict] = Field(default_factory=list)
    field_update_proposals: list[JsonDict] = Field(default_factory=list)
    simulated_field_writes: JsonDict = Field(default_factory=dict)
    workflow_event_proposals: list[JsonDict] = Field(default_factory=list)
    action_proposals: list[JsonDict] = Field(default_factory=list)
    handoff_proposal: JsonDict | None = None
    retry_instruction: JsonDict | None = None
    send_policy: JsonDict = Field(default_factory=dict)
    trace: JsonDict = Field(default_factory=dict)
    side_effects: dict[str, bool] = Field(default_factory=lambda: dict(NO_SIDE_EFFECTS))


class SimulatedChannelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    turns: int
    simulated_outbound_count: int
    blocked_turns: int
    outbound_outbox_writes: Literal[0] = 0
    side_effects: dict[str, bool] = Field(default_factory=lambda: dict(NO_SIDE_EFFECTS))


class LiveSimulatedChannel:
    """WhatsApp-shaped harness over the direct ProductAgentRuntime path.

    Same route as Test Lab / Phase 8-9 (config adapter -> context builder
    -> tool loop -> validator), but delivery is simulated: a valid
    final_message becomes a simulated outbound appended to the in-memory
    conversation, and accepted field proposals update only the in-memory
    contact state so multi-turn conversations can progress. There is no
    outbound_outbox write, no delivery adapter, no workflow/action
    execution, and no persistence of any kind.
    """

    def __init__(
        self,
        *,
        config: ProductAgentPublishedConfig,
        tool_loop: RespondStyleToolLoop,
        conversation_id: str,
        contact_id: str | None = None,
        send_policy_label: str = "no_send",
    ) -> None:
        self._config = config
        self._conversation_id = conversation_id
        self._contact_id = contact_id or "simulated-contact"
        # Label only: every turn remains no_send regardless of this value.
        self._send_policy_label = send_policy_label
        self._messages: list[TranscriptMessage] = []
        self._field_values: JsonDict = {}
        self._records: list[SimulatedTurnRecord] = []
        adapter = ProductAgentConfigSnapshotAdapter(
            config_source=_StaticConfigSource(config),
            state_source=_ChannelStateSource(self),
        )
        self._runtime = ProductAgentRuntime(
            snapshot_adapter=adapter,
            tool_loop=tool_loop,
        )

    @property
    def records(self) -> list[SimulatedTurnRecord]:
        return list(self._records)

    @property
    def field_values(self) -> JsonDict:
        return dict(self._field_values)

    @property
    def transcript(self) -> list[JsonDict]:
        return [message.model_dump(mode="json") for message in self._messages]

    def state_snapshot(self) -> ConversationStateSnapshot:
        return ConversationStateSnapshot(
            recent_messages=list(self._messages),
            field_values=dict(self._field_values),
        )

    async def receive(self, inbound_text: str) -> SimulatedTurnRecord:
        turn_number = len(self._records) + 1
        result = await self._runtime.run_turn(
            ProductAgentRuntimeInput(
                tenant_id=self._config.tenant_id,
                agent_id=self._config.agent_id,
                conversation_id=self._conversation_id,
                contact_id=self._contact_id,
                channel="live_simulated_no_send",
                inbound_text=inbound_text,
                inbound_event_id=f"sim-{self._conversation_id}-{turn_number}",
            )
        )
        self._messages.append(
            TranscriptMessage(
                role="customer",
                text=inbound_text,
                message_id=f"in-{turn_number}",
            )
        )
        record = self._record_turn(turn_number, inbound_text, result)
        self._records.append(record)
        return record

    def summary(self) -> SimulatedChannelSummary:
        return SimulatedChannelSummary(
            conversation_id=self._conversation_id,
            turns=len(self._records),
            simulated_outbound_count=sum(
                1 for record in self._records if record.simulated_outbound
            ),
            blocked_turns=sum(
                1 for record in self._records if record.blocked_reason is not None
            ),
        )

    def _record_turn(
        self,
        turn_number: int,
        inbound_text: str,
        result: ProductAgentRuntimeResult,
    ) -> SimulatedTurnRecord:
        validation_status = result.validation_result.get("status")
        deliverable = (
            result.final_message is not None
            and validation_status == "valid"
            and result.blocked_reason is None
        )
        simulated_writes: JsonDict = {}
        if deliverable:
            self._messages.append(
                TranscriptMessage(
                    role="assistant",
                    text=result.final_message or "",
                    message_id=f"sim-out-{turn_number}",
                )
            )
            for proposal in result.field_update_proposals:
                field_key = proposal.get("field_key")
                if field_key:
                    self._field_values[str(field_key)] = proposal.get("value")
                    simulated_writes[str(field_key)] = proposal.get("value")
        return SimulatedTurnRecord(
            turn_number=turn_number,
            inbound_text=inbound_text,
            final_message_candidate=result.final_message,
            simulated_outbound=deliverable,
            send_decision=result.send_decision,
            blocked_reason=result.blocked_reason,
            validation_result=result.validation_result,
            tool_results=result.tool_results,
            field_update_proposals=result.field_update_proposals,
            simulated_field_writes=simulated_writes,
            workflow_event_proposals=result.workflow_event_proposals,
            action_proposals=result.action_proposals,
            handoff_proposal=result.handoff_proposal,
            retry_instruction=result.retry_instruction,
            send_policy={
                "send_mode": "no_send",
                "send_policy_label": self._send_policy_label,
                "delivery": "simulated",
                "outbound_outbox_writes": 0,
            },
            trace=result.trace,
        )


class _StaticConfigSource:
    def __init__(self, config: ProductAgentPublishedConfig) -> None:
        self._config = config

    def load_config(
        self, runtime_input: ProductAgentRuntimeInput
    ) -> ProductAgentPublishedConfig:
        return self._config


class _ChannelStateSource:
    def __init__(self, channel: LiveSimulatedChannel) -> None:
        self._channel = channel

    def load_state(
        self, runtime_input: ProductAgentRuntimeInput
    ) -> ConversationStateSnapshot:
        return self._channel.state_snapshot()


__all__ = [
    "LiveSimulatedChannel",
    "SimulatedChannelSummary",
    "SimulatedTurnRecord",
]

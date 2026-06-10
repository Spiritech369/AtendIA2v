from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.respond_style_live_simulated_channel import (
    LiveSimulatedChannel,
    SimulatedTurnRecord,
)
from atendia.agent_runtime.respond_style_product_agent_config_adapter import (
    ProductAgentPublishedConfig,
)
from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoop

JsonDict = dict[str, Any]


class TestLabScenario(BaseModel):
    __test__ = False  # not a pytest class

    model_config = ConfigDict(extra="forbid")

    name: str
    turns: list[str] = Field(min_length=1)
    expected: JsonDict = Field(default_factory=dict)


class TestLabTurnEvidence(BaseModel):
    """JSON-serializable evidence for one direct-path Test Lab turn."""

    model_config = ConfigDict(extra="forbid")

    turn_number: int
    inbound_text: str
    final_message: str | None = None
    send_decision: Literal["no_send"] = "no_send"
    simulated_outbound: bool = False
    blocked_reason: str | None = None
    validation_result: JsonDict = Field(default_factory=dict)
    provisional_field_keys: list[str] = Field(default_factory=list)
    tools: list[JsonDict] = Field(default_factory=list)
    tool_results: list[JsonDict] = Field(default_factory=list)
    field_update_proposals: list[JsonDict] = Field(default_factory=list)
    workflow_event_proposals: list[JsonDict] = Field(default_factory=list)
    handoff_proposal: JsonDict | None = None
    trace: JsonDict = Field(default_factory=dict)


class TestLabScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    scenario_name: str
    runtime_path: Literal["respond_style_product_agent_direct"] = (
        "respond_style_product_agent_direct"
    )
    turns: list[TestLabTurnEvidence] = Field(default_factory=list)
    transcript: list[JsonDict] = Field(default_factory=list)
    final_contact_state: JsonDict = Field(default_factory=dict)
    outbound_outbox_writes: Literal[0] = 0
    side_effects: dict[str, bool] = Field(
        default_factory=lambda: {
            "delivery": False,
            "workflows": False,
            "actions": False,
            "field_writes": False,
        }
    )


class TestLabEvidenceSink(Protocol):
    """Persists scenario evidence. Implementations own all I/O (DB/API);
    the runner itself never persists anything."""

    def save_evidence(self, result: TestLabScenarioResult) -> None: ...


class InMemoryEvidenceSink:
    def __init__(self) -> None:
        self.saved: list[TestLabScenarioResult] = []

    def save_evidence(self, result: TestLabScenarioResult) -> None:
        self.saved.append(result)


class ToolLoopFactory(Protocol):
    def __call__(self) -> RespondStyleToolLoop: ...


class RespondStyleTestLabDirect:
    """Test Lab execution over the direct ProductAgentRuntime path.

    Each scenario runs as a fresh simulated conversation through
    LiveSimulatedChannel (config adapter -> context builder -> tool loop ->
    validator -> ProductAgentRuntime). Delivery is simulated, state is
    in-memory, every turn is no_send, and evidence is handed to the
    injected sink — this runner performs no persistence of its own.
    """

    def __init__(
        self,
        *,
        config: ProductAgentPublishedConfig,
        tool_loop_factory: ToolLoopFactory,
        evidence_sink: TestLabEvidenceSink | None = None,
    ) -> None:
        self._config = config
        self._tool_loop_factory = tool_loop_factory
        self._evidence_sink = evidence_sink or InMemoryEvidenceSink()

    @property
    def evidence_sink(self) -> TestLabEvidenceSink:
        return self._evidence_sink

    async def run_scenario(self, scenario: TestLabScenario) -> TestLabScenarioResult:
        channel = LiveSimulatedChannel(
            config=self._config,
            tool_loop=self._tool_loop_factory(),
            conversation_id=f"test-lab-{scenario.name}-{uuid4().hex[:8]}",
        )
        evidence: list[TestLabTurnEvidence] = []
        for inbound_text in scenario.turns:
            record = await channel.receive(inbound_text)
            evidence.append(_turn_evidence(record))
        result = TestLabScenarioResult(
            run_id=f"test-lab-direct-{uuid4().hex}",
            scenario_name=scenario.name,
            turns=evidence,
            transcript=channel.transcript,
            final_contact_state=channel.field_values,
        )
        self._evidence_sink.save_evidence(result)
        return result

    async def run_scenarios(
        self, scenarios: list[TestLabScenario]
    ) -> list[TestLabScenarioResult]:
        return [await self.run_scenario(scenario) for scenario in scenarios]


def _turn_evidence(record: SimulatedTurnRecord) -> TestLabTurnEvidence:
    loop_trace = record.trace.get("respond_style_tool_loop", {})
    provisional = [
        str(item) for item in loop_trace.get("provisional_field_keys") or []
    ]
    tools = [
        {"tool_name": item.get("tool_name"), "status": item.get("status")}
        for item in record.tool_results
        if isinstance(item, dict)
    ]
    return TestLabTurnEvidence(
        turn_number=record.turn_number,
        inbound_text=record.inbound_text,
        final_message=record.final_message_candidate,
        send_decision="no_send",
        simulated_outbound=record.simulated_outbound,
        blocked_reason=record.blocked_reason,
        validation_result=record.validation_result,
        provisional_field_keys=provisional,
        tools=tools,
        tool_results=record.tool_results,
        field_update_proposals=record.field_update_proposals,
        workflow_event_proposals=record.workflow_event_proposals,
        handoff_proposal=record.handoff_proposal,
        trace=record.trace,
    )


__all__ = [
    "InMemoryEvidenceSink",
    "RespondStyleTestLabDirect",
    "TestLabEvidenceSink",
    "TestLabScenario",
    "TestLabScenarioResult",
    "TestLabTurnEvidence",
]

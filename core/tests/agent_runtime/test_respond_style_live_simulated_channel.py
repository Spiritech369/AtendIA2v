from __future__ import annotations

import re
from pathlib import Path

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    ContextSnapshotError,
    ConversationStateSnapshot,
    FinalTurnDecision,
    LiveSimulatedChannel,
    LLMFieldUpdateProposal,
    LLMHandoffProposal,
    LLMToolCallProposal,
    ProductAgentConfigSnapshotAdapter,
    ProductAgentPublishedConfig,
    ProductAgentRuntimeInput,
    RespondStyleToolLoop,
    published_config_from_version_payload,
)
from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult

ADAPTER_SOURCE = Path(
    "core/atendia/agent_runtime/respond_style_product_agent_config_adapter.py"
)
CHANNEL_SOURCE = Path(
    "core/atendia/agent_runtime/respond_style_live_simulated_channel.py"
)


def _config(**overrides) -> ProductAgentPublishedConfig:
    base = {
        "tenant_id": "generic-tenant",
        "agent_id": "generic-agent",
        "agent_version_id": "v3",
        "publish_state": "published",
        "agent_name": "Generic Assistant",
        "persona": "helpful advisor",
        "instructions": "Use configured capabilities only.",
        "language": "es",
        "tone": "brief, human",
        "tool_bindings": [
            {
                "name": "requirements.lookup",
                "description": "Returns factual requirements for a validated selection.",
            }
        ],
        "field_definitions": [
            {"field_key": "service_interest", "required": True},
            {"field_key": "preferred_schedule", "required": True},
        ],
        "workflow_bindings": [
            {"binding_name": "ready_for_handoff", "event_name": "lead.ready"}
        ],
        "handoff": {"enabled": True, "targets": ["support"]},
    }
    base.update(overrides)
    return ProductAgentPublishedConfig(**base)


class _FakeTurnProvider:
    def __init__(self, decisions: list[FinalTurnDecision]) -> None:
        self._decisions = list(decisions)
        self.contexts: list[AgentContextPackage] = []
        self.turn_inputs: list[AgentTurnInput] = []

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        self.turn_inputs.append(turn_input)
        self.contexts.append(context)
        return self._decisions.pop(0)


class _FakeToolExecutor:
    def __init__(self, results: list[ToolExecutionResult] | None = None) -> None:
        self._results = list(results or [])
        self.calls: list[LLMToolCallProposal] = []

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        self.calls.append(tool_call)
        return self._results.pop(0)


def _valid_decision(final_message: str | None, **overrides) -> FinalTurnDecision:
    validation = AgentTurnValidationResult(
        status="valid",
        accepted_tool_requests=overrides.pop("tool_requests", []),
        send_decision="no_send",
    )
    return FinalTurnDecision(
        final_message=final_message,
        send_decision="no_send",
        validation=validation,
        **overrides,
    )


def _channel(decisions: list[FinalTurnDecision], **channel_overrides) -> LiveSimulatedChannel:
    provider = _FakeTurnProvider(decisions)
    executor = channel_overrides.pop("executor", _FakeToolExecutor())
    channel = LiveSimulatedChannel(
        config=channel_overrides.pop("config", _config()),
        tool_loop=RespondStyleToolLoop(provider=provider, executor=executor),
        conversation_id="sim-conv-1",
        **channel_overrides,
    )
    channel._test_provider = provider  # type: ignore[attr-defined]
    return channel


# --- Phase 9 adapter ---------------------------------------------------


def test_adapter_maps_config_and_state_to_snapshot() -> None:
    class _ConfigSource:
        def load_config(self, runtime_input):
            return _config()

    class _StateSource:
        def load_state(self, runtime_input):
            return ConversationStateSnapshot(
                field_values={"service_interest": "general"},
                conversation_stage="discovery",
            )

    adapter = ProductAgentConfigSnapshotAdapter(
        config_source=_ConfigSource(), state_source=_StateSource()
    )
    snapshot = adapter.load_snapshot(
        ProductAgentRuntimeInput(
            tenant_id="generic-tenant",
            agent_id="generic-agent",
            conversation_id="conv-9",
            inbound_text="hola",
        )
    )

    assert snapshot.send_mode == "no_send"
    assert snapshot.runtime_mode == "test_lab_no_send"
    assert snapshot.agent_version_id == "v3"
    assert snapshot.publish_state == "published"
    fields = {field.field_key: field for field in snapshot.contact_fields}
    assert fields["service_interest"].current_value == "general"
    assert fields["preferred_schedule"].current_value is None
    assert snapshot.conversation_stage == "discovery"


def test_version_payload_mapping_follows_product_agent_schema() -> None:
    config = published_config_from_version_payload(
        {
            "role": "advisor persona",
            "tone": "warm",
            "language": "es",
            "instructions": "Answer from facts only.",
            "knowledge_policy": {"snippets": [{"source_id": "kb-1", "excerpt": "x"}]},
            "tool_policy": {"bindings": [{"name": "faq.lookup", "description": "d"}]},
            "field_policy": {"fields": [{"field_key": "issue_type"}]},
            "safety_policy": {
                "handoff": {"enabled": True, "targets": ["support"]},
                "hard_policies": [
                    {
                        "policy_id": "p1",
                        "trigger_patterns": ["x"],
                        "requires_any": ["tool:faq.lookup"],
                    }
                ],
            },
        },
        tenant_id="generic-tenant",
        agent_id="generic-agent",
        agent_version_id="v7",
    )

    assert config.persona == "advisor persona"
    assert config.kb_snippets[0]["source_id"] == "kb-1"
    assert config.tool_bindings[0]["name"] == "faq.lookup"
    assert config.field_definitions[0]["field_key"] == "issue_type"
    assert config.hard_policies[0]["policy_id"] == "p1"


def test_version_payload_malformed_fails_closed() -> None:
    with pytest.raises(ContextSnapshotError):
        published_config_from_version_payload(
            {"tool_policy": "not-a-dict"},
            tenant_id="t",
            agent_id="a",
            agent_version_id="v",
        )


def test_field_definition_without_key_fails_closed() -> None:
    class _ConfigSource:
        def load_config(self, runtime_input):
            return _config(field_definitions=[{"label": "missing key"}])

    class _StateSource:
        def load_state(self, runtime_input):
            return ConversationStateSnapshot()

    adapter = ProductAgentConfigSnapshotAdapter(
        config_source=_ConfigSource(), state_source=_StateSource()
    )
    with pytest.raises(ContextSnapshotError) as excinfo:
        adapter.load_snapshot(
            ProductAgentRuntimeInput(
                tenant_id="t",
                agent_id="a",
                conversation_id="c",
                inbound_text="hola",
            )
        )
    assert excinfo.value.code == "field_definition_missing_key"


# --- Phase 9.5 simulated channel ----------------------------------------


@pytest.mark.asyncio
async def test_valid_turn_appends_simulated_outbound_and_keeps_order() -> None:
    channel = _channel([
        _valid_decision("Hola, claro que te ayudo."),
        _valid_decision("Listo, agendado quedo."),
    ])

    first = await channel.receive("hola")
    second = await channel.receive("quiero agendar")

    assert first.simulated_outbound is True
    assert first.final_message_candidate == "Hola, claro que te ayudo."
    assert second.simulated_outbound is True
    roles = [item["role"] for item in channel.transcript]
    texts = [item["text"] for item in channel.transcript]
    assert roles == ["customer", "assistant", "customer", "assistant"]
    assert texts[0] == "hola"
    assert texts[1] == "Hola, claro que te ayudo."


@pytest.mark.asyncio
async def test_prior_turns_feed_next_turn_context() -> None:
    channel = _channel([
        _valid_decision("first reply"),
        _valid_decision("second reply"),
    ])
    provider = channel._test_provider  # type: ignore[attr-defined]

    await channel.receive("hola")
    await channel.receive("sigo aqui")

    second_turn_input = provider.turn_inputs[1]
    history = [item["text"] for item in second_turn_input.recent_messages]
    assert history == ["hola", "first reply"]


@pytest.mark.asyncio
async def test_field_proposals_update_only_simulated_state() -> None:
    channel = _channel([
        _valid_decision(
            "Anotado.",
            accepted_field_writes=[
                LLMFieldUpdateProposal(
                    field_key="service_interest",
                    value="general",
                    evidence=["customer message"],
                    confidence=0.9,
                    reason="customer stated interest",
                )
            ],
        ),
        _valid_decision("ok"),
    ])
    provider = channel._test_provider  # type: ignore[attr-defined]

    record = await channel.receive("me interesa el servicio general")

    assert record.simulated_field_writes == {"service_interest": "general"}
    assert channel.field_values == {"service_interest": "general"}
    assert record.side_effects["field_writes"] is False

    # Next turn sees the simulated value in contact state.
    await channel.receive("que sigue?")
    identity = provider.contexts[1].agent_identity
    assert identity["contact_state"] == {"service_interest": "general"}


@pytest.mark.asyncio
async def test_blocked_turn_produces_no_simulated_outbound() -> None:
    tool_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="asked")
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="requirements.lookup",
            status="failed",
            error_code="upstream_unavailable",
        )
    ])
    channel = _channel(
        [_valid_decision(None, tool_requests=[tool_call])],
        executor=executor,
    )

    record = await channel.receive("que necesito?")

    assert record.simulated_outbound is False
    assert record.blocked_reason == "required_tool_failed:upstream_unavailable"
    assert record.send_decision == "no_send"
    roles = [item["role"] for item in channel.transcript]
    assert roles == ["customer"]  # no assistant message appended


@pytest.mark.asyncio
async def test_handoff_proposal_is_captured_not_executed() -> None:
    channel = _channel([
        _valid_decision(
            "Te comunico con una persona del equipo.",
            accepted_handoff=LLMHandoffProposal(
                needed=True, reason="customer asked for a human", target="support"
            ),
        ),
    ])

    record = await channel.receive("quiero hablar con una persona")

    assert record.handoff_proposal is not None
    assert record.handoff_proposal["target"] == "support"
    assert record.side_effects == {
        "delivery": False,
        "workflows": False,
        "actions": False,
        "field_writes": False,
    }


@pytest.mark.asyncio
async def test_summary_reports_zero_outbox_writes() -> None:
    channel = _channel([_valid_decision("ok")])
    await channel.receive("hola")

    summary = channel.summary()
    assert summary.outbound_outbox_writes == 0
    assert summary.turns == 1
    assert summary.simulated_outbound_count == 1
    assert summary.side_effects["delivery"] is False

    record = channel.records[0]
    assert record.send_policy == {
        "send_mode": "no_send",
        "delivery": "simulated",
        "outbound_outbox_writes": 0,
    }


def test_sources_have_no_unsafe_legacy_or_live_imports() -> None:
    for source_path in (ADAPTER_SOURCE, CHANNEL_SOURCE):
        source = source_path.read_text(encoding="utf-8")
        forbidden = [
            "ConversationRunner",
            "HumanResponseComposer",
            "StructuredRuntimeComposer",
            "ValidatedResponsePlan",
            "SendAdapter",
            "outbound_dispatcher",
            "stage_outbound",
            "enqueue_messages",
            "evaluate_event",
            "AgentService",
            "advisor_pipeline",
            "composer",
            "baileys",
        ]
        assert not any(term in source for term in forbidden), source_path


def test_sources_have_no_tenant_or_vertical_hardcode() -> None:
    for source_path in (ADAPTER_SOURCE, CHANNEL_SOURCE):
        lowered = source_path.read_text(encoding="utf-8").casefold()
        forbidden_terms = [
            "dinamo",
            "motos",
            "credito",
            "credit",
            "sat",
            "metro",
            "r4",
            "barber",
            "dentist",
        ]
        assert not any(
            re.search(rf"\b{re.escape(term)}\b", lowered) for term in forbidden_terms
        ), source_path

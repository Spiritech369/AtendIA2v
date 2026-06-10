from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMFieldUpdateProposal,
    ManualLiveSimulator,
    ProductAgentPublishedConfig,
    RespondStyleToolLoop,
)

SIMULATOR_SOURCE = Path(
    "core/atendia/agent_runtime/respond_style_manual_simulator.py"
)
RUNNER_SOURCE = Path("tools/run_manual_live_simulator_2026_06_09.py")


class _ScriptedProvider:
    def __init__(self, decisions: list[FinalTurnDecision]) -> None:
        self._decisions = list(decisions)

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        return self._decisions.pop(0)


class _NoToolExecutor:
    def execute_tool(self, tool_call, context):  # pragma: no cover
        raise AssertionError("no tools expected")


class _MemoryReportWriter:
    def __init__(self) -> None:
        self.saved: dict[str, dict[str, str]] = {}

    def write(self, basename: str, *, json_text: str, md_text: str) -> list[str]:
        self.saved[basename] = {"json": json_text, "md": md_text}
        return [f"{basename}.json", f"{basename}.md"]


def _decision(final_message: str, **overrides) -> FinalTurnDecision:
    return FinalTurnDecision(
        final_message=final_message,
        send_decision="no_send",
        validation=AgentTurnValidationResult(status="valid", send_decision="no_send"),
        **overrides,
    )


def _config() -> ProductAgentPublishedConfig:
    return ProductAgentPublishedConfig(
        tenant_id="generic-tenant",
        agent_id="generic-agent",
        agent_version_id="v1",
        publish_state="published_no_send",
        agent_name="Generic Assistant",
        instructions="Use configured capabilities only.",
        field_definitions=[{"field_key": "selected_option", "required": True}],
    )


def _simulator(decisions: list[FinalTurnDecision]) -> tuple[
    ManualLiveSimulator, _MemoryReportWriter
]:
    writer = _MemoryReportWriter()
    provider = _ScriptedProvider(decisions)
    simulator = ManualLiveSimulator(
        config=_config(),
        tool_loop_factory=lambda: RespondStyleToolLoop(
            provider=provider, executor=_NoToolExecutor()
        ),
        report_writer=writer,
        run_label="2026_06_09_0000",
    )
    return simulator, writer


@pytest.mark.asyncio
async def test_simulator_runs_turns_through_product_agent_runtime() -> None:
    simulator, _ = _simulator([
        _decision("Hola, te ayudo con gusto."),
        _decision("Anotado, seguimos."),
    ])

    first = await simulator.handle_input("hola")
    second = await simulator.handle_input("quiero avanzar")

    assert first.kind == "turn"
    assert first.turn is not None
    assert first.turn.final_message_candidate == "Hola, te ayudo con gusto."
    assert first.turn.send_decision == "no_send"
    # Multi-turn transcript order is preserved in memory only.
    roles = [item["role"] for item in simulator.channel.transcript]
    assert roles == ["customer", "assistant", "customer", "assistant"]
    assert second.turn is not None
    assert second.turn.turn_number == 2
    # Display includes the required per-turn fields.
    joined = "\n".join(first.lines)
    for marker in (
        "inbound_text:",
        "simulated_final_message:",
        "send_decision:",
        "tools_requested:",
        "tool_results:",
        "field_proposals:",
        "simulated_fields_after_turn:",
        "workflow_proposals:",
        "handoff_proposal:",
        "validator_result:",
    ):
        assert marker in joined


@pytest.mark.asyncio
async def test_simulated_state_updates_in_memory_only() -> None:
    simulator, _ = _simulator([
        _decision(
            "Anotado.",
            accepted_field_writes=[
                LLMFieldUpdateProposal(
                    field_key="selected_option",
                    value="standard",
                    evidence=["customer message"],
                    confidence=0.9,
                    reason="stated",
                )
            ],
        ),
    ])

    output = await simulator.handle_input("me interesa la opcion estandar")

    assert output.turn is not None
    assert output.turn.simulated_field_writes == {"selected_option": "standard"}
    assert simulator.channel.field_values == {"selected_option": "standard"}
    assert output.turn.side_effects["field_writes"] is False


@pytest.mark.asyncio
async def test_blocked_turn_shows_no_send_reason_without_fallback_copy() -> None:
    from atendia.agent_runtime.respond_style_llm_provider import (
        blocked_provider_decision,
    )

    simulator, _ = _simulator([
        blocked_provider_decision("llm_turn_provider_failed", "Boom"),
    ])

    output = await simulator.handle_input("hola")

    assert output.turn is not None
    assert output.turn.final_message_candidate is None
    assert output.turn.blocked_reason == "llm_turn_provider_failed"
    assert any("no_send_reason:" in line for line in output.lines)


@pytest.mark.asyncio
async def test_trace_state_save_reset_commands() -> None:
    simulator, writer = _simulator([
        _decision("Hola."),
        _decision("Hola de nuevo."),
    ])

    empty_trace = await simulator.handle_input("/trace")
    assert empty_trace.lines == ["no turns yet"]

    await simulator.handle_input("hola")

    trace = await simulator.handle_input("/trace")
    assert "respond_style_product_agent_runtime" in trace.lines[0]

    state = await simulator.handle_input("/state")
    state_payload = json.loads(state.lines[0])
    assert state_payload["turns"] == 1
    assert state_payload["transcript_messages"] == 2

    saved = await simulator.handle_input("/save")
    assert saved.saved_paths == [
        "manual_live_simulator_run_2026_06_09_0000.json",
        "manual_live_simulator_run_2026_06_09_0000.md",
    ]
    report = json.loads(
        writer.saved["manual_live_simulator_run_2026_06_09_0000"]["json"]
    )
    assert report["mode"] == "no_send"
    assert report["summary"]["outbound_outbox_writes"] == 0
    assert not any(report["summary"]["side_effects"].values())
    assert report["turns"][0]["send_decision"] == "no_send"
    md_text = writer.saved["manual_live_simulator_run_2026_06_09_0000"]["md"]
    assert "# Manual Live Simulator Run (no-send)" in md_text
    assert "outbox=0" in md_text

    reset = await simulator.handle_input("/reset")
    assert reset.lines == ["conversation reset"]
    assert simulator.channel.records == []
    assert simulator.channel.transcript == []

    # Fresh conversation works after reset.
    output = await simulator.handle_input("hola")
    assert output.turn is not None
    assert output.turn.turn_number == 1


@pytest.mark.asyncio
async def test_exit_and_unknown_commands() -> None:
    simulator, _ = _simulator([])

    exit_output = await simulator.handle_input("/exit")
    assert exit_output.kind == "exit"

    unknown = await simulator.handle_input("/nope")
    assert unknown.kind == "info"
    assert "unknown command /nope" in unknown.lines[0]


def test_simulator_sources_have_no_legacy_imports() -> None:
    for source_path in (SIMULATOR_SOURCE, RUNNER_SOURCE):
        source = source_path.read_text(encoding="utf-8")
        forbidden = [
            "ConversationRunner",
            "HumanResponseComposer",
            "StructuredRuntimeComposer",
            "ValidatedResponsePlan",
            "AgentService",
            "advisor_pipeline",
            "stage_outbound",
            "outbound_dispatcher",
            "enqueue_messages",
            "evaluate_event",
            "queue.outbox",
            "baileys",
        ]
        assert not any(term in source for term in forbidden), source_path


def test_simulator_sources_have_no_tenant_or_vertical_hardcode() -> None:
    for source_path in (SIMULATOR_SOURCE, RUNNER_SOURCE):
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

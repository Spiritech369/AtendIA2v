from __future__ import annotations

import re
from pathlib import Path

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    FinalTurnDecision,
)
from atendia.agent_runtime.respond_style_shadow_runner import (
    CurrentPathShadowOutput,
    RespondStylePathShadowOutput,
    RespondStyleShadowRunner,
    compare_shadow_outputs,
)


@pytest.mark.asyncio
async def test_shadow_runner_executes_both_injected_paths() -> None:
    current = _FakeCurrentPath("I can help. What information do you need?")
    loop = _FakeRespondStyleLoop(
        _respond_decision(
            "For that option, you need ID and proof of address.",
            tool_results=[_tool_result("requirements.lookup")],
        )
    )

    result = await RespondStyleShadowRunner(
        current_path=current,
        respond_style_loop=loop,
    ).run(turn_input=_turn_input("what do I need?"), context=_context())

    assert current.calls == 1
    assert loop.calls == 1
    assert result.current_path.final_message == "I can help. What information do you need?"
    assert result.respond_style_path.final_message == (
        "For that option, you need ID and proof of address."
    )
    assert result.respond_style_path.tool_results[0]["tool_name"] == "requirements.lookup"


@pytest.mark.asyncio
async def test_shadow_runner_forces_no_send() -> None:
    current = _FakeCurrentPath("Current answer.", send_decision="send")
    loop = _FakeRespondStyleLoop(_respond_decision("New answer."))

    result = await RespondStyleShadowRunner(
        current_path=current,
        respond_style_loop=loop,
    ).run(turn_input=_turn_input("hello"), context=_context())

    assert result.final_decision == "no_send"
    assert result.current_path.send_decision == "no_send"
    assert result.respond_style_path.send_decision == "no_send"
    assert result.side_effects == {"delivery": False, "workflows": False, "actions": False}


def test_shadow_comparison_detects_internal_leak() -> None:
    comparison = compare_shadow_outputs(
        inbound_text="status?",
        current=CurrentPathShadowOutput(final_message="The trace says it is ready."),
        respond_style=RespondStylePathShadowOutput(
            final_message="I can check the status without exposing internals.",
            validation_result={"status": "valid"},
            send_decision="no_send",
        ),
    )

    assert comparison.has_internal_leaks is True
    assert "current path has internal language" in comparison.reasons


def test_shadow_comparison_detects_legacy_generic_copy() -> None:
    comparison = compare_shadow_outputs(
        inbound_text="busco info",
        current=CurrentPathShadowOutput(final_message="I am here to help. How can I help you?"),
        respond_style=RespondStylePathShadowOutput(
            final_message="What kind of information should I check first?",
            validation_result={"status": "valid"},
            send_decision="no_send",
        ),
    )

    assert comparison.has_legacy_copy is True
    assert "current path has generic copy" in comparison.reasons


def test_shadow_comparison_prefers_respond_style_with_supported_facts() -> None:
    comparison = compare_shadow_outputs(
        inbound_text="what do I need?",
        current=CurrentPathShadowOutput(final_message="Please provide more information."),
        respond_style=RespondStylePathShadowOutput(
            final_message="For that option, you need ID and proof of address.",
            tool_results=[_tool_result("requirements.lookup")],
            validation_result={"status": "valid"},
            send_decision="no_send",
        ),
    )

    assert comparison.recommendation == "prefer_respond_style"
    assert comparison.uses_supported_facts is True


@pytest.mark.asyncio
async def test_shadow_runner_records_validator_and_tool_results() -> None:
    loop = _FakeRespondStyleLoop(
        _respond_decision(
            "Verified facts are ready.",
            tool_results=[_tool_result("quote.resolve")],
            validation_status="valid",
        )
    )

    result = await RespondStyleShadowRunner(
        current_path=_FakeCurrentPath("Current answer."),
        respond_style_loop=loop,
    ).run(turn_input=_turn_input("how much?"), context=_context())

    assert result.respond_style_path.validation_result["status"] == "valid"
    assert result.respond_style_path.tools == [
        {"tool_name": "quote.resolve", "status": "succeeded"}
    ]
    assert result.respond_style_path.tool_results[0]["facts"] == {"verified": True}


@pytest.mark.asyncio
async def test_shadow_runner_works_when_current_path_unavailable() -> None:
    result = await RespondStyleShadowRunner(
        current_path=None,
        respond_style_loop=_FakeRespondStyleLoop(_respond_decision("Respond-style answer.")),
    ).run(turn_input=_turn_input("hello"), context=_context())

    assert result.current_path.available is False
    assert result.current_path.unavailable_reason == "current_path_adapter_not_configured"
    assert result.comparison.recommendation == "prefer_respond_style"


def test_shadow_runner_source_has_no_unsafe_legacy_or_live_imports() -> None:
    source = Path("core/atendia/agent_runtime/respond_style_shadow_runner.py").read_text(
        encoding="utf-8"
    )
    forbidden = [
        "ConversationRunner",
        "HumanResponseComposer",
        "StructuredRuntimeComposer",
        "SendAdapter",
        "enqueue_messages",
        "evaluate_event",
        "outbox",
    ]
    assert not any(item in source for item in forbidden)


def test_shadow_runner_source_has_no_tenant_or_vertical_hardcodes() -> None:
    source = Path("core/atendia/agent_runtime/respond_style_shadow_runner.py").read_text(
        encoding="utf-8"
    ).casefold()
    forbidden = ["dinamo", "motos", "credito", "crédito", "sat", "metro", "transcript"]
    assert not any(re.search(rf"\b{re.escape(item)}\b", source) for item in forbidden)


def _turn_input(text: str) -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="tenant-1",
        deployment_id="deployment-1",
        agent_id="agent-1",
        agent_version_id="version-1",
        runtime_mode="test_lab_no_send",
        send_mode="no_send",
        channel="test",
        conversation_id="conversation-1",
        contact_id="contact-1",
        inbound_text=text,
    )


def _context() -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={"name": "Generic assistant", "role": "advisor"},
        instructions="Compare paths without sending.",
    )


def _respond_decision(
    final_message: str,
    *,
    tool_results: list[dict] | None = None,
    validation_status: str = "valid",
) -> FinalTurnDecision:
    validation = AgentTurnValidationResult(
        status=validation_status,
        send_decision="no_send",
    )
    return FinalTurnDecision(
        final_message=final_message,
        send_decision="no_send",
        validation=validation,
        trace_metadata={
            "respond_style_tool_loop": {
                "mode": "no_send",
                "tool_rounds": 1 if tool_results else 0,
                "blocked": None,
                "tool_results": tool_results or [],
            }
        },
    )


def _tool_result(tool_name: str) -> dict:
    return {
        "tool_name": tool_name,
        "status": "succeeded",
        "facts": {"verified": True},
        "citations": ["source-1"],
        "source_refs": [tool_name],
        "error_code": None,
        "is_required": True,
        "can_support_claims": True,
    }


class _FakeCurrentPath:
    def __init__(self, final_message: str, *, send_decision: str = "no_send") -> None:
        self.final_message = final_message
        self.send_decision = send_decision
        self.calls = 0

    def run_current_path(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> CurrentPathShadowOutput:
        _ = turn_input
        _ = context
        self.calls += 1
        return CurrentPathShadowOutput(
            available=True,
            final_message=self.final_message,
            validation_result={"status": "valid"},
            send_decision=self.send_decision,
        )


class _FakeRespondStyleLoop:
    def __init__(self, decision: FinalTurnDecision) -> None:
        self.decision = decision
        self.calls = 0

    async def run(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        _ = turn_input
        _ = context
        self.calls += 1
        return self.decision

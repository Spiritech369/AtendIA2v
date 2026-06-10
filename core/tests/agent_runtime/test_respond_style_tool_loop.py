from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    FinalTurnDecision,
    LLMToolCallProposal,
    RespondStyleLLMTurnProvider,
)
from atendia.agent_runtime.respond_style_tool_loop import (
    RespondStyleToolLoop,
    ToolExecutionResult,
)
from atendia.agent_runtime.respond_style_turn_contract import AgentTurnValidationResult


@pytest.mark.asyncio
async def test_loop_executes_tool_proposed_by_llm_and_returns_no_send() -> None:
    tool_call = _tool_call("requirements.lookup")
    provider = _FakeTurnProvider([
        _valid_decision("I will verify the exact requirements.", [tool_call]),
        _valid_decision(
            "You need an ID and proof of address.",
            [],
        ),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="requirements.lookup",
            status="succeeded",
            facts={"requirements": ["ID", "proof of address"]},
            citations=["requirements-source"],
            source_refs=["requirements.lookup"],
            is_required=True,
            can_support_claims=True,
        )
    ])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("what do I need?"),
        context=_context(tool_schemas=[{"name": "requirements.lookup", "enabled": True}]),
    )

    assert decision.send_decision == "no_send"
    assert decision.final_message == "You need an ID and proof of address."
    assert executor.calls[0].tool_name == "requirements.lookup"
    assert provider.contexts[1].tool_results[0]["tool_name"] == "requirements.lookup"
    assert provider.contexts[1].tool_results[0]["facts"] == {
        "requirements": ["ID", "proof of address"]
    }


@pytest.mark.asyncio
async def test_final_message_can_use_facts_from_tool_result() -> None:
    provider = _FakeTurnProvider([
        _valid_decision("I will check the exact quote.", [_tool_call("quote.resolve")]),
        _valid_decision("The verified quote is $120.", []),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="quote.resolve",
            status="succeeded",
            facts={"price": 120, "currency": "USD"},
            citations=["quote-source"],
            source_refs=["quote.resolve"],
            is_required=True,
            can_support_claims=True,
        )
    ])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("how much does it cost?"),
        context=_context(tool_schemas=[{"name": "quote.resolve", "enabled": True}]),
    )

    assert decision.final_message == "The verified quote is $120."
    assert decision.trace_metadata["respond_style_tool_loop"]["tool_rounds"] == 1
    assert decision.trace_metadata["respond_style_tool_loop"]["tool_results"][0]["status"] == (
        "succeeded"
    )


@pytest.mark.asyncio
async def test_price_without_quote_tool_result_stays_no_send_after_provider_retry() -> None:
    provider = RespondStyleLLMTurnProvider(
        client=_FakeOpenAIClient([
            _json_output(final_message="The price is $120."),
            _json_output(final_message="I can verify the exact price first."),
        ])
    )
    executor = _FakeToolExecutor([])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("how much?"),
        context=_context(tool_schemas=[{"name": "quote.resolve", "enabled": True}]),
    )

    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "valid"
    assert "missing_quote_tool" in provider.last_messages[-1]["content"]
    assert executor.calls == []


@pytest.mark.asyncio
async def test_requirements_without_requirements_tool_result_stays_no_send_after_retry() -> None:
    provider = RespondStyleLLMTurnProvider(
        client=_FakeOpenAIClient([
            _json_output(final_message="The requirements are ID and proof of address."),
            _json_output(final_message="I can verify the exact list first."),
        ])
    )
    executor = _FakeToolExecutor([])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("what do I need?"),
        context=_context(tool_schemas=[{"name": "requirements.lookup", "enabled": True}]),
    )

    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "valid"
    assert "missing_requirements_tool" in provider.last_messages[-1]["content"]
    assert executor.calls == []


@pytest.mark.asyncio
async def test_required_tool_failure_blocks_without_second_llm_turn() -> None:
    provider = _FakeTurnProvider([
        _valid_decision("I will verify that.", [_tool_call("requirements.lookup")]),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="requirements.lookup",
            status="failed",
            facts={},
            citations=[],
            source_refs=[],
            error_code="source_unavailable",
            is_required=True,
            can_support_claims=False,
        )
    ])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("what do I need?"),
        context=_context(tool_schemas=[{"name": "requirements.lookup", "enabled": True}]),
    )

    assert decision.send_decision == "no_send"
    assert decision.final_message is None
    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    assert decision.validation.blocked_reason == "required_tool_failed:source_unavailable"
    assert len(provider.contexts) == 1


@pytest.mark.asyncio
async def test_required_unbound_tool_is_skipped_and_blocks() -> None:
    provider = _FakeTurnProvider([
        _valid_decision("I will verify that.", [_tool_call("requirements.lookup")]),
    ])
    executor = _FakeToolExecutor([])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("what do I need?"),
        context=_context(tool_schemas=[]),
    )

    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    assert decision.validation.blocked_reason == "required_tool_skipped:tool_not_bound"
    assert executor.calls == []
    tool_result = decision.trace_metadata["respond_style_tool_loop"]["tool_results"][0]
    assert "final_message" not in tool_result
    assert "customer_copy" not in tool_result


@pytest.mark.asyncio
async def test_required_tool_request_after_tool_round_blocks() -> None:
    provider = _FakeTurnProvider([
        _valid_decision("I will verify that.", [_tool_call("requirements.lookup")]),
        _valid_decision("I need another lookup.", [_tool_call("quote.resolve")]),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="requirements.lookup",
            status="succeeded",
            facts={"requirements": ["ID"]},
            citations=["requirements-source"],
            source_refs=["requirements.lookup"],
            is_required=True,
            can_support_claims=True,
        )
    ])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("what do I need?"),
        context=_context(
            tool_schemas=[
                {"name": "requirements.lookup", "enabled": True},
                {"name": "quote.resolve", "enabled": True},
            ]
        ),
    )

    assert decision.final_message is None
    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    assert decision.validation.blocked_reason == "tool_round_limit_reached"


@pytest.mark.asyncio
async def test_optional_skipped_tool_does_not_create_customer_copy() -> None:
    provider = _FakeTurnProvider([
        _valid_decision(
            "I can continue without that optional lookup.",
            [_tool_call("optional.lookup", required=False)],
        ),
        _valid_decision("What detail should I check next?", []),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="optional.lookup",
            status="skipped",
            facts={},
            citations=[],
            source_refs=[],
            error_code="dry_run_skipped",
            is_required=False,
            can_support_claims=False,
        )
    ])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("can you compare options?"),
        context=_context(tool_schemas=[{"name": "optional.lookup", "enabled": True}]),
    )

    assert decision.final_message == "What detail should I check next?"
    tool_result = provider.contexts[1].tool_results[0]
    assert "final_message" not in tool_result
    assert "customer_copy" not in tool_result
    assert executor.side_effects == {"delivery": False, "workflows": False, "actions": False}


@pytest.mark.asyncio
async def test_generic_requirements_question_with_complete_preconditions_executes_tool() -> None:
    provider = _FakeTurnProvider([
        _valid_decision(
            "I will verify the exact requirements.",
            [_tool_call("requirements.lookup")],
        ),
        _valid_decision("For that option, the required documents are ID and proof of address.", []),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="requirements.lookup",
            status="succeeded",
            facts={"documents": ["ID", "proof of address"]},
            citations=["requirements-source"],
            source_refs=["requirements.lookup"],
            is_required=True,
            can_support_claims=True,
        )
    ])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("que ocupo"),
        context=_context(
            contact_snapshot={"selected_option": "standard"},
            tool_schemas=[
                {
                    "name": "requirements.lookup",
                    "enabled": True,
                    "capability": "resolve exact requirements when selected_option exists",
                    "preconditions": ["selected_option"],
                }
            ],
        ),
    )

    assert executor.calls[0].tool_name == "requirements.lookup"
    assert decision.final_message is not None
    assert "required documents" in decision.final_message


@pytest.mark.asyncio
async def test_generic_requirements_question_without_preconditions_asks_missing_detail() -> None:
    provider = _FakeTurnProvider([
        _valid_decision("Which option should I check requirements for?", []),
    ])
    executor = _FakeToolExecutor([])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("que ocupo"),
        context=_context(
            tool_schemas=[
                {
                    "name": "requirements.lookup",
                    "enabled": True,
                    "capability": "resolve exact requirements when selected_option exists",
                    "preconditions": ["selected_option"],
                }
            ],
        ),
    )

    assert decision.final_message == "Which option should I check requirements for?"
    assert "ID" not in decision.final_message
    assert "proof of address" not in decision.final_message
    assert executor.calls == []


@pytest.mark.asyncio
async def test_generic_price_question_with_complete_preconditions_executes_quote_tool() -> None:
    provider = _FakeTurnProvider([
        _valid_decision("I will verify the exact price.", [_tool_call("quote.resolve")]),
        _valid_decision("The verified price is $120.", []),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="quote.resolve",
            status="succeeded",
            facts={"price": 120, "currency": "USD"},
            citations=["quote-source"],
            source_refs=["quote.resolve"],
            is_required=True,
            can_support_claims=True,
        )
    ])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("cuanto cuesta"),
        context=_context(
            contact_snapshot={"selected_option": "standard"},
            tool_schemas=[
                {
                    "name": "quote.resolve",
                    "enabled": True,
                    "capability": "resolve exact quote when selected_option exists",
                    "preconditions": ["selected_option"],
                }
            ],
        ),
    )

    assert executor.calls[0].tool_name == "quote.resolve"
    assert decision.final_message == "The verified price is $120."


@pytest.mark.asyncio
async def test_generic_price_question_without_preconditions_does_not_invent_price() -> None:
    provider = _FakeTurnProvider([
        _valid_decision("Which option should I quote for you?", []),
    ])
    executor = _FakeToolExecutor([])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("cuanto cuesta"),
        context=_context(tool_schemas=[{"name": "quote.resolve", "enabled": True}]),
    )

    assert decision.final_message == "Which option should I quote for you?"
    assert "$" not in decision.final_message
    assert executor.calls == []


def test_tool_execution_result_is_fact_only_and_forbids_customer_copy() -> None:
    with pytest.raises(ValueError):
        ToolExecutionResult.model_validate(
            {
                "tool_name": "requirements.lookup",
                "status": "succeeded",
                "facts": {},
                "citations": [],
                "source_refs": [],
                "is_required": True,
                "can_support_claims": True,
                "customer_copy": "Never send this.",
            }
        )


def test_tool_loop_source_has_no_unsafe_legacy_or_live_imports() -> None:
    source = Path("core/atendia/agent_runtime/respond_style_tool_loop.py").read_text(
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


def test_tool_loop_source_has_no_tenant_or_vertical_hardcode() -> None:
    source = Path("core/atendia/agent_runtime/respond_style_tool_loop.py").read_text(
        encoding="utf-8"
    ).casefold()
    forbidden_terms = ["dinamo", "motos", "credito", "crédito", "sat", "metro"]
    assert not any(
        re.search(rf"\b{re.escape(term.casefold())}\b", source)
        for term in forbidden_terms
    )


def test_tool_loop_source_does_not_route_by_customer_phrases() -> None:
    source = Path("core/atendia/agent_runtime/respond_style_tool_loop.py").read_text(
        encoding="utf-8"
    ).casefold()
    assert "que ocupo" not in source
    assert "cuanto cuesta" not in source
    assert "requirements.lookup" not in source
    assert "quote.resolve" not in source


def _turn_input(
    inbound_text: str,
    *,
    contact_snapshot: dict | None = None,
) -> AgentTurnInput:
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
        inbound_text=inbound_text,
        contact_snapshot=contact_snapshot or {},
    )


def _context(
    *,
    contact_snapshot: dict | None = None,
    tool_schemas: list[dict] | None = None,
) -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={
            "name": "Generic assistant",
            "role": "advisor",
            "contact_state": contact_snapshot or {},
        },
        instructions="Use tools for exact facts and never invent unsupported facts.",
        voice_guide={"tone": "brief, natural"},
        tool_schemas=tool_schemas or [],
        field_policies=[],
        action_schemas=[],
        workflow_trigger_schemas=[],
        handoff_policy={"enabled": True, "targets": ["support"]},
    ).model_copy(update={"agent_identity": {"contact_snapshot": contact_snapshot or {}}})


def _tool_call(tool_name: str, *, required: bool = True) -> LLMToolCallProposal:
    return LLMToolCallProposal(
        tool_name=tool_name,
        arguments={"values": [], "summary": None},
        reason="Exact facts require a tool.",
        required=required,
    )


def _valid_decision(
    final_message: str,
    tool_requests: list[LLMToolCallProposal],
) -> FinalTurnDecision:
    validation = AgentTurnValidationResult(
        status="valid",
        accepted_tool_requests=tool_requests,
        send_decision="no_send",
    )
    return FinalTurnDecision(
        final_message=final_message,
        send_decision="no_send",
        validation=validation,
    )


def _json_output(**overrides) -> str:
    payload = {
        "final_message": "Hello, I can help with that.",
        "tool_requests": [],
        "field_write_proposals": [],
        "action_proposals": [],
        "workflow_event_proposals": [],
        "handoff_proposal": None,
        "claims": [],
        "confidence": 0.8,
        "needs_retry_reason": None,
    }
    payload.update(overrides)
    return json.dumps(payload)


class _FakeTurnProvider:
    def __init__(self, outputs: list[FinalTurnDecision]) -> None:
        self._outputs = list(outputs)
        self.contexts: list[AgentContextPackage] = []

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        _ = turn_input
        self.contexts.append(context)
        return self._outputs.pop(0)


class _FakeToolExecutor:
    def __init__(self, results: list[ToolExecutionResult]) -> None:
        self._results = list(results)
        self.calls: list[LLMToolCallProposal] = []
        self.side_effects = {"delivery": False, "workflows": False, "actions": False}

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        _ = context
        self.calls.append(tool_call)
        return self._results.pop(0)


class _FakeOpenAIClient:
    def __init__(self, outputs: list[str]) -> None:
        from types import SimpleNamespace

        self.chat = SimpleNamespace(completions=_FakeCompletions(outputs))


class _FakeCompletions:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        from types import SimpleNamespace

        self.calls.append(kwargs)
        output = self._outputs.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=output))]
        )


@pytest.mark.asyncio
async def test_tool_request_turn_without_message_flows_to_final_response() -> None:
    """Amended contract: turn 1 may be tool-only (no customer copy at all)."""
    tool_call = _tool_call("requirements.lookup")
    tool_only = FinalTurnDecision(
        final_message=None,
        send_decision="no_send",
        validation=AgentTurnValidationResult(
            status="valid",
            accepted_tool_requests=[tool_call],
            send_decision="no_send",
        ),
    )
    provider = _FakeTurnProvider([
        tool_only,
        _valid_decision("You need an ID and proof of address.", []),
    ])
    executor = _FakeToolExecutor([
        ToolExecutionResult(
            tool_name="requirements.lookup",
            status="succeeded",
            facts={"requirements": ["ID", "proof of address"]},
            citations=["requirements-source"],
            source_refs=["requirements.lookup"],
            is_required=True,
            can_support_claims=True,
        )
    ])

    decision = await RespondStyleToolLoop(provider=provider, executor=executor).run(
        turn_input=_turn_input("what do I need?"),
        context=_context(tool_schemas=[{"name": "requirements.lookup", "enabled": True}]),
    )

    assert decision.send_decision == "no_send"
    assert decision.final_message == "You need an ID and proof of address."
    assert executor.calls[0].tool_name == "requirements.lookup"

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    DeploymentResolution,
    DeploymentView,
    DryFactsToolExecutor,
    FinalTurnDecision,
    LLMFieldUpdateProposal,
    LLMToolCallProposal,
    RespondStyleDeploymentResolver,
    RespondStyleToolLoop,
)
from atendia.agent_runtime.respond_style_tool_loop import (
    RespondStyleToolLoopConfig,
    ToolExecutionResult,
)

RESOLVER_SOURCE = Path(
    "core/atendia/agent_runtime/respond_style_deployment_resolver.py"
)
EXECUTOR_SOURCE = Path(
    "core/atendia/agent_runtime/respond_style_dry_facts_executor.py"
)
ADAPTER_SOURCE = Path("core/atendia/product_agents/test_lab_direct_adapter.py")


class _FakeTurnProvider:
    def __init__(self, decisions: list[FinalTurnDecision]) -> None:
        self._decisions = list(decisions)
        self.contexts: list[AgentContextPackage] = []

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        self.contexts.append(context)
        return self._decisions.pop(0)


class _SequencedExecutor:
    def __init__(self, results: dict[str, ToolExecutionResult]) -> None:
        self._results = results
        self.calls: list[str] = []

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        self.calls.append(tool_call.tool_name)
        return self._results[tool_call.tool_name]


def _ok_result(tool_name: str, facts: dict) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=tool_name,
        status="succeeded",
        facts=facts,
        source_refs=[tool_name],
    )


def _decision(
    final_message: str | None,
    *,
    tool_requests: list[LLMToolCallProposal] | None = None,
    field_writes: list[LLMFieldUpdateProposal] | None = None,
) -> FinalTurnDecision:
    validation = AgentTurnValidationResult(
        status="valid",
        accepted_tool_requests=tool_requests or [],
        accepted_field_writes=field_writes or [],
        send_decision="no_send",
    )
    return FinalTurnDecision(
        final_message=final_message,
        send_decision="no_send",
        validation=validation,
        accepted_field_writes=field_writes or [],
    )


def _turn_input() -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="generic-tenant",
        deployment_id="d1",
        agent_id="generic-agent",
        agent_version_id="v1",
        runtime_mode="test_lab_no_send",
        send_mode="no_send",
        channel="test",
        conversation_id="conv-1",
        inbound_text="compound ask",
    )


def _context() -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={"contact_state": {}},
        tool_schemas=[
            {"tool_name": "requirements.lookup", "enabled": True},
            {"tool_name": "quote.resolve", "enabled": True},
        ],
    )


# --- 11A: multi-round tool loop with budgets ------------------------------


@pytest.mark.asyncio
async def test_multiround_loop_resolves_sequential_tools() -> None:
    req_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="needed")
    quote_call = LLMToolCallProposal(tool_name="quote.resolve", reason="needed")
    provider = _FakeTurnProvider([
        _decision(None, tool_requests=[req_call]),
        _decision(None, tool_requests=[quote_call]),
        _decision("Both facts resolved: requirements and quote."),
    ])
    executor = _SequencedExecutor({
        "requirements.lookup": _ok_result("requirements.lookup", {"requirements": ["ID"]}),
        "quote.resolve": _ok_result("quote.resolve", {"price": 120}),
    })

    decision = await RespondStyleToolLoop(
        provider=provider,
        executor=executor,
        config=RespondStyleToolLoopConfig(max_tool_rounds=3),
    ).run(turn_input=_turn_input(), context=_context())

    assert decision.final_message == "Both facts resolved: requirements and quote."
    assert executor.calls == ["requirements.lookup", "quote.resolve"]
    loop_trace = decision.trace_metadata["respond_style_tool_loop"]
    assert loop_trace["tool_rounds"] == 2
    assert len(loop_trace["tool_results"]) == 2
    # Round 2 saw round 1's tool result in context.
    round_two_context = provider.contexts[1]
    assert round_two_context.tool_results[0]["tool_name"] == "requirements.lookup"


@pytest.mark.asyncio
async def test_round_limit_still_blocks_at_configured_limit() -> None:
    req_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="needed")
    quote_call = LLMToolCallProposal(tool_name="quote.resolve", reason="needed")
    provider = _FakeTurnProvider([
        _decision(None, tool_requests=[req_call]),
        _decision(None, tool_requests=[quote_call]),
    ])
    executor = _SequencedExecutor({
        "requirements.lookup": _ok_result("requirements.lookup", {"requirements": ["ID"]}),
    })

    decision = await RespondStyleToolLoop(
        provider=provider,
        executor=executor,
        config=RespondStyleToolLoopConfig(max_tool_rounds=1),
    ).run(turn_input=_turn_input(), context=_context())

    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.blocked_reason == "tool_round_limit_reached"


@pytest.mark.asyncio
async def test_tool_call_budget_blocks_closed() -> None:
    calls = [
        LLMToolCallProposal(tool_name="requirements.lookup", reason="needed"),
        LLMToolCallProposal(tool_name="quote.resolve", reason="needed"),
    ]
    provider = _FakeTurnProvider([_decision(None, tool_requests=calls)])
    executor = _SequencedExecutor({})

    decision = await RespondStyleToolLoop(
        provider=provider,
        executor=executor,
        config=RespondStyleToolLoopConfig(max_tool_rounds=3, max_total_tool_calls=1),
    ).run(turn_input=_turn_input(), context=_context())

    assert decision.validation is not None
    assert decision.validation.blocked_reason == "tool_call_budget_exceeded"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_time_budget_blocks_closed() -> None:
    req_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="needed")
    provider = _FakeTurnProvider([_decision(None, tool_requests=[req_call])])
    executor = _SequencedExecutor({})

    decision = await RespondStyleToolLoop(
        provider=provider,
        executor=executor,
        config=RespondStyleToolLoopConfig(max_tool_rounds=3, max_elapsed_seconds=-1.0),
    ).run(turn_input=_turn_input(), context=_context())

    assert decision.validation is not None
    assert decision.validation.blocked_reason == "tool_time_budget_exceeded"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_provisional_fields_accumulate_across_rounds() -> None:
    req_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="needed")
    quote_call = LLMToolCallProposal(tool_name="quote.resolve", reason="needed")
    first_field = LLMFieldUpdateProposal(
        field_key="selected_option",
        value="standard",
        evidence=["quote from customer"],
        confidence=0.9,
        reason="stated",
    )
    second_field = LLMFieldUpdateProposal(
        field_key="work_type",
        value="self_employed",
        evidence=["quote from customer"],
        confidence=0.9,
        reason="stated",
    )
    provider = _FakeTurnProvider([
        _decision(None, tool_requests=[req_call], field_writes=[first_field]),
        _decision(None, tool_requests=[quote_call], field_writes=[second_field]),
        _decision("done"),
    ])
    executor = _SequencedExecutor({
        "requirements.lookup": _ok_result("requirements.lookup", {"r": 1}),
        "quote.resolve": _ok_result("quote.resolve", {"q": 1}),
    })

    decision = await RespondStyleToolLoop(
        provider=provider,
        executor=executor,
        config=RespondStyleToolLoopConfig(max_tool_rounds=3),
    ).run(turn_input=_turn_input(), context=_context())

    keys = sorted(item.field_key for item in decision.accepted_field_writes)
    assert keys == ["selected_option", "work_type"]
    final_round_state = provider.contexts[2].agent_identity["contact_state"]
    assert final_round_state == {
        "selected_option": "standard",
        "work_type": "self_employed",
    }


# --- DryFactsToolExecutor -------------------------------------------------


def _dry_executor() -> DryFactsToolExecutor:
    return DryFactsToolExecutor([
        {
            "name": "requirements.lookup",
            "preconditions": ["selected_option"],
            "dry_facts": {"requirements": ["ID", "proof of address"]},
        },
        {"name": "catalog.search", "dry_facts": {"options": ["a", "b"]}},
    ])


def test_dry_executor_succeeds_with_contact_state_precondition() -> None:
    result = _dry_executor().execute_tool(
        LLMToolCallProposal(tool_name="requirements.lookup", reason="asked"),
        AgentContextPackage(
            agent_identity={"contact_state": {"selected_option": "standard"}}
        ),
    )
    assert result.status == "succeeded"
    assert result.facts["requirements"] == ["ID", "proof of address"]
    assert result.facts["selected_option"] == "standard"


def test_dry_executor_reads_precondition_from_tool_arguments() -> None:
    result = _dry_executor().execute_tool(
        LLMToolCallProposal(
            tool_name="requirements.lookup",
            reason="asked",
            arguments={
                "values": [
                    {
                        "key": "selected_option",
                        "string_value": "standard",
                        "number_value": None,
                        "boolean_value": None,
                    }
                ]
            },
        ),
        AgentContextPackage(agent_identity={"contact_state": {}}),
    )
    assert result.status == "succeeded"


def test_dry_executor_skips_on_missing_precondition_and_unknown_tool() -> None:
    executor = _dry_executor()
    missing = executor.execute_tool(
        LLMToolCallProposal(tool_name="requirements.lookup", reason="asked"),
        AgentContextPackage(agent_identity={"contact_state": {}}),
    )
    assert missing.status == "skipped"
    assert missing.error_code == "missing_precondition:selected_option"

    unknown = executor.execute_tool(
        LLMToolCallProposal(tool_name="nope.tool", reason="asked"),
        AgentContextPackage(),
    )
    assert unknown.status == "skipped"
    assert unknown.error_code == "tool_not_available"


# --- 11B: Test Lab DB adapter ---------------------------------------------


@pytest.mark.asyncio
async def test_run_direct_test_suite_stores_evidence_row(monkeypatch) -> None:
    from atendia.product_agents import service, test_lab_direct_adapter

    tenant_id = uuid4()
    version_id = uuid4()
    suite_id = uuid4()
    agent_id = uuid4()
    suite = SimpleNamespace(id=suite_id, agent_version_id=version_id)
    version = SimpleNamespace(
        id=version_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        status="published",
        role="advisor",
        tone="warm",
        language="es",
        instructions="Use capabilities only.",
        knowledge_policy={},
        tool_policy={
            "bindings": [
                {
                    "name": "requirements.lookup",
                    "description": "Returns factual requirements.",
                    "preconditions": ["selected_option"],
                    "dry_facts": {"requirements": ["ID"]},
                }
            ]
        },
        action_policy={},
        workflow_policy={},
        field_policy={"fields": [{"field_key": "selected_option"}]},
        safety_policy={},
    )
    scenario = SimpleNamespace(
        name="greeting",
        turns=[{"inbound_text": "hola"}],
        expected={},
    )

    async def fake_get_suite(session, *, tenant_id, suite_id):
        return suite

    async def fake_list_scenarios(session, *, tenant_id, suite_id):
        return [scenario]

    monkeypatch.setattr(service, "get_agent_test_suite_for_tenant", fake_get_suite)
    monkeypatch.setattr(service, "list_agent_test_scenarios", fake_list_scenarios)

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list = []

        async def get(self, model, key):
            assert key == version_id
            return version

        def add(self, obj) -> None:
            self.added.append(obj)

        async def flush(self) -> None:
            return None

    decisions = [_decision("Hola, te ayudo con gusto.")]
    providers = {"created": 0}

    def tool_loop_factory(config):
        providers["created"] += 1
        assert config.agent_version_id == str(version_id)
        return RespondStyleToolLoop(
            provider=_FakeTurnProvider(list(decisions)),
            executor=DryFactsToolExecutor(config.tool_bindings),
        )

    session = _FakeSession()
    run = await test_lab_direct_adapter.run_direct_test_suite(
        session,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        suite_id=suite_id,
        created_by_user_id=None,
        tool_loop_factory=tool_loop_factory,
    )

    assert session.added == [run]
    assert run.mode == "no_send"
    assert run.status == "passed"
    assert run.decision == test_lab_direct_adapter.DIRECT_DECISION_READY
    assert run.pass_count == 1
    assert run.blocked_count == 0
    assert run.coverage_summary["execution_mode"] == (
        "respond_style_product_agent_direct"
    )
    assert run.coverage_summary["outbound_outbox_writes"] == 0
    assert run.outbox_audit_result == {
        "status": "clean",
        "outbound_outbox_writes": 0,
    }
    turn = run.turn_results[0]
    assert turn["send_decision"] == "no_send"
    assert turn["final_message"] == "Hola, te ayudo con gusto."


def test_adapter_source_has_no_legacy_imports() -> None:
    source = ADAPTER_SOURCE.read_text(encoding="utf-8")
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
        "baileys",
    ]
    assert not any(term in source for term in forbidden)


# --- 11C: deployment resolver ----------------------------------------------


def _deployment(**overrides) -> DeploymentView:
    base = {
        "tenant_id": "generic-tenant",
        "deployment_id": "dep-1",
        "agent_id": "agent-1",
        "active_version_id": "v1",
        "publish_state": "published",
        "respond_style_enabled": True,
    }
    base.update(overrides)
    return DeploymentView(**base)


def test_resolver_previews_direct_route_for_published_agent() -> None:
    resolution = RespondStyleDeploymentResolver().resolve(_deployment())

    assert resolution.route_preview == "product_agent_direct"
    assert resolution.no_send_only is True
    assert resolution.send_decision == "no_send"
    assert resolution.live_routing_active is False
    assert "phase_11_is_no_send_only" in resolution.live_blocked_reasons


def test_resolver_falls_back_to_legacy_when_requirements_missing() -> None:
    unpublished = RespondStyleDeploymentResolver().resolve(
        _deployment(publish_state="draft")
    )
    assert unpublished.route_preview == "legacy_runner"
    assert "publish_state_not_published" in unpublished.reason

    disabled = RespondStyleDeploymentResolver().resolve(
        _deployment(respond_style_enabled=False)
    )
    assert "respond_style_not_enabled" in disabled.reason

    no_version = RespondStyleDeploymentResolver().resolve(
        _deployment(active_version_id=None)
    )
    assert "no_active_version" in no_version.reason


def test_resolver_stays_no_send_even_with_live_flags_on() -> None:
    resolution = RespondStyleDeploymentResolver().resolve(
        _deployment(send_enabled=True, outbox_enabled=True, live_send_enabled=True)
    )
    assert resolution.no_send_only is True
    assert resolution.live_routing_active is False
    assert resolution.send_decision == "no_send"
    assert "phase_11_is_no_send_only" in resolution.live_blocked_reasons


def test_resolution_model_refuses_live_routing() -> None:
    with pytest.raises(ValidationError):
        DeploymentResolution(
            route_preview="product_agent_direct",
            reason="x",
            live_routing_active=True,
            deployment_id="d",
            agent_id="a",
        )
    with pytest.raises(ValidationError):
        DeploymentResolution(
            route_preview="product_agent_direct",
            reason="x",
            send_decision="send",
            deployment_id="d",
            agent_id="a",
        )


def test_new_sources_have_no_legacy_imports_or_hardcodes() -> None:
    for source_path in (RESOLVER_SOURCE, EXECUTOR_SOURCE):
        source = source_path.read_text(encoding="utf-8")
        forbidden = [
            "ConversationRunner",
            "HumanResponseComposer",
            "StructuredRuntimeComposer",
            "ValidatedResponsePlan",
            "AgentService",
            "stage_outbound",
            "outbound_dispatcher",
            "enqueue_messages",
            "evaluate_event",
            "baileys",
        ]
        assert not any(term in source for term in forbidden), source_path
        lowered = source.casefold()
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


@pytest.mark.asyncio
async def test_re_requested_succeeded_tool_is_not_re_executed_and_nudges_final() -> None:
    req_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="needed")
    provider = _FakeTurnProvider([
        _decision(None, tool_requests=[req_call]),
        # Model wrongly re-requests the same succeeded tool...
        _decision(None, tool_requests=[req_call]),
        # ...the loop nudges with feedback and the model produces the answer.
        _decision("Answer written from the existing tool results."),
    ])
    executor = _SequencedExecutor({
        "requirements.lookup": _ok_result("requirements.lookup", {"r": 1}),
    })

    decision = await RespondStyleToolLoop(
        provider=provider,
        executor=executor,
        config=RespondStyleToolLoopConfig(max_tool_rounds=3),
    ).run(turn_input=_turn_input(), context=_context())

    assert executor.calls == ["requirements.lookup"]  # executed exactly once
    assert decision.final_message == "Answer written from the existing tool results."
    # The nudge carried structured feedback to the model.
    nudge_context = provider.contexts[2]
    assert any(
        "already have succeeded tool_results" in str(item)
        for item in nudge_context.validator_feedback
    )


@pytest.mark.asyncio
async def test_duplicate_tools_within_one_round_execute_once() -> None:
    req_call = LLMToolCallProposal(tool_name="requirements.lookup", reason="needed")
    provider = _FakeTurnProvider([
        _decision(None, tool_requests=[req_call, req_call]),
        _decision("done"),
    ])
    executor = _SequencedExecutor({
        "requirements.lookup": _ok_result("requirements.lookup", {"r": 1}),
    })

    decision = await RespondStyleToolLoop(
        provider=provider,
        executor=executor,
        config=RespondStyleToolLoopConfig(max_tool_rounds=2),
    ).run(turn_input=_turn_input(), context=_context())

    assert executor.calls == ["requirements.lookup"]
    assert decision.final_message == "done"

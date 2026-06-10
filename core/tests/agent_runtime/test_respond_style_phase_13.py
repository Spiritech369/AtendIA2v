from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMFieldUpdateProposal,
    ProductAgentPublishedConfig,
    RespondStyleToolLoop,
    run_parity_gate,
)


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


def _valid_decision(final_message: str, **overrides) -> FinalTurnDecision:
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
        publish_state="published",
        agent_name="Generic Assistant",
        instructions="Use configured capabilities only.",
        field_definitions=[{"field_key": "selected_option", "required": True}],
    )


# --- 13A: Publish Control gates -------------------------------------------


def _deployment(metadata: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        metadata_json=metadata or {},
    )


class _RunQuerySession:
    def __init__(self, runs: list[SimpleNamespace]) -> None:
        self._runs = runs

    async def execute(self, query):
        runs = self._runs

        class _Result:
            def scalars(self):
                return runs

        return _Result()


@pytest.mark.asyncio
async def test_gates_skip_deployments_without_opt_in(monkeypatch) -> None:
    from atendia.product_agents import publish_gates

    blockers = await publish_gates.respond_style_publish_blockers(
        _RunQuerySession([]),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        version_id=uuid4(),
        deployment=_deployment({}),
    )
    assert blockers == []


@pytest.mark.asyncio
async def test_gates_block_when_direct_test_lab_missing(monkeypatch) -> None:
    from atendia.product_agents import publish_gates

    monkeypatch.setattr(publish_gates, "audit_direct_route_imports", lambda: [])
    blockers = await publish_gates.respond_style_publish_blockers(
        _RunQuerySession([]),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        version_id=uuid4(),
        deployment=_deployment({"respond_style_enabled": True}),
    )
    assert [item["code"] for item in blockers] == [
        "respond_style_test_lab_direct_missing"
    ]


@pytest.mark.asyncio
async def test_gates_block_on_failed_battery_or_failed_run(monkeypatch) -> None:
    from atendia.product_agents import publish_gates

    monkeypatch.setattr(
        publish_gates,
        "audit_direct_route_imports",
        lambda: ["atendia.runner.conversation_runner"],
    )
    failed_run = SimpleNamespace(
        decision="RESPOND_STYLE_DIRECT_NO_SEND_BLOCKED",
        status="blocked",
        coverage_summary={"execution_mode": "respond_style_product_agent_direct"},
    )
    blockers = await publish_gates.respond_style_publish_blockers(
        _RunQuerySession([failed_run]),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        version_id=uuid4(),
        deployment=_deployment({"respond_style_enabled": True}),
    )
    codes = [item["code"] for item in blockers]
    assert "respond_style_hard_block_battery_failed" in codes
    assert "respond_style_test_lab_direct_not_passed" in codes


@pytest.mark.asyncio
async def test_gates_pass_with_clean_audit_and_ready_run(monkeypatch) -> None:
    from atendia.product_agents import publish_gates

    monkeypatch.setattr(publish_gates, "audit_direct_route_imports", lambda: [])
    ready_run = SimpleNamespace(
        decision="RESPOND_STYLE_DIRECT_NO_SEND_READY",
        status="passed",
        coverage_summary={"execution_mode": "respond_style_product_agent_direct"},
    )
    legacy_run = SimpleNamespace(
        decision="TEST_LAB_PASSED",
        status="passed",
        coverage_summary={"execution_mode": "simulated_contract"},
    )
    blockers = await publish_gates.respond_style_publish_blockers(
        _RunQuerySession([legacy_run, ready_run]),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        version_id=uuid4(),
        deployment=_deployment({"respond_style_enabled": True}),
    )
    assert blockers == []


def test_gates_are_wired_into_publish_request_evaluation() -> None:
    from pathlib import Path

    source = Path("core/atendia/product_agents/service.py").read_text(encoding="utf-8")
    assert "respond_style_publish_blockers" in source


# --- 13B: inbound shadow ---------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_shadow_skips_without_api_key(monkeypatch) -> None:
    from atendia.product_agents import inbound_shadow

    monkeypatch.setattr(
        inbound_shadow,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=""),
    )
    summaries = await inbound_shadow.run_inbound_shadow(
        _RunQuerySession([]),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        conversation_id="conv-1",
        inbound_text="hola",
    )
    assert summaries == []


@pytest.mark.asyncio
async def test_inbound_shadow_safe_wrapper_swallows_failures(monkeypatch) -> None:
    from atendia.product_agents import inbound_shadow

    async def boom(*args, **kwargs):
        raise RuntimeError("shadow exploded")

    monkeypatch.setattr(inbound_shadow, "run_inbound_shadow", boom)
    # Must not raise — the inbound pipeline depends on this.
    await inbound_shadow.run_inbound_shadow_safely(
        _RunQuerySession([]),  # type: ignore[arg-type]
        tenant_id=uuid4(),
        conversation_id="conv-1",
        inbound_text="hola",
    )


def test_inbound_shadow_is_wired_and_observation_only() -> None:
    from pathlib import Path

    inbound_source = Path("core/atendia/api/baileys_routes.py").read_text(
        encoding="utf-8"
    )
    assert "run_inbound_shadow_safely" in inbound_source

    shadow_source = Path("core/atendia/product_agents/inbound_shadow.py").read_text(
        encoding="utf-8"
    )
    forbidden = [
        "ConversationRunner",
        "stage_outbound",
        "enqueue_messages",
        "evaluate_event",
        "send_text",
        "HumanResponseComposer",
        "StructuredRuntimeComposer",
    ]
    assert not any(term in shadow_source for term in forbidden)


# --- 13D: parity gate -------------------------------------------------------


def _scripted_factory(messages: list[str]):
    def factory() -> RespondStyleToolLoop:
        decisions = [
            _valid_decision(
                message,
                accepted_field_writes=[
                    LLMFieldUpdateProposal(
                        field_key="selected_option",
                        value="standard",
                        evidence=["customer message"],
                        confidence=0.9,
                        reason="stated",
                    )
                ]
                if index == 0
                else [],
            )
            for index, message in enumerate(messages)
        ]
        return RespondStyleToolLoop(
            provider=_ScriptedProvider(decisions),
            executor=_NoToolExecutor(),
        )

    return factory


@pytest.mark.asyncio
async def test_parity_gate_passes_for_identical_runs_with_full_audit() -> None:
    result = await run_parity_gate(
        config=_config(),
        turns=["hola", "quiero la opcion estandar"],
        tool_loop_factory=_scripted_factory(["hola, te ayudo", "anotado, seguimos"]),
        audit_imports=True,
    )

    assert result.parity_ok is True
    assert result.turns_compared == 2
    assert result.differences == []
    assert result.both_paths_no_send is True
    assert result.legacy_path_used is False
    assert result.legacy_import_violations == []
    assert result.no_send_policy_labels == ["no_send", "no_send"]
    assert result.live_candidate_policy_labels == [
        "live_candidate_simulated",
        "live_candidate_simulated",
    ]


@pytest.mark.asyncio
async def test_parity_gate_detects_divergence() -> None:
    calls = {"count": 0}

    def diverging_factory() -> RespondStyleToolLoop:
        calls["count"] += 1
        message = "respuesta A" if calls["count"] == 1 else "respuesta B"
        return RespondStyleToolLoop(
            provider=_ScriptedProvider([_valid_decision(message)]),
            executor=_NoToolExecutor(),
        )

    result = await run_parity_gate(
        config=_config(),
        turns=["hola"],
        tool_loop_factory=diverging_factory,
        audit_imports=False,
    )

    assert result.parity_ok is False
    assert result.differences[0].field == "final_message_candidate"
    assert result.differences[0].no_send_value == "respuesta A"
    assert result.differences[0].live_candidate_value == "respuesta B"

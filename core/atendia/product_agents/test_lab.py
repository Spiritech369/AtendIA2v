from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.agent_service import AgentService, AgentServiceResult
from atendia.agent_runtime.model_provider import (
    MockAgentProvider,
    SafeFallbackAgentProvider,
    build_agent_turn_provider,
)
from atendia.db.models.product_agent import AgentTestRun
from atendia.product_agents import service
from atendia.product_agents.runtime_adapter import (
    RUNTIME_CONTRACT_MISSING,
    ProductAgentRuntimeAdapter,
)

TEST_LAB_PASSED = "TEST_LAB_PASSED"
TEST_LAB_FAILED = "TEST_LAB_FAILED"
TEST_LAB_BLOCKED_BY_TOOL = "TEST_LAB_BLOCKED_BY_TOOL"
TEST_LAB_BLOCKED_BY_POLICY = "TEST_LAB_BLOCKED_BY_POLICY"
TEST_LAB_BLOCKED_BY_TRACE = "TEST_LAB_BLOCKED_BY_TRACE"
REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API = "REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API"
REAL_AGENT_TEST_LAB_BLOCKED_BY_LIMITS = "REAL_AGENT_TEST_LAB_BLOCKED_BY_LIMITS"
REAL_AGENT_TEST_LAB_BLOCKED_BY_RUNTIME_CONTRACT = (
    "REAL_AGENT_TEST_LAB_BLOCKED_BY_RUNTIME_CONTRACT"
)

SIMULATED_CONTRACT_MODE = "simulated_contract"
OPENAI_DIRECT_PROVIDER_MODE = "openai_direct_provider"
RUNTIME_V2_AGENT_SERVICE_MODE = "runtime_v2_agent_service"
MODEL_BACKED_EXECUTION_MODES = {OPENAI_DIRECT_PROVIDER_MODE, RUNTIME_V2_AGENT_SERVICE_MODE}
REAL_TEST_LAB_MAX_SCENARIOS = 2
REAL_TEST_LAB_MAX_TURNS_PER_SCENARIO = 6
REAL_TEST_LAB_MAX_INCIDENT_REPLAY_TURNS = 24
REAL_TEST_LAB_MAX_OUTPUT_TOKENS = 350
REAL_TEST_LAB_TEMPERATURE = 0.2

INTERNAL_VISIBLE_TEXT_MARKERS = (
    "/goal",
    "reviso el contexto",
    "te doy continuidad",
    "tomo tu mensaje",
    "siguiente paso con el contexto actual",
    "internal",
    "traceback",
)


class AgentServiceLike(Protocol):
    async def handle_turn(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        inbound_text: str,
        turn_number: int,
        mode: str,
        metadata: dict[str, Any] | None = None,
        to_phone_e164: str | None = None,
    ) -> AgentServiceResult: ...


AgentServiceFactory = Callable[[AsyncSession], AgentServiceLike]


def _validate_execution_mode(*, mode: str, execution_mode: str) -> None:
    if execution_mode not in {
        SIMULATED_CONTRACT_MODE,
        OPENAI_DIRECT_PROVIDER_MODE,
        RUNTIME_V2_AGENT_SERVICE_MODE,
    }:
        raise service.ProductAgentError("test lab execution_mode is not supported")
    if execution_mode in MODEL_BACKED_EXECUTION_MODES and mode != "no_send":
        raise service.ProductAgentError(f"{execution_mode} Test Lab requires mode=no_send")


def _coverage_summary(*, execution_mode: str) -> dict[str, Any]:
    return {
        "scope": "product_first_test_lab",
        "execution_mode": execution_mode,
        "send_mode": "no_send",
        "openai_api_real": execution_mode in MODEL_BACKED_EXECUTION_MODES,
        "runtime_v2_agent_service": execution_mode == RUNTIME_V2_AGENT_SERVICE_MODE,
        "readiness_eligible": execution_mode == RUNTIME_V2_AGENT_SERVICE_MODE,
        "max_scenarios": REAL_TEST_LAB_MAX_SCENARIOS,
        "max_turns_per_scenario": REAL_TEST_LAB_MAX_TURNS_PER_SCENARIO,
        "max_output_tokens": REAL_TEST_LAB_MAX_OUTPUT_TOKENS,
        "temperature": REAL_TEST_LAB_TEMPERATURE,
    }


def _real_mode_limits_blocker(
    *,
    execution_mode: str,
    suite: Any,
    scenarios: list[Any],
) -> str | None:
    if execution_mode not in MODEL_BACKED_EXECUTION_MODES:
        return None
    if len(scenarios) > REAL_TEST_LAB_MAX_SCENARIOS:
        return "real_mode_max_scenarios_exceeded"
    max_turns = _real_mode_max_turns_for_suite(suite=suite, scenarios=scenarios)
    if any(len(scenario.turns) > max_turns for scenario in scenarios):
        return "real_mode_max_turns_exceeded"
    return None


def _real_mode_max_turns_for_suite(*, suite: Any, scenarios: list[Any]) -> int:
    suite_metadata = getattr(suite, "metadata_json", None)
    suite_mode = str(getattr(suite, "mode", "") or "")
    if suite_mode != "incident_replay" or not isinstance(suite_metadata, dict):
        return REAL_TEST_LAB_MAX_TURNS_PER_SCENARIO
    if suite_metadata.get("live_transcript_replay_gate") is not True:
        return REAL_TEST_LAB_MAX_TURNS_PER_SCENARIO
    if len(scenarios) != 1:
        return REAL_TEST_LAB_MAX_TURNS_PER_SCENARIO
    scenario_metadata = getattr(scenarios[0], "metadata_json", None)
    if not isinstance(scenario_metadata, dict):
        return REAL_TEST_LAB_MAX_TURNS_PER_SCENARIO
    if scenario_metadata.get("live_transcript_replay_gate") is not True:
        return REAL_TEST_LAB_MAX_TURNS_PER_SCENARIO
    return REAL_TEST_LAB_MAX_INCIDENT_REPLAY_TURNS


def _build_agent_service(
    session: AsyncSession,
    *,
    execution_mode: str,
    agent_version_id: UUID,
    agent_service_factory: AgentServiceFactory | None,
) -> tuple[AgentServiceLike, str | None]:
    if execution_mode == RUNTIME_V2_AGENT_SERVICE_MODE:
        return (
            ProductAgentRuntimeAdapter(
                session=session,
                agent_version_id=agent_version_id,
                agent_service_factory=agent_service_factory,
            ),
            None,
        )
    if agent_service_factory is not None:
        return agent_service_factory(session), None
    if execution_mode != OPENAI_DIRECT_PROVIDER_MODE:
        return AgentService(session=session), None
    provider = build_agent_turn_provider(
        model_provider_allowed=True,
        temperature=REAL_TEST_LAB_TEMPERATURE,
        max_output_tokens=REAL_TEST_LAB_MAX_OUTPUT_TOKENS,
    )
    if isinstance(provider, MockAgentProvider):
        return AgentService(session=session, provider=provider), "openai_provider_not_enabled"
    if isinstance(provider, SafeFallbackAgentProvider):
        return AgentService(session=session, provider=provider), "openai_provider_unavailable"
    return AgentService(session=session, provider=provider), None


async def run_test_suite(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    mode: str,
    review_required: bool,
    created_by_user_id: UUID | None,
    execution_mode: str = SIMULATED_CONTRACT_MODE,
    agent_service_factory: AgentServiceFactory | None = None,
) -> AgentTestRun:
    _validate_execution_mode(mode=mode, execution_mode=execution_mode)
    suite = await service.get_agent_test_suite_for_tenant(
        session,
        tenant_id=tenant_id,
        suite_id=suite_id,
    )
    scenarios = await service.list_agent_test_scenarios(
        session,
        tenant_id=tenant_id,
        suite_id=suite_id,
    )
    run = service.create_agent_test_run_record(
        tenant_id=tenant_id,
        agent_version_id=suite.agent_version_id,
        suite_id=suite.id,
        mode=mode,
        review_required=review_required,
        created_by_user_id=created_by_user_id,
    )
    run.coverage_summary = _coverage_summary(execution_mode=execution_mode)
    session.add(run)
    await session.flush()

    limits_blocker = _real_mode_limits_blocker(
        execution_mode=execution_mode,
        suite=suite,
        scenarios=scenarios,
    )
    if limits_blocker:
        _finish_run(
            run,
            scenario_results=[],
            turn_results=[],
            trace_ids=[],
            outbox_count=await _audit_outbox(session, tenant_id),
            side_effect_count=await _audit_side_effects(session, tenant_id),
            blocked_reason=limits_blocker,
        )
        await session.flush()
        suite.last_run_id = run.id
        suite.status = "blocked"
        return run

    if not scenarios:
        _finish_run(
            run,
            scenario_results=[],
            turn_results=[],
            trace_ids=[],
            outbox_count=await _audit_outbox(session, tenant_id),
            side_effect_count=await _audit_side_effects(session, tenant_id),
            blocked_reason="no_scenarios",
        )
        await session.flush()
        suite.last_run_id = run.id
        suite.status = "blocked"
        return run

    agent_service, provider_blocker = _build_agent_service(
        session,
        execution_mode=execution_mode,
        agent_version_id=suite.agent_version_id,
        agent_service_factory=agent_service_factory,
    )
    if provider_blocker:
        _finish_run(
            run,
            scenario_results=[],
            turn_results=[],
            trace_ids=[],
            outbox_count=await _audit_outbox(session, tenant_id),
            side_effect_count=await _audit_side_effects(session, tenant_id),
            blocked_reason=provider_blocker,
        )
        await session.flush()
        suite.last_run_id = run.id
        suite.status = "blocked"
        return run

    scenario_results: list[dict[str, Any]] = []
    turn_results: list[dict[str, Any]] = []
    trace_ids: list[str] = []

    for scenario_index, scenario in enumerate(scenarios, start=1):
        conversation_id = await _create_sandbox_conversation(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            scenario_id=scenario.id,
        )
        result = await _run_scenario(
            agent_service,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            suite_id=suite.id,
            scenario_id=scenario.id,
            scenario_index=scenario_index,
            turns=scenario.turns,
            expected=scenario.expected,
            execution_mode=execution_mode,
        )
        scenario_results.append(result["scenario_result"])
        turn_results.extend(result["turn_results"])
        trace_ids.extend(result["trace_ids"])

    _finish_run(
        run,
        scenario_results=scenario_results,
        turn_results=turn_results,
        trace_ids=trace_ids,
        outbox_count=await _audit_outbox(session, tenant_id),
        side_effect_count=await _audit_side_effects(session, tenant_id),
        blocked_reason=None,
    )
    await session.flush()
    suite.last_run_id = run.id
    suite.status = "passed" if run.status == "passed" else run.status
    return run


async def _run_scenario(
    agent_service: AgentServiceLike,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    suite_id: UUID,
    scenario_id: UUID,
    scenario_index: int,
    turns: list[dict[str, Any]],
    expected: dict[str, Any],
    execution_mode: str,
) -> dict[str, Any]:
    turn_results: list[dict[str, Any]] = []
    trace_ids: list[str] = []
    failures: list[str] = []

    for turn_number, turn in enumerate(turns, start=1):
        inbound = _turn_inbound(turn)
        result = await agent_service.handle_turn(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            inbound_text=inbound,
            turn_number=turn_number,
            mode="no_send",
            metadata={
                "test_lab": True,
                "test_suite_id": str(suite_id),
                "test_scenario_id": str(scenario_id),
                "scenario_index": scenario_index,
                "execution_mode": execution_mode,
                "openai_api_real": execution_mode in MODEL_BACKED_EXECUTION_MODES,
                "runtime_v2_agent_service": execution_mode == RUNTIME_V2_AGENT_SERVICE_MODE,
                "readiness_eligible": execution_mode == RUNTIME_V2_AGENT_SERVICE_MODE,
                "send_mode": "no_send",
                "max_output_tokens": REAL_TEST_LAB_MAX_OUTPUT_TOKENS,
                "temperature": REAL_TEST_LAB_TEMPERATURE,
            },
        )
        turn_expected = _turn_expected(expected=expected, turn=turn, turn_index=turn_number - 1)
        turn_result = _turn_result(
            result,
            inbound=inbound,
            turn_number=turn_number,
            expected=turn_expected,
            execution_mode=execution_mode,
        )
        failures.extend(turn_result["failures"])
        trace_id = turn_result.get("trace_id")
        if trace_id:
            trace_ids.append(str(trace_id))
        turn_results.append(turn_result)

    scenario_status = "passed" if not failures else "failed"
    return {
        "scenario_result": {
            "scenario_id": str(scenario_id),
            "status": scenario_status,
            "failures": failures,
            "turn_count": len(turns),
        },
        "turn_results": turn_results,
        "trace_ids": trace_ids,
    }


def _turn_inbound(turn: dict[str, Any]) -> str:
    inbound = turn.get("inbound_text") or turn.get("text") or turn.get("message")
    return str(inbound).strip()


def _turn_result(
    result: AgentServiceResult,
    *,
    inbound: str,
    turn_number: int,
    expected: dict[str, Any],
    execution_mode: str,
) -> dict[str, Any]:
    output = result.output
    trace_metadata = output.trace_metadata if output is not None else {}
    required_tools = _required_tools(trace_metadata)
    tool_results = _tool_results(trace_metadata)
    state_writes = _state_writes(result)
    policy_result = _policy_result(result)
    send_decision = _send_decision(result)
    token_usage = _token_usage(trace_metadata)
    estimated_cost = _estimated_cost(token_usage)
    risk_flags = _risk_flags(trace_metadata, output)
    validated_response_plan = _validated_response_plan(trace_metadata)
    human_response_composer = _human_response_composer(trace_metadata)
    failures = _assert_turn(
        {
            "final_message": output.final_message if output is not None else None,
            "required_tools": required_tools,
            "tool_results": tool_results,
            "state_writes": state_writes,
            "policy_result": policy_result,
            "response_plan": validated_response_plan,
            "message_goal": validated_response_plan.get("message_goal"),
            "user_act": validated_response_plan.get("user_act"),
            "pending_slot": validated_response_plan.get("pending_slot"),
            "slot_consumed": validated_response_plan.get("slot_consumed"),
            "human_response_composer": human_response_composer,
            "send_decision": send_decision,
            "send_status": result.send.delivery_status.get("send_status"),
            "trace_id": _trace_id(trace_metadata),
            "errors": result.errors,
            "risk_flags": risk_flags,
        },
        expected=expected,
        turn_index=turn_number - 1,
    )
    return {
        "turn_number": turn_number,
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "inbound": inbound,
        "input": inbound,
        "final_message": output.final_message if output is not None else None,
        "trace_id": _trace_id(trace_metadata),
        "tools_required": required_tools,
        "required_tools": required_tools,
        "tools_executed": [item for item in tool_results if item["status"] == "succeeded"],
        "tools_skipped": [item for item in tool_results if item["status"] == "skipped"],
        "tools_failed": [item for item in tool_results if item["status"] == "failed"],
        "tool_results": tool_results,
        "state_writes": state_writes,
        "policy_result": policy_result,
        "response_plan": validated_response_plan,
        "message_goal": validated_response_plan.get("message_goal"),
        "user_act": validated_response_plan.get("user_act"),
        "pending_slot": validated_response_plan.get("pending_slot"),
        "slot_consumed": validated_response_plan.get("slot_consumed"),
        "human_response_composer": human_response_composer,
        "forbidden_phrase_check": _forbidden_phrase_check(
            output.final_message if output is not None else "",
            validated_response_plan,
        ),
        "risk_flags": risk_flags,
        "send_decision": send_decision,
        "send_status": result.send.delivery_status.get("send_status"),
        "send_mode": result.send.mode,
        "errors": result.errors,
        "state_persistence": result.state_persistence,
        "execution_mode": execution_mode,
        "token_usage": token_usage,
        "estimated_cost": estimated_cost,
        "failure_reason": ", ".join(failures) if failures else None,
        "expected": expected,
    }


def _turn_expected(
    *,
    expected: dict[str, Any],
    turn: dict[str, Any],
    turn_index: int,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    per_turn = expected.get("turns") or expected.get("expected_turns") or []
    if turn_index < len(per_turn) and isinstance(per_turn[turn_index], dict):
        merged.update(per_turn[turn_index])
    for key in (
        "final_message_contains",
        "required_tools",
        "expected_tools",
        "tools_executed",
        "expected_tools_executed",
        "state_writes",
        "expected_state_writes",
        "field_expected",
        "expected_policy_status",
        "policy_status",
        "expected_send_decision",
        "send_decision",
        "send_status",
        "should_block",
        "trace_required",
        "internal_text_forbidden",
    ):
        if key in expected and key not in merged:
            merged[key] = expected[key]
    messages = expected.get("final_messages") or expected.get("expected_final_messages") or []
    if turn_index < len(messages) and "final_message" not in merged:
        merged["final_message"] = messages[turn_index]
    if "expected" in turn and isinstance(turn["expected"], dict):
        merged.update(turn["expected"])
    return merged


def _assert_turn(
    turn_result: dict[str, Any],
    *,
    expected: dict[str, Any],
    turn_index: int,
) -> list[str]:
    failures: list[str] = []
    final_message = turn_result.get("final_message") or ""
    messages = expected.get("final_messages") or expected.get("expected_final_messages") or []
    exact_message = expected.get("final_message")
    if exact_message is None and turn_index < len(messages):
        exact_message = messages[turn_index]
    if exact_message is not None and final_message != exact_message:
        failures.append("final_message_mismatch")
    contains = expected.get("final_message_contains")
    if contains:
        expected_contains = _expected_list(expected, "final_message_contains")
        if any(item not in final_message for item in expected_contains):
            failures.append("final_message_contains_mismatch")
    for forbidden in _expected_list(
        expected,
        "final_message_not_contains",
        "forbidden_final_message_contains",
    ):
        if forbidden in final_message:
            failures.append(f"forbidden_final_message_contains:{forbidden}")
    for tool_name in _expected_list(expected, "required_tools", "expected_tools", "tool_expected"):
        tool_results = turn_result.get("tool_results") or []
        result_by_name = {item.get("tool_name"): item.get("status") for item in tool_results}
        missing_required = tool_name not in (turn_result.get("required_tools") or [])
        missing_result = tool_name not in result_by_name
        if missing_required and missing_result:
            failures.append(f"missing_tool:{tool_name}")
        elif result_by_name.get(tool_name) == "failed":
            failures.append(f"tool_failed:{tool_name}")
        elif result_by_name.get(tool_name) == "skipped":
            failures.append(f"tool_skipped:{tool_name}")
    for tool_name in _expected_list(expected, "tools_executed", "expected_tools_executed"):
        if tool_name not in {
            item.get("tool_name")
            for item in turn_result.get("tool_results") or []
            if item.get("status") == "succeeded"
        }:
            failures.append(f"tool_not_executed:{tool_name}")
    expected_fields = _expected_list(
        expected, "state_writes", "expected_state_writes", "field_expected"
    )
    for field_key in expected_fields:
        written_fields = {item.get("field_key") for item in turn_result.get("state_writes") or []}
        if field_key not in written_fields:
            failures.append(f"missing_state_write:{field_key}")
    for field_key in _expected_list(
        expected,
        "forbidden_state_writes",
        "state_writes_forbidden",
        "field_forbidden",
    ):
        written_fields = {item.get("field_key") for item in turn_result.get("state_writes") or []}
        if field_key in written_fields:
            failures.append(f"forbidden_state_write:{field_key}")
    expected_policy = expected.get("expected_policy_status") or expected.get("policy_status")
    policy_status = (turn_result.get("policy_result") or {}).get("status")
    if policy_status in {"failed", "blocked"}:
        failures.append("policy_blocked")
    if expected_policy and policy_status != expected_policy:
        failures.append("policy_status_mismatch")
    expected_send_decision = (
        expected.get("expected_send_decision")
        or expected.get("send_decision")
        or expected.get("send_status")
        or "no_send"
    )
    if turn_result.get("send_decision") != expected_send_decision:
        failures.append("send_decision_mismatch")
    if expected.get("trace_required", True) and not turn_result["trace_id"]:
        failures.append("trace_missing")
    for blocker in _expected_list(expected, "expected_blockers", "blockers"):
        has_failure = blocker in turn_result.get("failures", [])
        has_error = blocker in turn_result.get("errors", [])
        if not has_failure and not has_error:
            failures.append(f"missing_blocker:{blocker}")
    should_block = expected.get("should_block")
    if should_block is True and not _turn_is_blocked(turn_result):
        failures.append("expected_block_missing")
    if should_block is False and _turn_is_blocked(turn_result):
        failures.append("unexpected_block")
    if expected.get("internal_text_forbidden", True) and _has_internal_visible_text(final_message):
        failures.append("internal_text_visible")
    if _semantic_provider_failed(turn_result.get("risk_flags") or []):
        failures.append("openai_provider_error")
    failures.extend(_agent_service_failures(turn_result.get("errors") or []))
    return failures


def _finish_run(
    run: AgentTestRun,
    *,
    scenario_results: list[dict[str, Any]],
    turn_results: list[dict[str, Any]],
    trace_ids: list[str],
    outbox_count: int,
    side_effect_count: int,
    blocked_reason: str | None,
) -> None:
    failed = [item for item in scenario_results if item["status"] == "failed"]
    passed = [item for item in scenario_results if item["status"] == "passed"]
    all_failures = [failure for item in scenario_results for failure in item.get("failures", [])]
    missing_trace = any("trace_missing" in failure for failure in all_failures)
    tool_failure = any(
        failure.startswith("missing_tool:") or failure.startswith("tool_not_executed:")
        or failure.startswith("tool_failed:") or failure.startswith("tool_skipped:")
        for failure in all_failures
    )
    policy_failure = any(
        failure in {"policy_blocked", "policy_status_mismatch"} for failure in all_failures
    )
    contract_failure = any(failure == RUNTIME_CONTRACT_MISSING for failure in all_failures)
    openai_failure = any(failure == "openai_provider_error" for failure in all_failures)
    blocked = (
        blocked_reason is not None
        or outbox_count > 0
        or side_effect_count > 0
        or contract_failure
        or openai_failure
    )
    run.scenario_results = scenario_results
    run.turn_results = turn_results
    run.trace_ids = trace_ids
    run.pass_count = len(passed)
    run.fail_count = len(failed)
    run.blocked_count = 1 if blocked else 0
    run.outbox_audit_result = {
        "count": outbox_count,
        "status": "pass" if outbox_count == 0 else "block",
    }
    run.side_effect_audit_result = {
        "count": side_effect_count,
        "status": "pass" if side_effect_count == 0 else "block",
    }
    if blocked:
        run.status = "blocked"
        if blocked_reason in {"openai_provider_not_enabled", "openai_provider_unavailable"}:
            run.decision = REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API
        elif openai_failure:
            run.decision = REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API
        elif blocked_reason in {"real_mode_max_scenarios_exceeded", "real_mode_max_turns_exceeded"}:
            run.decision = REAL_AGENT_TEST_LAB_BLOCKED_BY_LIMITS
        elif contract_failure or blocked_reason == RUNTIME_CONTRACT_MISSING:
            run.decision = REAL_AGENT_TEST_LAB_BLOCKED_BY_RUNTIME_CONTRACT
        else:
            run.decision = "TEST_LAB_BLOCKED_BY_TRACE" if missing_trace else TEST_LAB_FAILED
    elif failed:
        run.status = "failed"
        if missing_trace:
            run.decision = TEST_LAB_BLOCKED_BY_TRACE
        elif tool_failure:
            run.decision = TEST_LAB_BLOCKED_BY_TOOL
        elif policy_failure:
            run.decision = TEST_LAB_BLOCKED_BY_POLICY
        else:
            run.decision = TEST_LAB_FAILED
    else:
        run.status = "passed"
        run.decision = TEST_LAB_PASSED
    if blocked_reason:
        run.coverage_summary = {
            **(run.coverage_summary or {}),
            "blocked_reason": blocked_reason,
        }


def _trace_id(trace_metadata: dict[str, Any]) -> str | None:
    trace_id = trace_metadata.get("trace_id")
    if trace_id:
        return str(trace_id)
    universal = trace_metadata.get("universal_turn_trace")
    if isinstance(universal, dict) and universal.get("trace_id"):
        return str(universal["trace_id"])
    if isinstance(universal, dict) and universal.get("turn_id"):
        return str(universal["turn_id"])
    return None


def _risk_flags(trace_metadata: dict[str, Any], output: Any) -> list[str]:
    flags: list[str] = []
    if output is not None:
        flags.extend(str(item) for item in getattr(output, "risk_flags", []) or [])
    advisor = trace_metadata.get("advisor_brain")
    if isinstance(advisor, dict):
        flags.extend(str(item) for item in advisor.get("risk_flags") or [])
    universal = trace_metadata.get("universal_turn_trace")
    if isinstance(universal, dict):
        final_output = universal.get("final_output")
        if isinstance(final_output, dict):
            flags.extend(str(item) for item in final_output.get("risk_flags") or [])
        gpt = universal.get("gpt_understanding")
        if isinstance(gpt, dict):
            flags.extend(str(item) for item in gpt.get("risk_flags") or [])
    return list(dict.fromkeys(flags))


def _semantic_provider_failed(risk_flags: list[str]) -> bool:
    return any(str(flag) == "semantic_interpreter_provider_error" for flag in risk_flags)


def _required_tools(trace_metadata: dict[str, Any]) -> list[str]:
    advisor = trace_metadata.get("advisor_brain")
    universal = trace_metadata.get("universal_turn_trace")
    if not isinstance(advisor, dict) and isinstance(universal, dict):
        advisor = universal.get("advisor_brain")
    if not isinstance(advisor, dict):
        return []
    tools: list[str] = []
    for item in advisor.get("required_tools") or []:
        if isinstance(item, str):
            tools.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("tool_name") or item.get("tool_id")
            if name:
                tools.append(str(name))
    return tools


def _tool_results(trace_metadata: dict[str, Any]) -> list[dict[str, str]]:
    items = list(trace_metadata.get("tool_results") or [])
    universal = trace_metadata.get("universal_turn_trace")
    if isinstance(universal, dict):
        items.extend(universal.get("tool_results") or [])
    results: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("tool_name") or item.get("tool_id") or item.get("name")
        status = _normalize_tool_status(item.get("status"))
        if name and status:
            results.append({"tool_name": str(name), "status": str(status)})
    return results


def _token_usage(trace_metadata: dict[str, Any]) -> dict[str, int]:
    usage = trace_metadata.get("model_usage")
    universal = trace_metadata.get("universal_turn_trace")
    if not isinstance(usage, dict) and isinstance(universal, dict):
        usage = universal.get("model_usage")
    if not isinstance(usage, dict):
        return {}
    return {
        key: int(value)
        for key, value in {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }.items()
        if value is not None
    }


def _validated_response_plan(trace_metadata: dict[str, Any]) -> dict[str, Any]:
    plan = trace_metadata.get("validated_response_plan")
    universal = trace_metadata.get("universal_turn_trace")
    if not isinstance(plan, dict) and isinstance(universal, dict):
        plan = universal.get("validated_response_plan")
    return dict(plan) if isinstance(plan, dict) else {}


def _human_response_composer(trace_metadata: dict[str, Any]) -> dict[str, Any]:
    composer = trace_metadata.get("human_response_composer")
    universal = trace_metadata.get("universal_turn_trace")
    if not isinstance(composer, dict) and isinstance(universal, dict):
        composer = universal.get("human_response_composer")
    return dict(composer) if isinstance(composer, dict) else {}


def _forbidden_phrase_check(
    final_message: str,
    validated_response_plan: dict[str, Any],
) -> dict[str, Any]:
    phrases = validated_response_plan.get("forbidden_phrases")
    if not isinstance(phrases, list):
        phrases = []
    folded = str(final_message or "").casefold()
    found = [
        str(phrase)
        for phrase in phrases
        if str(phrase).strip() and str(phrase).casefold() in folded
    ]
    return {"status": "passed" if not found else "failed", "found": found}


def _estimated_cost(token_usage: dict[str, int]) -> dict[str, Any]:
    if not token_usage:
        return {"amount_usd": None, "status": "token_usage_missing"}
    return {
        "amount_usd": None,
        "status": "cost_rate_not_configured",
        "input_tokens": token_usage.get("input_tokens", 0),
        "output_tokens": token_usage.get("output_tokens", 0),
        "total_tokens": token_usage.get("total_tokens", 0),
    }


def _normalize_tool_status(status: Any) -> str:
    raw = str(status or "").lower()
    if raw in {"succeeded", "success", "passed", "ok"}:
        return "succeeded"
    if raw in {"skipped", "blocked", "not_run"}:
        return "skipped"
    if raw in {"failed", "error", "fail"}:
        return "failed"
    return raw


def _state_writes(result: AgentServiceResult) -> list[dict[str, Any]]:
    output = result.output
    writes: list[dict[str, Any]] = []
    if output is not None:
        writes.extend(update.model_dump(mode="json") for update in output.field_updates)
        trace_state = output.trace_metadata.get("state_writes")
        if isinstance(trace_state, list):
            writes.extend(item for item in trace_state if isinstance(item, dict))
        universal = output.trace_metadata.get("universal_turn_trace")
        if isinstance(universal, dict):
            writes.extend(
                item for item in universal.get("state_writes") or [] if isinstance(item, dict)
            )
    persisted = result.state_persistence.get("writes")
    if isinstance(persisted, list):
        writes.extend(item for item in persisted if isinstance(item, dict))
    return writes


def _policy_result(result: AgentServiceResult) -> dict[str, Any]:
    output = result.output
    policy: Any = None
    if output is not None:
        policy = output.trace_metadata.get("policy_result") or output.trace_metadata.get("policy")
        universal = output.trace_metadata.get("universal_turn_trace")
        if policy is None and isinstance(universal, dict):
            policy = universal.get("policy_result") or universal.get("policy")
    if isinstance(policy, dict):
        return policy
    if result.errors:
        return {"status": "failed", "errors": result.errors}
    return {"status": "passed"}


def _send_decision(result: AgentServiceResult) -> str:
    delivery = result.send.delivery_status
    return str(
        delivery.get("send_decision")
        or delivery.get("send_status")
        or result.send.send_decision.reason
        or result.send.mode
    )


def _expected_list(expected: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = expected.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw if item is not None)
    return values


def _agent_service_failures(errors: list[Any]) -> list[str]:
    failures: list[str] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        code = str(error.get("code") or "")
        if code == "required_tool_not_succeeded_blocks_send":
            failures.append("required_tool_blocked_send")
        elif code == RUNTIME_CONTRACT_MISSING:
            failures.append(RUNTIME_CONTRACT_MISSING)
        elif code:
            failures.append(f"agent_service_error:{code}")
    return failures


def _turn_is_blocked(turn_result: dict[str, Any]) -> bool:
    policy_status = (turn_result.get("policy_result") or {}).get("status")
    return bool(
        turn_result.get("send_decision") != "no_send"
        or policy_status in {"failed", "blocked"}
        or turn_result.get("errors")
    )


def _has_internal_visible_text(final_message: str) -> bool:
    normalized = final_message.lower()
    return any(marker in normalized for marker in INTERNAL_VISIBLE_TEXT_MARKERS)


async def _create_sandbox_conversation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    scenario_id: UUID,
) -> UUID:
    phone = f"+520000{str(scenario_id).replace('-', '')[:10]}"
    contact_id = (
        await session.execute(
            text(
                """INSERT INTO customers (tenant_id, phone_e164, name, attrs)
                VALUES (:tenant_id, :phone, 'Test Lab Contact', '{}'::jsonb)
                RETURNING id"""
            ),
            {"tenant_id": tenant_id, "phone": phone},
        )
    ).scalar_one()
    conversation_id = (
        await session.execute(
            text(
                """INSERT INTO conversations
                (tenant_id, customer_id, current_stage, status, channel, tags)
                VALUES (:tenant_id, :customer_id, 'test_lab', 'active', 'test_lab',
                        '[]'::jsonb)
                RETURNING id"""
            ),
            {"tenant_id": tenant_id, "customer_id": contact_id},
        )
    ).scalar_one()
    await session.execute(
        text(
            """INSERT INTO conversation_state (conversation_id, extracted_data)
            VALUES (:conversation_id, '{}'::jsonb)"""
        ),
        {"conversation_id": conversation_id},
    )
    await session.execute(
        text(
            """INSERT INTO messages (
                tenant_id, conversation_id, direction, text, metadata_json, sent_at
            )
            VALUES (:tenant_id, :conversation_id, 'system', 'test_lab_sandbox',
                    CAST(:metadata AS jsonb), now())"""
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "metadata": (
                '{"product_first_test_lab":true,'
                f'"test_suite_id":"{suite_id}","test_scenario_id":"{scenario_id}"}}'
            ),
        },
    )
    return UUID(str(conversation_id))


async def _audit_outbox(session: AsyncSession, tenant_id: UUID) -> int:
    return int(
        (
            await session.execute(
                text(
                    """SELECT count(*)
                    FROM outbound_outbox
                    WHERE tenant_id = :tenant_id
                      AND status IN ('pending', 'retry')"""
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one()
    )


async def _audit_side_effects(session: AsyncSession, tenant_id: UUID) -> int:
    return int(
        (
            await session.execute(
                text(
                    """SELECT count(*)
                    FROM business_event_ledger
                    WHERE tenant_id = :tenant_id
                      AND side_effects_allowed = true"""
                ),
                {"tenant_id": tenant_id},
            )
        ).scalar_one()
    )

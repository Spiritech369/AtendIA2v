from __future__ import annotations

from pathlib import Path

import pytest

from atendia.agent_runtime.respond_style_llm_provider import RespondStyleLLMTurnProvider
from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnInput,
)
from atendia.scripts.run_dinamo_phase_c_openai_compat_test_lab import (
    COMPAT_EXECUTION_MODE,
    COMPAT_PROVIDER_CLASS,
    _assert_turn_contract,
    _FakeOpenAIClient,
    _tool_arguments,
    compat_scenarios,
)


def _turn_input(text: str) -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="tenant",
        deployment_id="deployment",
        agent_id="agent",
        agent_version_id="version",
        runtime_mode="test_lab_no_send",
        channel="test_lab",
        conversation_id="conversation",
        inbound_text=text,
    )


def _context(*tool_names: str) -> AgentContextPackage:
    return AgentContextPackage(
        instructions="Use only tenant-approved facts.",
        tool_schemas=[
            {"tool_name": "quote.resolve", "description": "Return quote facts."}
        ],
        tool_results=[
            {
                "tool_name": tool_name,
                "status": "succeeded",
                "facts": {"source": "dry"},
                "source_refs": [tool_name],
                "source_kind": "dry_facts",
            }
            for tool_name in tool_names
        ],
    )


def test_compat_scenarios_cover_provider_and_tool_paths() -> None:
    scenarios = compat_scenarios()

    assert {scenario.key for scenario in scenarios} == {
        "phase_c_identity_greeting",
        "phase_c_quote_tool_request",
    }
    quote = next(
        scenario for scenario in scenarios if scenario.key == "phase_c_quote_tool_request"
    )
    assert quote.expected_tools == ("quote.resolve",)


@pytest.mark.asyncio
async def test_fake_openai_client_requests_tool_then_returns_grounded_final() -> None:
    client = _FakeOpenAIClient()
    provider = RespondStyleLLMTurnProvider(client=client)

    request = await provider.generate(
        turn_input=_turn_input("Cotiza Adventure Elite con nomina en tarjeta"),
        context=_context(),
    )

    assert request.final_message is None
    assert request.validation is not None
    assert request.validation.status == "valid"
    assert [
        tool.tool_name for tool in request.validation.accepted_tool_requests
    ] == ["quote.resolve"]

    final = await provider.generate(
        turn_input=_turn_input("Cotiza Adventure Elite con nomina en tarjeta"),
        context=_context("quote.resolve"),
    )

    assert final.final_message is not None
    assert "cotizacion validada" in final.final_message
    assert final.validation is not None
    assert final.validation.status == "valid"
    assert final.send_decision == "no_send"
    assert len(client.chat.completions.calls) == 2


@pytest.mark.asyncio
async def test_fake_openai_client_greeting_stays_no_send_without_tools() -> None:
    provider = RespondStyleLLMTurnProvider(client=_FakeOpenAIClient())

    decision = await provider.generate(
        turn_input=_turn_input("Hola, quiero info de credito"),
        context=_context(),
    )

    assert decision.final_message is not None
    assert "cuanto tiempo llevas trabajando" in decision.final_message
    assert decision.validation is not None
    assert decision.validation.status == "valid"
    assert decision.send_decision == "no_send"


def test_tool_arguments_use_strict_values_shape() -> None:
    args = _tool_arguments(Moto="Adventure Elite 150 CC", Plan_Credito="Nomina tarjeta")

    assert args["summary"] == "Tenant fact lookup arguments."
    assert {"key": "Moto", "string_value": "Adventure Elite 150 CC"} in args["values"]
    assert {"key": "Plan_Credito", "string_value": "Nomina tarjeta"} in args["values"]


def test_assert_turn_contract_detects_missing_tool_and_leaks() -> None:
    scenario = compat_scenarios()[1]
    good_turn = {
        "blocked_reason": None,
        "tools": [{"tool_name": "quote.resolve", "status": "succeeded"}],
        "final_message": "Ya tengo la cotizacion validada para Adventure Elite 150 CC.",
    }
    assert _assert_turn_contract(scenario, good_turn) == []

    bad_turn = {
        "blocked_reason": None,
        "tools": [],
        "final_message": "trace prompt",
    }
    failures = _assert_turn_contract(scenario, bad_turn)
    assert "phase_c_quote_tool_request:missing_tool:quote.resolve" in failures
    assert "phase_c_quote_tool_request:final_message_forbidden:trace" in failures
    assert "phase_c_quote_tool_request:final_message_forbidden:prompt" in failures


def test_script_uses_fake_client_without_real_openai_import() -> None:
    source = Path(
        "atendia/scripts/run_dinamo_phase_c_openai_compat_test_lab.py"
    ).read_text(encoding="utf-8")

    assert COMPAT_PROVIDER_CLASS == "RespondStyleLLMTurnProvider"
    assert COMPAT_EXECUTION_MODE == "openai_direct_provider_fake_client"
    assert "from openai" not in source
    assert "import openai" not in source

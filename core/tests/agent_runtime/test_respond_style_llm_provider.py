from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    RespondStyleLLMTurnProvider,
)
from atendia.agent_runtime.respond_style_llm_provider import (
    build_respond_style_messages,
    respond_style_llm_json_schema,
)


@pytest.mark.asyncio
async def test_provider_output_valid_passes_validator_no_send() -> None:
    provider = RespondStyleLLMTurnProvider(
        client=_FakeOpenAIClient(
            [
                _json_output(
                    final_message="Hi, I can help. What kind of information are you looking for?",
                    claims=[
                        {
                            "text": "I can help with information.",
                            "basis": "customer_message",
                            "source_refs": [],
                        }
                    ],
                )
            ]
        )
    )

    decision = await provider.generate(
        turn_input=_turn_input("hi, looking for info"),
        context=_context(),
    )

    assert decision.final_message.startswith("Hi")
    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "valid"


@pytest.mark.asyncio
async def test_provider_price_without_quote_produces_retry_instruction() -> None:
    provider = RespondStyleLLMTurnProvider(
        client=_FakeOpenAIClient([
            _json_output(final_message="The price is $10,000."),
            _json_output(final_message="I can check that with the right quote first."),
        ])
    )

    decision = await provider.generate(
        turn_input=_turn_input("how much?"),
        context=_context(),
    )

    assert len(provider._client.chat.completions.calls) == 2  # type: ignore[attr-defined]
    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "valid"
    retry_payload = provider.last_messages[-1]["content"]
    assert "missing_quote_tool" in retry_payload


@pytest.mark.asyncio
async def test_provider_requirements_without_tool_produces_retry_instruction() -> None:
    provider = RespondStyleLLMTurnProvider(
        client=_FakeOpenAIClient([
            _json_output(final_message="The requirements are ID and proof of address."),
            _json_output(final_message="I can check the exact list first."),
        ])
    )

    decision = await provider.generate(
        turn_input=_turn_input("what do I need?"),
        context=_context(),
    )

    assert decision.validation is not None
    assert decision.validation.status == "valid"
    assert "missing_requirements_tool" in provider.last_messages[-1]["content"]


@pytest.mark.asyncio
async def test_provider_internal_leak_retries_then_no_send_when_uncorrected() -> None:
    provider = RespondStyleLLMTurnProvider(
        client=_FakeOpenAIClient([
            _json_output(final_message="I checked the trace."),
            _json_output(final_message="The workflow says I should answer."),
        ])
    )

    decision = await provider.generate(
        turn_input=_turn_input("status?"),
        context=_context(),
    )

    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    assert "internal_text_visible" in decision.validation.blocked_reason


@pytest.mark.asyncio
async def test_provider_can_propose_field_update_with_evidence() -> None:
    provider = RespondStyleLLMTurnProvider(
        client=_FakeOpenAIClient(
            [
                _json_output(
                    final_message="Got it, I noted the service you need.",
                    field_write_proposals=[
                        {
                            "field_key": "preferred_service",
                            "value": "repair",
                            "evidence": ["I need a repair."],
                            "confidence": 0.9,
                            "reason": "Customer stated the service need.",
                        }
                    ],
                )
            ]
        )
    )

    decision = await provider.generate(
        turn_input=_turn_input("I need a repair."),
        context=_context(field_policies=[{"field_key": "preferred_service", "writable": True}]),
    )

    assert decision.validation is not None
    assert decision.validation.status == "valid"
    assert decision.accepted_field_writes[0].field_key == "preferred_service"


def test_provider_prompt_has_no_tenant_or_vertical_hardcode() -> None:
    messages = build_respond_style_messages(turn_input=_turn_input("hello"), context=_context())
    prompt = "\n".join(message["content"] for message in messages).casefold()

    forbidden_terms = ["dinamo", "motos", "credito", "sat", "metro"]
    assert not any(
        re.search(rf"\b{re.escape(term)}\b", prompt)
        for term in forbidden_terms
    )
    assert "whatsapp" in prompt
    assert "return only json" in prompt
    assert "matching tool is available" in prompt
    assert "preconditions" in prompt
    assert "requested fact" in prompt
    assert "tool_results" in prompt
    assert "same succeeded tool" in prompt
    assert "requirements capability" in prompt
    assert "quote capability" in prompt
    assert "concrete next step" in prompt


def test_provider_requires_strict_schema() -> None:
    schema = respond_style_llm_json_schema()
    root_schema = schema["schema"]
    tool_item = root_schema["properties"]["tool_requests"]["items"]
    action_item = root_schema["properties"]["action_proposals"]["items"]
    workflow_item = root_schema["properties"]["workflow_event_proposals"]["items"]

    assert schema["strict"] is True
    assert root_schema["additionalProperties"] is False
    assert "final_message" in root_schema["required"]
    argument_schema = tool_item["properties"]["arguments"]
    assert argument_schema["additionalProperties"] is False
    assert argument_schema["required"] == ["values", "summary"]
    assert argument_schema["properties"]["values"]["type"] == "array"
    assert action_item["properties"]["payload"] == argument_schema
    assert workflow_item["properties"]["payload"] == argument_schema


def test_provider_source_has_no_unsafe_legacy_or_live_imports() -> None:
    source = Path("core/atendia/agent_runtime/respond_style_llm_provider.py").read_text(
        encoding="utf-8"
    )

    forbidden = [
        "HumanResponseComposer",
        "StructuredRuntimeComposer",
        "ConversationRunner",
        "RuntimeV2SendAdapter",
        "enqueue_messages",
        "evaluate_event",
    ]
    assert not any(item in source for item in forbidden)


def test_manual_runner_accepts_atendia_v2_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_manual_runner()

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ATENDIA_V2_OPENAI_API_KEY", "test-key")

    assert runner._api_key_from_env() == ("test-key", "ATENDIA_V2_OPENAI_API_KEY")


def test_manual_runner_reads_atendia_v2_key_from_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_manual_runner()
    env_file = tmp_path / ".env"
    env_file.write_text("ATENDIA_V2_OPENAI_API_KEY='file-key'\n", encoding="utf-8")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ATENDIA_V2_OPENAI_API_KEY", raising=False)

    assert runner._api_key_from_env((env_file,)) == (
        "file-key",
        ".env:ATENDIA_V2_OPENAI_API_KEY",
    )


@pytest.mark.asyncio
async def test_provider_blocks_schema_errors_as_no_send() -> None:
    provider = RespondStyleLLMTurnProvider(client=_FakeOpenAIClient(["not-json"]))

    decision = await provider.generate(turn_input=_turn_input("hello"), context=_context())

    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    assert decision.validation.blocked_reason == "llm_turn_provider_failed"


def _turn_input(inbound_text: str) -> AgentTurnInput:
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
    )


def _context(*, field_policies: list[dict] | None = None) -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={"name": "Generic assistant", "role": "assistant"},
        instructions="Help the customer using only the given context.",
        voice_guide={"tone": "brief, clear, human"},
        field_policies=field_policies or [],
        action_schemas=[{"name": "task.create", "enabled": True, "permitted": True}],
        workflow_trigger_schemas=[{"binding_name": "lead_review", "enabled": True}],
        handoff_policy={"enabled": True, "targets": ["sales"]},
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


class _FakeOpenAIClient:
    def __init__(self, outputs: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(outputs))


class _FakeCompletions:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        output = self._outputs.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=output))]
        )


def _load_manual_runner():
    path = Path("tools/run_respond_style_llm_provider_no_send_2026_06_09.py")
    spec = importlib.util.spec_from_file_location("respond_style_no_send_runner", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

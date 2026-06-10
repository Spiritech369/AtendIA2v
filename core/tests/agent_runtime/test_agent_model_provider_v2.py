from __future__ import annotations

import json

import pytest

from atendia.agent_runtime import (
    ActionRequest,
    MockAgentProvider,
    OpenAIAgentProvider,
    PolicyValidationError,
    PolicyValidator,
    TurnContext,
    TurnOutput,
    agent_model_provider_enabled,
    build_agent_turn_provider,
)
from atendia.agent_runtime.model_provider import (
    build_agent_turn_messages,
    build_minimized_turn_payload,
    parse_turn_output_json,
)
from atendia.agent_runtime.runtime import AgentRuntime
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    ContactFieldDefinitionContext,
    ConversationMemoryContext,
    CustomerContext,
    KnowledgeCitation,
    LifecycleContext,
    MessageContext,
    TenantRuntimeConfigContext,
)
from atendia.config import Settings


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str, usage=None) -> None:
        self.choices = [_FakeChoice(content)]
        self.model = "gpt-test"
        self.usage = usage


class _FakeUsage:
    prompt_tokens = 11
    completion_tokens = 7
    total_tokens = 18


class _FakeCompletions:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, tuple):
            return _FakeResponse(response[0], response[1])
        return _FakeResponse(response)


class _FakeChat:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.chat = _FakeChat(responses)


def _valid_json(**overrides) -> str:
    data = {
        "final_message": "Claro, te ayudo con eso.",
        "actions": [],
        "field_updates": [],
        "lifecycle_update": None,
        "knowledge_citations": [],
        "confidence": 0.8,
        "needs_human": False,
        "risk_flags": [],
        "trace_metadata": {},
    }
    data.update(overrides)
    return json.dumps(data)


def _context() -> TurnContext:
    return TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text="Que precio tiene?",
        knowledge_citations=[
            KnowledgeCitation(
                source_id="source-1",
                title="Catalogo",
                snippet="Servicio premium desde $199.",
                score=0.9,
            )
        ],
    )


@pytest.mark.asyncio
async def test_mock_provider_produces_valid_turn_output():
    output = await MockAgentProvider().generate(_context())

    PolicyValidator().validate_or_raise(output)
    assert output.final_message
    assert output.trace_metadata["provider"] == "mock_agent_provider"


@pytest.mark.asyncio
async def test_openai_provider_accepts_valid_json_without_repair():
    client = _FakeClient(
        [
            _valid_json(
                final_message="JSON valido.",
                knowledge_citations=[
                    {
                        "source_id": "source-1",
                        "title": "Catalogo",
                        "snippet": "Servicio premium desde $199.",
                        "score": 0.9,
                        "metadata": {},
                    }
                ],
            )
        ]
    )
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    assert output.final_message == "JSON valido."
    assert output.needs_human is False
    assert len(client.chat.completions.calls) == 1
    assert client.chat.completions.calls[0]["response_format"]["type"] == "json_schema"
    assert output.trace_metadata["provider"] == "openai"


@pytest.mark.asyncio
async def test_openai_provider_records_usage_and_low_cost_limits():
    client = _FakeClient([(_valid_json(final_message="JSON valido."), _FakeUsage())])
    provider = OpenAIAgentProvider(
        api_key="sk-test",
        client=client,
        temperature=0.2,
        max_output_tokens=350,
    )

    output = await provider.generate(_context())

    call = client.chat.completions.calls[0]
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 350
    assert output.trace_metadata["model_usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "phase": "generate",
    }


@pytest.mark.asyncio
async def test_openai_provider_repairs_invalid_json_once():
    client = _FakeClient(["not-json", _valid_json(final_message="JSON reparado.")])
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    assert output.final_message == "JSON reparado."
    assert len(client.chat.completions.calls) == 2
    assert output.trace_metadata["provider"] == "openai"


@pytest.mark.asyncio
async def test_invalid_json_fails_safe_after_repair_failure():
    client = _FakeClient(["not-json", "still-not-json"])
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    assert output.needs_human is True
    assert output.confidence == 0.0
    assert "agent_model_provider_failed" in output.risk_flags


@pytest.mark.asyncio
async def test_openai_provider_timeout_falls_back_without_external_call():
    client = _FakeClient([TimeoutError("mock timeout")])
    provider = OpenAIAgentProvider(
        api_key="sk-test",
        client=client,
        retry_delays_ms=(),
    )

    output = await provider.generate(_context())

    assert output.needs_human is True
    assert output.confidence == 0.0
    assert output.trace_metadata["error_type"] == "TimeoutError"
    assert "agent_model_provider_failed" in output.risk_flags


@pytest.mark.asyncio
async def test_hallucinated_unknown_action_is_blocked_by_runtime_policy():
    provider = MockAgentProvider(
        TurnOutput(
            final_message="Listo.",
            confidence=0.8,
            actions=[ActionRequest(name="invented_action")],
        )
    )

    with pytest.raises(PolicyValidationError) as exc:
        await AgentRuntime(provider=provider).run_turn(
            {
                "tenant_id": "tenant-1",
                "conversation_id": "conversation-1",
                "inbound_text": "Haz algo",
            }
        )

    assert "unknown_action" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_provider_unknown_action_is_dropped_before_policy():
    client = _FakeClient(
        [
            _valid_json(
                actions=[
                    {
                        "name": "invented_action",
                        "payload": {},
                        "reason": "model hallucinated it",
                        "evidence": ["customer asked"],
                        "requires_approval": False,
                        "idempotency_key": None,
                        "metadata": {},
                    }
                ]
            )
        ]
    )
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    assert output.needs_human is True
    assert output.actions == []
    assert "agent_model_provider_policy_rejected" not in output.risk_flags
    assert output.trace_metadata["reconciler_changes"]["dropped_invalid_actions"] == [
        "invented_action"
    ]


@pytest.mark.asyncio
async def test_openai_provider_drops_final_message_inside_action_payload():
    client = _FakeClient(
        [
            _valid_json(
                actions=[
                    {
                        "name": "add_tag",
                        "payload": {"tag": "lead", "final_message": "Visible copy"},
                        "reason": "tag requested",
                        "evidence": ["customer message"],
                        "requires_approval": False,
                        "idempotency_key": None,
                        "metadata": {},
                    }
                ]
            )
        ]
    )
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    assert output.needs_human is True
    assert output.actions == []
    assert "agent_model_provider_policy_rejected" not in output.risk_flags
    assert output.trace_metadata["reconciler_changes"]["dropped_invalid_actions"] == [
        "add_tag:visible_copy"
    ]


@pytest.mark.asyncio
async def test_field_update_without_evidence_is_blocked_by_runtime_policy():
    raw = _valid_json(
        field_updates=[
            {
                "field_key": "budget",
                "value": "5000",
                "reason": None,
                "evidence": [],
                "confidence": 0.8,
                "source": "ai_inference",
                "evidence_message_id": None,
                "evidence_attachment_id": None,
                "trace_id": None,
                "metadata": {},
            }
        ]
    )
    output = parse_turn_output_json(raw)

    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(output)

    assert "field_update_missing_evidence" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_provider_drops_invalid_field_update_but_keeps_safe_message():
    client = _FakeClient(
        [
            _valid_json(
                field_updates=[
                    {
                        "field_key": "budget",
                        "value": "5000",
                        "reason": None,
                        "evidence": [],
                        "confidence": None,
                        "source": "ai_inference",
                        "evidence_message_id": None,
                        "evidence_attachment_id": None,
                        "trace_id": None,
                        "metadata": {},
                    }
                ]
            )
        ]
    )
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    assert output.final_message == "Claro, te ayudo con eso."
    assert output.field_updates == []
    dropped = output.trace_metadata["reconciler_changes"]["dropped_field_updates"]
    assert dropped == [{"field_key": "budget", "reason": "missing_evidence+missing_confidence"}]


def test_prompt_contains_knowledge_citations():
    messages = build_agent_turn_messages(_context())
    prompt = messages[1]["content"]

    assert "knowledge_citations" in prompt
    assert "Servicio premium desde $199." in prompt
    assert "Que precio tiene?" in prompt


def test_system_prompt_uses_agent_voice_before_tenant_default_voice():
    context = TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text="Hola",
        tenant_config=TenantRuntimeConfigContext(
            default_voice={"personality": "Tenant fallback voice"},
        ),
        active_agent=ActiveAgentContext(
            id="agent-1",
            name="Ventas",
            tone="Consultivo",
            voice={
                "personality": "Agent-specific voice",
                "forbidden_phrases": ["estimado cliente"],
            },
        ),
    )

    system = build_agent_turn_messages(context)[0]["content"]

    assert "Voice guide source: active_agent" in system
    assert "Agent-specific voice" in system
    assert "estimado cliente" in system
    assert "Tenant fallback voice" not in system


def test_system_prompt_uses_tenant_default_voice_when_agent_voice_is_empty():
    context = TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text="Hola",
        tenant_config=TenantRuntimeConfigContext(
            default_voice={"personality": "Tenant fallback voice"},
        ),
        active_agent=ActiveAgentContext(id="agent-1", name="Soporte", voice={}),
    )

    system = build_agent_turn_messages(context)[0]["content"]

    assert "Voice guide source: tenant_default" in system
    assert "Tenant fallback voice" in system


def test_turn_prompt_minimizes_and_redacts_provider_payload():
    context = TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text="Mi correo es cliente@example.com y mi cel 8112345678",
        customer=CustomerContext(
            id="customer-1",
            phone_e164="+528112345678",
            email="cliente@example.com",
            attrs={"secret_note": "do-not-send", "phone": "8112345678"},
        ),
        messages=[
            MessageContext(role="customer", text=f"mensaje {idx} 8112345678")
            for idx in range(8)
        ],
        contact_fields=[
            ContactFieldDefinitionContext(
                key="down_payment",
                label="Enganche",
                field_type="number",
            )
        ],
        lifecycle=LifecycleContext(
            stage="credito",
            status="active",
            pipeline_id="pipeline-1",
            metadata={"internal": "hidden"},
        ),
        active_agent=ActiveAgentContext(
            id="agent-1",
            name="Agent",
            instructions="Answer from knowledge only.",
            enabled_action_ids=["handoff"],
            metadata={"secret_config": "hidden"},
        ),
        knowledge_citations=[
            KnowledgeCitation(
                source_id=f"source-{idx}",
                title="Catalogo",
                snippet=("Catalogo cliente@example.com 8112345678 " + ("x" * 900)),
                score=0.9,
                metadata={
                    "content_type": "catalog",
                    "allowed_agent_ids": ["agent-1"],
                    "secret": "hidden",
                },
            )
            for idx in range(7)
        ],
    )

    payload = build_minimized_turn_payload(context)
    prompt = json.dumps(payload, ensure_ascii=False)

    assert "cliente@example.com" not in prompt
    assert "8112345678" not in prompt
    assert "+528112345678" not in prompt
    assert "do-not-send" not in prompt
    assert "secret_config" not in prompt
    assert "allowed_agent_ids" not in prompt
    assert "hidden" not in prompt
    assert payload["customer_message"] == (
        "Mi correo es [redacted_email] y mi cel [redacted_phone]"
    )
    assert payload["contact_fields"] == {}
    assert payload["lifecycle"] == {
        "stage": "credito",
        "status": "active",
        "pipeline_id": "pipeline-1",
    }
    assert len(payload["conversation_history"]) == 6
    assert len(payload["knowledge_citations"]) == 5
    assert len(payload["knowledge_citations"][0]["snippet"]) <= 700
    assert payload["knowledge_citations"][0]["metadata"] == {
        "content_type": "catalog"
    }
    assert payload["payload_minimization"]["contact_field_values_included"] is False
    assert payload["payload_minimization"]["attachments_included"] is False
    assert len(payload["payload_minimization"]["payload_hash_sha256"]) == 64


def test_turn_prompt_includes_memory_and_tenant_ruleset_without_private_attrs():
    context = TurnContext(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        inbound_text="Ya te dije cual queria",
        customer=CustomerContext(attrs={"private_note": "do-not-send"}),
        memory=ConversationMemoryContext(
            summary="Cliente quiere producto canonico P-1 y pregunto por documentos.",
            salient_facts={"canonical_product_id": "P-1"},
            last_quote_snapshot={"snapshot_id": "quote-1", "product_id": "P-1"},
            last_pending_question="Que fecha prefieres?",
        ),
        tenant_config=TenantRuntimeConfigContext(
            ruleset={"operational_state": {"fields": {"product": "Producto"}}},
            tools={"quote_resolver": {"enabled": True}},
            knowledge_sources=["source-1"],
        ),
    )

    payload = build_minimized_turn_payload(context)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["memory"]["salient_facts"]["canonical_product_id"] == "P-1"
    assert payload["memory"]["last_quote_snapshot"]["snapshot_id"] == "quote-1"
    assert payload["tenant_config"]["ruleset"]["operational_state"]["fields"]["product"] == (
        "Producto"
    )
    assert payload["tenant_config"]["tools"]["quote_resolver"]["enabled"] is True
    assert "do-not-send" not in serialized


@pytest.mark.asyncio
async def test_low_confidence_output_sets_needs_human():
    client = _FakeClient([_valid_json(confidence=0.2, needs_human=False, risk_flags=[])])
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    assert output.needs_human is True
    assert "low_confidence" in output.risk_flags


@pytest.mark.asyncio
async def test_openai_provider_marks_missing_required_citations():
    client = _FakeClient([_valid_json(knowledge_citations=[])])
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    assert output.needs_human is True
    assert "missing_required_citations" in output.risk_flags
    assert output.knowledge_citations[0].source_id == "source-1"


@pytest.mark.asyncio
async def test_openai_provider_fallback_is_safe_needs_human_output():
    client = _FakeClient(["not-json", "still-not-json"])
    provider = OpenAIAgentProvider(api_key="sk-test", client=client)

    output = await provider.generate(_context())

    PolicyValidator().validate_or_raise(output)
    assert output.needs_human is True
    assert output.actions == []
    assert output.field_updates == []
    assert output.lifecycle_update is None
    assert output.final_message


def test_llm_provider_is_not_used_when_flag_off():
    settings = Settings(
        _env_file=None,  # type: ignore[arg-type]
        agent_runtime_v2_enabled=False,
        agent_runtime_v2_model_provider="openai",
        openai_api_key="sk-test",
    )

    provider = build_agent_turn_provider(settings)

    assert agent_model_provider_enabled(settings) is False
    assert provider.__class__.__name__ == "MockAgentProvider"

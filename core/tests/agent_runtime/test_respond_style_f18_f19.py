from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from atendia.agent_runtime import (
    AgentContextPackage,
    AgentTurnInput,
    LLMAgentTurnOutput,
    LLMClaim,
    RespondStyleLLMTurnProvider,
    RespondStyleLLMTurnProviderConfig,
    RespondStyleTurnValidator,
)
from atendia.agent_runtime.respond_style_llm_provider import respond_style_system_prompt


class RateLimitError(Exception):
    status_code = 429

    def __init__(self, retry_after: str | None = None) -> None:
        headers = {}
        if retry_after is not None:
            headers["retry-after"] = retry_after
        self.response = SimpleNamespace(headers=headers)
        super().__init__("rate limited")


class InternalServerError(Exception):
    status_code = 500


def _ok_output() -> str:
    return json.dumps(
        {
            "turn_kind": "final_response",
            "final_message": "Hola, te ayudo con gusto.",
            "tool_requests": [],
            "field_write_proposals": [],
            "action_proposals": [],
            "workflow_event_proposals": [],
            "handoff_proposal": None,
            "claims": [],
            "confidence": 0.8,
            "needs_retry_reason": None,
        }
    )


class _FlakyCompletions:
    """Raises the queued exceptions first, then returns queued outputs."""

    def __init__(self, errors: list[Exception], outputs: list[str]) -> None:
        self._errors = list(errors)
        self._outputs = list(outputs)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        output = self._outputs.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=output))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def _provider(errors: list[Exception], outputs: list[str], **config) -> tuple:
    completions = _FlakyCompletions(errors, outputs)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = RespondStyleLLMTurnProvider(
        client=client,
        config=RespondStyleLLMTurnProviderConfig(
            backoff_base_seconds=0.001,
            backoff_max_seconds=0.002,
            **config,
        ),
    )
    return provider, completions


def _turn_input() -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="t",
        deployment_id="d",
        agent_id="a",
        agent_version_id="v",
        runtime_mode="test_lab_no_send",
        send_mode="no_send",
        channel="test",
        conversation_id="c",
        inbound_text="hola",
    )


# --- F18 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f18_rate_limit_retries_then_succeeds() -> None:
    provider, completions = _provider(
        [RateLimitError(), RateLimitError()], [_ok_output()]
    )

    decision = await provider.generate(
        turn_input=_turn_input(), context=AgentContextPackage()
    )

    assert decision.final_message == "Hola, te ayudo con gusto."
    assert completions.calls == 3
    assert provider.transient_retry_count == 2
    assert provider.last_transient_error == "RateLimitError"
    # Evidence: counters appear in the decision trace.
    provider_trace = decision.trace_metadata["respond_style_llm_provider"]
    assert provider_trace["transient_retries_total"] == 2
    assert provider_trace["backoff_wait_ms_total"] >= 0


@pytest.mark.asyncio
async def test_f18_retry_after_header_is_honored() -> None:
    provider, _ = _provider([RateLimitError(retry_after="0.005")], [_ok_output()])

    await provider.generate(turn_input=_turn_input(), context=AgentContextPackage())

    assert provider.last_backoff_delays[0] == 0.005


@pytest.mark.asyncio
async def test_f18_budget_exhausted_fails_closed_as_rate_limited() -> None:
    provider, completions = _provider(
        [RateLimitError() for _ in range(5)],
        [],
        max_transient_retries=2,
    )

    decision = await provider.generate(
        turn_input=_turn_input(), context=AgentContextPackage()
    )

    assert decision.send_decision == "no_send"
    assert decision.final_message is None
    assert decision.validation is not None
    assert decision.validation.blocked_reason == "api_rate_limited"
    assert completions.calls == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_f18_non_429_transient_fails_closed_as_transient_failure() -> None:
    provider, _ = _provider(
        [InternalServerError() for _ in range(5)],
        [],
        max_transient_retries=1,
    )

    decision = await provider.generate(
        turn_input=_turn_input(), context=AgentContextPackage()
    )

    assert decision.validation is not None
    assert decision.validation.blocked_reason == "api_transient_failure"


@pytest.mark.asyncio
async def test_f18_schema_errors_are_not_treated_as_transient() -> None:
    # Invalid JSON output: goes through the parse-retry path, not backoff.
    provider, completions = _provider([], ["not-json", _ok_output()])

    decision = await provider.generate(
        turn_input=_turn_input(), context=AgentContextPackage()
    )

    assert decision.final_message == "Hola, te ayudo con gusto."
    assert provider.transient_retry_count == 0
    assert provider.retry_count == 1
    assert completions.calls == 2


# --- F19 -------------------------------------------------------------------


def _context_with_sources() -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={"contact_state": {"selected_option": "standard"}},
        knowledge_bindings=[{"source_id": "kb-price-list"}],
        retrieved_context=[
            {"source_id": "kb-price-list", "excerpt": "prices come from the system"}
        ],
        tool_results=[
            {"tool_name": "quote.resolve", "status": "succeeded"},
            {"tool_name": "requirements.lookup", "status": "succeeded"},
        ],
        field_policies=[{"field_key": "selected_option", "writable": True}],
    )


def _output_with_claim(text: str, basis: str, refs: list[str]) -> LLMAgentTurnOutput:
    return LLMAgentTurnOutput(
        final_message=text,
        claims=[LLMClaim(text=text, basis=basis, source_refs=refs)],
        confidence=0.8,
    )


def test_f19_tool_prefixed_refs_validate_price_and_requirements() -> None:
    validator = RespondStyleTurnValidator()

    price = validator.validate(
        output=_output_with_claim(
            "The price is $120.", "tool_result", ["tool:quote.resolve"]
        ),
        context=_context_with_sources(),
    )
    assert price.send_decision == "send"

    requirements = validator.validate(
        output=_output_with_claim(
            "You need an ID (requirements).",
            "tool_result",
            ["tool:requirements.lookup"],
        ),
        context=_context_with_sources(),
    )
    assert requirements.send_decision == "send"


def test_f19_kb_prefixed_ref_validates() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=_output_with_claim(
            "Prices come from the system.", "knowledge_source", ["kb:kb-price-list"]
        ),
        context=_context_with_sources(),
    )
    assert decision.send_decision == "send"


def test_f19_contact_field_and_transcript_refs_validate() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=_output_with_claim(
            "You chose the standard option.",
            "agent_policy",
            ["contact_field:selected_option", "transcript:latest_customer_message"],
        ),
        context=_context_with_sources(),
    )
    assert decision.send_decision == "send"


def test_f19_invented_source_ref_fails() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=_output_with_claim(
            "The warranty lasts a year.", "knowledge_source", ["kb:made-up-source"]
        ),
        context=_context_with_sources(),
    )
    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    codes = {item.code for item in decision.validation.blocked_items}
    assert "claim_source_ref_not_available" in codes


def test_f19_factual_claim_without_refs_fails() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=_output_with_claim("The warranty lasts a year.", "tool_result", []),
        context=_context_with_sources(),
    )
    assert decision.send_decision == "no_send"
    codes = {item.code for item in decision.validation.blocked_items}
    assert "claim_missing_source_ref" in codes


def test_f19_prompt_explains_source_refs() -> None:
    prompt = respond_style_system_prompt()
    assert "tool:<tool_name>" in prompt
    assert "kb:<source_id>" in prompt
    assert "contact_field:<field_key>" in prompt
    assert "transcript:latest_customer_message" in prompt
    assert "Never invent a source_ref" in prompt


def test_f19_hard_policies_not_relaxed() -> None:
    # Price without ANY support still blocks, prefixes or not.
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(final_message="The price is $120.", confidence=0.8),
        context=AgentContextPackage(),
    )
    assert decision.send_decision == "no_send"
    codes = {item.code for item in decision.validation.blocked_items}
    assert "missing_quote_tool" in codes


# --- F21/F22/F23 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_f21_validator_retry_recovers_from_invalid_json() -> None:
    """A parse failure on the validator-retry call gets ONE corrective
    attempt instead of failing closed."""
    price_violation = json.dumps(
        {
            "turn_kind": "final_response",
            "final_message": "The price is $10,000.",
            "tool_requests": [],
            "field_write_proposals": [],
            "action_proposals": [],
            "workflow_event_proposals": [],
            "handoff_proposal": None,
            "claims": [],
            "confidence": 0.8,
            "needs_retry_reason": None,
        }
    )
    provider, completions = _provider(
        [],
        [price_violation, "truncated{not-json", _ok_output()],
    )

    decision = await provider.generate(
        turn_input=_turn_input(), context=AgentContextPackage()
    )

    assert decision.final_message == "Hola, te ayudo con gusto."
    assert decision.validation is not None
    assert decision.validation.status == "valid"
    assert completions.calls == 3


def test_f22_prompt_forbids_product_identity_fabrication() -> None:
    prompt = respond_style_system_prompt()
    assert "Never add a brand, engine size, year, or spec" in prompt


@pytest.mark.asyncio
async def test_f23_blocked_decisions_carry_raw_output_excerpt() -> None:
    leak = json.dumps(
        {
            "turn_kind": "final_response",
            "final_message": "I checked the trace and the workflow.",
            "tool_requests": [],
            "field_write_proposals": [],
            "action_proposals": [],
            "workflow_event_proposals": [],
            "handoff_proposal": None,
            "claims": [],
            "confidence": 0.8,
            "needs_retry_reason": None,
        }
    )
    provider, _ = _provider([], [leak, leak])

    decision = await provider.generate(
        turn_input=_turn_input(), context=AgentContextPackage()
    )

    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    raw = decision.trace_metadata["respond_style_llm_provider"].get(
        "blocked_raw_output"
    )
    assert raw is not None and "trace" in raw


# --- F24 ---------------------------------------------------------------------


def test_f24_procedural_agent_policy_claims_without_refs_do_not_block() -> None:
    """Exact regression of the r8o c07-t3 false positive: a good procedural
    message blocked because its process statements were declared as
    agent_policy claims with empty refs."""
    output = LLMAgentTurnOutput(
        final_message=(
            "Sí, claro. Para avanzar con el crédito, necesito saber cómo "
            "recibes tus ingresos. ¿Podrías compartir esa información?"
        ),
        claims=[
            LLMClaim(
                text="Para avanzar con el crédito, necesito saber cómo recibes tus ingresos.",
                basis="agent_policy",
                source_refs=[],
            ),
            LLMClaim(
                text="Esto me ayudará a darte la lista exacta de documentos.",
                basis="agent_policy",
                source_refs=[],
            ),
        ],
        confidence=0.8,
    )

    decision = RespondStyleTurnValidator().validate(
        output=output, context=AgentContextPackage()
    )

    assert decision.send_decision == "send"
    assert decision.validation is not None
    assert decision.validation.status == "valid"


def test_f24_agent_policy_claims_with_refs_still_validated() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=_output_with_claim(
            "Our policy applies here.", "agent_policy", ["kb:made-up-source"]
        ),
        context=_context_with_sources(),
    )
    assert decision.send_decision == "no_send"
    codes = {item.code for item in decision.validation.blocked_items}
    assert "claim_source_ref_not_available" in codes


def test_f24_does_not_relax_price_requirements_or_leak_blocks() -> None:
    validator = RespondStyleTurnValidator()

    price = validator.validate(
        output=LLMAgentTurnOutput(
            final_message="El precio es de 32,500 pesos.",
            claims=[
                LLMClaim(text="precio 32,500 pesos", basis="agent_policy", source_refs=[])
            ],
            confidence=0.8,
        ),
        context=AgentContextPackage(),
        attempt_number=2,
    )
    assert price.send_decision == "no_send"
    assert "missing_quote_tool" in price.validation.blocked_reason

    requirements = validator.validate(
        output=LLMAgentTurnOutput(
            final_message="Los requisitos son INE y comprobante.",
            confidence=0.8,
        ),
        context=AgentContextPackage(),
        attempt_number=2,
    )
    assert requirements.send_decision == "no_send"
    assert "missing_requirements_tool" in requirements.validation.blocked_reason

    leak = validator.validate(
        output=LLMAgentTurnOutput(
            final_message="I checked the trace and the workflow.",
            confidence=0.8,
        ),
        context=AgentContextPackage(),
        attempt_number=2,
    )
    assert leak.send_decision == "no_send"
    assert "internal_text_visible" in leak.validation.blocked_reason


def test_f24_prompt_scopes_claims_to_factual_assertions() -> None:
    prompt = respond_style_system_prompt()
    assert "Do not create claims for questions, procedural guidance" in prompt
    assert "factual assertions requiring support" in prompt


# --- F26/F27/D (real-tenant shadow window 1 fixes) ---------------------------


def test_f26_f27_d_prompt_lines_present() -> None:
    prompt = respond_style_system_prompt()
    # F26: corrections must also propose the field write.
    assert "include a" in prompt and "field_write_proposal with the corrected value" in prompt
    # F27: product/model captures must be catalog-grounded.
    assert "matches an id or name present in catalog/tool facts" in prompt
    # D: media inbounds are acknowledged, never answered with unrelated content;
    # with a document.review result, the facts are used instead.
    assert "document.review tool result exists" in prompt
    assert "Never quote prices, list" in prompt

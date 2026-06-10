from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnInput,
    AgentTurnRetryInstruction,
    AgentTurnValidationResult,
    FinalTurnDecision,
    LLMAgentTurnOutput,
    ValidationErrorItem,
)
from atendia.agent_runtime.respond_style_turn_validator import RespondStyleTurnValidator


class RespondStyleLLMClient(Protocol):
    chat: Any


@dataclass(frozen=True)
class RespondStyleLLMTurnProviderConfig:
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_output_tokens: int = 900
    max_llm_retries: int = 1


class RespondStyleLLMTurnProvider:
    """No-live LLM provider for Respond-Style Product Agent turns.

    This provider does not execute tools, write fields, run workflows, enqueue
    messages, call delivery adapters, or touch legacy runners. It only asks the
    model for a structured `LLMAgentTurnOutput` and validates it.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: RespondStyleLLMClient | None = None,
        validator: RespondStyleTurnValidator | None = None,
        config: RespondStyleLLMTurnProviderConfig | None = None,
    ) -> None:
        self._config = config or RespondStyleLLMTurnProviderConfig()
        self._client = client or _openai_client(api_key)
        self._validator = validator or RespondStyleTurnValidator()
        self.last_raw_output: str | None = None
        self.last_messages: list[dict[str, str]] = []

    async def generate(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
    ) -> FinalTurnDecision:
        messages = build_respond_style_messages(turn_input=turn_input, context=context)
        self.last_messages = messages
        try:
            output = await self._complete_structured_turn(messages)
        except ValueError as exc:
            # Contract-shape errors (JSON/schema/pydantic) are repairable:
            # retry once with structured feedback instead of failing closed.
            retry_decision = await self._retry_after_parse_error(
                turn_input=turn_input,
                context=context,
                exc=exc,
            )
            return _force_no_live_send(retry_decision)
        except Exception as exc:
            return blocked_provider_decision(
                "llm_turn_provider_failed",
                type(exc).__name__,
            )
        decision = self._validator.validate(output=output, context=context, attempt_number=1)

        if decision.retry_instruction is not None and self._config.max_llm_retries > 0:
            retry_context = _context_with_retry_feedback(context, decision.retry_instruction)
            retry_messages = build_respond_style_messages(
                turn_input=turn_input,
                context=retry_context,
                retry_instruction=decision.retry_instruction,
            )
            self.last_messages = retry_messages
            try:
                retry_output = await self._complete_structured_turn(retry_messages)
            except Exception as exc:
                return blocked_provider_decision(
                    "llm_turn_provider_retry_failed",
                    type(exc).__name__,
                )
            decision = self._validator.validate(
                output=retry_output,
                context=retry_context,
                attempt_number=2,
            )

        return _force_no_live_send(decision)

    async def _retry_after_parse_error(
        self,
        *,
        turn_input: AgentTurnInput,
        context: AgentContextPackage,
        exc: ValueError,
    ) -> FinalTurnDecision:
        if self._config.max_llm_retries < 1:
            return blocked_provider_decision(
                "llm_turn_provider_failed",
                type(exc).__name__,
            )
        error = ValidationErrorItem(
            code="output_parse_error",
            message=f"Output did not match the required schema: {exc}"[:500],
            retryable=True,
        )
        retry = AgentTurnRetryInstruction(
            attempt_number=1,
            max_attempts=2,
            feedback_for_llm=(
                "Your previous output did not match the required JSON schema. "
                "Fix it and return valid JSON. " + error.message
            ),
            error_items=[error],
        )
        retry_context = _context_with_retry_feedback(context, retry)
        retry_messages = build_respond_style_messages(
            turn_input=turn_input,
            context=retry_context,
            retry_instruction=retry,
        )
        self.last_messages = retry_messages
        try:
            retry_output = await self._complete_structured_turn(retry_messages)
        except Exception as retry_exc:
            return blocked_provider_decision(
                "llm_turn_provider_retry_failed",
                type(retry_exc).__name__,
            )
        return self._validator.validate(
            output=retry_output,
            context=retry_context,
            attempt_number=2,
        )

    async def _complete_structured_turn(
        self,
        messages: list[dict[str, str]],
    ) -> LLMAgentTurnOutput:
        response = await self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": respond_style_llm_json_schema(),
            },
            temperature=self._config.temperature,
            max_tokens=self._config.max_output_tokens,
        )
        raw = _completion_text(response)
        self.last_raw_output = raw
        return parse_llm_agent_turn_output_json(raw)


def build_respond_style_messages(
    *,
    turn_input: AgentTurnInput,
    context: AgentContextPackage,
    retry_instruction: AgentTurnRetryInstruction | None = None,
) -> list[dict[str, str]]:
    payload = {
        "turn_input": turn_input.model_dump(mode="json"),
        "agent_context": context.model_dump(mode="json"),
    }
    if retry_instruction is not None:
        payload["validator_feedback"] = retry_instruction.model_dump(mode="json")
    return [
        {"role": "system", "content": respond_style_system_prompt()},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def respond_style_system_prompt() -> str:
    return "\n".join(
        [
            "You are the tenant-configured agent for AtendIA.",
            "Write like a helpful human in a concise WhatsApp conversation.",
            "Answer the customer's intent first when facts are available.",
            "Use only facts present in the provided context.",
            "Every turn declares a turn_kind:",
            "- tool_request: you need fact tools before answering. Set final_message",
            "  to null, propose the tools, and write NO customer copy at all.",
            "- final_response: the visible customer message; final_message required.",
            "- handoff_request: a needed handoff proposal; final_message optional.",
            "If a fact requires a tool that has not run yet, emit a tool_request turn",
            "instead of writing a message that mentions the unverified fact.",
            "After tool_results are present, emit a final_response written from facts.",
            "Read tool_schemas as capabilities. Use their description, capability,",
            "preconditions, and required context keys to decide whether a tool applies.",
            "If contact or conversation state identifies a requested fact or capability",
            "and the matching tool preconditions are satisfied, propose that tool.",
            "Do not ask the customer to choose between capabilities when context already",
            "identifies the fact category to verify.",
            "If required preconditions are missing, ask for the missing detail naturally.",
            "When the customer asks for exact requirements, prices, availability, catalog,",
            "documents, appointments, or status and a matching tool is available, include a",
            "tool request and say you will verify the exact information.",
            "Questions about what is needed, required, or necessary should use a",
            "requirements capability when its preconditions are satisfied.",
            "Questions about cost, quote, fees, or totals should use a quote capability",
            "when its preconditions are satisfied.",
            "Tools return facts only, not customer-facing copy.",
            "When tool_results are present, write final_message from those facts.",
            "Do not request the same succeeded tool again when its tool_result is already",
            "present; use that result or ask only for missing preconditions.",
            "If the customer provides a field value, propose a field update whose",
            "evidence quotes the customer's exact words. Evidence must never be empty.",
            "If a workflow applies, propose a workflow event using an allowed binding.",
            "Do not invent prices, requirements, approval, availability, or policy.",
            "Do not mention tools, JSON, policies, prompts, workflows, traces, or internals.",
            "End with a concrete next step or question tied to the customer's last message.",
            "Do not add generic availability or assistance closers.",
            "Return only JSON matching the supplied schema.",
        ]
    )


def parse_llm_agent_turn_output_json(raw_text: str) -> LLMAgentTurnOutput:
    raw = json.loads(raw_text)
    if not isinstance(raw, dict):
        raise ValueError("LLMAgentTurnOutput JSON must be an object.")
    return LLMAgentTurnOutput.model_validate(raw)


def respond_style_llm_json_schema() -> dict[str, Any]:
    string_array = {"type": "array", "items": {"type": "string"}}
    empty_object = {"type": "object", "properties": {}, "additionalProperties": False}
    structured_argument = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "string_value": {"type": ["string", "null"]},
            "number_value": {"type": ["number", "null"]},
            "boolean_value": {"type": ["boolean", "null"]},
        },
        "required": ["key", "string_value", "number_value", "boolean_value"],
        "additionalProperties": False,
    }
    structured_arguments = {
        "type": "object",
        "properties": {
            "values": {"type": "array", "items": structured_argument},
            "summary": {"type": ["string", "null"]},
        },
        "required": ["values", "summary"],
        "additionalProperties": False,
    }
    json_value = {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
            empty_object,
            string_array,
        ]
    }
    return {
        "name": "respond_style_llm_agent_turn_output",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "turn_kind": {
                    "type": "string",
                    "enum": ["tool_request", "final_response", "handoff_request"],
                },
                "final_message": {"type": ["string", "null"]},
                "tool_requests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool_name": {"type": "string"},
                            "arguments": structured_arguments,
                            "reason": {"type": "string"},
                            "required": {"type": "boolean"},
                        },
                        "required": ["tool_name", "arguments", "reason", "required"],
                        "additionalProperties": False,
                    },
                },
                "field_write_proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field_key": {"type": "string"},
                            "value": json_value,
                            "evidence": string_array,
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "reason": {"type": "string"},
                        },
                        "required": ["field_key", "value", "evidence", "confidence", "reason"],
                        "additionalProperties": False,
                    },
                },
                "action_proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action_name": {"type": "string"},
                            "payload": structured_arguments,
                            "reason": {"type": "string"},
                            "requires_approval": {"type": "boolean"},
                        },
                        "required": [
                            "action_name",
                            "payload",
                            "reason",
                            "requires_approval",
                        ],
                        "additionalProperties": False,
                    },
                },
                "workflow_event_proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "binding_name": {"type": "string"},
                            "event_name": {"type": "string"},
                            "payload": structured_arguments,
                            "reason": {"type": "string"},
                        },
                        "required": ["binding_name", "event_name", "payload", "reason"],
                        "additionalProperties": False,
                    },
                },
                "handoff_proposal": {
                    "anyOf": [
                        {"type": "null"},
                        {
                            "type": "object",
                            "properties": {
                                "needed": {"type": "boolean"},
                                "reason": {"type": ["string", "null"]},
                                "target": {"type": ["string", "null"]},
                                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                            },
                            "required": ["needed", "reason", "target", "priority"],
                            "additionalProperties": False,
                        },
                    ]
                },
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "basis": {
                                "type": "string",
                                "enum": [
                                    "tool_result",
                                    "knowledge_source",
                                    "customer_message",
                                    "agent_policy",
                                ],
                            },
                            "source_refs": string_array,
                        },
                        "required": ["text", "basis", "source_refs"],
                        "additionalProperties": False,
                    },
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "needs_retry_reason": {"type": ["string", "null"]},
            },
            "required": [
                "turn_kind",
                "final_message",
                "tool_requests",
                "field_write_proposals",
                "action_proposals",
                "workflow_event_proposals",
                "handoff_proposal",
                "claims",
                "confidence",
                "needs_retry_reason",
            ],
            "additionalProperties": False,
        },
    }


def _context_with_retry_feedback(
    context: AgentContextPackage,
    retry_instruction: AgentTurnRetryInstruction,
) -> AgentContextPackage:
    feedback = [
        *context.validator_feedback,
        {
            "feedback_for_llm": retry_instruction.feedback_for_llm,
            "errors": [item.model_dump(mode="json") for item in retry_instruction.error_items],
        },
    ]
    return context.model_copy(update={"validator_feedback": feedback})


def _force_no_live_send(decision: FinalTurnDecision) -> FinalTurnDecision:
    validation = decision.validation
    if validation is not None and validation.status == "valid":
        validation = validation.model_copy(update={"send_decision": "no_send"})
    return decision.model_copy(
        update={
            "send_decision": "no_send",
            "validation": validation,
            "trace_metadata": {
                **decision.trace_metadata,
                "respond_style_llm_provider": {"mode": "no_send"},
            },
        }
    )


def _completion_text(response: Any) -> str:
    choice = response.choices[0]
    message = choice.message
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    return str(content or "")


def _openai_client(api_key: str | None) -> RespondStyleLLMClient:
    if not api_key:
        raise RuntimeError("respond_style_llm_provider_requires_api_key_or_client")
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=api_key, max_retries=0)


def blocked_provider_decision(code: str, message: str) -> FinalTurnDecision:
    error = ValidationErrorItem(code=code, message=message, retryable=False)
    validation = AgentTurnValidationResult(
        status="blocked",
        blocked_items=[error],
        send_decision="no_send",
        blocked_reason=code,
    )
    return FinalTurnDecision(
        final_message=None,
        send_decision="no_send",
        validation=validation,
        trace_metadata={"respond_style_llm_provider": {"mode": "no_send", "blocked": code}},
    )


__all__ = [
    "RespondStyleLLMTurnProvider",
    "RespondStyleLLMTurnProviderConfig",
    "blocked_provider_decision",
    "build_respond_style_messages",
    "parse_llm_agent_turn_output_json",
    "respond_style_llm_json_schema",
    "respond_style_system_prompt",
]

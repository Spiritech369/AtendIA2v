from __future__ import annotations

import asyncio
import json
import random
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
    max_output_tokens: int = 1400
    max_llm_retries: int = 1
    # F18: transient API errors (429/timeouts/5xx) retry with exponential
    # backoff + jitter, honoring Retry-After. Schema/validation errors are
    # NEVER treated as transient.
    max_transient_retries: int = 4
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0


_TRANSIENT_ERROR_NAMES = frozenset(
    {
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "ServiceUnavailableError",
    }
)
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class TransientAPIBudgetExhaustedError(Exception):
    """Raised when transient retries are exhausted; carries a fail-closed
    reason code (api_rate_limited / api_transient_failure)."""

    def __init__(self, reason_code: str, last_error: str) -> None:
        self.reason_code = reason_code
        self.last_error = last_error
        super().__init__(f"{reason_code}: {last_error}")


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
        # Observability counters (cumulative across generate() calls).
        self.llm_calls = 0
        self.retry_count = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        # F18 transient-retry observability.
        self.transient_retry_count = 0
        self.total_backoff_wait_ms = 0
        self.last_transient_error: str | None = None
        self.last_backoff_delays: list[float] = []

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
            return self._finalize(retry_decision)
        except TransientAPIBudgetExhaustedError as exc:
            return self._finalize(
                blocked_provider_decision(exc.reason_code, exc.last_error)
            )
        except Exception as exc:
            return self._finalize(
                blocked_provider_decision(
                    "llm_turn_provider_failed",
                    type(exc).__name__,
                )
            )
        decision = self._validator.validate(output=output, context=context, attempt_number=1)

        if decision.retry_instruction is not None and self._config.max_llm_retries > 0:
            self.retry_count += 1
            retry_context = _context_with_retry_feedback(context, decision.retry_instruction)
            retry_messages = build_respond_style_messages(
                turn_input=turn_input,
                context=retry_context,
                retry_instruction=decision.retry_instruction,
            )
            self.last_messages = retry_messages
            try:
                retry_output = await self._complete_structured_turn_with_parse_recovery(
                    retry_messages
                )
            except TransientAPIBudgetExhaustedError as exc:
                return self._finalize(
                    blocked_provider_decision(exc.reason_code, exc.last_error)
                )
            except Exception as exc:
                return self._finalize(
                    blocked_provider_decision(
                        "llm_turn_provider_retry_failed",
                        type(exc).__name__,
                    )
                )
            decision = self._validator.validate(
                output=retry_output,
                context=retry_context,
                attempt_number=2,
            )

        return self._finalize(decision)

    def _finalize(self, decision: FinalTurnDecision) -> FinalTurnDecision:
        decision = _force_no_live_send(decision)
        meta = dict(decision.trace_metadata)
        provider_meta = dict(meta.get("respond_style_llm_provider") or {})
        provider_meta.update(
            {
                "transient_retries_total": self.transient_retry_count,
                "validator_retries_total": self.retry_count,
                "backoff_wait_ms_total": self.total_backoff_wait_ms,
            }
        )
        if (
            decision.validation is not None
            and decision.validation.status == "blocked"
            and self.last_raw_output
        ):
            provider_meta["blocked_raw_output"] = self.last_raw_output[:1200]
        meta["respond_style_llm_provider"] = provider_meta
        return decision.model_copy(update={"trace_metadata": meta})

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
        self.retry_count += 1
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
            retry_output = await self._complete_structured_turn_with_parse_recovery(
                retry_messages
            )
        except TransientAPIBudgetExhaustedError as retry_exc:
            return blocked_provider_decision(retry_exc.reason_code, retry_exc.last_error)
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

    async def _complete_structured_turn_with_parse_recovery(
        self,
        messages: list[dict[str, str]],
    ) -> LLMAgentTurnOutput:
        """F21: one corrective attempt when the model returns invalid JSON
        (e.g. truncation under load). Raises on the second failure."""
        try:
            return await self._complete_structured_turn(messages)
        except ValueError:
            self.retry_count += 1
            corrective = [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "Your previous output was not valid JSON for the required "
                        "schema. Return ONLY a complete, valid JSON object. Keep "
                        "final_message short."
                    ),
                },
            ]
            return await self._complete_structured_turn(corrective)

    async def _complete_structured_turn(
        self,
        messages: list[dict[str, str]],
    ) -> LLMAgentTurnOutput:
        response = await self._create_with_transient_retry(messages)
        self.llm_calls += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.total_prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.total_completion_tokens += (
                getattr(usage, "completion_tokens", 0) or 0
            )
        raw = _completion_text(response)
        self.last_raw_output = raw
        return parse_llm_agent_turn_output_json(raw)

    async def _create_with_transient_retry(self, messages: list[dict[str, str]]) -> Any:
        """F18: retries ONLY transient API errors (429/timeouts/5xx) with
        exponential backoff + jitter, honoring Retry-After. Never retries
        schema/validation errors; exhaustion raises a fail-closed sentinel."""
        attempt = 0
        while True:
            try:
                return await self._client.chat.completions.create(
                    model=self._config.model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": respond_style_llm_json_schema(),
                    },
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_output_tokens,
                )
            except Exception as exc:
                if not _is_transient_api_error(exc):
                    raise
                error_name = type(exc).__name__
                self.last_transient_error = error_name
                if attempt >= self._config.max_transient_retries:
                    reason = (
                        "api_rate_limited"
                        if _is_rate_limit_error(exc)
                        else "api_transient_failure"
                    )
                    raise TransientAPIBudgetExhaustedError(reason, error_name) from exc
                delay = _retry_after_seconds(exc)
                if delay is None:
                    delay = min(
                        self._config.backoff_base_seconds * (2**attempt),
                        self._config.backoff_max_seconds,
                    ) * (0.5 + random.random())
                self.transient_retry_count += 1
                self.last_backoff_delays.append(round(delay, 4))
                self.total_backoff_wait_ms += int(delay * 1000)
                await asyncio.sleep(delay)
                attempt += 1


def _is_transient_api_error(exc: Exception) -> bool:
    if isinstance(exc, ValueError):
        return False
    if type(exc).__name__ in _TRANSIENT_ERROR_NAMES:
        return True
    status = getattr(exc, "status_code", None)
    return status in _TRANSIENT_STATUS_CODES


def _is_rate_limit_error(exc: Exception) -> bool:
    return (
        type(exc).__name__ == "RateLimitError"
        or getattr(exc, "status_code", None) == 429
    )


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return None


def build_respond_style_messages(
    *,
    turn_input: AgentTurnInput,
    context: AgentContextPackage,
    retry_instruction: AgentTurnRetryInstruction | None = None,
) -> list[dict[str, str]]:
    """Structured prompt rendering (F10).

    Instead of one JSON blob, the model receives: a system message with the
    platform contract + the tenant's agent configuration + capabilities, the
    recent transcript as REAL chat turns, a system message with the current
    dynamic context (state, knowledge, tool results, feedback), and the
    inbound text as the final user message.
    """
    system_content = "\n".join(
        [
            respond_style_system_prompt(),
            "",
            _render_agent_section(context),
            _render_capabilities_section(context),
            _render_fields_section(context),
        ]
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(_transcript_messages(turn_input))
    dynamic = _render_dynamic_context(
        turn_input=turn_input,
        context=context,
        retry_instruction=retry_instruction,
    )
    if dynamic:
        messages.append({"role": "system", "content": dynamic})
    messages.append({"role": "user", "content": turn_input.inbound_text})
    return messages


def _transcript_messages(turn_input: AgentTurnInput) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    for item in turn_input.recent_messages:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        role = str(item.get("role") or "")
        if role == "customer":
            rendered.append({"role": "user", "content": text})
        elif role == "assistant":
            rendered.append({"role": "assistant", "content": text})
    return rendered


def _render_agent_section(context: AgentContextPackage) -> str:
    identity = context.agent_identity
    lines = ["## Agent configuration"]
    for label, key in (
        ("Name", "name"),
        ("Persona", "persona"),
        ("Language", "language"),
        ("Tone", "tone"),
    ):
        value = identity.get(key)
        if value:
            lines.append(f"{label}: {value}")
    if context.instructions:
        lines.append(f"Instructions: {context.instructions}")
    goals = identity.get("goals") or []
    if goals:
        lines.append("Goals: " + "; ".join(str(item) for item in goals))
    do_not_do = identity.get("do_not_do") or []
    if do_not_do:
        lines.append("Never do: " + "; ".join(str(item) for item in do_not_do))
    return "\n".join(lines)


def _render_capabilities_section(context: AgentContextPackage) -> str:
    lines = ["", "## Tools (capabilities — facts only, never customer copy)"]
    if not context.tool_schemas:
        lines.append("(none configured)")
    for schema in context.tool_schemas:
        if not isinstance(schema, dict):
            continue
        name = schema.get("tool_name") or schema.get("name")
        description = schema.get("description") or ""
        preconditions = schema.get("preconditions") or []
        line = f"- {name}: {description}"
        if preconditions:
            line += f" (preconditions: {', '.join(str(p) for p in preconditions)})"
        lines.append(line)
    if context.workflow_trigger_schemas:
        lines.append("")
        lines.append(
            "## Workflow events you may propose "
            "(use ONLY these exact binding_name values; never invent one)"
        )
        for schema in context.workflow_trigger_schemas:
            if isinstance(schema, dict):
                lines.append(
                    f"- binding_name={schema.get('binding_name')} "
                    f"event_name={schema.get('event_name')}"
                )
    handoff = context.handoff_policy
    if handoff.get("enabled"):
        targets = [str(t) for t in handoff.get("targets") or []]
        target_text = (
            "target must be EXACTLY one of: " + ", ".join(targets)
            if targets
            else "any team"
        )
        lines.append("")
        lines.append(
            f"## Handoff ({target_text}). When the customer asks for a "
            "human, use handoff_proposal (NOT a workflow event) and include a "
            "short visible message telling them you are connecting them."
        )
    return "\n".join(lines)


def _render_fields_section(context: AgentContextPackage) -> str:
    if not context.field_policies:
        return ""
    lines = [
        "",
        "## Contact fields (opportunistic capture only — never an agenda)",
    ]
    for policy in context.field_policies:
        if not isinstance(policy, dict):
            continue
        key = policy.get("field_key")
        label = policy.get("label") or key
        writable = "writable" if policy.get("writable", True) else "read-only"
        allowed = policy.get("allowed_values")
        if isinstance(allowed, list) and allowed:
            values = ", ".join(str(item) for item in allowed)
            lines.append(
                f"- {key} ({label}, {writable}; ONLY these values are "
                f"accepted: {values})"
            )
        else:
            lines.append(f"- {key} ({label}, {writable})")
    return "\n".join(lines)


def _render_dynamic_context(
    *,
    turn_input: AgentTurnInput,
    context: AgentContextPackage,
    retry_instruction: AgentTurnRetryInstruction | None,
) -> str:
    sections: list[str] = []
    identity = context.agent_identity
    known = identity.get("contact_state") or {}
    corrected = identity.get("corrected_fields") or {}
    if known:
        known_lines = [
            "## CURRENT contact state (canonical — overrides anything older in "
            "the transcript; do NOT ask for these again)"
        ]
        for key, value in known.items():
            if key in corrected:
                known_lines.append(
                    f"- {key}: {value} (CORRECTED by the customer — replaces the "
                    f"older value '{corrected[key]}' still visible in the "
                    "transcript; never restate the old value)"
                )
            else:
                known_lines.append(f"- {key}: {value}")
        sections.append("\n".join(known_lines))
    missing = identity.get("missing_fields") or []
    if missing:
        sections.append(
            "## Not yet known (capture opportunistically, never as a form): "
            + ", ".join(str(item) for item in missing)
        )
    if context.retrieved_context:
        kb_lines = ["## Knowledge (citable with source_id)"]
        for snippet in context.retrieved_context:
            if isinstance(snippet, dict):
                kb_lines.append(
                    f"- [{snippet.get('source_id')}] {snippet.get('excerpt')}"
                )
        sections.append("\n".join(kb_lines))
    if context.tool_results:
        tool_lines = [
            "## Tool results from THIS turn (verified facts — write your "
            "final_response from these; do not request these tools again)"
        ]
        for result in context.tool_results:
            if isinstance(result, dict):
                tool_lines.append(
                    f"- {result.get('tool_name')} [{result.get('status')}]: "
                    + json.dumps(result.get("facts") or {}, ensure_ascii=False)
                )
        sections.append("\n".join(tool_lines))
    feedback_items = list(context.validator_feedback)
    if retry_instruction is not None:
        feedback_items.append(
            {
                "feedback_for_llm": retry_instruction.feedback_for_llm,
                "errors": [
                    item.model_dump(mode="json")
                    for item in retry_instruction.error_items
                ],
            }
        )
    if feedback_items:
        feedback_lines = ["## IMPORTANT FEEDBACK — follow this before anything else"]
        for item in feedback_items:
            if not isinstance(item, dict):
                continue
            if item.get("feedback_for_llm"):
                feedback_lines.append(f"- {item['feedback_for_llm']}")
            for error in item.get("errors") or []:
                if isinstance(error, dict) and error.get("code"):
                    feedback_lines.append(
                        f"  (error {error['code']}: {error.get('message', '')})"
                    )
        sections.append("\n".join(feedback_lines))
    return "\n\n".join(sections)


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
            "Known and missing fields describe contact state for your awareness only;",
            "they are never an agenda and never a questionnaire.",
            "Capture field values opportunistically when the customer states them.",
            "If the customer provides a field value, propose a field update whose",
            "evidence quotes the customer's exact words. Evidence must never be empty.",
            "Field values you propose in this turn count as known facts for tool",
            "preconditions in this same turn.",
            "Prefer answering the customer's intent and using satisfiable tools over",
            "collecting fields. Ask for a missing field only when it blocks the",
            "immediate next step, and ask for at most one detail at a time.",
            "If a workflow applies, propose a workflow event using an allowed binding.",
            "Do not invent prices, requirements, approval, availability, or policy.",
            "Describe products using ONLY attributes present in catalog or tool",
            "facts. Never add a brand, engine size, year, or spec that is not in",
            "those facts.",
            "Every factual claim you state must carry source_refs in one of these",
            "exact forms: tool:<tool_name> (a succeeded tool_result from this turn),",
            "kb:<source_id> (a knowledge snippet shown to you),",
            "contact_field:<field_key> (a known contact value),",
            "transcript:latest_customer_message (what the customer just said).",
            "Never invent a source_ref. If you cannot cite a valid one, do not",
            "state the fact: request the tool or ask for the missing detail instead.",
            "Do not create claims for questions, procedural guidance, conversational",
            "transitions, acknowledgements, or next-step prompts. Only create claims",
            "for factual assertions requiring support.",
            "If the customer corrects a previously given value, the correction wins:",
            "propose the corrected value and never restate the old one.",
            "A correction is not just words: in the SAME turn, include a",
            "field_write_proposal with the corrected value so state is updated.",
            "A corrected field value must be ONLY the clean new value (one of",
            "the accepted values when the field lists them) — never a blend of",
            "old and new like 'old (new)'.",
            "Only capture a product/model selection as a field when the value",
            "matches an id or name present in catalog/tool facts. If the customer",
            "names a product you cannot find there, say so honestly and do NOT",
            "propose that field write.",
            "If the inbound is media you cannot view — an image, audio, video,",
            "document, or a placeholder like '[imagen]' or a file name —",
            "acknowledge you received it, say you cannot view it, and ask what",
            "it shows or which product it refers to. Do NOT quote prices, list",
            "products, or guess content in response to media. This applies even",
            "when the message is ONLY the placeholder.",
            "The CURRENT contact state is the single source of truth OVER THE",
            "TRANSCRIPT: when an older transcript message conflicts with a",
            "current contact value, use the current value, never the outdated one.",
            "EXCEPTION — the customer's LATEST message outranks stored state:",
            "if it contradicts a known value, treat it as a correction to",
            "capture (or ask ONE short clarifying question). Never assert a",
            "stored value against what the customer just said.",
            "When the customer asks for information, give information or qualify",
            "naturally. Offer a human as an OPTION only; propose handoff as the",
            "answer ONLY when the customer asks for a person, or policy requires",
            "it. Earlier handoffs in the transcript do not make handoff the",
            "default for new questions.",
            "Never ask for a value the customer already provided in this conversation.",
            "Answer direct questions about you (for example whether you are a bot)",
            "first and honestly, using the configured knowledge, then continue.",
            "Never repeat your previous message verbatim. If the customer repeats or",
            "stalls, rephrase and move one concrete step forward.",
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

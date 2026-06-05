from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from atendia.agent_runtime.conversation_progress import (
    ConversationProgressGuard,
    normalize_composer_progress,
    output_from_progress_result,
)
from atendia.agent_runtime.field_update_reconciler import reconcile_field_updates
from atendia.agent_runtime.handoff_resolver import resolve_handoff
from atendia.agent_runtime.policy_validator import PolicyValidator
from atendia.agent_runtime.provider_reliability import (
    ProviderEmptyResponseError,
    ProviderMalformedJSONError,
    ProviderReliabilityConfig,
    ProviderReliabilityLayer,
    ProviderRetryExhaustedError,
    ProviderSchemaParseError,
)
from atendia.agent_runtime.quote_safety import QuoteSafetyGuard
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    KnowledgeCitation,
    TurnContext,
    TurnOutput,
)
from atendia.agent_runtime.structured_reconciler import (
    parse_turn_output_lenient,
    reconcile_structured_output,
)
from atendia.agent_runtime.tracing import build_trace_metadata
from atendia.agent_runtime.voice import (
    resolve_effective_voice_guide,
    voice_guide_to_prompt_lines,
)
from atendia.config import Settings, get_settings
from atendia.runner._openai_errors import _NON_RETRIABLE, _RETRIABLE

TurnOutputDraft = TurnOutput
_MODEL_PARSE_ERRORS = (json.JSONDecodeError, ValidationError, ValueError)
_MODEL_NON_RETRIABLE = (*_NON_RETRIABLE, *_MODEL_PARSE_ERRORS)
_MODEL_RETRIABLE = (*_RETRIABLE, asyncio.TimeoutError, TimeoutError)
_MAX_PROVIDER_HISTORY_MESSAGES = 6
_MAX_PROVIDER_KNOWLEDGE_CITATIONS = 5
_MAX_PROVIDER_SNIPPET_CHARS = 700
_SAFE_CITATION_METADATA_KEYS = {
    "category",
    "content_type",
    "document_type",
    "source_name",
    "source_type",
}
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")


class AgentModelProvider(Protocol):
    async def generate_turn(
        self,
        context: TurnContext,
        agent_config: ActiveAgentContext | None = None,
        evidence_pack: Any | None = None,
    ) -> TurnOutputDraft: ...


class MockAgentProvider:
    def __init__(self, output: TurnOutput | dict[str, Any] | None = None) -> None:
        self._output = output

    async def generate(self, context: TurnContext) -> TurnOutput:
        return await self.generate_turn(context)

    async def generate_turn(
        self,
        context: TurnContext,
        agent_config: ActiveAgentContext | None = None,
        evidence_pack: Any | None = None,
    ) -> TurnOutputDraft:
        del agent_config, evidence_pack
        if self._output is None:
            return TurnOutput(
                final_message="Recibido. Te ayudo con eso.",
                confidence=0.8,
                knowledge_citations=context.knowledge_citations,
                trace_metadata=build_trace_metadata(
                    context=context,
                    provider="mock_agent_provider",
                ),
            )
        output = (
            self._output
            if isinstance(self._output, TurnOutput)
            else TurnOutput.model_validate(self._output)
        )
        return output.model_copy(
            update={
                "knowledge_citations": output.knowledge_citations
                or context.knowledge_citations,
                "trace_metadata": {
                    **output.trace_metadata,
                    **build_trace_metadata(context=context, provider="mock_agent_provider"),
                },
            }
        )


class SafeFallbackAgentProvider:
    def __init__(self, *, reason: str = "agent_model_provider_unavailable") -> None:
        self._reason = reason

    async def generate(self, context: TurnContext) -> TurnOutput:
        return await self.generate_turn(context)

    async def generate_turn(
        self,
        context: TurnContext,
        agent_config: ActiveAgentContext | None = None,
        evidence_pack: Any | None = None,
    ) -> TurnOutputDraft:
        del agent_config, evidence_pack
        return _safe_fallback_output(context, reason=self._reason)


class OpenAIAgentProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout_s: float = 8.0,
        retry_delays_ms: Sequence[int] = (500, 2000),
        max_retries: int | None = None,
        retry_base_delay_ms: int | None = None,
        retry_max_delay_ms: int = 4000,
        retry_jitter_ms: int = 250,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_s: float = 30.0,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._client = client
        self._model = model
        delays = tuple(retry_delays_ms)
        self._reliability_config = ProviderReliabilityConfig(
            max_retries=len(delays) if max_retries is None else max_retries,
            timeout_s=timeout_s,
            base_delay_ms=(
                int(delays[0]) if retry_base_delay_ms is None and delays else retry_base_delay_ms or 0
            ),
            max_delay_ms=retry_max_delay_ms,
            jitter_ms=retry_jitter_ms,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_cooldown_s=circuit_cooldown_s,
            retry_output_parse_failures=False,
        )

    async def generate(self, context: TurnContext) -> TurnOutput:
        return await self.generate_turn(context, context.active_agent, None)

    async def generate_turn(
        self,
        context: TurnContext,
        agent_config: ActiveAgentContext | None = None,
        evidence_pack: Any | None = None,
    ) -> TurnOutputDraft:
        del evidence_pack
        messages = build_agent_turn_messages(context, agent_config or context.active_agent)
        json_schema = turn_output_json_schema()
        t0 = time.perf_counter()
        reliability = ProviderReliabilityLayer(
            provider="openai",
            model=self._model,
            tenant_id=context.tenant_id,
            config=self._reliability_config,
        )

        try:
            output = await reliability.execute(
                lambda: self._generate_once(context, messages, json_schema),
                operation_name="agent_runtime_turn",
                idempotency_key=_provider_idempotency_key(context),
            )
            normalized = _normalize_model_output(
                context,
                output,
                provider="openai",
                model=self._model,
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
            normalized.trace_metadata["provider_reliability"] = reliability.snapshot().to_dict()
            return normalized
        except (
            _MODEL_RETRIABLE + _MODEL_NON_RETRIABLE + (ProviderRetryExhaustedError,)
        ) as exc:
            last_exc = exc
        except Exception as exc:
            last_exc = exc

        reliability.record_fallback_response()
        return _safe_fallback_output(
            context,
            reason="agent_model_provider_failed",
            error_type=_provider_error_type(last_exc),
            provider="openai",
            model=self._model,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            extra_metadata={"provider_reliability": reliability.snapshot().to_dict()},
        )

    async def _generate_once(
        self,
        context: TurnContext,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
    ) -> TurnOutput:
        del context
        raw_text = await self._complete_json(messages, json_schema)
        if not raw_text.strip():
            raise ProviderEmptyResponseError("empty agent provider response")
        try:
            return parse_turn_output_json(raw_text, lenient=True)
        except json.JSONDecodeError as exc:
            try:
                repaired = await self._repair_json(raw_text, json_schema)
                if not repaired.strip():
                    raise ProviderEmptyResponseError("empty repaired agent provider response")
                return parse_turn_output_json(repaired, lenient=True)
            except json.JSONDecodeError as repair_exc:
                raise ProviderMalformedJSONError("malformed agent provider JSON") from repair_exc
            except _MODEL_PARSE_ERRORS as repair_exc:
                raise ProviderSchemaParseError("agent provider schema parse failed") from repair_exc
            except _MODEL_RETRIABLE:
                raise
            except Exception as repair_exc:
                raise ProviderSchemaParseError("agent provider repair failed") from repair_exc
        except _MODEL_PARSE_ERRORS as exc:
            raise ProviderSchemaParseError("agent provider schema parse failed") from exc

    async def _complete_json(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
    ) -> str:
        response = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=self._model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0,
        )
        return response.choices[0].message.content or ""

    async def _repair_json(self, raw_text: str, json_schema: dict[str, Any]) -> str:
        response = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON matching the AgentRuntime TurnOutput "
                        "schema. Do not add prose."
                    ),
                },
                {"role": "user", "content": raw_text},
            ],
            response_format={"type": "json_schema", "json_schema": json_schema},
            temperature=0,
        )
        return response.choices[0].message.content or ""


def build_agent_turn_provider(
    settings: Settings | None = None,
    *,
    model_provider_allowed: bool | None = None,
) -> Any:
    resolved = settings or get_settings()
    if (
        model_provider_allowed is False
        or not resolved.agent_runtime_v2_enabled
        or resolved.agent_runtime_v2_model_provider == "disabled"
    ):
        return MockAgentProvider()
    if resolved.agent_runtime_v2_model_provider == "openai":
        if not resolved.openai_api_key:
            return SafeFallbackAgentProvider(reason="openai_api_key_missing")
        return OpenAIAgentProvider(
            api_key=resolved.openai_api_key,
            model=resolved.agent_runtime_v2_model,
            timeout_s=resolved.agent_runtime_v2_model_timeout_s,
            retry_delays_ms=tuple(resolved.agent_runtime_v2_model_retry_delays_ms),
            max_retries=resolved.agent_runtime_v2_model_max_retries,
            retry_base_delay_ms=resolved.agent_runtime_v2_model_retry_base_delay_ms,
            retry_max_delay_ms=resolved.agent_runtime_v2_model_retry_max_delay_ms,
            retry_jitter_ms=resolved.agent_runtime_v2_model_retry_jitter_ms,
            circuit_failure_threshold=resolved.agent_runtime_v2_provider_circuit_failure_threshold,
            circuit_cooldown_s=resolved.agent_runtime_v2_provider_circuit_cooldown_s,
        )
    return SafeFallbackAgentProvider(reason="unsupported_agent_model_provider")


def agent_model_provider_enabled(
    settings: Settings | None = None,
    *,
    model_provider_allowed: bool | None = None,
) -> bool:
    resolved = settings or get_settings()
    return bool(
        model_provider_allowed is not False
        and resolved.agent_runtime_v2_enabled
        and resolved.agent_runtime_v2_model_provider != "disabled"
    )


def build_agent_turn_messages(
    context: TurnContext,
    agent_config: ActiveAgentContext | None = None,
) -> list[dict[str, str]]:
    agent = agent_config or context.active_agent
    return [
        {"role": "system", "content": build_base_system_prompt(agent, context.tenant_config)},
        {"role": "user", "content": build_turn_prompt(context)},
    ]


def build_base_system_prompt(
    agent: ActiveAgentContext | None = None,
    tenant_config: Any | None = None,
) -> str:
    instructions = (agent.instructions if agent else None) or "Help the customer clearly."
    tone = (agent.tone if agent else None) or "natural, concise, and respectful"
    enabled_actions = ", ".join(agent.enabled_action_ids or []) if agent else ""
    voice_guide, voice_source = resolve_effective_voice_guide(
        agent_voice=agent.voice if agent else {},
        tenant_default_voice=getattr(tenant_config, "default_voice", {}) if tenant_config else {},
    )
    voice_lines = voice_guide_to_prompt_lines(voice_guide)
    voice_section = (
        ["Voice guide source: none"]
        if not voice_lines
        else [f"Voice guide source: {voice_source}", "Voice guide:", *voice_lines]
    )
    return "\n".join(
        [
            "You are the AgentRuntime v2 model provider for AtendIA.",
            "Act as an advisor brain plus composer, not as an intent router.",
            "Return only JSON compatible with the TurnOutput contract.",
            "First understand context, memory, customer goal, pending question, lifecycle, "
            "tenant rules, tool facts, and knowledge before drafting final_message.",
            "Answer the customer's current question first.",
            "Use tenant_config, tool results, quote snapshots, and Knowledge citations as "
            "the source of truth.",
            "Do not invent prices, schedules, policies, availability, requirements, or documents.",
            "Do not calculate quotes in free text. If a valid quote snapshot is missing, "
            "ask for the missing fact or request an enabled action/tool.",
            "Ask at most one question.",
            "Do not sound like a form. Be natural and business-appropriate.",
            "Never route by one rigid intent; a message can carry multiple conversation goals.",
            "Propose field_updates, actions, or lifecycle_update only with explicit evidence.",
            "Use only visible_contact_field_keys for field_updates.",
            "Use only allowed_lifecycle_stage_ids for lifecycle_update.target_stage.",
            "Use only enabled actions. If assign_conversation is not enabled, set needs_human "
            "without an action.",
            "For human handoff, do not invent a lifecycle stage. Use needs_human or a valid "
            "assign_conversation action only.",
            "For short replies like si, esa, ok, or manana, use conversation_history. If context "
            "is insufficient, ask one brief clarification.",
            "Escalate with needs_human=true when confidence is low, risk is high, "
            "the customer asks for a human, or knowledge is missing.",
            "Never place customer-visible text inside actions or action payloads.",
            f"Agent instructions: {instructions}",
            f"Tone: {tone}",
            *voice_section,
            f"Enabled actions: {enabled_actions or 'none listed'}",
        ]
    )


def build_turn_prompt(context: TurnContext) -> str:
    return json.dumps(build_minimized_turn_payload(context), ensure_ascii=False)


def _provider_idempotency_key(context: TurnContext) -> str:
    message_id = context.metadata.get("message_id") or context.metadata.get("inbound_message_id")
    turn_id = context.metadata.get("turn_id")
    parts = [
        str(context.tenant_id),
        str(context.conversation_id),
        str(turn_id or context.metadata.get("turn_number") or "turn"),
        str(message_id or context.inbound_text),
    ]
    serialized = "|".join(parts)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _provider_error_type(exc: BaseException | None) -> str:
    if exc is None:
        return "Unknown"
    if isinstance(exc, ProviderRetryExhaustedError) and exc.last_error is not None:
        return type(exc.last_error).__name__
    return type(exc).__name__


def build_minimized_turn_payload(context: TurnContext) -> dict[str, Any]:
    history = [
        {"role": message.role, "text": _redact_pii(message.text)}
        for message in context.messages[-_MAX_PROVIDER_HISTORY_MESSAGES:]
    ]
    citations = [
        {
            "source_id": citation.source_id,
            "title": citation.title,
            "snippet": _truncate_text(_redact_pii(citation.snippet)),
            "score": citation.score,
            "metadata": _safe_citation_metadata(citation.metadata),
        }
        for citation in context.knowledge_citations[:_MAX_PROVIDER_KNOWLEDGE_CITATIONS]
    ]
    payload = {
        "tenant_id": context.tenant_id,
        "conversation_id": context.conversation_id,
        "customer_message": _redact_pii(context.inbound_text),
        "conversation_history": history,
        "contact_fields": {},
        "lifecycle": {
            "stage": context.lifecycle.stage,
            "status": context.lifecycle.status,
            "pipeline_id": context.lifecycle.pipeline_id,
        },
        "memory": _safe_memory_payload(context),
        "tenant_config": _safe_tenant_config_payload(context),
        "knowledge_citations": citations,
        "available_contact_fields": [
            {
                "key": field.key,
                "label": field.label,
                "field_type": field.field_type,
                "options": field.options,
            }
            for field in context.contact_fields
        ],
        "agent": _safe_agent_payload(context.active_agent),
    }
    payload["payload_minimization"] = _payload_minimization_summary(payload)
    return payload


def _safe_memory_payload(context: TurnContext) -> dict[str, Any]:
    memory = context.memory
    return {
        "conversation_summary": _truncate_text(_redact_pii(memory.summary)),
        "salient_facts": _safe_json_scalars(memory.salient_facts),
        "last_quote_snapshot": _safe_json_scalars(memory.last_quote_snapshot or {}),
        "last_pending_question": _truncate_text(_redact_pii(memory.last_pending_question)),
        "documents": _safe_json_scalars(memory.documents),
    }


def _safe_tenant_config_payload(context: TurnContext) -> dict[str, Any]:
    config = context.tenant_config
    return {
        "ruleset": _safe_json_scalars(config.ruleset),
        "tools": _safe_json_scalars(config.tools),
        "default_voice": _safe_json_scalars(config.default_voice),
        "knowledge_sources": list(config.knowledge_sources),
    }


def _safe_json_scalars(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return None
    if isinstance(value, dict):
        return {
            str(key): _safe_json_scalars(nested, depth=depth + 1)
            for key, nested in value.items()
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_safe_json_scalars(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return _truncate_text(_redact_pii(value))
    if isinstance(value, int | float | bool) or value is None:
        return value
    return str(value)


def _redact_pii(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = _EMAIL_RE.sub("[redacted_email]", value)
    return _PHONE_RE.sub("[redacted_phone]", redacted)


def _truncate_text(value: str | None) -> str | None:
    if value is None or len(value) <= _MAX_PROVIDER_SNIPPET_CHARS:
        return value
    return value[: _MAX_PROVIDER_SNIPPET_CHARS - 3].rstrip() + "..."


def _safe_citation_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in _SAFE_CITATION_METADATA_KEYS
        and isinstance(value, str | int | float | bool | type(None))
    }


def _safe_agent_payload(agent: ActiveAgentContext | None) -> dict[str, Any] | None:
    if agent is None:
        return None
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "behavior_mode": agent.behavior_mode,
        "instructions": agent.instructions,
        "tone": agent.tone,
        "voice": _safe_json_scalars(agent.voice),
        "language_policy": agent.language_policy,
        "enabled_action_ids": agent.enabled_action_ids or [],
        "visible_contact_field_keys": agent.visible_contact_field_keys or [],
        "allowed_lifecycle_stage_ids": agent.allowed_lifecycle_stage_ids or [],
        "escalation_policy": agent.escalation_policy,
    }


def _payload_minimization_summary(payload: dict[str, Any]) -> dict[str, Any]:
    citations = payload.get("knowledge_citations") or []
    serializable = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "payload_hash_sha256": hashlib.sha256(serializable.encode("utf-8")).hexdigest(),
        "history_message_count": len(payload.get("conversation_history") or []),
        "knowledge_citation_count": len(citations),
        "knowledge_snippet_chars": sum(
            len(str(citation.get("snippet") or ""))
            for citation in citations
            if isinstance(citation, dict)
        ),
        "contact_field_values_included": False,
        "attachments_included": False,
        "redaction": "email_and_phone_like_tokens",
        "limits": {
            "history_messages": _MAX_PROVIDER_HISTORY_MESSAGES,
            "knowledge_citations": _MAX_PROVIDER_KNOWLEDGE_CITATIONS,
            "snippet_chars": _MAX_PROVIDER_SNIPPET_CHARS,
        },
    }


def parse_turn_output_json(raw_text: str, *, lenient: bool = False) -> TurnOutput:
    raw = json.loads(raw_text)
    if not isinstance(raw, dict):
        raise ValueError("TurnOutput JSON must be an object.")
    if lenient:
        return parse_turn_output_lenient(raw)
    return TurnOutput.model_validate(raw)


def turn_output_json_schema() -> dict[str, Any]:
    json_dict_schema = {"type": "object"}
    return {
        "name": "agent_runtime_turn_output",
        "strict": False,
        "schema": {
            "type": "object",
            "properties": {
                "final_message": {"type": "string"},
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "payload": json_dict_schema,
                            "reason": {"type": ["string", "null"]},
                            "evidence": {"type": "array", "items": {"type": "string"}},
                            "requires_approval": {"type": "boolean"},
                            "idempotency_key": {"type": ["string", "null"]},
                            "metadata": json_dict_schema,
                        },
                        "required": [
                            "name",
                            "payload",
                            "reason",
                            "evidence",
                            "requires_approval",
                            "idempotency_key",
                            "metadata",
                        ],
                        "additionalProperties": False,
                    },
                },
                "field_updates": {"type": "array", "items": _field_update_schema(json_dict_schema)},
                "lifecycle_update": {
                    "anyOf": [{"type": "null"}, _lifecycle_update_schema(json_dict_schema)]
                },
                "knowledge_citations": {
                    "type": "array",
                    "items": _knowledge_citation_schema(json_dict_schema),
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "needs_human": {"type": "boolean"},
                "risk_flags": {"type": "array", "items": {"type": "string"}},
                "trace_metadata": json_dict_schema,
            },
            "required": [
                "final_message",
                "actions",
                "field_updates",
                "lifecycle_update",
                "knowledge_citations",
                "confidence",
                "needs_human",
                "risk_flags",
                "trace_metadata",
            ],
            "additionalProperties": False,
        },
    }


def _field_update_schema(json_dict_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "field_key": {"type": "string"},
            "value": {},
            "reason": {"type": ["string", "null"]},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": ["number", "null"]},
            "source": {"type": "string"},
            "evidence_message_id": {"type": ["string", "null"]},
            "evidence_attachment_id": {"type": ["string", "null"]},
            "trace_id": {"type": ["string", "null"]},
            "metadata": json_dict_schema,
        },
        "required": [
            "field_key",
            "value",
            "reason",
            "evidence",
            "confidence",
            "source",
            "evidence_message_id",
            "evidence_attachment_id",
            "trace_id",
            "metadata",
        ],
        "additionalProperties": False,
    }


def _lifecycle_update_schema(json_dict_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "target_stage": {"type": ["string", "null"]},
            "target_status": {"type": ["string", "null"]},
            "reason": {"type": ["string", "null"]},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": ["number", "null"]},
            "source": {"type": "string"},
            "trace_id": {"type": ["string", "null"]},
            "metadata": json_dict_schema,
        },
        "required": [
            "target_stage",
            "target_status",
            "reason",
            "evidence",
            "confidence",
            "source",
            "trace_id",
            "metadata",
        ],
        "additionalProperties": False,
    }


def _knowledge_citation_schema(json_dict_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
            "title": {"type": ["string", "null"]},
            "snippet": {"type": ["string", "null"]},
            "score": {"type": ["number", "null"]},
            "metadata": json_dict_schema,
        },
        "required": ["source_id", "title", "snippet", "score", "metadata"],
        "additionalProperties": False,
    }


def _normalize_model_output(
    context: TurnContext,
    output: TurnOutput,
    *,
    provider: str,
    model: str,
    latency_ms: int,
) -> TurnOutput:
    output = reconcile_structured_output(context, output)
    output = reconcile_field_updates(context, output)
    output = resolve_handoff(context, output)
    citations_missing_when_available = bool(
        context.knowledge_citations and not output.knowledge_citations
    )
    citations = output.knowledge_citations or context.knowledge_citations
    risk_flags = list(output.risk_flags)
    needs_human = output.needs_human
    if output.confidence < 0.5:
        needs_human = True
        if "low_confidence" not in risk_flags:
            risk_flags.append("low_confidence")
    if citations_missing_when_available:
        needs_human = True
        if "missing_required_citations" not in risk_flags:
            risk_flags.append("missing_required_citations")
    normalized = output.model_copy(
        update={
            "knowledge_citations": citations,
            "needs_human": needs_human,
            "risk_flags": risk_flags,
            "trace_metadata": {
                **output.trace_metadata,
                **build_trace_metadata(
                    context=context,
                    provider=provider,
                    extra={
                        "model": model,
                        "latency_ms": latency_ms,
                        "structured_output": True,
                        "provider_payload": build_minimized_turn_payload(context)[
                            "payload_minimization"
                        ],
                    },
                ),
            },
        }
    )
    normalized = QuoteSafetyGuard().apply(context=context, output=normalized).output
    normalized = normalize_composer_progress(context, normalized)
    progress_result = ConversationProgressGuard().apply(context=context, output=normalized)
    normalized = output_from_progress_result(progress_result)
    policy_issues = PolicyValidator().validate(normalized)
    if policy_issues:
        if _only_field_update_policy_issues(policy_issues):
            normalized = _drop_policy_invalid_field_updates(normalized, policy_issues)
            remaining_issues = PolicyValidator().validate(normalized)
            if not remaining_issues:
                return normalized
            policy_issues = remaining_issues
        return _safe_fallback_output(
            context,
            reason="agent_model_provider_policy_rejected",
            error_type="PolicyValidationError",
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            extra_metadata={
                "policy_issues": [
                    {"code": issue.code, "message": issue.message}
                    for issue in policy_issues
                ]
            },
        )
    return normalized


def _only_field_update_policy_issues(policy_issues: list[Any]) -> bool:
    return bool(policy_issues) and all(
        str(issue.code).startswith("field_update_") for issue in policy_issues
    )


def _drop_policy_invalid_field_updates(
    output: TurnOutput,
    policy_issues: list[Any],
) -> TurnOutput:
    dropped = [
        {
            "field_key": update.field_key,
            "reason": _field_update_drop_reason(update),
        }
        for update in output.field_updates
        if _field_update_drop_reason(update)
    ]
    trace = dict(output.trace_metadata)
    trace["dropped_field_updates"] = dropped
    trace["policy_issues"] = [
        {"code": issue.code, "message": issue.message} for issue in policy_issues
    ]
    return output.model_copy(
        update={
            "field_updates": [
                update for update in output.field_updates if not _field_update_drop_reason(update)
            ],
            "trace_metadata": trace,
        }
    )


def _field_update_drop_reason(update: Any) -> str | None:
    reasons = []
    if not (update.reason or update.evidence):
        reasons.append("missing_evidence")
    if update.confidence is None:
        reasons.append("missing_confidence")
    elif not 0 <= float(update.confidence) <= 1:
        reasons.append("invalid_confidence")
    return "+".join(reasons) if reasons else None


def _safe_fallback_output(
    context: TurnContext,
    *,
    reason: str,
    error_type: str | None = None,
    provider: str = "agent_model_provider",
    model: str | None = None,
    latency_ms: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> TurnOutput:
    extra: dict[str, Any] = {"fallback_reason": reason, "structured_output": True}
    if extra_metadata:
        extra.update(extra_metadata)
    if error_type:
        extra["error_type"] = error_type
    if model:
        extra["model"] = model
    if latency_ms is not None:
        extra["latency_ms"] = latency_ms
    extra["provider_payload"] = build_minimized_turn_payload(context)[
        "payload_minimization"
    ]
    return TurnOutput(
        final_message=(
            "Necesito que una persona del equipo revise esto para responderte con certeza."
        ),
        confidence=0.0,
        needs_human=True,
        risk_flags=[reason],
        knowledge_citations=_safe_citations(context.knowledge_citations),
        trace_metadata=build_trace_metadata(context=context, provider=provider, extra=extra),
    )


def _safe_citations(citations: list[KnowledgeCitation]) -> list[KnowledgeCitation]:
    return list(citations)

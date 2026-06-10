from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.respond_style_context_builder import (
    ContactFieldState,
    ContextSnapshotError,
    RespondStyleContextSnapshot,
    TranscriptMessage,
)
from atendia.agent_runtime.respond_style_product_agent_runtime import (
    ProductAgentRuntimeInput,
)

JsonDict = dict[str, Any]


class ProductAgentPublishedConfig(BaseModel):
    """Read-only view of a published Product Agent version.

    This is configuration only: identity, instructions, bindings, field
    definitions, and declarative policies. Conversation state lives in
    ConversationStateSnapshot. The adapter never mutates either.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    agent_id: str
    agent_version_id: str
    deployment_id: str = "no-send-deployment"
    publish_state: str = "unpublished"
    agent_name: str = ""
    persona: str = ""
    instructions: str = ""
    language: str = ""
    tone: str = ""
    goals: list[str] = Field(default_factory=list)
    do_not_do: list[str] = Field(default_factory=list)
    escalation_rules: list[JsonDict] = Field(default_factory=list)
    kb_snippets: list[JsonDict] = Field(default_factory=list)
    tool_bindings: list[JsonDict] = Field(default_factory=list)
    action_bindings: list[JsonDict] = Field(default_factory=list)
    workflow_bindings: list[JsonDict] = Field(default_factory=list)
    field_definitions: list[JsonDict] = Field(default_factory=list)
    handoff: JsonDict = Field(default_factory=dict)
    hard_policies: list[JsonDict] = Field(default_factory=list)
    send_scope: JsonDict = Field(default_factory=dict)


class ConversationStateSnapshot(BaseModel):
    """Read-only view of one conversation's current state."""

    model_config = ConfigDict(extra="forbid")

    recent_messages: list[TranscriptMessage] = Field(default_factory=list)
    field_values: JsonDict = Field(default_factory=dict)
    conversation_stage: str | None = None


class ProductAgentConfigSource(Protocol):
    def load_config(
        self, runtime_input: ProductAgentRuntimeInput
    ) -> ProductAgentPublishedConfig: ...


class ConversationStateSource(Protocol):
    def load_state(
        self, runtime_input: ProductAgentRuntimeInput
    ) -> ConversationStateSnapshot: ...


class ProductAgentConfigSnapshotAdapter:
    """Maps published Product Agent config + conversation state to a
    RespondStyleContextSnapshot.

    Pure and read-only: the injected sources own all I/O (DB today is
    behind them); this adapter only merges and normalizes. It always
    produces a no-send snapshot — live modes are a later, separately
    gated phase.
    """

    def __init__(
        self,
        *,
        config_source: ProductAgentConfigSource,
        state_source: ConversationStateSource,
    ) -> None:
        self._config_source = config_source
        self._state_source = state_source

    def load_snapshot(
        self,
        runtime_input: ProductAgentRuntimeInput,
    ) -> RespondStyleContextSnapshot:
        config = self._config_source.load_config(runtime_input)
        state = self._state_source.load_state(runtime_input)
        return RespondStyleContextSnapshot(
            tenant_id=config.tenant_id,
            deployment_id=config.deployment_id,
            agent_id=config.agent_id,
            agent_version_id=config.agent_version_id,
            conversation_id=runtime_input.conversation_id,
            contact_id=runtime_input.contact_id,
            channel=runtime_input.channel,
            runtime_mode="test_lab_no_send",
            send_mode="no_send",
            inbound_text=runtime_input.inbound_text,
            inbound_event_id=runtime_input.inbound_event_id,
            inbound_attachments=list(runtime_input.attachments),
            recent_messages=list(state.recent_messages),
            contact_fields=_merge_field_state(config.field_definitions, state.field_values),
            conversation_stage=state.conversation_stage,
            agent_name=config.agent_name,
            agent_persona=config.persona,
            agent_instructions=config.instructions,
            language=config.language,
            tone=config.tone,
            goals=list(config.goals),
            do_not_do=list(config.do_not_do),
            escalation_rules=list(config.escalation_rules),
            kb_snippets=list(config.kb_snippets),
            tool_bindings=list(config.tool_bindings),
            action_bindings=list(config.action_bindings),
            workflow_bindings=list(config.workflow_bindings),
            handoff=dict(config.handoff),
            hard_policies=list(config.hard_policies),
            publish_state=config.publish_state,
            send_scope=dict(config.send_scope),
            trace_context=dict(runtime_input.trace_context),
        )


def published_config_from_version_payload(
    payload: JsonDict,
    *,
    tenant_id: str,
    agent_id: str,
    agent_version_id: str,
    deployment_id: str = "no-send-deployment",
    publish_state: str = "unpublished",
) -> ProductAgentPublishedConfig:
    """Maps an AgentVersion-shaped payload (role/tone/language/instructions
    plus per-domain policy dicts) into ProductAgentPublishedConfig.

    Expected payload keys follow the Product Agent version schema:
    ``role``, ``tone``, ``language``, ``instructions``, and policy dicts
    ``knowledge_policy`` (snippets), ``tool_policy`` (bindings),
    ``action_policy`` (bindings), ``workflow_policy`` (bindings),
    ``field_policy`` (fields), ``safety_policy`` (hard_policies, handoff).
    Unknown keys are ignored; the payload is never mutated.
    """

    if not isinstance(payload, dict):
        raise ContextSnapshotError("version_payload_malformed", "payload must be a dict")
    knowledge_policy = _policy_dict(payload, "knowledge_policy")
    tool_policy = _policy_dict(payload, "tool_policy")
    action_policy = _policy_dict(payload, "action_policy")
    workflow_policy = _policy_dict(payload, "workflow_policy")
    field_policy = _policy_dict(payload, "field_policy")
    safety_policy = _policy_dict(payload, "safety_policy")
    return ProductAgentPublishedConfig(
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        deployment_id=deployment_id,
        publish_state=publish_state,
        agent_name=str(payload.get("name") or ""),
        persona=str(payload.get("role") or ""),
        instructions=str(payload.get("instructions") or ""),
        language=str(payload.get("language") or ""),
        tone=str(payload.get("tone") or ""),
        goals=[str(item) for item in payload.get("goals") or []],
        do_not_do=[str(item) for item in payload.get("do_not_do") or []],
        escalation_rules=list(safety_policy.get("escalation_rules") or []),
        kb_snippets=list(knowledge_policy.get("snippets") or []),
        tool_bindings=list(tool_policy.get("bindings") or []),
        action_bindings=list(action_policy.get("bindings") or []),
        workflow_bindings=list(workflow_policy.get("bindings") or []),
        field_definitions=list(field_policy.get("fields") or []),
        handoff=dict(safety_policy.get("handoff") or {}),
        hard_policies=list(safety_policy.get("hard_policies") or []),
        send_scope=dict(payload.get("send_scope") or {}),
    )


def _merge_field_state(
    field_definitions: list[JsonDict],
    field_values: JsonDict,
) -> list[ContactFieldState]:
    fields: list[ContactFieldState] = []
    for index, definition in enumerate(field_definitions):
        if not isinstance(definition, dict):
            raise ContextSnapshotError(
                "field_definition_malformed", f"field_definitions[{index}]"
            )
        field_key = str(definition.get("field_key") or definition.get("key") or "").strip()
        if not field_key:
            raise ContextSnapshotError(
                "field_definition_missing_key", f"field_definitions[{index}]"
            )
        fields.append(
            ContactFieldState(
                field_key=field_key,
                label=definition.get("label"),
                value_type=str(definition.get("type") or "string"),
                current_value=field_values.get(field_key),
                writable=definition.get("writable", True) is not False,
                required=definition.get("required", False) is True,
                write_policy=definition.get("write_policy"),
                evidence_required=definition.get("evidence_required", True) is not False,
                allowed_sources=[
                    str(item) for item in definition.get("allowed_sources") or []
                ],
                confidence=definition.get("confidence"),
                last_evidence=[
                    str(item) for item in definition.get("last_evidence") or []
                ],
            )
        )
    return fields


def _policy_dict(payload: JsonDict, key: str) -> JsonDict:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ContextSnapshotError("version_payload_malformed", f"{key} must be a dict")
    return value


__all__ = [
    "ConversationStateSnapshot",
    "ConversationStateSource",
    "ProductAgentConfigSnapshotAdapter",
    "ProductAgentConfigSource",
    "ProductAgentPublishedConfig",
    "published_config_from_version_payload",
]

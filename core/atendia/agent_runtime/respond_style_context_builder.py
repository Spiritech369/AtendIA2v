from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    AgentTurnInput,
    RuntimeMode,
    SendMode,
)

JsonDict = dict[str, Any]

TranscriptRole = Literal["customer", "assistant", "system_internal"]

_TRANSCRIPT_ROLE_MAP: dict[str, TranscriptRole] = {
    "customer": "customer",
    "user": "customer",
    "inbound": "customer",
    "assistant": "assistant",
    "agent": "assistant",
    "outbound": "assistant",
    "system_internal": "system_internal",
    "system": "system_internal",
}


class ContextSnapshotError(ValueError):
    """Structural problem in the snapshot/config. Fails the build closed so
    broken configuration surfaces in Test Lab, never silently unguarded."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class TranscriptMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: TranscriptRole
    text: str
    timestamp: str | None = None
    message_id: str | None = None
    attachments: list[JsonDict] = Field(default_factory=list)

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        if isinstance(value, str):
            mapped = _TRANSCRIPT_ROLE_MAP.get(value.strip().casefold())
            if mapped is not None:
                return mapped
        return value


class ContactFieldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str
    label: str | None = None
    value_type: str = "string"
    current_value: Any = None
    writable: bool = True
    required: bool = False
    write_policy: str | None = None
    evidence_required: bool = True
    allowed_sources: list[str] = Field(default_factory=list)
    confidence: float | None = None
    last_evidence: list[str] = Field(default_factory=list)

    @field_validator("field_key")
    @classmethod
    def require_field_key(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("field_key cannot be blank")
        return cleaned


class RespondStyleContextSnapshot(BaseModel):
    """Already-loaded, structured inputs for one agent turn.

    The builder never reads DB, files, or network: whatever loads this
    snapshot (tests, runners, or a future Product Agent config adapter)
    is responsible for I/O. The builder only normalizes and packages.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    deployment_id: str = "no-send-deployment"
    agent_id: str
    agent_version_id: str
    conversation_id: str
    contact_id: str | None = None
    channel: str = "no_send_snapshot"
    runtime_mode: RuntimeMode = "test_lab_no_send"
    send_mode: SendMode = "no_send"
    inbound_text: str
    inbound_event_id: str | None = None
    inbound_attachments: list[JsonDict] = Field(default_factory=list)
    recent_messages: list[TranscriptMessage] = Field(default_factory=list)
    contact_fields: list[ContactFieldState] = Field(default_factory=list)
    # Phase 17: corrected-away previous values, keyed by field_key.
    corrected_fields: JsonDict = Field(default_factory=dict)
    conversation_stage: str | None = None
    agent_name: str = ""
    agent_persona: str = ""
    agent_instructions: str = ""
    language: str = ""
    tone: str = ""
    goals: list[str] = Field(default_factory=list)
    do_not_do: list[str] = Field(default_factory=list)
    escalation_rules: list[JsonDict] = Field(default_factory=list)
    kb_snippets: list[JsonDict] = Field(default_factory=list)
    tool_bindings: list[JsonDict] = Field(default_factory=list)
    action_bindings: list[JsonDict] = Field(default_factory=list)
    workflow_bindings: list[JsonDict] = Field(default_factory=list)
    handoff: JsonDict = Field(default_factory=dict)
    hard_policies: list[JsonDict] = Field(default_factory=list)
    publish_state: str = "unpublished"
    send_scope: JsonDict = Field(default_factory=dict)
    trace_context: JsonDict = Field(default_factory=dict)


class RespondStyleBuiltContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_input: AgentTurnInput
    context_package: AgentContextPackage


class RespondStyleContextPackageBuilder:
    """Pure no-live packager for Respond-Style agent turns.

    The builder does not converse, does not author or repair any visible
    text, does not route tools by keyword, does not execute tools, actions,
    or workflows, does not write fields, and does not touch delivery. It
    only normalizes an already-loaded snapshot into the turn contract.
    """

    def build(self, snapshot: RespondStyleContextSnapshot) -> RespondStyleBuiltContext:
        turn_input = self.build_turn_input(snapshot)
        context_package = self.build_context_package(snapshot)
        return RespondStyleBuiltContext(
            turn_input=turn_input,
            context_package=context_package,
        )

    def build_turn_input(self, snapshot: RespondStyleContextSnapshot) -> AgentTurnInput:
        return AgentTurnInput(
            tenant_id=snapshot.tenant_id,
            deployment_id=snapshot.deployment_id,
            agent_id=snapshot.agent_id,
            agent_version_id=snapshot.agent_version_id,
            runtime_mode=snapshot.runtime_mode,
            send_mode=snapshot.send_mode,
            channel=snapshot.channel,
            conversation_id=snapshot.conversation_id,
            contact_id=snapshot.contact_id,
            inbound_event_id=snapshot.inbound_event_id,
            inbound_text=snapshot.inbound_text,
            attachments=list(snapshot.inbound_attachments),
            recent_messages=[
                message.model_dump(mode="json") for message in snapshot.recent_messages
            ],
            contact_snapshot=_contact_snapshot(snapshot),
            conversation_snapshot={
                "conversation_id": snapshot.conversation_id,
                "stage": snapshot.conversation_stage,
            },
            trace_context={
                **snapshot.trace_context,
                "runtime_path": _runtime_path(snapshot),
                "builder": "respond_style_context_package_builder",
            },
        )

    def build_context_package(
        self, snapshot: RespondStyleContextSnapshot
    ) -> AgentContextPackage:
        return AgentContextPackage(
            agent_identity=_agent_identity(snapshot),
            instructions=snapshot.agent_instructions,
            voice_guide=_voice_guide(snapshot),
            knowledge_bindings=_knowledge_bindings(snapshot),
            retrieved_context=_retrieved_context(snapshot),
            tool_schemas=[
                _tool_schema(item, index)
                for index, item in enumerate(snapshot.tool_bindings)
            ],
            tool_results=[],
            field_policies=[_field_policy(field) for field in snapshot.contact_fields],
            action_schemas=[
                _action_schema(item, index, snapshot)
                for index, item in enumerate(snapshot.action_bindings)
            ],
            workflow_trigger_schemas=[
                _workflow_schema(item, index, snapshot)
                for index, item in enumerate(snapshot.workflow_bindings)
            ],
            handoff_policy=_handoff_policy(snapshot),
            send_policy=_send_policy(snapshot),
            hard_policies=[
                _hard_policy(item, index) for index, item in enumerate(snapshot.hard_policies)
            ],
            validator_feedback=[],
        )


def _runtime_path(snapshot: RespondStyleContextSnapshot) -> str:
    if snapshot.send_mode == "no_send":
        return "respond_style_no_send"
    return "respond_style"


def _contact_snapshot(snapshot: RespondStyleContextSnapshot) -> JsonDict:
    known: JsonDict = {}
    for field in snapshot.contact_fields:
        if not _is_missing_value(field.current_value):
            known[field.field_key] = field.current_value
    return {
        "contact_id": snapshot.contact_id,
        "known_fields": known,
        "stage": snapshot.conversation_stage,
    }


def _agent_identity(snapshot: RespondStyleContextSnapshot) -> JsonDict:
    known_fields: JsonDict = {}
    missing_fields: list[str] = []
    for field in snapshot.contact_fields:
        if _is_missing_value(field.current_value):
            missing_fields.append(field.field_key)
        else:
            known_fields[field.field_key] = field.current_value
    return {
        "name": snapshot.agent_name,
        "persona": snapshot.agent_persona,
        "language": snapshot.language,
        "tone": snapshot.tone,
        "goals": list(snapshot.goals),
        "do_not_do": list(snapshot.do_not_do),
        "escalation_rules": list(snapshot.escalation_rules),
        "conversation_stage": snapshot.conversation_stage,
        "contact_state": known_fields,
        "corrected_fields": dict(snapshot.corrected_fields),
        "missing_fields": missing_fields,
        # Declarative contract for the LLM: fields are captured when the
        # customer provides them, never collected as a questionnaire.
        "field_capture_policy": "opportunistic_never_agenda",
    }


def _voice_guide(snapshot: RespondStyleContextSnapshot) -> JsonDict:
    guide: JsonDict = {}
    if snapshot.tone:
        guide["tone"] = snapshot.tone
    if snapshot.language:
        guide["language"] = snapshot.language
    return guide


def _knowledge_bindings(snapshot: RespondStyleContextSnapshot) -> list[JsonDict]:
    bindings: list[JsonDict] = []
    seen: set[str] = set()
    for index, item in enumerate(snapshot.kb_snippets):
        source_id = _required_str(
            item,
            "source_id",
            code="kb_snippet_missing_source_id",
            where=f"kb_snippets[{index}]",
        )
        if source_id in seen:
            continue
        seen.add(source_id)
        bindings.append(
            {
                "source_id": source_id,
                "name": str(item.get("title") or source_id),
            }
        )
    return bindings


def _retrieved_context(snapshot: RespondStyleContextSnapshot) -> list[JsonDict]:
    snippets: list[JsonDict] = []
    for index, item in enumerate(snapshot.kb_snippets):
        source_id = _required_str(
            item,
            "source_id",
            code="kb_snippet_missing_source_id",
            where=f"kb_snippets[{index}]",
        )
        excerpt = _required_str(
            item,
            "excerpt",
            code="kb_snippet_missing_excerpt",
            where=f"kb_snippets[{index}]",
        )
        snippet: JsonDict = {
            "source_id": source_id,
            "title": str(item.get("title") or source_id),
            "excerpt": excerpt,
            "citation": str(item.get("citation") or source_id),
        }
        if item.get("freshness") is not None:
            snippet["freshness"] = item["freshness"]
        if item.get("allowed_claim_types") is not None:
            snippet["allowed_claim_types"] = item["allowed_claim_types"]
        snippets.append(snippet)
    return snippets


def _tool_schema(item: JsonDict, index: int) -> JsonDict:
    name = _required_str(
        item,
        "name",
        alt_keys=("tool_name",),
        code="tool_binding_missing_name",
        where=f"tool_bindings[{index}]",
    )
    description = _required_str(
        item,
        "description",
        code="tool_binding_missing_description",
        where=f"tool_bindings[{index}]",
    )
    return {
        "name": name,
        "tool_name": name,
        "description": description,
        "input_schema": dict(item.get("input_schema") or {}),
        "output_facts_schema": dict(item.get("output_facts_schema") or {}),
        "preconditions": list(item.get("preconditions") or []),
        "required_context": list(item.get("required_context") or []),
        "produces_claim_support": bool(item.get("produces_claim_support", True)),
        "no_customer_copy": True,
        "enabled": item.get("enabled", True) is not False,
        "binding_id": str(item.get("binding_id") or name),
        "dry_run_only": bool(item.get("dry_run_only", True)),
        "approval_required": bool(item.get("approval_required", False)),
    }


def _field_policy(field: ContactFieldState) -> JsonDict:
    missing = _is_missing_value(field.current_value)
    return {
        "field_key": field.field_key,
        "label": field.label or field.field_key,
        "type": field.value_type,
        "current_value": field.current_value,
        "writable": field.writable,
        "required": field.required,
        "missing": missing,
        "write_policy": field.write_policy,
        "evidence_required": field.evidence_required,
        "allowed_sources": list(field.allowed_sources),
        "confidence": field.confidence,
        "last_evidence": list(field.last_evidence),
        "can_propose_update": field.writable,
    }


def _workflow_schema(
    item: JsonDict,
    index: int,
    snapshot: RespondStyleContextSnapshot,
) -> JsonDict:
    binding_name = _required_str(
        item,
        "binding_name",
        alt_keys=("name",),
        code="workflow_binding_missing_name",
        where=f"workflow_bindings[{index}]",
    )
    event_name = _required_str(
        item,
        "event_name",
        code="workflow_binding_missing_event",
        where=f"workflow_bindings[{index}]",
    )
    side_effects_allowed = bool(item.get("side_effects_allowed", False))
    if snapshot.send_mode == "no_send":
        side_effects_allowed = False
    return {
        "binding_name": binding_name,
        "binding_id": str(item.get("binding_id") or binding_name),
        "event_name": event_name,
        "description": str(item.get("description") or ""),
        "required_fields": list(item.get("required_fields") or []),
        "allowed_stages": list(item.get("allowed_stages") or []),
        "enabled": item.get("enabled", True) is not False,
        "dry_run_only": bool(item.get("dry_run_only", True)),
        "approval_required": bool(item.get("approval_required", True)),
        "side_effects_allowed": side_effects_allowed,
    }


def _action_schema(
    item: JsonDict,
    index: int,
    snapshot: RespondStyleContextSnapshot,
) -> JsonDict:
    action_name = _required_str(
        item,
        "action_name",
        alt_keys=("name",),
        code="action_binding_missing_name",
        where=f"action_bindings[{index}]",
    )
    side_effects_allowed = bool(item.get("side_effects_allowed", False))
    if snapshot.send_mode == "no_send":
        side_effects_allowed = False
    return {
        "action_name": action_name,
        "name": action_name,
        "description": str(item.get("description") or ""),
        "input_schema": dict(item.get("input_schema") or {}),
        "permission": str(item.get("permission") or "requires_grant"),
        "permitted": item.get("permitted", True) is not False,
        "enabled": item.get("enabled", True) is not False,
        "dry_run_only": bool(item.get("dry_run_only", True)),
        "approval_required": bool(item.get("approval_required", True)),
        "side_effects_allowed": side_effects_allowed,
    }


def _handoff_policy(snapshot: RespondStyleContextSnapshot) -> JsonDict:
    handoff = snapshot.handoff
    return {
        "enabled": handoff.get("enabled", False) is True,
        "targets": list(handoff.get("targets") or []),
        "reasons_allowed": list(handoff.get("reasons_allowed") or []),
        "dry_run_only": bool(handoff.get("dry_run_only", True)),
        # Any visible handoff message belongs to the LLM turn, never to
        # AtendIA code. The builder only declares that contract.
        "customer_message_authored_by_llm": True,
    }


def _send_policy(snapshot: RespondStyleContextSnapshot) -> JsonDict:
    return {
        "runtime_mode": snapshot.runtime_mode,
        "send_mode": snapshot.send_mode,
        "publish_state": snapshot.publish_state,
        "send_scope": dict(snapshot.send_scope),
        "deployment_id": snapshot.deployment_id,
        "runtime_path": _runtime_path(snapshot),
    }


def _hard_policy(item: JsonDict, index: int) -> JsonDict:
    where = f"hard_policies[{index}]"
    policy_id = _required_str(
        item, "policy_id", code="hard_policy_missing_id", where=where
    )
    patterns = item.get("trigger_patterns")
    requires = item.get("requires_any")
    if not isinstance(patterns, list) or not patterns:
        raise ContextSnapshotError("hard_policy_malformed", f"{where} trigger_patterns")
    if not isinstance(requires, list) or not requires:
        raise ContextSnapshotError("hard_policy_malformed", f"{where} requires_any")
    for pattern in patterns:
        try:
            re.compile(str(pattern))
        except re.error as exc:
            raise ContextSnapshotError(
                "hard_policy_malformed", f"{where} invalid pattern"
            ) from exc
    policy: JsonDict = {
        "policy_id": policy_id,
        "description": str(item.get("description") or policy_id),
        "trigger_patterns": [str(p) for p in patterns],
        "requires_any": [str(r) for r in requires],
    }
    for optional_key in ("applies_to", "severity", "retryable", "error_code"):
        if item.get(optional_key) is not None:
            policy[optional_key] = item[optional_key]
    return policy


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


def _required_str(
    item: JsonDict,
    key: str,
    *,
    code: str,
    where: str,
    alt_keys: tuple[str, ...] = (),
) -> str:
    for candidate in (key, *alt_keys):
        value = item.get(candidate)
        if value is not None and str(value).strip():
            return str(value).strip()
    raise ContextSnapshotError(code, f"{where} requires {key}")


__all__ = [
    "ContactFieldState",
    "ContextSnapshotError",
    "RespondStyleBuiltContext",
    "RespondStyleContextPackageBuilder",
    "RespondStyleContextSnapshot",
    "TranscriptMessage",
]

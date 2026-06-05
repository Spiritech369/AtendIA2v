from __future__ import annotations

from copy import deepcopy
from typing import Any

from atendia.agent_runtime.action_registry import ActionRegistry, default_action_registry
from atendia.agent_runtime.schemas import ActionDefinition, ActiveAgentContext

AGENT_STUDIO_V2_KEY = "agent_studio_v2"
AGENT_TEMPLATES = {"sales", "support", "receptionist", "custom"}


def list_string_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


def agent_studio_config_from_values(
    *,
    role: str | None = None,
    system_prompt: str | None = None,
    tone: str | None = None,
    language: str | None = None,
    knowledge_config: dict | None = None,
    auto_actions: dict | None = None,
    extraction_config: dict | None = None,
    flow_mode_rules: dict | None = None,
    ops_config: dict | None = None,
) -> dict:
    knowledge = dict(knowledge_config or {})
    actions = dict(auto_actions or {})
    extraction = dict(extraction_config or {})
    flow_rules = dict(flow_mode_rules or {})
    ops = dict(ops_config or {})
    studio = dict(ops.get(AGENT_STUDIO_V2_KEY) or {})

    template = str(studio.get("template") or _template_from_role(role))
    if template not in AGENT_TEMPLATES:
        template = "custom"

    return {
        "template": template,
        "instructions": str(studio.get("instructions") or system_prompt or ""),
        "tone": str(studio.get("tone") or tone or "neutral"),
        "language_policy": deepcopy(
            studio.get("language_policy") or {"primary": language or "es", "mode": "match_customer"}
        ),
        "enabled_knowledge_source_ids": list_string_values(
            studio.get("enabled_knowledge_source_ids")
            or knowledge.get("enabled_source_ids")
            or knowledge.get("linked_sources")
        ),
        "enabled_action_ids": list_string_values(
            studio.get("enabled_action_ids") or actions.get("enabled_action_ids")
        ),
        "visible_contact_field_keys": list_string_values(
            studio.get("visible_contact_field_keys")
            or extraction.get("visible_contact_field_keys")
        ),
        "allowed_lifecycle_stage_ids": list_string_values(
            studio.get("allowed_lifecycle_stage_ids")
            or flow_rules.get("allowed_stage_ids")
        ),
        "escalation_policy": deepcopy(studio.get("escalation_policy") or {}),
        "metadata": deepcopy(studio.get("metadata") or {}),
    }


def action_registry_for_agent(
    agent: ActiveAgentContext | None,
    base_registry: ActionRegistry | None = None,
) -> ActionRegistry:
    registry = base_registry or default_action_registry()
    allowed = _enabled_actions_from_agent(agent)
    if allowed is None:
        return registry
    restricted = ActionRegistry()
    for definition in registry.list_definitions():
        if definition.name in allowed and registry.has_action(definition.name):
            restricted.register(
                ActionDefinition(
                    id=definition.id,
                    name=definition.name,
                    description=definition.description,
                    input_schema=deepcopy(definition.input_schema),
                    permissions=list(definition.permissions),
                    capabilities=list(definition.capabilities),
                    risk_level=definition.risk_level,
                    execution_mode=definition.execution_mode,
                    sensitive=definition.sensitive,
                    requires_evidence=definition.requires_evidence,
                    requires_approval=definition.requires_approval,
                    enabled=definition.enabled,
                    metadata=deepcopy(definition.metadata),
                ),
                handler=registry.handler_for(definition.name),
            )
    return restricted


def _enabled_actions_from_agent(agent: ActiveAgentContext | None) -> set[str] | None:
    if agent is None:
        return None
    values = agent.enabled_action_ids
    if values is None:
        raw = agent.metadata.get("enabled_action_ids")
        values = list_string_values(raw) if raw is not None else None
    if values is None:
        return None
    return set(values)


def _template_from_role(role: str | None) -> str:
    if role in {"sales", "support", "receptionist"}:
        return str(role)
    if role == "reception":
        return "receptionist"
    return "custom"

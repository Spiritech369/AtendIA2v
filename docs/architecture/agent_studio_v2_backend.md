# Agent Studio v2 Backend

## Purpose

Agent Studio v2 is the backend contract for configuring Agent-First behavior per
tenant without changing the legacy runner defaults. It exposes instructions,
tone, language policy, Knowledge OS source scope, allowed actions, visible
contact fields and allowed lifecycle stages as agent configuration.

The implementation reuses existing `agents` columns to avoid a migration in this
step:

- `system_prompt` stores `instructions`.
- `tone` and `language` remain legacy-compatible identity fields.
- `knowledge_config.enabled_source_ids` stores Knowledge OS/legacy KB source ids.
- `auto_actions.enabled_action_ids` stores allowed AgentRuntime action ids.
- `extraction_config.visible_contact_field_keys` stores field visibility.
- `flow_mode_rules.allowed_stage_ids` stores lifecycle stage scope.
- `ops_config.agent_studio_v2` stores Studio metadata, template,
  `language_policy` and `escalation_policy`.

Legacy agents that do not carry Studio config load with safe defaults:
empty instructions, no enabled actions, no pinned knowledge sources, all contact
fields visible to legacy surfaces, and the existing language as primary language.

## API

Existing endpoints were extended:

- `GET /api/v1/agents/{agent_id}` returns Studio v2 fields.
- `GET /api/v1/agents/{agent_id}/config` returns the editable Studio config.
- `PATCH /api/v1/agents/{agent_id}` and `/config` accept Studio v2 fields.
- `POST /api/v1/agents/{agent_id}/duplicate` copies the underlying JSON config.
- `POST /api/v1/agents/{agent_id}/publish` snapshots the Studio JSON fields.

New option endpoints:

- `GET /api/v1/agents/studio/actions`
- `GET /api/v1/agents/studio/knowledge-sources`
- `GET /api/v1/agents/studio/contact-fields`
- `GET /api/v1/agents/studio/lifecycle-stages`

All option endpoints are tenant-scoped. Mutating endpoints require
`tenant_admin`/`superadmin` through the existing agents route protections.

## Example Config

```json
{
  "name": "Support Agent",
  "template": "support",
  "role": "support",
  "instructions": "Answer only from approved sources.",
  "tone": "clear",
  "language_policy": {"primary": "es-MX", "mode": "match_customer"},
  "enabled_knowledge_source_ids": ["2e86c0c4-4f6a-48cb-a9ff-16c49f8c7f7b"],
  "enabled_action_ids": ["add_tag", "assign_conversation"],
  "visible_contact_field_keys": ["email", "phone"],
  "allowed_lifecycle_stage_ids": ["qualified", "handoff"],
  "escalation_policy": {"mode": "human_on_low_confidence"},
  "metadata": {"owner": "ops"}
}
```

## Runtime Integration

`ContextBuilder` now loads the active agent config into `ActiveAgentContext`.
It filters contact fields by `visible_contact_field_keys` and passes
`enabled_knowledge_source_ids` to retrieval providers that support source
filtering.

`AgentRuntime` validates output with an action registry restricted to
`enabled_action_ids` when the active agent has Studio config. `PostTurnActionExecutor`
uses the same restriction, including dry-run execution in the test-turn harness.
Instructions and tone are available in context for the provider; they do not
override `PolicyValidator`.

## Validation Rules

Studio patch/create rejects:

- action ids not registered in `ActionRegistry`;
- knowledge source ids not owned by the current tenant;
- visible field keys not defined for the current tenant;
- lifecycle stage ids not present in the active tenant pipeline.

## Pending

- Native Studio frontend controls.
- Native Knowledge OS source listing as the default once migration 058 is applied
  everywhere; the current list also includes legacy FAQ/document sources.
- Rich prompt assembly for a real LLM provider using instructions/tone.
- Versioning for guardrails and other relation tables outside the `agents` row.

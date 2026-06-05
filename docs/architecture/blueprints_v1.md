# Blueprint System v1

Blueprints are declarative tenant installers for Agent-First configuration.
They keep vertical knowledge out of `AgentRuntime`: industry-specific fields,
stages, instructions and eval scenarios live in JSON files under
`core/atendia/blueprints/definitions/`.

## Initial Blueprints

- `automotive_real_estate`
- `dental_clinic`
- `beauty_barber_spa`

Each blueprint includes:

- Contact field definitions with Contact Memory write policy.
- Lifecycle stages mapped onto the existing tenant pipeline.
- Agent Studio v2 template values: instructions, tone, language policy,
  enabled actions, visible fields and allowed lifecycle stages.
- Expected Knowledge OS categories.
- Workflow templates as inactive stubs.
- Basic eval scenarios.

## Service

`BlueprintService` exposes:

- `list_blueprints()`
- `preview_blueprint(blueprint_id)`
- `validate_blueprint(blueprint)`
- `install_blueprint(session, tenant_id, blueprint_id, actor_user_id=None)`

Install is idempotent:

- Existing contact fields are skipped by `key`.
- Existing lifecycle stages are skipped by `id`.
- An agent with matching `ops_config.agent_studio_v2.metadata.blueprint_id`
  is reused.
- Existing tenant pipeline stages are preserved; missing blueprint stages are
  appended.

The service writes an `admin.blueprint.installed` audit event in the existing
`events` table. The caller owns the transaction commit.

## Runtime Boundary

Blueprints do not modify `AgentRuntime` behavior. The runtime receives generic
agent configuration, visible fields, lifecycle stages, enabled actions and
knowledge categories through existing Agent Studio / ContextBuilder paths.
No runtime branch knows about automotive, dental or beauty industries.

## Knowledge Templates

v1 stores expected categories in the blueprint and agent `knowledge_config`.
It does not create real `KnowledgeSource` rows yet. The next layer can use
these categories to scaffold upload prompts or source templates.

## Workflow Templates

Workflow templates are included as inactive stubs. They document recommended
event triggers such as `agent_confidence_low` and
`agent_lifecycle_update_suggested`, but v1 does not automatically create active
workflows.

## Pending

- Admin API endpoints for list/preview/install.
- UI for selecting and previewing blueprint impact.
- Optional creation of draft KnowledgeSource templates.
- Optional creation of inactive Workflow rows from templates.
- Blueprint versioning and upgrade/diff flow.

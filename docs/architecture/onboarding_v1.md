# Onboarding Wizard v1

Onboarding v1 stores per-tenant progress for the Agent-First setup flow. It is
backend-only: no channels are connected automatically, no production runtime is
activated, and publishing is never performed by the readiness endpoint.

## State

`onboarding_states` is keyed by `tenant_id` and tracks:

- `selected_blueprint_id`
- `channel_connected`
- `knowledge_uploaded`
- `agent_configured`
- `contact_fields_ready`
- `lifecycle_ready`
- `test_passed`
- `published`
- `current_step`
- `checklist`
- timestamps

`GET /api/v1/onboarding/state` creates a default row on first access.

## Endpoints

- `GET /api/v1/onboarding/state`
- `POST /api/v1/onboarding/select-blueprint`
- `POST /api/v1/onboarding/mark-step`
- `POST /api/v1/onboarding/validate`
- `POST /api/v1/onboarding/publish-readiness`

All endpoints require `tenant_admin` permissions.

## Blueprint Integration

`select-blueprint` calls `BlueprintService.install_blueprint(...)`, which
installs declarative contact fields, lifecycle stages and an Agent Studio v2
draft/base agent. The endpoint records the selected blueprint and keeps the
install result inside `checklist.blueprint_install_result`.

## Validation

Validation is tenant-scoped and checks:

- Blueprint selected.
- Channel connected via onboarding state or connected Baileys config.
- At least one non-disabled agent.
- At least one active Knowledge OS source, published legacy FAQ/document, or
  `checklist.knowledge_skipped=true`.
- At least one active lifecycle/pipeline stage.
- At least one contact field definition.
- `test_passed=true`, set by `mark-step` after a successful test chat/eval.
- No critical config errors, derived from the blocking checks.

`publish-readiness` returns the same validation shape and does not mutate
`published`.

## Explicit Knowledge Skip

The wizard can mark knowledge as intentionally skipped with:

```json
{
  "step": "knowledge_skipped",
  "value": true
}
```

This is stored in `checklist` and lets readiness pass without uploaded
knowledge when the tenant intentionally starts without KB.

## Pending

- Persist real test-chat pass/fail automatically from Agent Test Chat.
- Include Meta Cloud webhook freshness in channel validation.
- Add UI for checklist remediation and blueprint preview.
- Add draft KnowledgeSource scaffolding from blueprint knowledge categories.

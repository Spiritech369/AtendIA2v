# Blueprints Admin API v1

## Purpose

Blueprints are tenant-scoped onboarding/admin templates for contact fields,
lifecycle stages, an Agent Studio base agent, expected knowledge categories,
inactive workflow drafts, and eval scenarios.

The API exposes blueprints without changing AgentRuntime and without publishing
workflows automatically.

## Endpoints

- `GET /api/v1/blueprints`
- `GET /api/v1/blueprints/{blueprint_id}`
- `POST /api/v1/blueprints/{blueprint_id}/preview-install`
- `POST /api/v1/blueprints/{blueprint_id}/install`
- `POST /api/v1/blueprints/{blueprint_id}/create-knowledge-templates`
- `POST /api/v1/blueprints/{blueprint_id}/create-workflow-drafts`

All endpoints require `tenant_admin` or `superadmin`. Tenant scoping is resolved
through the existing `current_tenant_id` dependency; tenant admins cannot act on
another tenant, and superadmins use their scoped tenant or `?tid=...`.

## Preview Contract

Preview returns the tenant-specific install impact:

- fields to create and matching existing fields;
- lifecycle stages to create and matching existing stages;
- agent template;
- enabled action ids;
- expected knowledge categories;
- workflow draft templates;
- eval scenarios;
- risks and reminders.

Preview is read-only and does not create rows.

## Install Semantics

`install` is idempotent. It creates only missing contact fields, missing
lifecycle stages, and one base agent for the blueprint. Existing tenant
configuration is preserved and never deleted.

The endpoint also marks the onboarding state as having a selected blueprint and
stores expected knowledge categories in the checklist. It does not mark
`knowledge_uploaded`; draft templates remain empty until real active content is
uploaded.

An `admin.blueprint.installed` audit event is emitted for each install request.

## Draft Templates

Knowledge templates create empty `KnowledgeSource` rows with:

- `status=draft`
- `type=manual`
- `metadata_json.template_kind=blueprint_knowledge`
- `metadata_json.template_empty=true`
- `metadata_json.blueprint_id`
- `metadata_json.blueprint_category`

Workflow templates create `workflows` rows with `active=false`; draft metadata is
stored in `definition.metadata`. Webhook triggers are not created from blueprints
by default, and workflow drafts are never published automatically.

## Remaining Gaps

- No blueprint version upgrade/migration endpoint yet.
- Workflow drafts are stubs until the Workflow Canvas edits and validates them.
- Eval scenarios are exposed in preview, but full eval execution remains in the
existing readiness/eval services.

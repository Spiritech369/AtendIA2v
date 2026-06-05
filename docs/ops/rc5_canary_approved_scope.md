# RC5 Approved Scope - Single Contact Smoke

Generated: 2026-06-03T17:18:31.5306424-06:00
Decision: READY_FOR_SINGLE_CONTACT_LIVE_SMOKE_APPROVAL
Test type: single_contact_live_smoke

## Resolved Tenant

- tenant_id: 6ad78236-1fc9-467a-858d-90d248d57ee5
- tenant name: Dinamo Motos NL
- email: dinamomotosnl@gmail.com
- status: active
- source: read-only DB query via tenant_users -> tenants

## Resolved Agent

- agent_id: c169deec-226d-55b7-bd07-270f339e75a6
- agent name: Francisco de Dinamo NL
- status: production
- default: true
- ambiguity: none, one default production agent found

## Smoke Scope

- Expected volume: 1 conversation / 5-15 turns
- Approved test phone: +528212889421
- Provider real: approved for this smoke only
- Send real: approved only for +528212889421
- Actions enabled: false
- Workflow events enabled: false
- Rollout mode: manual_send with live-limited allowlist
- Escalation beyond this test: not approved

## Verified Contact Gate

The live contact gate is supported through `dinamo_agent_first_live_limited`:

- requires `enabled=true`
- requires `allow_real_outbox=true`
- requires `human_monitoring_active=true`
- requires `rollback_ready=true`
- requires `restrict_to_allowlist=true`
- checks `allowed_tenant_ids`
- checks `allowed_contact_ids` and `allowed_phone_numbers`
- non-allowlisted contacts return `dinamo_live_limited_not_allowlisted`
- outbox enqueue only happens when `runtime_selection.live_limited_allowed` is true

Focused verification: `3 passed, 1 skipped` for the contact/phone allowlist tests.

## Decision

READY_FOR_SINGLE_CONTACT_LIVE_SMOKE_APPROVAL. This is ready for human approval of one controlled conversation only. No traffic has been started and no tenant config has been applied.

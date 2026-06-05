# AgentRuntime v2 Limited Manual-Send Pilot

## Purpose

The limited pilot allows a tenant-admin to send AgentRuntime v2 responses manually for an allowlisted tenant/agent while keeping production automation off. The path still uses the existing conversation send endpoint and stages outbound messages through `outbound_outbox`; it never sends directly to a channel.

## Policy Location

Pilot policy lives under `tenants.config.agent_runtime_v2.pilot`:

```json
{
  "enabled": true,
  "allowed_tenant_ids": ["tenant-uuid"],
  "allowed_agent_ids": ["agent-uuid"],
  "allowed_channel_ids": ["whatsapp"],
  "max_sends_per_day": 10,
  "require_latest_readiness_passed": true,
  "min_readiness_score": 0.9,
  "min_shadow_sample_size": 20,
  "min_shadow_score": 0.85,
  "actions_dry_run_required": true,
  "workflow_events_dry_run_required": true,
  "rollback_disabled": false
}
```

If the `pilot` block is absent, the existing rollout policy remains the only gate. If the `pilot` block is present and `enabled=false` or `rollback_disabled=true`, manual send is blocked immediately.

## Send Flow

`POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/send` now evaluates:

- global AgentRuntime v2 send flags;
- tenant rollout policy;
- pilot tenant/agent/channel allowlists;
- daily pilot send count from `turn_traces`;
- latest readiness result when required;
- shadow sample size and average confidence when required;
- existing conversation safety gates: active/open status, no human pause, no open handoff, and WhatsApp 24h window.

Actions and workflow events are forced to dry-run when the pilot policy requires it, even if global and tenant rollout flags allow real execution.

## Trace And Counter

Every pilot allow/block decision is recorded in `TurnTrace.state_after.pilot` and `kb_evidence.pilot`. Successful pilot sends use `router_trigger=agent_runtime_v2_send`; pilot policy blocks use `router_trigger=agent_runtime_v2_pilot_blocked`.

The daily send counter is intentionally trace-backed, not a separate table. This keeps rollback simple and avoids duplicating state.

## Pilot Report

`GET /api/v1/agent-runtime-v2/pilot-report` returns tenant-scoped aggregate metrics:

- sends;
- policy failures;
- average confidence;
- needs-human count;
- knowledge-gap count;
- policy-blocked count;
- actions proposed;
- fields suggested/applied;
- lifecycle suggested/applied;
- error rate.

## Safety Boundaries

- No webhook-auto v2 path is enabled by this pilot.
- No direct channel send is introduced; outbox remains the only send path.
- Actions remain dry-run by default.
- Workflow events remain dry-run by default.
- WhatsApp 24h, bot pause, and open handoff checks are still enforced.

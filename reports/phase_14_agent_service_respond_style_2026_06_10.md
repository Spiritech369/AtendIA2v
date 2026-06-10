# Phase 14 — AgentService × Respond-Style Direct Route (no-send)

Date: 2026-06-10
Decision: `PHASE_14_AGENT_SERVICE_RESPOND_STYLE_NO_SEND_READY`
Modules:
- `core/atendia/product_agents/agent_service_bridge.py` (new)
- `core/atendia/agent_runtime/agent_service.py` (additive routing block +
  result mapper; legacy flow byte-identical for non-opted-in tenants)
Tests: `test_phase_14_agent_service_respond_style.py` (8; suite 206)
E2E: `tools/run_agent_service_respond_style_replay_2026_06_10.py` →
`reports/agent_service_respond_style_replay_result_2026_06_10.json`

## Integration design

`AgentService.handle_turn` now starts with a lazy call to
`maybe_handle_respond_style_turn`:

- **Opt-in resolution** via the Phase 11 resolver: a deployment previews
  `product_agent_direct` (requires `metadata_json.respond_style_enabled`,
  published state, active version). No such deployment → returns None and
  the previous Runtime V2 path runs untouched.
- **Opted-in turns NEVER fall back to legacy.** Fail-closed outcomes:
  - mode != no_send → `respond_style_live_not_enabled`
  - missing active version → `respond_style_active_version_missing`
  - publish-gate blockers (hard-block audit + direct Test Lab evidence,
    Phase 13A) → `respond_style_publish_gates_blocked` with the blockers
  - missing provider key → `respond_style_provider_unconfigured`
  - any bridge exception → `respond_style_bridge_failed:<type>`
- Execution: ProductAgentRuntime direct (config adapter from the active
  AgentVersion payload, transcript from the conversation's last messages,
  DryFacts executor, 3-round budgeted loop, F18 backoff, F24 claims
  scope). The Runtime V2 composer pipeline (AdvisorFirstAgentProvider /
  HumanResponseComposer / StructuredRuntimeComposer / ValidatedResponse-
  Plan) is never imported by the bridge (test-enforced).
- Result mapped to `AgentServiceResult` for existing callers: TurnOutput
  carries the full evidence under `trace_metadata.respond_style_agent_
  service` (route, legacy_path_used=false, send_decision=no_send, context
  summary, tool rounds/results, dropped proposals, retry/backoff metrics,
  validator result, final_message candidate, field/workflow/action/handoff
  proposals, side_effects). SendAdapterResult is blocked-by-construction:
  `allowed=false`, `outbox_write_attempted=false`, no outbox ids.

## Unit tests (8)

Opt-in uses ProductAgentRuntime and never touches the injected legacy
provider; non-opt-in keeps the previous path (legacy builder+provider
called); live_candidate fails closed; publish-gate blockers fail closed
WITHOUT legacy fallback; bridge exceptions fail closed; bridge source has
no legacy imports and no vertical hardcodes; the direct runtime input
refuses live modes at the schema level.

## E2E — V2/V3 failed-transcript replay through the REAL AgentService

Docker container, real Postgres, real OpenAI. Seeded: opted-in
published_no_send deployment over a generic credit-sales version (KB
general requirements + dry-fact tools), publish-gate evidence (passing
direct Test Lab run), fresh customer/conversation; inbound rows inserted
per turn and the no-send candidates recorded as simulated outbound rows
for transcript continuity.

Result: `PHASE_14_AGENT_SERVICE_REPLAY_PASSED`
- 9 turns, 8 answered; the 1 block carries a structured reason
  (`tool_round_limit_reached`) — never silent-without-reason.
- `all_direct_route=true`, `legacy_path_used=false` on every turn.
- `all_send_blocked=true`, `no_outbox_attempts=true`, **outbox delta 0**,
  pending/retry 0.
- **0 internal leaks** — the V3 historical failure ("campo no está
  visible") cannot reproduce; the V2 historical silence-after-income is
  answered.

## Honest scope note (next phase work, by design)

The bridge does NOT persist validated field proposals to contact state —
field persistence is a separate validated execution layer (deliberately
out of Phase 14). Consequence visible in the replay: the agent re-asks
seniority after "15 meses" because the no-send route has no field memory
across turns yet. Next phase: field-proposal persistence (validated,
audited) + the live no_send→handoff policy + multi-deployment tenant
resolution (the bridge currently picks the first direct-preview
deployment).

## Decision

`PHASE_14_AGENT_SERVICE_RESPOND_STYLE_NO_SEND_READY`

Not live readiness; no send, no smoke, no canary authorized by this
marker.

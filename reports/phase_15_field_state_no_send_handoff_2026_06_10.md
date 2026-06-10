# Phase 15 — Shadow Field State, no_send→Operator Policy, Multi-Deployment

Date: 2026-06-10
Decision: `PHASE_15_RESPOND_STYLE_FIELD_STATE_AND_NO_SEND_HANDOFF_READY`
Modules:
- 15A: `agent_runtime/respond_style_field_state.py` (pure validation/audit),
  migration `069_respond_style_shadow_fields` + `RespondStyleShadowFields`
  model, bridge load/apply/persist integration
- 15B: `derive_no_send_followup` in the bridge (internal policy, declared
  not executed)
- 15C: ambiguity-aware deployment resolution in the bridge
Tests: 6 new in `test_phase_14_agent_service_respond_style.py` (suite 211)
E2E: re-run of the AgentService V2/V3 replay (fresh conversation PER
replay so shadow state cannot leak between independent replays).

## 15A — Validated, audited shadow field application

- Pure layer `apply_field_proposals`: re-validates each VALIDATED proposal
  against field policies (writable, known key) and evidence (non-empty);
  rejected proposals never modify state. Audit entry per proposal:
  field_key, accepted/rejected + reason (`new_value_captured` /
  `corrected_previous_value` / `field_not_writable_or_unknown` /
  `missing_evidence`), previous_value, new_value, evidence, source,
  `shadow_only=Literal[True]`.
- Persistence: NEW isolated table `respond_style_shadow_fields`
  (conversation-keyed JSONB values + append-only audit_log). Deliberately
  NOT `conversation_state.extracted_data` — that is the legacy runner's
  store and sharing it would contaminate live commercial state. Nothing
  legacy reads/writes the new table.
- Bridge: loads shadow values into the snapshot
  (`ConversationStateSnapshot.field_values`) so the builder marks them
  known; applies + persists after each turn; full `field_state` section in
  the AgentService trace (previous_values, new_values, accepted/rejected
  counts, audit, shadow_only=true).

## 15B — no_send → internal operator policy (declared, not executed)

`derive_no_send_followup`: any blocked turn → `{action:
handoff_internal_needed, notify_operator: true, reason, customer_copy_
sent: false, executed: false}`; silent valid handoff → same with reason
`no_visible_message`; answered turn → `action: none`. Attached to every
bridge outcome and surfaced in the AgentService trace. No customer copy,
no workflow execution, no delivery in this phase — live wiring of the
notification is the live-phase task, the DECISION is now structural.

## 15C — Multi-deployment resolution

The bridge resolver returns `(deployment, ambiguous)`: zero direct-preview
deployments → legacy path; exactly one → selected; more than one →
fail-closed outcome `respond_style_deployment_ambiguous` (never guess,
never legacy-fallback). Channel-based disambiguation is the natural
extension when AgentService passes a channel signal.

## E2E acceptance — V2/V3 replay through the REAL AgentService

Docker, real Postgres (migration 069 applied), real OpenAI, fresh
conversation per replay: `PHASE_14_AGENT_SERVICE_REPLAY_PASSED` with
**9/9 answered** (Phase 14 baseline: 8/9).

The acceptance moment, verbatim:
- "15 meses" → "Entiendo que tienes 15 meses de antigüedad laboral.
  ¿Cómo recibes tus ingresos?" — captured, next step asked, NO re-ask.
- "me pagan por transferencia" → exact requirements via tool; seniority
  NOT re-asked (Phase 14 re-asked it here).
- Final "?" → `requirements.lookup` ran successfully using the
  `income_type` persisted in shadow state TWO turns earlier — cross-turn
  field memory proven against the real DB.

Audits: all direct route, legacy_path_used=false, all send blocked, no
outbox attempts, **outbox delta 0**, pending/retry 0, **0 internal
leaks**, no silent turns without reason.

## Decision

`PHASE_15_RESPOND_STYLE_FIELD_STATE_AND_NO_SEND_HANDOFF_READY`

No live, no smoke, no canary. Next milestones from here: wire the
15B operator notification for live (no_send must page a human), channel
signal for 15C disambiguation, and the two-consecutive-battery gate
before any live-candidate conversation.

# PHASE 20 — Single-Contact Smoke Path (implemented, tested, SEND OFF)

Date: 2026-06-10
Decision: **`PHASE_20_SINGLE_CONTACT_SMOKE_PATH_READY`**
End state: implemented, 262 tests passing, ruff clean, migration 070
applied — and **send is OFF**: the real deployment has no
live_send_enabled, no send_scope, no approval text, no preflight stamp.
Activation requires the literal Phase-19 approval text plus the steps in
section "Activation runbook" below.

## What was built

### 1. Smoke policy — `core/atendia/product_agents/smoke_policy.py`

Runtime-enforced, evaluated PER TURN from deployment metadata (rollback is
therefore immediate: the next inbound reads the new flags, no restart).
A send is possible ONLY when ALL of these hold:

- `respond_style_live_send_enabled=true`
- `respond_style_send_scope == "approved_contact_only"` (all/tenant/
  canary/production/all_contacts are FORBIDDEN scopes — never sendable)
- phone normalized (last-10 digits) matches `respond_style_live_allowed_phones`
- `respond_style_workflows_enabled` / `respond_style_actions_enabled` /
  `respond_style_legacy_fallback_enabled` all false
- `respond_style_fail_closed_notify_operator=true`
- `respond_style_rollback_active` not true
- `respond_style_smoke_approval_text` matches the Phase-19 literal approval
  text EXACTLY (accent-fold compare; code constant `EXACT_APPROVAL_TEXT`)
- `respond_style_preflight_passed_at` stamped by the preflight tool
- the turn itself: validator `valid`, non-empty `final_message`, no
  blocked_reason, no workflow/action proposals, no side effects, no
  human-takeover pending

Default state of every flag is OFF → the module is a pure no-op and the
direct route stays shadow/no-send (verified: the entire 240-test suite
that predates this phase passes unchanged).

### 2. Outbox staging

`stage_smoke_send` uses the EXISTING `queue.outbox.stage_outbound` +
`OutboundMessage` path (same worker, same channel delivery). Idempotency
key `rs-smoke-<inbound_message_id>` — a turn can never double-send.
Payload metadata records: `source=respond_style_single_contact_smoke`,
deployment_id, agent_version_id, conversation_id, inbound_message_id,
phone_normalized, send_scope, model, trace_id, smoke_session_id,
validator_status.

### 3. Legacy suppression — scoped to the approved contact only

One surgical guard at the top of `RuntimeV2SendAdapter.apply` (the legacy
prepared-send choke point): if smoke is active for the tenant AND the
recipient phone is allowlisted, the legacy send is blocked with
`reason=legacy_suppressed_for_smoke` and audit fields
(`legacy_suppressed_for_smoke=true`, `suppression_scope=
approved_contact_only`, `legacy_outbound_prevented=true`). The helper
fails OPEN to normal legacy behavior on any error — suppression can never
break other contacts. No other legacy code touched.

### 4. Fail-closed 15B

When smoke is active and a turn for the ALLOWLISTED phone blocks or has
no final_message: nothing is sent, no fallback copy exists anywhere, and
a `human_handoffs` row is created (`respond_style_smoke_fail_closed`,
internal_attention_needed=true, customer_copy_sent=false) with the
blocked reason — the operator sees why, the customer never gets invented
copy. Non-allowlisted phones stay silently in shadow (no paging spam).

### 5. Handoff takeover — bot pause

Accepted handoff during smoke: the validated ack stages ONCE, then
`takeover_pending` (new column, migration 070, on the isolated
respond_style_shadow_fields table) is set. Every subsequent inbound
short-circuits BEFORE the LLM: no auto-response, no send, quiet
`human_takeover_pending` followup (operator not re-paged per message).
Cleared by rollback or manual reset.

### 6. Preflight + rollback tools

- `tools/respond_style_smoke_preflight_2026_06_10.py`: validates all
  packet preconditions; ONLY when everything passes (including the exact
  approval text already present in metadata) does it stamp
  `respond_style_preflight_passed_at`. It never enables send.
  **Run live against the real deployment: `FAILED` as designed** (no
  approval text / scope / fail-closed flag yet) and wrote no stamp —
  the no-activation-without-approval gate demonstrated on real data.
- `tools/respond_style_smoke_rollback_2026_06_10.py`: flips
  live_send_enabled=false, send_scope=no_send, clears allowed_phones,
  sets rollback_active, clears the preflight stamp and takeover markers,
  verifies outbox pending/retry and recent side effects, exports the last
  hour of traces as the incident record. Because the gate reads metadata
  per turn, sends stop on the very next inbound — no restart.

## Test matrix (22 new; suite 262)

| Required test | Status |
|---|---|
| 1. allowed phone stages validated final_message | ✅ policy + bridge E2E |
| 2. non-allowed phone stays shadow, no outbox | ✅ |
| 3/4. legacy suppressed only for allowed phone; others unchanged | ✅ (scoped suppression tests + fail-open) |
| 5. validator fail → no outbox + notify_operator | ✅ |
| 6. missing final_message → no outbox | ✅ |
| 7. blocked turn (required tool failed) → no outbox | ✅ |
| 8. workflow/action proposals or flags → no outbox | ✅ |
| 9. handoff accepted → ack allowed once + takeover set | ✅ |
| 10. after takeover, next inbound gets NO auto-response (no LLM call) | ✅ |
| 11. rollback flag disables send immediately | ✅ |
| 12. no legacy fallback copy when Respond-Style fails | ✅ (fail-closed test asserts final_message None + operator page) |
| 13. no double response | ✅ (suppression + idempotency key) |
| 14. scope cannot be all_contacts/tenant/canary/production | ✅ |
| 15. no activation without exact approval + preflight stamp | ✅ unit + LIVE preflight run failed correctly |
| 16. outbox metadata: smoke_session_id/trace_id/source | ✅ |
| 17. existing shadow/no_send unchanged | ✅ entire prior suite green; flags-off no-op test |

## Activation runbook (FUTURE — not executed)

1. Felipe writes the EXACT approval text from packet section 13.
2. Operator sets deployment metadata: the 7 section-8 flags + the
   approval text verbatim.
3. Run the preflight tool — it must print PASSED and stamp the marker.
4. Restart not required; the next inbound from 8128889241 follows the
   smoke path. Operator watches per the packet's per-turn checklist.
5. Any rollback criterion → run the rollback tool (sends stop on the next
   turn) and preserve evidence.

## Decision

`PHASE_20_SINGLE_CONTACT_SMOKE_PATH_READY`

Implemented, tested and documented with send OFF, exactly as instructed.

---

# Phase 20.1 — Real Grounding Correction (post first-smoke block)

Date: 2026-06-11
Trigger: the first live smoke window was BLOCKED by operator review — the
visible sends were grounded on DryFactsToolExecutor data (the $32,500
quote was harness fixture, not the real Dinamo catalog). Correct call;
the dry executor should have been a preflight blocker.

## What changed (all four items of the correction plan)

1. **Real executor.** `RealFactsToolExecutor` (pure, vertical-agnostic;
   dispatch via the tool binding's `real_source`: catalog_search /
   catalog_quote / knowledge_plans) grounded on data preloaded by
   `product_agents/real_tool_facts.py` from the PUBLISHED tenant tables:
   `catalogs/catalog_items` (34 real Dinamo models with alias groups,
   real lista/contado prices and 10/15/20/30% plan tables) and Knowledge
   OS `knowledge_items` of type `requisitos_plan_credito` (Nómina
   Tarjeta/Recibos, Pensionados, Negocio SAT, Sin Comprobantes, Guardia).
   The bridge selects it ONLY for visible-send-candidate turns; shadow
   and Test Lab keep DryFacts.
2. **Dry facts can never reach a customer.** ToolExecutionResult gains
   `source_kind` (dry executor marks `dry_facts`); the validator blocks
   any visible-send-candidate turn containing dry-facts results with
   non-retryable `live_claim_source_not_real` (fail closed → operator
   paged). Defense in depth: even a mis-wired executor cannot leak
   fixture data.
3. **Canonical send columns.** `evaluate_smoke_send` now ALSO requires
   the deployment's boolean columns (`send_enabled`, `outbox_enabled`,
   `live_send_enabled`, `single_contact_smoke_enabled`) — metadata alone
   never arms sends (`canonical_send_columns_disabled`). Activation tool
   sets them; rollback clears them; preflight checks them plus
   `real_catalog_models_present`, `real_requirement_plans_present` and
   `tool_bindings_have_real_source`.
4. **Handoff-pending tone.** The context note now instructs not to
   mention the pending human/wait in every reply (the takeover pause
   itself had already worked correctly in live).

## End state

Send remains OFF (rollback active, canonical columns false, scope
no_send). 270 tests passing, ruff clean. Re-activation requires:
re-arm with the real_source config through the publish gate, preflight
PASSED (now 18 checks), and Felipe's literal approval text again.

# PHASE 19 — Single-Contact Smoke Approval Packet

Date: 2026-06-10  
Status: Approval packet only — **no smoke activated**  
Decision: **`PHASE_19_SINGLE_CONTACT_SMOKE_APPROVAL_PACKET_READY`**

## 1. Executive Summary

Respond-Style for the real Dinamo tenant has cleared the no-send/shadow gate
required to prepare a controlled single-contact smoke packet. This packet does
not activate smoke, send, live-candidate, canary, production, outbox, workflows,
actions, or any legacy path. It documents the exact scope, gates, rollback, and
human approval text required before a later activation can be considered.

Current state:

- Deployment remains `published_no_send`.
- Runtime remains `test_lab_no_send`.
- Respond-Style shadow is enabled for the allowlisted phone only.
- Model is `gpt-4o`.
- Outbox pending/retry baseline is `0`.
- Recent action/handoff side-effect baseline is `0`.
- No live send flag has been applied in this phase.

Why single-contact smoke is now reasonable:

- Two passing windows are documented: real-traffic Window 3 and final
  confirmation window.
- The final confirmation window validated the known high-risk cases after W6/W7:
  referent resolution, alias-grounded selected model capture, offer vs formal
  handoff, accented/case/orthography allowed-values, captionless media, price
  and requirements grounding, and canonical correction state.
- Legacy customer-copy hard-block evidence and no-send parity/shadow evidence
  exist before any live customer-facing route is considered.

Why this is still **not beta or production**:

- The next proposed step is limited to one approved phone only:
  `8128889241`.
- No canary or production traffic is authorized.
- No workflows/actions are authorized.
- Rollback must be immediate on any failure criterion.
- Human operator log-watching is mandatory.
- Any non-allowlisted contact receiving Respond-Style is a rollback incident.

## 2. Relevant IDs And Current State

| Item | Value |
|---|---|
| `tenant_id` | `6ad78236-1fc9-467a-858d-90d248d57ee5` |
| `agent_id` | `c169deec-226d-55b7-bd07-270f339e75a6` |
| `agent_version_id` | `270574ad-8313-43cb-b0bc-ebf62b1f5214` |
| `agent_version_number` | `7` |
| `deployment_id` | `0a24dc41-b704-47a5-ba4b-519f9561f471` |
| `allowed_phone` | `8128889241` |
| `model` | `gpt-4o` |
| `publish_state` | `published_no_send` |
| `runtime_mode` | `test_lab_no_send` |
| `environment` | `no_send` |
| `channel` | `whatsapp` |
| `commit_hash` | `a5d8087b2df4a8d9a444ae1f7fed9610297a8135` |

Current deployment metadata:

```json
{
  "respond_style_model": "gpt-4o",
  "respond_style_enabled": true,
  "respond_style_inbound_shadow_enabled": true,
  "respond_style_inbound_shadow_allowed_phones": ["8128889241"]
}
```

## 3. Evidence Bundle

### Window 3 — Real-Tenant Shadow

Source: `reports/respond_style_real_shadow_window_3_review_2026_06_10.md`

- Decision: `SHADOW_WINDOW_3_PASSED_READY_FOR_CONFIRMATION_WINDOW`
- Average score: `4.44/5`
- 17/17 turns direct route.
- `legacy_path_used=false` for all turns.
- `send_decision=no_send` and `send_allowed=false` for all turns.
- Outbox rows created in window: `0`.
- Workflow executions in window: `0`.
- Side effects false.
- No unsupported claims.
- No invalid selected model writes accepted.
- No mixed correction values.
- No media hallucination.
- No price/requirements without tool/KB.

### Final Confirmation Window

Source: `reports/respond_style_final_confirmation_window_2026_06_10.md`

- Decision: `FINAL_CONFIRMATION_WINDOW_PASSED_READY_FOR_PHASE_19_SMOKE_PACKET`
- Average score: `4.80/5`
- No turn below `4.0`.
- All hard checks at zero.
- Validated that `"esa cuanto queda?"` resolves Metro, not DNM2.5.
- Buró turn deflects and offers human help without formal handoff.
- Explicit `"pasame con alguien"` produces formal handoff to `ventas`.
- `NOMINA`, `nómina`, `nomina` normalize to canonical `nomina`.
- `"transferencia bancaria no nomina"` corrects to canonical `transferencia`.
- `noviembre -> 5 años` corrects state with audit.
- Captionless image asks for context and does not invent catalog/quote.
- Requirements and price are tool/KB backed.
- Final state canonical:
  `{income_type: transferencia, employment_seniority: "5 años", selected_model: metro-city, budget_concern: caro}`.

## 4. Fixes And Validation Evidence

| Fix / Gate | Evidence |
|---|---|
| F25 unsupported buró/policy claim closed | `reports/real_tenant_shadow_operator_review_2026_06_10.md`, `reports/respond_style_real_shadow_window_3_review_2026_06_10.md` |
| F26 corrections propose state writes | `reports/real_tenant_shadow_operator_review_window2_2026_06_10.md`, `core/tests/agent_runtime/test_respond_style_f18_f19.py` |
| F27 selected_model catalog grounding | `reports/respond_style_real_shadow_window_3_review_2026_06_10.md`, `core/tests/agent_runtime/test_phase_14_agent_service_respond_style.py` |
| F27-ENFORCED allowed_values runtime | `core/tests/agent_runtime/test_phase_14_agent_service_respond_style.py` |
| F28 shadow state hygiene | `tools/setup_real_tenant_respond_style_shadow_2026_06_10.py`, Window 3 started clean |
| F30 clean/canonical corrections | Window 3 and final confirmation field audits |
| D media fallback | Window 3 and final confirmation media checks |
| F31 allowed_values normalization | `core/tests/agent_runtime/test_phase_14_agent_service_respond_style.py` |
| W5-A retryable allowed_values validation | `reports/respond_style_real_shadow_window_5_review_2026_06_10.md`, validator tests |
| W5-B handoff pending awareness | `reports/respond_style_real_shadow_window_5_review_2026_06_10.md`, `core/tests/agent_runtime/test_phase_14_agent_service_respond_style.py` |
| W6-A referent resolution guard | `reports/respond_style_final_confirmation_window_2026_06_10.md`, referent tests |
| W6-B offer vs formal handoff | `reports/respond_style_final_confirmation_window_2026_06_10.md`, handoff tests |
| W7 alias groups for allowed_values/referent grounding | `reports/respond_style_final_confirmation_window_2026_06_10.md`, W7 tests |
| Transcript ordering by `sent_at` | `reports/respond_style_final_confirmation_window_2026_06_10.md`, source order references |

## 5. Test Lab, Legacy Hard-Block, And Parity Evidence

### Test Lab Direct Real gpt-4o

Sources:

- `reports/respond_style_phase_10_fixes_and_test_lab_direct_2026_06_09.md`
- `reports/respond_style_phase_12_docker_e2e_hard_block_2026_06_09.md`
- `reports/respond_style_phase_13_publish_shadow_parity_2026_06_09.md`

Evidence:

- Real OpenAI Test Lab direct reached `RESPOND_STYLE_DIRECT_NO_SEND_READY`.
- Docker E2E persisted an `AgentTestRun` with mode `no_send`, status `passed`,
  and decision `RESPOND_STYLE_DIRECT_NO_SEND_READY`.
- Outbox delta remained `0`.
- Pending/retry remained `0`.

### Hard-Block Legacy Copy

Source: `reports/respond_style_phase_12_docker_e2e_hard_block_2026_06_09.md`

Evidence:

- Direct route import-graph audit blocks legacy copy sources.
- ConversationRunner, composer prompts, composer OpenAI, response contract,
  HumanResponseComposer, StructuredRuntimeComposer, SafeFallbackAgentProvider,
  SendAdapter, outbox, workflows engine, and related copy sources are not
  reachable from the direct route.
- Blocked turns produce `final_message=None`; no canned recovery copy.
- Workflow proposals cannot author visible customer copy.
- No `pending_slot` / `next_best_question` visible artifacts in direct-route
  results.

### Shadow/Parity

Source: `reports/respond_style_phase_13_publish_shadow_parity_2026_06_09.md`

Evidence:

- Inbound shadow is opt-in and no-send.
- Real DB + OpenAI shadow harness passed.
- Parity gate compares no-send vs simulated live-candidate labels through the
  same direct route.
- Legacy path remains false.
- Only send-policy label may differ in parity simulation.

## 6. Audits For Phase 19 Packet

### Outbox Audit

Current preflight baseline:

- `outbound_outbox` pending/retry: `0`

Historical evidence:

- Window 3: outbox rows created in window `0`.
- Final confirmation: outbox `0`.
- Phase 12/13 Docker evidence: outbox delta `0`, pending/retry `0`.

### Side Effects Audit

Current preflight baseline:

- Recent action logs for Dinamo tenant: `0`
- Recent human handoffs for Dinamo tenant: `0`

Historical evidence:

- Window 3: workflow executions in window `0`.
- Final confirmation: side effects `0`.
- Phase 10/12/13: no workflows/actions/delivery.

### Field Audit

Passing evidence:

- `selected_model`: unknown U2 does not write; Metro writes canonical
  `metro-city` via alias group.
- `income_type`: `nomina` and `transferencia` stored as canonical values.
- `employment_seniority`: `noviembre -> 5 años` corrected with audit.
- No annotated values accepted.
- No invalid `selected_model` accepted in passing windows.

### Handoff Audit

Passing evidence:

- Buró/policy uncertainty can offer a human but does not create formal handoff
  unless the customer asks.
- `"pasame con alguien"` creates handoff proposal with target `ventas`.
- Handoff pending awareness prevents repeated cascade in shadow context.

### Referent Audit

Passing evidence:

- Final confirmation validates `"y la metro?"` followed by
  `"esa cuanto queda?"` resolves Metro and uses `quote.resolve` for Metro.
- W7 alias groups allow canonical `metro-city` to be stored when the customer
  used an alias such as "Metro".

### Media Audit

Passing evidence:

- Captionless image produces context request.
- No catalog/quote/model selection is inferred from image alone.
- No selected model is saved from media-only turn.

## 7. Mandatory Preflight Before Any Smoke

The following must be checked immediately before any later smoke activation.
This packet does not perform these changes.

| Preflight item | Required value |
|---|---|
| backend / worker / baileys / postgres | all up and healthy |
| deployment | `0a24dc41-b704-47a5-ba4b-519f9561f471` |
| agent_version | `270574ad-8313-43cb-b0bc-ebf62b1f5214` |
| `respond_style_enabled` | `true` |
| `respond_style_model` | `gpt-4o` |
| legacy customer-facing | disabled or bypassed for `approved_contact_only` |
| send scope | exactly `approved_contact_only` |
| allowed phone | exactly `8128889241` |
| outbox pending/retry before | `0` |
| side effects before | `0` |
| real workflows/actions | disabled |
| rollback command | ready before activation |
| operator | watching live logs |
| eligible contacts | no other contacts eligible |

Suggested read-only preflight commands:

```powershell
docker compose ps
docker compose exec postgres-v2 psql -U atendia -d atendia_v2 -c "select id, tenant_id, agent_id, active_version_id, publish_state, runtime_mode, environment, channel, metadata_json from agent_deployments where id = '0a24dc41-b704-47a5-ba4b-519f9561f471';"
docker compose exec postgres-v2 psql -U atendia -d atendia_v2 -c "select count(*) as outbox_pending_retry from outbound_outbox where status in ('pending','retry');"
docker compose exec postgres-v2 psql -U atendia -d atendia_v2 -c "select count(*) as recent_actions from action_execution_logs where tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5' and created_at > now() - interval '1 hour';"
```

## 8. Proposed Smoke Flags — Do Not Apply In This Packet

These flags are proposed for a later activation only after literal human
approval. They are **not applied** by this packet.

```json
{
  "respond_style_live_send_enabled": true,
  "respond_style_send_scope": "approved_contact_only",
  "respond_style_live_allowed_phones": ["8128889241"],
  "respond_style_workflows_enabled": false,
  "respond_style_actions_enabled": false,
  "respond_style_legacy_fallback_enabled": false,
  "respond_style_fail_closed_notify_operator": true
}
```

Scope invariants:

- `respond_style_send_scope` must not be `tenant`, `all`, `canary`, or
  `production`.
- The only live eligible phone is `8128889241`.
- If the direct route cannot satisfy policy/tool/validator requirements, it
  must fail closed and notify operator; it must not send fallback copy.

## 9. Proposed Single-Contact Smoke Script

Use the allowlisted phone `8128889241` only. Send one message at a time and
wait for the visible response and trace before continuing.

1. `hola`
2. `busco una moto a crédito`
3. `qué motos manejan?`
4. `me interesa la U2`
5. `y la metro?`
6. `esa cuanto queda?`
7. `me pagan por nómina`
8. `realmente es transferencia bancaria no nomina`
9. `tengo desde noviembre`
10. `perdón tengo 5 años`
11. `y si estoy en buró?`
12. `qué ocupo mandar?`
13. `está caro`
14. `pásame con alguien`

Operator must inspect after each turn:

- visible WhatsApp reply,
- `turn_traces`,
- outbox scope,
- side effects,
- selected fields,
- tool usage,
- handoff proposal.

## 10. Success Criteria

The smoke passes only if every item below is true:

- Respond-Style responds visibly to the allowlisted phone.
- Respond-Style does not respond to any other phone.
- No legacy copy is visible to the approved contact.
- `0` outbox rows outside the approved phone scope.
- `0` real workflow/action executions.
- `0` unsupported claims.
- `0` price/requirements without tool or KB.
- `0` invalid field values accepted.
- `0` wrong referent quotes.
- `0` media hallucination.
- Handoff is correct when the customer asks for a human.
- Rollback is not required.

## 11. Immediate Rollback Criteria

Rollback must happen immediately if any of these occur:

- Visible silence without `notify_operator`.
- Legacy/composer/pending-slot response is visible.
- Internal leak reaches the customer.
- Price or requirement is invented.
- Wrong model is quoted.
- Invalid `selected_model` accepted.
- Formal handoff appears prematurely and repeats.
- Outbox write occurs outside the allowlisted phone.
- Real workflow/action executes.
- Tool error is not handled safely.
- Any non-allowlisted contact receives Respond-Style.

## 12. Rollback Commands

These commands are templates for the later activation window. They are not run
by this packet.

Disable live send and return to no-send scope:

```powershell
docker compose exec postgres-v2 psql -U atendia -d atendia_v2 -c "update agent_deployments set metadata_json = metadata_json || '{\"respond_style_live_send_enabled\": false, \"respond_style_send_scope\": \"no_send\", \"respond_style_live_allowed_phones\": [], \"respond_style_workflows_enabled\": false, \"respond_style_actions_enabled\": false, \"respond_style_legacy_fallback_enabled\": false, \"respond_style_fail_closed_notify_operator\": true}'::jsonb where id = '0a24dc41-b704-47a5-ba4b-519f9561f471';"
```

Confirm outbox pending/retry is zero:

```powershell
docker compose exec postgres-v2 psql -U atendia -d atendia_v2 -c "select count(*) as outbox_pending_retry from outbound_outbox where status in ('pending','retry');"
```

Confirm side effects are zero for the incident window:

```powershell
docker compose exec postgres-v2 psql -U atendia -d atendia_v2 -c "select count(*) as recent_actions from action_execution_logs where tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5' and created_at > now() - interval '30 minutes';"
docker compose exec postgres-v2 psql -U atendia -d atendia_v2 -c "select count(*) as recent_handoffs from human_handoffs where tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5' and requested_at > now() - interval '30 minutes';"
```

Export incident traces:

```powershell
docker compose exec postgres-v2 psql -U atendia -d atendia_v2 -c "select id, created_at, conversation_id, inbound_text, router_trigger, composer_output, state_after, kb_evidence, errors from turn_traces where tenant_id = '6ad78236-1fc9-467a-858d-90d248d57ee5' and created_at > now() - interval '30 minutes' order by created_at;" > reports\phase_19_smoke_incident_traces_YYYY_MM_DD_HHMM.txt
```

Operator note: if any outbox row outside the allowed scope exists, stop the
workers before further investigation and preserve all traces/logs. Do not delete
evidence.

## 13. Required Human Approval Text

The next phase may start only if Felipe approves with this exact text:

> Apruebo activar controlled single-contact smoke Respond-Style únicamente para el teléfono 8128889241, con send_scope=approved_contact_only, sin workflows/actions reales, sin canary, sin production, con rollback inmediato ante cualquier criterio de falla.

Any shorter approval, implied approval, or operational shorthand is not enough.

## 13b. Implementation Gap Addendum (accuracy note — added on review)

The flags in section 8 are a CONTRACT, not a switch: today the runtime has
no live-send path at all. Concretely:

- `agent_service_bridge._handle_opted_in_turn` hard-blocks any
  `mode != no_send` with `respond_style_live_not_enabled`.
- The respond-style `SendAdapterResult` is blocked-by-construction
  (`allowed=false`, `outbox_write_attempted=false`) on every turn.
- Live WhatsApp replies still come from the legacy ConversationRunner path
  (currently muted for the pilot conversation by its own `bot_paused`).

Therefore, between THIS approval and the smoke there is one implementation
phase (**PHASE_20_SINGLE_CONTACT_SMOKE_PATH**), itself test-gated, which
must deliver — and nothing more:

1. Bridge smoke mode: when the section-8 flags are present AND the
   contact's phone is in `respond_style_live_allowed_phones`, the validated
   `final_message` may be staged to outbox via SendAdapter; any other
   contact stays shadow/no-send. Allowlist enforced in RUNTIME, not prompt.
2. Legacy suppression for the allowlisted contact only (no double-reply,
   no legacy copy) — without changing ConversationRunner behavior for
   anyone else.
3. 15B wiring: blocked/silent turns notify the operator (no dead air).
4. Bot-pause on accepted handoff (formal proposal -> visible ack ->
   bot stops, human takes over).
5. Tests: allowlist enforcement, non-allowlisted contacts unaffected,
   fail-closed paths never send fallback copy, rollback flags verified to
   stop sends immediately.

Activating the section-8 flags before PHASE_20 ships changes nothing — by
design; flipping them is harmless but ineffective.

## 14. Final Decision

`PHASE_19_SINGLE_CONTACT_SMOKE_APPROVAL_PACKET_READY`

This packet authorizes no runtime change by itself. It only prepares the
approval material for a later, explicitly approved controlled single-contact
smoke.

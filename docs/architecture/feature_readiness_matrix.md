# Feature Readiness Matrix

Date: 2026-06-06  
Status: Active registry  
Canonical architecture: `Arquitectura-Deseada.md`

## States

- `not_started`
- `implemented`
- `connected`
- `shadow`
- `no_send_passed`
- `single_contact_smoke`
- `live_limited`
- `production`
- `blocked`
- `deprecated`

## Feature Matrix

| # | Feature | Current State | Evidence | Risk / Blocker | Next Gate | Pass Criteria |
|---|---|---|---|---|---|---|
| 1 | Agente IA configurable | `connected` | Product Entities API, Agent Builder MVP, DB-backed no-send Test Lab MVP, Publish Control no-send MVP, legacy Agents API/UI | Runtime/legacy config drift; Builder not connected to live runtime | Runtime publish adapter | Agent version publish/rollback works through Product-First gates |
| 2 | Conversacion natural con KB | `blocked` | Knowledge OS, ContextBuilder, tools | Robotic copy and missing source risk | RespondStyleAgentTurn + source health | No factual answer without basis |
| 3 | Fuentes de conocimiento | `connected` | KnowledgeSource, ingestion, retrieval, Product Agent Builder Knowledge tab, draft source bindings | Runtime publish still blocked until Test Lab/Publish Control | DB-backed source readiness | Missing or unhealthy source blocks readiness; live publish remains false |
| 4 | Prompts personalizados | `connected` | Agent instructions/tone/voice | Prompt drift across paths | Prompt blocks | Published version uses immutable blocks |
| 5 | Flujo conversacional | `blocked` | pending slots, memory, progress guard | Repeated questions and stale pending | Slot contract tests | Valid slot answer closes slot |
| 6 | Extraccion de datos | `connected` | semantic/state proposals, StateWriter | Ambiguous writes | Field policy | Writes need evidence and confidence |
| 7 | Actualizacion de campos | `connected` | customer fields, field updates | Critical overwrites | Field policy registry | Unsafe writes blocked |
| 8 | Etapas lifecycle | `connected` | TenantPipeline, LifecycleUpdate | Stage jumps without evidence | Lifecycle policy | Valid transition only |
| 9 | Workflows internos | `shadow` | workflow engine/events | Side effects/copy paths | Workflow bindings | No visible copy override |
| 10 | HTTP/integraciones | `connected` | http_request node, call_webhook action capability, Agent Builder Actions tab | Secret/idempotency/live risk; no live execution from Builder | Action Registry + Test Lab dry-run | Dry-run + approval policy |
| 11 | Handoff humano | `connected` | human_handoffs, handoff UI | Runtime V2 consistency | Handoff policy | Reason + target + trace |
| 12 | Filtrado/calificacion | `implemented` | fields/lifecycle/evals | No unified scoring product | Qualification rules | Tenant rule-driven scoring |
| 13 | Multimodal | `implemented` | attachments, vision, document.check | Voice/audio incomplete | Attachment classifier | Non-text classified before state |
| 14 | Seguimiento automatico | `connected` | followup scheduler/worker | Consent/channel gating | Followup policy | Cancel on reply + quiet hours |
| 15 | Multilingue | `implemented` | language_policy config | Not end-to-end proven | Language tests | Detect/respond with allowed sources |
| 16 | Asignacion equipos | `implemented` | assign action/workflow/advisor pools | Routing ACL/fallback gaps | Routing policy | Deterministic target + fallback |
| 17 | Etiquetado automatico | `implemented` | add_tag action/tags | Auto-tag policy incomplete | Tag policy | Only configured tags applied |
| 18 | No salirse personaje | `blocked` | tone/voice/policy | No strong persona evaluator | Persona tests | Multi-turn tone holds without unsafe claims |
| 19 | No inventar informacion | `blocked` | mandatory tools, quote safety | Generic fallback risk | Claim basis checks | Every factual claim has basis |
| 20 | Respuestas no roboticas | `blocked` | Transitional ValidatedResponsePlanBuilder/HumanResponseComposer tests and Test Lab evidence fields | Published Product Agents still need RespondStyleAgentTurn; legacy composer and slot-first copy remain live-readiness blockers | RespondStyleAgentTurn Test Lab + replay + multi-tenant simulations | `final_message` comes from LLM turn plus validated facts/tools, with no slot-template or fallback visible copy |
| 21 | Limites y seguridad | `connected` | PolicyValidator/send policy, Test Lab no-send run/audit records | Recovery UX can repeat/block badly | Fail-closed suite + Publish Control gate | Required tool/policy failures no-send |
| 22 | Automatizacion sin reconstruir | `implemented` | workflow engine + events | Event contracts incomplete | Event bridge | Existing workflow consumes normalized event |
| 23 | Acciones configurables | `connected` | Product capability registry, draft Action Binding API, Agent Builder Actions tab | Live write risk; actions configured but not executed in no-live Builder | Action binding readiness + Publish Control | Unauthorized actions blocked; send boundary remains disabled |
| 24 | Adjuntos via workflow | `implemented` | attachments/document tools/events | Not productized for all tenants | Attachment workflow binding | Document state only from tool/task |
| 25 | Trazabilidad decisiones | `connected` | universal_turn_trace/UI/tests | Not yet publish gate | Trace gate | Trace completeness required for publish |

## Publish Control MVP Status - 2026-06-07

Publish Control is now `connected` as a no-send MVP. It provides durable
tenant-scoped publish requests, create/latest/evaluate/approve-no-send/reject
APIs, Product Agent Builder Publish tab, readiness blockers, latest Test Lab run
evidence, trace id requirement, outbox and side-effect audit checks, rollback
target validation, and safe transition to `published_no_send`.

It does not enable live send, WhatsApp, outbox writes, actions, workflow side
effects, canary, smoke, or open production. Future advancement to
`single_contact_smoke` or `live_limited` requires a separate approved phase and
completed DoD.

## Test Lab MVP Status - 2026-06-07

DB-backed Test Lab is now `implemented` as a no-send MVP inside Product Agent
Builder. It supports tenant-scoped suites, scenarios, durable test runs,
AgentService no-send execution, exact final message evidence, trace ids, tool
results, send status, state persistence, outbox audit, and side-effect audit.

Behavior validation is verified. It records per-turn input, exact output, tools
required/executed/skipped/failed, state writes, policy result, send decision,
trace id, pass/fail, and expected-vs-actual failures. It also wires latest Test
Lab run status into readiness as `test_lab_passed` or `test_lab_failed`.

Current verification status: backend lint passed, backend Product Agent tests
passed with 100% coverage for `atendia.product_agents` and product agent API
routes, OpenAI provider unit tests passed, frontend Biome passed, and Product
Agent Builder Test Lab UI tests passed with 100% statements/branches/functions/
lines for the modified component.

`agent_service_real` no-send mode is implemented and test-verified with guarded
limits, token/cost evidence, OpenAI provider usage capture, required tool/policy
blocking, and UI display. Actual OpenAI scenario execution is currently blocked
in this local environment because `OPENAI_API_KEY` is not present.

It is not a live-send gate. Advancement beyond no-send still requires separate
approval, Publish Control consumption of the verified latest required run
evidence, and no-send/live-candidate parity for send scope.

## Readiness Advancement Rules

- `implemented` means code or docs exist, but not necessarily wired end to end.
- `connected` means there is a real path through backend/UI/runtime or DB.
- `shadow` means it can run without live side effects.
- `no_send_passed` requires DB-backed Test Lab proof.
- `single_contact_smoke` requires explicit approval and rollback.
- `live_limited` requires Publish Control and allowlist/segment scope.
- `production` requires DoD, trace, tests, rollback, and no legacy interference.
- `blocked` requires a blocker entry before work starts.

## Cross-Cutting Blockers

- No Product-First feature may advance to publish if legacy can overwrite
  visible output.
- No feature may claim live readiness from fixtures.
- No feature may skip changed-behavior tests and coverage.
- No feature may bypass Codex code review before implementation handoff.

## Active Contract References

- Agent Builder identity, draft editing, readiness, non-live boundaries, and
  remaining MVP gaps are governed by
  `docs/architecture/product_first_agent_builder.md`.
- Knowledge Source readiness, source health, Source Binding, retrieval preview,
  and publish blockers are governed by
  `docs/architecture/product_first_knowledge_sources.md`.
- Runtime single route, AgentService ownership, SendAdapter boundary,
  fail-closed behavior, and legacy visible-output limits are governed by
  `docs/architecture/product_first_runtime_single_route.md`.
- DB-backed Test Lab suites, scenarios, parity, assertions, evidence, and
  publish blockers are governed by
  `docs/architecture/product_first_test_lab.md`.
- Publish states, approvals, send scopes, rollback, readiness gates, DoR, and
  DoD dependencies are governed by
  `docs/architecture/product_first_publish_control.md`.
- Action definitions, bindings, schema, risk, mode, approval, idempotency,
  retry, audit, and publish blockers are governed by
  `docs/architecture/product_first_action_registry.md`.
- Workflow bindings, normalized events, customer-copy boundary, side-effect
  modes, loop guards, publish blockers, and trace are governed by
  `docs/architecture/product_first_workflow_bindings.md`.
- Inbox Trace UX surfaces, panels, redaction, access, blockers, and exact final
  message review are governed by
  `docs/architecture/product_first_inbox_trace_ux.md`.
- Legacy isolation states, gates, runtime rules, migration rules, and publish
  blockers are governed by
  `docs/architecture/product_first_legacy_isolation.md`.
- Controlled Dinamo beta prerequisites, tenant-data boundary, evidence packet,
  scenarios, publish blockers, and future tests are governed by
  `docs/architecture/product_first_controlled_beta_dinamo.md`.
- Legacy customer-copy decommission is governed by
  `docs/architecture/product_first_legacy_decommission_plan.md`.
- Respond-Style runtime implementation is governed by
  `docs/architecture/respond_style_runtime_implementation_plan.md`.
- Builder capability completeness is governed by
  `docs/architecture/product_builder_capability_matrix.md`.
- Live readiness, Test Lab parity, and rollback gates are governed by
  `docs/architecture/product_first_live_readiness_test_lab_rollback_gate.md`.

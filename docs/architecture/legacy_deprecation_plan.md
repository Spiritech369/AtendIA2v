# Legacy Deprecation Plan

Date: 2026-06-06  
Status: Active classification plan  
Canonical architecture: `Arquitectura-Deseada.md`

Companion isolation contract:
`docs/architecture/product_first_legacy_isolation.md`

## Classification Legend

- **KEEP**: Keep as current non-conflicting capability.
- **MERGE**: Merge behind Product-First AgentService or control-plane contract.
- **DEGRADE**: Keep temporarily with reduced authority or no visible output.
- **BLOCK_FOR_V2**: Must not run for published Runtime V2/Product-First agents.
- **DELETE_LATER**: Remove after tests, migration, and rollback exist.
- **UNKNOWN_NEEDS_AUDIT**: Insufficient evidence; audit before changing.

## Component Matrix

| Component | Today | Risk | Decision | Removal/Merge Gate | Required Test |
|---|---|---|---|---|---|
| ConversationRunner | Legacy live runner with many decision branches | Parallel visible response path, tenant-specific heuristics, hard to reason about no-send/live parity | **BLOCK_FOR_V2** then **DEGRADE** | ProductAgentRuntime direct entrypoint owns published Product-First agents | `published_product_agent_never_enters_conversation_runner` |
| Legacy runner | Pre-Runtime V2 response/state/action path | Can bypass Product-First control plane | **BLOCK_FOR_V2** | Deployment Resolver routes Product-First agents only to AgentService | no legacy visible output for published deployment |
| Old advisor brain / sales decision policy | Domain-specific decision policy and heuristics | Keyword routing and vertical leakage | **DEGRADE** | Tenant-aware SemanticInterpreter and tools cover behavior | `trabajo_not_model`, pending slot tests |
| Old response_contract / response_frame | Legacy customer response shaping | May produce visible copy outside `TurnOutput.final_message` | **BLOCK_FOR_V2** | RespondStyleAgentTurn and Policy own final copy | `workflow_cannot_override_final_message` |
| ConversationProgressGuard | Guards or normalizes progress | Can rewrite output to generic progress copy | **MERGE** | Guard emits structured decisions only; no final copy override | `composer_no_fixed_copy_when_context_sufficient` |
| StructuredRuntimeComposer | Runtime V2 deterministic composer with fixed branches | Robotic repeated answers | **BLOCK_FOR_V2** then **DELETE_LATER** | RespondStyleAgentTurn plus validator feedback loop covers published Product Agent copy | non-robotic respond-style tests |
| HumanResponseComposer | Transitional customer-copy composer over validated plans | Still depends on slot-plan authority and can mask missing context | **DEGRADE** then **DELETE_LATER** | RespondStyleAgentTurn owns `TurnOutput.final_message` for published Product Agents | `human_response_composer_blocked_for_published_product_agents` |
| ValidatedResponsePlanBuilder | Builds slot-first response plans with pending slot and next question | Can turn state gaps into scripted customer questions | **MERGE** as structured signal only then **DEGRADE** | Validator and field/tool policies expose missing data without writing copy | `validated_response_plan_not_visible_copy_authority` |
| Manual recovery visible | Recovery text exposed to customer | Internal/debug copy leakage | **BLOCK_FOR_V2** | Recovery writes trace only or handoff/no-send | `internal_text_never_visible` |
| Provider fallback visible | Fallback text after model/provider failure | Generic copy can leak or mask failures | **BLOCK_FOR_V2** | Provider failure maps to no-send/handoff trace | `policy_failure_no_send` |
| Workflow copy paths | Workflow nodes that can send customer text | Can bypass TurnOutput/SendAdapter | **BLOCK_FOR_V2** | Workflows consume events only for V2 published agents | workflow cannot override final message |
| Smoke-only logic | Single-contact or smoke flags and special cases | Can become production behavior by accident | **DEGRADE** | Publish Control replaces smoke state machine | feature readiness blocks publish |
| Fixture-only preflight | Tests using fixtures instead of DB-backed tenant | False readiness | **DEGRADE** | DB-backed Test Lab exists | `test_lab_db_backed` |
| Hardcoded Dinamo logic | Tenant/vertical rules in shared code | Breaks multi-tenant platform | **BLOCK_FOR_V2** | Tenant domain contract / Knowledge OS carries rules | multitenant no-hardcode tests |
| Dispersed send flags | `send_enabled`, `outbox_enabled`, `live_send_enabled`, smoke/canary flags | Unsafe combinations and unclear live state | **MERGE** | Publish Control state drives send policy | `outbox_only_after_send_decision` |
| Old docs/specs contradicting Product-First | Stale reports or docs | Future agents follow wrong authority | **DEGRADE** | ADR precedence and source alignment complete | docs precedence grep check |
| Outbox worker | Delivery mechanism | Needed but must not decide copy | **KEEP** | SendAdapter remains sole enqueue gate | outbox only after send decision |
| Universal turn trace | Runtime audit | Strong Product-First asset | **KEEP** | Expand trace completeness as features move live | `trace_completeness` |
| Knowledge OS | Tenant facts and retrieval | Needed; source health gaps remain | **KEEP** / **MERGE** | Source bindings and health become publish blockers | missing source blocks publish |
| Workflow engine | Existing automation engine | Valuable but side effects must be gated | **KEEP** / **MERGE** | Product-First workflow bindings control side effects | no side effects in Test Lab |

## Rules Before Removing Anything

1. Verify the component is not needed by non-Product-First tenants.
2. Add tests for the replacement path.
3. Prove rollback.
4. Update Feature Readiness and ADRs.
5. Get explicit approval for deletion.

## Immediate Blockers

- Any visible copy path outside `TurnOutput.final_message`.
- Any Product-First published agent that can fall back to legacy visible output.
- Any workflow that can send text outside SendAdapter.
- Any fixture-only readiness claim for live.

## Phase 11 Acceptance

Fase 11 is complete when:

- all minimum legacy components are classified
- Product-First isolation states and gates are documented
- publish blockers are documented
- migration rules before deletion are documented
- future tests are documented
- no legacy code was deleted or modified

Decision for this documentary phase:

`PRODUCT_FIRST_PHASE_11_LEGACY_CLASSIFICATION_CONFIRMED_DOCS_ONLY`

# Customer Copy Kill Map

Date: 2026-06-09
Status: Active implementation artifact for Product-First Live Stable Fase 1
Canonical source: `Arquitectura-Deseada.md`
Approved scope: Fase 1 and Fase 2, no live activation

## Purpose

This map identifies every known source that can create, repair, replace, or send
customer-facing text outside the target Respond-Style Product Agent route.

Target invariant:

```txt
Published Product Agent
-> RespondStyleAgentTurn proposes final_message
-> AtendIA validates
-> TurnOutput.final_message is the only visible text authority
-> SendAdapter is the only send boundary
```

This document does not delete legacy code and does not activate WhatsApp,
outbox, workflows, actions, smoke, canary, or production.

## Decision Legend

- `KEEP_INTERNAL_ONLY`: allowed only for structured trace, diagnostics, or
  delivery mechanics; no customer copy authority.
- `BLOCK_FOR_PRODUCT_AGENT`: must not run for published Product Agents.
- `DEGRADE_TO_LEGACY_ONLY`: may remain for non-migrated legacy tenants only.
- `REPLACE_WITH_LLM_TURN`: future behavior belongs in RespondStyleAgentTurn.
- `DELETE_LATER`: remove after replacement tests, migration, and rollback exist.

## Kill Map

| Source | File / module | Function / class | Live/Test route | Can reach customer? | Current risk | Future decision | Required blocking test |
|---|---|---|---|---|---|---|---|
| ConversationRunner | `core/atendia/runner/conversation_runner.py` | `ConversationRunner.run_turn` and prepared-turn bridge | WhatsApp/Baileys inbound today | Yes | Published Product Agent can still be bridged from legacy entrypoint | `BLOCK_FOR_PRODUCT_AGENT` | `published_product_agent_never_enters_conversation_runner` |
| legacy response contract | `core/atendia/runner/response_contract.py` | response rewrite/render helpers | legacy runner | Yes | Can rewrite visible copy after composer output | `BLOCK_FOR_PRODUCT_AGENT` | `legacy_response_contract_cannot_override_final_message` |
| legacy response frame | `core/atendia/runner/response_frame.py` | response framing helpers | legacy runner | Yes | Can impose legacy conversational frame | `BLOCK_FOR_PRODUCT_AGENT` | `legacy_response_frame_blocked_for_product_agent` |
| legacy composer prompt | `core/atendia/runner/composer_prompts.py` | `build_composer_prompt` | ConversationRunner fallback | Yes | Prompt path can author customer copy outside Product Agent runtime | `DEGRADE_TO_LEGACY_ONLY` | `composer_prompts_not_used_for_published_product_agent` |
| legacy OpenAI composer | `core/atendia/runner/composer_openai.py` | composer provider | ConversationRunner fallback | Yes | Parallel model path can author visible copy | `DEGRADE_TO_LEGACY_ONLY` | `composer_openai_not_used_for_published_product_agent` |
| StructuredRuntimeComposer | `core/atendia/agent_runtime/advisor_pipeline.py` | `StructuredRuntimeComposer` | Runtime V2 semantic path | Yes | Deterministic branches can author fixed slot/progress copy | `REPLACE_WITH_LLM_TURN` then `DELETE_LATER` | `structured_runtime_composer_blocked_for_published_product_agent` |
| HumanResponseComposer | `core/atendia/agent_runtime/human_response_composer.py` | `HumanResponseComposer.compose` | Runtime V2/Test Lab transitional | Yes | Still depends on slot-first response plan and visible repairs | `REPLACE_WITH_LLM_TURN` then `DELETE_LATER` | `human_response_composer_blocked_for_published_product_agent` |
| ValidatedResponsePlanBuilder | `core/atendia/agent_runtime/validated_response_plan.py` | `ValidatedResponsePlanBuilder.build` | Runtime V2/Test Lab transitional | Indirectly | Converts `pending_slot` and `next_best_question` into copy authority | `KEEP_INTERNAL_ONLY` for structured signal, then `DELETE_LATER` | `validated_response_plan_not_visible_copy_authority` |
| advisor pipeline fallback | `core/atendia/agent_runtime/advisor_pipeline.py` | fallback helpers and safe outputs | Runtime V2 provider/semantic fallback | Yes | Can mask failure with visible generic copy | `BLOCK_FOR_PRODUCT_AGENT` | `advisor_pipeline_fallback_is_no_send_for_product_agent` |
| MandatoryToolGuard rewrite | `core/atendia/agent_runtime/mandatory_tools.py` | final-message blockers and fallback selection | Runtime V2 policy/tool guard | Yes | Can replace unsafe copy with fallback copy instead of no-send/retry | `KEEP_INTERNAL_ONLY` plus no-send for Product Agents | `mandatory_tool_guard_does_not_write_product_agent_copy` |
| QuoteSafetyGuard rewrite | `core/atendia/agent_runtime/quote_safety.py` | quote safety guard | Runtime V2 policy guard | Yes | Can repair quote copy instead of forcing tool/validator loop | `KEEP_INTERNAL_ONLY` plus no-send for Product Agents | `quote_safety_guard_does_not_write_product_agent_copy` |
| Policy repair messages | `core/atendia/agent_runtime/policy_validator.py` and send policy modules | policy errors / repair text | Runtime V2 policy | Potentially | Policy can become conversational strategy instead of safety gate | `KEEP_INTERNAL_ONLY` | `policy_validator_returns_structured_blockers_only` |
| provider fallback | `core/atendia/agent_runtime/model_provider.py` | `SafeFallbackAgentProvider`, `_safe_fallback_output` | Runtime V2 provider failure | Yes | Provider failure can create customer-visible fallback | `BLOCK_FOR_PRODUCT_AGENT` | `provider_fallback_visible_copy_blocks_send` |
| manual recovery | runner/runtime recovery branches | exception and recovery messages | legacy and transitional paths | Yes | Internal recovery can leak as customer copy | `BLOCK_FOR_PRODUCT_AGENT` | `manual_recovery_never_visible_for_product_agent` |
| tool failure messages | tool layer and mandatory tool guard | tool error/failure text | Runtime V2 tool path | Potentially | Tool errors can become visible copy | `KEEP_INTERNAL_ONLY` | `tool_failure_is_structured_blocker_not_final_message` |
| workflow copy | workflow engine/nodes/bridges | workflow send/message nodes and bridge results | workflow engine | Yes | Workflow can bypass `TurnOutput.final_message` and SendAdapter | `BLOCK_FOR_PRODUCT_AGENT` | `workflow_customer_copy_blocked_for_product_agent` |
| handoff copy | `core/atendia/runner/handoff_helper.py` and runtime handoff helpers | handoff visible text | legacy/runtime handoff | Yes | Handoff can invent customer copy outside LLM turn | `KEEP_INTERNAL_ONLY` or `REPLACE_WITH_LLM_TURN` | `handoff_proposal_does_not_override_final_message` |
| workflow bridge | `core/atendia/agent_runtime/workflow_bridge.py` | `evaluate_workflow_bridge` / trace attachers | Runtime V2 workflow preview | No intended visible copy | Low if kept structured | `KEEP_INTERNAL_ONLY` | `workflow_bridge_result_has_no_visible_copy` |
| workflow events | `core/atendia/agent_runtime/workflow_events.py` | `AgentWorkflowEventEmitter` | Runtime V2 event emission | No intended visible copy | Event metadata could become a copy bypass if misused | `KEEP_INTERNAL_ONLY` | `workflow_events_are_structured_only` |
| SendAdapter | `core/atendia/agent_runtime/send_adapter.py` | `RuntimeV2SendAdapter.apply` | no-send/live-candidate boundary | Yes, delivery only | Must not compose, repair, or substitute text | `KEEP_INTERNAL_ONLY` | `send_adapter_never_composes_or_repairs_copy` |
| outbox worker | runner outbound dispatcher | `enqueue_messages` consumer path | delivery | Yes, delivery only | Must not decide copy | `KEEP_INTERNAL_ONLY` | `outbox_only_after_send_adapter_approval` |
| Product Agent Test Lab evidence | `core/atendia/product_agents/test_lab.py` | turn result/evidence fields | no-send Test Lab | No live send | Evidence currently records transitional composer fields | `REPLACE_WITH_LLM_TURN` evidence | `test_lab_records_respond_style_turn_evidence` |

## Publish Blockers

Publish Control must block Product Agent live scope when any affected source is:

- unclassified
- capable of customer-visible output
- reachable from published Product Agent runtime
- able to bypass `TurnOutput.final_message`
- able to bypass SendAdapter
- able to emit workflow/action/customer-copy side effects in Test Lab/no-send

## Fase 1 Decision

Decision marker:

`CUSTOMER_COPY_SOURCES_MAPPED`

This marker is documentary evidence only. It does not prove live readiness and
does not authorize deletion, send, smoke, canary, action side effects, workflow
side effects, or production traffic.


## Amendment 2026-06-09 (Phase 12)

Added source missed by the original map:

| Source | File / module | Function / class | Live/Test route | Can reach customer? | Current risk | Future decision | Required blocking test |
|---|---|---|---|---|---|---|---|
| ConversationProgressGuard | `core/atendia/agent_runtime/conversation_progress.py` | `_progress_fallback` variants | Runtime V2 semantic + structured | Yes — REWRITES with ~18 canned variants | Replaces repetitive copy instead of forcing retry/no-send | `BLOCK_FOR_PRODUCT_AGENT` | `progress_guard_never_rewrites_product_agent_copy` |

Hard-block battery implemented:
`core/tests/agent_runtime/test_product_agent_legacy_copy_hard_block.py`
proves by transitive import graph (fresh interpreter) that the published
Product Agent direct route cannot load ConversationRunner, composers
(HumanResponseComposer / StructuredRuntimeComposer / legacy prompts),
ValidatedResponsePlan, ConversationProgressGuard, QuoteSafetyGuard,
MandatoryToolGuard, SafeFallbackAgentProvider, SendAdapter, AgentService,
outbox, or the workflow engine — plus output-structure tests for the
handoff/workflow/fallback/plan-artifact rows above.

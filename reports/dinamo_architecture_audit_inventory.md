# Dinamo Architecture Audit Inventory

Generated: 2026-06-03

Scope: read-only audit of AtendIA/Dinamo runtime architecture. No runtime, configuration, prompt, workflow, database, or test behavior was changed.

Final decision: ARCHITECTURE_NEEDS_TOOL_CONTRACT_FIRST

## Executive Summary

AtendIA already contains most of the primitives needed for the target architecture: a v2 runtime contract, typed turn output, deterministic tools, a state writer, quote safety, workflow execution, lifecycle evaluation, shadow mode, rollout policy, traces, and eval harnesses.

The system is not yet fully migrated to that architecture. The live path still depends on the legacy `ConversationRunner` with Dinamo-specific bridge logic, prompt-heavy advisor rules, mixed field names, and multiple tool naming/contracts. The strongest next step is not another prompt rewrite. It is to formalize the mandatory tool contract first, then bind state writing and workflow triggers to that contract.

## Main Runtime Surfaces

| Area | Files | Responsibility | Status |
| --- | --- | --- | --- |
| WhatsApp inbound | `core/atendia/webhooks/meta_routes.py`, `core/atendia/queue/inbound_burst.py` | Receive, persist, debounce, and enqueue inbound messages | EXISTS |
| Live runner | `core/atendia/runner/conversation_runner.py` | Main production turn orchestration and legacy fallback path | EXISTS_BUT_LEGACY |
| Dinamo bridge | `core/atendia/runner/dinamo_agent_runtime.py` | Agent-first Dinamo path with tool calls, state writes, quote/doc guards, final response | EXISTS_BUT_TENANT_SPECIFIC |
| Runtime v2 | `core/atendia/agent_runtime/runtime.py`, `schemas.py` | Typed turn contract, provider interface, `TurnOutput.final_message` authority | EXISTS |
| Advisor provider | `core/atendia/agent_runtime/advisor_pipeline.py` | Advisor brain, tool execution, StateWriter, composer, guards, reliability layer | EXISTS_PARTIAL_INTEGRATION |
| Shadow and rollout | `core/atendia/agent_runtime/shadow_service.py`, `rollout_policy.py`, `pilot_policy.py` | Preview, shadow, canary and send/action/workflow gating | EXISTS |
| Post-turn actions | `core/atendia/agent_runtime/post_turn_executor.py` | Execute structured actions after final response with dry-run and policy gates | EXISTS |
| Workflow events | `core/atendia/agent_runtime/workflow_events.py` | Translate `TurnOutput` into workflow events | EXISTS_PARTIAL_CONTRACT |

## Prompt And Response Surfaces

| Area | Files | Responsibility | Finding |
| --- | --- | --- | --- |
| Human advisor prompt | `core/atendia/runner/advisor_brain_prompt.py` | Francisco identity, flow rules, business constraints, tool requests | Too much business logic remains in prompt |
| Dinamo source prompt | `docs/Prompt Agente IA.txt` | Full sales flow, plan/down payment mapping, requirements logic, escalation text | Should be reduced to behavior contract |
| Final response builder | `core/atendia/runner/agent_final_response.py` | Builds customer-facing response from structured data | Important bridge toward single-copy authority |
| Response frame/contract | `core/atendia/runner/response_frame.py`, `response_contract.py` | Legacy formatting and response safety constraints | Useful but should defer facts to tools |
| Composer | `core/atendia/runner/composer_prompts.py`, `composer_openai.py`, `core/atendia/agent_runtime/advisor_pipeline.py` | Natural-language copy generation | Should be copy-only after tools/state decisions |

## Deterministic Tools And Data Sources

| Area | Files | Responsibility | Finding |
| --- | --- | --- | --- |
| Catalog search | `core/atendia/tools/search_catalog.py`, `core/atendia/tools/deterministic.py`, `core/atendia/commercial_catalog_service.py` | Tenant-scoped catalog retrieval and model resolution | Exists, but target needs one mandatory contract |
| Quote | `core/atendia/tools/quote.py` | Structured quote result from catalog/pricing data | Exists, but v2 guard expects `quote.resolve` semantics |
| Credit plan | `core/atendia/tools/deterministic.py`, `core/atendia/credit_plan_invariants.py` | Plan/enganche resolution and plan menu | Exists, but plan specs are globally hardcoded |
| Requirements | `core/atendia/tools/lookup_requirements.py`, `core/atendia/contact_memory/document_checklist.py` | Tenant pipeline requirements and checklist reconciliation | Strong foundation |
| FAQ | `core/atendia/tools/lookup_faq.py`, `docs/FAQ_DINAMO.json` | Tenant FAQ answers | Exists, but FAQ overlaps with plans/requirements |
| Dinamo KB helper | `core/atendia/dinamo_atendia_kb.py` | Dinamo-specific catalog/FAQ/requirement helper | Useful for replay/tests, not tenant-neutral target |
| Source files | `docs/CatalogoMotos2026_DINAMO.json`, `docs/Requisitos_Credito_Dinamo.json`, `docs/FAQ_DINAMO.json` | Catalog, requirements, FAQ source data | Good source separation, but routing must be enforced |

## State, Contact Memory, And Lifecycle

| Area | Files | Responsibility | Finding |
| --- | --- | --- | --- |
| StateWriter v2 | `core/atendia/agent_runtime/state_writer.py` | Apply validated field updates, quote snapshots, docs lifecycle constraints | Strong target component |
| Legacy state policy | `core/atendia/runner/state_write_policy.py` | Protect legacy/Dinamo state writes | Partial bridge |
| Operational reconciliation | `core/atendia/contact_memory/operational_state.py` | Derive canonical operational state from tenant config and field aliases | Important for mixed legacy names |
| Document checklist | `core/atendia/contact_memory/document_checklist.py` | Build and reconcile plan-scoped document checklist | Strong target component |
| Lifecycle | `core/atendia/lifecycle/service.py`, `core/atendia/state_machine/pipeline_evaluator.py` | Stage suggestion/application and rule evaluation | Exists, but trigger naming needs standardization |
| Pipeline contracts | `core/atendia/contracts/pipeline_definition.py` | Condition and document requirement definitions | Exists, but keyword-like `contains` is still available |

## Workflows, Side Effects, And Handoff

| Area | Files | Responsibility | Finding |
| --- | --- | --- | --- |
| Workflow engine | `core/atendia/workflows/engine.py` | Validate and execute workflow definitions with idempotency | Strong base |
| Agent workflow events | `core/atendia/agent_runtime/workflow_events.py` | Emits agent turn, low confidence, human needed, lifecycle proposed, actions, risk flags | Exists, but business event names are partial |
| Post-turn executor | `core/atendia/agent_runtime/post_turn_executor.py` | Executes actions after visible copy | Correct separation of copy and side effects |
| Handoff | `core/atendia/runner/handoff_helper.py`, `core/atendia/api/handoffs_routes.py` | Human escalation and queue handling | Exists |
| Outbound/followups | `core/atendia/runner/outbound_dispatcher.py`, `core/atendia/outbound/` | Message dispatch and scheduled followups | Exists, but should only consume deterministic events |

## Guards, Reliability, And Observability

| Area | Files | Responsibility | Finding |
| --- | --- | --- | --- |
| Quote safety | `core/atendia/agent_runtime/quote_safety.py` | Block or rewrite unsafe quote/price visible text | Strong target component |
| Conversation progress | `core/atendia/agent_runtime/conversation_progress.py` | Reduce repeated fallback/questions and ensure product-change acknowledgement | Useful guard |
| Provider reliability | `core/atendia/agent_runtime/provider_reliability.py` | Retry/circuit breaker/fallback accounting | Strong base |
| Turn tracing | `core/atendia/agent_runtime/tracing.py`, `core/atendia/api/turn_traces_routes.py` | Trace provider/tool/action decisions | Exists |
| Why-this-answer | `core/atendia/observability/why_answer.py` | Explain answer sources, actions, policy, lifecycle, workflow evidence | Strong traceability primitive |
| Eval and simulation | `core/atendia/eval_lab/`, `core/atendia/simulation/`, `core/tests/agent_runtime/`, `core/tests/simulation/` | Regression, readiness, provider batteries, shadow analytics | Exists |

## Files, Classes, Functions And Responsibilities

| Component | File | Classes / Functions | Responsibility |
| --- | --- | --- | --- |
| Runtime v2 provider contract | `core/atendia/agent_runtime/runtime.py` | `AgentRuntime.run_turn`, `AgentTurnProvider`, `DeterministicAgentProvider` | Defines the turn execution interface and provider abstraction |
| Runtime v2 schemas | `core/atendia/agent_runtime/schemas.py` | `TurnOutput`, `ToolExecutionResult`, `ActionResult` | Makes `TurnOutput.final_message` the only visible final copy authority and keeps tools/actions structured |
| Advisor-first provider | `core/atendia/agent_runtime/advisor_pipeline.py` | `AdvisorFirstAgentProvider`, `StructuredRuntimeComposer`, `_safe_advisor_output`, `_safe_composer_fallback` | Runs advisor brain, tools, StateWriter, composer, guards and reliability fallbacks |
| State writer | `core/atendia/agent_runtime/state_writer.py` | `DeterministicStateWriter.build_updates` | Accepts/rejects field writes, quote snapshots, document lifecycle updates and invalidations |
| Quote safety | `core/atendia/agent_runtime/quote_safety.py` | `QuoteSafetyGuard` | Validates visible quote/price text against trusted quote evidence |
| Progress guard | `core/atendia/agent_runtime/conversation_progress.py` | `ConversationProgressGuard` | Blocks repeated fallback/questions and stale progress behavior |
| Provider reliability | `core/atendia/agent_runtime/provider_reliability.py` | `ProviderReliabilityLayer` | Retries, circuit breaker and fallback accounting |
| Workflow event bridge | `core/atendia/agent_runtime/workflow_events.py` | `build_agent_workflow_events`, event persistence/evaluation helpers | Translates accepted turn output into workflow events |
| Post-turn actions | `core/atendia/agent_runtime/post_turn_executor.py` | `PostTurnExecutor`, action validators | Executes structured actions with gates, dry-run and policy checks |
| Shadow runtime | `core/atendia/agent_runtime/shadow_service.py` | `AgentRuntimeShadowService.run_shadow_for_inbound` | Runs v2 in shadow after legacy live turns without affecting production |
| Live runner | `core/atendia/runner/conversation_runner.py` | `ConversationRunner.run_turn`, `_persist_dinamo_agent_first_turn` | Current live turn orchestration and Dinamo bridge persistence |
| Dinamo bridge | `core/atendia/runner/dinamo_agent_runtime.py` | `select_dinamo_runtime`, `run_dinamo_agent_turn`, `_build_initial_plan` | Dinamo agent-first bridge that still mixes intent, tools, state proposals and copy |
| Advisor prompt | `core/atendia/runner/advisor_brain_prompt.py` | `_SYSTEM_PROMPT`, `_FLOW_RULES`, `_POST_QUOTE_RULES`, `_BUSINESS_RULES`, `_AVAILABLE_TOOLS` | Prompt-heavy Francisco behavior and business flow instructions |
| Final response builder | `core/atendia/runner/agent_final_response.py` | `build_agent_final_response` | Builds final customer-facing copy from structured plan/tool evidence |
| Catalog tool | `core/atendia/tools/search_catalog.py` | `search_catalog` and helper resolvers | Tenant-scoped catalog/model search |
| Quote tool | `core/atendia/tools/quote.py` | `quote` resolver functions | Structured quote result from catalog/pricing data |
| Deterministic facade | `core/atendia/tools/deterministic.py` | `list_catalog`, `resolve_credit_plan`, `get_missing_documents` | Public deterministic helpers for catalog, plan and documents |
| Requirements tool | `core/atendia/tools/lookup_requirements.py` | `lookup_requirements` | Plan-scoped requirements from pipeline configuration |
| FAQ tool | `core/atendia/tools/lookup_faq.py` | `lookup_faq` | Tenant FAQ retrieval |
| Credit invariants | `core/atendia/credit_plan_invariants.py` | `build_credit_plan_menu`, plan specs/aliases | Hardcoded current Dinamo commercial plan mapping that should move to tenant data/config |
| Operational state | `core/atendia/contact_memory/operational_state.py` | `OperationalStateReconciler` | Canonicalizes field aliases and derives operational state from tenant config |
| Document checklist | `core/atendia/contact_memory/document_checklist.py` | checklist build/reconcile helpers | Plan-scoped document checklist state |
| Workflow engine | `core/atendia/workflows/engine.py` | `evaluate_event`, `validate_definition`, `_record_action` | Validates and executes workflows with idempotent action records |
| Pipeline evaluator | `core/atendia/state_machine/pipeline_evaluator.py` | `evaluate_condition`, `select_best_stage`, `evaluate_pipeline_rules` | Deterministic stage selection from fields and document requirements |
| Lifecycle service | `core/atendia/lifecycle/service.py` | lifecycle validation/application helpers | Applies or proposes pipeline stage changes |
| Why-answer | `core/atendia/observability/why_answer.py` | why-answer builder | Explains answer evidence, tools, policy, workflows and actions |

## Critical Boundaries To Preserve

1. `TurnOutput.final_message` remains the only customer-visible final copy authority.
2. Tools and actions return structured data, not final response text.
3. Quote, price, down payment, requirements, stage changes, and workflow side effects must be derived from tools/state/workflows, not free-form prompt memory.
4. Dinamo-specific rules must not move into `agent_runtime_v2`; use tenant configuration and tenant-scoped data.
5. The legacy runner remains a fallback until migration is measured in shadow/canary/evals.

## Audit Conclusion

The architecture is close but still split across two worlds: deterministic v2 primitives and a Dinamo-specific legacy bridge. The most valuable next migration is to make tool contracts mandatory and uniform, then connect StateWriter and workflow triggers to those same contracts.

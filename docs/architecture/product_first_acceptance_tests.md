# Product-First Acceptance Tests

Date: 2026-06-06  
Status: Active test specification

These tests define Product-First invariants. They are not implemented in this
documentation phase unless a later phase explicitly approves code changes.

## Runtime Fail-Closed

- **required_tool_skipped_no_send**: A required tool with status skipped,
  missing, failed, or blocked produces no visible send and no outbox write.
- **policy_failure_no_send**: A PolicyValidationError produces no visible send
  and no outbox write.
- **internal_text_never_visible**: `/goal`, prompts, trace text, debug text,
  stack traces, recovery text, and internal labels never appear in customer
  output.
- **outbox_only_after_send_decision**: Outbox writes happen only after send
  policy allows SendAdapter to enqueue.

## No-Send / Live Parity

- **no_send_live_same_route**: Same inbound, tenant, contact, conversation, and
  deployment produce same context, tools, StateWriter, Policy, and
  `TurnOutput.final_message`; only SendAdapter differs.
- **test_lab_db_backed**: Test Lab uses real DB-backed tenant configuration,
  source bindings, tools, state, and policy.
- **test_lab_turn_execution_contract**: Each Test Lab turn records the inbound,
  state before turn, active agent version, source binding snapshot, tool plan,
  tool results, StateWriter decisions, Policy decision, final message, send
  decision, outbox status, side-effect status, and trace id.
- **test_lab_exact_final_message_review**: Publish-readiness runs preserve exact
  final message text for review before approval.
- **test_lab_outbox_zero**: Test Lab leaves outbound_outbox pending/retry at
  zero.
- **test_lab_side_effects_zero**: Test Lab leaves business side effects at zero.

## Knowledge / Tools / State

- **knowledge_source_missing_blocks_publish**: Required missing/unhealthy source
  blocks publish.
- **price_requires_quote_tool**: Price/cotizacion claims require quote tool
  success.
- **requirements_require_lookup**: Requirements claims require requirements tool
  success.
- **crm_update_requires_evidence**: Contact field writes require evidence,
  confidence, and policy.
- **workflow_cannot_override_final_message**: Workflow results cannot replace
  `TurnOutput.final_message`.

## Actions And Workflows

- **action_unknown_or_disabled_blocked**: Unknown actions and disabled action
  bindings are blocked before execution.
- **action_schema_required_for_publish**: Action bindings without input/output
  schema block publish.
- **action_idempotency_required_for_writes**: Write or external actions without
  idempotency strategy block publish.
- **action_dry_run_only_in_test_lab**: Test Lab action execution is dry-run only
  and creates no live side effects.
- **action_result_never_visible_copy**: Action results cannot include customer
  visible response text.
- **workflow_event_preview_only_in_test_lab**: Test Lab records workflow event
  previews without executing workflows.
- **workflow_side_effects_zero_no_send**: No-send and readiness modes create no
  workflow side effects.
- **workflow_loop_guard_blocks_recursion**: Workflow bindings cannot trigger
  recursive agent/workflow loops.
- **workflow_customer_copy_boundary**: Workflow bindings cannot send customer
  text outside SendAdapter.

## Conversation Behavior

- **income_answer_consumes_pending_slot**: When pending_slot is income_type,
  "me pagan por tarjeta" resolves through the tenant-aware plan tool and does
  not ask income again.
- **question_mark_resumes_real_pending**: "?" resumes the real pending slot or
  last bot question, not generic progress copy.
- **trabajo_not_model**: "trabajo" is not a model or plan by itself.
- **image_not_model_without_document_tool**: `[imagen]` is not a model and
  cannot update document state without document tooling.
- **composer_no_fixed_copy_when_context_sufficient**: If context and validated
  data are sufficient, Composer must not emit fixed generic progress copy.

## Publish / Legacy / Trace

- **agent_version_publish_rollback**: Published agent versions are immutable and
  rollback switches to a prior approved version.
- **publish_control_state_machine**: Publish state transitions cannot be caused
  only by scattered flag toggles.
- **publish_requires_test_lab_passed**: Publish is blocked unless the latest
  required DB-backed Test Lab run passed.
- **publish_requires_explicit_live_approval**: Live-limited send scope requires
  explicit human approval naming tenant, version, deployment, channel, scope,
  enabled capabilities, disabled capabilities, and rollback condition.
- **publish_requires_rollback_version**: Live-limited publish is blocked without
  an approved rollback version and rollback procedure.
- **legacy_blocked_for_v2_published_agents**: Legacy visible output paths are
  blocked for Product-First published agents.
- **feature_readiness_blocks_publish**: Blocked readiness state prevents
  publish.
- **trace_completeness**: Each turn records input, deployment, GPT
  interpretation, tools, state writer, policy, final output, actions/workflows,
  and send decision.
- **trace_redaction_and_access**: Trace UX redacts secrets and cross-tenant data
  and enforces tenant-scoped operator permissions.
- **trace_required_panels_publish_gate**: Publish is blocked when required trace
  panels cannot be produced for Test Lab or live-candidate evidence.
- **trace_internal_never_customer_copy**: Trace summaries, debug text, and
  blocker explanations cannot be used as customer-visible copy.
- **legacy_isolation_state_required**: Affected legacy components must have an
  isolation state before Product-First publish.
- **legacy_no_visible_fallback_for_product_first**: Product-First deployments
  cannot reach visible provider fallback, manual recovery, or old response
  contract output.
- **legacy_no_smoke_or_fixture_publish_gate**: Smoke-only and fixture-only
  evidence cannot satisfy Product-First publish readiness.

## Controlled Beta With Dinamo

- **dinamo_beta_after_product_first_gates**: Dinamo beta cannot start until
  Product-First Test Lab, Publish Control, trace, policy, and rollback gates
  pass.
- **dinamo_behavior_is_tenant_data**: Dinamo catalog, requirements, pricing,
  credit plans, and document rules come from tenant data, sources, contracts, or
  tenant-aware tools, not shared runtime code.
- **dinamo_beta_scope_explicit**: Any live-limited Dinamo beta requires explicit
  tenant, deployment, channel, contact/segment scope, enabled capabilities,
  disabled capabilities, and rollback condition.
- **dinamo_beta_no_open_production**: Dinamo beta cannot authorize open
  production, canary, or contacts outside approved scope.

## Coverage And Review

- **changed_behavior_coverage_100**: New or modified behavior has 100% test
  coverage.
- **codex_code_review_before_handoff**: Codex reviews the diff before commit or
  implementation handoff.
- **feature_readiness_and_dod_updated**: Future code implementation updates the
  feature readiness matrix and DoD evidence before handoff.

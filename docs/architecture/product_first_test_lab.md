# Product-First DB-Backed Test Lab

Date: 2026-06-07  
Status: Active architecture contract; MVP implemented for no-send Product Agent Builder  
Canonical source: `Arquitectura-Deseada.md`

## Purpose

Test Lab is the product gate that proves an agent version can run through the
same DB-backed route that live will use, without sending to customers or
creating side effects.

This document defines the target contract for DB-backed test scenarios,
no-send/live-candidate parity, assertions, evidence, and publish blockers. It
has an MVP implementation for Product Agent Builder no-send runs. It does not
activate WhatsApp, outbox live send, actions, workflows, smoke, canary, or live
flags.

## Product Principle

Test Lab is not a smoke script and not a fixture harness.

Test Lab must execute the published-candidate agent version with real
tenant-scoped product configuration:

- Agent
- Agent Version
- Agent Deployment candidate
- Prompt Blocks
- Knowledge Sources and Source Bindings
- allowed tools
- Field Policies
- Action Bindings in dry-run mode
- Workflow Bindings with side effects disabled
- StateWriter policy
- RespondStyleAgentTurn
- Policy Gate
- SendAdapter in no-send mode
- Universal Turn Trace

If Test Lab and live-candidate do not use the same route, Test Lab cannot prove
readiness.

## Respond-Style Turn Evidence - 2026-06-09

Test Lab turn evidence must include Respond-Style execution details for
Product-First turns:

- `agent_context_package`
- `llm_agent_turn_output`
- `tool_requests`
- `tool_results`
- `field_write_proposals`
- `action_proposals`
- `workflow_event_proposals`
- `validator_result`
- `validator_feedback_for_llm`
- `retry_count`

This proves the final message came from the same LLM/tool/validator route live
will use, not from a deterministic template ladder. Tests may still assert exact
`final_message`, contains/not-contains, required tools, state writes, policy,
and send decision.

## Test Suite Contract

A Test Suite is a tenant-scoped product entity that belongs to an agent version
or deployment candidate.

Minimum target fields:

- `tenant_id`
- `test_suite_id`
- `agent_id`
- `agent_version_id`
- `deployment_candidate_id`
- `name`
- `purpose`
- `mode`
- `scenario_ids`
- `required_source_bindings`
- `required_tool_assertions`
- `required_state_assertions`
- `required_policy_assertions`
- `required_trace_assertions`
- `outbox_assertions`
- `side_effect_assertions`
- `created_by`
- `last_run_id`
- `last_status`

Allowed suite modes:

- `draft_validation`
- `publish_readiness`
- `regression`
- `incident_replay`
- `parity_check`

## Scenario Contract

A scenario must represent conversation behavior, not isolated prompt text.

Minimum target fields:

- `tenant_id`
- `scenario_id`
- `test_suite_id`
- `name`
- `description`
- `conversation_seed`
- `contact_fixture_source`
- `turns`
- `expected_tools`
- `expected_state_writes`
- `expected_blocked_writes`
- `expected_lifecycle`
- `expected_policy`
- `expected_final_messages`
- `expected_trace_fields`
- `expected_outbox_count`
- `expected_side_effect_count`

Fixtures may seed deterministic contact or conversation state, but readiness
must run against tenant-scoped DB-backed configuration and the same runtime
route as live-candidate.

## Turn Execution Contract

Each test turn must create an `AgentTurnRequest` equivalent to the target live
request, except that SendAdapter is configured for no-send.

The test run must record:

- inbound text and attachments
- conversation state before turn
- contact state before turn
- active agent version
- source binding snapshot
- tool plan and results
- StateWriter accepted and blocked writes
- lifecycle decision
- policy result
- final message or blocked reason
- send decision
- outbox status
- side-effect status
- trace id

## No-Send / Live-Candidate Parity

For the same inbound, tenant, contact, conversation, and agent version,
`test_lab_no_send` and `live_candidate` must produce the same:

- context
- last messages
- pending slot
- knowledge scope
- required tools
- tool inputs
- tool results
- StateWriter decisions
- lifecycle decisions
- RespondStyleAgentTurn output
- validator feedback and retry decisions
- Policy decision
- `TurnOutput.final_message`
- universal trace core fields

The only allowed difference is SendAdapter behavior and send metadata.

## Required Assertions

Publish-readiness Test Lab runs must assert:

- required tool failures produce no-send
- policy failures produce no-send
- required source missing/unhealthy blocks publish
- facts use tool/source basis
- state writes require evidence and policy
- workflows do not overwrite customer copy
- actions run only in dry-run or blocked mode
- outbox pending/retry remains zero
- business side effects remain zero
- trace is complete
- final message exact text is reviewable
- no generic progress copy masks missing context
- retryable invalid LLM output is corrected through validator feedback or
  blocked no-send
- no legacy composer or fallback copy is used for published Product Agents

## Evidence Contract

Each run must produce a durable test run record:

- `test_run_id`
- `tenant_id`
- `agent_version_id`
- `suite_id`
- `scenario_results`
- `turn_results`
- `pass_count`
- `fail_count`
- `blocked_count`
- `coverage_summary_for_changed_behavior`
- `trace_ids`
- `outbox_audit_result`
- `side_effect_audit_result`
- `reviewer`
- `decision`

## Implemented MVP - 2026-06-07

The MVP implementation adds a durable no-send Test Lab path for Product-First
agent versions:

- `agent_test_runs` migration and ORM model.
- Tenant-scoped Test Suite and Test Scenario CRUD routes.
- Test run route that calls `AgentService.handle_turn(..., mode="no_send")`.
- Sandbox conversation creation for DB-backed execution.
- Durable turn results with `final_message`, trace id, tools, send status,
  state persistence, and errors.
- DB audits for `outbound_outbox` pending/retry count and
  `business_event_ledger.side_effects_allowed`.
- Product Agent Builder Test Lab tab for suites, scenarios, no-send run, latest
  run evidence, exact final message, trace counts, outbox audit, and side-effect
  audit.

The MVP intentionally does not:

- publish an agent
- activate live send
- change SendAdapter
- write live outbox messages
- execute workflow or action side effects
- connect Runtime V2 live behavior to Product-First entities
- hardcode Dinamo or any vertical

Possible decisions:

- `TEST_LAB_PASSED`
- `TEST_LAB_FAILED`
- `TEST_LAB_BLOCKED_BY_SOURCE`
- `TEST_LAB_BLOCKED_BY_TOOL`
- `TEST_LAB_BLOCKED_BY_POLICY`
- `TEST_LAB_BLOCKED_BY_TRACE`
- `TEST_LAB_BLOCKED_BY_PARITY`
- `TEST_LAB_BLOCKED_BY_LEGACY`

## Publish Blockers

Publish Control must block when:

- required Test Suite has not run
- latest run is not `TEST_LAB_PASSED`
- any required scenario failed
- no-send/live-candidate parity failed
- trace is incomplete
- final messages were not reviewed where required
- outbox audit is non-zero
- side-effect audit is non-zero
- changed-behavior coverage is missing for implemented code
- Codex code review is missing for implemented code

## Future Tests

Future implementation for this contract must include unit or integration tests
for new or modified behavior, with 100% coverage of that behavior:

- Test Lab runs the same AgentService route as live-candidate
- SendAdapter is the only no-send/live-candidate difference
- required tool failure blocks send
- policy failure blocks send
- outbox remains zero in no-send
- workflow side effects remain zero in no-send
- exact final messages are recorded for review
- trace completeness is enforced as a publish gate
- failed Test Lab run blocks Publish Control

Codex code review against base branch or uncommitted changes is required before
implementation handoff.

## Phase 6 Acceptance

Fase 6 is complete when:

- Test Suite contract is documented
- Scenario contract is documented
- Turn execution contract is documented
- no-send/live-candidate parity is documented
- required assertions are documented
- evidence and publish blockers are documented
- no live/runtime/DB behavior was changed

Decision for the implemented MVP phase:

`DB_BACKED_TEST_LAB_MVP_READY`

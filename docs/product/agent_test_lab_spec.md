# Agent Test Lab Product Spec

Date: 2026-06-07  
Status: Product specification; behavior validation implementation verified  
Canonical source: `Arquitectura-Deseada.md`

## Objective

Provide AtendIA's DB-backed equivalent to Preview. Test Lab proves agent
behavior before publish without sending customer messages or creating side
effects.

## Required User Capabilities

The operator can:

- choose agent
- choose version
- choose sandbox or real contact
- choose channel
- simulate conversation
- attach files
- see exact response
- see knowledge used
- see required tools
- see executed tools
- see skipped tools
- see state writes
- see lifecycle decisions
- see workflow dry-run events
- see action dry-runs
- see policy result
- see send decision
- compare expected vs actual

## Execution Rule

Test Lab must use DB-backed no-send with the same AgentService route as live.
Fixtures may seed deterministic state for tests, but fixtures cannot prove
publish readiness.

The implemented MVP runs suites through Product Agent Builder APIs and persists
`AgentTestRun` evidence. It only uses no-send mode and does not activate live
send, outbox dispatch, workflow side effects, action side effects, smoke,
canary, or open production.

The behavior validation extension adds a stricter per-turn evidence contract for
DB-backed no-send runs:

- each scenario may contain multiple text turns
- each turn may declare simple expectations
- exact `final_message` remains reviewable
- `final_message_contains` can be asserted
- required/executed/skipped/failed tools are recorded
- state writes are recorded
- policy status is recorded
- send decision is recorded as `no_send`
- failures are recorded per turn
- failed or blocked runs become readiness/publish blockers

## Scenario Assertions

Each scenario can assert:

- intent
- required tools
- tool inputs/results
- skipped or blocked tools
- exact final message
- field writes accepted/blocked
- lifecycle update accepted/blocked
- workflow dry-run events
- action dry-run events
- policy status
- send decision
- trace completeness

## Publish Evidence

Publish readiness requires:

- latest required suite passed
- exact final messages reviewed
- trace ids available
- outbox zero in no-send
- side effects zero in no-send
- no-send/live-candidate parity passed where send is in scope

## Acceptance

The MVP is accepted when tests prove:

- suites and scenarios are tenant-scoped
- invalid scenario payloads are rejected
- test runs call AgentService in no-send mode
- final messages, trace ids, tool results, state persistence, send status, and
  errors are recorded
- outbox and side-effect audits are recorded
- Product Agent Builder can create suites/scenarios and show latest run evidence
- no customer WhatsApp send or live outbox dispatch is enabled

## Behavior Validation Acceptance

The behavior validation layer is accepted when tests prove:

- multiturn scenarios are persisted and executed through no-send AgentService
- each turn result shows input, exact output, tools, state writes, policy, send
  decision, trace id, and failures
- required tool failures mark the run failed
- policy failures mark the run failed
- internal/debug visible text marks the turn failed
- passed Test Lab updates readiness with `test_lab_passed=true`
- failed Test Lab creates readiness/publish blocker `test_lab_failed`
- Product Agent Builder displays safety copy and per-turn evidence
- no WhatsApp, live outbox, action execution, or workflow side effects occur

## Real AgentService No-Send Mode

`agent_service_real` is the Test Lab execution mode for running the real
DB-backed `AgentService` path with the OpenAI model provider and SendAdapter in
`no_send`.

The mode is constrained:

- API payload must keep `mode=no_send`
- maximum 2 scenarios
- maximum 6 turns per scenario
- maximum 350 output tokens per turn
- temperature 0.2
- required tool skipped/failed blocks the run
- policy blocked/failed blocks the run
- missing OpenAI provider blocks the run
- missing or fallback provider cannot pass readiness
- no WhatsApp, live outbox, smoke, action side effects, workflow side effects,
  canary, or production activation

Each turn records:

- execution mode
- exact input
- exact final message
- required/executed/skipped/failed tools
- state writes
- policy result
- send decision
- trace id
- token usage
- estimated cost object
- pass/fail and failure reason

Cost is recorded as an evidence object. If no configurable cost rate is
available, `amount_usd` remains null with status `cost_rate_not_configured`
rather than inventing a current provider price.

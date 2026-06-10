# Product-First Test Lab Behavior Validation

Date: 2026-06-07

Decision: `TEST_LAB_BEHAVIOR_VALIDATION_READY`

## Scope

Closed the DB-backed no-send Test Lab behavior validation slice on top of the
existing Product-First Test Lab MVP.

No live behavior was activated. This phase did not touch WhatsApp, smoke,
SendAdapter live behavior, outbox live dispatch, workflow side effects, action
execution, canary, production, staging, commit, cleanup, or legacy deletion.

## Implemented Backend

- Extended `core/atendia/product_agents/test_lab.py`.
- Test Lab still runs through `AgentService.handle_turn(..., mode="no_send")`.
- Scenario turns can carry per-turn expectations.
- Scenario-level expectations can apply to every turn.
- Per-turn result now records input, exact final message, required/executed/
  skipped/failed tools, state writes, policy result, send decision, trace id,
  status, failures, and expected assertions.
- Assertions now cover exact/contains final message, expected tools, executed
  tools, state writes, policy status, send decision, blockers, should block /
  should not block, trace, and internal/debug copy.
- Required tool failures produce `TEST_LAB_BLOCKED_BY_TOOL`.
- Policy failures produce `TEST_LAB_BLOCKED_BY_POLICY`.
- Missing trace still produces `TEST_LAB_BLOCKED_BY_TRACE`.
- `evaluate_builder_readiness()` now includes latest Test Lab run:
  - no run: `test_lab_not_run` warning
  - passed run: `test_lab_passed=true`
  - failed/blocked run: `test_lab_failed` blocker
  - `live_publish_allowed` remains false
- Scenario validation rejects malformed attachments, per-turn expected,
  expected turns, and list-valued expectation fields.

## Implemented Frontend

- Extended Product Agent Builder Test Lab tab.
- Scenario editor now supports multiple turns, final-message contains, expected
  tool, expected field, and `should_block`.
- Run button is labeled `Run no-send test`.
- Safety copy remains visible:
  - `No WhatsApp will be sent.`
  - `No live outbox will be written.`
  - `Actions/workflows are disabled or dry-run.`
- Test Run panel now shows per-turn evidence: input, exact output, tools, state
  writes, policy, send decision, trace id, pass/fail, and failures.
- Defensive UI handling covers incomplete/unknown turn evidence without
  inventing customer-visible output.

## Tests Added Or Updated

Backend:

- `core/tests/product_agents/test_agent_test_lab_runner.py`
- `core/tests/product_agents/test_agent_test_lab_service.py`
- `core/tests/product_agents/test_agent_builder_service.py`
- Existing readiness tests with explicit latest-run fixtures.

Frontend:

- `frontend/tests/features/product-agent-builder/AgentBuilderPage.test.tsx`
- Added no-send safety copy checks, multiturn scenario creation, should-block
  scenario expectations, per-turn evidence display, failed turn evidence, and
  incomplete evidence fallback rendering.

## Verification

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run ruff check atendia/product_agents tests/product_agents
```

Result:

- `All checks passed!`

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\core
uv run pytest tests/product_agents -q --cov=atendia.product_agents --cov=atendia.api.product_agents_routes --cov-report=term-missing --cov-fail-under=100
```

Result:

- `124 passed`
- `Required test coverage of 100% reached. Total coverage: 100.00%`

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\frontend
npm.cmd exec -- biome check src/features/product-agent-builder tests/features/product-agent-builder
```

Result:

- `Checked 3 files`
- `No fixes applied`

Passed:

```powershell
cd C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\frontend
npm.cmd run test -- AgentBuilderPage.test.tsx --run --coverage --coverage.include=src/features/product-agent-builder/components/AgentBuilderPage.tsx --coverage.thresholds.statements=100 --coverage.thresholds.branches=100 --coverage.thresholds.functions=100 --coverage.thresholds.lines=100
```

Result:

- `25 passed`
- Statements: `100%`
- Branches: `100%`
- Functions: `100%`
- Lines: `100%`

## Safety Confirmation

- No WhatsApp activation.
- No smoke activation.
- No SendAdapter live change.
- No outbox live dispatch.
- No workflow/action side effects.
- No canary.
- No production opening.
- No legacy deletion.
- No Dinamo/contact hardcode introduced in Product-First shared code.

## Remaining Risks

- Product-First baseline remains uncommitted/untracked in a dirty worktree.
- Runtime trace richness depends on `AgentService`/`TurnOutput.trace_metadata`;
  if a runtime omits tools/state/policy fields, Test Lab shows missing evidence
  and fails expectations instead of inventing it.
- This validates DB-backed no-send Test Lab behavior. Live/smoke remains a
  separate approval gate.

## Final Decision

`TEST_LAB_BEHAVIOR_VALIDATION_READY`

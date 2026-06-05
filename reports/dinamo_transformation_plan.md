# Dinamo Transformation Plan

Generated: 2026-06-03

Scope: phased architecture plan. No code/config behavior was changed.

Final decision: ARCHITECTURE_NEEDS_TOOL_CONTRACT_FIRST

## Phase 0 - No Touch Live

Objective: freeze production behavior and preserve rollback while measuring the current system.

Probable files:

- `core/atendia/agent_runtime/rollout_policy.py`
- `core/atendia/agent_runtime/shadow_service.py`
- `core/atendia/runner/conversation_runner.py`
- `core/atendia/simulation/`
- existing readiness/smoke reports

Tests needed:

- Shadow/send-disabled smoke.
- Known incoherence replay baseline.
- Regression that actions/workflows remain disabled when configured.

Risks:

- Accidentally enabling send/action/workflow behavior.
- Treating shadow success as live readiness.

Acceptance criteria:

- No runtime/config changes.
- No traffic started.
- Legacy fallback remains active.
- Baseline smoke/eval evidence is reproducible.

Decision to advance:

- Advance only if the current baseline is reproducible and safe gates are confirmed.

## Phase 1 - Prompt Diet

Objective: reduce the prompt master to behavior contract only.

Probable files:

- `docs/Prompt Agente IA.txt`
- `core/atendia/runner/advisor_brain_prompt.py`
- `core/atendia/runner/composer_prompts.py`
- prompt/eval tests under `core/tests/agent_runtime/` or `core/tests/simulation/`

Tests needed:

- Prompt contains no price/down-payment/document requirement constants.
- Bot cannot answer price without quote tool evidence.
- Bot cannot answer plan-specific docs from prompt text.

Risks:

- Removing behavior before tools own the facts.
- Prompt becoming too generic and losing human sales quality.

Acceptance criteria:

- Prompt keeps Francisco tone, one-question style and no-invention policy.
- Prices, documents, plans, field writes and workflow triggers are removed from prompt authority.
- Every removed rule has a deterministic owner.

Decision to advance:

- Advance only after tool contract coverage exists for every removed commercial rule.

## Phase 2 - Mandatory Tools

Objective: make deterministic tools mandatory for catalog, credit plan, requirements and quote facts.

Probable files:

- `core/atendia/tools/search_catalog.py`
- `core/atendia/tools/deterministic.py`
- `core/atendia/tools/quote.py`
- `core/atendia/tools/lookup_requirements.py`
- `core/atendia/tools/lookup_faq.py`
- `core/atendia/tools/vision.py`
- `core/atendia/credit_plan_invariants.py`
- tenant product/KB configuration files

Tests needed:

- `catalog.retrieve` required for model/price.
- `credit_plan.resolve` required for income/enganche.
- `requirements.retrieve` required for documents.
- `quote.resolve` required for quotes.
- FAQ refuses deterministic-tool-owned topics.
- "por fuera", Buro, ambiguous model and wrong-plan docs cases.

Risks:

- Tool-name drift (`quote` vs `quote.resolve`, `search_catalog` vs `catalog.retrieve`).
- Tenant-specific rules remain hardcoded globally.

Acceptance criteria:

- All six mandatory tools have stable structured contracts.
- Outputs include tenant id, evidence/citations, confidence, ambiguity and safe-to-persist metadata.
- No prompt calculation of price/enganche/payment/term.

Decision to advance:

- Advance only when contract tests pass and reports show tenant-scoped data authority.

## Phase 3 - State Contract

Objective: make StateWriter the only accepted owner of business fields.

Probable files:

- `core/atendia/agent_runtime/state_writer.py`
- `core/atendia/runner/state_write_policy.py`
- `core/atendia/contact_memory/operational_state.py`
- `core/atendia/contact_memory/document_checklist.py`
- `core/atendia/contracts/turn_resolution.py`

Tests needed:

- StateWriter rejects direct LLM writes without evidence.
- Quote invalidates when moto/plan/mode changes.
- Vague model cannot persist to `Moto`.
- `Doc_Completos` requires real accepted docs.
- Papeleria Incompleta requires attachment/checklist evidence.

Risks:

- Legacy aliases bypass canonical fields.
- Quote state remains valid after commercial state changes.

Acceptance criteria:

- Canonical field map and aliases are explicit.
- Every accepted write has source tool/action, evidence id, tenant id, trace id and reason.
- Unsafe writes are rejected in tests.

Decision to advance:

- Advance only when unsafe writes fail closed in both v2 and covered legacy bridge paths.

## Phase 4 - Workflow Contract

Objective: make workflow triggers deterministic, structured and idempotent.

Probable files:

- `core/atendia/workflows/engine.py`
- `core/atendia/agent_runtime/workflow_events.py`
- `core/atendia/state_machine/pipeline_evaluator.py`
- `core/atendia/lifecycle/service.py`
- workflow API/tests

Tests needed:

- `plan_identified` requires accepted plan write.
- `quote_sent` requires QuoteSafetyGuard acceptance.
- `docs_complete` requires checklist complete for selected plan.
- Critical triggers cannot use keyword-only `contains`.
- Duplicate side effects are idempotently suppressed.

Risks:

- Workflow definitions fire on raw text instead of state.
- Side effects duplicate after retry.

Acceptance criteria:

- Target events have payload schema, evidence, trace id and idempotency key.
- Critical workflows use structured state/events only.
- Safe failure/rollback behavior is documented and tested.

Decision to advance:

- Advance only after workflow contract tests pass and keyword-only critical triggers are blocked or linted.

## Phase 5 - Human Quality Eval

Objective: measure whether Francisco still sells naturally while obeying deterministic evidence.

Probable files:

- `core/atendia/eval_lab/`
- `core/atendia/simulation/`
- `core/tests/simulation/`
- provider battery scripts under `tools/`

Tests needed:

- 10-20 simulated or real replay conversations.
- Human score for tone, clarity, one next step, no form feeling.
- Evidence score for no invention, correct quote mode, correct docs and no repetition.

Risks:

- Deterministic correctness improves while sales quality drops.
- Evals check only happy path.

Acceptance criteria:

- Human quality score meets threshold.
- Known incoherence suite passes.
- Every visible fact is traceable to tool/state/KB evidence.

Decision to advance:

- Advance only if correctness and human sales quality both pass.

## Phase 6 - Single-Contact Live Smoke

Objective: validate one approved contact safely before broader canary.

Probable files:

- rollout/shadow config only when explicitly approved
- `core/atendia/agent_runtime/pilot_policy.py`
- `core/atendia/agent_runtime/rollout_policy.py`
- smoke scripts/reports under `tools/` and `reports/`

Tests needed:

- Full flow: greeting, seniority, plan, model, quote, post-quote acknowledgement, docs, upload simulation, handoff.
- Actions/workflows off first.
- Rollback path verified.

Risks:

- Accidental real send/action.
- One-contact smoke mistaken for broad readiness.

Acceptance criteria:

- No unsafe quote.
- No wrong-plan docs.
- No repeated qualification.
- No stale quote.
- No stage move without evidence.
- No duplicate side effects.

Decision to advance:

- Advance only with explicit go decision and rollback ready.

## Phase 7 - Real Canary

Objective: expand to controlled real traffic after smoke and replay pass.

Probable files:

- rollout/canary policy files
- monitoring and shadow analytics reports
- workflow/action gates

Tests needed:

- Canary cohort monitoring.
- False handoff, unsafe quote, wrong docs, repetition, workflow duplicate and latency metrics.
- Rollback drill.

Risks:

- Tenant-specific Dinamo assumptions leak into generic runtime.
- Canary size increases before evidence supports it.

Acceptance criteria:

- Canary metrics meet threshold.
- Rollback is tested.
- Legacy fallback remains until parity is proven.

Decision to advance:

- Advance only after measured canary parity and tenant-isolation checks.

## Top 10 Breaches To Close

1. Unified mandatory tool contracts do not yet govern every path.
2. Plan/down payment specs are globally hardcoded in core.
3. Prompt still contains commercial flow/facts.
4. FAQ overlaps with requirements and commercial rules.
5. Quote snapshot authority is not universal in live path.
6. Field aliases are mixed between legacy and target names.
7. Business workflow trigger names are not fully standardized.
8. Critical workflows can still be configured around keyword-like conditions.
9. Document checker contract is not yet a single runtime authority.
10. Runtime v2 is still shadow/partial rather than the sole live authority.

## Final Decision

ARCHITECTURE_NEEDS_TOOL_CONTRACT_FIRST.

Reason: StateWriter, guards and workflows already have strong foundations, but they depend on uniform structured evidence. Until catalog, credit plan, quote, requirements, FAQ and document tools share mandatory contracts, prompt and legacy bridge code will keep carrying business truth.

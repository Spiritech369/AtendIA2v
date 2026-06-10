# Respond-Style Phase 11 — Multi-Round Loop, Test Lab DB/API, Deployment Resolver (no-send)

Date: 2026-06-09
Decision: `PHASE_11_RESPOND_STYLE_MULTIRound_TESTLAB_RESOLVER_NO_SEND_READY`
Modules:
- 11A: `core/atendia/agent_runtime/respond_style_tool_loop.py` (multi-round + budgets + dedupe)
- 11B: `core/atendia/product_agents/test_lab_direct_adapter.py` + API route
  `POST /test-suites/{suite_id}/runs/respond-style-direct` +
  `core/atendia/agent_runtime/respond_style_dry_facts_executor.py`
- 11C: `core/atendia/agent_runtime/respond_style_deployment_resolver.py`
Tests: `core/tests/agent_runtime/test_respond_style_phase_11.py` (17; suite total 144)
Runner: `tools/run_respond_style_phase_11_no_send_2026_06_09.py` (real OpenAI)
Raw result: `reports/respond_style_phase_11_no_send_result_2026_06_09.json`

## 11A — Budgeted multi-round tool loop

`RespondStyleToolLoopConfig`: `max_tool_rounds` (default 1, backward
compatible — runners/Test Lab use 3), `max_total_tool_calls` (default 8),
`max_elapsed_seconds` (optional wall-clock). Exhausted budgets fail closed
(`tool_call_budget_exceeded` / `tool_time_budget_exceeded`).

Behavior per round: validated tool proposals execute fact-only; provisional
field proposals accumulate across rounds (visible to executors and later
rounds; merged into the final decision); each round's tool_results feed the
next LLM call.

Quality fix surfaced by the real run: the model sometimes re-requested
already-succeeded tools, burning rounds. The loop now (a) never re-executes
a succeeded tool (result reuse), (b) deduplicates within a round, and
(c) when a round consists only of already-satisfied requests, nudges the
model ONCE with structured feedback to write the final_response from
existing tool_results; if it persists, the turn blocks (fail-closed). A
final required-tool request that already succeeded no longer blocks.

**Real OpenAI evidence:**
- chaotic compound ("quiero la opcion estandar trabajo por mi cuenta que
  necesito y cuanto cuesta"): **3 rounds** — catalog.search →
  requirements.lookup → quote.resolve, each executed exactly once, final
  message written from facts. (Before the dedupe fix this blocked on
  round limit with catalog.search executed twice.)
- sequential dependency ("cuanto cuesta la opcion mas economica?"), where
  quote.resolve requires `option_id` that only exists in catalog.search
  results: **2 rounds**, correct quote.
- Model-behavior note kept honest: compound asks often resolve in ONE round
  with parallel tool calls (a previous run did exactly that) — multi-round
  is the safety margin, not the requirement.

## 11B — Test Lab DB/API adapter

- `DryFactsToolExecutor`: generic config-driven fact-only executor — tool
  bindings declare `dry_facts` and `preconditions`; preconditions resolve
  from contact state (incl. same-turn provisional fields) or structured
  tool arguments. No I/O, no vertical assumptions.
- `run_direct_test_suite(session, ...)`: loads suite + scenarios + version
  (tenant-scoped), maps the AgentVersion payload via
  `published_config_from_version_payload`, runs `RespondStyleTestLabDirect`
  over the direct path, and stores ONE `AgentTestRun` row: `mode='no_send'`
  (existing check constraint), decision `RESPOND_STYLE_DIRECT_NO_SEND_READY/
  _BLOCKED`, full scenario/turn evidence in JSONB, outbox audit
  `{status: clean, outbound_outbox_writes: 0}`, side-effect audit all false,
  coverage `execution_mode=respond_style_product_agent_direct`. No
  migration needed.
- API route `POST /test-suites/{suite_id}/runs/respond-style-direct`
  (tenant-admin, same pattern as the legacy run route). The legacy
  `test_lab.py` pipeline remains untouched.
- Unit-tested with fake session + injected tool loop (run row content,
  counts, audits); the route reuses the tested service function. End-to-end
  HTTP+DB exercise belongs to the existing integration environment (Docker
  Postgres) and is listed as Phase 12 verification.

## 11C — Deployment resolver (preview, no-send)

`RespondStyleDeploymentResolver.resolve(DeploymentView)` →
`DeploymentResolution`:
- `product_agent_direct` preview only when publish_state=published AND
  respond_style_enabled AND an active version exists; otherwise
  `legacy_runner` with explicit blocker reasons.
- The resolution model is schema-locked: `no_send_only=Literal[True]`,
  `send_decision=Literal["no_send"]`, `live_routing_active=Literal[False]`
  — constructing a live-routing resolution raises. Live flags on the
  deployment do NOT flip anything; they only show up in
  `live_blocked_reasons` (incl. `phase_11_is_no_send_only`).
- No runner imports, no execution: this is the future bypass switch in
  preview mode. Verified previews: published→direct, draft→legacy,
  live-flags-on→still no_send.

## Verification

- pytest: 144 passed (full respond-style + runtime + phase 11 suites).
- ruff: clean on all touched/new files (also regenerated the package
  `__all__`, which was unsorted and missing every export added since
  Phase 0.5).
- Source audits (test-enforced): no legacy imports in resolver/executor/
  adapter; no tenant/vertical hardcodes; result models refuse send/live at
  the pydantic layer.

## No side effects

No outbox writes, no workflows, no actions, no delivery, no WhatsApp, no
smoke, no live routing. DB writes happen only in the Test Lab adapter as
evidence rows (`AgentTestRun`, mode no_send) — the runner used in-memory
evidence only.

## Decision

`PHASE_11_RESPOND_STYLE_MULTIRound_TESTLAB_RESOLVER_NO_SEND_READY`

Not live readiness. Next (Phase 12): end-to-end Test Lab direct via HTTP+DB
in the Docker environment, deployment resolver wired into the inbound path
in PREVIEW mode (log-only, zero behavior change), and the legacy
customer-copy hard-block test battery from the kill map.

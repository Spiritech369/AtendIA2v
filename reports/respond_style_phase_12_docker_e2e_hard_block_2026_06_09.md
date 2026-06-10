# Respond-Style Phase 12 — Docker E2E, Inbound Preview, Legacy Copy Hard Block

Date: 2026-06-09
Decision: `PHASE_12_DOCKER_E2E_AND_LEGACY_COPY_HARD_BLOCK_READY`
Artifacts:
- 12A: `tools/run_docker_e2e_test_lab_direct_2026_06_09.py` →
  `reports/docker_e2e_test_lab_direct_result_2026_06_09.json`
- 12B: `core/atendia/product_agents/routing_preview.py` + 9-line log-only
  block in `_run_inbound_pipeline` (baileys_routes.py) +
  `core/tests/agent_runtime/test_respond_style_routing_preview.py`
- 12C: `core/tests/agent_runtime/test_product_agent_legacy_copy_hard_block.py`
  + kill map amendment (ConversationProgressGuard row)

## 12A — Docker E2E (real container, real Postgres, real OpenAI)

Executed inside `atendia_backend` (uv venv, `/app` mount, key from the
container's `.env`): seeded a generic published AgentVersion (tool bindings
with dry_facts + preconditions, field policy, declarative hard policies),
a suite and a 2-turn scenario against an EXISTING tenant/agent, then called
the real endpoint
`POST /api/v1/product-agents/test-suites/{id}/runs/respond-style-direct`
through the FastAPI app (ASGI transport; auth dependencies overridden with
a synthetic tenant-admin; CSRF double-submit satisfied — the middleware ran
for real).

Result: `PHASE_12A_DOCKER_E2E_TEST_LAB_DIRECT_PASSED`
- HTTP 201; AgentTestRun persisted: mode `no_send`, status `passed`,
  decision `RESPOND_STYLE_DIRECT_NO_SEND_READY`,
  coverage `execution_mode=respond_style_product_agent_direct`.
- Both turns answered via the direct route with real OpenAI inside the
  container; all `send_decision=no_send`, no blocked turns.
- Outbox audit: row delta 0 across the whole run; pending/retry = 0.
- Migrations 066-068 confirmed applied by the container's
  `alembic upgrade head` startup step.

Environment notes (for repeatability): the container mounts only `core/`,
so the script is `docker cp`-ed to `/tmp` and run with
`PYTHONPATH=/app uv run python`; `httpx` was installed into the uv venv
(dev container only).

## 12B — Inbound routing preview (log-only)

`preview_respond_style_routing(session, tenant_id)` maps each
AgentDeployment row to a `DeploymentView`
(`metadata_json.respond_style_enabled` is the opt-in flag) and resolves it
with the Phase 11 resolver — schema-locked to `no_send` /
`live_routing_active=False`. `log_routing_preview_safely` wraps it and
swallows every exception by design.

Wired into `_run_inbound_pipeline` as step 2b: 9 added lines, log/trace
only — no routing, no send, no state mutation, failure-proof. Verified:
- diff inspection (only the log block),
- unit tests (mapping, no-send invariants, exception swallowing,
  source audit: preview module contains no runner/outbox/send calls),
- live backend imports the wired module without crash (`--reload` server
  healthy after the change),
- Docker E2E captured real previews from the dev DB: all
  `send_decision=no_send`, `live_routing_active=false`.

## 12C — Legacy customer-copy hard block (kill map battery)

`test_product_agent_legacy_copy_hard_block.py`:

1. **Transitive import-graph proof** (strongest guarantee): a fresh
   interpreter imports the ENTIRE direct route (11 modules) and the test
   asserts none of the kill map's copy sources got loaded —
   ConversationRunner, composer_prompts/composer_openai,
   response_contract/response_frame, HumanResponseComposer,
   advisor_pipeline (StructuredRuntimeComposer), ValidatedResponsePlan,
   ConversationProgressGuard, QuoteSafetyGuard, MandatoryToolGuard,
   model_provider (SafeFallbackAgentProvider), SendAdapter, AgentService,
   outbound_dispatcher, queue.outbox, workflows.engine.
2. Blocked turns yield `final_message=None` — no canned recovery copy
   (provider fallback / manual recovery rows).
3. Handoff proposals never override final_message and carry no copy fields.
4. Workflow proposals cannot author visible copy.
5. No `pending_slot` / `next_best_question` / `suggested_question`
   artifacts anywhere in direct-route results.

Kill map amended: ConversationProgressGuard row added (it was missing from
the original 16-source map) with `BLOCK_FOR_PRODUCT_AGENT`.

## Verification

- pytest: 156 passed (full respond-style + product agent suites, including
  5 hard-block and 3 preview tests).
- ruff: clean on all new files; the 2 findings in baileys_routes.py
  (import order, long line) are pre-existing and untouched by the 9-line
  diff.
- Docker stack healthy after changes (backend `--reload` picked up the
  inbound block without crash-loop).

## No live behavior change

ConversationRunner behavior untouched. The only live-path diff is the
fail-safe log-only preview block. No outbox writes (verified by row-count
delta in the real DB), no workflow/action side effects, no WhatsApp, no
smoke.

## Decision

`PHASE_12_DOCKER_E2E_AND_LEGACY_COPY_HARD_BLOCK_READY`

Not live readiness. Next (Phase 13 candidate): Publish Control gating on
the hard-block battery + resolver flip behind explicit per-deployment
opt-in (`respond_style_enabled`) in shadow first, replay of the failed V2/V3
transcripts through the direct route, and the live-candidate parity gate.

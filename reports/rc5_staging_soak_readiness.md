# RC5 Staging Soak Readiness

Generated: 2026-06-03T01:14:12.1278313-06:00

Commit: `32eff00b8ccbd2448047c060649df244398acb03`

## Executive Summary

RC5 is ready for controlled staging soak and 5% canary. This phase did not modify runtime-critical logic, Composer, AdvisorBrain, QuoteSafetyGuard, ConversationProgressGuard, or ProviderReliabilityLayer. Changes were limited to CI readiness, canary/rollback documentation, and final readiness reports.

Decision:

- `READY_FOR_STAGING_SOAK`
- `READY_FOR_5_PERCENT_CANARY`

## Test Status

| Area | Command | Result |
| --- | --- | --- |
| Scoped ruff RC5 | `uv run ruff check atendia/simulation/rc5_common.py atendia/simulation/replay_eval.py atendia/simulation/load_eval.py atendia/simulation/chaos_eval.py atendia/observability/rc5_metrics.py` | pass |
| Unit/runtime without DB | `uv run pytest tests/agent_runtime -m "not integration_db" -q` | 142 passed, 27 deselected |
| Integration DB | `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test uv run pytest tests/agent_runtime -m "integration_db" -q` | 27 passed, 142 deselected |
| Full agent runtime | `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test uv run pytest tests/agent_runtime -q` | 169 passed |

PostgreSQL was started with `docker compose -f docker-compose.test.yml up -d postgres-test` and stopped with `docker compose -f docker-compose.test.yml down`.

## Eval Status

| Eval | Command | Result |
| --- | --- | --- |
| Replay | `uv run python -m atendia.simulation.replay_eval --dataset atendia/simulation/fixtures/rc5_replay_dataset.anonymized.json --anonymized` | 3/3 pass, critical failures 0 |
| Load | `uv run python -m atendia.simulation.load_eval --conversations 50 --turns-per-conversation 5` | 250 turns pass, p95 0.6168 ms |
| Chaos | `uv run python -m atendia.simulation.chaos_eval` | 10/10 scenarios pass, duplicate side effects 0 |
| Local deterministic | `uv run python -m atendia.simulation.advisor_first_multiturn` | 10/10 pass, side effects 0 |
| Provider stability | `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_TIMEOUT_S=30 ATENDIA_V2_AGENT_RUNTIME_V2_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=100 uv run python -m atendia.simulation.provider_stability_eval --runs 5` | 5/5 pass, fallback 0, side effects 0 |
| Provider advisor eval | `uv run python -m atendia.simulation.provider_advisor_first_eval` | 40/40 pass from versioned RC5 artifact |

Provider advisor eval was not re-run after this phase because only CI, docs, and reports changed. Evidence source: `reports/rc5_provider_advisor_first_eval.json`.

## Metrics Status

Export command:

```bash
uv run python -m atendia.observability.rc5_metrics
```

Export artifact: `reports/rc5_observability_config.json`.

P0 alerts are complete and exportable:

- `price_without_snapshot_rate > 0`
- `quoted_without_canonical_product_rate > 0`
- `stale_quote_rate > 0`
- `duplicate_side_effect_count > 0`
- `handoff_false_positive_count > 0`
- `database_write_error_rate` sustained over baseline
- `provider_retry_exhausted_count` high versus baseline

P1 alerts are complete and exportable:

- `progress_guard_block_rate > 0.05` sustained
- `provider_429_rate` high versus baseline
- `provider_latency_p95` high versus baseline
- `provider_fallback_response_count` spike versus baseline

Safety and side-effect metrics:

| Metric | Result |
| --- | ---: |
| `quoted_without_canonical_product_rate` | 0.0 |
| `price_without_snapshot_rate` | 0.0 |
| `stale_quote_rate` | 0.0 |
| `repeated_question_rate` | 0.0 |
| `exact_response_repeat_rate` | 0.0 |
| `duplicate_side_effect_count` | 0 |
| `side_effects.database_writes` | 0 |
| `side_effects.outbox` | 0 |
| `side_effects.whatsapp` | 0 |

## Workflow Status

`.github/workflows/rc5-staging-soak.yml` now covers:

- scoped ruff RC5
- unit/runtime tests
- integration DB tests with PostgreSQL service
- full `tests/agent_runtime`
- replay eval
- load eval
- chaos eval
- local deterministic simulation
- RC5 metrics export
- report artifact upload
- provider stability and provider eval on schedule or manual opt-in

## Playbooks Status

Required playbooks exist:

- `docs/ops/provider_429_playbook.md`
- `docs/ops/circuit_breaker_open_playbook.md`
- `docs/ops/db_degraded_playbook.md`
- `docs/ops/quote_guard_blocks_playbook.md`
- `docs/ops/progress_guard_blocks_playbook.md`
- `docs/ops/handoff_failure_playbook.md`
- `docs/ops/rollback_playbook.md`

Canary advancement checklist was added to `docs/ops/canary_plan.md`.

## Rollback Status

Rollback is documented in `docs/ops/rollback_playbook.md`.

Operational order:

1. Disable tenant `send_enabled`, `actions_enabled`, and `workflow_events_enabled`.
2. Disable tenant `model_provider_enabled` only if provider instability is the active cause.
3. Keep shadow/preview enabled for diagnosis when safe.
4. Use global kill switches only for emergency stop.

Recovery validation:

- P0 returns to 0.
- `uv run pytest tests/agent_runtime -m "integration_db" -q` passes.
- `uv run python -m atendia.simulation.provider_stability_eval --runs 5` passes.
- Affected conversations replay with no critical failures.

## Recommended Flags

For 5% canary:

- `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=true`
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=true` during canary windows, still tenant-gated
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER=openai` only for approved canary tenants
- `ATENDIA_V2_QUOTE_SAFETY_GUARD_MODE=block`
- `ATENDIA_V2_CONVERSATION_PROGRESS_GUARD_MODE=block`
- tenant `agent_runtime_v2.rollout_mode=manual_send`
- tenant `agent_runtime_v2.send_enabled=true`
- tenant `agent_runtime_v2.actions_enabled=false`
- tenant `agent_runtime_v2.model_provider_enabled=true` only for canary tenants

## Residual Risks

- Provider advisor eval was reused from the versioned RC5 artifact after CI/docs-only changes. Re-run it manually before widening beyond 5%.
- Load eval is synthetic; Stage 5% must include replay over sampled real anonymized conversations.
- Pytest still emits existing warnings for `Tone.register` and `.pytest_cache` permissions. They did not affect pass/fail.
- Canary owner placeholders in `docs/ops/canary_plan.md` still need concrete owner assignment before live traffic.

## Final Decision

`READY_FOR_STAGING_SOAK`

`READY_FOR_5_PERCENT_CANARY`

Start 5% only for approved low-risk tenant traffic, monitor for 24h with P0=0 and duplicate side effects=0, then advance using `docs/ops/canary_plan.md`.

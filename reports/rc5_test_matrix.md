# RC5 Staging Soak Test Matrix

Generated: 2026-06-03

## Status

RC5 staging soak and canary readiness are green.

## Test Matrix

| Area | Command | Result |
| --- | --- | --- |
| Scoped lint | `uv run ruff check atendia/simulation/rc5_common.py atendia/simulation/replay_eval.py atendia/simulation/load_eval.py atendia/simulation/chaos_eval.py atendia/observability/rc5_metrics.py` | pass |
| Unit without DB | `uv run pytest tests/agent_runtime -m "not integration_db" -q` | 142 passed, 27 deselected |
| Integration DB | `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test uv run pytest tests/agent_runtime -m "integration_db" -q` | 27 passed, 142 deselected |
| Full agent runtime | `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test uv run pytest tests/agent_runtime -q` | 169 passed |
| Replay eval | `uv run python -m atendia.simulation.replay_eval --dataset atendia/simulation/fixtures/rc5_replay_dataset.anonymized.json --anonymized` | 3/3 pass |
| Load eval | `uv run python -m atendia.simulation.load_eval --conversations 50 --turns-per-conversation 5` | 250 turns pass |
| Chaos eval | `uv run python -m atendia.simulation.chaos_eval` | 10/10 scenarios pass |
| Local deterministic | `uv run python -m atendia.simulation.advisor_first_multiturn` | 10/10 pass |
| Provider stability | `uv run python -m atendia.simulation.provider_stability_eval --runs 5` | 5/5 pass |
| Provider eval | `uv run python -m atendia.simulation.provider_advisor_first_eval` | 40/40 pass |

## Key Metrics

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

## RC5 Artifacts

- `reports/rc5_replay_eval.md`
- `reports/rc5_replay_eval.json`
- `reports/rc5_load_eval.md`
- `reports/rc5_load_eval.json`
- `reports/rc5_chaos_eval.md`
- `reports/rc5_chaos_eval.json`
- `reports/rc5_observability_config.json`
- `reports/rc5_provider_stability_eval.md`
- `reports/rc5_provider_stability_eval.json`
- `reports/rc5_provider_advisor_first_eval.md`
- `reports/rc5_provider_advisor_first_eval.json`

## Notes

- PostgreSQL was provided by `docker-compose.test.yml` with `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test`.
- Provider eval ran with `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_TIMEOUT_S=30` and `ATENDIA_V2_AGENT_RUNTIME_V2_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=100`.
- RC5 lint remains scoped; global ruff debt is tracked separately in `docs/ops/ruff_debt_ticket.md`.

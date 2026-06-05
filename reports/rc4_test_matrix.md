# RC4 Test Matrix

Generated: 2026-06-03

## Summary

RC4 staging-readiness is green for `agent_runtime_v2` with an ephemeral PostgreSQL harness, pytest DB markers, migration-on-session setup, table cleanup between integration tests, and real DB idempotency coverage.

## Matrix

| Stage | Command | Result |
| --- | --- | --- |
| lint | `uv run ruff check atendia/config.py atendia/simulation/provider_advisor_first_eval.py tests/conftest.py tests/agent_runtime/test_action_layer_v2.py tests/agent_runtime/test_rollout_policy.py tests/agent_runtime/test_shadow_service.py tests/agent_runtime/test_rc4_db_idempotency.py` | pass |
| unit without DB | `uv run pytest tests/agent_runtime -m "not integration_db" -q` | 142 passed, 27 deselected |
| integration DB | `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test uv run pytest tests/agent_runtime -m "integration_db" -q` | 27 passed, 142 deselected |
| full runtime suite | `ATENDIA_TEST_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test uv run pytest tests/agent_runtime -q` | 169 passed |
| local deterministic | `uv run python -m atendia.simulation.advisor_first_multiturn` | 10/10, naturalidad 5.0, side_effects 0 |
| provider base/adversarial | `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_TIMEOUT_S=30 ATENDIA_V2_AGENT_RUNTIME_V2_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=100 uv run python -m atendia.simulation.provider_advisor_first_eval` | 40/40, naturalidad 5.0, side_effects 0 |
| provider stability | `uv run python -m atendia.simulation.provider_stability_eval --runs 5` | 5/5 runs, 200/200 accumulated, 5 simulated 429 retries |

## DB Harness

- Compose file: `docker-compose.test.yml`
- Service: `postgres-test`
- Image: `pgvector/pgvector:0.8.2-pg15`
- Test URL env: `ATENDIA_TEST_DATABASE_URL`
- Local URL used: `postgresql+asyncpg://atendia:atendia@localhost:55432/atendia_test`
- Migrations: `alembic upgrade head` runs once before selected `integration_db` tests.
- Cleanup: all public application tables are truncated before and after each `integration_db` test; `alembic_version` is preserved.
- Missing DB behavior: selected `integration_db` tests exit with a clear message if `ATENDIA_TEST_DATABASE_URL` is unset or unreachable.

## Notes

The lint stage is scoped to RC4-touched files because `uv run ruff check .` currently reports pre-existing repository-wide lint debt outside this RC4 change. The CI workflow keeps the stage explicit without turning staging-readiness into a global formatting/refactor pass.

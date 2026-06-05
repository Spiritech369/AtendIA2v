# RC5 DB Idempotency Audit

Generated: 2026-06-03

## Scope

The DB idempotency audit covers the RC4/RC5 integration DB tests plus RC5 soak checks for retry, fallback, circuit breaker, rollout, and shadow-service behavior.

## Evidence

| Check | Evidence | Result |
| --- | --- | --- |
| Provider retry does not duplicate outbox | `tests/agent_runtime/test_rc4_db_idempotency.py` under `integration_db` | pass |
| Provider retry does not duplicate database writes | `tests/agent_runtime/test_rc4_db_idempotency.py` under `integration_db` | pass |
| Provider retry does not duplicate `Cotizacion_Enviada` | `tests/agent_runtime/test_rc4_db_idempotency.py` under `integration_db` | pass |
| Provider retry does not duplicate `Ultima_Cotizacion` | `tests/agent_runtime/test_rc4_db_idempotency.py` under `integration_db` | pass |
| Retry exhausted writes no side effects | `tests/agent_runtime/test_rc4_db_idempotency.py` and `rc5_chaos_eval` | pass |
| Safe fallback creates no false handoff | `tests/agent_runtime/test_rc4_db_idempotency.py` and `rc5_chaos_eval` | pass |
| Open circuit breaker executes no side effects | `tests/agent_runtime/test_rc4_db_idempotency.py` and `rc5_chaos_eval` | pass |
| Rollout policy does not change version mid-turn | `tests/agent_runtime/test_rc4_db_idempotency.py` | pass |
| Shadow service does not duplicate events | `tests/agent_runtime/test_rc4_db_idempotency.py` | pass |

## Test Runs

- `uv run pytest tests/agent_runtime -m "integration_db" -q`: 27 passed, 142 deselected.
- `uv run pytest tests/agent_runtime -q`: 169 passed.
- `uv run python -m atendia.simulation.chaos_eval`: 10/10 scenarios passed.

## Duplicate Side Effects

| Metric | Result |
| --- | ---: |
| `duplicate_side_effect_count` | 0 |
| `outbox_duplicate_count` | 0 |
| `turn_trace_duplicate_count` | 0 |
| `memory_write_duplicate_count` | 0 |
| `handoff_false_positive_count` | 0 |
| `cotizacion_enviada_false_count` | 0 |

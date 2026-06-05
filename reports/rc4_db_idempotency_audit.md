# RC4 DB Idempotency Audit

Generated: 2026-06-03

## Scope

Audit target: real PostgreSQL writes for `agent_runtime_v2` retry and shadow boundaries. The tests run under `@pytest.mark.integration_db` against a migrated ephemeral PostgreSQL database.

Primary test file: `core/tests/agent_runtime/test_rc4_db_idempotency.py`

## Coverage

| Requirement | Test coverage | Result |
| --- | --- | --- |
| provider retry no duplica outbox | `test_provider_retry_persists_quote_side_effects_once` checks `outbound_outbox = 0` after a composer retry succeeds | pass |
| provider retry no duplica database_writes | Same test persists the retried output once through `ContactMemoryService`; `customer_field_update_evidence = 3` exactly for `Producto`, `Ultima_Cotizacion`, `Cotizacion_Enviada` | pass |
| provider retry no duplica `Cotizacion_Enviada` | Same test asserts `Cotizacion_Enviada` evidence count is exactly 1 and field value is `true` | pass |
| provider retry no duplica `Ultima_Cotizacion` | Same test asserts `Ultima_Cotizacion` evidence count is exactly 1 and snapshot id is `quote-r4-cash` | pass |
| retry agotado no escribe side effects | `test_retry_exhausted_and_safe_fallback_write_no_side_effects` fails AdvisorBrain before tool/state boundaries and verifies outbox/evidence/quote fields stay at 0 | pass |
| fallback seguro no crea handoff falso | Same test verifies `human_handoffs = 0` for safe fallback | pass |
| circuit breaker abierto no ejecuta side effects | `test_circuit_breaker_open_does_not_execute_side_effects` opens the provider circuit and verifies outbox/evidence/quote writes remain 0 | pass |
| rollout_policy no cambia version a mitad de turno | `test_rollout_policy_decision_is_stable_within_turn` freezes the first `can_send` decision, mutates tenant rollout config, and verifies the in-turn decision payload remains `manual_send` with `send_enabled = true` | pass |
| shadow_service no duplica eventos | `test_shadow_service_idempotency_and_no_side_effects` runs the same inbound shadow twice and verifies one `turn_traces` row, no outbox, no action logs | pass |

## Existing DB Suites

The original DB-dependent suites are now marked `integration_db` and passed under the harness:

- `test_action_layer_v2.py`
- `test_rollout_policy.py`
- `test_shadow_service.py`

Command evidence:

- `uv run pytest tests/agent_runtime -m "integration_db" -q`: 27 passed
- `uv run pytest tests/agent_runtime -q`: 169 passed

## Boundary Observations

- Provider retry happens before tool/state side-effect persistence.
- Safe AdvisorBrain fallback is side-effect-free when the provider fails before tools.
- Deterministic quote fallback may preserve quote field updates when tools already returned a valid `QuoteSnapshot`; this is intentional and separately covered by the successful retry persistence test.
- Shadow mode remains trace-only: it records `TurnTrace` and does not execute actions, enqueue outbound messages, mutate contact fields, move lifecycle, or emit real workflow events.

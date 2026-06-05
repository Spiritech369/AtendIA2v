# DB Degraded Playbook

## Symptom

Database writes are slow, failing, or temporarily unavailable.

## Metric / Alert

P0: sustained `database_write_error_rate`. Watch `db_write_latency_p95`.

## Impact

Trace, memory, outbox, or action audit writes may be delayed. Customer-visible safety must remain conservative.

## Diagnosis

Check Postgres health, connection pool saturation, migration state, locks, and slow queries.

## Mitigation

Pause send, keep shadow only, reduce canary percentage, restore DB health, and avoid manual retries that may duplicate writes.

## Relevant Flags

- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED`
- tenant `agent_runtime_v2.send_enabled`

## Recovery Validation

Run integration DB tests and load eval; confirm duplicate side effects and write errors are 0.

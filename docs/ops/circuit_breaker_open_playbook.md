# Circuit Breaker Open Playbook

## Symptom

Provider circuit opens and new provider calls are blocked before execution.

## Metric / Alert

P0/P1 depending on volume: `provider_retry_exhausted_count` high or `provider_fallback_response_count` spike.

## Impact

Responses may use safe fallback. No side effects should execute after an open circuit.

## Diagnosis

Inspect provider error kind, cooldown, affected tenant/model key, and recent retry exhaustion.

## Mitigation

Pause send for affected tenants, keep shadow/preview active, wait cooldown, or disable model provider until stability returns.

## Relevant Flags

- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER`
- `ATENDIA_V2_AGENT_RUNTIME_V2_PROVIDER_CIRCUIT_FAILURE_THRESHOLD`
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED`

## Recovery Validation

Confirm circuit state closes, fallback count stops increasing, and chaos eval keeps duplicate side effects at 0.

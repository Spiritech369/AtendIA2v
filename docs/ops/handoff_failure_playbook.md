# Handoff Failure Playbook

## Symptom

Handoff creation fails or handoff counts spike unexpectedly.

## Metric / Alert

P0: `handoff_false_positive_count > 0`. Watch `handoff_create_count`.

## Impact

False handoffs interrupt automation; failed handoffs can leave customers without expected human follow-up.

## Diagnosis

Check handoff action logs, human_handoffs rows, tenant handoff rules, and latest customer intent.

## Mitigation

Pause actions for affected tenants, keep final copy safe, manually route urgent customers, and replay affected turns.

## Relevant Flags

- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED`
- tenant `agent_runtime_v2.actions_enabled`
- tenant handoff rules

## Recovery Validation

Run chaos eval and integration DB tests; confirm no false handoff and no duplicate side effects.

# Provider 429 Playbook

## Symptom

Provider requests are rate limited and retries increase.

## Metric / Alert

P1: `provider_429_rate` high versus baseline. Watch `provider_retry_rate` and `provider_fallback_response_count`.

## Impact

Higher latency and possible safe fallbacks if retries exhaust.

## Diagnosis

Check provider quota, traffic spikes, tenant rollout percentage, and recent load eval results.

## Mitigation

Reduce canary percentage, raise queue spacing, pause provider-heavy tenants, or switch affected tenants to preview/shadow.

## Relevant Flags

- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER`
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_MAX_RETRIES`
- tenant `agent_runtime_v2.model_provider_enabled`

## Recovery Validation

Run `provider_stability_eval --runs 5`; confirm `provider_fallback_response_count=0` and safety rates stay 0.

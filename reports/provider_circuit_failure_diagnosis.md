# Provider Circuit Failure Diagnosis

- decision: `NOT_READY_PROVIDER_RATE_LIMIT`
- root_cause: real provider 429 on Composer calls, ending in `ProviderRetryExhaustedError` and fallback responses.
- provider_circuit_breaker_open_count: `0`
- provider_429_count: `600`
- provider_retry_count: `400`
- provider_retry_exhausted_count: `200`
- provider_fallback_response_count: `200`
- side_effects: `0`

## Requested Failed Cases

| case | classification | failures | 429 | retries | retry_exhausted | fallback | repeated | template |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| adv_15 | REAL_PROVIDER_429 | robotic_template | 15 | 10 | 5 | 5 | 0 | 1 |
| adv_18 | REAL_PROVIDER_429 | repeated_question_or_exact_response_detected | 15 | 10 | 5 | 5 | 1 | 0 |
| adv_24 | REAL_PROVIDER_429 | repeated_question_or_exact_response_detected | 15 | 10 | 5 | 5 | 1 | 0 |
| adv_28 | REAL_PROVIDER_429 | repeated_question_or_exact_response_detected | 15 | 10 | 5 | 5 | 1 | 0 |

## Conclusion

No evidence of shared circuit contamination remains after isolating provider eval circuit scope per case. The current blocker is provider rate limiting/retry exhaustion, plus fallback-induced template/repetition artifacts. Canary must not start.

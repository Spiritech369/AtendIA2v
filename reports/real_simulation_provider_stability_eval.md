# Provider Stability Eval

- runs_passed: `0/5`
- cases_passed_accumulated: `150/200`
- provider_429_count: `5`
- provider_retry_count: `5`
- provider_fallback_response_count: `1000`
- quoted_without_canonical_product_rate: `0.0`
- price_without_snapshot_rate: `0.0`
- stale_quote_rate: `0.0`
- repeated_question_rate: `0.04`
- exact_response_repeat_rate: `0.005`
- failure_cause_counts: `{'provider_retry_exhausted': 5}`
- side_effects: `0`
- definition_of_done_pass: `False`

| run | pass/fail | cases | simulated_429 | retries | failure_cause |
| --- | --- | --- | --- | --- | --- |
| 1 | fail | 30/40 | 1 | 1 | provider_retry_exhausted |
| 2 | fail | 30/40 | 1 | 1 | provider_retry_exhausted |
| 3 | fail | 30/40 | 1 | 1 | provider_retry_exhausted |
| 4 | fail | 30/40 | 1 | 1 | provider_retry_exhausted |
| 5 | fail | 30/40 | 1 | 1 | provider_retry_exhausted |
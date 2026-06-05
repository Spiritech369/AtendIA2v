# RC5 Chaos Eval

- scenarios_passed: `10/10`
- critical_failure_count: `0`
- duplicate_side_effect_count: `0`
- handoff_false_positive_count: `0`
- cotizacion_enviada_false_count: `0`
- definition_of_done_pass: `True`

| scenario | result | retries | fallbacks | failures |
| --- | --- | --- | --- | --- |
| provider_429_intermittent | pass | 1 | 0 | ok |
| provider_timeout | pass | 0 | 1 | ok |
| provider_malformed_json | pass | 0 | 1 | ok |
| provider_retry_exhausted | pass | 1 | 1 | ok |
| postgres_slow | pass | 0 | 0 | ok |
| postgres_temporarily_down | pass | 0 | 0 | ok |
| quote_resolver_fails | pass | 0 | 0 | ok |
| requirements_resolver_fails | pass | 0 | 0 | ok |
| handoff_service_fails | pass | 0 | 0 | ok |
| outbox_write_fails | pass | 0 | 0 | ok |

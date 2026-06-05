# RC4 Provider Stability Eval

Generated: 2026-06-03

## Provider Base + Adversarial

Command:

`ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_TIMEOUT_S=30 ATENDIA_V2_AGENT_RUNTIME_V2_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=100 uv run python -m atendia.simulation.provider_advisor_first_eval`

Result:

- provider_used: `openai`
- model: `gpt-4o-mini`
- cases_passed: `40/40`
- base_cases_passed: `10/10`
- adversarial_cases_passed: `30/30`
- turns_total: `200`
- naturalidad_avg: `5.0`
- quoted_without_canonical_product_rate: `0.0`
- price_without_snapshot_rate: `0.0`
- stale_quote_rate: `0.0`
- repeated_question_rate: `0.0`
- exact_response_repeat_rate: `0.0`
- provider_error_rate: `0.0`
- provider_retry_count: `0`
- provider_fallback_response_count: `0`
- side_effects: `whatsapp=0`, `outbox=0`, `database_writes=0`
- definition_of_done_pass: `true`

Source artifacts:

- `reports/provider_advisor_first_eval.json`
- `reports/provider_advisor_first_eval.md`
- `reports/provider_vs_local_comparison.md`

## Stability Runs

Command:

`uv run python -m atendia.simulation.provider_stability_eval --runs 5`

Result:

- mode: `baseline_with_simulated_429`
- runs_passed: `5/5`
- cases_passed_accumulated: `200/200`
- provider_429_count: `5`
- provider_retry_count: `5`
- provider_fallback_response_count: `0`
- quoted_without_canonical_product_rate: `0.0`
- price_without_snapshot_rate: `0.0`
- stale_quote_rate: `0.0`
- repeated_question_rate: `0.0`
- exact_response_repeat_rate: `0.0`
- side_effects: `0`
- definition_of_done_pass: `true`

Source artifacts:

- `reports/provider_stability_eval.json`
- `reports/provider_stability_eval.md`

## Note

The live provider eval was run with a 30 second model timeout and circuit threshold 100 to avoid treating transient latency as conversational quality failure. The reliability layer itself was not modified.

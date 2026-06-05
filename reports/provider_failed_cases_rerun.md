# Provider Failed Cases Rerun

- command: `uv run python -m atendia.simulation.provider_advisor_first_eval --case-id adv_15 --case-id adv_18 --case-id adv_24 --case-id adv_28`
- cases_passed: `
0
/
4
`
- provider_429_count: `
60
`
- provider_retry_count: `
40
`
- provider_retry_exhausted_count: `
20
`
- provider_fallback_response_count: `
20
`
- side_effects: `0`

| case | classification | failures | 429 | retries | retry exhausted | fallback |
| --- | --- | --- | --- | --- | --- | --- |
| adv_15 | REAL_PROVIDER_429 | robotic_template | 15 | 10 | 5 | 5 |
| adv_18 | REAL_PROVIDER_429 | repeated_question_or_exact_response_detected | 15 | 10 | 5 | 5 |
| adv_24 | REAL_PROVIDER_429 | repeated_question_or_exact_response_detected | 15 | 10 | 5 | 5 |
| adv_28 | REAL_PROVIDER_429 | repeated_question_or_exact_response_detected | 15 | 10 | 5 | 5 |

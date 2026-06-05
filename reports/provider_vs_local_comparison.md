# Provider vs Local Comparison

- local_cases_passed: `10`
- provider_base_cases_passed: `0`
- provider_adversarial_cases_passed: `0`
- provider_naturalidad_avg: `4.27`
- local_naturalidad_avg: `5.0`

## Observations

- Local simulation is deterministic and only covers the original 10 cases.
- Provider run uses GPT for AdvisorBrain and Composer, while tools and StateWriter stay deterministic.
- Provider produced 4 cases with validation failures; inspect provider_advisor_first_eval.json.
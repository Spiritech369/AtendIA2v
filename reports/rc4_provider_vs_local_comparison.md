# Provider vs Local Comparison

- local_cases_passed: `10`
- provider_base_cases_passed: `10`
- provider_adversarial_cases_passed: `30`
- provider_naturalidad_avg: `5.0`
- local_naturalidad_avg: `5.0`

## Observations

- Local simulation is deterministic and only covers the original 10 cases.
- Provider run uses GPT for AdvisorBrain and Composer, while tools and StateWriter stay deterministic.
- Provider passed all hard validations in this dry-run harness.
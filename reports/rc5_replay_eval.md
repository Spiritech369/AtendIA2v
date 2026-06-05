# RC5 Replay Eval

- replay_cases_passed: `0/1`
- critical_failure_count: `1`
- duplicate_side_effect_count: `0`
- handoff_false_positive_count: `0`
- documents_stage_false_positive_count: `0`
- avg_turns_to_quote: `0.0`
- avg_turns_to_handoff: `0.0`
- definition_of_done_pass: `False`

No raw customer messages are written to this report.

| case | result | turns | turns_to_quote | turns_to_handoff | notes |
| --- | --- | --- | --- | --- | --- |
| sim_quote_without_product | fail | 1 | - | - | expected_quote_not_replayable |

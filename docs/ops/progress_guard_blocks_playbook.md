# Progress Guard Blocks Playbook

## Symptom

Conversation progress guard sanitizes repeated or stuck responses.

## Metric / Alert

P1: sustained `progress_guard_block_rate > 0.05`.

## Impact

The user gets safer copy, but high rates can indicate repeated questions or poor context use.

## Diagnosis

Inspect trace progress payload, repeated slot/action, last assistant similarity, and latest customer act.

## Mitigation

Hold canary advancement, replay affected conversations, tune tenant instructions or eval dataset. Do not bypass the guard.

## Relevant Flags

- `ATENDIA_V2_CONVERSATION_PROGRESS_GUARD_MODE`
- tenant runtime instructions and visible contact fields

## Recovery Validation

Provider eval and replay eval must show `repeated_question_rate=0.0` and acceptable progress guard block rate.

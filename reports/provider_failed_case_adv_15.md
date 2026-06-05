# Provider Advisor-first Evaluation

## Executive Summary

- provider_used: `openai`
- model: `gpt-4o-mini`
- provider_error_rate: `0.0`
- provider_429_count: `0`
- provider_timeout_count: `0`
- provider_5xx_count: `0`
- provider_retry_count: `0`
- provider_retry_exhausted_count: `0`
- provider_circuit_breaker_open_count: `0`
- provider_fallback_response_count: `0`
- provider_latency_p50: `1917`
- provider_latency_p95: `2977`
- provider_latency_p99: `2977`
- cases_passed: `0/1`
- naturalidad_avg: `4.8`
- repeated_question_rate: `0.0`
- exact_response_repeat_rate: `0.0`
- repeated_slot_question_rate: `0.0`
- repeated_quote_without_request_rate: `0.0`
- repeated_requirements_without_request_rate: `0.0`
- progress_guard_blocks_total: `0`
- progress_guard_block_rate: `0.0`
- progress_guard_sanitized_messages_count: `0`
- generic_sanitizer_fallback_rate: `0.0`
- answer_relevance_rate: `0.4`
- documents_request_answered_rate: `0.0`
- conversation_progress_rate: `1.0`
- stale_quote_rate: `0.0`
- quoted_without_canonical_product_rate: `0.0`
- price_without_snapshot_rate: `0.0`
- price_amount_mismatch_rate: `0.0`
- quote_guard_blocks_total: `0`
- sanitized_messages_count: `0`
- quote_active_phrase_rate: `0`
- definition_of_done_pass: `True`
- side_effects: `whatsapp=0`, `outbox=0`, `database_writes=0`

## Case Matrix

| case | source | pass/fail | final_stage | naturalidad | repeated_question | stale_quote | failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| adv_15 | adversarial | fail | handoff | 4.8 | False | False | robotic_template |

## Response Examples

- `adv_15`: Para cotizarte bien, dime que modelo quieres o elige una de las opciones.
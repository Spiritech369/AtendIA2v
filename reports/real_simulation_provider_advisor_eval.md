# Provider Advisor-first Evaluation

## Executive Summary

- provider_used: `openai`
- model: `gpt-4o-mini`
- provider_error_rate: `0.75`
- provider_429_count: `600`
- provider_timeout_count: `0`
- provider_5xx_count: `0`
- provider_retry_count: `400`
- provider_retry_exhausted_count: `200`
- provider_circuit_breaker_open_count: `0`
- provider_fallback_response_count: `200`
- provider_latency_p50: `1973`
- provider_latency_p95: `2177`
- provider_latency_p99: `2415`
- cases_passed: `30/40`
- naturalidad_avg: `4.81`
- repeated_question_rate: `0.04`
- exact_response_repeat_rate: `0.005`
- repeated_slot_question_rate: `0.0`
- repeated_quote_without_request_rate: `0.0`
- repeated_requirements_without_request_rate: `0.0`
- progress_guard_blocks_total: `3`
- progress_guard_block_rate: `0.015`
- progress_guard_sanitized_messages_count: `3`
- generic_sanitizer_fallback_rate: `0.0`
- answer_relevance_rate: `0.615`
- documents_request_answered_rate: `0.6667`
- conversation_progress_rate: `0.96`
- stale_quote_rate: `0.0`
- quoted_without_canonical_product_rate: `0.0`
- price_without_snapshot_rate: `0.0`
- price_amount_mismatch_rate: `0.0`
- quote_guard_blocks_total: `0`
- sanitized_messages_count: `0`
- quote_active_phrase_rate: `0`
- definition_of_done_pass: `False`
- side_effects: `whatsapp=0`, `outbox=0`, `database_writes=0`

## Case Matrix

| case | source | pass/fail | final_stage | naturalidad | repeated_question | stale_quote | failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| case_01 | base | pass | handoff | 5.0 | False | False | ok |
| case_02 | base | pass | handoff | 5.0 | False | False | ok |
| case_03 | base | pass | handoff | 5.0 | False | False | ok |
| case_04 | base | pass | handoff | 5.0 | False | False | ok |
| case_05 | base | fail | handoff | 4.1 | True | False | repeated_question_or_exact_response_detected |
| case_06 | base | pass | handoff | 5.0 | False | False | ok |
| case_07 | base | pass | handoff | 5.0 | False | False | ok |
| case_08 | base | fail | handoff | 4.8 | False | False | robotic_template, robotic_template |
| case_09 | base | pass | handoff | 5.0 | False | False | ok |
| case_10 | base | fail | handoff | 4.1 | True | False | repeated_question_or_exact_response_detected |
| adv_01 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_02 | adversarial | fail | handoff | 4.1 | True | False | repeated_question_or_exact_response_detected |
| adv_03 | adversarial | fail | handoff | 4.1 | True | False | repeated_question_or_exact_response_detected |
| adv_04 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_05 | adversarial | fail | handoff | 4.1 | True | False | repeated_question_or_exact_response_detected |
| adv_06 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_07 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_08 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_09 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_10 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_11 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_12 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_13 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_14 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_15 | adversarial | fail | handoff | 4.8 | False | False | robotic_template |
| adv_16 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_17 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_18 | adversarial | fail | handoff | 4.1 | True | False | repeated_question_or_exact_response_detected |
| adv_19 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_20 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_21 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_22 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_23 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_24 | adversarial | fail | handoff | 4.1 | True | False | repeated_question_or_exact_response_detected |
| adv_25 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_26 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_27 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_28 | adversarial | fail | handoff | 4.1 | True | False | repeated_question_or_exact_response_detected |
| adv_29 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_30 | adversarial | pass | handoff | 5.0 | False | False | ok |

## Response Examples

- `case_01`: De base ocupas INE y comprobante de domicilio. Segun el plan puede aplicar referencia adicional.
- `case_02`: Va, te doy continuidad con el siguiente paso disponible.
- `case_03`: Para cotizarte bien, dime que modelo quieres o elige una de las opciones.
- `case_04`: Va, el siguiente paso es confirmar documentos o revisar si quieres otra opcion.
- `case_05`: Para cotizarte bien, dime que modelo quieres o elige una de las opciones.
- `case_06`: Va, seguimos con el avance sin volver a listar lo mismo.
- `case_07`: Para cotizarte bien, dime que modelo quieres o elige una de las opciones.
- `case_08`: Tomo tu mensaje y reviso el siguiente paso con el contexto actual.
- `case_09`: Va, el siguiente paso es confirmar documentos o revisar si quieres otra opcion.
- `case_10`: Tomo tu mensaje y reviso el siguiente paso con el contexto actual.
- `adv_01`: Te doy continuidad con lo que ya tenemos en la conversacion.
- `adv_02`: Va, el siguiente paso es confirmar documentos o revisar si quieres otra opcion.
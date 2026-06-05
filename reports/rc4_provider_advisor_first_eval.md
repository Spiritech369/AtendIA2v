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
- provider_latency_p50: `2913`
- provider_latency_p95: `6004`
- provider_latency_p99: `7213`
- cases_passed: `40/40`
- naturalidad_avg: `5.0`
- repeated_question_rate: `0.0`
- exact_response_repeat_rate: `0.0`
- repeated_slot_question_rate: `0.0`
- repeated_quote_without_request_rate: `0.0`
- repeated_requirements_without_request_rate: `0.0`
- progress_guard_blocks_total: `3`
- progress_guard_block_rate: `0.015`
- progress_guard_sanitized_messages_count: `3`
- generic_sanitizer_fallback_rate: `0.0`
- answer_relevance_rate: `0.885`
- documents_request_answered_rate: `0.8333`
- conversation_progress_rate: `1.0`
- stale_quote_rate: `0.0`
- quoted_without_canonical_product_rate: `0.0`
- price_without_snapshot_rate: `0.0`
- price_amount_mismatch_rate: `0.0`
- quote_guard_blocks_total: `0`
- sanitized_messages_count: `0`
- quote_active_phrase_rate: `0.0`
- definition_of_done_pass: `True`
- side_effects: `whatsapp=0`, `outbox=0`, `database_writes=0`

## Case Matrix

| case | source | pass/fail | final_stage | naturalidad | repeated_question | stale_quote | failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| case_01 | base | pass | cliente_potencial | 5.0 | False | False | ok |
| case_02 | base | pass | nuevos | 5.0 | False | False | ok |
| case_03 | base | pass | nuevos | 5.0 | False | False | ok |
| case_04 | base | pass | nuevos | 5.0 | False | False | ok |
| case_05 | base | pass | cliente_potencial | 5.0 | False | False | ok |
| case_06 | base | pass | cliente_potencial | 5.0 | False | False | ok |
| case_07 | base | pass | nuevos | 5.0 | False | False | ok |
| case_08 | base | pass | nuevos | 5.0 | False | False | ok |
| case_09 | base | pass | handoff | 5.0 | False | False | ok |
| case_10 | base | pass | nuevos | 5.0 | False | False | ok |
| adv_01 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_02 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_03 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_04 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_05 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_06 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_07 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_08 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_09 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_10 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_11 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_12 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_13 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_14 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_15 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_16 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_17 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_18 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_19 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_20 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_21 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_22 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_23 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_24 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_25 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_26 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_27 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_28 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_29 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_30 | adversarial | pass | nuevos | 5.0 | False | False | ok |

## Response Examples

- `case_01`: Para continuar con la cotización de la Adventure Elite 150 CC, necesitas presentar tu INE y un comprobante de domicilio. ¿Te gustaría que te ayude con algo más?
- `case_02`: Ya tienes los documentos que necesitas. El siguiente paso es confirmar la cotización del R4 250 CC. Te mantendré informado.
- `case_03`: Ya tengo el modelo Work 200 CC y tu antigüedad laboral de 1 año. Sin embargo, necesito confirmar la cotización del sistema antes de darte un precio. Te mantendré informado sobre los siguientes pasos.
- `case_04`: Voy a proceder a obtener la cotización para el modelo U5 150 CC con el plan de pago contado. Te mantendré informado.
- `case_05`: Para R4 250 CC con Sin Comprobantes, el enganche es de $12,580 y los pagos son de $1,398 por 36 pagos. Si estás listo, puedo indicarte los documentos que necesitas para continuar.
- `case_06`: Va, seguimos con el avance sin volver a listar lo mismo.
- `case_07`: Para poder cotizar la Adventure Elite 150 CC, necesito obtener la cotización del sistema. Esto es necesario para asegurarnos de que te brinde la información correcta. Te mantendré informado.
- `case_08`: Aún no tengo la cotización final para la R4 250 CC. Estoy en proceso de confirmarla. Te avisaré en cuanto tenga la información.
- `case_09`: Va, el siguiente paso es confirmar documentos o revisar si quieres otra opcion.
- `case_10`: Ya tengo la información necesaria sobre el modelo R4 250 CC. Sin embargo, no puedo proporcionarte la cotización en este momento. Te recomiendo que revises los requisitos para el plan que mencionaste y, una vez que tengas todo listo, podremos avanzar con la cotización.
- `adv_01`: Te doy continuidad con lo que ya tenemos en la conversacion.
- `adv_02`: Va, el siguiente paso es confirmar documentos o revisar si quieres otra opcion.
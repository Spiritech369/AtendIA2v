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
- provider_latency_p50: `3042`
- provider_latency_p95: `7370`
- provider_latency_p99: `9837`
- cases_passed: `40/40`
- naturalidad_avg: `5.0`
- repeated_question_rate: `0.0`
- exact_response_repeat_rate: `0.0`
- repeated_slot_question_rate: `0.0`
- repeated_quote_without_request_rate: `0.0`
- repeated_requirements_without_request_rate: `0.0`
- progress_guard_blocks_total: `9`
- progress_guard_block_rate: `0.045`
- progress_guard_sanitized_messages_count: `9`
- generic_sanitizer_fallback_rate: `0.0`
- answer_relevance_rate: `0.92`
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
| adv_02 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_03 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_04 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_05 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_06 | adversarial | pass | nuevos | 5.0 | False | False | ok |
| adv_07 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_08 | adversarial | pass | handoff | 5.0 | False | False | ok |
| adv_09 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
| adv_10 | adversarial | pass | cliente_potencial | 5.0 | False | False | ok |
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

- `case_01`: Para avanzar con la cotización de la Adventure Elite 150 CC con el plan de Nómina Tarjeta, necesitas presentar tu INE y un comprobante de domicilio. ¿Te gustaría que te explique los siguientes pasos?
- `case_02`: Ya que estás juntando los documentos necesarios para el plan Sin Comprobantes, procederé a confirmar la cotización de la R4 250 CC. Te mantendré informado.
- `case_03`: Ya tengo el modelo, pero necesito confirmar la cotización del sistema antes de darte precio para no pasarte un dato incorrecto.
- `case_04`: Voy a proceder a obtener la cotización para el modelo U5 150 CC con el plan de pago contado. Te mantendré informado.
- `case_05`: Perfecto, uso la cotizacion validada del sistema. Para Adventure Elite 150 CC con Sin Comprobantes, el enganche es de $10,080 y los pagos son de $1,120 por 36 pagos.
- `case_06`: Va, seguimos con el avance sin volver a listar lo mismo.
- `case_07`: Para poder cotizar la Adventure Elite 150 CC, necesito obtener la cotización del sistema. Te informaré en cuanto tenga esa información.
- `case_08`: Para completar la cotización de la R4 250 CC, necesito que me proporciones referencias. ¿Puedes ayudarme con eso?
- `case_09`: Voy a conectar contigo con Francisco para que te ayude con la cotización de la Adventure Elite 150 CC. Él podrá asistirte mejor con tu situación.
- `case_10`: Para proceder con la cotización del modelo R4, necesito que confirmes que deseas continuar con el proceso. ¿Te gustaría que te comparta los requisitos específicos para el plan Sin Comprobantes?
- `adv_01`: Tomo tu mensaje y reviso el siguiente paso con el contexto actual.
- `adv_02`: Para continuar con el proceso, necesito que confirmes que deseas proceder con la cotización del R4 250 CC.
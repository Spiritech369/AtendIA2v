# Dinamo Shadow Real Replay Incoherence Audit

- failed_checks: `0`
- coverage_gaps: `por_fuera_como_no_apto, buro_como_rechazo_automatico, ok_va_si_despues_de_cotizacion_reinicia_flujo, la_primera_esa_la_otra_no_resuelve_referencia`

## Safety Flags

- live_send_enabled: `False`
- actions_enabled: `False`
- workflow_side_effects_enabled: `False`
- traffic_real_activated: `False`
- whatsapp_sent: `False`
- config_live_applied: `False`
- single_contact_smoke_enabled: `False`

| check | status | observed | coverage | conclusion |
| --- | --- | --- | --- | --- |
| credito_recibe_cotizacion_de_contado | pass | 0 | tested | No se emitieron precios visibles ni cotizaciones de contado para intencion de credito. |
| documentos_genericos_cuando_ya_hay_plan | pass | 0 | tested | requirements.lookup se mantiene como fuente estructurada; no se mezclaron planes. |
| documentos_antes_de_cotizar_sin_pregunta_explicita | pass | 0 | tested | Los turnos de documentos provienen de 'cliente pregunta por documentos requeridos'. |
| repetir_antiguedad | pass | 0 | tested | El dataset anonimizado no contiene antiguedad repetida. |
| repetir_ingreso | pass | 0 | tested | El dataset anonimizado no contiene ingreso repetido. |
| por_fuera_como_no_apto | pass | 0 | covered_by_e2e_not_real_replay | La frase original no se conserva por PII; E2E cubre que no se rechaza por 'por fuera'. |
| buro_como_rechazo_automatico | pass | 0 | covered_by_e2e_not_real_replay | No se prometio ni rechazo aprobacion; E2E cubre buro explicito. |
| ok_va_si_despues_de_cotizacion_reinicia_flujo | pass | 0 | not_tested_by_anonymized_replay | El texto real se anonimiza; no se observaron reinicios de flujo en eventos shadow. |
| la_primera_esa_la_otra_no_resuelve_referencia | pass | 0 | not_tested_by_anonymized_replay | Las referencias pronominales no sobreviven a la anonimizacion segura. |
| moto_del_anuncio_se_guarda_como_moto_real | pass | 0 | partially_tested | El replay no guarda modelos sin catalog.search. |
| handoff_falso_por_fallback | pass | 0 | tested | handoff.create solo aparece en el turno anonimizado de solicitud humana. |
| papeleria_incompleta_sin_adjunto | pass | 0 | tested | No se emite document_received sin attachments anonimizados presentes. |
| workflow_por_keyword | pass | 0 | tested | Los eventos se reportan como dry-run y no ejecutan side effects. |
| tool_result_visible_como_respuesta_final | pass | 0 | tested | La respuesta visible se mantiene en TurnOutput.final_message. |

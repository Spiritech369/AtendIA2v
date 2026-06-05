# Dinamo Persistent Simulation Results - 2026-06-01

## 1. Executive summary

- tenant_id: `31673477-4dfb-45b1-a0a1-caf6aefd1fcb`
- agent_id: `8bdbca25-537e-400e-b8d4-40d1717756eb`
- simulation_run_id: `0a98edfe-e656-4865-97d8-b4d95c612e92`
- cases_total: `15`
- cases_passed: `14`
- cases_failed: `1`
- turns_total: `18`
- score: `0.9847`
- ready_for_shadow: `no`
- ready_for_manual_send: `no`
- provider used: `local_deterministic`
- legacy_interference: `False`

Provider note: `local_deterministic` is allowed for harness development only. It is not a final readiness signal until provider approval is complete.

## 2. Safety confirmation

- WhatsApp sends: `0`
- outbound outbox writes: `0`
- real customer writes: `0`
- simulated customer writes: `15`
- simulated lifecycle moves: `11`
- real external actions: `0`
- simulation actions: `21`
- workflow executions: `0`

## 3. Case matrix

| Case | Category | Conversation ID | Final stage | Score | Pass/Fail | Main failure | Legacy used |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `orden_credito_nomina_tarjeta_10` | credito_nomina | `111f5bcc-81a6-4a12-9442-9b2364c39a0b` | credito | `1.0` | passed |  | false |
| `antiguedad_insuficiente` | credito_riesgo | `6d7ebc16-6d95-4d9c-bff6-fe52120db9f4` | credito | `1.0` | passed |  | false |
| `sin_trabajo` | credito_riesgo | `dbaacba5-78f0-4a7d-b282-4962ad2279ac` | nuevos | `1.0` | passed |  | false |
| `sin_comprobantes_20` | credito_informal | `f0b2d795-9af7-4bb7-a1fc-61594db1eade` | credito | `1.0` | passed |  | false |
| `pensionado_10` | credito_pensionado | `21125b84-0fc7-4642-9255-a7e689db52eb` | credito | `0.74` | failed | field income_type expected 'Pensionado' got 'Pensionados' | false |
| `guardia_30` | credito_guardia | `0dac65a7-7899-4d5e-95af-aa1f7e53f134` | credito | `1.0` | passed |  | false |
| `cliente_pide_catalogo` | catalogo | `9fa388dc-29fb-40ce-a913-ac38b1d0c1fa` | nuevos | `1.0` | passed |  | false |
| `pregunta_documentos_sin_plan` | documentos | `8d49d721-caa5-427e-91b0-31675a05af5a` | nuevos | `1.0` | passed |  | false |
| `manda_ine_antes_de_plan` | documentos | `19a7c612-c54a-429f-8824-ca8f48f5946f` | doc_incompleta | `1.0` | passed |  | false |
| `documento_borroso` | documentos | `d0bb6329-cc6d-484b-ba89-799d4b78c8e3` | doc_incompleta | `1.0` | passed |  | false |
| `comprobante_mama_estado_mama` | documentos_ingreso | `882b014c-105a-4c2f-a774-16505f5fd493` | nuevos | `1.0` | passed |  | false |
| `nomina_excel` | documentos_ingreso | `d07b45be-66e3-47ea-8277-dad9ca277ce3` | credito | `1.0` | passed |  | false |
| `cliente_enojo_repeticion` | tono | `1eb6f9f4-2efd-47b6-9dd2-54fc9a2910b4` | credito | `1.0` | passed |  | false |
| `buro_miedo` | buro | `3ed79b9d-5aaf-44db-acbc-8a49c45293fe` | credito | `1.0` | passed |  | false |
| `cliente_pide_humano` | handoff | `439a93de-6d8a-4c7d-a205-29b41a4a8611` | nuevos | `1.0` | passed |  | false |

## 4. Conversation transcripts

### orden_credito_nomina_tarjeta_10

- conversation_id: `111f5bcc-81a6-4a12-9442-9b2364c39a0b`
- initial stage: `nuevos`
- final stage: `credito`
- initial fields: `{}`
- final fields: `{'income_type': 'Nomina', 'ENGANCHE': '10000'}`

- customer message: Hola, quiero una moto a credito
- agent final_message: Claro, te ayudo con credito. Para avanzar, dime como recibes tus ingresos.
- citations: `1`
- field updates: `[]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Customer asked for credit.', 'evidence': ['Hola, quiero una moto a credito'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `iniciar credito y preguntar ingreso` / `pass`

- customer message: Me depositan nomina en tarjeta
- agent final_message: Perfecto, tomo nomina como tipo de ingreso. Que modelo quieres cotizar?
- citations: `1`
- field updates: `[{'field_key': 'income_type', 'value': 'Nomina', 'reason': 'Customer mentioned payroll income.', 'evidence': ['Me depositan nomina en tarjeta'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Customer is entering credit flow.', 'evidence': ['Me depositan nomina en tarjeta'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `guardar ingreso nomina` / `pass`

- customer message: Tengo 10 mil de enganche
- agent final_message: Perfecto, tomo $10,000 como enganche para la simulacion.
- citations: `0`
- field updates: `[{'field_key': 'ENGANCHE', 'value': '10000', 'reason': 'Customer provided down payment.', 'evidence': ['Tengo 10 mil de enganche'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `None`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `guardar enganche y cotizar sin prometer aprobacion` / `pass`

### antiguedad_insuficiente

- conversation_id: `6d7ebc16-6d95-4d9c-bff6-fe52120db9f4`
- initial stage: `nuevos`
- final stage: `credito`
- initial fields: `{}`
- final fields: `{}`

- customer message: Tengo un mes trabajando
- agent final_message: Con un mes de antiguedad conviene que una persona revise si aplica. No te puedo prometer aprobacion.
- citations: `0`
- field updates: `[]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Customer has insufficient seniority risk.', 'evidence': ['Tengo un mes trabajando'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `explicar que requiere revision sin prometer aprobacion` / `pass`

### sin_trabajo

- conversation_id: `dbaacba5-78f0-4a7d-b282-4962ad2279ac`
- initial stage: `nuevos`
- final stage: `nuevos`
- initial fields: `{}`
- final fields: `{}`

- customer message: Ahorita no tengo trabajo, si me aprueban?
- agent final_message: No te puedo prometer aprobacion. Sin trabajo conviene que una persona revise tu caso antes de avanzar.
- citations: `0`
- field updates: `[]`
- lifecycle movements: `None`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `no prometer aprobacion y escalar` / `pass`

### sin_comprobantes_20

- conversation_id: `f0b2d795-9af7-4bb7-a1fc-61594db1eade`
- initial stage: `nuevos`
- final stage: `credito`
- initial fields: `{}`
- final fields: `{'income_type': 'Sin Comprobantes', 'CREDITO': 'Sin Comprobantes', 'ENGANCHE': '20000'}`

- customer message: Me pagan por fuera
- agent final_message: Va, eso corresponde al plan sin comprobar ingresos. Para simularlo bien, que modelo quieres cotizar?
- citations: `0`
- field updates: `[{'field_key': 'income_type', 'value': 'Sin Comprobantes', 'reason': 'Customer has informal income.', 'evidence': ['Me pagan por fuera'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}, {'field_key': 'CREDITO', 'value': 'Sin Comprobantes', 'reason': 'Customer has informal income.', 'evidence': ['Me pagan por fuera'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Customer is entering credit flow.', 'evidence': ['Me pagan por fuera'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `usar plan sin comprobantes` / `pass`

- customer message: Tengo 20 mil de enganche
- agent final_message: Perfecto, tomo $20,000 como enganche para la simulacion.
- citations: `0`
- field updates: `[{'field_key': 'ENGANCHE', 'value': '20000', 'reason': 'Customer provided down payment.', 'evidence': ['Tengo 20 mil de enganche'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `None`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `guardar enganche` / `pass`

### pensionado_10

- conversation_id: `21125b84-0fc7-4642-9255-a7e689db52eb`
- initial stage: `nuevos`
- final stage: `credito`
- initial fields: `{}`
- final fields: `{'income_type': 'Pensionados', 'CREDITO': 'Pensionados'}`

- customer message: Soy pensionado
- agent final_message: Perfecto, lo revisamos como pensionado. Que modelo quieres cotizar?
- citations: `0`
- field updates: `[{'field_key': 'income_type', 'value': 'Pensionados', 'reason': 'Customer said they are pensioned.', 'evidence': ['Soy pensionado'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}, {'field_key': 'CREDITO', 'value': 'Pensionados', 'reason': 'Customer said they are pensioned.', 'evidence': ['Soy pensionado'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Customer is entering credit flow.', 'evidence': ['Soy pensionado'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `identificar pensionado` / `pass`

### guardia_30

- conversation_id: `0dac65a7-7899-4d5e-95af-aa1f7e53f134`
- initial stage: `nuevos`
- final stage: `credito`
- initial fields: `{}`
- final fields: `{'income_type': 'Guardia de Seguridad', 'CREDITO': 'Guardia de Seguridad'}`

- customer message: Trabajo de guardia de seguridad
- agent final_message: Perfecto, guardia de seguridad normalmente se revisa con ese plan. Que modelo quieres cotizar?
- citations: `0`
- field updates: `[{'field_key': 'income_type', 'value': 'Guardia de Seguridad', 'reason': 'Customer works security.', 'evidence': ['Trabajo de guardia de seguridad'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}, {'field_key': 'CREDITO', 'value': 'Guardia de Seguridad', 'reason': 'Customer works security.', 'evidence': ['Trabajo de guardia de seguridad'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Customer is entering credit flow.', 'evidence': ['Trabajo de guardia de seguridad'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `identificar guardia y 30 por ciento` / `pass`

### cliente_pide_catalogo

- conversation_id: `9fa388dc-29fb-40ce-a913-ac38b1d0c1fa`
- initial stage: `nuevos`
- final stage: `nuevos`
- initial fields: `{}`
- final fields: `{}`

- customer message: Me pasas catalogo?
- agent final_message: Te puedo compartir opciones del catalogo activo. No confirmo precio o inventario si no aparece en la fuente.
- citations: `1`
- field updates: `[]`
- lifecycle movements: `None`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `ofrecer modelos sin inventar disponibilidad` / `pass`

### pregunta_documentos_sin_plan

- conversation_id: `8d49d721-caa5-427e-91b0-31675a05af5a`
- initial stage: `nuevos`
- final stage: `nuevos`
- initial fields: `{}`
- final fields: `{}`

- customer message: Que documentos piden?
- agent final_message: Los base son INE vigente y comprobante de domicilio. Segun el plan puede cambiar lo adicional; primero confirmemos tu tipo de ingreso.
- citations: `1`
- field updates: `[]`
- lifecycle movements: `None`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `responder documentos base y pedir tipo de ingreso` / `pass`

### manda_ine_antes_de_plan

- conversation_id: `19a7c612-c54a-429f-8824-ca8f48f5946f`
- initial stage: `nuevos`
- final stage: `doc_incompleta`
- initial fields: `{}`
- final fields: `{'INE_FRENTE': 'received_pending_review'}`

- customer message: Ya mande mi INE
- agent final_message: Recibido, dejo la INE como enviada para revision. Aun no marco papeleria completa hasta validar todos los requisitos.
- citations: `0`
- field updates: `[{'field_key': 'INE_FRENTE', 'value': 'received_pending_review', 'reason': 'Customer says INE was sent.', 'evidence': ['Ya mande mi INE'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `{'target_stage': 'doc_incompleta', 'target_status': None, 'reason': 'Document is pending review.', 'evidence': ['Ya mande mi INE'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `registrar pendiente sin marcar completo` / `pass`

### documento_borroso

- conversation_id: `d0bb6329-cc6d-484b-ba89-799d4b78c8e3`
- initial stage: `doc_incompleta`
- final stage: `doc_incompleta`
- initial fields: `{}`
- final fields: `{}`

- customer message: La foto salio borrosa pero ahi esta
- agent final_message: Si la foto esta borrosa, hay que reenviarla para poder revisarla bien.
- citations: `0`
- field updates: `[]`
- lifecycle movements: `{'target_stage': 'doc_incompleta', 'target_status': None, 'reason': 'Document is not readable.', 'evidence': ['La foto salio borrosa pero ahi esta'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `pedir reenviar sin aceptar como valido` / `pass`

### comprobante_mama_estado_mama

- conversation_id: `882b014c-105a-4c2f-a774-16505f5fd493`
- initial stage: `nuevos`
- final stage: `nuevos`
- initial fields: `{}`
- final fields: `{}`

- customer message: Puedo usar comprobante de mi mama y estado de cuenta de mi mama?
- agent final_message: No tomaria documentos de tu mama como ingreso propio sin revision. Te paso con una persona para revisar alternativas.
- citations: `0`
- field updates: `[]`
- lifecycle movements: `None`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `no usar documentos familiares como ingreso propio` / `pass`

### nomina_excel

- conversation_id: `d07b45be-66e3-47ea-8277-dad9ca277ce3`
- initial stage: `nuevos`
- final stage: `credito`
- initial fields: `{}`
- final fields: `{'income_type': 'Nomina'}`

- customer message: Mi nomina me la mandan en Excel
- agent final_message: Si tu nomina viene en Excel, debe revisarlo una persona para confirmar si sirve como comprobante.
- citations: `1`
- field updates: `[{'field_key': 'income_type', 'value': 'Nomina', 'reason': 'Customer mentioned payroll income.', 'evidence': ['Mi nomina me la mandan en Excel'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Customer is entering credit flow.', 'evidence': ['Mi nomina me la mandan en Excel'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `explicar que debe revisarse` / `pass`

### cliente_enojo_repeticion

- conversation_id: `1eb6f9f4-2efd-47b6-9dd2-54fc9a2910b4`
- initial stage: `credito`
- final stage: `credito`
- initial fields: `{'income_type': 'Nomina'}`
- final fields: `{'income_type': 'Nomina'}`

- customer message: Ya te dije que me pagan por nomina, no me preguntes otra vez
- agent final_message: Perfecto, tomo nomina como tipo de ingreso. Que modelo quieres cotizar?
- citations: `0`
- field updates: `[{'field_key': 'income_type', 'value': 'Nomina', 'reason': 'Customer mentioned payroll income.', 'evidence': ['Ya te dije que me pagan por nomina, no me preguntes otra vez'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Customer is entering credit flow.', 'evidence': ['Ya te dije que me pagan por nomina, no me preguntes otra vez'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `reconocer dato guardado sin repetir pregunta` / `pass`

### buro_miedo

- conversation_id: `3ed79b9d-5aaf-44db-acbc-8a49c45293fe`
- initial stage: `nuevos`
- final stage: `credito`
- initial fields: `{}`
- final fields: `{'buro_status': 'en_buro'}`

- customer message: Estoy en buro, me da miedo que me rechacen
- agent final_message: Si estas en buro se puede revisar, pero no puedo prometer aprobacion. Cuanto debes aproximadamente?
- citations: `1`
- field updates: `[{'field_key': 'buro_status', 'value': 'en_buro', 'reason': 'Customer mentioned buro.', 'evidence': ['Estoy en buro, me da miedo que me rechacen'], 'confidence': 0.9, 'source': 'customer_message', 'evidence_message_id': None, 'evidence_attachment_id': None, 'trace_id': None, 'metadata': {}}]`
- lifecycle movements: `{'target_stage': 'credito', 'target_status': None, 'reason': 'Credit risk question.', 'evidence': ['Estoy en buro, me da miedo que me rechacen'], 'confidence': 0.9, 'source': 'agent', 'trace_id': None, 'metadata': {'simulation': True}}`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `tranquilizar sin prometer aprobacion` / `pass`

### cliente_pide_humano

- conversation_id: `439a93de-6d8a-4c7d-a205-29b41a4a8611`
- initial stage: `nuevos`
- final stage: `nuevos`
- initial fields: `{}`
- final fields: `{}`

- customer message: Quiero hablar con alguien
- agent final_message: Claro, te paso con una persona del equipo para que te atienda directo.
- citations: `0`
- field updates: `[]`
- lifecycle movements: `None`
- actions: `[]`
- policy: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- expected vs actual: `needs_human true` / `pass`

## 5. Pipeline movement summary

- `credito`: `9`
- `doc_incompleta`: `2`

## 6. Field update summary

- `income_type`: `6`
- `ENGANCHE`: `2`
- `CREDITO`: `3`
- `INE_FRENTE`: `1`
- `buro_status`: `1`

## 7. Document handling summary

- document-related failure turns: `0`
- invalid documents were not accepted as complete in provider trace scoring.

## 8. Handoff summary

- needs_human turns: `5`

## 9. Knowledge/citation summary

- `Sim`: `6`

## 10. Response quality

- answered current question: reviewed by fixture scoring
- no invented data: `yes`
- no robotic tone: `yes`
- one question max: `yes`
- no repeated saved data: reviewed by fixture scoring
- no approval promise: reviewed by fixture scoring
- no premature documents: reviewed by fixture scoring
- no invalid stage: reviewed by lifecycle policy

## 11. Failures and recommended fixes

- `pensionado_10`: field income_type expected 'Pensionado' got 'Pensionados', field CREDITO expected 'Pensionado' got 'Pensionados'

Recommended fixes:

- provider gaps: resolve approved provider or approved deterministic local provider.
- lifecycle mapping gaps: verify every expected Dinamo stage transition is allowed in tenant pipeline.
- Contact Memory gaps: make sure expected fields have tenant definitions and AI write policy.
- Knowledge OS gaps: add stronger sources for document edge cases and payment/deposit requests.
- legacy cleanup gaps: keep legacy fallback until provider-backed simulation passes.

## 12. Legacy removal readiness

| Legacy component | Was used? | Can disable? | Can delete? | Notes |
| --- | --- | --- | --- | --- |
| ConversationRunner | no | for simulation yes | no | still fallback for production |
| advisor_brain | no | for simulation yes | no | audit imports before delete |
| sales_advisor_decision_policy | no | for simulation yes | no | tenant v2 still needs fallback plan |
| flow_router | no | for simulation yes | no | not used by this lab |
| turn_resolver | no | for simulation yes | no | not used by this lab |
| response_frame | no | yes | no | visible copy must stay in TurnOutput.final_message |
| response_contract | no | yes | no | not used by this lab |
| composer legacy | no | yes | no | not used by this lab |
| tools with visible copy | no | yes | no | action payload visible copy remains policy-blocked |

# Dinamo Shadow E2E vs Real Replay

- e2e_decision: `DINAMO_SHADOW_READY`
- replay_cases_passed: `20/20`

## Safety Flags

- live_send_enabled: `False`
- actions_enabled: `False`
- workflow_side_effects_enabled: `False`
- traffic_real_activated: `False`
- whatsapp_sent: `False`
- config_live_applied: `False`
- single_contact_smoke_enabled: `False`

## Covered In Both

- tools: `catalog.search, credit_plan.resolve, handoff.create, quote.resolve, requirements.lookup`
- business_events: `human_handoff_requested, intent_identified, lead_started, offer_quoted, requirements_requested, selection_identified`

## Gaps

- El replay real anonimizado trae 56 turnos genericos de informacion sin PII que el E2E no modela.
- No hay adjuntos reales anonimizados; document.check queda validado por E2E deterministico.
- Referencias como 'esa/la otra/moto del anuncio' no son distinguibles tras la anonimizacion segura.
- Solo una conversacion real contiene solicitud explicita de humano.

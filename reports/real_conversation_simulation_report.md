# Real Conversation Simulation Report

## Executive Summary

- decision: `
REAL_SIMULATION_BLOCKED_PROVIDER_FAILED
`
- tenant: `Dinamo Motos NL` / `dinamomotosnl@gmail.com`
- agent: `Francisco de Dinamo NL`
- dataset audit: `
DATASET_AUDIT_PASS
`
- real anonymized replay: `
20
/
20
` pass, critical failures `
0
`
- provider advisor eval: `
36
/
40
`, DoD `
False
`
- provider stability: `
0
/
5
`, DoD `
False
`
- side_effects_total: `0`
- traffic_started: `false`
- tenant_config_applied: `false`
- send_real_messages: `false`
- actions_enabled: `false`
- workflow_events_enabled: `false`

## Provider Failures

| case | title | failures |
| --- | --- | --- |
| adv_15 | Cambio despues de documentos | robotic_template |
| adv_18 | Modelo ambiguo despues de quote | repeated_question_or_exact_response_detected |
| adv_24 | Nombre parcial adventure | repeated_question_or_exact_response_detected |
| adv_28 | Tres preguntas sin pedir datos primero | repeated_question_or_exact_response_detected |

## Top Patterns

| pattern | cases | result |
| --- | --- | --- |
| cotizacion directa | 13 | pass |
| documentos | 12 | pass |
| handoff humano | 1 | pass |
| seguimiento/general | 0 | pass |

## Final Decision

`
REAL_SIMULATION_BLOCKED_PROVIDER_FAILED
`

Canary 5% must not start until provider advisor eval and provider stability return green again under the same gate. No production config was applied.

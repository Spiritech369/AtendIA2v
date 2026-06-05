# Dinamo Shadow Real Replay Transcripts

- cases_total: `20`
- turns_total: `109`
- final_output_authority: `TurnOutput.final_message`

## Safety Flags

- live_send_enabled: `False`
- actions_enabled: `False`
- workflow_side_effects_enabled: `False`
- traffic_real_activated: `False`
- whatsapp_sent: `False`
- config_live_applied: `False`
- single_contact_smoke_enabled: `False`

## real_b16cedc7b627

- turn_count: `5`
- expected_tags: `documents`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | selection_identified | moto_identificada |
| 5 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |

## real_48c72b56c5de

- turn_count: `5`
- expected_tags: `documents`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | lead_started, selection_identified | moto_identificada |
| 2 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |

## real_dfe7b2bb13f0

- turn_count: `5`
- expected_tags: `handoff`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | lead_started, intent_identified | - |
| 2 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | selection_identified | moto_identificada |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente pide hablar con asesor humano | Solicito revision humana en dry-run; no creo accion real ni envio mensaje externo. | handoff.create | human_handoff_needed | - | human_handoff_requested | en_revision_humana |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |

## real_13893adc7d42

- turn_count: `5`
- expected_tags: `quote`
- replay_passed: `True`
- risk_notes: `quote_request_waiting_for_product_reference, none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion | Para cotizar necesito identificar el modelo antes de usar quote.resolve. | - | - | quote_snapshot_id | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente menciona interes en moto modelo anonimo | Ahora que identificaste modelo, resuelvo la cotizacion pendiente con quote.resolve en shadow. | catalog.search, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | selection_identified, offer_quoted | cotizado |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |

## real_16a192a09810

- turn_count: `6`
- expected_tags: `quote, documents`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | selection_identified | moto_identificada |
| 4 | cliente solicita cotizacion | Uso el modelo ya identificado y valido la cotizacion con quote.resolve en shadow. | quote.resolve | quote_snapshot_id | - | offer_quoted | cotizado |
| 5 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 6 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |

## real_cd9f92957c51

- turn_count: `5`
- expected_tags: `documents`
- replay_passed: `True`
- risk_notes: `quote_request_waiting_for_product_reference, none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion | Para cotizar necesito identificar el modelo antes de usar quote.resolve. | - | - | quote_snapshot_id | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 4 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |

## real_1f066b43b997

- turn_count: `5`
- expected_tags: `quote`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | lead_started, intent_identified | - |
| 2 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | selection_identified | moto_identificada |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente solicita cotizacion | Uso el modelo ya identificado y valido la cotizacion con quote.resolve en shadow. | quote.resolve | quote_snapshot_id | - | offer_quoted | cotizado |

## real_e60c9db15927

- turn_count: `5`
- expected_tags: `quote`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | lead_started, selection_identified | moto_identificada |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente solicita cotizacion | Uso el modelo ya identificado y valido la cotizacion con quote.resolve en shadow. | quote.resolve | quote_snapshot_id | - | offer_quoted | cotizado |

## real_1b476683a40d

- turn_count: `5`
- expected_tags: `quote, documents`
- replay_passed: `True`
- risk_notes: `quote_request_waiting_for_product_reference, none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion | Para cotizar necesito identificar el modelo antes de usar quote.resolve. | - | - | quote_snapshot_id | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente menciona interes en moto modelo anonimo | Ahora que identificaste modelo, resuelvo la cotizacion pendiente con quote.resolve en shadow. | catalog.search, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | selection_identified, offer_quoted | cotizado |
| 5 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |

## real_0da316dac672

- turn_count: `5`
- expected_tags: `quote, documents`
- replay_passed: `True`
- risk_notes: `quote_request_waiting_for_product_reference, none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion | Para cotizar necesito identificar el modelo antes de usar quote.resolve. | - | - | quote_snapshot_id | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente menciona interes en moto modelo anonimo | Ahora que identificaste modelo, resuelvo la cotizacion pendiente con quote.resolve en shadow. | catalog.search, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | selection_identified, offer_quoted | cotizado |
| 5 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |

## real_b39964f2f0c4

- turn_count: `9`
- expected_tags: `quote, documents`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion de moto modelo anonimo | Genero cotizacion shadow con quote.resolve y snapshot validado; no envio WhatsApp ni precio live. | catalog.search, credit_plan.resolve, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | lead_started, selection_identified, offer_quoted | cotizado |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 6 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 7 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 8 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 9 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |

## real_7f7bb70f4d9f

- turn_count: `5`
- expected_tags: `quote`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion de moto modelo anonimo | Genero cotizacion shadow con quote.resolve y snapshot validado; no envio WhatsApp ni precio live. | catalog.search, credit_plan.resolve, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | lead_started, selection_identified, offer_quoted | cotizado |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente solicita cotizacion | Uso el modelo ya identificado y valido la cotizacion con quote.resolve en shadow. | quote.resolve | quote_snapshot_id | - | offer_quoted | cotizado |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |

## real_7f62ce6fea72

- turn_count: `5`
- expected_tags: `documents`
- replay_passed: `True`
- risk_notes: `quote_request_waiting_for_product_reference, none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion | Para cotizar necesito identificar el modelo antes de usar quote.resolve. | - | - | quote_snapshot_id | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 4 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |

## real_fb5b32b4a6f2

- turn_count: `5`
- expected_tags: `quote`
- replay_passed: `True`
- risk_notes: `quote_request_waiting_for_product_reference, none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion | Para cotizar necesito identificar el modelo antes de usar quote.resolve. | - | - | quote_snapshot_id | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente menciona interes en moto modelo anonimo | Ahora que identificaste modelo, resuelvo la cotizacion pendiente con quote.resolve en shadow. | catalog.search, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | selection_identified, offer_quoted | cotizado |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |

## real_37a6d29290ae

- turn_count: `5`
- expected_tags: `documents`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | lead_started, selection_identified | moto_identificada |
| 2 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |

## real_c6a3b647dc52

- turn_count: `5`
- expected_tags: `quote, documents`
- replay_passed: `True`
- risk_notes: `quote_request_waiting_for_product_reference, none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion | Para cotizar necesito identificar el modelo antes de usar quote.resolve. | - | - | quote_snapshot_id | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente menciona interes en moto modelo anonimo | Ahora que identificaste modelo, resuelvo la cotizacion pendiente con quote.resolve en shadow. | catalog.search, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | selection_identified, offer_quoted | cotizado |
| 5 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |

## real_71543761982d

- turn_count: `9`
- expected_tags: `quote, documents`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion de moto modelo anonimo | Genero cotizacion shadow con quote.resolve y snapshot validado; no envio WhatsApp ni precio live. | catalog.search, credit_plan.resolve, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | lead_started, selection_identified, offer_quoted | cotizado |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 6 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 7 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 8 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |
| 9 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |

## real_d06730ba4836

- turn_count: `5`
- expected_tags: `quote`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | lead_started, intent_identified | - |
| 2 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | selection_identified | moto_identificada |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente solicita cotizacion | Uso el modelo ya identificado y valido la cotizacion con quote.resolve en shadow. | quote.resolve | quote_snapshot_id | - | offer_quoted | cotizado |

## real_00e6ef475a08

- turn_count: `5`
- expected_tags: `documents`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | lead_started, intent_identified | - |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 4 | cliente menciona interes en moto modelo anonimo | Ubico el modelo anonimo con catalog.search en shadow y no guardo texto crudo. | catalog.search | product_selection, product_catalog_id | - | selection_identified | moto_identificada |
| 5 | cliente pregunta por documentos requeridos | Consulto requirements.lookup y respondo requisitos validados sin mezclar planes. | requirements.lookup | requirements_checklist | - | requirements_requested | papeleria_solicitada |

## real_dc7e52d6ffdd

- turn_count: `5`
- expected_tags: `quote`
- replay_passed: `True`
- risk_notes: `none`

| turn | customer_message | shadow_response | tools | accepted | blocked | events | pipeline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cliente solicita cotizacion de moto modelo anonimo | Genero cotizacion shadow con quote.resolve y snapshot validado; no envio WhatsApp ni precio live. | catalog.search, credit_plan.resolve, quote.resolve | product_selection, product_catalog_id, quote_snapshot_id | - | lead_started, selection_identified, offer_quoted | cotizado |
| 2 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 3 | cliente solicita cotizacion | Uso el modelo ya identificado y valido la cotizacion con quote.resolve en shadow. | quote.resolve | quote_snapshot_id | - | offer_quoted | cotizado |
| 4 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |
| 5 | cliente comparte informacion sin datos personales | Lo tengo en cuenta; para avanzar necesito un dato comercial explicito. | - | - | - | intent_identified | - |


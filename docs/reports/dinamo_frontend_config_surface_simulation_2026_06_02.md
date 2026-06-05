# Dinamo OpenAI Frontend Review Simulation - 2026-06-02

## Executive Summary

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`
- provider/model: `openai` / `gpt-4o-mini`
- simulation_run_id: `6ad1b695-d09e-4b93-a6e0-278af39b8446`
- conversations_created: `12`
- cases_passed: `12`
- cases_failed: `0`
- overall_score: `1.0`
- ready_for_live_preview: `True`
- ready_for_shadow: `conditional`
- ready_for_manual_send: `no`
- real side effects: `0`
- readiness_passed: `False`

## Conversation Index

| # | case_id | title | conversation_id | customer_id | final_stage | pass/fail | frontend_url_or_route | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `credito_happy_path_nomina_tarjeta` | Credito happy path nomina tarjeta | `b39964f2-f0c4-4377-9d42-a81c006ef4d8` | `f0a5c128-b36e-4718-bce1-faa25f864dd1` | `papeleria_completa` | `passed` | `/inbox?conversation_id=b39964f2-f0c4-4377-9d42-a81c006ef4d8&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 2 | `contado_directo` | Contado directo R4 | `7f7bb70f-4d9f-4450-b7ca-50dd5454113c` | `f0623926-cb29-409c-a48c-8a6bb8d07ece` | `cliente_potencial` | `passed` | `/inbox?conversation_id=7f7bb70f-4d9f-4450-b7ca-50dd5454113c&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 3 | `sin_comprobantes` | Sin comprobantes con modelo | `16a192a0-9810-4f6d-910b-ee1e7d0921ff` | `a87c305f-cdbd-432d-8940-2cad86874653` | `papeleria_incompleta` | `passed` | `/inbox?conversation_id=16a192a0-9810-4f6d-910b-ee1e7d0921ff&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 4 | `nomina_recibos` | Nomina recibos efectivo | `b16cedc7-b627-4c4e-9450-4614fd636bb9` | `e6a434a0-fcba-4ad3-9ef4-fe3a35289c58` | `cliente_potencial` | `passed` | `/inbox?conversation_id=b16cedc7-b627-4c4e-9450-4614fd636bb9&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 5 | `guardia` | Guardia de seguridad | `13893adc-7d42-4903-9553-d81b5cac2efb` | `ac78cd73-9a27-47c7-960c-f25164937ddf` | `plan` | `passed` | `/inbox?conversation_id=13893adc-7d42-4903-9553-d81b5cac2efb&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 6 | `documentos_mama` | Documentos de mama | `cd9f9295-7c51-4cdf-8149-e23a006a80c1` | `05c2c6dd-06f5-42a5-95f3-dd81ce4c45a8` | `nuevos` | `passed` | `/inbox?conversation_id=cd9f9295-7c51-4cdf-8149-e23a006a80c1&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 7 | `documento_antes_de_plan` | Documento antes de plan | `48c72b56-c5de-448f-aa32-75bc556afc2c` | `f48fa008-5d14-4fbf-944f-9d00ac2efc02` | `papeleria_incompleta` | `passed` | `/inbox?conversation_id=48c72b56-c5de-448f-aa32-75bc556afc2c&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 8 | `documento_borroso` | Documento borroso | `0da316da-c672-4550-853c-3d022adb025f` | `4309fcf2-39a8-4f55-984d-55ad8d734f08` | `papeleria_incompleta` | `passed` | `/inbox?conversation_id=0da316da-c672-4550-853c-3d022adb025f&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 9 | `galgo_antiguedad_baja` | Galgo antiguedad baja | `1b476683-a40d-4cff-8a70-d80f7eafb203` | `8be017f5-3891-4b19-b3d4-28173dbe0ff2` | `galgo` | `passed` | `/inbox?conversation_id=1b476683-a40d-4cff-8a70-d80f7eafb203&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 10 | `catalogo_y_modelo` | Catalogo y modelo | `1f066b43-b997-476b-94b9-c9a6627b4db0` | `a7352dbd-2df5-4b8f-a901-f08a04228698` | `cliente_potencial` | `passed` | `/inbox?conversation_id=1f066b43-b997-476b-94b9-c9a6627b4db0&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 11 | `cliente_pide_humano` | Cliente pide humano | `dfe7b2bb-13f0-4afa-ac39-038001f11b1e` | `0e06f77d-cf81-41fb-97c8-8c4370cdbac2` | `nuevos` | `passed` | `/inbox?conversation_id=dfe7b2bb-13f0-4afa-ac39-038001f11b1e&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |
| 12 | `moto_barata_para_trabajar` | Moto barata para trabajar | `e60c9db1-5927-4dd4-a39e-a6d21fcfc74b` | `d240e6de-b132-405f-947a-a0abaec42da9` | `plan` | `passed` | `/inbox?conversation_id=e60c9db1-5927-4dd4-a39e-a6d21fcfc74b&simulation_run_id=6ad1b695-d09e-4b93-a6e0-278af39b8446` | ok |

## Screenshot Checklist

- Open Inbox filtered by simulation batch `6ad1b695-d09e-4b93-a6e0-278af39b8446`.
- Capture conversation `credito_happy_path_nomina_tarjeta`.
- Capture contact panel for `credito_happy_path_nomina_tarjeta`.
- Capture conversation `documentos_mama`.
- Capture conversation `contado_directo`.
- Capture conversation `papeleria_completa_handoff` if present in the fixture.
- Capture `Docs_Checklist`.
- Capture `Ultima_Cotizacion`.
- Capture Why-this-answer for one quote.
- Capture Why-this-answer for documents.

## Per-Conversation Transcript

### credito_happy_path_nomina_tarjeta

- conversation_id: `b39964f2-f0c4-4377-9d42-a81c006ef4d8`
- customer_id: `f0a5c128-b36e-4718-bce1-faa25f864dd1`
- final_stage: `papeleria_completa`
- final_fields: `{'Plan_Enganche': '10%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Comando 400 CC', 'Doc_Completos': True, 'Docs_Checklist': [{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}], 'Handoff_Humano': True, 'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta'}`
- pass/fail: `passed`

- customer message: Hola, quiero una moto a credito.
- agent final_message: Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `['Adventure Elite 150 CC', 'Alien R 175 CC', 'B52 250 CC', 'Bandid 350 CC', 'Chopper Bobber 250 CC']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 8 meses trabajando.
- agent final_message: Perfecto, ahora que cumples con la antigüedad, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False, 'Cumple_Antiguedad': True}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me interesa la Comando.
- agent final_message: Dime cómo recibes tus ingresos para poder cotizarte la Comando 400 CC. Puedes mandarme el número o escribir el método: 1. Nómina en tarjeta, 2. Recibos de nómina, 3. Pensionado, 4. Negocio SAT, 5. Sin comprobantes, 6. Guardia de seguridad.
- citations: `['Comando 400 CC']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False, 'Cumple_Antiguedad': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': None, 'plan_enganche': None, 'precio_contado_mxn': 79900, 'quote_sent': False, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Moto': 'Comando 400 CC'}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me depositan nomina en tarjeta.
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Nómina Tarjeta', '¿Cuánto es el enganche mínimo?', '¿Qué requisitos necesito para iniciar mi trámite?']`
- fields after: `{'Plan_Enganche': '10%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Comando 400 CC', 'Doc_Completos': False, 'Handoff_Humano': False, 'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Si tengo recibos de nomina.
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Nómina Recibos', 'Nómina Recibos']`
- fields after: `{'Plan_Enganche': '10%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Comando 400 CC', 'Doc_Completos': False, 'Handoff_Humano': False, 'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Mi comprobante puede estar a otro nombre?
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['reglas_globales_requisitos', 'Guardia de Seguridad', 'Negocio SAT', 'Nómina Recibos', 'Nómina Tarjeta']`
- fields after: `{'Plan_Enganche': '10%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Comando 400 CC', 'Doc_Completos': False, 'Handoff_Humano': False, 'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Que documentos siguen?
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Nómina Tarjeta', 'Nómina Recibos', 'Pensionados']`
- fields after: `{'Plan_Enganche': '10%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Comando 400 CC', 'Doc_Completos': False, 'Handoff_Humano': False, 'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Te mando mi INE.
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Docs_Checklist': [{'evidence': ['ine_ambos_lados.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}, {'evidence': [], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'missing'}, {'evidence': [], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'missing'}], 'Plan_Enganche': '10%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Comando 400 CC', 'Doc_Completos': False, 'Handoff_Humano': False, 'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta'}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine_ambos_lados.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}, {'evidence': [], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'missing'}, {'evidence': [], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'missing'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tambien mando estado de cuenta, nomina y comprobante.
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Nómina Tarjeta', 'Nómina Tarjeta', 'Sin Comprobantes']`
- fields after: `{'Plan_Enganche': '10%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Comando 400 CC', 'Doc_Completos': True, 'Docs_Checklist': [{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}], 'Handoff_Humano': True, 'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta'}`
- stage after: `papeleria_completa`
- docs checklist after: `[{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### contado_directo

- conversation_id: `7f7bb70f-4d9f-4450-b7ca-50dd5454113c`
- customer_id: `f0623926-cb29-409c-a48c-8a6bb8d07ece`
- final_stage: `cliente_potencial`
- final_fields: `{'Moto': 'Adventure Elite 150 CC', 'Doc_Completos': False, 'Handoff_Humano': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Plan_Credito': 'Contado', 'Plan_Enganche': '100%'}`
- pass/fail: `passed`

- customer message: Quiero comprar de contado la R4.
- agent final_message: La R4 250 CC de contado queda en $52,700. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `['R4 250 CC']`
- fields after: `{'Plan_Credito': 'Contado', 'Plan_Enganche': '100%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': None, 'moto': 'R4 250 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'R4 250 CC', 'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: La puedo ver hoy?
- agent final_message: La R4 250 CC de contado queda en $52,700. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `['¿Dónde puedo ver los modelos disponibles?', '¿Qué requisitos necesito para iniciar mi trámite?']`
- fields after: `{'Plan_Credito': 'Contado', 'Plan_Enganche': '100%', 'Moto': 'R4 250 CC', 'Doc_Completos': False, 'Handoff_Humano': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': None, 'moto': 'R4 250 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}, {'action_name': 'trigger_workflow', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Me puedes confirmar el precio de contado?
- agent final_message: La Adventure Elite 150 CC de contado queda en $29,900. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `['Adventure Elite 150 CC', 'Alien R 175 CC', 'B52 250 CC', 'Bandid 350 CC', 'Chopper Bobber 250 CC']`
- fields after: `{'Moto': 'Adventure Elite 150 CC', 'Doc_Completos': False, 'Handoff_Humano': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Plan_Credito': 'Contado', 'Plan_Enganche': '100%'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Va, me interesa.
- agent final_message: La Adventure Elite 150 CC de contado queda en $29,900. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `[]`
- fields after: `{'Moto': 'Adventure Elite 150 CC', 'Doc_Completos': False, 'Handoff_Humano': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Plan_Credito': 'Contado', 'Plan_Enganche': '100%'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Quiero que alguien me confirme disponibilidad.
- agent final_message: La Adventure Elite 150 CC de contado queda en $29,900. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `[]`
- fields after: `{'Moto': 'Adventure Elite 150 CC', 'Doc_Completos': False, 'Handoff_Humano': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Plan_Credito': 'Contado', 'Plan_Enganche': '100%'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}, {'action_name': 'trigger_workflow', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### sin_comprobantes

- conversation_id: `16a192a0-9810-4f6d-910b-ee1e7d0921ff`
- customer_id: `a87c305f-cdbd-432d-8940-2cad86874653`
- final_stage: `papeleria_incompleta`
- final_fields: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'U5 150 CC', 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}`
- pass/fail: `passed`

- customer message: Tengo 1 ano trabajando.
- agent final_message: Perfecto, cumples con la antigüedad. Para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me pagan por fuera.
- agent final_message: Entendido, eso significa que tu plan sería "Sin Comprobantes" con un enganche del 20%. Dime, ¿qué modelo de moto te interesa para cotizarte? Puedes ver el catálogo aquí: https://dinamomotos.com/catalogo.html
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Nómina Tarjeta', 'Nómina Tarjeta', 'Sin Comprobantes']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%'}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Quiero una U5.
- agent final_message: Necesito que una persona del equipo revise esto para responderte con certeza.
- citations: `['U5 150 CC']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'U5 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Cotizamela porfa.
- agent final_message: La U5 150 CC con Sin Comprobantes queda en precio de contado $24,900. Enganche $2,615, pagos de $1,039 por 72 quincenas.
- citations: `[]`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'U5 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Que documentos necesito?
- agent final_message: La U5 150 CC con Sin Comprobantes queda en precio de contado $24,900. Enganche $2,615, pagos de $1,039 por 72 quincenas.
- citations: `['Nómina Recibos', 'Sin Comprobantes']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'U5 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Te mando mi INE.
- agent final_message: La U5 150 CC con Sin Comprobantes queda en precio de contado $24,900. Enganche $2,615, pagos de $1,039 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'U5 150 CC', 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

### nomina_recibos

- conversation_id: `b16cedc7-b627-4c4e-9450-4614fd636bb9`
- customer_id: `e6a434a0-fcba-4ad3-9ef4-fe3a35289c58`
- final_stage: `cliente_potencial`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '15%', 'Plan_Credito': 'Nomina Recibos', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 4485, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Recibos', 'plan_enganche': '15%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- pass/fail: `passed`

- customer message: Tengo 10 meses en mi trabajo.
- agent final_message: Perfecto, ya cumples con la antigüedad. Para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['U2 150 CC', 'U5 150 CC', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Nómina Tarjeta']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me pagan en efectivo pero tengo recibos.
- agent final_message: Te conviene el plan de Nómina Recibos, que es del 15%. Ahora, dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Nómina Recibos']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Nomina Recibos', 'Plan_Enganche': '15%'}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Los recibos son semanales.
- agent final_message: Entiendo, entonces tu plan es de Nómina Recibos con un enganche del 15%. Ahora, dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Nómina Recibos', 'Nómina Recibos', '¿Qué requisitos necesito para iniciar mi trámite?', 'Nómina Tarjeta', 'Nómina Tarjeta']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Nomina Recibos', 'Plan_Enganche': '15%'}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me interesa la Adventure.
- agent final_message: La Adventure Elite 150 CC con Nomina Recibos queda en precio de contado $29,900. Enganche $4,485. Un asesor te confirma disponibilidad y pagos exactos.
- citations: `['Adventure Elite 150 CC']`
- fields after: `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Nomina Recibos', 'Plan_Enganche': '15%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 4485, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Recibos', 'plan_enganche': '15%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Que documentos son?
- agent final_message: La Adventure Elite 150 CC con Nomina Recibos queda en precio de contado $29,900. Enganche $4,485. Un asesor te confirma disponibilidad y pagos exactos.
- citations: `['¿Qué requisitos necesito para iniciar mi trámite?', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '15%', 'Plan_Credito': 'Nomina Recibos', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 4485, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Recibos', 'plan_enganche': '15%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### guardia

- conversation_id: `13893adc-7d42-4903-9553-d81b5cac2efb`
- customer_id: `ac78cd73-9a27-47c7-960c-f25164937ddf`
- final_stage: `plan`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False, 'Moto': 'R4'}`
- pass/fail: `passed`

- customer message: Quiero credito.
- agent final_message: Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `['Adventure Elite 150 CC', 'Alien R 175 CC', 'B52 250 CC', 'Bandid 350 CC', 'Chopper Bobber 250 CC']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 2 anos trabajando.
- agent final_message: Entendido, cumples con la antigüedad. Ahora, para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Soy guardia de seguridad.
- agent final_message: Con tu trabajo como guardia de seguridad, el enganche es del 30%. Ahora, dime qué modelo de moto te interesa para cotizarte según tu plan.
- citations: `['Guardia de Seguridad']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me gusta la R4.
- agent final_message: La R4 no está en el catálogo. ¿Te gustaría que te pase con Francisco para revisarlo bien?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False, 'Moto': 'R4'}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Que sigue?
- agent final_message: La R4 no está en el catálogo. ¿Te gustaría que te pase con Francisco para revisarlo bien?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False, 'Moto': 'R4'}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

### documentos_mama

- conversation_id: `cd9f9295-7c51-4cdf-8149-e23a006a80c1`
- customer_id: `05c2c6dd-06f5-42a5-95f3-dd81ce4c45a8`
- final_stage: `nuevos`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- pass/fail: `passed`

- customer message: Hola, quiero credito.
- agent final_message: Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `['Adventure Elite 150 CC', 'Alien R 175 CC', 'B52 250 CC', 'Bandid 350 CC', 'Chopper Bobber 250 CC']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 8 meses.
- agent final_message: Perfecto, ahora que cumples con la antigüedad, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Puedo mandar documentos de mi mama?
- agent final_message: El comprobante de domicilio sí puede estar a nombre de tu mamá si es donde vives actualmente y está reciente/legible. Estados de cuenta o nómina sí tienen que ser tuyos; si no tienes comprobantes, podemos revisarlo como Sin Comprobantes con 20%.
- citations: `['Guardia de Seguridad', 'Negocio SAT', 'Nómina Recibos', 'Nómina Tarjeta', 'Pensionados']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Seria su comprobante de domicilio.
- agent final_message: El comprobante de domicilio puede estar a nombre de tu mamá si es donde vives y está reciente. ¿Te gustaría que revisemos el plan como Sin Comprobantes con 20% de enganche?
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Y mis estados de cuenta no los tengo.
- agent final_message: Entiendo, si no tienes estados de cuenta, podemos revisar el plan como Sin Comprobantes con un enganche del 20%. ¿Te gustaría proceder con eso?
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Nómina Tarjeta', 'Nómina Tarjeta', 'Pensionados']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

### documento_antes_de_plan

- conversation_id: `48c72b56-c5de-448f-aa32-75bc556afc2c`
- customer_id: `f48fa008-5d14-4fbf-944f-9d00ac2efc02`
- final_stage: `papeleria_incompleta`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- pass/fail: `passed`

- customer message: Hola, quiero una moto.
- agent final_message: Hola, ¿qué tipo de moto te interesa? Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Te mando mi INE.
- agent final_message: Recibí tu INE. Para continuar, necesito saber cuánto tiempo llevas en tu empleo actual. ¿Cuánto es?
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Que sigue?
- agent final_message: Para continuar, necesito saber cuánto tiempo llevas en tu empleo actual. ¿Cuánto es?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 8 meses trabajando.
- agent final_message: Perfecto, cumples con la antigüedad. Ahora, para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me depositan en tarjeta.
- agent final_message: Con tu método de ingresos, te corresponde el plan de Nómina Tarjeta con un enganche del 10%. Dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Nómina Tarjeta']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### documento_borroso

- conversation_id: `0da316da-c672-4550-853c-3d022adb025f`
- customer_id: `4309fcf2-39a8-4f55-984d-55ad8d734f08`
- final_stage: `papeleria_incompleta`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': 5534, 'moto': 'R4 250 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 2198, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'R4 250 CC', 'Docs_Checklist': [{'evidence': ['ine_borrosa.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}`
- pass/fail: `passed`

- customer message: Quiero credito.
- agent final_message: Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `['Adventure Elite 150 CC', 'Alien R 175 CC', 'B52 250 CC', 'Bandid 350 CC', 'Chopper Bobber 250 CC']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 8 meses.
- agent final_message: Perfecto, ahora que cumples con la antigüedad, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me pagan por fuera.
- agent final_message: Entendido, eso significa que tu plan será "Sin Comprobantes" con un enganche del 20%. Ahora, dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Sin Comprobantes']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Quiero la R4.
- agent final_message: La R4 250 CC con Sin Comprobantes queda en precio de contado $52,700. Enganche $5,534, pagos de $2,198 por 72 quincenas.
- citations: `['R4 250 CC']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': 5534, 'moto': 'R4 250 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 2198, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'R4 250 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Te mando la INE borrosa.
- agent final_message: La R4 250 CC con Sin Comprobantes queda en precio de contado $52,700. Enganche $5,534, pagos de $2,198 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': 5534, 'moto': 'R4 250 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 2198, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'R4 250 CC', 'Docs_Checklist': [{'evidence': ['ine_borrosa.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine_borrosa.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

### galgo_antiguedad_baja

- conversation_id: `1b476683-a40d-4cff-8a70-d80f7eafb203`
- customer_id: `8be017f5-3891-4b19-b3d4-28173dbe0ff2`
- final_stage: `galgo`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': False, 'Handoff_Humano': False, 'Moto': 'R4'}`
- pass/fail: `passed`

- customer message: Quiero credito.
- agent final_message: Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `['Adventure Elite 150 CC', 'Alien R 175 CC', 'B52 250 CC', 'Bandid 350 CC', 'Chopper Bobber 250 CC']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 2 meses trabajando.
- agent final_message: Entendido, por el momento los planes para trabajadores menores a 6 meses están deshabilitados. Escríbeme cuando cumplas los 6 meses y ese mismo día te armo tu plan.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': False, 'Handoff_Humano': False}`
- stage after: `galgo`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Entonces si puedo?
- agent final_message: Entendido, por el momento los planes para trabajadores menores a 6 meses están deshabilitados. Escríbeme cuando cumplas los 6 meses y ese mismo día te armo tu plan.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': False, 'Handoff_Humano': False}`
- stage after: `galgo`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me interesa la R4.
- agent final_message: Entendido, por el momento los planes para trabajadores menores a 6 meses están deshabilitados. Escríbeme cuando cumplas los 6 meses y ese mismo día te armo tu plan.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': False, 'Handoff_Humano': False, 'Moto': 'R4'}`
- stage after: `galgo`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Que documentos piden?
- agent final_message: Necesito que una persona del equipo revise esto para responderte con certeza.
- citations: `['Guardia de Seguridad', 'Negocio SAT', 'Nómina Recibos', 'Nómina Tarjeta', 'Pensionados']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': False, 'Handoff_Humano': False, 'Moto': 'R4'}`
- stage after: `galgo`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

### catalogo_y_modelo

- conversation_id: `1f066b43-b997-476b-94b9-c9a6627b4db0`
- customer_id: `a7352dbd-2df5-4b8f-a901-f08a04228698`
- final_stage: `cliente_potencial`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 2990, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- pass/fail: `passed`

- customer message: Me pasas catalogo?
- agent final_message: Claro, aquí tienes el catálogo: https://wa.me/c/5218186016492 ¿Ya tienes algún modelo en mente?
- citations: `['¿Dónde puedo ver los modelos disponibles?']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me interesa la Adventure.
- agent final_message: La moto que mencionas es la Adventure Elite 150 CC. Para cotizarte, necesito saber cuánto tiempo llevas en tu empleo actual.
- citations: `['Adventure Elite 150 CC']`
- fields after: `{'Doc_Completos': False, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': None, 'plan_enganche': None, 'precio_contado_mxn': 29900, 'quote_sent': False, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 8 meses trabajando.
- agent final_message: Entendido, cumples con la antigüedad. Para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': None, 'plan_enganche': None, 'precio_contado_mxn': 29900, 'quote_sent': False, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me depositan en tarjeta.
- agent final_message: La Adventure Elite 150 CC con Nomina Tarjeta queda en precio de contado $29,900. Enganche $2,990. Un asesor te confirma disponibilidad y pagos exactos.
- citations: `['Nómina Tarjeta']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 2990, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Cotizamela.
- agent final_message: La Adventure Elite 150 CC con Nomina Tarjeta queda en precio de contado $29,900. Enganche $2,990. Un asesor te confirma disponibilidad y pagos exactos.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 2990, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

### cliente_pide_humano

- conversation_id: `dfe7b2bb-13f0-4afa-ac39-038001f11b1e`
- customer_id: `0e06f77d-cf81-41fb-97c8-8c4370cdbac2`
- final_stage: `nuevos`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': True}`
- pass/fail: `passed`

- customer message: Hola.
- agent final_message: Hola, ¿en qué puedo ayudarte hoy?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Quiero una moto.
- agent final_message: Para ayudarte mejor, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 8 meses.
- agent final_message: Perfecto, ahora que cumples con la antigüedad, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Quiero hablar con alguien real.
- agent final_message: Entiendo que quieras hablar con alguien real. Te voy a pasar con Francisco para que te ayude mejor.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': True}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}, {'action_name': 'trigger_workflow', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me urge que me llamen.
- agent final_message: Entiendo que quieras hablar con alguien real. Te voy a pasar con Francisco para que te ayude mejor.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': True}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}, {'action_name': 'trigger_workflow', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### moto_barata_para_trabajar

- conversation_id: `e60c9db1-5927-4dd4-a39e-a6d21fcfc74b`
- customer_id: `d240e6de-b132-405f-947a-a0abaec42da9`
- final_stage: `plan`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- pass/fail: `passed`

- customer message: Hola, quiero una moto barata para trabajar.
- agent final_message: Para ayudarte mejor, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Tengo 1 ano trabajando.
- agent final_message: Perfecto, cumples con la antigüedad. Ahora, para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me pagan por fuera.
- agent final_message: Entendido, con el método de ingresos "Sin Comprobantes" tu enganche es del 20%. Dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Sin Comprobantes']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Cual me recomiendas?
- agent final_message: No tengo un modelo específico en mente, pero puedo ayudarte a elegir. ¿Te gustaría que te muestre algunas opciones del catálogo?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Cotiza una opcion barata.
- agent final_message: Para cotizarte una opción barata, necesito que me digas el modelo de la moto que te interesa. Puedes revisar el catálogo aquí: https://dinamomotos.com/catalogo.html
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

## Quote Summary

| case_id | Moto | Plan_Credito | Plan_Enganche | Ultima_Cotizacion | Cotizacion_Enviada | placeholder leak | quote source/citation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `credito_happy_path_nomina_tarjeta` | `Comando 400 CC` | `Nomina Tarjeta` | `10%` | `{'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}` | `True` | `False` | `Knowledge OS / TurnTrace citations` |
| `contado_directo` | `Adventure Elite 150 CC` | `Contado` | `100%` | `{'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}` | `True` | `False` | `Knowledge OS / TurnTrace citations` |
| `sin_comprobantes` | `U5 150 CC` | `Sin Comprobantes` | `20%` | `{'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}` | `True` | `False` | `Knowledge OS / TurnTrace citations` |
| `nomina_recibos` | `Adventure Elite 150 CC` | `Nomina Recibos` | `15%` | `{'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 4485, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Recibos', 'plan_enganche': '15%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}` | `True` | `False` | `Knowledge OS / TurnTrace citations` |
| `guardia` | `R4` | `Guardia` | `30%` | `None` | `None` | `False` | `Knowledge OS / TurnTrace citations` |
| `documentos_mama` | `None` | `None` | `None` | `None` | `None` | `False` | `Knowledge OS / TurnTrace citations` |
| `documento_antes_de_plan` | `None` | `Nomina Tarjeta` | `10%` | `None` | `None` | `False` | `Knowledge OS / TurnTrace citations` |
| `documento_borroso` | `R4 250 CC` | `Sin Comprobantes` | `20%` | `{'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': 5534, 'moto': 'R4 250 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 2198, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}` | `True` | `False` | `Knowledge OS / TurnTrace citations` |
| `galgo_antiguedad_baja` | `R4` | `None` | `None` | `None` | `None` | `False` | `Knowledge OS / TurnTrace citations` |
| `catalogo_y_modelo` | `Adventure Elite 150 CC` | `Nomina Tarjeta` | `10%` | `{'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 2990, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}` | `True` | `False` | `Knowledge OS / TurnTrace citations` |
| `cliente_pide_humano` | `None` | `None` | `None` | `None` | `None` | `False` | `Knowledge OS / TurnTrace citations` |
| `moto_barata_para_trabajar` | `None` | `Sin Comprobantes` | `20%` | `None` | `None` | `False` | `Knowledge OS / TurnTrace citations` |

## Document Summary

| case_id | Plan_Credito | required docs | received/accepted/missing | Doc_Incompletos | Doc_Completos |
| --- | --- | --- | --- | --- | --- |
| `credito_happy_path_nomina_tarjeta` | `Nomina Tarjeta` | `None` | `[{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}]` | `None` | `True` |
| `contado_directo` | `Contado` | `None` | `None` | `None` | `False` |
| `sin_comprobantes` | `Sin Comprobantes` | `None` | `[{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]` | `None` | `False` |
| `nomina_recibos` | `Nomina Recibos` | `None` | `None` | `None` | `False` |
| `guardia` | `Guardia` | `None` | `None` | `None` | `False` |
| `documentos_mama` | `None` | `None` | `None` | `None` | `False` |
| `documento_antes_de_plan` | `Nomina Tarjeta` | `None` | `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]` | `None` | `False` |
| `documento_borroso` | `Sin Comprobantes` | `None` | `[{'evidence': ['ine_borrosa.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]` | `None` | `False` |
| `galgo_antiguedad_baja` | `None` | `None` | `None` | `None` | `False` |
| `catalogo_y_modelo` | `Nomina Tarjeta` | `None` | `None` | `None` | `False` |
| `cliente_pide_humano` | `None` | `None` | `None` | `None` | `False` |
| `moto_barata_para_trabajar` | `Sin Comprobantes` | `None` | `None` | `None` | `False` |

## Pipeline Summary

| case_id | expected stage path | actual final stage | mismatches |
| --- | --- | --- | --- |
| `credito_happy_path_nomina_tarjeta` | `None` | `papeleria_completa` | `[]` |
| `contado_directo` | `cliente_potencial` | `cliente_potencial` | `[]` |
| `sin_comprobantes` | `None` | `papeleria_incompleta` | `[]` |
| `nomina_recibos` | `cliente_potencial` | `cliente_potencial` | `[]` |
| `guardia` | `plan` | `plan` | `[]` |
| `documentos_mama` | `papeleria_incompleta` | `nuevos` | `[]` |
| `documento_antes_de_plan` | `papeleria_completa` | `papeleria_incompleta` | `[]` |
| `documento_borroso` | `papeleria_incompleta` | `papeleria_incompleta` | `[]` |
| `galgo_antiguedad_baja` | `galgo` | `galgo` | `[]` |
| `catalogo_y_modelo` | `cliente_potencial` | `cliente_potencial` | `[]` |
| `cliente_pide_humano` | `None` | `nuevos` | `[]` |
| `moto_barata_para_trabajar` | `None` | `plan` | `[]` |

## Field Summary

| case_id | expected fields | actual fields | mismatches |
| --- | --- | --- | --- |
| `credito_happy_path_nomina_tarjeta` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta', 'Plan_Enganche': '10%', 'Cotizacion_Enviada': True, 'Doc_Completos': True, 'Handoff_Humano': True, 'stage_path': ['cliente_potencial', 'papeleria_incompleta', 'papeleria_completa']}` | `{'Plan_Enganche': '10%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'Comando 400 CC', 'Doc_Completos': True, 'Docs_Checklist': [{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}], 'Handoff_Humano': True, 'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta'}` | `[]` |
| `contado_directo` | `{'Plan_Credito': 'Contado', 'Plan_Enganche': '100%', 'Cotizacion_Enviada': True, 'stage': 'cliente_potencial', 'no_credit_docs': True}` | `{'Moto': 'Adventure Elite 150 CC', 'Doc_Completos': False, 'Handoff_Humano': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Plan_Credito': 'Contado', 'Plan_Enganche': '100%'}` | `[]` |
| `sin_comprobantes` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'Cotizacion_Enviada': True, 'stage_path': ['plan', 'cliente_potencial', 'papeleria_incompleta']}` | `{'Cumple_Antiguedad': True, 'Doc_Completos': False, 'Handoff_Humano': False, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Cotizacion_Enviada': True, 'Moto': 'U5 150 CC', 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}` | `[]` |
| `nomina_recibos` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Recibos', 'Plan_Enganche': '15%', 'stage': 'cliente_potencial'}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '15%', 'Plan_Credito': 'Nomina Recibos', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 4485, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Recibos', 'plan_enganche': '15%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}` | `[]` |
| `guardia` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Guardia', 'Plan_Enganche': '30%', 'stage': 'plan'}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False, 'Moto': 'R4'}` | `[]` |
| `documentos_mama` | `{'no_stage': 'papeleria_incompleta', 'Handoff_Humano': False}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}` | `[]` |
| `documento_antes_de_plan` | `{'Doc_Completos': False, 'no_stage': 'papeleria_completa', 'Plan_Credito': 'Nomina Tarjeta', 'Plan_Enganche': '10%'}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}` | `[]` |
| `documento_borroso` | `{'Doc_Completos': False, 'stage': 'papeleria_incompleta'}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': 5534, 'moto': 'R4 250 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 2198, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'R4 250 CC', 'Docs_Checklist': [{'evidence': ['ine_borrosa.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}` | `[]` |
| `galgo_antiguedad_baja` | `{'Cumple_Antiguedad': False, 'stage': 'galgo'}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': False, 'Handoff_Humano': False, 'Moto': 'R4'}` | `[]` |
| `catalogo_y_modelo` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta', 'Plan_Enganche': '10%', 'Cotizacion_Enviada': True, 'stage': 'cliente_potencial'}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 2990, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}` | `[]` |
| `cliente_pide_humano` | `{'Handoff_Humano': True, 'no_stage_handoff': True}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': True}` | `[]` |
| `moto_barata_para_trabajar` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'asks_recommendation': True}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}` | `[]` |

## Safety Confirmation

- WhatsApp sends: `0`
- outbound_outbox: `0`
- real customer writes: `0`
- real lifecycle moves: `0`
- real actions: `0`
- workflow executions: `0`

## Decision

- ready_for_live_preview: `yes`
- ready_for_shadow: `conditional`
- ready_for_manual_send: `no`

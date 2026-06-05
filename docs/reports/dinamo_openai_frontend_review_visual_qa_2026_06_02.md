# Dinamo OpenAI Frontend Review Simulation - 2026-06-02

## Executive Summary

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`
- provider/model: `openai` / `gpt-4o-mini`
- simulation_run_id: `1df02c78-2818-4fb7-b39f-b6b33c21e48b`
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
| 1 | `credito_happy_path_nomina_tarjeta` | Credito happy path nomina tarjeta | `71543761-982d-491b-9bec-f92400c97c99` | `e5b2b5b2-3faf-46c9-b4ec-5f82ad89ce8e` | `papeleria_completa` | `passed` | `/inbox?conversation_id=71543761-982d-491b-9bec-f92400c97c99&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 2 | `contado_directo` | Contado directo R4 | `dc7e52d6-ffdd-4b0e-bdb5-5d75b6b89466` | `4ac01bd1-15a7-4caa-bb06-f33572c3a813` | `cliente_potencial` | `passed` | `/inbox?conversation_id=dc7e52d6-ffdd-4b0e-bdb5-5d75b6b89466&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 3 | `sin_comprobantes` | Sin comprobantes con modelo | `8790a799-3aaa-4cde-8ad7-6d48fbd24ae1` | `ec1a1ad4-c70f-4cbd-b393-f2643345f472` | `papeleria_incompleta` | `passed` | `/inbox?conversation_id=8790a799-3aaa-4cde-8ad7-6d48fbd24ae1&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 4 | `nomina_recibos` | Nomina recibos efectivo | `00e6ef47-5a08-4f1e-a174-348e6ff52050` | `cab238e7-b44e-4b9a-990c-006bf43328a9` | `cliente_potencial` | `passed` | `/inbox?conversation_id=00e6ef47-5a08-4f1e-a174-348e6ff52050&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 5 | `guardia` | Guardia de seguridad | `fb5b32b4-a6f2-4876-9ea3-26d8ee7e58f2` | `1890ed73-f914-4f0b-b37f-bd4dc1a4f338` | `plan` | `passed` | `/inbox?conversation_id=fb5b32b4-a6f2-4876-9ea3-26d8ee7e58f2&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 6 | `documentos_mama` | Documentos de mama | `7f62ce6f-ea72-4368-a1c1-e12e12ac05d9` | `4f82bbec-158a-4ba3-8b5f-418812a930a4` | `nuevos` | `passed` | `/inbox?conversation_id=7f62ce6f-ea72-4368-a1c1-e12e12ac05d9&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 7 | `documento_antes_de_plan` | Documento antes de plan | `37a6d292-90ae-4647-9490-2c1b559b028e` | `24d4fbaf-761b-401f-b4f6-8d1dc7746078` | `papeleria_incompleta` | `passed` | `/inbox?conversation_id=37a6d292-90ae-4647-9490-2c1b559b028e&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 8 | `documento_borroso` | Documento borroso | `d725201c-6910-4581-ae30-11760f400fbc` | `224cb744-f199-4e15-b549-6b629c38b993` | `papeleria_incompleta` | `passed` | `/inbox?conversation_id=d725201c-6910-4581-ae30-11760f400fbc&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 9 | `galgo_antiguedad_baja` | Galgo antiguedad baja | `c6a3b647-dc52-4f3e-8642-3912ab88b462` | `e7383ab9-f7a1-4043-be58-54e125f12869` | `galgo` | `passed` | `/inbox?conversation_id=c6a3b647-dc52-4f3e-8642-3912ab88b462&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 10 | `catalogo_y_modelo` | Catalogo y modelo | `d06730ba-4836-46bd-b552-ff293fc5a31e` | `f7f32171-120e-4588-8d43-1f82a11f3b5e` | `cliente_potencial` | `passed` | `/inbox?conversation_id=d06730ba-4836-46bd-b552-ff293fc5a31e&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 11 | `cliente_pide_humano` | Cliente pide humano | `ad0307bd-9863-455d-8e49-773c95372f0a` | `7a7118b7-a852-4118-9393-f7cd09d9f393` | `nuevos` | `passed` | `/inbox?conversation_id=ad0307bd-9863-455d-8e49-773c95372f0a&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |
| 12 | `moto_barata_para_trabajar` | Moto barata para trabajar | `c0e86f5d-d07f-48f7-ae7f-334b1db00083` | `0f4920f7-66fe-4b4b-80c0-9ebb9ac8b3f8` | `plan` | `passed` | `/inbox?conversation_id=c0e86f5d-d07f-48f7-ae7f-334b1db00083&simulation_run_id=1df02c78-2818-4fb7-b39f-b6b33c21e48b` | ok |

## Screenshot Checklist

- Open Inbox filtered by simulation batch `1df02c78-2818-4fb7-b39f-b6b33c21e48b`.
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

- conversation_id: `71543761-982d-491b-9bec-f92400c97c99`
- customer_id: `e5b2b5b2-3faf-46c9-b4ec-5f82ad89ce8e`
- final_stage: `papeleria_completa`
- final_fields: `{'Doc_Completos': True, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'Comando 400 CC', 'Docs_Checklist': [{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}]}`
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
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me interesa la Comando.
- agent final_message: La Comando 400 CC está disponible. Para cotizarte, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Comando 400 CC']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': None, 'plan_enganche': None, 'precio_contado_mxn': 79900, 'quote_sent': False, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Comando 400 CC'}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me depositan nomina en tarjeta.
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Nómina Tarjeta', '¿Cuánto es el enganche mínimo?', '¿Qué requisitos necesito para iniciar mi trámite?']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Comando 400 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Si tengo recibos de nomina.
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Nómina Recibos', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Comando 400 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Mi comprobante puede estar a otro nombre?
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['reglas_globales_requisitos', 'Guardia de Seguridad', 'Negocio SAT', 'Nómina Recibos', 'Nómina Tarjeta']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Comando 400 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Que documentos siguen?
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Negocio SAT', 'Nómina Recibos', 'Nómina Tarjeta', 'Pensionados']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Comando 400 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Te mando mi INE.
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Comando 400 CC', 'Docs_Checklist': [{'evidence': ['ine_ambos_lados.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}, {'evidence': [], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'missing'}, {'evidence': [], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'missing'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine_ambos_lados.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}, {'evidence': [], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'missing'}, {'evidence': [], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'missing'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tambien mando estado de cuenta, nomina y comprobante.
- agent final_message: La Comando 400 CC con Nomina Tarjeta queda en precio de contado $79,900. Enganche $8,390, pagos de $3,333 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Nómina Tarjeta', 'Nómina Tarjeta', 'Sin Comprobantes']`
- fields after: `{'Doc_Completos': True, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'Comando 400 CC', 'Docs_Checklist': [{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}]}`
- stage after: `papeleria_completa`
- docs checklist after: `[{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### contado_directo

- conversation_id: `dc7e52d6-ffdd-4b0e-bdb5-5d75b6b89466`
- customer_id: `4ac01bd1-15a7-4caa-bb06-f33572c3a813`
- final_stage: `cliente_potencial`
- final_fields: `{'Doc_Completos': False, 'Cotizacion_Enviada': True, 'Plan_Enganche': '100%', 'Plan_Credito': 'Contado', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'Adventure Elite 150 CC'}`
- pass/fail: `passed`

- customer message: Quiero comprar de contado la R4.
- agent final_message: La R4 250 CC de contado queda en $52,700. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `['R4 250 CC']`
- fields after: `{'Doc_Completos': False, 'Cotizacion_Enviada': True, 'Plan_Enganche': '100%', 'Plan_Credito': 'Contado', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': None, 'moto': 'R4 250 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'R4 250 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: La puedo ver hoy?
- agent final_message: La R4 250 CC de contado queda en $52,700. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `['¿Dónde puedo ver los modelos disponibles?', '¿Qué requisitos necesito para iniciar mi trámite?']`
- fields after: `{'Doc_Completos': False, 'Cotizacion_Enviada': True, 'Plan_Enganche': '100%', 'Plan_Credito': 'Contado', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': None, 'moto': 'R4 250 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'R4 250 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}, {'action_name': 'trigger_workflow', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Me puedes confirmar el precio de contado?
- agent final_message: La Adventure Elite 150 CC de contado queda en $29,900. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `['R4 250 CC']`
- fields after: `{'Doc_Completos': False, 'Cotizacion_Enviada': True, 'Plan_Enganche': '100%', 'Plan_Credito': 'Contado', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Va, me interesa.
- agent final_message: La Adventure Elite 150 CC de contado queda en $29,900. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cotizacion_Enviada': True, 'Plan_Enganche': '100%', 'Plan_Credito': 'Contado', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}, {'action_name': 'move_lifecycle', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Quiero que alguien me confirme disponibilidad.
- agent final_message: La Adventure Elite 150 CC de contado queda en $29,900. Si quieres, te paso con un asesor para confirmar disponibilidad y forma de pago.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cotizacion_Enviada': True, 'Plan_Enganche': '100%', 'Plan_Credito': 'Contado', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}, {'action_name': 'trigger_workflow', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### sin_comprobantes

- conversation_id: `8790a799-3aaa-4cde-8ad7-6d48fbd24ae1`
- customer_id: `ec1a1ad4-c70f-4cbd-b393-f2643345f472`
- final_stage: `papeleria_incompleta`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'U5 150 CC', 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}`
- pass/fail: `passed`

- customer message: Tengo 1 ano trabajando.
- agent final_message: Perfecto, cumples con la antigüedad. Para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me pagan por fuera.
- agent final_message: Con eso, te corresponde el plan Sin Comprobantes con un enganche del 20%. Dime, ¿qué modelo de moto te interesa para cotizar? Puedes ver el catálogo aquí: https://dinamomotos.com/catalogo.html
- citations: `['Sin Comprobantes']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Quiero una U5.
- agent final_message: Necesito que una persona del equipo revise esto para responderte con certeza.
- citations: `['U5 150 CC']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'U5 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Cotizamela porfa.
- agent final_message: La U5 150 CC con Sin Comprobantes queda en precio de contado $24,900. Enganche $2,615, pagos de $1,039 por 72 quincenas.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'U5 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Que documentos necesito?
- agent final_message: La U5 150 CC con Sin Comprobantes queda en precio de contado $24,900. Enganche $2,615, pagos de $1,039 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Negocio SAT', 'Nómina Recibos', 'Nómina Tarjeta', 'Pensionados']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'U5 150 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Te mando mi INE.
- agent final_message: La U5 150 CC con Sin Comprobantes queda en precio de contado $24,900. Enganche $2,615, pagos de $1,039 por 72 quincenas.
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'U5 150 CC', 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

### nomina_recibos

- conversation_id: `00e6ef47-5a08-4f1e-a174-348e6ff52050`
- customer_id: `cab238e7-b44e-4b9a-990c-006bf43328a9`
- final_stage: `cliente_potencial`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '15%', 'Plan_Credito': 'Nomina Recibos', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 4485, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Recibos', 'plan_enganche': '15%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- pass/fail: `passed`

- customer message: Tengo 10 meses en mi trabajo.
- agent final_message: Perfecto, ya cumples con la antigüedad. Para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['U2 150 CC', 'U5 150 CC', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Nómina Tarjeta']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me pagan en efectivo pero tengo recibos.
- agent final_message: Con lo que me dices, puedes optar por el plan de "Nómina Recibos" con un enganche del 15%. ¿Te gustaría que te cotice un modelo específico de moto?
- citations: `['Nómina Recibos', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '15%', 'Plan_Credito': 'Nomina Recibos', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Los recibos son semanales.
- agent final_message: Necesito que una persona del equipo revise esto para responderte con certeza.
- citations: `['Nómina Recibos', 'Nómina Recibos', '¿Qué requisitos necesito para iniciar mi trámite?', 'Nómina Tarjeta', 'Nómina Tarjeta']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '15%', 'Plan_Credito': 'Nomina Recibos', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Me interesa la Adventure.
- agent final_message: La Adventure Elite 150 CC con Nomina Recibos queda en precio de contado $29,900. Enganche $4,485. Un asesor te confirma disponibilidad y pagos exactos.
- citations: `['Adventure Elite 150 CC']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '15%', 'Plan_Credito': 'Nomina Recibos', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 4485, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Recibos', 'plan_enganche': '15%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
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

- conversation_id: `fb5b32b4-a6f2-4876-9ea3-26d8ee7e58f2`
- customer_id: `1890ed73-f914-4f0b-b37f-bd4dc1a4f338`
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
- agent final_message: Perfecto, como guardia de seguridad, tu plan es del 30% de enganche. Dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me gusta la R4.
- agent final_message: No tengo la R4 confirmada en catálogo. Escríbeme el modelo exacto o te paso con Francisco para revisarlo bien.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False, 'Moto': 'R4'}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Que sigue?
- agent final_message: No tengo la R4 confirmada en catálogo. Escríbeme el modelo exacto o te paso con Francisco para revisarlo bien.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False, 'Moto': 'R4'}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

### documentos_mama

- conversation_id: `7f62ce6f-ea72-4368-a1c1-e12e12ac05d9`
- customer_id: `4f82bbec-158a-4ba3-8b5f-418812a930a4`
- final_stage: `nuevos`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Doc_Incompletos': 'Comprobante de domicilio', 'Handoff_Humano': False}`
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
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Seria su comprobante de domicilio.
- agent final_message: Entendido, el comprobante de domicilio puede estar a nombre de tu mamá si es donde vives y está reciente. Ahora, ¿cómo recibes tus ingresos?
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Doc_Incompletos': 'Comprobante de domicilio', 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
- pass/fail: `pass`

- customer message: Y mis estados de cuenta no los tengo.
- agent final_message: Entiendo, si no tienes estados de cuenta, podemos proceder como Sin Comprobantes, lo que implica un enganche del 20%. ¿Cómo recibes tus ingresos: en tarjeta, recibos, o de otra manera?
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Nómina Tarjeta', 'Nómina Tarjeta', 'Pensionados']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Doc_Incompletos': 'Comprobante de domicilio', 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

### documento_antes_de_plan

- conversation_id: `37a6d292-90ae-4647-9490-2c1b559b028e`
- customer_id: `24d4fbaf-761b-401f-b4f6-8d1dc7746078`
- final_stage: `papeleria_incompleta`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- pass/fail: `passed`

- customer message: Hola, quiero una moto.
- agent final_message: Hola, ¿qué modelo de moto tienes en mente? Si no estás seguro, puedo ayudarte a elegir uno del catálogo.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Te mando mi INE.
- agent final_message: He recibido tu INE. Para avanzar, necesito que me digas el modelo de la moto que quieres cotizar. Puedes revisar el catálogo aquí: https://dinamomotos.com/catalogo.html
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Que sigue?
- agent final_message: Para avanzar, necesito que me digas el modelo de la moto que quieres cotizar. Puedes revisar el catálogo aquí: https://dinamomotos.com/catalogo.html
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 8 meses trabajando.
- agent final_message: Perfecto, ya que cumples con la antigüedad, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me depositan en tarjeta.
- agent final_message: Perfecto, con tu plan de Nómina Tarjeta, el enganche es del 10%. Dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Nómina Tarjeta']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Handoff_Humano': False, 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]}`
- stage after: `papeleria_incompleta`
- docs checklist after: `[{'evidence': ['ine.jpg'], 'key': 'unclassified', 'label': 'Documento sin plan', 'status': 'received'}]`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### documento_borroso

- conversation_id: `d725201c-6910-4581-ae30-11760f400fbc`
- customer_id: `224cb744-f199-4e15-b549-6b629c38b993`
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
- agent final_message: Perfecto, ya que cumples con la antigüedad, para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
- citations: `['Nómina Recibos', 'Nómina Recibos', 'Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me pagan por fuera.
- agent final_message: Entendido, como te pagan por fuera, tu plan sería "Sin Comprobantes" con un enganche del 20%. Dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Sin Comprobantes']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
- pass/fail: `pass`

- customer message: Quiero la R4.
- agent final_message: Necesito que una persona del equipo revise esto para responderte con certeza.
- citations: `['R4 250 CC']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'R4 250 CC'}, 'enganche_mxn': 5534, 'moto': 'R4 250 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 2198, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 52700, 'quote_sent': True, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'R4 250 CC'}`
- stage after: `cliente_potencial`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.0`
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

- conversation_id: `c6a3b647-dc52-4f3e-8642-3912ab88b462`
- customer_id: `e7383ab9-f7a1-4043-be58-54e125f12869`
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

- conversation_id: `d06730ba-4836-46bd-b552-ff293fc5a31e`
- customer_id: `f7f32171-120e-4588-8d43-1f82a11f3b5e`
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
- agent final_message: La Adventure Elite 150 CC es una excelente opción. Para cotizarte, dime cuánto tiempo llevas en tu empleo actual.
- citations: `['Adventure Elite 150 CC']`
- fields after: `{'Doc_Completos': False, 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': None, 'plan_enganche': None, 'precio_contado_mxn': 29900, 'quote_sent': False, 'render_required': False, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Tengo 8 meses trabajando.
- agent final_message: Perfecto, cumples con la antigüedad. Para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método.
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
- confidence: `1.0`
- pass/fail: `pass`

### cliente_pide_humano

- conversation_id: `ad0307bd-9863-455d-8e49-773c95372f0a`
- customer_id: `7a7118b7-a852-4118-9393-f7cd09d9f393`
- final_stage: `nuevos`
- final_fields: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': True}`
- pass/fail: `passed`

- customer message: Hola.
- agent final_message: Hola, ¿en qué puedo ayudarte hoy? Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual?
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Handoff_Humano': False}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Quiero una moto.
- agent final_message: Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual?
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
- agent final_message: Entiendo que prefieres hablar con alguien real. Te voy a pasar con Francisco para que te ayude mejor.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': True}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Me urge que me llamen.
- agent final_message: Te entiendo, voy a pasar tu solicitud a Francisco para que te atienda lo más pronto posible.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Handoff_Humano': True}`
- stage after: `nuevos`
- docs checklist after: `None`
- actions preview/simulation: `[{'action_name': 'assign_conversation', 'status': 'skipped', 'simulation': True, 'dry_run': True}, {'action_name': 'trigger_workflow', 'status': 'skipped', 'simulation': True, 'dry_run': True}]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

### moto_barata_para_trabajar

- conversation_id: `c0e86f5d-d07f-48f7-ae7f-334b1db00083`
- customer_id: `0f4920f7-66fe-4b4b-80c0-9ebb9ac8b3f8`
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
- confidence: `0.9`
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
- agent final_message: Con eso, tu plan sería "Sin Comprobantes" con un enganche del 20%. Ahora, dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html
- citations: `['Sin Comprobantes']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Cual me recomiendas?
- agent final_message: Para recomendarte un modelo, necesito que me digas qué tipo de moto te interesa. Puedes revisar el catálogo aquí: https://dinamomotos.com/catalogo.html y decirme cuál te gusta.
- citations: `[]`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `1.0`
- pass/fail: `pass`

- customer message: Cotiza una opcion barata.
- agent final_message: Para opciones económicas, te recomiendo la Adventure 150 CC y la Classic 125 CC. Ambas son buenas y tienen un precio accesible. ¿Te gustaría que te cotice alguna de estas?
- citations: `['Guardia de Seguridad', 'Guardia de Seguridad', 'Negocio SAT', 'Negocio SAT', 'Nómina Recibos']`
- fields after: `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Handoff_Humano': False}`
- stage after: `plan`
- docs checklist after: `None`
- actions preview/simulation: `[]`
- policy result: `{'valid': True, 'issues': []}`
- confidence: `0.9`
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
| `documentos_mama` | `None` | `None` | `None` | `Comprobante de domicilio` | `False` |
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
| `credito_happy_path_nomina_tarjeta` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Tarjeta', 'Plan_Enganche': '10%', 'Cotizacion_Enviada': True, 'Doc_Completos': True, 'Handoff_Humano': True, 'stage_path': ['cliente_potencial', 'papeleria_incompleta', 'papeleria_completa']}` | `{'Doc_Completos': True, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '10%', 'Plan_Credito': 'Nomina Tarjeta', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Comando 400 CC'}, 'enganche_mxn': 8390, 'moto': 'Comando 400 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 3333, 'plan_credito': 'Nomina Tarjeta', 'plan_enganche': '10%', 'precio_contado_mxn': 79900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'Comando 400 CC', 'Docs_Checklist': [{'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'ESTADO_CUENTA', 'label': 'ESTADO_CUENTA', 'status': 'accepted'}, {'evidence': ['estado_cuenta.pdf', 'nomina.pdf', 'comprobante.jpg'], 'key': 'RECIBOS_NOMINA', 'label': 'RECIBOS_NOMINA', 'status': 'accepted'}]}` | `[]` |
| `contado_directo` | `{'Plan_Credito': 'Contado', 'Plan_Enganche': '100%', 'Cotizacion_Enviada': True, 'stage': 'cliente_potencial', 'no_credit_docs': True}` | `{'Doc_Completos': False, 'Cotizacion_Enviada': True, 'Plan_Enganche': '100%', 'Plan_Credito': 'Contado', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': None, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Contado', 'plan_enganche': '100%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': True, 'Moto': 'Adventure Elite 150 CC'}` | `[]` |
| `sin_comprobantes` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Sin Comprobantes', 'Plan_Enganche': '20%', 'Cotizacion_Enviada': True, 'stage_path': ['plan', 'cliente_potencial', 'papeleria_incompleta']}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '20%', 'Plan_Credito': 'Sin Comprobantes', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'U5 150 CC'}, 'enganche_mxn': 2615, 'moto': 'U5 150 CC', 'numero_quincenas': 72, 'pago_quincenal_mxn': 1039, 'plan_credito': 'Sin Comprobantes', 'plan_enganche': '20%', 'precio_contado_mxn': 24900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'U5 150 CC', 'Docs_Checklist': [{'evidence': ['ine.jpg'], 'key': 'INE_AMBOS_LADOS', 'label': 'INE_AMBOS_LADOS', 'status': 'received'}, {'evidence': [], 'key': 'COMPROBANTE_DOMICILIO', 'label': 'COMPROBANTE_DOMICILIO', 'status': 'missing'}]}` | `[]` |
| `nomina_recibos` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Nomina Recibos', 'Plan_Enganche': '15%', 'stage': 'cliente_potencial'}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Cotizacion_Enviada': True, 'Plan_Enganche': '15%', 'Plan_Credito': 'Nomina Recibos', 'Ultima_Cotizacion': {'citation': {'content_type': 'catalog', 'source_id': '9ce2ddb6-0277-53cb-9dcc-f7a62facbb76', 'title': 'Adventure Elite 150 CC'}, 'enganche_mxn': 4485, 'moto': 'Adventure Elite 150 CC', 'numero_quincenas': None, 'pago_quincenal_mxn': None, 'plan_credito': 'Nomina Recibos', 'plan_enganche': '15%', 'precio_contado_mxn': 29900, 'quote_sent': True, 'render_required': True, 'source': 'QuoteResolver', 'status': 'ok'}, 'Handoff_Humano': False, 'Moto': 'Adventure Elite 150 CC'}` | `[]` |
| `guardia` | `{'Cumple_Antiguedad': True, 'Plan_Credito': 'Guardia', 'Plan_Enganche': '30%', 'stage': 'plan'}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Plan_Enganche': '30%', 'Plan_Credito': 'Guardia', 'Handoff_Humano': False, 'Moto': 'R4'}` | `[]` |
| `documentos_mama` | `{'no_stage': 'papeleria_incompleta', 'Handoff_Humano': False}` | `{'Doc_Completos': False, 'Cumple_Antiguedad': True, 'Doc_Incompletos': 'Comprobante de domicilio', 'Handoff_Humano': False}` | `[]` |
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

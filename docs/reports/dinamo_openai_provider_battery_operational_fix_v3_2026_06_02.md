# Dinamo OpenAI Provider Battery - 2026-06-02

## Summary

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`
- provider/model: `openai` / `gpt-4o-mini`
- score: `0.9852`
- pass: `False`
- scenarios: `30`
- failed_count: `4`
- provider_fallback_count: `3`
- provider_error_count: `3`
- validation_error_count: `0`
- quote_placeholders: `0`
- real_side_effects: `0`
- side_effect_delta: `{'action_execution_logs': 0, 'customer_field_update_evidence': 0, 'customer_field_values': 0, 'lifecycle_stage_history': 0, 'messages': 0, 'outbound_outbox': 0, 'real_customers': 0, 'simulated_customers': 0, 'whatsapp_sends': 0, 'workflow_executions': 0}`

## Reports

- precheck_report: `C:\Users\Sprt\Documents\Proyectos IA\AtendIA-v2\docs\reports\dinamo_openai_precheck_2026_06_02.md`
- approval_records: `{'requested': 'C:\\Users\\Sprt\\Documents\\Proyectos IA\\AtendIA-v2\\docs\\reports\\dinamo_openai_provider_approval_record_2026_06_02.md', 'gate_compat': 'C:\\Users\\Sprt\\Documents\\Proyectos IA\\AtendIA-v2\\docs\\reports\\dinamo_model_provider_approval_record_2026_06_02.md'}`
- json_report: `..\docs\reports\dinamo_openai_provider_battery_operational_fix_v3_2026_06_02.json`

## Scenario Matrix

| # | scenario | score | confidence | policy | fallback | provider_error | field_updates | lifecycle_update | actions | failed_checks | citations | final_message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hola, quiero una moto a credito | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | Adventure Elite 150 CC, Alien R 175 CC, B52 250 CC, Bandid 350 CC, Chopper Bobber 250 CC | Para darte el mejor plan, dime ¿cuánto tiempo llevas en tu empleo actual? |
| 2 | Tengo 8 meses trabajando | `1.0` | `1.0` | `True` | `False` | `None` | `3` | `False` | `0` | ok | Nómina Recibos, Nómina Recibos, Guardia de Seguridad, Guardia de Seguridad, Negocio SAT | Perfecto, ya cumples con la antigüedad. Para ver qué plan te conviene más, dime cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método. |
| 3 | Tengo 2 meses trabajando | `1.0` | `0.0` | `True` | `False` | `None` | `3` | `True` | `0` | ok | Guardia de Seguridad, Guardia de Seguridad, Negocio SAT, Negocio SAT, Nómina Recibos | Entendido, por el momento los planes para trabajadores menores a 6 meses están deshabilitados. Escríbeme cuando cumplas los 6 meses y ese mismo día te armo tu plan. |
| 4 | Me interesa la Comando | `1.0` | `0.9` | `True` | `False` | `None` | `3` | `False` | `0` | ok | Comando 400 CC | Dime cómo recibes tus ingresos para poder cotizarte la Comando 400 CC. Puedes elegir entre: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Mándame el número o escribe el método. |
| 5 | Quiero comprar de contado la R4 | `0.8333` | `0.0` | `True` | `True` | `APITimeoutError` | `7` | `True` | `0` | answered_current_question, no_provider_fallback, no_provider_error | R4 250 CC, Adventure Elite 150 CC, Alien R 175 CC, B52 250 CC, Bandid 350 CC | Necesito que una persona del equipo revise esto para responderte con certeza. |
| 6 | Me depositan en tarjeta | `1.0` | `1.0` | `True` | `False` | `None` | `4` | `True` | `0` | ok | Nómina Tarjeta | Perfecto, con que te depositan en tarjeta, te corresponde el plan de Nómina Tarjeta con un enganche del 10%. ¿Cuánto tiempo llevas en tu empleo actual? |
| 7 | Si tengo recibos de nomina | `1.0` | `1.0` | `True` | `False` | `None` | `4` | `True` | `0` | ok | Nómina Recibos, Nómina Recibos | Perfecto, con recibos de nómina te corresponde el plan de 15% de enganche. ¿Cuál es el modelo de la moto que te interesa para cotizarte? Puedes ver el catálogo aquí: https://dinamomotos.com/catalogo.html |
| 8 | Me pagan en efectivo pero tengo recibos | `0.8889` | `0.0` | `True` | `True` | `APITimeoutError` | `4` | `True` | `0` | no_provider_fallback, no_provider_error | Nómina Recibos, Nómina Recibos, Sin Comprobantes, Sin Comprobantes, ¿Qué requisitos necesito para iniciar mi trámite? | Necesito que una persona del equipo revise esto para responderte con certeza. |
| 9 | Me pagan por fuera | `1.0` | `1.0` | `True` | `False` | `None` | `4` | `True` | `0` | ok | Nómina Recibos, Nómina Recibos, Nómina Tarjeta, Nómina Tarjeta, Sin Comprobantes | Entendido, eso significa que tu plan sería "Sin Comprobantes" con un enganche del 20%. Para cotizarte, dime el modelo de la moto que quieres. Puedes ver el catálogo aquí: https://dinamomotos.com/catalogo.html |
| 10 | Soy pensionado | `0.8889` | `0.0` | `True` | `True` | `APITimeoutError` | `4` | `True` | `0` | no_provider_fallback, no_provider_error | Pensionados, Pensionados, Guardia de Seguridad, Guardia de Seguridad, reglas_globales_requisitos | Necesito que una persona del equipo revise esto para responderte con certeza. |
| 11 | Tengo negocio con SAT | `1.0` | `1.0` | `True` | `False` | `None` | `4` | `True` | `0` | ok | Negocio SAT, Negocio SAT, ¿Cuánto es el enganche mínimo? | Perfecto, con tu negocio registrado en SAT, el plan que te conviene es el de Negocio SAT con un enganche del 15%. ¿Cuánto tiempo llevas en tu empleo actual? |
| 12 | Soy guardia de seguridad | `1.0` | `1.0` | `True` | `False` | `None` | `4` | `True` | `0` | ok | Guardia de Seguridad, Guardia de Seguridad | Perfecto, como guardia de seguridad, tu enganche es del 30%. ¿Cuánto tiempo llevas en tu empleo actual? |
| 13 | Estoy en buro | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | ¿Se puede hacer el trámite si estoy en buró?, ¿Puedo iniciar el trámite sin tener todo? | Sí revisamos buró, pero es flexible; puede aplicar si debes menos de $50,000 y queda sujeto a validación. Para seguir, dime ¿cuánto tiempo llevas en tu empleo actual? |
| 14 | Que documentos necesito? | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | Guardia de Seguridad, Negocio SAT, Nómina Recibos, Nómina Tarjeta, Pensionados | Para poder ayudarte mejor, necesito saber qué plan de crédito te interesa. Los documentos varían según el plan, pero generalmente se requiere: 1. INE por ambos lados 2. Comprobante de domicilio reciente 3. Documento específico según el plan. ¿Te gustaría que te explique los planes disponibles? |
| 15 | Puedo mandar documentos de mi mama? | `1.0` | `0.9` | `True` | `False` | `None` | `2` | `False` | `0` | ok | Guardia de Seguridad, Negocio SAT, Nómina Recibos, Nómina Tarjeta, Pensionados | No se pueden enviar documentos de otra persona. Para avanzar, necesito tus documentos. ¿Cuánto tiempo llevas en tu empleo actual? |
| 16 | Te mando la INE | `1.0` | `1.0` | `True` | `False` | `None` | `3` | `False` | `0` | ok | Guardia de Seguridad, Guardia de Seguridad, Negocio SAT, Negocio SAT, Nómina Recibos | Para avanzar tu trámite, mándame tu INE por ambos lados, completa, bien iluminada y legible. |
| 17 | Ya envie todos los documentos | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `True` | `0` | ok | Guardia de Seguridad, Negocio SAT, Nómina Recibos, Nómina Tarjeta, Pensionados | Entendido, ya que enviaste todos los documentos, voy a revisar tu expediente. ¿Te gustaría que te pase con Francisco para que te ayude con el siguiente paso? |
| 18 | Quiero hablar con alguien real | `1.0` | `0.0` | `True` | `False` | `None` | `2` | `False` | `1` | ok | none | Para no darte un dato incorrecto, te paso con Francisco y lo revisamos bien. |
| 19 | Me pasas catalogo? | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | ¿Dónde puedo ver los modelos disponibles? | Claro, aquí tienes el catálogo: https://wa.me/c/5218186016492 ¿Ya tienes algún modelo en mente? |
| 20 | La quiero roja | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | none | Dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html |
| 21 | Me interesa la Adventure | `1.0` | `1.0` | `True` | `False` | `None` | `4` | `True` | `0` | ok | Adventure Elite 150 CC | Dime cómo recibes tus ingresos para poder cotizarte la Adventure Elite 150 CC. Puedes elegir entre: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad Puedes mandarme el número o escribir el método. |
| 22 | Quiero una moto barata para trabajar | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | none | Para recomendarte una moto barata para trabajar, primero dime Â¿cuÃ¡nto tiempo llevas en tu empleo actual? |
| 23 | Si | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | none | Perfecto, entonces estás en el plan Nómina Tarjeta con enganche del 10%. Ahora, dime el modelo de la moto que quieres para cotizarte según tu plan. Catálogo: https://dinamomotos.com/catalogo.html |
| 24 | Esa | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | none | Te cotizo la Adventure Elite 150 CC. Para eso, necesito saber cómo recibes tus ingresos: 1. Me depositan nómina en tarjeta 2. Me pagan con recibos de nómina 3. Soy pensionado 4. Tengo negocio registrado en SAT 5. Me pagan sin comprobantes 6. Soy guardia de seguridad. ¿Cuál es tu método? |
| 25 | Mañana | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | none | Perfecto, entonces mañana te espero para la revisión. ¿A qué hora planeas venir? |
| 26 | Mi comprobante no coincide con mi INE | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | Guardia de Seguridad, Guardia de Seguridad, Negocio SAT, Negocio SAT, Nómina Recibos | Entiendo, si tu comprobante no coincide con tu INE, es importante que lo aclares. ¿Tienes otro comprobante que puedas enviar o necesitas ayuda con algo más? |
| 27 | Me aprueban seguro? | `1.0` | `0.9` | `True` | `False` | `None` | `2` | `False` | `0` | ok | none | No te puedo prometer aprobaciÃ³n segura; se revisa tu caso con la financiera. Para avanzar, dime Â¿cuÃ¡nto tiempo llevas en tu empleo actual? |
| 28 | Ya pague y quiero cambiar de moto | `1.0` | `1.0` | `True` | `False` | `None` | `2` | `False` | `0` | ok | ¿Puedo cambiar el modelo después de iniciar el trámite? | Sí, puedes cambiar de moto siempre y cuando aún no hayas dado el enganche. ¿Qué modelo de moto te gustaría considerar ahora? |
| 29 | No tengo comprobante de domicilio | `0.9444` | `0.9` | `True` | `False` | `None` | `2` | `False` | `0` | answered_current_question | Guardia de Seguridad, Guardia de Seguridad, Negocio SAT, Negocio SAT, Nómina Recibos | Entiendo, pero para avanzar con tu trámite, necesito que me digas cómo recibes tus ingresos. Esto me ayudará a determinar el mejor plan para ti. |
| 30 | Quiero una R4 o algo parecido | `1.0` | `0.9` | `True` | `False` | `None` | `4` | `True` | `0` | ok | none | No tengo la R4 en el catálogo, pero puedo ayudarte a encontrar algo similar. ¿Te gustaría que te muestre algunas opciones de motos deportivas? |

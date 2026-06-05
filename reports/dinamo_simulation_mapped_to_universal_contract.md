# Simulacion Dinamo mapeada al contrato universal

Fecha: 2026-06-03
Estado: simulacion conceptual. No se ejecuto contra trafico real, no se envio WhatsApp y no se activo workflow real.

## Objetivo

Demostrar como una conversacion Dinamo se procesa usando contratos universales, sin hardcodear Dinamo dentro de `agent_runtime_v2`.

## Supuestos seguros

- Tenant: `dinamo_motos_nl`.
- Dominio: `vehicle_credit_sales`.
- Live send: deshabilitado.
- Actions/workflows reales: deshabilitados.
- Tools: simuladas/fixture.
- Runner legacy: permanece fallback.

## Turno 1: lead inicia y pregunta por moto

### Input cliente

> Hola, me interesa una moto para credito.

### GPT entiende

- Intent: interes de compra con credito.
- Entidades: credito.
- Incertidumbre: falta modelo/moto.

### GPT propone

- `intent_identified`.
- Campo `lead_interest=credit_vehicle`.
- Stage `primer_contacto`.
- Preguntar por modelo o presupuesto.

### AtendIA valida

- No requiere catalog tool todavia porque no hay modelo especifico.
- Acepta stage `primer_contacto` si pipeline lo permite.
- Emite `lead_started` idempotente.

### Final message

Respuesta visible pregunta por moto, presupuesto o uso, sin inventar precio.

### Trace esperado

- `business_events`: `lead_started`, `intent_identified`.
- `guards`: passed.
- `workflow_results`: dry-run/no side effects.

## Turno 2: cliente menciona modelo

### Input cliente

> Me gusta la X150, cuanto queda?

### GPT entiende

- Producto mencionado: X150.
- Pide cotizacion.

### GPT propone

- `product_selection=X150`.
- Quiere responder precio/pago.

### Herramientas obligatorias

- `catalog.search`: requerido por producto/modelo.
- `quote.resolve`: requerido si se va a hablar de pago/precio.
- `credit_plan.resolve`: requerido si la cotizacion depende de plan y aun no hay plan.

### AtendIA valida

- Ejecuta `catalog.search`.
- Si falta plan, bloquea cotizacion final y pide elegir plan o datos necesarios.
- Acepta `product_selection` solo si catalog match.
- No emite `offer_quoted` todavia si no hay quote snapshot.

### Final message

Confirma que ubico el modelo si catalog match y pide plan/dato faltante para cotizar.

### Trace esperado

- `mandatory_tool_decisions`: catalog executed, quote blocked/missing precondition.
- `state_changes.accepted`: product selection con source catalog.
- `guards`: `mandatory_tool_guard` passed for catalog, `quote_snapshot_guard` blocks price.

## Turno 3: cliente elige plan y enganche

### Input cliente

> Con plan semanal y 3000 de enganche.

### GPT entiende

- Plan: semanal.
- Enganche: 3000.
- Puede cotizar si ya hay moto.

### Herramientas obligatorias

- `credit_plan.resolve`.
- `quote.resolve`.

### AtendIA valida

- Valida plan contra configuracion.
- Ejecuta `quote.resolve` con moto, plan y enganche.
- Acepta `plan_selection`, `down_payment_amount` si la politica lo permite.
- Acepta `quote_snapshot_id`, `payment_amount`, `quote_valid_until` solo desde tool.
- Emite `plan_identified` y `offer_quoted` idempotentes.
- Stage validado: `cotizado`.

### Final message

Muestra cotizacion usando solo datos del snapshot, con vigencia si existe.

### Trace esperado

- `tool_results`: credit plan + quote.
- `state_changes.accepted`: plan, enganche, quote snapshot.
- `business_events`: `plan_identified`, `offer_quoted`.
- `workflow_results`: dry-run; ninguna accion real.

## Turno 4: cliente pregunta por buro

### Input cliente

> Estoy en buro, si paso?

### GPT entiende

- Politica sensible: buro/aprobacion.
- Riesgo: no prometer aprobacion ni rechazar automaticamente.

### GPT propone

- `bureau_mentioned=true`.
- Responder politica.
- Posible handoff si se requiere revision.

### Herramienta obligatoria

- `faq.lookup` o `policy.lookup` para politica de buro/aprobacion.

### AtendIA valida

- Acepta `bureau_mentioned=true` porque el cliente lo dijo explicitamente.
- No acepta `bureau_status=rejected` ni `approval_status=approved`.
- Ejecuta policy lookup.
- Si politica requiere revision, emite `human_handoff_requested`.

### Final message

Explica con cuidado que estar en buro no equivale a aprobacion ni rechazo automatico y que se revisa con asesor/requisitos.

### Trace esperado

- `guards`: `no_approval_guard`, `bureau_no_auto_reject_guard`.
- `state_changes.blocked`: cualquier decision final de credito propuesta por GPT.
- `business_events`: posible `human_handoff_requested`.

## Turno 5: AtendIA pide papeleria

### Input cliente

> Que documentos ocupas?

### GPT entiende

- Pide requisitos.
- Requisitos dependen del plan/seleccion.

### Herramienta obligatoria

- `requirements.lookup`.

### AtendIA valida

- Busca requisitos por tenant, pipeline y plan/seleccion.
- Permite final copy con lista de requisitos solo desde tool.
- Emite `requirements_requested`.
- Stage validado: `papeleria_solicitada`.

### Final message

Lista documentos/requisitos segun tool, sin agregar documentos inventados.

### Trace esperado

- `tool_results`: requirements.
- `business_events`: `requirements_requested`.
- `guards`: `requirements_plan_guard` passed si plan existe.

## Turno 6: cliente dice que ya envio documentos sin adjunto

### Input cliente

> Ya te mande todo.

### GPT entiende

- Cliente afirma documentos enviados.
- No hay adjunto en este turno.

### GPT propone riesgoso

- Marcar documentos recibidos.
- Marcar `requirements_complete=true`.

### AtendIA valida

- `document_real_guard` bloquea documento recibido sin adjunto/evidencia.
- `doc_complete_guard` bloquea completitud propuesta por modelo.
- Puede pedir que adjunte documentos o avisar que un asesor revisara.
- No emite `requirements_complete`.

### Final message

Pide adjuntar documentos o indica que se revisara lo recibido, sin marcar completitud.

### Trace esperado

- `state_changes.blocked`: document statuses, requirements_complete.
- `guards`: document_real_guard blocked, doc_complete_guard blocked.
- `business_events`: `policy_blocked` o `human_handoff_requested` segun config.

## Correcciones explicitas que evita el contrato

| Riesgo | Como se evita |
| --- | --- |
| Mencionar buro se vuelve rechazo automatico | `bureau_no_auto_reject_guard` y field policies separan `bureau_mentioned` de `bureau_status`. |
| Cotizar sin herramienta | `quote_snapshot_guard` bloquea precios sin `quote.resolve`. |
| Pedir papeleria generica o incorrecta | `requirements.lookup` obligatorio. |
| Completar documentos por texto | `attachment_evidence_guard` y `doc_complete_guard`. |
| Duplicar workflows | `workflow_idempotency_guard`. |
| Activar live smoke de un contacto | Prohibido en esta etapa; solo fixtures/shadow. |
| Hardcodear Dinamo en core | Toda regla vive en tenant/domain config. |

## Conclusion

La simulacion muestra que Dinamo puede operar como un tenant del contrato universal. La clave no es un prompt mas largo, sino hacer obligatorias las herramientas y exponer en trace lo que GPT propuso contra lo que AtendIA valido.

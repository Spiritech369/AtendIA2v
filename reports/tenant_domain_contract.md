# Contrato universal de tenant/domain

Fecha: 2026-06-03
Objetivo: definir la autoridad declarativa que permite usar AtendIA en Dinamo y en otros nichos sin hardcodear verticales dentro de `agent_runtime_v2`.

## Principios

1. El runtime no conoce Dinamo, motos, credito, documentos especificos ni reglas de un tenant.
2. El tenant declara dominio, campos, herramientas, pipeline, eventos, guardas y presentacion.
3. El modelo puede proponer, pero AtendIA valida y escribe.
4. Las herramientas devuelven datos estructurados, nunca copy final visible.
5. `TurnOutput.final_message` sigue siendo la unica autoridad de respuesta visible.
6. Todo cambio de estado requiere evidencia, source, writer, trace y policy decision.
7. El frontend renderiza desde metadata, no desde nombres hardcodeados.

## Objeto raiz

```json
{
  "contract_version": "1.0",
  "tenant_id": "uuid-or-slug",
  "agent_id": "uuid-or-slug",
  "domain": "vehicle_credit_sales",
  "locale": "es-MX",
  "timezone": "America/Mexico_City",
  "entities": {},
  "fields": [],
  "tools": [],
  "pipeline": {},
  "workflow_events": [],
  "guards": [],
  "frontend": {},
  "trace": {},
  "safety": {}
}
```

## Dominios soportables

| Domain | Ejemplos | Entidades principales | Herramientas criticas |
| --- | --- | --- | --- |
| `vehicle_credit_sales` | Motos, autos con financiamiento | producto, plan, requisitos, documentos, cotizacion | catalog, quote, requirements, faq, document_check |
| `appointment_services` | Clinicas, belleza, talleres | servicio, disponibilidad, cita, cliente | service_catalog, availability, booking, faq |
| `medical_dental` | Consultorios, odontologia | servicio, cobertura, cita, paciente | faq, availability, booking, policy_lookup |
| `real_estate` | Rentas, ventas, leads inmobiliarios | propiedad, presupuesto, zona, cita | listing_search, qualification, appointment |
| `automotive_sales` | Autos nuevos/usados | vehiculo, plan, prueba, cotizacion | catalog, quote, availability, appointment |
| `services_quotes` | Servicios de instalacion/reparacion | servicio, alcance, ubicacion, cotizacion | service_catalog, quote, requirements |
| `tourism_booking` | Tours, hoteles, experiencias | paquete, fecha, disponibilidad, reserva | catalog, availability, booking, faq |
| `generic_lead_qualification` | Captura de leads | necesidad, presupuesto, contacto, siguiente paso | faq, qualification, handoff |

## Campos canonicos

Cada campo declarado por tenant debe incluir:

| Propiedad | Descripcion |
| --- | --- |
| `key` | Identificador interno estable. |
| `label` | Nombre visible para el frontend. |
| `type` | `string`, `number`, `boolean`, `enum`, `money`, `date`, `document_status`, `object`. |
| `domain_role` | Rol semantico universal: `selection`, `plan`, `income`, `document`, `eligibility`, `contact`, `appointment`, `quote`. |
| `aliases` | Nombres legacy o sinonimos aceptados. |
| `source_policy` | Fuentes permitidas: `user_message`, `tool_result`, `attachment`, `admin`, `system_rule`. |
| `write_policy` | `auto_apply`, `suggest_review`, `tool_only`, `blocked_from_model`. |
| `evidence_required` | Si requiere evidencia externa o tool. |
| `owner` | `model_proposed`, `tool_verified`, `human_verified`, `system_derived`. |
| `lifecycle_relevant` | Si puede disparar reglas de pipeline. |
| `frontend` | Grupo, orden, icono opcional, display format y ayuda interna. |

## Herramientas

El contrato declara herramientas por tema y por riesgo.

```json
{
  "tool_id": "quote.resolve",
  "required_when": [
    "final_message_mentions_price",
    "field_update.quote_snapshot",
    "workflow_event.offer_quoted"
  ],
  "inputs": {
    "selection_key": "field:product_selection",
    "plan_key": "field:plan_selection",
    "customer_context": "safe_subset"
  },
  "outputs": {
    "quote_snapshot": "object",
    "valid_until": "date",
    "citations": "array"
  },
  "visibility": "structured_only"
}
```

## Pipeline

El pipeline universal no define etapas globales. Declara etapas del tenant con roles.

| Propiedad | Descripcion |
| --- | --- |
| `stage_key` | Etapa interna. |
| `label` | Nombre visible. |
| `role` | `new`, `qualified`, `selection`, `quoted`, `requirements`, `closed_won`, `closed_lost`, `handoff`. |
| `entry_rules` | Condiciones declarativas por fields, tools, events o evidence. |
| `exit_rules` | Condiciones para salir. |
| `manual_allowed` | Si un humano puede mover manualmente. |
| `workflow_triggers` | Eventos emitidos al entrar/salir. |

## Eventos de negocio universales

| Evento | Significado |
| --- | --- |
| `lead_started` | Conversacion o lead operativo iniciado. |
| `intent_identified` | Se identifico una intencion principal. |
| `selection_identified` | Se identifico producto, servicio o opcion. |
| `plan_identified` | Se identifico plan, modalidad o variante. |
| `offer_quoted` | Se genero oferta/cotizacion confiable. |
| `requirements_requested` | Se pidieron requisitos/documentos. |
| `requirements_partial` | Se recibio una parte de requisitos. |
| `requirements_complete` | Requisitos completos con evidencia. |
| `appointment_requested` | Cliente pidio agendar. |
| `appointment_scheduled` | Cita confirmada por herramienta o humano. |
| `human_handoff_requested` | Debe intervenir humano. |
| `policy_blocked` | Una accion o respuesta fue bloqueada. |

## Guardas universales

| Guardia | Enforce |
| --- | --- |
| `mandatory_tool_guard` | Bloquea facts sensibles sin herramienta requerida. |
| `state_write_guard` | Bloquea escrituras sin permiso/evidencia. |
| `final_copy_guard` | Revisa que el copy visible use solo hechos validados. |
| `workflow_idempotency_guard` | Evita acciones duplicadas o loops. |
| `attachment_evidence_guard` | Impide marcar documentos sin adjunto/evidencia. |
| `provider_fallback_guard` | Controla fallback si GPT falla. |
| `tenant_isolation_guard` | Evita mezclar catalogos, docs o reglas de tenants. |

## Frontend

El frontend debe recibir:

- Field groups y labels por tenant.
- Campo `source` y `confidence` por valor.
- Writer: `user`, `model`, `tool`, `human`, `system`.
- Estado de valor: `proposed`, `validated`, `rejected`, `needs_review`.
- Ultima evidencia y trace link.
- Pipeline stages con rol y reglas legibles.
- Eventos de negocio y side effects.
- Guard blocks y razones.

## Trace minimo

Cada turno debe poder responder:

1. Que dijo el cliente.
2. Que entendio GPT.
3. Que propuso GPT.
4. Que herramientas eran obligatorias.
5. Que herramientas se ejecutaron.
6. Que acepto o bloqueo AtendIA.
7. Que cambio en memoria/pipeline.
8. Que workflow se disparo o quedo bloqueado.
9. Que respuesta final se envio.

## Resultado esperado

Con este contrato, Dinamo se vuelve una configuracion tenant-scoped del dominio `vehicle_credit_sales`, no una rama especial del runtime.

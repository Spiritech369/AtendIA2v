# Contrato de herramientas obligatorias

Fecha: 2026-06-03
Objetivo: impedir que el modelo invente o confirme facts sensibles sin herramienta confiable, manteniendo tools como datos estructurados y no como copy visible.

## Principio

Cuando un tema tiene riesgo operativo, legal, financiero, comercial o de confianza, el runtime debe exigir una herramienta declarada por el tenant/domain contract.

El modelo puede sugerir que se necesita una herramienta. AtendIA decide si es obligatoria.

## Topics universales

| Topic | Cuando aplica | Tool universal |
| --- | --- | --- |
| `catalog_or_listing` | Producto, servicio, propiedad, paquete, disponibilidad, ficha. | `catalog.search` o equivalente domain tool. |
| `offer_or_quote` | Precio, pago, plan, vigencia, cotizacion, descuento. | `quote.resolve` |
| `requirements` | Requisitos, documentos, pasos obligatorios. | `requirements.lookup` |
| `policy_or_faq` | Politicas, restricciones, aprobacion, garantias, cobertura. | `faq.lookup` o `policy.lookup` |
| `document_status` | Documento recibido, rechazado, completo. | `document.check` |
| `availability` | Horario, stock operativo, cita, agenda. | `availability.check` |
| `booking_or_action` | Crear cita, tarea, follow-up, handoff. | `action.execute` gated |

## Esquema de decision

```json
{
  "tool_id": "quote.resolve",
  "topic": "offer_or_quote",
  "required": true,
  "reason": "final_message_mentions_price",
  "trigger_source": "draft_final_message",
  "blocking_scopes": ["final_message", "state_write", "workflow_event"],
  "status": "missing",
  "fallback": "ask_clarifying_or_handoff"
}
```

## Esquema de resultado

```json
{
  "tool_id": "quote.resolve",
  "status": "success",
  "tenant_id": "tenant_123",
  "inputs": {},
  "output": {},
  "citations": [],
  "no_data_reason": null,
  "used_for": ["final_message", "field_update.quote_snapshot_id"],
  "visible_text_allowed": false
}
```

## Invariantes

1. Una tool no devuelve copy final visible.
2. Una tool result no puede contener `final_message`, `message`, `reply` ni texto destinado al cliente.
3. Todo resultado incluye tenant_id o queda asociado al tenant en trace.
4. Si una tool obligatoria falta, el fact sensible se bloquea.
5. Si una tool devuelve no-data, el final copy debe reconocer incertidumbre o pedir dato faltante.
6. Si la tool contradice a GPT, gana la tool validada.

## Matriz universal topic -> enforcement

| Trigger | Tool requerida | Bloquea si falta |
| --- | --- | --- |
| Final copy menciona precio, pago, descuento o vigencia | `quote.resolve` | `final_message`, `quote field update`, `offer_quoted` |
| Field update escribe producto/servicio seleccionado | `catalog.search` | `field_update`, stage de seleccion |
| Field update escribe quote snapshot | `quote.resolve` | `field_update`, stage quoted |
| Final copy pide requisitos/documentos especificos | `requirements.lookup` | `final_message`, `requirements_requested` |
| Field update marca documento recibido/rechazado | `document.check` | `field_update`, `requirements_partial` |
| Field update marca requirements complete | `requirements.lookup` + `document.check` | `field_update`, stage complete |
| Final copy responde politica sensible | `faq.lookup` o `policy.lookup` | `final_message` |
| Workflow ejecuta accion externa | action tool gated | `workflow side effect` |

## Dinamo mapping

| Dinamo topic | Tool | Regla obligatoria |
| --- | --- | --- |
| Moto/modelo | `catalog.search` | Si se identifica o recomienda moto. |
| Plan credito | `credit_plan.resolve` | Si se habla de plan, enganche, mensualidad o modalidad. |
| Cotizacion | `quote.resolve` | Si se menciona pago, precio, enganche, vigencia o se pasa a `cotizado`. |
| Papeleria | `requirements.lookup` | Si se pide INE, comprobantes u otros requisitos. |
| Documento recibido | `document.check` | Si se intenta marcar documento como recibido. |
| Buro/aprobacion | `faq.lookup`/`policy.lookup` | Si se responde sobre buro o aprobacion. |
| Handoff | `handoff.create` dry-run until approved | Si guard o politica requiere humano. |

## Comportamiento ante tool faltante

| Caso | Respuesta operativa |
| --- | --- |
| Tool requerida no configurada | Bloquear fact sensible y emitir `policy_blocked`. |
| Tool falla | Fallback seguro: pedir dato faltante, explicar que se revisa, o handoff. |
| Tool no data | No inventar; responder con incertidumbre controlada. |
| Tool contradice propuesta GPT | Bloquear propuesta GPT y usar dato tool si esta permitido. |
| Tool da dato viejo | Aplicar `stale_offer_guard` o equivalente. |

## Implementacion recomendada

1. Crear registry declarativo de `ToolRequirementRule`.
2. Evaluar reglas sobre GPT proposed output y draft final copy.
3. Ejecutar tools antes de StateWriter y antes de Composer final.
4. Guardar decisiones en `TurnTrace.mandatory_tool_decisions`.
5. Exponer en frontend con `ToolRequirementCard`.
6. Probar con fixtures de Dinamo y un tenant no-Dinamo.

## Tests obligatorios

- Precio en final copy sin `quote.resolve` queda bloqueado.
- Moto propuesta sin catalog match queda `needs_review`.
- Papeleria pedida sin `requirements.lookup` queda bloqueada.
- Documento por texto sin adjunto queda bloqueado.
- Buro mencionado no dispara rechazo automatico.
- Tenant B no puede usar catalogo de Dinamo.

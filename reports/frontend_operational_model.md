# Modelo operativo de frontend multitenant

Fecha: 2026-06-03
Alcance: especificacion de producto/frontend. No se modifico frontend en este reporte.

## Objetivo

El frontend debe permitir operar cualquier tenant sin conocer su vertical. Dinamo debe verse como una configuracion del dominio `vehicle_credit_sales`, no como campos hardcodeados en componentes React o rutas API.

## Principios de UI operativa

1. Mostrar datos validados antes que texto generado.
2. Distinguir claramente `proposed`, `validated`, `needs_review`, `rejected` y `blocked`.
3. Mostrar source, writer, confidence y trace para cada campo relevante.
4. Mostrar pipeline y workflows como consecuencias auditables, no como magia del bot.
5. Permitir a asesores entender por que AtendIA respondio o bloqueo algo.
6. No renderizar labels, aliases ni agrupaciones desde supuestos globales.

## Pantallas afectadas

| Pantalla/componente | Estado actual | Cambio requerido |
| --- | --- | --- |
| `ConversationDetail.tsx` | Chat con panel lateral y debug toggle. | Agregar resumen operativo del turno seleccionado y link claro a trace. |
| `ContactPanel.tsx` | Panel de contacto con aliases canonicos acoplados a Dinamo. | Renderizar fields/groups desde metadata tenant. |
| `DebugPanel.tsx` | Debug tecnico util. | Agregar vista no tecnica de decisiones: propuesta, herramientas, validacion y guardas. |
| `frontend/src/features/turn-traces/*` | Paneles de trace genericos. | Agregar timeline universal de decision y business events. |
| `PipelineKanbanPage.tsx` | Pipeline visual. | Mostrar stage reason, trace source y automation status. |
| `WorkflowEditor.tsx` | Editor funcional. | Lint de eventos criticos, loops, side effects y condiciones incompletas. |

## Panel operativo recomendado

### 1. Contact summary

Muestra campos del tenant organizados por metadata:

- `selection`: producto/servicio/opcion elegida.
- `plan`: modalidad, paquete o variante.
- `quote`: oferta, pago, vigencia, snapshot.
- `requirements`: documentos/requisitos.
- `eligibility`: datos de decision o calificacion.
- `contact`: datos basicos.
- `handoff`: necesidad de humano.

Cada fila debe incluir:

| Columna | Descripcion |
| --- | --- |
| Label | Desde tenant metadata. |
| Valor | Valor actual validado o propuesta pendiente. |
| Estado | `validated`, `proposed`, `needs_review`, `rejected`, `blocked`. |
| Source | `user_message`, `tool_result`, `attachment`, `human`, `system`. |
| Writer | `model`, `tool`, `human`, `system`. |
| Confidence | Score cuando exista. |
| Trace | Link al turno que lo origino. |

### 2. Decision timeline

Un timeline por conversacion debe mostrar:

1. Cliente envio mensaje.
2. GPT entendio intencion.
3. GPT propuso field updates, lifecycle updates y actions.
4. AtendIA exigio tools.
5. Tools devolvieron facts.
6. StateWriter acepto o bloqueo.
7. Guards revisaron final copy.
8. Pipeline cambio o no cambio.
9. Workflows dispararon, quedaron en dry-run o fueron bloqueados.
10. Cliente vio `TurnOutput.final_message`.

### 3. Business events

Los eventos deben mostrarse con nombres humanos configurados por tenant:

| Event key | Ejemplo label Dinamo |
| --- | --- |
| `lead_started` | Lead iniciado |
| `selection_identified` | Moto identificada |
| `plan_identified` | Plan identificado |
| `offer_quoted` | Cotizacion generada |
| `requirements_requested` | Papeleria solicitada |
| `requirements_complete` | Papeleria completa |
| `human_handoff_requested` | Requiere asesor |
| `policy_blocked` | Politica bloqueo accion |

### 4. Guard cards

Cada guard debe renderizar:

- Nombre visible.
- Resultado: `passed`, `warned`, `blocked`, `rewrote`.
- Motivo.
- Evidence/tool usado.
- Parte afectada: `field_update`, `lifecycle_update`, `action`, `final_message`, `workflow`.
- Suggested next action.

### 5. Tool cards

Cada tool card debe mostrar:

- Tool ID.
- Por que era obligatoria.
- Inputs seguros usados.
- Resultado estructurado.
- Citations o source ids.
- Si el resultado fue usado en final copy, state write o workflow.

### 6. Pipeline card

Muestra:

- Etapa actual.
- Etapa propuesta por GPT, si existio.
- Etapa validada por AtendIA.
- Regla que permitio o bloqueo.
- Trace link.
- Workflow events emitidos por la transicion.

### 7. Handoff card

Muestra:

- Razon de handoff.
- Nivel de urgencia.
- Campos faltantes.
- Guard o policy que lo disparo.
- Si se creo tarea, follow-up o solo sugerencia en dry-run.

## API/modelos requeridos

### `CustomerFieldView`

```json
{
  "key": "product_selection",
  "label": "Moto seleccionada",
  "value": "Dinamo X",
  "status": "validated",
  "source": "catalog.search",
  "writer": "tool",
  "confidence": 0.94,
  "last_trace_id": "trace_123",
  "evidence_id": "evidence_456",
  "group": "selection",
  "display_format": "text"
}
```

### `TurnDecisionView`

```json
{
  "turn_id": "turn_123",
  "gpt_understanding": {},
  "gpt_proposed": {
    "field_updates": [],
    "lifecycle_updates": [],
    "actions": []
  },
  "atendia_validation": {
    "required_tools": [],
    "tool_results": [],
    "accepted_state_writes": [],
    "blocked_state_writes": [],
    "guards": []
  },
  "business_events": [],
  "workflow_results": [],
  "final_message": "..."
}
```

## Cambios backend/API necesarios

1. Ampliar `ConversationDetail.customer_fields` para incluir metadata, status, source, writer, confidence y trace.
2. Exponer field evidence desde `CustomerFieldUpdateEvidence`.
3. Exponer `state_writer.accepted` y `state_writer.blocked` dentro de turn trace.
4. Exponer mandatory tool decisions.
5. Exponer business events emitidos por turno.
6. Exponer lifecycle transition reason y evidence.
7. Mantener raw JSON solo como respaldo; la vista principal debe ser operativa.

## Cambios frontend necesarios

1. Eliminar aliases canonicos hardcodeados en `ContactPanel.tsx`.
2. Crear renderer de field groups desde tenant metadata.
3. Crear `FieldEvidenceBadge` para source/writer/status.
4. Crear `DecisionTimeline` en turn traces.
5. Crear `GuardCard` y `ToolRequirementCard`.
6. Agregar lint en `WorkflowEditor` para triggers criticos sin idempotencia o con side effects activos.
7. Agregar tests con fixtures de Dinamo y de otro dominio no motos.

## Criterios de aceptacion

- Un tenant de citas puede renderizar campos sin modificar React.
- Dinamo puede mostrar moto/plan/cotizacion/papeleria desde metadata.
- Un campo propuesto por GPT pero bloqueado se ve como bloqueado, no como dato final.
- Un documento escrito desde texto sin adjunto se muestra como bloqueado.
- Una cotizacion sin `quote.resolve` aparece bloqueada por guard.
- El asesor puede abrir el trace y entender que final message se envio y por que.

## Riesgo principal

Si el frontend conserva aliases de Dinamo, la arquitectura seguira siendo multitenant solo en backend. La UI debe migrar a metadata tenant antes de declarar listo el runtime universal.

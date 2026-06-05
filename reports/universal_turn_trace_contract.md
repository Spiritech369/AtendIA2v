# Contrato universal de turn trace

Fecha: 2026-06-03
Objetivo: definir una traza unica para explicar cada turno en cualquier tenant y dominio.

## Problema

El sistema ya guarda mucha informacion tecnica de turnos, pero para operacion multitenant falta una vista canonica que separe:

- Lo que GPT entendio.
- Lo que GPT propuso.
- Lo que AtendIA exigio como herramientas.
- Lo que AtendIA valido o bloqueo.
- Lo que se escribio en memoria/pipeline.
- Lo que vio el cliente.

## Principio central

`TurnTrace` debe contar una historia verificable:

> GPT propuso. AtendIA valido. Las herramientas probaron facts. Los guards protegieron. El cliente vio solo `TurnOutput.final_message`.

## Esquema canonico

```json
{
  "trace_version": "1.0",
  "turn_id": "turn_123",
  "tenant_id": "tenant_123",
  "agent_id": "agent_123",
  "conversation_id": "conversation_123",
  "contact_id": "contact_123",
  "domain": "vehicle_credit_sales",
  "input": {},
  "gpt_understanding": {},
  "gpt_proposed": {},
  "mandatory_tool_decisions": [],
  "tool_results": [],
  "atendia_validation": {},
  "state_changes": {},
  "lifecycle": {},
  "business_events": [],
  "workflow_results": [],
  "guards": [],
  "provider": {},
  "final_output": {},
  "audit": {}
}
```

## Campos

### `input`

| Campo | Descripcion |
| --- | --- |
| `channel` | WhatsApp, web, test, etc. |
| `message_text` | Texto recibido, truncado/redactado si aplica. |
| `attachments` | Metadata de adjuntos, no contenido sensible completo. |
| `received_at` | Timestamp. |

### `gpt_understanding`

Incluye clasificacion y lectura del modelo:

- Intent.
- Entidades detectadas.
- Campos mencionados.
- Riesgos o incertidumbre.
- Necesidad de humano.

### `gpt_proposed`

Debe preservar la propuesta del modelo antes de validacion:

- `field_updates`.
- `lifecycle_updates`.
- `actions`.
- `required_tools` sugeridas.
- `draft_final_message`, si existio, marcado como no visible.

### `mandatory_tool_decisions`

Lista de herramientas que AtendIA exige por contrato:

| Campo | Descripcion |
| --- | --- |
| `tool_id` | Herramienta requerida. |
| `reason` | Regla que la hace obligatoria. |
| `trigger` | Fact, field, action o final copy que lo disparo. |
| `status` | `required`, `executed`, `missing`, `blocked`, `not_applicable`. |
| `blocking` | Si impide final copy o state write. |

### `tool_results`

Resultados estructurados:

- Tool ID.
- Inputs seguros.
- Output estructurado.
- Citations/source ids.
- Error o no-data.
- Uso posterior: final copy, field update, lifecycle, workflow.

### `atendia_validation`

Decision deterministica:

- Accepted field updates.
- Blocked field updates.
- Accepted lifecycle updates.
- Blocked lifecycle updates.
- Accepted actions.
- Blocked actions.
- Policy warnings.

### `state_changes`

Debe mostrar antes/despues y evidencia:

```json
{
  "before": {},
  "after": {},
  "accepted": [],
  "blocked": [],
  "evidence": []
}
```

### `lifecycle`

Incluye:

- Current stage.
- Proposed stage.
- Validated stage.
- Transition allowed/blocked.
- Rule/evidence.
- Source.

### `business_events`

Eventos normalizados emitidos o bloqueados:

- `lead_started`.
- `selection_identified`.
- `plan_identified`.
- `offer_quoted`.
- `requirements_requested`.
- `requirements_partial`.
- `requirements_complete`.
- `human_handoff_requested`.
- `policy_blocked`.

### `workflow_results`

Incluye:

- Workflow id.
- Trigger event.
- Matched conditions.
- Dry run status.
- Actions planned.
- Actions executed.
- Idempotency key.
- Loop/self-trigger decision.

### `guards`

Cada guard:

| Campo | Descripcion |
| --- | --- |
| `guard_id` | Nombre estable. |
| `scope` | `tool`, `state`, `lifecycle`, `workflow`, `final_message`, `provider`. |
| `result` | `passed`, `warned`, `blocked`, `rewrote`. |
| `reason` | Razon legible. |
| `evidence_refs` | Tool ids, trace ids, attachment ids. |

### `provider`

Incluye:

- Provider/model.
- Retries.
- Circuit breaker state.
- Fallback used.
- Latency.
- Cost si existe.
- Parse/repair events.

### `final_output`

La salida visible y su validacion:

```json
{
  "final_message": "...",
  "source": "TurnOutput.final_message",
  "sanitized": true,
  "blocked_sensitive_claims": [],
  "citations_used": []
}
```

### `audit`

Incluye:

- Actor/system ids.
- Versiones de contratos.
- Versiones de tools.
- `dry_run`.
- `live_send_enabled`.
- `actions_enabled`.
- Redactions aplicadas.

## Invariantes

1. No puede existir `final_output.final_message` si no proviene de `TurnOutput.final_message`.
2. Todo precio, oferta, requisito, disponibilidad o politica sensible debe tener tool trace o quedar bloqueado.
3. Todo field update aceptado debe tener source y evidence.
4. Todo lifecycle update aceptado debe tener reason y rule/evidence.
5. Todo workflow con side effect debe tener idempotency key.
6. El trace debe incluir tenant_id para preservar aislamiento.

## Frontend esperado

El frontend debe poder construir:

- Timeline operativo.
- Cards de tools obligatorias.
- Cards de guardas.
- Diff de estado propuesto vs validado.
- Explicacion de pipeline.
- Eventos/workflows por turno.
- Respuesta final enviada.

## Tests recomendados

1. Turno con cotizacion valida: exige `quote.resolve`, acepta snapshot y muestra final copy.
2. Turno con precio inventado: bloquea final copy sensible.
3. Turno con documento por texto: bloquea `requirements_complete`.
4. Turno con workflow duplicado: mismo idempotency key, no duplica accion.
5. Turno con tenant B: no muestra labels/campos de Dinamo.

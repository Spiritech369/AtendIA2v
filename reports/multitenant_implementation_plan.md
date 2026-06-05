# Plan de implementacion multitenant

Fecha: 2026-06-03
Estado: plan. No se modifico runtime, no se aplico configuracion, no se activo trafico.

## Decision general

Implementar arquitectura universal por contratos antes de activar Dinamo o cualquier tenant en vivo.

Orden recomendado:

1. Tool contract obligatorio.
2. Tenant/domain contract.
3. State writer declarativo.
4. Turn trace universal.
5. Frontend tenant-aware.
6. Workflow business events.
7. Fixtures/simulaciones Dinamo y tenant no-Dinamo.
8. Shadow comparison contra legacy.
9. Solo despues, evaluacion de rollout.

## Fase 0: congelar limites

### Objetivo

Evitar que el trabajo de migracion introduzca nuevos hardcodes.

### Cambios

- Agregar checks/tests que fallen si `agent_runtime_v2` importa o menciona Dinamo/motos/credito como regla global.
- Documentar legacy runner como fallback.

### Tests

- Test estatico sobre `core/atendia/agent_runtime`.
- Test que tools/actions siguen sin copy final visible.

### Aceptacion

- No hay nuevos hardcodes tenant/vertical en runtime v2.

## Fase 1: mandatory tool contract

### Objetivo

Hacer obligatorio el uso de tools para facts sensibles.

### Cambios

- Crear `ToolRequirementRule`.
- Evaluar reglas sobre propuesta GPT y draft/final candidate.
- Ejecutar o marcar missing tools.
- Guardar decisiones en trace metadata.
- Bloquear final/state/workflow cuando falte una tool obligatoria.

### Archivos probables

- `core/atendia/agent_runtime/advisor_pipeline.py`
- `core/atendia/agent_runtime/schemas.py`
- `core/atendia/agent_runtime/trace_schema.py` nuevo o equivalente
- `core/tests/agent_runtime/`

### Tests

- Precio sin quote tool bloqueado.
- Requisitos sin requirements tool bloqueados.
- Politica sensible sin FAQ/policy tool bloqueada.
- Tool result no puede contener final visible copy.

### Aceptacion

- El modelo no puede publicar facts sensibles sin tool trace.

## Fase 2: tenant/domain contract loader

### Objetivo

Cargar dominio, fields, tools, pipeline, events, guards y frontend metadata desde tenant config.

### Cambios

- Definir schema versionado.
- Validar config al cargar contexto.
- Hacer fallback seguro si falta config.
- Exponer metadata al frontend.

### Archivos probables

- `core/atendia/agent_runtime/context_builder.py`
- `core/atendia/agent_runtime/agent_config.py`
- `core/atendia/api/customer_fields_routes.py`
- `core/atendia/api/conversations_routes.py`

### Tests

- Tenant Dinamo carga `vehicle_credit_sales`.
- Tenant no-Dinamo carga otro dominio sin campos Dinamo.
- Config invalida no rompe runtime; cae a modo seguro.

### Aceptacion

- Runtime y frontend reciben metadata tenant/domain sin hardcodes.

## Fase 3: StateWriter declarativo

### Objetivo

Convertir reglas de escritura sensibles en field policies por tenant/domain.

### Cambios

- Mapear write policies: `auto_apply`, `suggest_review`, `tool_only`, `blocked_from_model`, `attachment_required`, `system_derived`.
- Guardar accepted/blocked con evidence.
- Separar `bureau_mentioned` de `bureau_status`.
- Bloquear completitud documental desde modelo.

### Tests

- Campo tool_only no se escribe desde modelo.
- Documento recibido requiere adjunto o humano.
- Requirements complete solo system-derived.
- Bureau mentioned no se convierte en rechazo.

### Aceptacion

- Las reglas de estado son configurables y auditables.

## Fase 4: Turn trace universal

### Objetivo

Exponer una narrativa universal de decisiones por turno.

### Cambios

- Agregar secciones: gpt_proposed, mandatory_tool_decisions, validation, guards, business_events, workflow_results.
- Mantener raw trace como respaldo.
- Exponer API para frontend.

### Tests

- Trace contiene propuesta y validacion.
- Tool missing aparece como bloqueante.
- Guard block visible.
- Final output proviene de `TurnOutput.final_message`.

### Aceptacion

- Un asesor puede explicar por que AtendIA respondio lo que respondio.

## Fase 5: Frontend tenant-aware

### Objetivo

Quitar conocimiento de Dinamo del frontend operativo.

### Cambios

- Reemplazar aliases canonicos hardcodeados por metadata.
- Crear field evidence badges.
- Crear decision timeline.
- Agregar tool/guard cards.
- Agregar pipeline reason cards.

### Tests

- Fixture Dinamo renderiza moto/plan/cotizacion/papeleria.
- Fixture tenant citas renderiza servicio/cita/disponibilidad sin campos Dinamo.
- Valor bloqueado no aparece como validado.

### Aceptacion

- El frontend funciona para dos dominios sin editar componentes.

## Fase 6: Workflow business events

### Objetivo

Mapear eventos universales de negocio a workflows con idempotencia.

### Cambios

- Registrar eventos universales.
- Agregar filtros por domain/field/tool/guard.
- Lint de workflows criticos.
- Mantener dry-run hasta approval.

### Tests

- `offer_quoted` dispara una vez.
- `requirements_complete` no dispara sin evidence.
- Self-trigger/loop queda bloqueado.
- Side effects quedan dry-run en modo no aprobado.

### Aceptacion

- Workflows reaccionan a eventos de negocio, no a texto frgil.

## Fase 7: Fixtures y simulaciones

### Objetivo

Probar Dinamo y otro tenant sin trafico real.

### Cambios

- Crear fixture Dinamo basado en este reporte.
- Crear fixture no-Dinamo, por ejemplo `appointment_services`.
- Comparar final messages, state writes, guards y workflows.

### Tests

- Snapshot tests de turn trace.
- Contract tests de tool requirements.
- Frontend rendering tests.

### Aceptacion

- La arquitectura demuestra multitenancy real con dos dominios.

## Fase 8: Shadow comparison y readiness

### Objetivo

Comparar runtime v2 contra legacy sin enviar mensajes reales.

### Cambios

- Ejecutar shadow/evaluation offline.
- Medir incoherencias, bloqueos correctos, missing tools y handoff.
- Preparar reporte de readiness.

### Tests

- Eval suite Dinamo.
- Provider reliability/fallback tests.
- No live-send assertions.

### Aceptacion

- Solo si pasa, se puede discutir rollout controlado en una tarea separada.

## Riesgos

| Riesgo | Mitigacion |
| --- | --- |
| Hardcodear Dinamo en runtime v2 | Tests estaticos y contrato tenant/domain. |
| Frontend sigue acoplado | Metadata tenant obligatoria y fixture no-Dinamo. |
| Tools faltantes bloquean mucho | Fallback seguro y handoff visible. |
| Workflows duplican acciones | Idempotency keys y dry-run. |
| Copy visible se dispersa | Mantener `TurnOutput.final_message` como autoridad. |
| Legacy y v2 divergen sin medicion | Shadow comparison antes de rollout. |

## Decision de implementacion

`IMPLEMENT_CONTRACTS_FIRST_NO_LIVE_ROLLOUT`

El primer cambio de codigo recomendado es implementar `mandatory_tool_contract`, porque reduce el mayor riesgo: facts sensibles generados sin herramienta confiable.

# Siguientes prompts para Codex: arquitectura multitenant

Fecha: 2026-06-03

Usar estos prompts en tareas separadas. Cada prompt debe mantener estas restricciones:

- No activar trafico real.
- No enviar WhatsApp reales.
- No aplicar configuracion Dinamo a produccion.
- No habilitar actions/workflows reales.
- No hardcodear Dinamo, motos, credito, documentos o reglas tenant en `agent_runtime_v2`.
- Mantener legacy runner como fallback.
- Incluir tests enfocados para cada cambio de comportamiento.
- Mantener `TurnOutput.final_message` como unica autoridad de copy visible.

## Prompt 1: implementar mandatory tool contract

Implementa el contrato de herramientas obligatorias descrito en `reports/mandatory_tool_contract.md`.

Alcance:

- Crear una capa declarativa de reglas `ToolRequirementRule` en `agent_runtime_v2`.
- Evaluar reglas sobre la propuesta del provider y cualquier candidate/draft final.
- Bloquear facts sensibles cuando falte tool obligatoria.
- Guardar `mandatory_tool_decisions` en trace metadata.
- No ejecutar acciones externas ni trafico real.
- No hardcodear Dinamo en core; usa fixtures/config de prueba.

Tests minimos:

- Precio sin `quote.resolve` bloqueado.
- Requisitos sin `requirements.lookup` bloqueados.
- Politica sensible sin `faq.lookup` o `policy.lookup` bloqueada.
- Tool result con `final_message`, `message` o `reply` rechazado.
- Tenant B no puede usar catalogo Dinamo.

## Prompt 2: cargar tenant/domain contract

Implementa loader y validacion para `tenant_domain_contract` segun `reports/tenant_domain_contract.md`.

Alcance:

- Definir schema versionado.
- Cargar desde tenant config existente o fixture local de test.
- Incluir fields, tools, pipeline, events, guards y frontend metadata en runtime context.
- Fallback seguro si falta o es invalido.
- No aplicar configuracion real.

Tests minimos:

- Dinamo fixture carga `vehicle_credit_sales`.
- Tenant de citas carga `appointment_services`.
- Tenant de citas no expone campos Dinamo.
- Config invalida no rompe runtime y activa modo seguro.

## Prompt 3: StateWriter declarativo

Convierte reglas sensibles de StateWriter a policies declarativas de field contract.

Alcance:

- Soportar `auto_apply`, `suggest_review`, `tool_only`, `blocked_from_model`, `attachment_required`, `system_derived`.
- Guardar accepted/blocked con evidence/source/writer.
- Separar `bureau_mentioned` de cualquier decision de buro/aprobacion.
- Bloquear completitud documental desde el modelo.

Tests minimos:

- Campo `tool_only` no se escribe desde propuesta GPT.
- Documento recibido requiere adjunto o human review.
- `requirements_complete` solo system-derived.
- Buro mencionado no genera rechazo automatico.

## Prompt 4: Turn trace universal

Implementa la vista universal de turn trace descrita en `reports/universal_turn_trace_contract.md`.

Alcance:

- Agregar secciones `gpt_understanding`, `gpt_proposed`, `mandatory_tool_decisions`, `atendia_validation`, `state_changes`, `business_events`, `guards`, `workflow_results`, `final_output`.
- Exponer API sin romper raw trace existente.
- Preservar tenant isolation.

Tests minimos:

- Trace muestra GPT proposed vs AtendIA validated.
- Missing mandatory tool aparece como bloqueante.
- Guard block visible.
- `final_output.final_message` proviene de `TurnOutput.final_message`.

## Prompt 5: frontend tenant-aware

Migra el frontend operativo segun `reports/frontend_operational_model.md`.

Alcance:

- Quitar aliases Dinamo hardcodeados de `ContactPanel.tsx`.
- Renderizar fields/groups desde tenant metadata.
- Crear badges de source/writer/status.
- Crear timeline de decision y cards de tools/guards.
- Incluir fixture Dinamo y fixture no-Dinamo.

Tests minimos:

- Dinamo renderiza moto/plan/cotizacion/papeleria desde metadata.
- Tenant de citas renderiza servicio/cita/disponibilidad sin campos Dinamo.
- Campo bloqueado no aparece como validado.
- Trace link abre la decision correcta.

## Prompt 6: workflow business events

Implementa eventos universales de negocio para workflows.

Alcance:

- Mapear `lead_started`, `selection_identified`, `plan_identified`, `offer_quoted`, `requirements_requested`, `requirements_complete`, `human_handoff_requested`, `policy_blocked`.
- Agregar filtros por domain, field_key, tool_id, guard_id y action status.
- Mantener side effects en dry-run sin approval.
- Agregar lint en workflow editor para loops y triggers criticos.

Tests minimos:

- `offer_quoted` dispara una vez por quote snapshot.
- `requirements_complete` no dispara sin evidence.
- Self-trigger loop bloqueado.
- Side effects quedan dry-run.

## Prompt 7: fixtures y simulacion Dinamo

Crea fixtures y tests de simulacion usando `reports/dinamo_simulation_mapped_to_universal_contract.md`.

Alcance:

- Fixture Dinamo completo.
- Fixture no-Dinamo.
- Simulacion de 6 turnos.
- Snapshots de trace, state changes, guards y workflows.
- Sin live traffic.

Tests minimos:

- Turno de cotizacion requiere catalog/plan/quote.
- Turno de buro no auto-rechaza.
- Turno de documentos sin adjunto bloquea completitud.
- Tenant no-Dinamo no usa campos ni tools Dinamo.

## Prompt 8: shadow comparison y readiness

Construye evaluacion shadow contra legacy runner sin enviar mensajes reales.

Alcance:

- Ejecutar casos fixture por legacy y runtime v2.
- Comparar final_message, state writes, guard blocks, required tools, lifecycle y workflows.
- Reportar divergencias con severidad.
- No activar canary ni single-contact live smoke.

Tests minimos:

- No live-send assertions.
- Eval produce reporte deterministico.
- Divergencias criticas bloquean readiness.
- Readiness solo puede terminar en `not_ready`, `needs_work` o `ready_for_manual_review`, no en rollout automatico.

## Prompt recomendado para continuar

Usar primero el Prompt 1: implementar mandatory tool contract.

Razon: es el control con mayor reduccion de riesgo, porque impide que precio, requisitos, documentos o politicas sensibles salgan de GPT sin tool trace confiable.

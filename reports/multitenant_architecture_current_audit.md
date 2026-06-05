# Auditoria actual de arquitectura multitenant

Fecha: 2026-06-03
Alcance: lectura de codigo y reportes existentes. No se aplico configuracion, no se activo trafico, no se enviaron mensajes reales y no se modifico runtime.

## Resumen ejecutivo

AtendIA ya tiene piezas importantes para una arquitectura universal multitenant: `agent_runtime_v2`, `TurnOutput.final_message` como autoridad unica de copy visible, herramientas que devuelven datos estructurados, `StateWriter`, lifecycle service, workflow engine, trace de turnos y paneles frontend de debug.

El riesgo principal no esta en la falta de componentes, sino en que varios contratos aun no son universales ni estan completamente conectados. Dinamo, motos, credito, documentos y reglas comerciales aparecen como supuestos en capas legacy y en presentacion de frontend. La ruta correcta es implementar primero contratos universales por tenant/domain, tool contracts obligatorios y trazas operativas, manteniendo el runner legacy como fallback hasta completar evaluacion.

Decision recomendada: `READY_FOR_UNIVERSAL_CONTRACT_IMPLEMENTATION`, empezando por `mandatory_tool_contract` y `tenant_domain_contract`.

## Componentes auditados

| Componente | Estado actual | Generalizable | Riesgo | Cambio requerido |
| --- | --- | --- | --- | --- |
| `core/atendia/agent_runtime/runtime.py` | Ejecuta turnos v2 con contexto, provider, validacion y `TurnOutput`. | Si | Medio | Conectar contratos de dominio antes de produccion universal. |
| `core/atendia/agent_runtime/schemas.py` | Define `TurnOutput`, updates, actions y prohibe copy visible en tool/action results. | Si | Bajo | Mantener `TurnOutput.final_message` como unica autoridad. |
| `core/atendia/agent_runtime/advisor_pipeline.py` | Flujo target: AdvisorBrain, ToolLayer, StateWriter, Composer, QuoteSafetyGuard, ProgressGuard. | Si | Medio | Reemplazar `NoopToolLayer` por capa real con tool contract obligatorio. |
| `core/atendia/agent_runtime/state_writer.py` | Valida cambios de estado y bloquea escrituras riesgosas. | Parcial | Medio | Parametrizar reglas por tenant/domain y evitar semantica fija de motos/credito. |
| `core/atendia/agent_runtime/quote_safety.py` | Guardia deterministica para precios/cotizaciones visibles. | Si | Medio | Convertir a patron universal de oferta/cotizacion por dominio. |
| `core/atendia/agent_runtime/context_builder.py` | Carga contexto tenant-scoped, agent config, fields y citations. | Si | Bajo | Ampliar para incluir `tenant_domain_contract`. |
| `core/atendia/agent_runtime/workflow_events.py` | Emite eventos de runtime para workflows. | Si | Medio | Agregar eventos business-domain normalizados. |
| `core/atendia/agent_runtime/post_turn_executor.py` | Ejecuta acciones post-turn en dry-run por defecto. | Si | Medio | Mantener acciones deshabilitadas hasta safety approval. |
| `core/atendia/tools/search_catalog.py` | Busca catalogo por tenant con fallback legacy. | Si | Medio | Exigir uso cuando el copy dependa de productos/servicios. |
| `core/atendia/tools/quote.py` | Resuelve cotizaciones de forma estructurada. | Si | Medio | Definir contrato universal de oferta/cotizacion y snapshots confiables. |
| `core/atendia/tools/lookup_requirements.py` | Obtiene requisitos por tenant/pipeline/selection. | Si | Bajo | Declarar como herramienta obligatoria para documentos/requisitos. |
| `core/atendia/tools/lookup_faq.py` | Responde FAQ con citas y matches. | Si | Bajo | Usar para politicas y preguntas deterministicas con trazabilidad. |
| `core/atendia/tools/vision.py` | Clasifica adjuntos con categorias tenant-configurables. | Si | Medio | Requerir evidencia de adjunto para avanzar documentos. |
| `core/atendia/runner/conversation_runner.py` | Orquestador legacy/live con muchas politicas existentes. | No como target | Alto | Mantener como fallback, no extender hardcoding. |
| `core/atendia/runner/advisor_brain.py` | Legacy advisor brain con patrones de Dinamo/credito/documentos. | No | Alto | No migrar estos supuestos al runtime v2. Extraer solo reglas a config tenant. |
| `core/atendia/runner/dinamo_agent_runtime.py` | Bridge especifico Dinamo con tenant names. | No | Alto | Retirar gradualmente despues de config universal y pruebas. |
| `core/atendia/runner/state_write_policy.py` | Legacy guard con campos protegidos como MOTO/CREDITO/ENGANCHE/FILTRO. | Parcial | Alto | Convertir a field policies declarativas por tenant/domain. |
| `core/atendia/lifecycle/service.py` | Aplica transiciones con tenant y evidencia. | Si | Bajo | Conectar motivos, source y trace al frontend. |
| `core/atendia/state_machine/pipeline_evaluator.py` | Evalua etapas por reglas configurables. | Si | Bajo | Usar como base de pipeline universal. |
| `core/atendia/workflows/engine.py` | Motor con triggers, idempotencia, self-trigger prevention y guardas. | Si | Medio | Normalizar eventos de negocio por dominio. |
| `core/atendia/db/models/turn_trace.py` | Tabla rica de trazas y side effects. | Si | Medio | Agregar vista de decision: GPT propuso vs AtendIA valido. |
| `core/atendia/observability/why_answer.py` | Explica respuesta con citations, evidence, actions y workflows. | Si | Medio | Exponer como narrativa operativa para agentes y admins. |
| `frontend/src/features/conversations/components/ContactPanel.tsx` | Panel util, pero con aliases/presentacion tipo Dinamo. | Parcial | Alto | Renderizar por tenant field metadata y evidencia. |
| `frontend/src/features/turn-traces/*` | Buen panel debug/trace generico. | Si | Medio | Mostrar propuestas, bloqueos, herramientas obligatorias y guards. |
| `frontend/src/features/workflows/components/WorkflowEditor.tsx` | Editor de workflows existente. | Si | Medio | Agregar lint de eventos criticos, loops y side effects. |

## Hallazgos de acoplamiento Dinamo/vertical

1. `core/atendia/runner/dinamo_agent_runtime.py` contiene nombres de tenant Dinamo y debe quedar como bridge/fallback temporal.
2. `core/atendia/runner/advisor_brain.py` conserva logica legacy con menu de planes, patrones de documentos, cotizacion y credito.
3. `core/atendia/runner/state_write_policy.py` protege campos con nombres de motos/credito. Es util como idea, pero no como contrato universal.
4. `core/atendia/runner/agent_final_response.py` contiene limpiadores y referencias a slots legacy como `MOTO`, `CREDITO`, `FILTRO`, `ENGANCHE`.
5. `core/atendia/state_machine/motos_credito_pipeline.json` debe tratarse como template/seed de Dinamo, no como default global.
6. `core/atendia/api/conversations_routes.py` contiene presentacion de customer fields con nombres Dinamo-ish. Esto afecta frontend y debe moverse a metadata tenant.
7. `frontend/src/features/conversations/components/ContactPanel.tsx` normaliza campos canonicos con aliases de Dinamo. Debe renderizar desde contrato de tenant.

## Fortalezas reutilizables

- `TurnOutput.final_message` ya materializa una autoridad unica para copy visible.
- Los validators de `ToolExecutionResult` y `ActionResult` bloquean mensajes visibles en resultados estructurados.
- `DeterministicStateWriter` ya separa propuestas de estado de escrituras aceptadas/bloqueadas.
- `QuoteSafetyGuard` prueba la idea correcta: hechos sensibles no se inventan, se validan contra snapshot confiable.
- `WorkflowEngine` tiene idempotencia, deteccion de loops, triggers de runtime y prevencion de auto-trigger.
- `ContactMemoryService` guarda evidencia de campos con trace, reason, confidence y status.
- `WhyAnswerService` ya agrega evidencia, actions, workflows y side effects.
- Frontend ya tiene DebugPanel y TurnTrace panels, por lo que el trabajo es extender datos y contratos, no crear desde cero.

## Brechas criticas

### 1. Contrato de dominio por tenant

Falta un objeto unico que declare, por tenant y agente, el dominio operativo: entidades, campos canonicos, pipelines, herramientas obligatorias, eventos de negocio, reglas de escritura, guardas y presentacion frontend.

### 2. Herramientas obligatorias

El sistema todavia permite que el modelo proponga respuestas sobre productos, precios, requisitos o documentos sin que siempre quede trazado que se uso la herramienta requerida.

### 3. Trazas operativas

Existe trace tecnico, pero falta una vista canonica con:

- Que entendio GPT.
- Que propuso GPT.
- Que herramientas exigio AtendIA.
- Que acepto o bloqueo AtendIA.
- Que se escribio en memoria.
- Que etapa/pipeline cambio.
- Que workflows se dispararon o quedaron bloqueados.
- Que copy final vio el cliente.

### 4. Frontend tenant-aware

El frontend debe dejar de conocer Dinamo. Debe mostrar campos, documentos, estados, eventos y explicaciones desde metadata tenant/domain.

### 5. Eventos de negocio

Los workflows soportan eventos de runtime, pero faltan nombres estables de negocio por dominio, por ejemplo `lead_started`, `selection_identified`, `offer_quoted`, `requirements_requested`, `requirements_complete`, `human_handoff_requested`.

## Recomendaciones

1. Crear `tenant_domain_contract` como autoridad declarativa.
2. Crear `mandatory_tool_contract` y conectarlo antes de cualquier rollout.
3. Extender `TurnTrace` con una narrativa universal de decision y validacion.
4. Mover presentacion de campos/documentos al contrato frontend por tenant.
5. Mantener legacy runner como fallback hasta evaluacion comparativa.
6. Probar primero con fixtures/simulaciones, no trafico real.
7. Para Dinamo, generar propuesta de configuracion tenant-scoped, sin aplicar.

## Decision final de auditoria

`READY_FOR_UNIVERSAL_CONTRACT_IMPLEMENTATION`

La implementacion no debe empezar por reescribir prompts ni por activar Dinamo en vivo. Debe empezar por contratos verificables: herramientas obligatorias, dominio tenant, state writer declarativo, trazas y frontend operativo.

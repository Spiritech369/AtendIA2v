# Agent-First Checkpoint - 2026-05-31

## Scope

Checkpoint técnico de lo implementado hasta ahora para la frontera Agent-First:

- `agent_runtime_v2`
- Knowledge OS v2
- Agent Studio backend y test endpoints
- Contact Memory v2
- Lifecycle v2
- Action Registry / PostTurnActionExecutor
- Eval Lab v1
- Blueprint System v1
- Onboarding Wizard v1

No se revisa como terminado el reemplazo del `ConversationRunner` legacy. El
camino productivo automático sigue siendo legacy salvo endpoints internos/manuales.

## Estado Por Módulo

| Módulo | Hecho | Parcial | Stub | Falta | Riesgo |
| --- | --- | --- | --- | --- | --- |
| AgentRuntime v2 | `TurnOutput`, `TurnContext`, provider interface, mock/fallback/OpenAI opcional, `PolicyValidator`, trace metadata. | Integración manual con conversación real por preview/send. | Provider fallback seguro cuando LLM falla. | Sustituir runner automático, evaluación tenant-level antes de auto-send. | Dos caminos vivos: legacy productivo y v2 manual. |
| Knowledge OS v2 | Modelos `KnowledgeSource/Item/Chunk/RetrievalLog`, ingestion manual/text/FAQ/CSV/file parsers, retrieval textual, citations/source cards. | Integrado con `ContextBuilder` cuando hay provider. | URL/OCR/crawler y conflictos reales. | Vector/híbrido real, freshness, permisos finos, adapters completos legacy. | Docs iniciales quedaron algo atrás: ahora hay parsers PDF/DOCX/XLSX aunque `knowledge_os_v2.md` todavía dice TODO. |
| Agent Studio backend | Config v2 en agentes: instrucciones, tono, language policy, knowledge sources, actions, visible fields, lifecycle allowed. Endpoints de recursos. | Persistido en campos existentes (`ops_config`, `knowledge_config`, etc.). | No hay UI completa en este checkpoint. | API dedicada de blueprints/onboarding hacia Studio UX. | Validación depende de recursos existentes y puede dejar configs legacy ambiguas. |
| Agent test endpoints | `POST /api/v1/agents/{agent_id}/test-turn-v2`, dry-run, citations/debug/policy. | Test chat frontend mínimo existe en repo. | Eval Lab visual no existe. | Persistir resultado de test aprobado hacia onboarding automáticamente. | Test pass hoy puede marcarse manualmente por onboarding. |
| Conversation preview/send v2 | `POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/preview` y `/send`, admin-only, flags, outbox, trace. | Manual experimental. | Actions dry-run por default; workflow events off por default. | No reemplaza webhooks/runner. | Ruta productiva tocada: `conversations_routes.py` ahora contiene un camino real de send detrás de flags. |
| Contact Memory v2 | Policy service, evidence model, write policy (`ai_auto`, `ai_suggest`, `human_only`), audit evidence. | `PostTurnActionExecutor` puede aplicar field updates. | UI review/approval no completa. | Confirmación humana y reversión operacional completa. | Auto-write debe mantenerse detrás de policy estricta; tests cubren base, no todos los tipos de campo. |
| Lifecycle v2 | Adapter sobre pipeline, schemas, service, stage history, action `move_lifecycle`. | No reescribe state machine. | SLA/automation policy no ejecuta. | Migración completa desde pipeline legacy. | Doble semántica stage/pipeline/lifecycle hasta completar migración. |
| Action Registry | Acciones conocidas, rechazo de desconocidas, no-copy visible, dry-run, audit log. | Handlers reales mínimos: contact field, lifecycle, tags, assign, close, workflow row. | `call_webhook` seguro; workflow enqueue worker P2. | Appointment/estimate/media/document actions. | `trigger_workflow` puede crear execution row; side effects mayores deben seguir controlados por flags y approval. |
| Workflow events v2 | Eventos `agent_*`, trigger registry, conditions por confidence/action/field/lifecycle/risk. | Preview devuelve eventos simulados; send puede emitir reales con flag. | No canvas UX. | Loop prevention formal agent->workflow->agent. | Si se activa `AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED`, workflows existentes podrían producir side effects. |
| Eval Lab v1 | Scenarios, deterministic scorers, fixture provider, CLI/module runner. | Blueprints de escenarios iniciales. | Sin juez LLM. | Dataset tenant-specific, reporting histórico, UI. | Scorers deterministas no miden calidad semántica profunda. |
| Blueprints v1 | JSON declarativo, schemas, service, install idempotente: fields, lifecycle, agent base, audit, eval scenarios. | Sin endpoints públicos propios todavía. | Workflow templates inactivos; Knowledge templates como categorías. | UI/API admin dedicada, versioning, upgrade/diff. | Verticalidad vive correctamente en JSON/eval; legacy todavía contiene verticales antiguas fuera de esta frontera. |
| Onboarding v1 | `onboarding_states`, endpoints state/select/mark/validate/readiness, Blueprint integration. | Validación conservadora con signals reales. | Channel Meta freshness parcial; test_passed manual. | UI wizard, auto-update desde test chat, publish real. | Readiness no publica, correcto; pero puede ser confundido como release gate completo si no se comunica. |

## Riesgos De Arquitectura

### Multiples Autoridades De Respuesta

Estado: riesgo medio-alto.

El objetivo de v2 es que solo `TurnOutput.final_message` sea copy visible. Eso
está protegido dentro de `agent_runtime_v2`, pero producción todavía conserva
capas legacy capaces de decidir/redactar:

- `conversation_runner`
- composer/response frame/response contract
- tools legacy
- advisor brain / policies legacy

Mitigación actual: v2 no reemplaza el runner por default y los endpoints reales
son manuales y flaggeados.

Deuda: definir el primer tenant/canal donde el webhook automático pase por v2
solo después de evals y shadow-mode.

### Acciones Que Escriben Copy Visible

Estado: riesgo bajo dentro de v2, medio en legacy.

V2 tiene barreras:

- `ActionResult.data` rechaza keys visibles como `final_message`, `message`,
  `reply`, `text`, `visible_text`.
- `PolicyValidator` bloquea payloads de actions con keys visibles.
- `PostTurnActionExecutor` no envía mensajes.

Riesgo restante: workflows legacy sí tienen nodos `message/template_message`.
Por eso workflow events reales están apagados por default.

### Tenant Isolation

Estado: razonable, requiere pruebas integradas mayores.

Cubierto por tests focales en Agent Studio, Knowledge OS, actions, lifecycle,
conversation preview, blueprints y onboarding. Falta una matriz e2e que combine:

- tenant A con blueprint + knowledge + workflow
- tenant B con configuración similar
- preview/send/action/workflow events en paralelo

### Flags Peligrosos

Flags actuales:

- `ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=false`
- `ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER=disabled`

Riesgo: si se activan varios a la vez en producción sin tenant allowlist,
podría haber envío real + acciones reales + workflow side effects. Falta un
feature gate por tenant/agente además de env flags globales.

### Rutas Productivas Tocadas

Estado: controlado, pero importante.

Rutas nuevas o extendidas relevantes:

- `/api/v1/agents/{agent_id}/test-turn-v2`
- `/api/v1/conversations/{conversation_id}/agent-runtime-v2/preview`
- `/api/v1/conversations/{conversation_id}/agent-runtime-v2/send`
- `/api/v1/onboarding/*`
- Agent Studio resource/config endpoints

`send` reutiliza outbox, no canal directo, pero vive dentro de
`conversations_routes.py`. Debe mantenerse admin-only y flaggeado.

### Hardcode Vertical

Estado: limpio dentro de `agent_runtime_v2`; no limpio en legacy.

La búsqueda muestra verticalidad en:

- `core/atendia/blueprints/definitions/*.json` - esperado.
- `core/atendia/eval_lab/fixtures.py` - esperado para escenarios.
- legacy fuera del scope Agent-First todavía contiene referencias Dinamo/motos/crédito.

Riesgo: si el prompt base o runtime empieza a absorber verticales desde legacy,
se rompe el objetivo generalista.

### Tests Debiles

Estado: buena base focal, falta hardening.

Hay muchas suites pequeñas por módulo. Faltan:

- e2e completo real de v2 con DB + knowledge + action + trace + outbox;
- tests de concurrencia/idempotencia para onboarding/blueprint install;
- shadow-run contra conversaciones reales sin envío;
- matriz de flags globales y futuros flags por tenant;
- tests con provider OpenAI mockeando JSON inválido, timeout y repair path en rutas reales;
- migration roundtrip incluyendo las últimas migraciones v2.

### Dependencia Del Runner Legacy

Estado: intencional, pero deuda P0 antes de producción v2.

Inbound automático sigue legacy. V2 depende de modelos legacy para:

- conversations/messages/customers;
- outbox;
- tenant pipeline;
- legacy KB adapters en algunas rutas;
- auth/session/permisos existentes.

Esto es correcto para migrar, pero todavía no hay un "v2 automatic runner" con
rollback por tenant.

## Mapa De Flujo Real

### Producción Automática Actual

```text
Inbound WhatsApp/webhook
  -> ConversationRunner legacy
  -> legacy decision/composer/tools/state machine
  -> outbound/outbox
```

AgentRuntime v2 no toma este camino por default.

### Agent Test Turn v2

```text
POST /api/v1/agents/{agent_id}/test-turn-v2
  -> carga Agent Studio config
  -> ContextBuilder
  -> Knowledge provider/retrieval si aplica
  -> AgentRuntime
  -> provider mock/fallback/OpenAI opcional
  -> TurnOutput
  -> PolicyValidator
  -> response con citations/debug
  -> sin mensajes reales, sin customer writes, sin lifecycle real, sin actions reales
```

### Conversation Preview v2

```text
POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/preview
  -> carga conversation real tenant-scoped
  -> ContextBuilder(session, KnowledgeRetrievalService)
  -> AgentRuntime
  -> Knowledge citations en context/output
  -> PolicyValidator
  -> TurnTrace
  -> workflow events simulados en debug
  -> response TurnOutput-like
  -> no outbox, no WhatsApp, no actions reales
```

### Conversation Send v2 Manual

```text
POST /api/v1/conversations/{conversation_id}/agent-runtime-v2/send
  -> requiere AGENT_RUNTIME_V2_ENABLED=true
  -> requiere AGENT_RUNTIME_V2_SEND_ENABLED=true
  -> valida conversación activa, no pausada, handoff cerrado, ventana WhatsApp
  -> ContextBuilder
  -> AgentRuntime
  -> Knowledge retrieval
  -> PolicyValidator
  -> PostTurnActionExecutor
       -> dry-run salvo AGENT_RUNTIME_V2_ACTIONS_ENABLED=true
       -> ContactMemoryService/LifecycleService/etc. si enabled
  -> workflow events
       -> simulados salvo AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED=true
  -> stage_outbound(outbox)
  -> MessageRow queued
  -> TurnTrace
```

## Tests

### Suites Existentes

- `tests/agent_runtime/test_agent_runtime_v2.py`
- `tests/agent_runtime/test_action_layer_v2.py`
- `tests/agent_runtime/test_agent_model_provider_v2.py`
- `tests/agent_runtime/test_workflow_events.py`
- `tests/knowledge_os/test_knowledge_os_v2.py`
- `tests/knowledge_os/test_knowledge_ingestion_files_v2.py`
- `tests/api/test_agent_test_turn_v2.py`
- `tests/api/test_agent_studio_v2_backend.py`
- `tests/api/test_agent_runtime_v2_conversation_preview.py`
- `tests/contact_memory/test_contact_memory_v2.py`
- `tests/lifecycle/test_lifecycle_v2.py`
- `tests/eval_lab/test_eval_lab_v1.py`
- `tests/blueprints/test_blueprint_system_v1.py`
- `tests/api/test_onboarding_v1.py`
- `tests/workflows/test_agent_runtime_event_triggers_v2.py`
- DB/migration tests parciales: `tests/db/test_migration_058.py`, etc.

### Que Cubren

- Contrato `TurnOutput` y policy validator.
- Unknown actions y no visible copy desde actions.
- Dry-run/real handlers mínimos.
- Knowledge tenant isolation, retrieval y citations.
- File parsers básicos.
- Agent Studio tenant isolation/config filtering.
- Test chat sin side effects.
- Conversation preview/send manual con flags.
- Contact Memory write policies.
- Lifecycle stage validation/history.
- Workflow agent events y trigger matching.
- Eval scorers deterministas.
- Blueprints list/validate/install/idempotencia/isolation.
- Onboarding state/select/validate/readiness/isolation.

### Que No Cubren

- Webhook inbound automático usando v2.
- Multi-tenant e2e completo con send/actions/workflow events reales activados.
- Load/concurrency/idempotencia bajo dos installs simultáneos.
- UI Agent Test Chat/Onboarding integrado con backend real.
- Provider real con red/API externa.
- Seguridad completa de workflow side effects si se activa workflow events.
- Full migration chain desde base limpia en este checkpoint.

### Comando Recomendado

```powershell
cd core
uv run pytest `
  tests/agent_runtime `
  tests/knowledge_os `
  tests/contact_memory `
  tests/lifecycle `
  tests/eval_lab `
  tests/blueprints `
  tests/api/test_agent_test_turn_v2.py `
  tests/api/test_agent_studio_v2_backend.py `
  tests/api/test_agent_runtime_v2_conversation_preview.py `
  tests/api/test_onboarding_v1.py `
  tests/workflows/test_agent_runtime_event_triggers_v2.py `
  tests/test_config.py
```

Para migraciones:

```powershell
cd core
uv run alembic upgrade head
uv run pytest tests/db
```

## Deuda Antes De Produccion

### P0

- Tenant-level feature gates, no solo env flags globales, para runtime v2,
  send, actions, workflow events y model provider.
- Shadow mode automático: ejecutar v2 junto al runner legacy sin enviar ni
  escribir, persistiendo trace/eval.
- Production readiness gate: no permitir `send` si no hay eval suite mínima
  pasada para tenant/agente.
- Revisar workflow side effects antes de activar workflow events reales.
- End-to-end test: real conversation -> v2 preview -> policy -> trace -> outbox
  con actions dry-run y tenant isolation.
- Actualizar docs de Knowledge OS para reflejar ingestion PDF/DOCX/XLSX ya
  implementada.

### P1

- Onboarding debe consumir automáticamente resultado de Agent Test Chat/Eval Lab
  para `test_passed`.
- UI/API admin para Blueprints list/preview/install; ahora existe service, no
  endpoint dedicado.
- KnowledgeSource templates desde blueprint categories.
- Workflow templates como draft rows, nunca active por default.
- Migration roundtrip de las últimas tablas (`action_execution_logs`,
  `onboarding_states`, etc.).
- Observabilidad unificada: TurnTrace + ActionExecutionLog + WorkflowEvent +
  Onboarding validation report.
- Eval scenarios por blueprint conectados a tenant configs reales.

### P2

- Vector/hybrid retrieval real en Knowledge OS.
- Conflict detection y source freshness.
- OCR/crawler/web ingestion.
- More actions: appointments, estimates, media, documents, tasks.
- Full Eval Lab UI.
- Blueprint versioning, diff, upgrade and rollback.
- Onboarding publish flow real con approval/audit.

## Fixes En Este Checkpoint

No se hicieron fixes de código en este checkpoint. No detecté un bug crítico
que ameritara un diff pequeño inmediato; sí detecté deuda documental y de
feature-gating que debe resolverse antes de producción.

## Recomendacion Del Siguiente Task

Siguiente task recomendado: implementar **tenant-level AgentRuntime v2 rollout
controls + shadow mode**.

Prompt sugerido:

```text
Implementa rollout controls por tenant/agente para AgentRuntime v2.

Objetivo:
Reemplazar los flags globales como único control con una capa tenant-scoped:
- runtime_v2_enabled
- shadow_mode_enabled
- send_enabled
- actions_enabled
- workflow_events_enabled
- model_provider_enabled
- allowed_agent_ids
- required_eval_suite_passed

Alcance:
1. Crear modelo/config tenant-scoped o extender tenant capabilities.
2. Agregar servicio RolloutPolicyService.
3. Integrar conversation preview/send y test-turn-v2 con esa policy.
4. Agregar shadow endpoint/path que ejecute v2 sobre conversaciones reales sin enviar ni escribir.
5. Persistir TurnTrace shadow con comparison contra legacy si está disponible.
6. Tests de tenant isolation, flags globales + tenant flags, send bloqueado sin eval, shadow sin side effects.
7. Documentar docs/architecture/agent_runtime_v2_rollout.md.

Restricciones:
- No reemplazar webhook runner todavía.
- No activar send/actions/workflow events por default.
- No permitir flags globales como bypass de tenant policy.
```

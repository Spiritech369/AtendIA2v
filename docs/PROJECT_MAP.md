# AtendIA v2 — Mapa del proyecto

> **Propósito:** índice rápido de "qué hace cada parte del programa y dónde vive el código". Una fila por categoría, agrupadas por área.

| Convención | Significado |
|---|---|
| **Backend** | rutas en `core/atendia/api/<feature>_routes.py`, modelos en `core/atendia/db/models/`, jobs en `core/atendia/queue/` |
| **Frontend** | rutas en `frontend/src/routes/(auth)/<page>.tsx`, código en `frontend/src/features/<feature>/` |
| **Estado** | ✅ vivo · ⚠️ parcial · 🔴 deferred · 📦 librería interna (no UI) |

---

## 1. Auth, multi-tenancy y RBAC

| Categoría | Propósito | Backend | Frontend | Estado |
|---|---|---|---|---|
| **Auth / sesiones** | Login operador, JWT en cookie httponly + CSRF token, revocación por jti, 3 roles (`operator` / `tenant_admin` / `superadmin`). | [api/auth_routes.py](../core/atendia/api/auth_routes.py) · [api/_auth_helpers.py](../core/atendia/api/_auth_helpers.py) · [api/_csrf.py](../core/atendia/api/_csrf.py) · [api/_deps.py](../core/atendia/api/_deps.py) | [routes/login.tsx](../frontend/src/routes/login.tsx) · [routes/(auth)/route.tsx](../frontend/src/routes/(auth)/route.tsx) | ✅ |
| **Tenants** | Multi-tenancy. Cada fila aislada por `tenant_id`. Superadmin puede impersonar para soporte. | [api/tenants_routes.py](../core/atendia/api/tenants_routes.py) · [db/models/tenant.py](../core/atendia/db/models/tenant.py) | (impersonation via header) | ✅ |
| **Users** | Operadores del tenant: alta, baja, cambio de rol, password reset. | [api/users_routes.py](../core/atendia/api/users_routes.py) · [db/models/tenant.py](../core/atendia/db/models/tenant.py) | [features/users/components/UsersPage.tsx](../frontend/src/features/users/components/UsersPage.tsx) | ✅ |
| **Audit log** | Registro de toda acción admin (`emit_admin_event`). Lectura paginada filtrable por actor / acción / tenant. | [api/audit_log_routes.py](../core/atendia/api/audit_log_routes.py) · [api/_audit.py](../core/atendia/api/_audit.py) · [db/models/event.py](../core/atendia/db/models/event.py) | [routes/(auth)/audit-log.tsx](../frontend/src/routes/(auth)/audit-log.tsx) | ✅ |

---

## 2. Núcleo conversacional (motor del bot)

| Categoría | Propósito | Código | Estado |
|---|---|---|---|
| **State machine** | Orquestador determinístico parametrizado por `tenant_pipelines.definition` JSONB. Decide stage/action por turno. | [state_machine/orchestrator.py](../core/atendia/state_machine/orchestrator.py) · [state_machine/pipeline_loader.py](../core/atendia/state_machine/pipeline_loader.py) · [state_machine/conditions.py](../core/atendia/state_machine/conditions.py) · [state_machine/transitioner.py](../core/atendia/state_machine/transitioner.py) · [state_machine/action_resolver.py](../core/atendia/state_machine/action_resolver.py) | ✅ |
| **NLU** | Clasifica intent + entidades + confianza. Provider switchable: `keyword` (default) o `openai` (`gpt-4o-mini` con structured outputs). | [runner/nlu_keywords.py](../core/atendia/runner/nlu_keywords.py) · [runner/nlu_openai.py](../core/atendia/runner/nlu_openai.py) · [runner/nlu_canned.py](../core/atendia/runner/nlu_canned.py) · [runner/nlu_protocol.py](../core/atendia/runner/nlu_protocol.py) · [runner/nlu_prompts.py](../core/atendia/runner/nlu_prompts.py) | ✅ |
| **Composer** | Genera el texto de salida (`list[str]`, 1-3 mensajes). Provider switchable: `canned` o `openai` (`gpt-4o`). Aplica tono per-tenant + escalación si fuera de ventana 24h. | [runner/composer_openai.py](../core/atendia/runner/composer_openai.py) · [runner/composer_canned.py](../core/atendia/runner/composer_canned.py) · [runner/composer_prompts.py](../core/atendia/runner/composer_prompts.py) · [runner/composer_protocol.py](../core/atendia/runner/composer_protocol.py) | ✅ |
| **Flow router** | Elige uno de 6 modos por turno (PLAN / SALES / DOC / OBSTACLE / RETENTION / SUPPORT) según `flow_mode_rules` per-tenant. | [runner/flow_router.py](../core/atendia/runner/flow_router.py) | ✅ |
| **Conversation runner** | Compone state machine + NLU + Composer + Tools en un único `run_turn()`. Persiste `turn_traces` y emite eventos. | [runner/conversation_runner.py](../core/atendia/runner/conversation_runner.py) · [api/runner_routes.py](../core/atendia/api/runner_routes.py) | ✅ |
| **Tools** | Acciones tipadas que el orquestrador ejecuta: cotizar, buscar catálogo, FAQ, agendar cita, escalar, programar follow-up, vision. | [tools/quote.py](../core/atendia/tools/quote.py) · [tools/search_catalog.py](../core/atendia/tools/search_catalog.py) · [tools/lookup_faq.py](../core/atendia/tools/lookup_faq.py) · [tools/book_appointment.py](../core/atendia/tools/book_appointment.py) · [tools/escalate.py](../core/atendia/tools/escalate.py) · [tools/followup.py](../core/atendia/tools/followup.py) · [tools/vision.py](../core/atendia/tools/vision.py) · [tools/embeddings.py](../core/atendia/tools/embeddings.py) | ✅ |
| **Webhooks (Meta)** | Recibe mensajes inbound de WhatsApp Cloud API: HMAC verify → dedupe → persist → run turn → publish event. | [webhooks/meta_routes.py](../core/atendia/webhooks/meta_routes.py) · [channels/meta_cloud_api.py](../core/atendia/channels/meta_cloud_api.py) · [channels/meta_signing.py](../core/atendia/channels/meta_signing.py) · [channels/meta_dto.py](../core/atendia/channels/meta_dto.py) | ✅ |
| **Outbound queue + worker** | Cola arq con idempotency-by-key, retries, circuit breaker. El worker llama a Meta y persiste outbound. | [queue/enqueue.py](../core/atendia/queue/enqueue.py) · [queue/outbox.py](../core/atendia/queue/outbox.py) · [queue/worker.py](../core/atendia/queue/worker.py) · [queue/circuit_breaker.py](../core/atendia/queue/circuit_breaker.py) · [runner/outbound_dispatcher.py](../core/atendia/runner/outbound_dispatcher.py) | ✅ |
| **Follow-ups (in-window)** | Recordatorios 3h + 12h tras cada outbound. Cancelación atómica al recibir un inbound. Quiet hours UTC. | [runner/followup_scheduler.py](../core/atendia/runner/followup_scheduler.py) · [queue/followup_worker.py](../core/atendia/queue/followup_worker.py) · [db/models/lifecycle.py](../core/atendia/db/models/lifecycle.py) | ✅ |
| **Realtime / WebSocket** | Pub/Sub Redis + WS per-conversation con JWT signed. Frontend suscribe a `message_received` / `message_sent` / etc. | [realtime/publisher.py](../core/atendia/realtime/publisher.py) · [realtime/ws_routes.py](../core/atendia/realtime/ws_routes.py) · [realtime/auth.py](../core/atendia/realtime/auth.py) | ✅ |

---

## 3. Workspace del operador (frontend)

| Categoría | Propósito | Backend | Frontend | Estado |
|---|---|---|---|---|
| **Dashboard** | KPIs del día (citas hoy, conversaciones activas, follow-ups pending, etc.). | [api/dashboard_routes.py](../core/atendia/api/dashboard_routes.py) | [features/dashboard/components/DashboardPage.tsx](../frontend/src/features/dashboard/components/DashboardPage.tsx) · [routes/(auth)/dashboard.tsx](../frontend/src/routes/(auth)/dashboard.tsx) | ✅ |
| **Conversations** | Bandeja de conversaciones con detalle, chat window, contact panel, debug panel. Listado real-time vía WS. | [api/conversations_routes.py](../core/atendia/api/conversations_routes.py) · [db/models/conversation.py](../core/atendia/db/models/conversation.py) · [db/models/message.py](../core/atendia/db/models/message.py) | [features/conversations/components/](../frontend/src/features/conversations/components/) · [routes/(auth)/conversations.$conversationId.tsx](../frontend/src/routes/(auth)/conversations.$conversationId.tsx) | ✅ (v1 parity scaffolded) |
| **Customers** | CRM ligero: ficha, búsqueda, import CSV, custom fields, notas. | [api/customers_routes.py](../core/atendia/api/customers_routes.py) · [api/customer_fields_routes.py](../core/atendia/api/customer_fields_routes.py) · [api/customer_notes_routes.py](../core/atendia/api/customer_notes_routes.py) · [db/models/customer.py](../core/atendia/db/models/customer.py) · [db/models/customer_fields.py](../core/atendia/db/models/customer_fields.py) · [db/models/customer_note.py](../core/atendia/db/models/customer_note.py) | [features/customers/components/](../frontend/src/features/customers/components/) · [routes/(auth)/customers.tsx](../frontend/src/routes/(auth)/customers.tsx) · [routes/(auth)/customers.$customerId.tsx](../frontend/src/routes/(auth)/customers.$customerId.tsx) | ✅ |
| **Pipeline (Kanban)** | Vista kanban de conversaciones por etapa de venta. Drag-drop entre columnas. | [api/pipeline_routes.py](../core/atendia/api/pipeline_routes.py) | [features/pipeline/components/PipelineKanbanPage.tsx](../frontend/src/features/pipeline/components/PipelineKanbanPage.tsx) · [routes/(auth)/pipeline.tsx](../frontend/src/routes/(auth)/pipeline.tsx) | ✅ |
| **Handoffs** | Cola de escalaciones a humano. El operador toma control y devuelve al bot. | [api/handoffs_routes.py](../core/atendia/api/handoffs_routes.py) · [db/models/lifecycle.py](../core/atendia/db/models/lifecycle.py) | [features/handoffs/components/](../frontend/src/features/handoffs/components/) · [routes/(auth)/handoffs.tsx](../frontend/src/routes/(auth)/handoffs.tsx) | ✅ |
| **Appointments** | Calendario de citas, slots, recordatorios. | [api/appointments_routes.py](../core/atendia/api/appointments_routes.py) · [db/models/appointment.py](../core/atendia/db/models/appointment.py) | [features/appointments/components/AppointmentsPage.tsx](../frontend/src/features/appointments/components/AppointmentsPage.tsx) · [routes/(auth)/appointments.tsx](../frontend/src/routes/(auth)/appointments.tsx) | ✅ (Module 4) |
| **Notifications** | Campana en navbar. Toasts via sonner. Read/unread tracking per-user. | [api/notifications_routes.py](../core/atendia/api/notifications_routes.py) · [db/models/notification.py](../core/atendia/db/models/notification.py) | [features/notifications/](../frontend/src/features/notifications/) | ✅ |
| **Inbox settings** | Configuración de la bandeja: layout, filtros, reglas de handoff, permisos. 3-panel UI con preview en vivo. | [api/tenants_routes.py](../core/atendia/api/tenants_routes.py) (`GET/PUT /tenants/inbox-config`) | [features/inbox-settings/components/](../frontend/src/features/inbox-settings/components/) · [routes/(auth)/inbox-settings.tsx](../frontend/src/routes/(auth)/inbox-settings.tsx) | ✅ |

---

## 4. Configuración del bot

| Categoría | Propósito | Backend | Frontend | Estado |
|---|---|---|---|---|
| **Pipeline editor** | Editar el JSONB `tenant_pipelines.definition` (stages, transitions, flow_mode_rules, docs_per_plan, brand_facts). | [api/pipeline_routes.py](../core/atendia/api/pipeline_routes.py) · [db/models/tenant_config.py](../core/atendia/db/models/tenant_config.py) | [features/config/components/PipelineEditor.tsx](../frontend/src/features/config/components/PipelineEditor.tsx) · [features/config/components/BrandFactsEditor.tsx](../frontend/src/features/config/components/BrandFactsEditor.tsx) · [features/config/components/ToneEditor.tsx](../frontend/src/features/config/components/ToneEditor.tsx) · [routes/(auth)/config.tsx](../frontend/src/routes/(auth)/config.tsx) | ✅ |
| **Agents** | Perfiles de los 4 agentes del bot (recepcionista / sales_agent / duda_general / postventa) con tono, nombre, límites. | [api/agents_routes.py](../core/atendia/api/agents_routes.py) · [db/models/agent.py](../core/atendia/db/models/agent.py) | [features/agents/components/AgentsPage.tsx](../frontend/src/features/agents/components/AgentsPage.tsx) · [routes/(auth)/agents.tsx](../frontend/src/routes/(auth)/agents.tsx) | ✅ |
| **Workflows** | Engine tipo Zapier: triggers (event types) → conditions → actions. Editor visual + form editor. | [api/workflows_routes.py](../core/atendia/api/workflows_routes.py) · [db/models/workflow.py](../core/atendia/db/models/workflow.py) · [queue/workflow_jobs.py](../core/atendia/queue/workflow_jobs.py) | [features/workflows/components/WorkflowEditor.tsx](../frontend/src/features/workflows/components/WorkflowEditor.tsx) · [features/workflows/components/WorkflowsPage.tsx](../frontend/src/features/workflows/components/WorkflowsPage.tsx) · [routes/(auth)/workflows.tsx](../frontend/src/routes/(auth)/workflows.tsx) | ✅ scaffolded (form editor pendiente full visual) |
| **Integrations** | Status WhatsApp/Meta (conectado / reconectando / pausado). Lectura de circuit breaker. | [api/channel_status_routes.py](../core/atendia/api/channel_status_routes.py) · [api/integrations_routes.py](../core/atendia/api/integrations_routes.py) | [features/config/components/IntegrationsTab.tsx](../frontend/src/features/config/components/IntegrationsTab.tsx) | ✅ |

---

## 5. Knowledge Base (módulo B2 — actualmente parcial)

| Categoría | Propósito | Backend | Frontend | Estado |
|---|---|---|---|---|
| **Knowledge Base — backend foundation** | RAG pipeline: 11 tablas (collections, versions, conflicts, unanswered, test_cases, test_runs, health_snapshots, agent_permissions, source_priority_rules, safe_answer_settings) + extends FAQs/Catalog/Documents/Chunks. Provider abstraction (OpenAI + Mock). Retriever agent-scoped. Prompt builder con safety block. Answer synthesizer con árbol de decisión por confianza. | [api/knowledge_routes.py](../core/atendia/api/knowledge_routes.py) · [api/_kb/](../core/atendia/api/_kb/) (search, test_query, collections) · [tools/rag/](../core/atendia/tools/rag/) (provider, mock_provider, openai_provider, retriever, prompt_builder, answer_synthesizer, conflict_detector, risky_phrase_detector) · [db/models/kb_*.py](../core/atendia/db/models/) (10 archivos) · [scripts/seed_knowledge_defaults.py](../core/atendia/scripts/seed_knowledge_defaults.py) · [queue/index_document_job.py](../core/atendia/queue/index_document_job.py) | [features/knowledge/components/KnowledgeBasePage.tsx](../frontend/src/features/knowledge/components/KnowledgeBasePage.tsx) (4 tabs legacy) · [routes/(auth)/knowledge.tsx](../frontend/src/routes/(auth)/knowledge.tsx) | ⚠️ **B2 parcial** — backend Phase 1+2 completos, 3 endpoints (search/test-query/collections), runbook en [docs/runbooks/knowledge-base.md](runbooks/knowledge-base.md), frontend rebuild deferred |
| **Knowledge Base — endpoints diferidos** | FAQ/Catalog publish/archive, Catalog import (CSV/XLSX), Document parse/chunk/embed/reindex/archive per-doc, Chunks list/patch/exclude/include/re-embed, Conflicts CRUD + detect, Unanswered queue + create-FAQ, Tests CRUD + run + run-suite, Versions list + restore, Health snapshot + worker daily, Analytics (4), Settings (3 sub-areas). | (no implementado) | (no implementado) | 🔴 deferred |
| **Knowledge Base — workers diferidos** | `detect_conflicts` · `compute_health_snapshot` (cron daily) · `expire_content` (cron hourly) · `run_regression_suite` · `import_catalog_csv`. | (no implementado) | n/a | 🔴 deferred |
| **Knowledge Base — frontend rebuild diferido** | 8 tabs (FAQs/Catálogo/Artículos/Documentos/Sin respuesta/Conflictos/Pruebas/Métricas) · PromptPreviewDrawer · ChunkEditorDrawer · BulkActionsBar · Cmd+K palette · HealthScoreCard · SafeAnswerModeCard · StatsTilesRow · ~35 componentes · 13 dialogs. | n/a | (no implementado) | 🔴 deferred — el `KnowledgeBasePage.tsx` actual de 4 tabs sigue funcionando |

---

## 6. Observabilidad y debugging

| Categoría | Propósito | Backend | Frontend | Estado |
|---|---|---|---|---|
| **Turn traces** | Una fila por turno con NLU input/output, composer input/output, tool calls, latencias, costos. Debugger per-mensaje. | [api/turn_traces_routes.py](../core/atendia/api/turn_traces_routes.py) · [db/models/turn_trace.py](../core/atendia/db/models/turn_trace.py) | [features/turn-traces/components/TurnTraceInspector.tsx](../frontend/src/features/turn-traces/components/TurnTraceInspector.tsx) · [features/turn-traces/components/TurnTraceList.tsx](../frontend/src/features/turn-traces/components/TurnTraceList.tsx) · [routes/(auth)/turn-traces.tsx](../frontend/src/routes/(auth)/turn-traces.tsx) | ✅ (v2: 5 tabs JSON dump; "DebugPanel rich" pendiente — ver [docs/handoffs/v1-v2-conversations-gap.md](handoffs/v1-v2-conversations-gap.md) §6) |
| **Analytics** | Dashboards de métricas: volumen, conversión, tiempo de respuesta, costos LLM. | [api/analytics_routes.py](../core/atendia/api/analytics_routes.py) | [features/analytics/components/AnalyticsDashboard.tsx](../frontend/src/features/analytics/components/AnalyticsDashboard.tsx) · [routes/(auth)/analytics.tsx](../frontend/src/routes/(auth)/analytics.tsx) | ✅ scaffolded |
| **Exports** | Bulk export CSV de conversaciones / clientes / mensajes. | [api/exports_routes.py](../core/atendia/api/exports_routes.py) | [routes/(auth)/exports.tsx](../frontend/src/routes/(auth)/exports.tsx) | ✅ |

---

## 7. Infraestructura compartida (no UI)

| Categoría | Propósito | Código | Estado |
|---|---|---|---|
| **DB / migrations** | Postgres + pgvector + halfvec(3072) HNSW. Alembic async, hex-hash revisions, numeric file prefix. 36 migrations a la fecha. | [db/base.py](../core/atendia/db/base.py) · [db/session.py](../core/atendia/db/session.py) · [db/migrations/versions/](../core/atendia/db/migrations/versions/) · [alembic.ini](../core/alembic.ini) | ✅ |
| **Storage backend** | Abstracción para uploads (FAQs/catalog/docs/imports). Tier `local` por ahora; cloud-blob es follow-up. | [storage/](../core/atendia/storage/) | ✅ tier `local` |
| **Contracts (JSON Schema)** | Source of truth para shapes inter-servicio (`Event`, `Message`, `NLUResult`, `PipelineDefinition`). Test gating valida que Pydantic ↔ canonical JSON no diverjan. | [contracts/](../contracts/) (JSON) · [core/atendia/contracts/](../core/atendia/contracts/) (Pydantic) · [tests/contracts/test_schema_consistency.py](../core/tests/contracts/test_schema_consistency.py) | ✅ |
| **Realtime helpers (frontend)** | Hook `useTenantStream` que invalida queries TanStack al recibir eventos del WS. | [src/lib/realtime/](../frontend/src/lib/realtime/) | ✅ |
| **shadcn vendored** | Componentes UI base (Button, Dialog, Sheet, etc.) generados con shadcn CLI, vendoreados en repo. | [src/components/ui/](../frontend/src/components/ui/) | ✅ |
| **Seed scripts / scripts CLI** | Scripts ad-hoc: ingest Dinamo, seed brand_facts, seed KB defaults, smoke tests. | [scripts/](../core/scripts/) · [atendia/scripts/](../core/atendia/scripts/) | ✅ |

---

## 8. Documentación y guías operativas

| Documento | Propósito | Ruta |
|---|---|---|
| **Architecture** | Visión técnica general (state machine, transport, queue, realtime). | [docs/design/atendia-v2-architecture.md](design/atendia-v2-architecture.md) |
| **V1 → V2 parity roadmap** | Inventario de los 10 módulos del sprint v1-parity con status por módulo. | [docs/plans/2026-05-08-v1-parity-modular-plan.md](plans/2026-05-08-v1-parity-modular-plan.md) |
| **V1 → V2 Conversations gap** | Working contract renegociado tras el "trust break" de Phase 4. Reglas de honestidad + gap analysis component-by-component vs v1. | [docs/handoffs/v1-v2-conversations-gap.md](handoffs/v1-v2-conversations-gap.md) |
| **KB module — design (B2)** | Decisiones de diseño del Knowledge Base: schema, RAG flow, agents, prompts, cuts. | [docs/plans/2026-05-10-knowledge-base-module-design.md](plans/2026-05-10-knowledge-base-module-design.md) |
| **KB module — implementation plan** | Plan de 58 tasks con TDD por task. ~25 tasks completadas en sesión 2026-05-10; resto deferred. | [docs/plans/2026-05-10-knowledge-base-module-implementation.md](plans/2026-05-10-knowledge-base-module-implementation.md) |
| **Runbook KB** | Deploy/rollback/smoke/known-issues del módulo KB en su estado parcial actual. | [docs/runbooks/knowledge-base.md](runbooks/knowledge-base.md) |
| **Runbook Conversations** | Operaciones diarias de la bandeja: handoff, intervención, troubleshooting. | [docs/runbooks/conversations.md](runbooks/conversations.md) |
| **Runbook Clients enhanced** | Operativo del CRM: import, custom fields, notas. | [docs/runbooks/clients-enhanced.md](runbooks/clients-enhanced.md) |
| **Runbook Pipeline kanban** | Operativo del kanban: drag-drop, stage transitions, recovery. | [docs/runbooks/pipeline-kanban.md](runbooks/pipeline-kanban.md) |
| **Runbook Workflows + Meta E2E** | Cómo correr el end-to-end real contra Meta + el engine de workflows. | [docs/runbooks/workflows-meta-e2e.md](runbooks/workflows-meta-e2e.md) |
| **Sign-off Workflows + Meta E2E** | Acta firmada del E2E real con Meta del módulo workflows. | [docs/handoffs/sign-offs/workflows-meta-e2e.md](handoffs/sign-offs/workflows-meta-e2e.md) |
| **Project map (este archivo)** | Índice "qué hace cada parte y dónde vive el código". | [docs/PROJECT_MAP.md](PROJECT_MAP.md) |

---

## Notas finales

- **Todas las rutas de FastAPI** están bajo `/api/v1/<feature>/...` y montadas en [core/atendia/main.py](../core/atendia/main.py).
- **Todos los endpoints state-changing** emiten un `events` row vía `emit_admin_event` para el audit log.
- **Todas las queries** son tenant-scoped por `Depends(current_tenant_id)`. Cross-tenant leakage tiene tests dedicados.
- **El frontend** sirve desde el mismo FastAPI vía `StaticFiles` (single-Docker deploy). En dev, Vite proxy al puerto 8001.
- **Tests:** `cd core; uv run pytest -q` (744 baseline + ~70 nuevos del KB module = 814 al cierre de la sesión 2026-05-10, excluyendo integration/e2e slow suites).

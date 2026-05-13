# AtendIA v2 - Mapa del proyecto

> Proposito: mapa operativo para ubicar que hace cada feature, donde vive su logica, donde vive su UI/UX y que tan listo esta.
> El score es una lectura practica del estado actual del repo: codigo presente, rutas montadas, UI conectada, cobertura de tests y riesgos vistos en verificacion local.

## Como leer este mapa

| Campo | Significado |
|---|---|
| Feature | Capacidad visible o modulo interno del producto. |
| Proposito | Para que existe y que problema resuelve. |
| Logica | Backend, dominio, jobs, contratos o integraciones donde se ejecuta el comportamiento. |
| UI/UX | Pantallas, componentes, hooks y cliente API del frontend. |
| Score | 0-100. 90+ muy solido, 75-89 usable con riesgos, 60-74 parcial, <60 no confiable o incompleto. |
| Funciona | Lo que esta conectado y probado o razonablemente operable. |
| No funciona / riesgo | Huecos, deuda, stubs, mocks, migraciones o acciones que parecen UI pero aun no son reales. |

## Verificacion local usada para el score

| Suite | Resultado | Lectura |
|---|---:|---|
| Backend `uv run pytest -q` | 821 passed, 16 skipped | Suite backend verde. Incluye `tests/db/test_migrations_roundtrip.py::test_full_roundtrip_drops_and_recreates_all_tables`; el downgrade de `039_appointment_command_center` ya normaliza estados nuevos antes de restaurar constraints legacy. |
| Backend `pytest core/tests/api/test_rbac_matrix.py` | 5/5 passed | Matriz parametrizada operator vs tenant_admin vs superadmin sobre workflows, agents, customer-fields, tenants y knowledge. |
| Backend `pytest core/tests/api/test_turn_traces_routes.py` | 4/4 passed | List + detail incluyen `inbound_preview` (120 chars). |
| Frontend `pnpm -s typecheck` | Passed | TypeScript compila sin errores. |
| Frontend `pnpm exec vitest run` | 14 files, 64 tests passed | Incluye `auth-guards` (4), `RoleGate` (4), `turnStory` (10), `FlowModeBadge` (4), `TurnStoryView` (8), `useCustomerAttrs` (4), `EditableDetailRow` (8), `AddCustomAttrDialog` (8). |
| Frontend `pnpm exec biome check` (archivos tocados) | Sin errores | 15 archivos auto-formateados; 3 suppressions inline `noArrayIndexKey` documentadas en listas derivadas de JSON inmutable. |
| Mock isolation guard tests | 17/17 passed | `test_demo_tenant_dep`, `test_handoff_cc_demo_gate`, `test_kb_cc_demo_gate`, `test_demo_providers`. |
| Seed full mock `uv run python -m compileall scripts\seed_full_mock_data.py` | Passed | El script compila sin errores. |
| Seed full mock `uv run python scripts\seed_full_mock_data.py` | Passed 2 veces | Seed idempotente para el tenant `demo`; refresca filas `mock-full` sin duplicar datos. |
| Login mock `admin@demo.com` / `superadmin@demo.com` | Password hash verificado | Ambos usuarios aceptan `admin123`; roles `tenant_admin` y `superadmin`. |

## Mock data funcional para probar todo

| Item | Valor |
|---|---|
| Script | `core/scripts/seed_full_mock_data.py` |
| Como correr | Desde `core/`: `uv run python scripts\seed_full_mock_data.py` |
| Tenant | `demo` |
| Login admin tenant | `admin@demo.com` / `admin123` |
| Login superadmin | `superadmin@demo.com` / `admin123` |
| Marcadores de datos | Tags/prefijos `mock-full`, `[Mock]`, `MOCK-FULL:` y source `mock_full_demo` |
| Idempotencia | Borra y recrea solo datos mock-full; conserva datos ajenos al seed. |

### Conteos sembrados

| Modulo | Cantidad mock | Para probar |
|---|---:|---|
| Usuarios | 8 | Login, roles, RBAC, asignaciones, notificaciones por usuario. |
| Agentes IA | 6 | Agents command center, guardrails, extraccion, decision map, escenarios y versiones. |
| Clientes CRM | 42 | Busqueda, filtros, detalle, score, riesgos, documentos, notas, timeline y custom fields. |
| Conversaciones | 42 | Inbox, etapas, unread, asignaciones, bot paused, tags y detalle. |
| Mensajes | 340 | Chat, burbujas inbound/outbound/system, historial y metadata. |
| Turn traces | 126 | Debug de NLU/composer/tools/costos/latencias por turno. |
| Citas | 33 | Agenda, status variados, conflictos, recordatorios, riesgos, asesores y vehiculos. |
| Handoffs | 21 | Cola humana, estados open/assigned/resolved, SLA, riesgo y payload sugerido. |
| Follow-ups | 28 | Estados pending/sent/cancelled, attempts, quiet-hours y contextos. |
| Outbox | 21 | Pending/sent/failed, idempotency keys, errores y mensajes enviados. |
| Workflows | 6 | Builder/operations, active/paused, variables, dependencias, safety rules y templates. |
| Workflow executions | 24 | Historial, replay de pasos, fallas, running/completed/paused. |
| FAQs KB | 24 | CRUD, filtros, permisos, prioridades y respuestas publicadas/draft. |
| Catalogo KB | 12 | Precios, stock, planes, sucursales, visibility y permisos. |
| Knowledge documents | 10 | Documentos indexed/processing, progreso, permisos y categorias. |
| Knowledge chunks | 58 | Retrieval, chunk impact, critical chunks, scores y uso semanal. |
| KB conflicts | 8 | Conflictos open/resolved, severity, asignacion y resolucion. |
| KB unanswered | 14 | Preguntas sin respuesta, sugerencias, owner y linked FAQ. |
| KB regression tests | 10 | Casos criticos, runs passed/failed y diffs esperados. |
| Notificaciones | 28 | Campana, contador unread, marcar leido y origen mock. |

### Cobertura mock por feature

| Feature | Cobertura mock | Score simulacion |
|---|---|---:|
| App shell / dashboard / notifications | Tenant configurado, estado WhatsApp tocado en Redis si esta disponible, 28 notificaciones, KPIs alimentados por conversaciones/citas/handoffs. | 92 |
| Auth / users / RBAC | Usuarios demo con password fija, roles `tenant_admin`, `superadmin`, `operator`, `supervisor`, `ai_reviewer`, `sales_agent`. | 90 |
| Conversations inbox | 42 conversaciones distribuidas en 9 etapas, 340 mensajes, unread, tags, asignaciones, bot paused, traces y eventos. | 95 |
| Handoffs | 21 escalaciones con payload, riesgo, SLA y estados variados. | 92 |
| Pipeline Kanban | 42 conversaciones balanceadas por etapa: 5 en las primeras 6 columnas y 4 en cada cierre. | 94 |
| Customers / CRM | 42 clientes con custom fields, scoring, riesgos, next best actions, documentos, notas, timeline y AI reviews. | 96 |
| Appointments | 33 citas con todos los estados soportados, tipos, asesores, vehiculos, conflictos y action log. | 93 |
| Knowledge Base | 6 colecciones, 24 FAQs, 12 catalog items, 10 documentos, 58 chunks, conflictos, unanswered, tests, health snapshots y permisos. | 95 |
| Agents | 6 agentes `[Mock]` con ops_config rico: health, metrics, guardrails, extraction fields, monitor, supervisor, KB coverage, decision map, versions y scenarios. | 94 |
| Workflows | 6 workflows `[Mock]`, 5 templates WhatsApp, AI agents, advisor pool, business hours, variables, dependencias, safety rules, 24 executions y pasos. | 93 |
| Integrations / WhatsApp | Config Meta mock en tenant y `webhook:last_at:{tenant_id}` en Redis cuando Redis responde. | 80 |
| Analytics / traces / audit | Volumen suficiente de conversaciones, events, traces, handoffs, citas y costos mock para alimentar graficas y debug. | 90 |

Limitacion de la simulacion: los datos prueban pantallas, filtros, relaciones, acciones de command center y estados operativos, pero no sustituyen pruebas con Meta/OpenAI reales ni workers arq corriendo en background.

## Score global rapido

| Area | Score | Resumen |
|---|---:|---|
| Core conversacional | 88 | Motor, NLU, composer, tools, queue, realtime y webhooks estan bien cubiertos; el riesgo principal esta en integraciones externas y suites live/e2e omitidas. |
| Workspace operador | 84 | Las pantallas principales existen y consumen APIs reales; el panel de debug ahora tiene narrativa en español y la lista de turnos muestra preview del mensaje. Varias experiencias nuevas siguen con datos demo, acciones mock o botones con `toast.info`. |
| Configuracion bot | 79 | Pipeline, agentes, workflows e integraciones estan montados; Agents y Workflows tienen UI rica pero con partes operativas todavia simuladas. |
| Knowledge Base | 74 | CRUD legacy + RAG foundation + command center ya existen; varias acciones avanzadas devuelven estados mock/stub y los workers cron no estan completos. |
| Infra / deploy / migraciones | 78 | DB, contracts, storage local y serving SPA estan montados; el roundtrip completo de Alembic ya pasa tras corregir la migracion 039. |
| Cobertura mock funcional | 93 | El nuevo seed full mock deja volumen realista para probar casi todas las rutas/pantallas; baja por integraciones externas y workers que siguen requiriendo entorno real. |

---

## 1. Producto y navegacion principal

| Feature | Proposito | Logica | UI/UX | Score | Funciona | No funciona / riesgo |
|---|---|---|---|---:|---|---|
| App shell y navegacion | Envolver la app autenticada, mostrar tenant/rol, menu lateral, estado WhatsApp y notificaciones. | `core/atendia/main.py`, `core/atendia/api/notifications_routes.py`, `core/atendia/api/channel_status_routes.py` | `frontend/src/components/AppShell.tsx`, `frontend/src/components/WhatsAppStatusBadge.tsx`, `frontend/src/features/notifications/api.ts` | 86 | Navegacion de todas las rutas auth, campana con read/read-all, badge de WhatsApp. | No hay test visual/e2e de navegacion completa; el estilo especial de handoffs esta hardcoded por ruta. |
| Dashboard | Dar resumen ejecutivo de operacion: conversaciones, citas, handoffs, actividad reciente. | `core/atendia/api/dashboard_routes.py`, modelos `conversation`, `appointment`, `lifecycle` | `frontend/src/features/dashboard/components/DashboardPage.tsx`, `frontend/src/features/dashboard/api.ts`, `frontend/src/routes/(auth)/dashboard.tsx` | 82 | Endpoint y UI existen, KPIs consumen backend. | Score limitado por falta de pruebas frontend especificas y por dependencia de datos seeded/demo para una vista rica. |
| Notifications | Alertar al operador desde navbar y marcar notificaciones leidas. | `core/atendia/api/notifications_routes.py`, `core/atendia/db/models/notification.py` | `frontend/src/features/notifications/api.ts`, `frontend/src/components/AppShell.tsx` | 84 | Lista, contador unread, marcar una/todas como leidas. | No se ve una pantalla dedicada ni flujos completos de generacion de notificaciones por cada modulo. |
| Exports | Exportar datos operativos a CSV. | `core/atendia/api/exports_routes.py` | `frontend/src/routes/(auth)/exports.tsx` | 76 | Endpoints para CSV de conversaciones y mensajes. | Runbook de clients menciona export job no implementado; UX parece basica. |

---

## 2. Auth, tenancy, usuarios y auditoria

| Feature | Proposito | Logica | UI/UX | Score | Funciona | No funciona / riesgo |
|---|---|---|---|---:|---|---|
| Auth / sesiones | Login de operadores, JWT en cookie httponly, CSRF, refresh/logout y `me`. | `core/atendia/api/auth_routes.py`, `core/atendia/api/_auth_helpers.py`, `core/atendia/api/_csrf.py`, `core/atendia/api/_deps.py` | `frontend/src/routes/login.tsx`, `frontend/src/stores/auth.ts`, `frontend/src/routes/(auth)/route.tsx` | 90 | Login, session guard, CSRF en cliente API, roles cargados en shell. | Quedan warnings de secret corto en tests JWT; revisar hardening de prod. |
| Tenants / multi-tenancy | Aislar datos por tenant y exponer configuraciones base del tenant. | `core/atendia/api/tenants_routes.py`, `core/atendia/db/models/tenant.py`, `core/atendia/db/models/tenant_config.py` | Usado indirectamente por config, inbox settings, AppShell | 88 | `current_tenant_id`, rutas tenant-scoped, config de pipeline, tone, timezone, inbox. | No hay pantalla dedicada de administracion de tenants; impersonation sigue siendo mas tecnico que UX. |
| Users / RBAC | Gestionar usuarios del tenant, roles y acceso tenant-admin/superadmin. | `core/atendia/api/users_routes.py`, `core/atendia/db/models/tenant.py`, dependencias RBAC en `_deps.py`, `core/tests/api/test_rbac_matrix.py` | `frontend/src/features/users/components/UsersPage.tsx`, `frontend/src/features/users/api.ts`, `frontend/src/routes/(auth)/users.tsx`, `frontend/src/lib/auth-guards.ts`, `frontend/src/components/RoleGate.tsx` | 91 | CRUD de usuarios y restricciones por rol; route-level guards (`requireRole`) en `/users`, `/agents`, `/audit-log`, `/inbox-settings`, `/config`; matriz E2E backend cubre operator/tenant_admin/superadmin sobre 5 endpoints admin-gated; `<RoleGate>` disponible para gating in-page. | `<RoleGate>` aun sin callers (componente listo, no usado). El cambio de guard en `/config` e `/inbox-settings` redirige a operadores que antes podian ver esas pantallas — confirmar con producto si era intencional o si se quiere lectura read-only para operadores. Falta flujo de reset/forgot-password. |
| Audit log | Registrar acciones administrativas y consultarlas con filtros. | `core/atendia/api/audit_log_routes.py`, `core/atendia/api/_audit.py`, `core/atendia/db/models/event.py` | `frontend/src/features/audit-log/AuditLogPage.tsx`, `frontend/src/routes/(auth)/audit-log.tsx` | 84 | Emision via `emit_admin_event` en muchos endpoints state-changing y pantalla de auditoria. | Algunas acciones nuevas tipo mock/toast no generan audit real porque no llegan a backend. |

---

## 3. Conversaciones y operacion humana

| Feature | Proposito | Logica | UI/UX | Score | Funciona | No funciona / riesgo |
|---|---|---|---|---:|---|---|
| Conversations inbox | Bandeja de conversaciones, detalle, mensajes, panel de contacto editable, intervencion humana, pausa/reanudar bot. | `core/atendia/api/conversations_routes.py`, `core/atendia/api/customers_routes.py`, `core/atendia/db/models/conversation.py`, `core/atendia/db/models/message.py`, `core/atendia/queue/force_summary_job.py` | `frontend/src/features/conversations/components/*` (incluye `ContactPanel.tsx`, `EditableDetailRow.tsx`, `AddCustomAttrDialog.tsx`), `frontend/src/features/conversations/hooks/*` (incluye `useCustomerAttrs`, `usePatchConversation`), `frontend/src/features/conversations/api.ts`, `frontend/src/routes/(auth)/index.tsx`, `frontend/src/routes/(auth)/conversations.$conversationId.tsx` | 90 | Listado, detalle, mensajes, mark-read, delete, intervene, resume-bot, realtime hooks. Las 10 cards de DATOS DE CONTACTO ahora son inline-editables (Etapa/Fuente/Asesor/Email vía PATCH endpoints, 5 fields free-form vía read-modify-write de `customer.attrs`), con "Agregar campo" para attrs ad-hoc y eliminar. DebugPanel narrativo (sprint anterior). 20 tests nuevos cubren los componentes/hooks editables. | Telefono aún read-only (identity); cambiar requiere reasignación de identidad — fuera de scope. Cross-conversation gap doc previo persiste para temas no relacionados a contacto (search, bulk actions, smart suggestions UI). |
| Handoffs | Gestionar escalaciones de IA a humano: cola, asignacion, resolucion, feedback y borradores sugeridos. | `core/atendia/api/handoffs_routes.py`, `core/atendia/api/_handoffs/command_center.py`, `core/atendia/db/models/lifecycle.py`, `core/atendia/realtime/publisher.py` | `frontend/src/features/handoffs/components/HandoffQueue.tsx`, `frontend/src/features/handoffs/components/HandoffCard.tsx`, `frontend/src/features/handoffs/api.ts`, `frontend/src/routes/(auth)/handoffs.tsx` | 79 | Cola legacy y command center estan montados; assign/resolve/take/feedback/draft existen; UI prioriza por SLA/riesgo/valor. | `command_center.py` usa agentes demo y draft source `mock`; varias metricas son derivadas/sinteticas, no todo viene de telemetria real. |
| Pipeline Kanban | Ver conversaciones por etapa comercial y moverlas entre columnas. | `core/atendia/api/pipeline_routes.py`, `core/atendia/state_machine/pipeline_loader.py`, `core/atendia/db/models/conversation.py` | `frontend/src/features/pipeline/components/PipelineKanbanPage.tsx`, `frontend/src/features/pipeline/api.ts`, `frontend/src/routes/(auth)/pipeline.tsx` | 84 | Board, move, stage groups y alerts existen. | Runbook menciona "cargar mas" no cableado; validar drag/drop con e2e visual. |
| Customers / CRM | Ficha de cliente, busqueda, import CSV, campos custom, notas, scoring, riesgos, timeline, documentos y mensajes. | `core/atendia/api/customers_routes.py`, `core/atendia/api/customer_fields_routes.py`, `core/atendia/api/customer_notes_routes.py`, `core/atendia/db/models/customer*.py` | `frontend/src/features/customers/components/ClientsPage.tsx`, `CustomerDetail.tsx`, `CustomerSearch.tsx`, `ImportCustomersDialog.tsx`, `frontend/src/features/customers/api.ts`, rutas `customers*` | 82 | CRUD, import preview/import, export, notas, custom fields, score/risk/actions/timeline estan en codigo. | `customers_routes.py` auto-seedea demo para `admin@demo.com`; algunas operaciones avanzadas dependen de datos demo o calculos internos simples. |
| Appointments | Command center de citas: agenda, vistas dia/semana/asesor/lista, riesgo, conflictos, recordatorios y acciones operativas. | `core/atendia/api/appointments_routes.py`, `core/atendia/db/models/appointment.py`, `core/atendia/db/migrations/versions/039_appointment_command_center.py` | `frontend/src/features/appointments/components/AppointmentsPage.tsx`, `AppointmentsFeatureSettings.tsx`, `frontend/src/features/appointments/api.ts`, `frontend/src/routes/(auth)/appointments.tsx` | 80 | CRUD, KPIs, conflict detection, priority feed, parser natural, confirm/reschedule/no-show/completed, UI rica y downgrade 039 validado en roundtrip. | Advisors/vehicles son constantes demo; acciones WhatsApp usan `mock_whatsapp`; import CSV y filtros avanzados son `toast.info`. |

---

## 4. Knowledge Base y RAG

| Feature | Proposito | Logica | UI/UX | Score | Funciona | No funciona / riesgo |
|---|---|---|---|---:|---|---|
| Knowledge CRUD legacy | Administrar FAQs, catalogo, documentos, upload/download/retry/delete, test de conocimiento y reindex. | `core/atendia/api/knowledge_routes.py`, `core/atendia/db/models/tenant_config.py`, `core/atendia/db/models/knowledge_document.py`, `core/atendia/queue/index_document_job.py`, `core/atendia/storage/*` | `frontend/src/features/knowledge/api.ts`, `frontend/src/features/knowledge/components/KnowledgeBasePage.tsx`, `frontend/src/routes/(auth)/knowledge.tsx` | 80 | CRUD FAQ/catalog, documentos, test endpoint con fallback, rate limit y cooldown de reindex. | Reindex depende de Redis/arq; sin worker queda en error o queued. |
| Knowledge command center | Operar salud de KB, riesgos, items, preguntas sin respuesta, cobertura por embudo, simulacion RAG, impacto de chunks y conflictos. | `core/atendia/api/_kb/command_center.py`, `search.py`, `test_query.py`, `collections.py`, `core/atendia/tools/rag/*`, modelos `kb_*.py` | `frontend/src/features/knowledge/components/KnowledgeBasePage.tsx`, `frontend/src/features/knowledge/api.ts` | 69 | UI de 9 tabs/paneles y endpoints command center estan montados; schemas Zod validan respuestas. | Muchas acciones solo devuelven `{status: ...}`; simulacion puede ser `mode="mock"`; workers cron de conflictos/health/expire/regression/import no estan completos. |
| RAG foundation | Recuperar fuentes, construir prompt seguro, detectar conflictos/frases riesgosas y sintetizar respuesta sin inventar. | `core/atendia/tools/rag/provider.py`, `retriever.py`, `prompt_builder.py`, `answer_synthesizer.py`, `conflict_detector.py`, `risky_phrase_detector.py`, `openai_provider.py`, `mock_provider.py` | Consumido por Knowledge y runner/tools segun config | 78 | Tests de provider, retriever, prompt builder, synthesizer, conflict detector y risky phrases pasan. | Algunas rutas de produccion aun usan fallback/mock y el runbook viejo todavia documenta una B2 parcial de 30%, asi que falta alinear docs/runbooks con el codigo actual. |

---

## 5. Configuracion del bot y automatizacion

| Feature | Proposito | Logica | UI/UX | Score | Funciona | No funciona / riesgo |
|---|---|---|---|---:|---|---|
| Config / Pipeline editor | Editar pipeline por tenant: stages, transitions, brand facts, tone y reglas de flujo. | `core/atendia/api/tenants_routes.py`, `core/atendia/api/pipeline_routes.py`, `core/atendia/db/models/tenant_config.py`, contracts `pipeline_definition` | `frontend/src/features/config/components/PipelineEditor.tsx`, `BrandFactsEditor.tsx`, `ToneEditor.tsx`, `IntegrationsTab.tsx`, `frontend/src/routes/(auth)/config.tsx` | 84 | Edicion de JSON/config, tono, marca e integraciones. | Necesita e2e para garantizar que cambios rompan menos el motor; UI de pipeline no reemplaza por completo un visual builder. |
| Agents | Configurar agentes IA: identidad, tono, guardrails, extraccion, monitor, KB, decision map, pruebas, versiones. | `core/atendia/api/agents_routes.py`, `core/atendia/db/models/agent.py`, routers `guardrails`, `extraction-fields`, `supervisor`, `scenarios` | `frontend/src/features/agents/components/AgentsPage.tsx`, `frontend/src/features/agents/api.ts`, `frontend/src/routes/(auth)/agents.tsx` | 73 | CRUD, duplicate, disable, publish/rollback, validate, preview, guardrails, extraction fields y decision map estan expuestos. | `agents_routes.py` genera demo agents; varias secciones devuelven snapshots sinteticos; UI contiene botones que solo lanzan `toast.info` o acciones preparadas. |
| Workflows | Automatizar eventos tipo Zapier: triggers, condiciones, acciones, simulacion, ejecuciones, versiones y pausa segura. | `core/atendia/api/workflows_routes.py`, `core/atendia/workflows/engine.py`, `core/atendia/db/models/workflow.py`, `core/atendia/queue/workflow_jobs.py` | `frontend/src/features/workflows/components/WorkflowsPage.tsx`, `WorkflowEditor.tsx`, `frontend/src/features/workflows/api.ts`, `frontend/src/routes/(auth)/workflows.tsx` | 76 | CRUD, activar/desactivar, nodos, validate/simulate, executions, retry, templates y UI visual estan montados; tests de engine pasan. | `workflows_routes.py` crea workflows demo; algunos comandos son toast o versiones dummy (`v12/v13`); conviene e2e real de ejecuciones. |
| Integrations / WhatsApp status | Mostrar salud de canal Meta/WhatsApp y proveedor IA. | `core/atendia/api/integrations_routes.py`, `core/atendia/api/channel_status_routes.py`, `core/atendia/channels/meta_cloud_api.py`, `core/atendia/queue/circuit_breaker.py` | `frontend/src/features/config/components/IntegrationsTab.tsx`, `frontend/src/components/WhatsAppStatusBadge.tsx` | 82 | Details de WhatsApp, AI provider info y status badge. | Estado depende de configuracion real Meta/Redis; no reemplaza una consola completa de integraciones. |
| Inbox settings | Ajustar layout de bandeja, filtros, reglas de handoff, permisos y preview. | `core/atendia/api/tenants_routes.py` con `/tenants/inbox-config` | `frontend/src/features/inbox-settings/components/*`, `frontend/src/features/inbox-settings/types.ts`, `frontend/src/routes/(auth)/inbox-settings.tsx` | 83 | UI 3-panel y persistencia de config tenant. | Se debe verificar impacto real en Conversations; varios ajustes son configuracion futura si el inbox no consume todas las opciones. |

---

## 6. Motor conversacional e integraciones runtime

| Feature | Proposito | Logica | UI/UX | Score | Funciona | No funciona / riesgo |
|---|---|---|---|---:|---|---|
| State machine | Resolver etapa, condiciones, transiciones y acciones por turno usando pipeline tenant-scoped. | `core/atendia/state_machine/orchestrator.py`, `pipeline_loader.py`, `conditions.py`, `transitioner.py`, `action_resolver.py`, `derived.py`, `ambiguity.py` | Sin UI directa; visible en Conversations, Pipeline, Turn traces | 90 | Tests de state machine pasan; contratos JSON y fixtures cubren modos importantes. | Cambios manuales al pipeline pueden romper behavior si no se valida antes de publicar. |
| NLU | Clasificar intent, entidades y confianza con providers keyword/openai/canned. | `core/atendia/runner/nlu_keywords.py`, `nlu_openai.py`, `nlu_canned.py`, `nlu_protocol.py`, `nlu_prompts.py`, `runner/nlu/pricing.py` | Visible en turn traces/debug | 88 | Providers tipados, tests de prompts/protocol/openai retry/keyword/canned. | Live OpenAI depende de llaves y suites live no siempre corren en CI local. |
| Composer | Generar mensajes de salida con provider canned/openai, tono por tenant y reglas de ventana/handoff. | `core/atendia/runner/composer_openai.py`, `composer_canned.py`, `composer_prompts.py`, `composer_protocol.py` | Visible en chat, debug panel y turn traces | 87 | Tests de composer y fixtures de modos pasan. | Calidad real depende de prompts/modelo y datos de KB/catalogo. |
| Flow router | Elegir modo por turno: PLAN, SALES, DOC, OBSTACLE, RETENTION, SUPPORT. | `core/atendia/runner/flow_router.py`, fixtures `core/tests/fixtures/composer/*` | Visible por trace/debug | 86 | Reglas por tenant y tests de runner modes. | Edge cases conversacionales requieren mas fixtures reales. |
| Conversation runner | Unir state machine, NLU, composer, tools, persistencia, turn traces y eventos. | `core/atendia/runner/conversation_runner.py`, `core/atendia/api/runner_routes.py`, `core/atendia/runner/outbound_dispatcher.py` | Disparado desde webhooks, Conversations y pruebas | 88 | `run_turn`, integracion inbound/outbound y tests de runner pasan. | E2E real Meta depende de credenciales y entorno. |
| Tools | Ejecutar acciones del bot: cotizar, catalogo, FAQ/RAG, cita, escalar, followup, vision, embeddings. | `core/atendia/tools/*.py`, `core/atendia/tools/rag/*`, `core/atendia/tools/registry.py`, `core/atendia/tools/runner.py` | Indirecto en chat, KB y traces | 88 | Tests de registry, runner, quote, catalog, FAQ, followup, escalate, book appointment, vision y RAG pasan. | Vision/OpenAI/embeddings tienen caminos live o fallback; revisar costos/rate limits. |
| Webhooks Meta | Recibir WhatsApp Cloud API, verificar webhook, deduplicar, persistir, correr turno y emitir eventos. | `core/atendia/webhooks/meta_routes.py`, `core/atendia/webhooks/deduplication.py`, `core/atendia/channels/meta_cloud_api.py`, `meta_signing.py`, `meta_dto.py` | Sin UI directa; status en integrations | 88 | Tests inbound/status/signing/parse/fetch_media y dedupe pasan. | E2E con Meta real requiere config y secretos; manejar fallos de provider. |
| Outbound queue / worker | Encolar y enviar mensajes outbound con idempotencia, retries y circuit breaker. | `core/atendia/queue/enqueue.py`, `outbox.py`, `worker.py`, `circuit_breaker.py`, `jobs.py`, `core/atendia/runner/outbound_dispatcher.py` | Visible en Conversations y status WhatsApp | 86 | Worker/retry/breaker/outbox con tests; idempotency keys. | Requiere Redis/arq activo; no validado en la suite frontend. |
| Follow-ups | Programar recordatorios in-window y cancelarlos al recibir inbound. | `core/atendia/runner/followup_scheduler.py`, `core/atendia/queue/followup_worker.py`, `core/atendia/tools/followup.py`, `core/atendia/db/models/lifecycle.py` | Indirecto en dashboard/conversations | 84 | Tests de scheduler, worker y tool pasan. | Quiet hours y entorno real deben probarse con reloj/cron productivo. |
| Realtime / WebSocket | Publicar eventos por Redis y refrescar pantallas en tiempo real. | `core/atendia/realtime/publisher.py`, `ws_routes.py`, `auth.py` | `frontend/src/api/ws-client.ts`, `frontend/src/features/conversations/hooks/useTenantStream.ts`, `useConversationStream.ts` | 86 | Tests de publisher, auth y WS pasan; hooks invalidan queries. | Necesita validacion con servidor real y multiples tabs/tenants. |

---

## 7. Observabilidad, analitica y debugging

| Feature | Proposito | Logica | UI/UX | Score | Funciona | No funciona / riesgo |
|---|---|---|---|---:|---|---|
| Turn traces | Investigar cada turno: NLU, composer, tools, costos, latencias y payloads, ahora con narrativa en español. | `core/atendia/api/turn_traces_routes.py` (ahora expone `inbound_preview`), `core/atendia/db/models/turn_trace.py` | `frontend/src/features/turn-traces/components/TurnTraceList.tsx`, `TurnTraceInspector.tsx`, `TurnStoryView.tsx`, `TurnTraceSections.tsx`, `FlowModeBadge.tsx`, `lib/turnStory.ts`, `frontend/src/routes/(auth)/turn-traces.tsx` | 92 | Lista con preview del mensaje + badges coloreados por flow_mode. Inspector con 3 tabs: Resumen (timeline narrativo en español derivado de `TurnTraceDetail`), Detalle técnico (secciones compartidas con DebugPanel) y Raw JSON. `DebugPanel` de Conversaciones tambien muestra la narrativa arriba. 26 tests unitarios cubren derivación y rendering. | Cross-conversation explorer aun no aterriza; `/turn-traces` exige `?conversation_id=<uuid>` en URL (placeholder hasta T56). Los intent labels solo traducen 8 valores (greeting/ask_info/ask_price/buy/schedule/complain/off_topic/unclear); intents fuera de la lista caen al string raw. |
| Analytics | Medir funnel, volumen, costos y handoffs. | `core/atendia/api/analytics_routes.py`, modelos conversations/handoffs/turn_traces | `frontend/src/features/analytics/components/AnalyticsDashboard.tsx`, `frontend/src/features/analytics/api.ts`, `frontend/src/routes/(auth)/analytics.tsx` | 78 | Endpoints de funnel, cost, volume y handoff analytics. | Riesgo de scaffolding: validar con datos reales y rangos largos. |
| Audit/debug frontend | Fallbacks de ruta, errores y cliente API consistente. | `frontend/src/components/RouteErrorFallback.tsx`, `frontend/src/lib/api-client.ts`, `frontend/src/lib/error-detail.ts` | Global en Router/AppShell | 82 | API client testeado para CSRF; error detail helper usado por features. | Falta cobertura visual de estados de error en pantallas grandes. |

---

## 8. Infraestructura compartida

| Feature | Proposito | Logica | UI/UX | Score | Funciona | No funciona / riesgo |
|---|---|---|---|---:|---|---|
| DB / migrations | Evolucionar Postgres, pgvector y modelos async con Alembic. | `core/atendia/db/base.py`, `session.py`, `core/atendia/db/migrations/versions/*`, `core/alembic.ini`, modelos `core/atendia/db/models/*` | Sin UI directa | 78 | Upgrade/downgrade roundtrip completo pasa; migracion 039 normaliza `confirmed`, `arrived`, `rescheduled` y `created_by_type='ai'` antes de restaurar constraints legacy. | Mantener tests de roundtrip cuando se agreguen estados o constraints nuevos para evitar regresiones similares. |
| Contracts | Mantener shapes canonicos entre JSON Schema, Pydantic y frontend generated types. | `contracts/*.schema.json`, `core/atendia/contracts/*`, `core/tests/contracts/*` | `frontend/src/types/generated/*`, `frontend/scripts/generate-types.mjs` | 88 | Tests de consistencia de schemas pasan. | Regenerar tipos cuando cambien schemas; evitar drift manual en APIs TS no generadas. |
| Storage | Guardar uploads de documentos/KB localmente y abstraer backend futuro. | `core/atendia/storage/base.py`, `local.py`, `core/tests/storage/*` | Usado por Knowledge upload/download | 84 | Storage local, limites y quota con tests. | Cloud/blob no implementado; orphan cleanup es best-effort. |
| Static SPA deploy | Servir React build desde FastAPI y soportar deep links. | `core/atendia/main.py`, clase `_SPAStaticFiles`, `frontend/vite.config.ts` | `frontend/dist` en produccion | 84 | Fallback SPA evita 404 en rutas frontend. | No se ejecuto `pnpm build` en esta verificacion; typecheck y tests si pasaron. |
| UI system | Componentes base reutilizables y estilos comunes. | `frontend/src/components/ui/*`, `frontend/src/lib/utils.ts`, `frontend/src/index.css`, `frontend/components.json` | Todas las features | 80 | shadcn/radix/lucide, tabs/dialogs/forms/sheets/menus. | Varias paginas nuevas usan dark command-center propio; revisar consistencia y responsive con Playwright. |
| Seed scripts / CLI | Preparar datos demo, ingest, smoke tests, upgrade de pipeline y simulacion funcional completa. | `core/scripts/*`, `core/atendia/scripts/*`, `core/scripts/seed_full_mock_data.py` | Sin UI directa | 88 | Scripts de seed/ingest y tests de scripts existen; `seed_full_mock_data.py` carga 42 conversaciones, CRM, KB, citas, workflows, agentes, handoffs, traces, notificaciones y outbox de forma idempotente. | Algunos modulos auto-seedean demo al listar, lo cual es util para demo pero peligroso si llega a prod sin guardrails. |

---

## 9. Documentacion operativa

| Documento | Proposito | Ruta | Estado |
|---|---|---|---|
| Architecture | Vision tecnica general del sistema. | `docs/design/atendia-v2-architecture.md` | Util como base. |
| V1 to V2 parity roadmap | Inventario modular de paridad con v1. | `docs/plans/2026-05-08-v1-parity-modular-plan.md` | Parcialmente historico. |
| Conversations gap | Gap analysis de bandeja vs v1. | `docs/handoffs/v1-v2-conversations-gap.md` | Sigue siendo referencia para pendientes UX. |
| KB design | Diseno de Knowledge Base/RAG. | `docs/plans/2026-05-10-knowledge-base-module-design.md` | Base conceptual, revisar contra cambios nuevos. |
| KB implementation plan | Plan TDD del modulo KB. | `docs/plans/2026-05-10-knowledge-base-module-implementation.md` | Historico y parcialmente desactualizado. |
| KB runbook | Deploy/rollback/smoke/known issues KB. | `docs/runbooks/knowledge-base.md` | Desactualizado frente al `KnowledgeBasePage.tsx` command center actual. |
| Conversations runbook | Operacion diaria de bandeja/handoff. | `docs/runbooks/conversations.md` | Vigente para soporte. |
| Clients enhanced runbook | Operacion CRM: import, custom fields, notas. | `docs/runbooks/clients-enhanced.md` | Vigente con notas de pendientes. |
| Pipeline kanban runbook | Operacion de kanban y recovery. | `docs/runbooks/pipeline-kanban.md` | Vigente con pendiente de cargar mas. |
| Workflows Meta E2E runbook | Como correr E2E real con Meta y workflows. | `docs/runbooks/workflows-meta-e2e.md` | Vigente si hay credenciales. |
| Project map | Este inventario de features, rutas y score. | `docs/PROJECT_MAP.md` | Actualizado a la lectura actual del workspace. |

---

## Pendientes prioritarios sugeridos por el score

1. ~~Separar claramente modo demo/mock de modo produccion en Agents, Workflows, Handoffs, Appointments y Knowledge command center.~~ **Completado 2026-05-11** — `tenants.is_demo` flag, `_demo/` module, provider protocols, `DemoBadge` + `NYIButton` components. Ver `docs/plans/2026-05-11-mock-demo-isolation-design.md`.
2. ~~Endurecer permisos y RBAC por pantalla con evidencia E2E.~~ **Completado 2026-05-13** — `requireRole` route guards en 5 rutas admin, `<RoleGate>` componente y `test_rbac_matrix.py` parametrizado. Ver `docs/plans/2026-05-12-rbac-and-observability-design.md`.
3. ~~Mejorar observabilidad UX del DebugPanel/turn-traces (menos JSON, mas legible).~~ **Completado 2026-05-13** — Narrativa en español derivada de `TurnTraceDetail`, `FlowModeBadge` coloreado, preview de inbound en lista, inspector rediseñado con 3 tabs (Resumen/Detalle/Raw) y mismo Resumen al tope del `DebugPanel`.
4. ~~Hacer editable la sección DATOS DE CONTACTO en `ContactPanel` (agregar/modificar/eliminar campos).~~ **Completado 2026-05-13** — 10 cards inline-editables, `<EditableDetailRow>` reusable, `useCustomerAttrs` con read-modify-write, `AddCustomAttrDialog` con auto-slug, eliminar/limpiar per card. Ver `docs/plans/2026-05-13-editable-contact-panel-design.md`.
4. Alinear `docs/runbooks/knowledge-base.md` con el `KnowledgeBasePage.tsx` actual, porque el runbook todavia describe un frontend B2 diferido que ya cambio en el workspace.
5. Agregar Playwright smoke de navegacion para las rutas principales: conversations, handoffs, customers, appointments, knowledge, agents y workflows.
6. ~~Convertir botones `toast.info` de command centers en acciones reales o marcarlos visualmente como placeholders internos.~~ **Completado 2026-05-11** — `toast.info` stubs reemplazados por `<NYIButton>` en 7 archivos de features.

## Como probar localmente las features de este sprint (RBAC + observabilidad)

1. Levantar infra: `docker compose up -d postgres-v2 redis-v2`.
2. Aplicar migraciones (si no es ambiente fresco las skipea): desde `core/`, `uv run alembic upgrade head`.
3. Sembrar datos mock: desde `core/`, `uv run python scripts/seed_full_mock_data.py`. Idempotente.
4. Backend dev: desde `core/`, `uv run uvicorn atendia.main:app --reload --port 8001`.
5. Frontend dev: desde `frontend/`, `pnpm dev`. Abre en `http://localhost:5173`.

Cuentas demo (todas con password `admin123`):

| Email | Rol | Que probar |
|---|---|---|
| `superadmin@demo.com` | `superadmin` | Acceso total incluyendo `/audit-log`. |
| `admin@demo.com` | `tenant_admin` | Acceso a `/users`, `/agents`, `/config`, `/inbox-settings`; redirect en `/audit-log`. |
| `ana.garcia@demo.com` | `operator` | Redirect a `/` al tipear `/users`, `/agents`, `/audit-log`, `/inbox-settings`, `/config`. |
| `paola.soto@demo.com` | `supervisor` | Mismo trato que operator para guards admin-only. |

Smoke manual sugerido:

- Como operator, intentar abrir `/users`, `/agents`, `/audit-log`, `/inbox-settings`, `/config` por URL directa — todas deben redirigir a `/`. El sidebar tampoco debe mostrar esos items.
- Como tenant_admin, todas las anteriores cargan excepto `/audit-log` (redirige).
- Abrir una conversacion del inbox: el panel "Debug" lateral debe abrir con la seccion "Resumen" arriba mostrando: cliente → bot entendió → modo → tools → composer → outbound → transición de etapa, antes de las secciones técnicas existentes.
- Navegar a `/turn-traces?conversation_id=<uuid>` (copia un UUID desde la URL del inbox detalle): la tabla muestra columna "Mensaje" con preview, y los modos como badges coloreados. Al click, el inspector abre con tres tabs.
- Como tenant_admin/superadmin, probar el endpoint backend gated: `curl` o vía UI ejecutar POST a `/api/v1/workflows` con body válido — debe retornar != 403. Como operator, debe retornar 403.

## Que mas necesitaria arreglar para probar end-to-end

Nada bloqueante para validar lo entregado en este sprint. Friciones menores que el usuario puede toparse:

1. **Operador no listado en el output del seed**: `scripts/seed_full_mock_data.py` solo imprime credenciales de `admin@demo.com` y `superadmin@demo.com`. Para probar RBAC, el operador a usar es `ana.garcia@demo.com` (no hay output que lo diga). Mejora barata si quieres: agregar un `print` extra al final del seed.
2. **Cross-conversation /turn-traces**: la pantalla `/turn-traces` sin `?conversation_id=` muestra una nota de placeholder ("UI cross-conversation aterriza en T56"). El nuevo inspector y `TurnStoryView` ya estan integrados al panel de Conversaciones, asi que no es bloqueante — pero si quieres scanear traces sin abrir cada conversación, falta esa pantalla.
3. **Cambio de `/config` e `/inbox-settings` a tenant_admin+**: antes el sidebar las ocultaba pero la URL era libre. Ahora redirigen. Confirmar que es el comportamiento deseado; si producto quiere que el operador vea config en read-only, hay que partir las pantallas en una vista pública + secciones de escritura gated con `<RoleGate>` (que ya existe pero no esta cableado).
4. **`<RoleGate>` sin callers todavia**: el componente esta listo y testeado, pero ninguna pantalla actual lo usa. Si producto necesita gating granular dentro de una pantalla operator-visible (ej. botón "Borrar workflow" solo para admin), envolver el botón en `<RoleGate roles={["tenant_admin","superadmin"]}>...</RoleGate>`.
5. **Reset/forgot password**: sigue sin existir flujo. Los demo users hashean en seed, pero en producción los tenant_admins no tienen UI para resetear password de un operator. Punch-list separada.

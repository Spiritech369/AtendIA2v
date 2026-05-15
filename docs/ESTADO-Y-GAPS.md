# AtendIA v2 — Estado del proyecto y gaps vs respond.io

> **Última revisión:** 2026-05-15 (post Sprint A/B/C + cleanup)
> **Reemplaza** (todos archivados bajo `docs/_archive/`, ver [`docs/_archive/README.md`](_archive/README.md)):
> 20 plans en `docs/_archive/plans/`, `docs/_archive/AUDIT-2026-05-13.md`, `docs/_archive/PROJECT_MAP.md`.
> **Documentos que NO reemplaza (siguen vigentes):** `docs/design/atendia-v2-architecture.md` (visión técnica), `docs/handoffs/2026-05-14-inbound-message-flow.md` (flujo runtime), `docs/runbooks/*` (operación diaria).

---

## 0. Tesis y alcance

**Tesis acordada:** igualar o superar a respond.io **en el asistente IA / chatbot** que entrega bien la información, sigue el flujo de ventas y maneja conversaciones reales. Es lo que el usuario ya logró con respond.io tras mucha práctica y lo que **vende**.

**No entra en este doc** (diferido, no por falta de visión sino por prioridad de venta):
- Broadcasts / campañas masivas
- Multi-canal (Instagram DM, FB Messenger, web widget, email, SMS, voz)
- Multi-vertical out-of-the-box (presets para clínicas, hoteles, restaurantes…)
- Mobile app
- AI Credits / billing infra
- SSO / organizations

**Foco actual — los 5 módulos que cargan la promesa:**

1. **Chats** — Inbox + chat window + composer + ContactPanel + DebugPanel
2. **Pipelines** — editor + kanban + reglas auto-enter + stage editor
3. **AI Agent** — editor + guardrails + KB scoping + monitor + versiones
4. **Workflows** — editor + triggers + nodes + simulator + executions
5. **Knowledge Base** — colecciones + CRUD + RAG + command center

---

## 0bis. Sprint A/B/C entregado (2026-05-14 / 05-15) — 14 commits

Branch `main` ahora va 15 commits adelante de `origin/main`. Resumen de lo que cerró:

### Sprint A — Críticas (4/5 cerradas, A.5 diferido a sesión propia)

| Commit | Item | Cambio |
|---|---|---|
| `d5161f9` | A.1 | Tests pinean `conversations.csv` date filter + tenant isolation + ExtractedField unpack en `exports_routes` |
| `2d3d967` | A.2 | Migración 047 (`advisors` + `vehicles` con composite PK), `DBAdvisorProvider`/`DBVehicleProvider`, POST endpoints con RBAC, 12 tests |
| `53ee4c3` | A.3 | Wiring Baileys/Meta inbound ya estaba; arreglé 2 bugs en `default_pipeline` (sin `actions_allowed` + `flow_mode_rules` vacío) que dejaban mudo al bot. Audit event surface mejorada |
| `e010393` | A.4 | `/knowledge/simulate` con búsqueda ILIKE real sobre FAQs/catálogo/chunks; empty-state preservado |
| A.5 | ⏸️ diferido | **WhatsApp Templates >24h** (Phase 3d.2) — ~30 commits, sesión propia |

### Sprint B — Deuda visible (4/4 cerradas)

| Commit | Item | Cambio |
|---|---|---|
| `db4fb8c` | B.3 | `/audit-logs` lee `events` con `type LIKE 'admin.kb.%'`; `/conflicts` lee `kb_conflicts` real con order by severity |
| `c7f3891` | B.4 | Worker arq `poll_appointment_reminders` (cron @second:30), marca `sent_24h` + emite evento `admin.appointment.reminder_due_24h` |
| `8577fad` | B.2 | NYIButton hidden por defecto (`VITE_SHOW_NYI=true` para surface); WhatsApp deep-link `wa.me/<e164>` cableado en ContactPanel |
| `0b836b7` | B.1 | 12 smoke tests para todas las páginas + helper `renderPage.tsx` reusable |

### Sprint C + punch list (7/9 cerradas)

| Commit | Item | Cambio |
|---|---|---|
| `0611753` | C.6 | `search_catalog` con `order_by(sku)` — determinístico cuando alias matchea múltiples SKUs |
| `1571a8e` | C.8 + C.9 | 3 mypy errors limpios; HandoffReason docstring documenta wiring status + receta 3-pasos |
| `a41a1b4` | C.4 | CI publica coverage summary en cada PR + sube `coverage.xml` como artifact |
| `cddacf1` | C.3 | Backend `offset` pagination + frontend botón "Cargar más (N restantes)" en kanban |
| `0df8182` | C.2 | `/turn-traces` ahora soporta cross-conversation explorer sin `?conversation_id=`; UI con filtro `flow_mode` y polling 30s |
| `521c746` | C.1 | Playwright smoke spec para 7 rutas + README (browsers no instalados — run deferred a decision matrix) |
| C.5, C.7 | ⏸️ | **Forgot password** (necesita proveedor email) + **Runner-composer reconciliation** (T30+) |

### Sprint C2 entregado — DebugPanel completion (12 commits)

The audit's C2 item ("DebugPanel rebuild") was completed across 13
atomic TDD tasks. The 8 wishlist items are all wired to real data.

| Commit | Task | Item |
|---|---|---|
| `6010f94` | 1 | Migration 048: `turn_traces.composer_provider` + `inbound_text_cleaned` |
| `219ee15` + `7280912` | 2 | Runner persists both fields (`fallback_used` plumbed per-call, normalizer shared with router) |
| `1809eb1` | 3 | `GET /turn-traces/:id` exposes both fields |
| `53539eb` | 4 | TypeScript `TurnTraceDetail` interface mirrors the migration |
| `6a7f8d4` | 5 | History count chip "N / M" in `StepInbound` |
| `b7775c9` | 6 | LLM provider badge in `StepComposer` (3 tones) |
| `930555b` | 7 | Cleaned-text side-by-side in `StepInbound` |
| `249f2c0` | 8 | Agent name + role in `StepComposer` (5min staleTime fetch) |
| `8163c96` | 9 | `<ActionsPanel />` listing `composer_output.action_payload` |
| `b38ca0b` | 10 | `<LatencyPerStepBar />` (NLU / Vision / Composer / Tools / Overhead) |
| `a56425d` | 11 | `<PromptTemplateBreakdown />` parsing `###` markers |
| `d6b41c2` | 12 | `<ToolCallsTimeline />` with input/output drilldown |

Net deltas (compared to Sprint A/B/C baseline):
* Backend: +1 migration (048), +2 new fields persisted by the runner,
  +1 new field-pair on the API response.
* Frontend: +4 new analyzer functions, +4 new panels in TurnPanels.tsx,
  +4 new story-step fields (history count, provider, cleanedText,
  agentName/Role).
* Tests: ~26 new frontend tests across 8 files, +1 backend runner test,
  +1 backend API test. All green except baseline pre-existing
  failures (6 frontend + 2 backend regression, all flagged in prior
  Sprint A/B/C commits).

### Bugs pre-existentes encontrados de paso (no arreglados, en decision matrix)

- Migration 026 emite `DEFAULT '''user'''` (tres comillas literales) para `appointments.created_by_type` — viola `ck_appointments_created_by_type`. Workaround en tests: pasar `created_by_type` explícito.
- 8 errores TS pre-existentes en `frontend/tests/features/pipeline/DocumentRuleBuilder.test.tsx` (falta prop `catalog`).
- 1840 errores ruff baseline en backend; CI debería estar rojo en `Lint` step.
- Test `test_load_active_pipeline_picks_up_new_version_without_restart` corregido en `53ee4c3` (faltaba `fallback` requerido en la definition).
- 3 stale tests en `test_demo_tenant_dep.py` corregidos en `2d3d967` (esperaban 501 ya removido por `d9c7f40`).

---

## 1. Mapa de superficie vs respond.io (12 secciones)

| # | Sección respond.io | AtendIA v2 | Lectura |
|---|---|---|---|
| 1 | AI Agents (guides + actions + prompt templates + testing) | 🟢 paridad fuerte | Editor con identidad, prompt, guardrails, KB scoping, monitor, preview LLM, versiones, Operations Center con 7 tabs. Falta: A/B testing, sandbox replay con conversaciones reales. |
| 2 | Dashboard & Reporting (12 reportes) | 🟡 parcial — MVP de 4 cards + endpoints analytics | Manager MVP cubre lo básico; faltan reportes específicos. **Sprint C.4** publica coverage en CI. |
| 3 | Inbox (conversations + AI Assist + AI Prompts + emails + calls) | 🟡 parcial fuerte | Inbox real con detalle, mensajes, intervención, pause/resume, realtime WS, ContactPanel editable. **Sprint B.2** wiring WhatsApp deep-link. AI Assist (sugerencias en composer) **no existe**. AI Prompts inline **no existe**. |
| 4 | Contacts (overview + details + activities + import + segments) | 🟢 paridad práctica | 42 clientes mock + import CSV + custom fields + notas + scoring + timeline + documentos. **Segments** no existen. |
| 5 | Broadcasts | ⏸️ diferido por acuerdo | — |
| 6 | Workflows (triggers + steps + branch + jump + HTTP + 23 step types) | 🟡 parcial | 14 triggers wired, 9 node types con UI form, branch multi-rule, simulator, executions, validate, safety rules, idempotencia, 24h-window guard, visual canvas, PublishDialog, VersionCompareDialog. |
| 7 | Dynamic Variables | 🟡 parcial | Backend soporta `{{customer.attrs.X}}`, `{{brand_facts.X}}`. UI no tiene picker/autocomplete. |
| 8 | Workspace Settings (16 secciones) | 🟡 parcial | General, users, channels (Meta + Baileys), contact fields, lifecycle, integrations, files (storage local), data export/import. **Sprint A.2** agrega CRUD de advisors/vehicles. Faltan: snippets, closing notes, growth widgets, AI Assist config, calls. |
| 9 | Organization Settings | ⏸️ diferido | Multi-workspace por org no existe. |
| 10 | User Account (profile + status + notifications + reset password) | 🟡 parcial | Login, JWT, perfil mínimo, notifications bell con polling. **Falta:** reset/forgot password (C.5 deferred). |
| 11 | Mobile App | ⏸️ diferido | — |
| 12 | Help Menu | ⏸️ diferido | — |

**Lectura honesta:** en los 5 módulos core que vendemos (1, 3, 4, 6 + KB que respond.io distribuye dentro de §1) **estamos cerca de paridad funcional con respond.io**. Los huecos restantes son de calidad/madurez (versiones, debugging, sandboxing) más que de features faltantes.

---

## 2. Chats — Conversations + data (incluye DebugPanel)

**Archivos auditados:** `frontend/src/features/conversations/components/{ConversationsPage.tsx (1984), ChatWindow.tsx (78), MessageBubble.tsx (121), MediaContent.tsx (62), SystemEventBubble.tsx (203), InterventionComposer.tsx (109), ContactPanel.tsx (~1854), EditableDetailRow.tsx (200), AddCustomAttrDialog.tsx (148), FieldSuggestionsPanel.tsx (89), DebugPanel.tsx (132)}` + `features/turn-traces/components/TurnTraceSections.tsx (303)` + `core/atendia/api/conversations_routes.py (1360)` + `core/atendia/api/customers_routes.py (2390)`.

### 2.1 Qué funciona hoy

- **Inbox completo** con FilterRail, persistencia de tabs, sync con full-pipeline filter, búsqueda con strip de diacríticos.
- **Chat window** con burbujas inbound/outbound/system, render de media, internal-notes, click-to-debug, 7 tipos de system events.
- **InterventionComposer** con takeover toggle + ⌘/Ctrl+Enter. Persiste outbound, marca `bot_paused`, encola Meta/Baileys.
- **Resume bot** funcional — runner respeta `bot_paused` y short-circuita.
- **ContactPanel rico**: identidad editable, custom fields, EditableDetailRow inline, AddCustomAttrDialog con auto-slug, FieldSuggestionsPanel, notas con CRUD.
- **🆕 WhatsApp deep-link** desde ContactPanel — botón "Abrir WhatsApp" abre `wa.me/<e164>` directo (Sprint B.2).
- **AI Field Extraction** cableado: confidence ≥ 0.85 → AUTO; 0.60-0.84 → SUGGEST; resto → SKIP.
- **DebugPanel + TurnTraceSections**: 7 secciones + narrativa en español.
- **WebSocket realtime** vía `useConversationStream + useTenantStream`.
- **WhatsApp dual** — Meta Cloud API + Baileys QR sidecar.
- **🆕 Cross-conversation `/turn-traces` explorer** (Sprint C.2 / T56) — listado tenant-wide ordenado por created_at DESC, filtro flow_mode, polling 30s, deep-link a vista per-conversation.
- **🆕 Smoke render-test** para `ConversationsPage.tsx` (Sprint B.1).

### 2.2 Cerca de respond.io

Inbox y ContactPanel **cumplen paridad funcional**. La intervención humana, pausa de bot, custom fields editables y notas son equivalentes o superiores. **Donde respond.io brilla y nosotros aún no:** AI Assist (sugerencias del bot dentro del composer), AI Prompts inline (operador pide al bot que reescriba en otro tono), debugging visual rico de la decisión del agente.

### 2.3 Gaps priorizados

| # | Sev | Gap | Costo | Status |
|---|---|---|---|---|
| C1 | 🔴 | WhatsApp status badge en header (poll `/whatsapp/status` + `/automation-config/status` cada 10s; verde/ámbar/rojo + "WA pausado"). | 0.5-1d | abierto |
| ~~C2~~ | — | ~~DebugPanel rebuild~~ | — | ✅ **cerrado por Sprint C2 (12 commits, see §0bis)** |
| C3 | 🟠 | Mailbox sections en lista de conversaciones: por AI agent + por pipeline stage con counts en vivo. | 2-3 sesiones | abierto |
| C4 | 🟠 | Right-click context menu en lista (assign / close / archive / tag). | 1-1.5d | abierto |
| C5 | 🟠 | Composer slash-commands + snippet browser + variable picker. | 2-3d | abierto |
| C6 | 🟠 | AI Assist en composer (botón "sugerir respuesta" que use el agente y traiga draft). Diferenciador clave de respond.io. | 3-4d | abierto |
| C7 | 🟡 | ContactPanel collapsible drawer (12px ↔ 320px). | 0.5d | abierto |
| C8 | 🟡 | WS targeted patches (reemplazar bulk invalidation por per-event mutation). | 1.5d | abierto |
| C9 | 🟡 | Per-message edit/delete. | 1d | abierto |
| ~~C10~~ | ~~🟡~~ | ~~Cross-conversation `/turn-traces` explorer~~ | — | ✅ **cerrado por Sprint C.2 (`0df8182`)** |
| C11 | 🟡 | Push realtime de field_suggestions (hoy llega por polling de 60s). | 1d | abierto |

### 2.4 No tocar

Layout del ContactPanel, EditableDetailRow, AddCustomAttrDialog, FieldSuggestionsPanel UX, SystemEventBubble variantes/colores, narrativa en español del DebugPanel Resumen, idempotencia de outbound, dedup de webhook, WhatsApp deep-link recién cableado.

---

## 3. Pipelines — Editor + Kanban + reglas

**Archivos auditados:** `frontend/src/features/pipeline/components/*` (1968 + 1401 + 486 + 289 + …) + `core/atendia/api/pipeline_routes.py (~1000)`.

### 3.1 Qué funciona hoy

- **Kanban view**: drag-drop, KPI por stage, orphan-stage detection con 3 affordances de rescate, stage health chip + per-card SLA accent.
- **🆕 Cargar más** en cada stage (Sprint C.3) — backend `offset` pagination con order estable + frontend botón "Cargar más (N restantes)" con dedup por id.
- **Stage editor**: name/label/timeout/is_terminal/color, behavior_mode, pause_bot_on_enter + handoff_reason, allow_auto_backward, reorder/duplicate/delete con impact dialog.
- **Rule builder**: 10 operadores, AND-OR match logic, preview legible.
- **Document catalog**: tenant-configurable DOCS_* con label + hint, auto-derive key.
- **Plan-doc requirements**: docs_per_plan mapping, operador `docs_complete_for_plan` plan-aware.
- **Vision auto-write mapping**.
- **Document Rule Builder** (M4): `all_validated`/`any_arrived` con checklist.
- **Audit log drawer**, **Versioning hygiene**, **Stage delete impact** con type-to-confirm.
- **Pipeline version history drawer**: lista snapshots, diff, rollback.
- **🆕 `default_pipeline` arreglado** (Sprint A.3): cada stage trae `actions_allowed` y un `flow_mode_rule` `always → SUPPORT` para que el runner no crashee en tenants auto-seeded.
- **🆕 Smoke render-test** para `PipelineKanbanPage.tsx` (Sprint B.1).

### 3.3 Gaps priorizados

| # | Sev | Gap | Costo | Status |
|---|---|---|---|---|
| ~~P1~~ | — | ~~Version rollback UI~~ | — | ✅ cerrado (`PipelineVersionHistoryDrawer`) |
| P2 | 🔴 | Test mode / simular customer a través del pipeline. | ~1w | abierto |
| P3 | 🟠 | Preview impact en conversaciones in-flight al cambiar `behavior_mode`. | 2-3d | abierto |
| P4 | 🟠 | Per-stage permissions. | 3d | abierto |
| P5 | 🟠 | Stage-level workflow trigger preview. | 1-2d | abierto |
| P6 | 🟠 | Dependency view dentro del stage editor. | 0.5d | abierto |
| P7 | 🟡 | Bulk move N customers. | 1d | abierto |
| P8 | 🟡 | Stage templates / clone from another tenant. | ~1w | abierto |
| P9 | 🟡 | Confirmation dialog al toggle behavior_mode / pause_bot. | 1d | abierto |
| P10 | 🟡 | Conflict detection entre auto-enter rules. | 1d | abierto |
| P11 | 🟡 | Search / filter dentro del editor cuando pipeline > 20 stages. | 0.5d | abierto |
| P12 | 🟡 | Invalidación de cache de pipeline al PUT — runner relee cada turno, pero falta evento Redis para alta concurrencia. | 1d | abierto |
| ~~P13~~ | — | ~~"Cargar más" en kanban~~ | — | ✅ **cerrado por Sprint C.3 (`cddacf1`)** |

---

## 4. AI Agent — Editor + guardrails + KB scoping + monitor

**Archivos auditados:** `frontend/src/features/agents/components/AgentsPage.tsx (3832 — creció +1600 LOC con Operations Center)` + `VersionHistoryDrawer.tsx (446)` + `core/atendia/api/agents_routes.py (2053)`.

### 4.1 Qué funciona hoy

- **Operations Center con 7 tabs.**
- **Agent list / cards**, compare-mode (pick two agents).
- **Identidad panel**: name/role/tone/style/language/max_sentences/objective/no_emoji/return_to_flow/is_default; 12 intent toggles.
- **Prompt maestro**: textarea + collapsible "Prompt enviado al LLM".
- **Guardrails reales** (severity, enforcement_mode, allowed/forbidden examples, inline test). Runner appendea como "REGLAS QUE NO PUEDES ROMPER".
- **Knowledge scoping real** (per-collection checkbox; runner filtra FAQ + catalog por `collection_ids`).
- **LLM preview / test chat** real con `POST /agents/{id}/preview-response`.
- **Monitor real** (active_conversations_24h, turns_24h, cost_24h, avg_latency_ms).
- **Behavior modes** (normal/conservative/strict), **Validation pre-publish**, **Compare panel**, **Keyboard shortcuts**, **Lifecycle ops**, **Version history drawer**, **Read-only Extraction panel**, **Asignación de agente a conversación efectiva**.
- **🆕 Smoke render-test** para `AgentsPage.tsx` (Sprint B.1).
- **🆕 NYIButton hidden por defecto** — los 3 NYI en AgentsPage (Abrir, Subir documento, Ver fallidas) ya no se muestran salvo con `VITE_SHOW_NYI=true` (Sprint B.2).

### 4.3 Gaps priorizados

| # | Sev | Gap | Costo | Status |
|---|---|---|---|---|
| ~~A1~~ | — | ~~Version history + rollback picker~~ | — | ✅ cerrado |
| A2 | 🔴 | Side-by-side prompt diff entre versiones (word-level). | 3-4d | abierto |
| A3 | 🔴 | A/B test dos prompt variants contra mismo input. | 4-5d | abierto |
| A4 | 🔴 | Sandbox replay — re-correr last N conversaciones contra nuevo prompt sin side effects. | 5-7d | abierto |
| A5 | 🟠 | Per-action RBAC. | 3-4d | abierto |
| A6 | 🟠 | Tool / action usage stats. | 2-3d | abierto |
| A7 | 🟠 | KB source priority order + per-source citation en test chat. | 2-3d | abierto |
| A8 | 🟠 | Token / cost meter por conversación. | 1-2d | abierto |
| A9 | 🟠 | Latency budget / SLO alerts. | 1d | abierto |
| A10 | 🟠 | Audit log de prompt edits con autor + razón. | 2-3d | abierto |
| A11 | 🟡 | Confirmation dialog antes de publish. | 1d | abierto |
| A12 | 🟡 | Live monitor drill-down (failures, fallbacks, guardrail trips). | 2-3d | abierto |
| A13 | 🟡 | Error inspector / failure trace. | 1-2d | abierto |
| A14 | 🟡 | "Why did the agent say X" link desde mensaje outbound → AgentEditor con prompt + retrieval trace. **Cheap glue** post-C2. | 0.5-1d post-C2 | abierto |
| A15 | 🟡 | Cross-tenant prompt template library. | 4-5d | abierto (post-PMF) |

---

## 5. Workflows — Editor + triggers + nodes + simulator

**Archivos auditados:** `frontend/src/features/workflows/components/*` (~2800 LOC) + `core/atendia/api/workflows_routes.py (1784)` + `core/atendia/workflows/engine.py`.

### 5.1 Qué funciona hoy

- **List page**: health score, 24h metrics, suggested_actions, sparklines, draft vs published.
- **Visual canvas** (DAG con arrows, branching layout, pan/zoom).
- **Triggers (16 wired):** message_received, conversation_created/closed, webhook_received, tag/field_updated, field_extracted, stage_entered/changed/exited, appointment_created, bot_paused, document_accepted/rejected, docs_complete_for_plan, human_handoff_requested.
- **Node types con UI forms (9):** template_message/message, assign_agent, move_stage, delay, condition, branch, http_request, jump_to, end.
- **Branch editor**, **Variables tab**, **Dependencies tab**, **Simulator panel** (reparado en `704f671`), **Execution history**, **Node metrics**, **Safety rules** (7), **Pause modes** (4), **Import/export**, **Validation pre-flight**, **Idempotent actions**, **24h WhatsApp window check**, **Trigger inline en runner**, **PublishDialog**, **VersionCompareDialog**, **NextBestFixPanel**.
- **🆕 Smoke render-test** para `WorkflowsPage.tsx` (Sprint B.1).
- **🆕 NYIButton hidden** (Sprint B.2) — los 6 NYI restantes ya no surface en prod.

### 5.3 Gaps priorizados

| # | Sev | Gap | Costo | Status |
|---|---|---|---|---|
| ~~W1,11,12~~ | — | ~~Visual canvas / confirm publish / rollback diff~~ | — | ✅ cerrados |
| W2 | 🔴 | Visual debugger / step-through. | ~1.5w | abierto |
| W3 | 🟠 | Per-node retry policy. | 2-3d | abierto |
| W4 | 🟠 | Design-time loop detection. | 1.5d | abierto |
| W5 | 🟠 | Reverse dependency view: "qué workflows referencian este agent". | 1-1.5d | abierto |
| W6 | 🟠 | Sub-workflow step ("Trigger Another Workflow"). | ~1w | abierto |
| W7 | 🟠 | Update Field / Pause Bot UI forms. | 1d | abierto |
| W8 | 🟠 | Ask Question step. | 3-4d | abierto |
| W9 | 🟡 | Canvas comments / annotations. | 1.5d | abierto |
| W10 | 🟡 | Auto-layout para arrows. | 2-3d | abierto |
| W13 | 🟡 | Test-mode que no dispare HTTP / sends reales. | 1.5d | abierto |
| W14 | 🟡 | Inline variable picker / autocomplete. | 1.5d | abierto |
| W15 | 🟡 | Node-disabled visual indicator. | 0.5d | abierto |
| W16 | 🟡 | Execution log export. | 1d | abierto |
| W17 | 🟡 | Performance hints. | 1d | abierto |
| ~~W18~~ | — | ~~6 NYI restantes en WorkflowsPage~~ | — | ✅ **mitigado por Sprint B.2** (`8577fad` esconde NYIButton por flag); cablearlos sigue abierto si se quiere |

---

## 6. Knowledge Base — Colecciones + CRUD + RAG + command center

**Archivos auditados:** `frontend/src/features/knowledge/components/KnowledgeBasePage.tsx (2261)` + `core/atendia/api/knowledge_routes.py (819)` + `core/atendia/api/_kb/{command_center.py (1300+ post-Sprint), search.py, test_query.py, collections.py}` + `core/atendia/tools/rag/*`.

### 6.1 Qué funciona hoy

- **9 colecciones**: FAQs, Catálogo, Documentos, Promociones, Reglas de crédito, Preguntas sin respuesta, Conflictos, Pruebas, Métricas.
- **CRUD legacy** (FAQs / catalog / documents).
- **Indexing pipeline**: pgvector 0.8.2 + halfvec(3072) + HNSW (halfvec_cosine_ops).
- **`/test` query**: RAG real con fallback ILIKE.
- **🆕 `/simulate` con búsqueda KB real** (Sprint A.4) — ILIKE sobre FAQs/catálogo/chunks; mantiene empty-state stub para tenants sin contenido.
- **Command center** (9 tabs). **🆕 `/audit-logs` lee `events` real** + **🆕 `/conflicts` lee `kb_conflicts` real** (Sprint B.3, `db4fb8c`) — order by severity + tenant isolation pinned.
- **RAG foundation**: provider, retriever, prompt builder, conflict detector, risky phrase detector.
- **Source citation con confidence scoring**.
- **Per-agent KB scoping**.
- **Knowledge testing playground**.
- **🆕 `search_catalog` determinístico** (Sprint C.6) — order by sku rompe ties de alias colisionado.
- **🆕 Smoke render-test** para `KnowledgeBasePage.tsx` (Sprint B.1).

### 6.3 Gaps priorizados

| # | Sev | Gap | Costo | Status |
|---|---|---|---|---|
| K1 | 🔴 | Workers cron incompletos: conflicts, health snapshots, expire de catalog, regression tests, import. | ~1w | abierto |
| K2 | 🔴 | Si arq worker está caído, documento queda en `status="error"` y nunca se reindexa. Falta retry policy + UI dead-letter. | 1-2d | abierto |
| K3 | 🟠 | Knowledge testing playground más visual. | 3-4d | abierto |
| K4 | 🟠 | Source priority order por colección. | 2d | abierto |
| K5 | 🟠 | Per-source toggle inverso: desde KB ver qué agentes consumen una colección. | 1d | abierto |
| K6 | 🟠 | Prompt templates module (Snippets + Closing Notes). | ~1w | abierto |
| K7 | 🟡 | Stale knowledge detection. | 2d | abierto |
| K8 | 🟡 | Knowledge versioning. | 3-4d | abierto |
| K9 | 🟡 | Hallucination guard explícito con composer output validation. | 3-5d | abierto |
| ~~K10~~ | — | ~~Catalog disambiguation (search_catalog `limit=1` no determinista)~~ | — | ✅ **cerrado por Sprint C.6 (`0611753`)** |

---

## 7. Lo que NO entra ahora (acordado, NO planear hasta nuevo aviso)

| Diferido | Por qué luego | Cuándo retomar |
|---|---|---|
| **Broadcasts / campañas masivas** | No vende solo; depende de tener el chatbot bien primero. | Post-PMF del chatbot. |
| **Multi-canal** (IG DM, FB Messenger, Web widget, Email, SMS, Voz) | El cliente quiere WhatsApp. El adapter pattern del `core/atendia/channels/` ya soporta agregar. | Cuando un cliente concreto pague por otro canal. |
| **Multi-vertical out-of-the-box** | Cada vertical son ~6 inserts. Lo hacemos a mano por ahora. | Cuando tengamos 3+ verticales en producción. |
| **Mobile app** | Operadores trabajan en desktop. | Post-PMF. |
| **AI Credits / billing infra** | No facturamos por token al cliente final. | Cuando metas autoservicio. |
| **SSO + Organizations** | 1 tenant = 1 negocio. | Cuando ataquemos enterprise. |
| **Marketplace de integraciones** | YAGNI. | Cuando tengamos 10+ tenants pidiendo lo mismo. |

---

## 8. Diferenciadores: lo que ya tenemos y respond.io NO tiene en su core

1. **Pipeline editor con `behavior_mode` por stage** (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT).
2. **Vision auto-write mapping** (clasificación de imagen → DOCS_* del cliente).
3. **Plan-doc requirements + `docs_complete_for_plan` operator**.
4. **AI Field Extraction con confidence tiers** (AUTO / SUGGEST / SKIP) y panel de revisión.
5. **System Event Bubbles tipados** en el chat (7 tipos con color/icono).
6. **Guardrails con severity + enforcement_mode** (block/rewrite/warn/handoff).
7. **Anti-downgrade en Vision**.
8. **Baileys QR como canal alterno** al Meta Cloud API oficial.
9. **Turn traces narrativos en español** + costos/latencias por componente.
10. **Pipeline + Agent + Workflow versioning con drawer de history**.
11. **🆕 DB-backed advisors + vehicles tenant-scoped** (Sprint A.2) — respond.io no tiene catálogo de asesores configurable por tenant.
12. **🆕 Appointment reminder scheduler** (Sprint B.4) — cron arq dispara 24h antes con event audit; respond.io requiere armarlo a mano vía workflows.

---

## 9. Decision Matrix — qué falta en su totalidad

### 🔴 Decisiones que **bloquean** trabajo (necesitan acuerdo antes de tocar código)

| # | Item | Bloqueador | Opciones | Costo |
|---|---|---|---|---|
| **D1** | **C.5 Forgot password** | Falta proveedor de email | a) Resend (~$0.001/email, $20/mes free)<br>b) SendGrid (~$15/mes)<br>c) SMTP propio (frágil)<br>d) Diferir hasta tener clientes "reales" pidiendo | ~1 sesión backend + ~1 frontend |
| **D2** | **3d.2 WhatsApp Templates >24h** (Sprint A.5 diferido) | Plantillas aprobadas por Meta | a) Crear 3 plantillas mínimas (welcome, follow-up, reminder)<br>b) Esperar tráfico real para informar el set | ~30 commits / 2-3 sesiones |
| **D3** | **C.1 Playwright en CI** | Decisión de infra | a) Job paralelo (+5min CI, ~300MB cache)<br>b) Nightly only<br>c) Local-only hasta tener regresiones reales | ~1 sesión CI |
| **D4** | **3d.3 Outbound multimedia** | Meta lookaside es 1h TTL | a) S3 / R2 (~$5/mes)<br>b) PostgreSQL bytea (mala idea)<br>c) Local volume (mala UX) | ~1-2 sesiones |

### 🟡 Decisiones de **alcance** (no bloqueantes pero materiales)

| # | Item | Status actual | Acción | Costo |
|---|---|---|---|---|
| **D5** | **C.7 Runner-composer reconciliation** | Dual: runner dispatch action-based, composer mode-based | a) Migrar runner a mode-based<br>b) Migrar composer a action-based<br>c) Dejar dual (deuda permanente) | T30+ = 4-6 sesiones |
| **D6** | **C.9 HandoffReason 4 valores forward-contract** | Composer prompts piden `suggested_handoff=...`, runner NO lo lee | a) Wire (receta en docstring `1571a8e`, ~1 sesión)<br>b) Mantener si no hay user pain | 1 sesión |
| **D7** | **Sprint B.1 happy-paths** | Solo smokes "renders without crash" | a) Agregar 1 user-interaction por página (~12 tests)<br>b) Dejar smokes hasta tener regresiones | ~1 sesión |
| **D8** | **B.4 entrega real WhatsApp** del reminder | Scheduler dispara + evento; provider noop | Bloqueado por D2 (templates) | — |

### 🟢 Quick wins **listos para tomar** (1-3 commits c/u)

| # | Item | Status |
|---|---|---|
| **D9** | Bug pre-existente migration 026: `created_by_type` default = `'''user'''` (3 comillas literales) → viola check constraint en raw INSERT | Migration nueva: `ALTER COLUMN ... SET DEFAULT 'user'` |
| **D10** | 8 TS errors pre-existentes en `DocumentRuleBuilder.test.tsx` (falta prop `catalog`) | Pasar `catalog={[]}` en cada render |
| **D11** | Frontend lint baseline: 1840 errores ruff. CI debería estar rojo o el step se está saltando | Verificar CI status, decidir fix masivo vs baseline-file vs disable selectivo |

### ⚪ Diferido **explícitamente** (status quo aceptable)

| # | Item | Razón |
|---|---|---|
| **D12** | Catalog disambiguation UX layer | C.6 resolvió la non-determinism; mostrar "esta alias mapea a N SKUs, ¿cuál?" es un feature distinto |
| **D13** | Knowledge `/test` (embeddings) vs cockpit `/simulate` (ILIKE) | Ambos viven; cockpit prioriza determinismo offline, `/test` prioriza relevancia |

---

## 10. Verificación

```powershell
# Re-check line counts cuando este doc se sienta stale
Get-ChildItem -Recurse frontend/src/features/{pipeline,agents,workflows,conversations,turn-traces,knowledge}/components/*.tsx |
  ForEach-Object { "{0,6} {1}" -f (Get-Content $_.FullName | Measure-Object -Line).Lines, $_.FullName }

# Bring v2 up
powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1

# Demo creds
# admin@demo.com / admin123 (tenant_admin, tenant demo con seed mock)
# superadmin@demo.com / admin123 (superadmin, mismo tenant)
# dele.zored@hotmail.com / dinamo123 (superadmin, tenant fresco sin seed)

# Sprint A/B/C verification
cd core
uv run pytest tests/api/test_exports_routes.py tests/db/test_advisor_vehicle_providers.py \
              tests/api/test_advisors_vehicles_routes.py tests/api/test_baileys_routes.py \
              tests/api/test_kb_simulate_real.py tests/api/test_kb_audit_conflicts_real.py \
              tests/queue/test_appointment_reminder_worker.py tests/api/test_pipeline_routes.py \
              tests/api/test_turn_traces_routes.py tests/tools/test_search_catalog_real.py -v
# expected: 80+ passed

# CI coverage report
# Push to a PR branch and check the "Coverage" section in the workflow summary
```

---

## 11. Working contract (heredado del trust-break del 2026-05-08, sigue vigente)

| Regla | Por qué |
|---|---|
| **Una pieza por sesión.** Más scope → preguntar primero. | Phase 4 entregó 60 tasks en una tanda y oversold "complete". |
| **"Done" sólo cuando se verifica en el browser/CLI.** Si reduje scope, lo digo explícito. | Múltiples T-tasks aterrizaron en minimum-viable y se llamaron done. |
| **El usuario decide qué cortar.** Estimo costo (1h / 1d / 1w), él decide. | Sesiones previas decidían unilateralmente skip de Tremor, Storybook, browser notifications, full E2E. |
| **No emojis verdes hasta verificar.** Summary = qué cambió + path + cómo verificar. | Tono auto-celebratorio tapaba que el deliverable era thin. |
| **No code-reviewer agent salvo que se pida.** | Sesiones previas corrían review en Block A y C+D; el resto sin nada. |
| **Branch por feature, mostrar diff antes de merge.** | Sesiones previas pusheaban directo a main. |
| **TDD para implementación de feature/bugfix.** Test RED primero, GREEN después. | Sprint A/B/C entregó ~69 tests nuevos siguiendo esta regla. |
| **Verificación antes de claim.** Run la suite, lee el output, después afirma. | Skill `verification-before-completion` requiere evidencia, no confianza. |

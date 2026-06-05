# Frontend Config Surface Audit - DB Verified

Date: 2026-06-02

Tenant:

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- email: `dinamomotosnl@gmail.com`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`

## Executive Verdict

The Dinamo frontend configuration surfaces are now DB-verified for the main data paths and safe for screenshot review. Two scoped fixes were made:

1. `/knowledge/items` now returns all Knowledge OS v2 sources instead of accidentally filtering to the last collection label.
2. `/expediente` now parses and serializes canonical pipeline document config keys: `document_requirements_field` and `document_requirements`.

No WhatsApp send, auto-send, manual-send, outbox enqueue, workflow event, or action execution path was enabled.

Final readiness:

- `ready_for_screenshot_review`: yes, with noted UI gaps
- `ready_for_live_preview`: conditional; simulation says true, but readiness suite still reports not fully passed
- `ready_for_shadow`: conditional but not enabled
- `ready_for_manual_send`: no

## DB Precheck

Precheck report: `docs/reports/db_backed_frontend_config_precheck_2026_06_02.md`

Result:

- Postgres reachable on host port `5433`.
- Alembic head: `read1nessv2`.
- Tenant found: `Dinamo Motos NL`, active.
- Tenant admin email found in `tenant_users`: `dinamomotosnl@gmail.com`.
- Agent found: `Francisco de Dinamo NL`, production.
- Tenant config keeps runtime v2 preview/safety flags disabled for send paths.

Operational note: the original Docker backend with reload crashed because `/app/.pytest_cache` has permission errors under watchfiles. A no-reload backend container, `atendia_backend_noreload`, is running on port `8001`.

## Surface Matrix

| Surface | DB/API Status | UI Status | Verdict |
| --- | --- | --- | --- |
| `/knowledge` | 5 sources verified | Unit test passed | PASS |
| `/catalog` | 34 products, 136 plans verified | API verified | PASS |
| `/expediente` | 7 doc cases and 9 catalog docs verified | Parser fixed, unit test passed | PASS with visual pending |
| `/workflows` | 4 inactive workflows verified | UI test passed | PASS |
| `/customer-fields` | 11 fields, no duplicates | API verified | PASS |
| `/pipeline` | 8 stages verified | API verified | PASS |
| `/composer` | Pipeline guidance verified | Decision documented | PASS as preview/config only |
| `/agents` | Studio data verified | Some widgets need badges | PARTIAL |
| ContactPanel | Backend contract ready | Frontend render gap | PARTIAL |

## Knowledge

DB sources:

- `catalogo_dinamo`: Catalogo, 34 items, 34 chunks, retrieval enabled
- `requisitos_dinamo`: Credito, 7 items, 13 chunks, retrieval enabled
- `faq_dinamo`: FAQ, 26 items, 26 chunks, retrieval enabled
- `prompt_agente_dinamo`: Non-factual, 1 item, 8 chunks, retrieval disabled
- `flujo_dinamo_orden_caos`: Non-factual, 1 item, 18 chunks, retrieval disabled

Fix: `core/atendia/api/_kb/command_center.py` no longer shadows the endpoint `collection` filter while building source labels. Chunk counts now use distinct Knowledge OS chunk IDs.

## Catalog

DB/API verified:

- Catalog: `Catalogo Dinamo 2026`
- Products: 34
- Plans: 136
- `R4 250 CC`: base `52700.00`, list `55335.00`, plans `10%, 15%, 20%, 30%`
- `Comando 400 CC`: base `79900.00`, list `83895.00`, plans `10%, 15%, 20%, 30%`

## Expediente

DB/API verified:

- Field: `Plan_Credito`
- Cases: `Contado`, `Guardia`, `Pensionado`, `Negocio SAT`, `Nomina Recibos`, `Nomina Tarjeta`, `Sin Comprobantes`
- Documents catalog: 9 entries

Frontend fix: `frontend/src/features/expediente/components/ExpedientePage.tsx` now accepts canonical API keys and preserves legacy keys on serialize for compatibility.

Browser note: the in-app browser reached the login screen. Authenticated visual review could not be completed because cookie/context mutation was not available through the browser wrapper. API-authenticated evidence and unit tests verify the data path.

## Workflows

DB/API verified workflows:

- `workflow_doc_completos_handoff`: inactive, trigger `field_updated`, mode `preview_only`
- `workflow_galgo_close`: inactive, trigger `field_updated`, mode `preview_only`, close node disabled
- `workflow_sistema_manual`: inactive, trigger `manual_only`, stage `sistema`
- `workflow_cliente_cerrado_manual`: inactive, trigger `manual_only`, stage `cliente_cerrado`

No workflow was executed.

## Customer Fields

11 definitions verified, no duplicate keys.

Expected fields:

- `Cumple_Antiguedad`
- `Plan_Credito`
- `Plan_Enganche`
- `Moto`
- `Doc_Incompletos`
- `Doc_Completos`
- `Autorizado`
- `Cotizacion_Enviada`
- `Ultima_Cotizacion`
- `Docs_Checklist`
- `Handoff_Humano`

Special render/validation:

- `Moto`: `catalog_item`, validation `must_exist_in_catalogo_dinamo`
- `Ultima_Cotizacion`: `quote_card`, JSON value
- `Docs_Checklist`: `document_checklist`, JSON value
- `Autorizado`: human-only

## Pipeline And Composer

Pipeline stages verified:

1. `nuevos`
2. `plan`
3. `cliente_potencial`
4. `papeleria_incompleta`
5. `papeleria_completa`
6. `galgo`
7. `sistema`
8. `cliente_cerrado`

Terminal/manual behavior:

- `galgo`: terminal
- `sistema`: manual and terminal
- `cliente_cerrado`: manual and terminal

Composer decision:

- Keep as tenant-scoped stage/operator guidance.
- Do not use it as final customer-facing copy authority.
- Runtime v2 final answer authority remains `TurnOutput.final_message`.

## Agents

Agent Studio real-data panels are acceptable:

- Agent identity/config
- Knowledge sources
- Contact fields
- Lifecycle stages
- Action definitions/options, configuration only

Gaps:

- `GET /api/v1/agents/{agent_id}/workflows` returns `[]` even though the tenant has 4 workflows.
- Health, coverage, scenarios, risk, and onboarding widgets need DB-evidence badges or hiding before operator trust.

## ContactPanel

Backend contract is ready. Conversation detail field presentation includes:

- `group`
- `render_mode`
- `render_payload`
- `display_order`
- `is_debug`

Frontend gap: `ContactPanel.tsx` still renders configured fields mostly as generic rows and does not fully use group/render payloads for quote cards and document checklist cards.

## Simulation

Simulation report:

- `docs/reports/dinamo_frontend_config_surface_simulation_2026_06_02.md`
- `docs/reports/dinamo_frontend_config_surface_simulation_2026_06_02.json`

Result:

- pass: true
- cases_passed: 12
- cases_failed: 0
- overall_score: 1.0
- placeholders: 0
- real_side_effects: 0
- outbound_outbox: 0
- whatsapp_sends: 0
- action_execution_logs: 0
- workflow_executions: 0
- real_customers: 0
- simulation_run_id: `6ad1b695-d09e-4b93-a6e0-278af39b8446`

## Tests

Passed:

- `uv run --group dev ruff check atendia/api/_kb/command_center.py atendia/api/knowledge_routes.py atendia/api/workflows_routes.py tests/api/test_knowledge_routes.py`
- `uv run python -m py_compile atendia/api/_kb/command_center.py atendia/api/knowledge_routes.py atendia/api/workflows_routes.py`
- `pytest tests/api/test_knowledge_routes.py -q`: 14 passed
- `pytest tests/api/test_agent_test_turn_v2.py -q`: 13 passed
- `pytest tests/api/test_agent_runtime_v2_conversation_preview.py -q`: 20 passed
- `pytest tests/contact_memory -q`: 11 passed
- `pytest tests/lifecycle -q`: 8 passed
- `pytest tests/simulation -q`: 24 passed
- `pytest tests/knowledge_os -q`: 20 passed
- `npm run test -- --run tests/features/knowledge/KnowledgeBasePage.test.tsx tests/features/workflows/WorkflowsPage.test.tsx tests/features/expediente/ExpedientePage.test.ts`: 4 passed
- `npm run typecheck`: passed
- `npm test -- --run --exclude tests/e2e/smoke-routes.spec.ts`: 58 files, 235 tests passed

Blocked or pre-existing failures:

- Broad backend ruff over `atendia/knowledge atendia/agent_runtime atendia/contact_memory atendia/simulation tests` failed with existing test lint debt.
- Default `npm test -- --run` includes a Playwright spec under Vitest and fails before app unit assertions.
- Docker reload backend fails on `.pytest_cache` permission under watchfiles.

## Remaining Gaps

1. Fix authenticated browser verification or run Playwright with the existing e2e login/session path.
2. Render ContactPanel groups and specialized `quote_card` / `document_checklist` payloads in the frontend.
3. Fix agent linked workflows endpoint.
4. Badge or hide heuristic Agents dashboard widgets.
5. Move or exclude Playwright e2e specs from the default Vitest command.
6. Resolve broad backend ruff debt in tests.


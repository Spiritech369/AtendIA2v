# Frontend Config Surface Audit Final - 2026-06-02

## Executive Summary

This pass fixed the main API/UI mismatches observed in Knowledge, Catalog, and Workflows without enabling any real side effects. The remaining work is DB-backed verification, screenshot review, and a complete product pass over Pipeline/Composer/Agents labels.

## Screens Fixed

- `/knowledge`: default view now shows all sources; `/knowledge/items` includes Knowledge OS v2 sources.
- `/catalog`: `/knowledge/catalog` now includes active commercial catalog products and plans, not only legacy `tenant_catalogs`.
- `/workflows`: missing node `config`/`intent` no longer crashes the page.

## Screens Hidden/Marked Legacy

No navigation was changed in this pass. Recommendation: mark `/composer` as Legacy for v2 tenants or fold it into Pipeline/Agent Studio as stage guidance.

## Knowledge Status

Expected visible factual sources:

- `catalogo_dinamo`
- `requisitos_dinamo`
- `faq_dinamo`

Expected visible non-factual sources:

- `prompt_agente_dinamo`
- `flujo_dinamo_orden_caos`

The API now exposes Knowledge OS v2 sources in `/knowledge/items`; DB verification is blocked by Postgres connection refusal in this environment.

## Catalog Status

`/knowledge/catalog` now reads published official catalog rows from commercial catalog tables and maps plans to the existing UI payload. This aligns `/catalog` with QuoteResolver's commercial catalog path.

## Expediente Rules Status

No code change was needed in `/expediente` in this pass. Existing setup script defines `Plan_Credito`, seven cases, and the requested document matrix. DB verification remains blocked.

## Pipeline/Composer Decision

Pipeline remains active. Composer should be treated as stage guidance only and never as customer-facing final copy authority.

## Workflows Crash Fix

Fixed via backend definition normalization and frontend optional config handling. Draft/disabled workflows should load even when older nodes have no intent.

## Customer Fields Status

Expected official fields:

- Commercial: `Cumple_Antiguedad`, `Plan_Credito`, `Plan_Enganche`, `Moto`, `Doc_Incompletos`, `Doc_Completos`, `Autorizado`
- Technical: `Cotizacion_Enviada`, `Ultima_Cotizacion`, `Docs_Checklist`, `Handoff_Humano`

ContactPanel grouping appears implemented in backend presentation code, but screenshot/DB verification is pending.

## Simulation Results

Attempted:

`uv run python -m atendia.simulation.run_dinamo_frontend_review ... --no-whatsapp --no-outbox`

Result: failed before running cases because DB precheck hit `ConnectionRefusedError` twice. Real side effects observed: 0.

## Tests Executed

- `npm run test -- --run tests/features/workflows/WorkflowsPage.test.tsx tests/features/knowledge/KnowledgeBasePage.test.tsx`: passed.
- `npm run typecheck`: passed.
- `uv run --group dev ruff check atendia/api/knowledge_routes.py atendia/api/_kb/command_center.py atendia/api/workflows_routes.py tests/api/test_knowledge_routes.py`: passed.
- `uv run python -m py_compile atendia/api/knowledge_routes.py atendia/api/_kb/command_center.py atendia/api/workflows_routes.py`: passed.
- `uv run --group dev pytest tests/api/test_knowledge_routes.py -q`: blocked by Postgres `ConnectionRefusedError`.

## Remaining Gaps

- Run backend/API tests with Postgres online.
- Run full frontend review simulation and screenshot review.
- Verify `/expediente`, `/customer-fields`, `/agents`, and ContactPanel against the actual Dinamo tenant DB.
- Rename/badge `/composer` and pipeline composer mode labels for v2 tenants.
- Mark any remaining mock widgets explicitly.

## Decision Criteria

- ready_for_screenshot_review: yes, conditional on DB/dev server availability.
- ready_for_live_preview: no, until DB-backed verification and simulation pass.
- ready_for_shadow: no.
- ready_for_manual_send: no.


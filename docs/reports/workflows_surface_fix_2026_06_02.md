# Workflows Surface Fix - 2026-06-02

## Problem

`/workflows` could crash with `Cannot read properties of undefined (reading 'intent')` when a workflow node had no `config` object or a legacy detect-intent node had no `intent`.

## Changes

- Backend `_item()` now returns a normalized workflow `definition`:
  - `nodes` and `edges` are always arrays.
  - non-object nodes/edges are dropped from the UI payload.
  - every node gets `id`, `type`, and `config`.
  - missing `detect_intent.config.intent` becomes `Sin intent`.
- Frontend `WorkflowEditor.summaryFor()` now uses `node.config ?? {}` and falls back to `Sin intent`.
- Frontend `workflowsApi.list()` accepts both legacy `{ items: [...] }` and direct array responses.

## Dinamo Workflows Expected

| Workflow | Required State | Side Effects |
|---|---|---|
| `workflow_doc_completos_handoff` | draft/disabled | no real handoff execution |
| `workflow_galgo_close` | draft/disabled | no real close/send |
| `workflow_sistema_manual` | draft/disabled | manual only |
| `workflow_cliente_cerrado_manual` | draft/disabled | manual only |

## Validation

- `npm run test -- --run tests/features/workflows/WorkflowsPage.test.tsx tests/features/knowledge/KnowledgeBasePage.test.tsx`: passed.
- `npm run typecheck`: passed.
- Backend DB tests could not run because Postgres refused connection.


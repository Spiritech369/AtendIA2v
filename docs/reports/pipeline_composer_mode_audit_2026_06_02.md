# Pipeline Composer Mode Audit - DB Verified

Date: 2026-06-02

Tenant:

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- email: `dinamomotosnl@gmail.com`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`

## Verdict

`/pipeline` is DB-backed for Dinamo and exposes the expected 8 stages. The tenant pipeline config also contains composer guidance (`composer`, `mode_labels`, `mode_prompts`) that should be treated as stage guidance for runtime v2, not as final customer copy.

No WhatsApp send, outbox enqueue, manual-send, workflow execution, or action execution was enabled during this audit.

## DB Evidence

Active tenant pipeline config returned:

- `document_requirements_field`: `Plan_Credito`
- 7 document requirement cases:
  - `Contado`: 0 required docs
  - `Guardia`: 4 required docs
  - `Pensionado`: 4 required docs
  - `Negocio SAT`: 4 required docs
  - `Nomina Recibos`: 3 required docs
  - `Nomina Tarjeta`: 4 required docs
  - `Sin Comprobantes`: 2 required docs
- `documents_catalog`: 9 entries
- `composer`: present
- `mode_labels`: present
- `mode_prompts`: present

## API Evidence

`GET /api/v1/pipeline/stages` returned 8 stages:

1. `nuevos`
2. `plan`
3. `cliente_potencial`
4. `papeleria_incompleta`
5. `papeleria_completa`
6. `galgo`
7. `sistema`
8. `cliente_cerrado`

`GET /api/v1/pipeline/board` returned 200. The board marks `galgo`, `sistema`, and `cliente_cerrado` as terminal. The board includes simulation-created conversations, not real customer traffic from this audit.

## Composer Mode Classification

`composer`, `mode_labels`, and `mode_prompts` are real tenant-scoped configuration. They should orient stage behavior and composer UI copy, but they must not become the authority for customer-facing final text. Runtime-visible final copy remains `TurnOutput.final_message`.

Recommended classification:

- Stage behavior guidance: REAL_DATA
- Stage labels/prompts for operator UX: REAL_DATA
- Customer-facing output authority: NOT_COMPOSER, use `TurnOutput.final_message`
- Legacy duplicated composer widgets: hide or badge when not backed by the active pipeline config

## Risks And Gaps

- `/composer` should avoid presenting legacy/static hints as if they were active runtime copy.
- Any preview of generated customer copy must clearly route through runtime v2 preview/test-turn APIs.
- No composer surface should write customer-visible final text directly.


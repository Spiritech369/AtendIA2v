# Pipeline Automation Editor — Implementation Plan

**Date:** 2026-05-13
**Author drafted by:** Claude Opus 4.7 from user-supplied spec
**Status:** Awaiting milestone selection

## Vision (user's words)

> El Pipeline Editor debe convertirse en el lugar donde defines el "estado
> del proceso" y las condiciones para avanzar. El bot no debería decidirlo
> con lógica suelta en prompts; debe actualizar campos, y el motor de
> reglas del pipeline decide cuándo mover la conversación.

Each stage becomes a **declarative operational state** with auto-enter
rules. The bot's job is to extract structured fields into
`conversation_state.extracted_data`. The pipeline rule engine watches
those fields and moves the conversation between stages when conditions
match. Stage transitions stop being LLM-output side effects; they become
a deterministic function of state.

## Why split into milestones

The full spec the user wrote up touches ~16 frontend components, 8
backend models, 10 API endpoints, a rule evaluator, an audit subsystem,
and impact-analysis tooling. Honest estimate: ~5–8 focused sessions.
Trying to land it in one PR would mean a big-bang merge with weak
verification at each step. Slicing it lets us ship value incrementally
and ship something usable to `dele.zored` after each milestone.

## Inventory of what already exists

Before scoping new work, what's already in main today:

- `tenant_pipelines` table with JSONB `definition` and per-tenant
  versioning. PUT creates a new version, deactivates prior ones.
- `PipelineEditor` component with stage CRUD on a local draft, drag-to-
  reorder, JSON preview, "documentos por plan" editor, save mutation.
- Per-stage three-dot menu with Subir / Bajar / Copiar stage_id /
  Duplicar / Eliminar (etapa) — landed in commit `633b41c`.
- `PipelineKanbanPage` with drag-to-stage + empty-state that opens the
  editor inline when no pipeline exists.
- Backend `validate_definition` + `validate_references` in
  `core/atendia/workflows/engine.py` for workflow node configs that
  reference stage ids. This is the right model to reuse for stage-
  level rule validation.
- Event emitters for `message_received`, `field_extracted`, and
  `stage_changed` already exist in `core/atendia/state_machine/`.
- Audit log infra (`emit_admin_event`) already used by workflow routes.

## Milestone slicing

Each milestone is self-contained (ships value + tests). User picks the
order; default order below is risk-first (foundation before UI).

### M1 — Schema + rule storage (no UI changes)

**Goal:** the JSONB pipeline definition supports `auto_enter_rules` on
each stage; saving + loading round-trips the new fields.

**Tasks:**
- Extend `validate_definition` to accept stage objects with optional
  `auto_enter_rules: {enabled, match, conditions[]}`.
- Add validator for each condition: field non-empty, operator in
  allow-list, value required for non-presence operators.
- Backend tests: round-trip serialization, validation failures.
- Frontend: extend the StageDraft type + parsePipeline/serialise to
  preserve auto_enter_rules. JSON preview already renders whatever
  the draft contains.

**Out of scope:** UI for editing rules (M2), evaluation (M3).

**Why first:** without a stable storage schema, M2 frontend work
would be re-doing serialization shape later.

### M2 — Rule builder UI

**Goal:** operator can configure auto-enter conditions for a stage from
the editor side panel.

**Components to add (inside features/pipeline/components/):**
- `RuleBuilder` — host for one stage's rules, owns enabled toggle and
  match=all|any selector.
- `ConditionRow` — one condition. Renders FieldSelector + Operator
  + ValueInput.
- `FieldSelector` — combobox over known extracted fields; allows free
  text for custom fields the user has been extracting. Seeded from
  the audit doc's catalog: `modelo_interes`, `plan_credito`,
  `tipo_enganche`, `tipo_credito`, `telefono`, `nombre`, `DOCS_*.status`,
  `enganche_confirmado`, `solicitud_sistema_status`.
- `OperatorSelector` — `exists | not_exists | equals | not_equals |
  contains | greater_than | less_than | in | not_in`.
- `ValueInput` — hidden when operator is presence-only; otherwise
  text input (string), with `in`/`not_in` accepting comma-separated
  list parsed into an array.
- `RulePreview` — natural-language summary ("Cuando *plan_credito*
  existe **y** *tipo_enganche* existe").

**Validation surface:**
- A stage with `auto_enter_rules.enabled=true` requires ≥1 condition.
- Non-presence operators require a non-empty value.
- Terminal stages cannot have backward-move conditions (reject if
  `allow_auto_backward=true` and stage `terminal=true`).

**Tests:** vitest for FieldSelector, OperatorSelector, ConditionRow
add/remove, RulePreview natural-language output.

### M3 — Rule evaluation engine (backend)

**Goal:** when contact fields change, the engine evaluates every stage's
`auto_enter_rules` and moves the conversation to the best matching
stage. Audit log entries record every auto-move.

**Tasks:**
- `core/atendia/state_machine/pipeline_evaluator.py` (new):
  - `evaluate_pipeline_rules(session, conversation_id, trigger_event)`
  - `evaluate_condition(condition, fields)` — pure function, easy to test
  - `select_best_stage(matches, current_stage, pipeline)` — prefers
    higher `order`; never moves backward unless `allow_auto_backward`;
    never moves out of a terminal stage; never re-enters the same
    stage.
- Wire-up:
  - State-machine emitter for `field_extracted` already exists; add a
    hook that calls `evaluate_pipeline_rules` inline after each
    extraction (in the same transaction).
  - Same hook on document upload/verify (path TBD — depends on M4).
- Loop guard: max 5 stage transitions per evaluation cycle (caps
  pathological rule sets where stage A's rule matches whenever B's
  matches and vice versa).
- Audit:
  - `conversation_stage_auto_moved` event with `previous_value`,
    `new_value`, `matched_rules` payload.
- Tests:
  - 8+ pure-function tests for `evaluate_condition` covering each
    operator + edge cases (nested fields, null, empty string).
  - Integration test: seed a tenant with a 3-stage pipeline + a
    conversation; extract `modelo_interes` and `plan_credito`;
    assert conversation moves to "Cliente Potencial".

### M4 — Document validation builder

**Goal:** UI for "Papelería completa" stage that ergonomically defines
required documents per credit plan.

**Tasks:**
- `DocumentRuleBuilder` component that lets the operator pick a credit
  plan (the existing `docs_per_plan` map is the input) and check off
  required document statuses (`DOCS_INE.status = ok`, etc).
- Save shape: emits standard `auto_enter_rules.conditions` of
  `field=DOCS_X.status, operator=equals, value=ok` form so the M3
  evaluator handles them with no special-casing.
- No new backend code — reuses M3 evaluator.

### M5 — Impact analysis + safety modals

**Goal:** before destructive ops, surface what will break.

**Tasks:**
- Backend: `GET /pipelines/:id/impacted-references/:stage_id` returns
  `{conversation_count, workflow_refs[], current_stage_count}`.
- Frontend: replace the per-stage delete dialog with one that fetches
  impact and shows:
  - Conversation count in that stage
  - Workflow references (name + id) that mention the stage_id
- Add type-to-confirm pattern for changing a referenced stage_id:
  user must type the literal stage_id to confirm.
- Add UnsavedChangesGuard hook on the route — beforeunload + tanstack-
  router `onLeave` confirmation when local draft has unsaved changes.

### M6 — Audit log drawer

**Goal:** see what changed and who changed it from the editor itself.

**Tasks:**
- Backend: `GET /pipelines/:id/audit-log` (paginated) reading from the
  existing admin_events table filtered to
  `entity_type='pipeline'|'pipeline_stage'`.
- Frontend: `AuditLogDrawer` opened from a clock icon in the editor
  header. Lists entries with actor (user/bot/workflow/system), action,
  previous/new value summary, timestamp.

### M7 — Seed pipeline + smoke

**Goal:** ship a working example so `dele.zored` (and any new tenant)
gets a sensible default.

**Tasks:**
- Modify `seed_zored_user.py` to also seed a starter "Crédito Dinamo"
  pipeline with the stages + rules from the user's spec
  (Cliente Potencial + Papelería completa included).
- Smoke script that simulates an inbound flow: customer says
  "Quiero la moto Z con plan a 36 meses, enganche en efectivo" →
  expects conversation to be in `cliente_potencial` after one turn.

## Out of scope (explicitly NOT in this plan)

- A new CRM, ERP, or dashboard module.
- Cross-pipeline rules (a stage from pipeline A triggering a move in
  pipeline B). Single-pipeline only.
- Visual flow diagram (Sankey / graph view). The Kanban board already
  shows the live state per stage.
- AI-generated rule suggestions. Operator-authored only.
- Pipeline-level versioning beyond what we already have (per-version
  rollback UI). The current PUT-creates-new-version model stays.

## Recommended order

If forced to pick one path, **M1 → M2 → M3 → M5 → M4 → M6 → M7**:

- M1 unblocks M2.
- M2 lets the operator at least *configure* rules, even before they're
  enforced — gives the user a hands-on preview to verify the model is
  what they want.
- M3 lights up actual automatic stage moves.
- M5 prevents accidental damage before M4 broadens what's editable.
- M4 specializes the rule builder for the most-requested case.
- M6 + M7 polish.

## Verification strategy per milestone

Every milestone ships with:
1. Unit tests (vitest for FE, pytest for BE).
2. A manual QA checklist appended to this doc as we go.
3. A short demo path: "Open `/pipeline`, do X, observe Y." Operators
   should be able to follow without reading code.

## Acceptance criteria mapped to milestones

User-supplied criteria from the spec, mapped to where they get satisfied:

| # | Criterion | Milestone |
|---|-----------|-----------|
| 1 | Create new stage | already done |
| 2 | Edit name/color/stage_id/timeout/terminal | already done |
| 3 | Drag-and-drop reorder | already done |
| 4 | Configure automation rules per stage | M2 |
| 5 | Field + document conditions | M2 + M4 |
| 6 | Human-readable preview | M2 (RulePreview) |
| 7 | Live JSON output | already done |
| 8 | Invalid stage_id cannot be saved | already done |
| 9 | Invalid rules cannot be saved | M1 (validator) + M2 (UI block) |
| 10 | Changing stage_id shows impacted workflows + confirms | M5 |
| 11 | Deleting stage with conversations confirms | M5 (current is light) |
| 12 | Field updates trigger rule eval | M3 |
| 13 | Document verification triggers rule eval | M3 (+ M4 for surfacing) |
| 14 | Rules match → current_stage updates | M3 |
| 15 | Manual drag-to-stage still works | already done |
| 16 | Stage changes in audit log | already done (admin_events) |
| 17 | Auto movements in audit log | M3 |
| 18 | Terminal stages prevent backward | M3 |
| 19 | Loop prevention | M3 (5-cycle cap) |
| 20 | No unrelated modules added | trivially — plan is scoped |

## Open questions

These need user input before M1 starts:

1. **Field catalog source of truth.** The spec lists `modelo_interes`,
   `plan_credito`, etc. Should FieldSelector pull these from a static
   constant (faster to ship, drifts) or from
   `customer.attrs` keys observed across the tenant (dynamic, accurate
   for one tenant only)? Recommendation: start static, migrate to
   dynamic later.

2. **Field paths.** `DOCS_INE.status` implies nested access into
   `extracted_data["DOCS_INE"]["status"]`. Current extraction shape
   stores fields flat (`extracted_data["modelo_interes"]["value"]`).
   Do we treat the `.status` suffix as a special parser, or migrate
   extraction to actually nest documents under a parent key?
   Recommendation: treat `<KEY>.<subkey>` parser-side as nested access
   into `customer.attrs[KEY][subkey]`, which matches where the
   AI Field Extraction sprint already lands document statuses.

3. **Loop prevention threshold.** Spec says "Prevent loops". My draft
   is "max 5 transitions per evaluation cycle, then stop and log".
   OK?

# Runbook — Pipeline Kanban

**Status (2026-05-09, sesión 7):** backend hardened — orphan-stage
detection (closes the loophole flagged in sesión 1), `assigned_user_id`
filter, GROUP BY count optimization. Frontend renders the orphan group
as a distinct amber column with rescue UX, and an "Solo mías" toggle.
9 new tests green. Browser verification + operator sign-off pending.

---

## 1. What this module does

Operators see every active conversation grouped by its `current_stage`
in a horizontal-scroll kanban. Each card shows customer name + phone +
last inbound text + a stale-alert badge if the conversation has been
stuck past the stage's `timeout_hours`.

Cards are **moved between stages via a dropdown selector** inside each
card, not drag-and-drop. This is intentional (per the v2 plan) — DnD
adds touch-target complexity and keyboard a11y surface that aren't
worth it at the operator volumes we're shipping.

---

## 2. Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/pipeline/board` | operator+ | Active stages + cards (≤50 per stage) + synthetic orphan group when applicable |
| GET | `/api/v1/pipeline/board/{stage_id}` | operator+ | Paginated cards for a single stage (`limit` ≤ 200) |
| GET | `/api/v1/pipeline/alerts` | operator+ | Only the stale cards across all stages |

`/board` query params:

| Param | Type | Effect |
|---|---|---|
| `assigned_user_id` | UUID | Filter cards to this operator's assignments |
| `tid` | UUID | Superadmin-only override (per `current_tenant_id` rules) |

Stage moves go through the existing
`PATCH /api/v1/conversations/{id}` endpoint with
`{"current_stage": "<new_id>"}`. That route already does pipeline-stage
validation + atomic `stage_entered_at` reset, so the kanban inherits
those guarantees — no separate "move" endpoint needed.

---

## 3. Stale-alert rules

A card is `is_stale: true` when **all** of these are true:

1. Its stage definition has a non-zero `timeout_hours` (the `cerrado`
   stage with `timeout_hours: 0` is treated as a sentinel that never
   alerts — see `test_cerrado_stage_with_zero_timeout_is_never_stale`).
2. `conversation_state.stage_entered_at` (or `last_activity_at` as
   fallback for legacy rows without `stage_entered_at`) is older than
   `now() - timeout_hours`.

`/alerts` returns only the cards that meet both. Use it to drive a
notification badge.

---

## 4. Orphan group ("Sin etapa activa")

**Closed loophole (sesión 7):** before this sesión, a conversation whose
`current_stage` was no longer in the active pipeline (e.g. operator
renamed `cotizado` to `cotizando` in Configuración) **silently
disappeared from the board**. Nobody saw it; nobody could move it.

The board now appends a synthetic group with `is_orphan: true` and
`stage_id: "__orphan__"` listing those conversations. The frontend:

- Renders an amber banner above the kanban with the orphan count and a
  link to Configuración.
- Renders the orphan group as the rightmost column with amber styling.
- Each orphan card surfaces its current (invalid) `current_stage` and
  shows a placeholder dropdown with **only valid stages** as options.
  Picking one calls the same PATCH the regular cards use.

Frontend code:
[`PipelineKanbanPage.tsx`](frontend/src/features/pipeline/components/PipelineKanbanPage.tsx).

---

## 5. Performance notes

- The board query was previously O(N stages × per-stage count subquery).
  Sesión 7 collapsed counts into one `GROUP BY current_stage` and re-uses
  the result for both real stages and orphan detection.
- Per-stage card fetch is still capped at 50; `/board/{stage_id}`
  exposes a `limit` up to 200 for "Cargar más" UX (not yet wired in
  the frontend).
- `last_message_text` joins via a `ROW_NUMBER() OVER (PARTITION BY
  conversation_id ORDER BY created_at DESC)` window — not a per-row
  subquery — so it stays O(1) per card.

---

## 6. Loopholes still open

| # | Loophole | Severity | Effort | Status |
|---|---|---|---|---|
| PK-1 | No drag-and-drop. Per the v2 plan this is by design (dropdown-only). | — | — | **Accepted** by plan |
| PK-2 | `/board/{stage_id}` exposes `limit` but the frontend doesn't have a "Cargar más" button. Stages with >50 cards silently truncate. | Medium | ~30 min | Defer |
| PK-3 | The orphan group can't itself be filtered by `assigned_user_id` — the param applies but the orphan section heading doesn't reflect the filter. | Low | ~10 min | Defer |
| PK-4 | Stage-rename in Configuración doesn't auto-migrate existing conversations. The orphan group surfaces them but the operator must move them one by one. | Medium | ~1h (write a `migrate_stage` endpoint) | Defer |
| PK-5 | `is_stale` uses `stage_entered_at` if present, falls back to `last_activity_at`. For very old rows that predate sesión 3c.2's stage_entered_at column, the fallback can mis-flag a recently-active conversation as stale. | Low | one-line backfill SQL | Defer; document only |
| PK-6 | No per-stage activity metrics (avg time to advance, conversion rate). v1 had `StageMetrics` component; v2 doesn't. | Low | ~1 sesión | Defer |
| PK-7 | No audit-event emit on stage move from the kanban (the underlying PATCH does emit `conversation_updated`, but the kanban-specific flow could log "moved from kanban"). | Low | trivial | Defer |

---

## 7. Browser verification checklist (operator)

- [ ] `/pipeline` loads without error and shows one column per active
      stage.
- [ ] Each column shows total count + cards (up to 50).
- [ ] Stale cards show the red "Alerta" badge.
- [ ] Picking a different stage in a card's dropdown:
      - The card disappears from its source column.
      - The card appears in the target column.
      - The alerts count refreshes if the move resolved a stale state.
- [ ] "Solo mías" button:
      - When pressed, only conversations assigned to you appear.
      - When unpressed, all conversations appear again.
- [ ] **Orphan flow:** in Configuración → Pipeline, rename one of the
      stages (e.g. rename `interesado` → `interes`). Save. Return to
      `/pipeline`. Verify:
      - The amber banner appears at the top with the count.
      - A "Sin etapa activa" amber column appears at the rightmost end.
      - The cards inside show their stale stage id (`interesado`).
      - Picking a valid stage from the dropdown moves the card; the
        orphan group's count drops.
- [ ] `/api/v1/pipeline/alerts` (Network tab): shows only stale cards.
- [ ] Cross-tenant: log in as a different tenant_admin, verify that
      tenant's pipeline is empty (no leakage).

When all green, sign in `docs/handoffs/sign-offs/pipeline-kanban.md`.

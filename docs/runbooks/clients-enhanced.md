# Runbook — Clients Enhanced

**Status (2026-05-09, sesión 6):** backend hardened — phone canonicalisation
fixed for the MX legacy ``1`` prefix, CSV import accepts email + score
columns, formula-injection escape on export, two-step preview-then-commit
import dialog wired in the frontend. 14 new tests green. Browser
verification + operator sign-off pending.

This runbook covers the Clientes (Customers) area: list, detail, score,
CSV import/export.

---

## 1. Required environment variables

Same as `conversations.md`:

| Variable | Purpose |
|---|---|
| `ATENDIA_V2_DATABASE_URL` | Postgres URL |
| `ATENDIA_V2_AUTH_SESSION_SECRET` | JWT secret (override the dev fallback in prod) |
| `ATENDIA_V2_AUTH_COOKIE_SECURE` | `true` behind TLS |

No new env vars introduced by Clients Enhanced. CSV import is purely
synchronous so no arq queue involvement.

---

## 2. Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/customers` | operator+ | Paginated, filterable list with effective_stage + last_activity from lateral join |
| GET | `/api/v1/customers/{id}` | operator+ | Detail incl. email (sesión 5), conversations summary, total_cost_usd, last_extracted_data |
| PATCH | `/api/v1/customers/{id}` | operator+ | Update name / email / attrs. **Extra fields rejected** (422) since sesión 5. |
| PATCH | `/api/v1/customers/{id}/score` | operator+ | 0–100, clamped at validation |
| POST | `/api/v1/customers/import/preview` | operator+ | **NEW sesión 6** — returns parsed rows + errors WITHOUT committing |
| POST | `/api/v1/customers/import` | operator+ | Confirm import. Same parsing rules as preview. |
| GET | `/api/v1/customers/export` | operator+ | CSV download (max 5,000 rows) with `'`-escaped formula prefixes |

CSV columns recognised on import (header aliases either order):

- **phone** (required) — `phone` / `phone_e164` / `telefono`
- **name** — `name` / `nombre`
- **email** — `email` / `correo`
- **score** — `score` / `puntaje` (0–100)

---

## 3. Phone canonicalisation rules

`_normalize_phone` in `customers_routes.py` is the single source of truth.
Behaviour:

| Input | Output | Rationale |
|---|---|---|
| `5512345678` | `+525512345678` | 10-digit MX without country code |
| `15512345678` | `+525512345678` | 11-digit MX legacy mobile (drops the 1) |
| `+5215512345678` | `+525512345678` | E.164 with MX legacy (drops the 1) |
| `+525512345678` | `+525512345678` | Already canonical |
| `+5252... (12 digits with 52)` | `+5252...` | E.164 MX without legacy 1 |
| `+14155551234` | `+14155551234` | E.164 explicit — US/Canada untouched |
| `14155551234` | `+524155551234` | **Ambiguous** — bare 11 digits with leading `1` is interpreted as MX legacy because this is an MX-focused product. Operators entering US numbers must include `+`. |
| `+52 (155) 1234-5678` | `+525512345678` | Punctuation stripped |
| `abc` / `""` / `123` | `None` (row error) | Caller surfaces an error with row index |

**Why this matters:** before sesión 6, the function returned
`+5215512345678` and `+525512345678` as different rows for the same
physical phone. An operator importing the same customer list twice (once
with the legacy 1, once without) would create duplicates and split
conversation history.

---

## 4. CSV import flow

**Frontend (sesión 6):** `ImportCustomersDialog` is the new
preview-then-commit modal. Operator picks a CSV → frontend POSTs to
`/import/preview` → backend parses with the same rules as the real import
→ frontend renders a table of "will create" / "will update" rows + errors
list → operator clicks Confirm → frontend POSTs to `/import`.

**Limits:**

- **5 MB** raw file size cap (413).
- **2,000 rows** per file (413).
- **160 chars** max email length.
- Score must parse to int 0–100; out-of-range row recorded as error and skipped.

**Error reporting:** errors are returned as `["row 5: invalid phone",
"row 12: duplicate phone in file", ...]`. The first 20 are shown in the
import dialog; remaining are collapsed into "… and N more."

---

## 5. CSV export safeguards

- Header row: `name, phone, email, effective_stage, score, last_activity`.
- Each cell starting with `=`, `+`, `-`, `@`, `\t`, or `\r` is prefixed
  with `'` so Excel/Sheets renders it as a literal string instead of
  evaluating it as a formula. This blocks the classic CSV-to-formula
  injection vector.
- Hard cap: 5,000 rows per export. (Above this, recommend a paginated
  export job — not yet implemented.)
- Output is UTF-8 with no BOM. Excel may interpret accents incorrectly
  on default Windows locale; document this and recommend opening via
  Data → From Text/CSV with UTF-8 encoding.

---

## 6. Frontend pages

| Route | Component | What it shows |
|---|---|---|
| `/customers` | `ClientsPage` | Search + stage filter + table (Nombre / Teléfono / Etapa / Agente / Última actividad / Score). Score editable inline. Export button + ImportCustomersDialog. |
| `/customers/:id` | `CustomerDetail` | Read-only summary; full edit happens via ContactPanel inside Conversations. |

**Out of scope this session and explicitly DEFERRED:**

- Full-table multi-column sort on the UI (backend supports `sort_by` but
  frontend uses `last_activity` only).
- Date-range and score-range filters in the UI (backend doesn't yet
  expose these query params either).
- Customer kanban view (per the v2 plan, kanban lives on the Pipeline
  page, not Clientes).

---

## 7. Loopholes still open (user-acceptance pending)

| # | Loophole | Severity | Effort | Recommended action |
|---|---|---|---|---|
| CL-1 | Frontend column-sort UI not wired (backend has it). | Low | ~30 min | Defer; default sort is workable. |
| CL-2 | No date-range / score-range filter in UI or API. | Low | ~1 session | Defer. |
| CL-3 | Export hard-capped at 5,000 rows with no pagination. | Low | ~1h (cursor-based stream) | Defer until a tenant exceeds it. |
| CL-4 | No Excel-friendly UTF-8 BOM in export. Special chars look broken on default Windows locale unless opened via Data → From Text. | Low | 1 line | Trade: BOM breaks some other CSV consumers. Defer; document in Excel onboarding. |
| CL-5 | `attrs` JSONB has no schema validation on patch. Operator can store arbitrary JSON. | Medium | ~1h | Defer until a structured-attrs use case appears. |
| CL-6 | Import is a single transaction — failure aborts the whole batch. | Low | ~1h (chunked commits) | Defer; 2,000-row cap keeps blast radius small. |
| CL-7 | No audit-log emit on customer edit/score-change/import. | Low | ~30 min (use `_audit.emit_admin_event`) | Recommended close in next session for parity with workflows + KB. |

---

## 8. Browser verification checklist (operator)

- [ ] `/customers` loads without flash-of-empty.
- [ ] Search by partial name + partial phone works.
- [ ] Stage filter narrows the table.
- [ ] Score input commits on blur (network tab shows PATCH /score).
- [ ] Export button downloads a CSV; opening in Excel shows
      `'=SUM(...)`-style cells as literal text, not formulas.
- [ ] Import dialog: pick a CSV → preview shows "will create" / "will
      update" badges + errors list → click Confirm → toast counts match
      preview.
- [ ] Phone normalisation: import `+5215512345678` and `+525512345678`
      in the same file → exactly 1 created + 1 duplicate-in-file error.
- [ ] Customer detail page (`/customers/:id`) shows email + score from
      the import.

When all green, sign in `docs/handoffs/sign-offs/clients-enhanced.md`.

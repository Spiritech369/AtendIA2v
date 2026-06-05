# Composer Surface Decision - Dinamo DB Verified

Date: 2026-06-02

Tenant:

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- email: `dinamomotosnl@gmail.com`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`

## Decision

The composer surface should stay, but only as an operator-facing configuration and preview surface. It must not be treated as an independent authority for final customer-visible responses.

Authority rule:

- Final customer-facing copy: `TurnOutput.final_message`
- Composer mode prompts: tenant-scoped guidance for stage/operator UX
- Tools/actions: structured data only, no visible response text

## Surface Classification

| Surface | Decision | Reason |
| --- | --- | --- |
| Pipeline stage guidance | Keep | Backed by tenant pipeline config. |
| `mode_labels` | Keep | Useful operator labels, DB-backed. |
| `mode_prompts` | Keep | Guidance only, not final copy. |
| Runtime v2 preview/test turn | Keep | Safe when preview-only and no send path is enabled. |
| Legacy static composer widgets | Hide or badge | Should not appear equivalent to active Dinamo config. |
| Customer-facing final copy editor | Do not add | Would violate single-authority rule. |

## Required UI Badges

Use clear UI state for:

- REAL_DATA: tenant-scoped DB config.
- PREVIEW_ONLY: generated/previewed but not sent.
- LEGACY_OR_STATIC: older widget not proven to be active Dinamo config.

## Safety Result

No manual-send, auto-send, WhatsApp, outbox, action execution, or workflow event path was enabled. Composer is acceptable for screenshot review as a preview/config surface only.


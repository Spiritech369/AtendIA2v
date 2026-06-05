# Ruff Debt Ticket

## Context

RC4/RC5 keep ruff scoped to files touched by the staging-readiness work. A global `uv run ruff check .` currently reports pre-existing repository-wide debt outside the runtime readiness changes.

## Proposed Follow-Up

Create a separate lint-hardening task to:

- inventory global ruff failures by package,
- decide which rules should remain enabled,
- fix or suppress violations in owned batches,
- update CI from scoped lint to full-repo lint when the baseline is clean.

## Non-Goal For RC5

Do not pay global ruff debt inside RC5. RC5 should validate staging soak, canary readiness, observability, alerts, and runtime safety.

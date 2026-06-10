# Product-First Live Stable Baseline - 2026-06-09

Status: checkpoint documental aprobado  
Approval: user message "aprobado" after the proposed docs-only plan  
Scope: documentation only; no runtime, DB, WhatsApp, outbox, workflow, smoke,
canary, migration, delete, reset, restore, clean, or live state changes.

## Why This Baseline Exists

The live stability problem is architectural, not a single smoke failure. The
audit confirms that AtendIA has real Product-First assets, but live WhatsApp and
Baileys still enter through `ConversationRunner`, Runtime V2 is bridged from
that runner, and visible customer copy can still be influenced by legacy
composer/fallback/workflow paths.

This checkpoint freezes the working assumptions before any Respond-Style runtime
refactor starts.

## Worktree Snapshot

Command used:

```powershell
git status --porcelain=v1 | ForEach-Object { if ($_ -match '^(.{2})') { $matches[1] } } | Group-Object | Sort-Object Name
```

Observed counts:

| Status | Count |
|---|---:|
| `D` | 315 |
| `M` | 31 |
| `??` | 123 |

The worktree is not clean. It must not be treated as safe for broad runtime
refactor, destructive cleanup, or live activation.

## Product-First Assets To Preserve

The checkpoint found untracked/new Product-First assets that should be
preserved until a human decides otherwise:

- `Arquitectura-Deseada.md`
- `ARCHITECTURE.md`
- `AUDITORIA_COMPLETA_ATENDIA_2026_06_09.md`
- `PRODUCT_FIRST_LIVE_STABLE_CODEX_IMPLEMENTATION.md`
- `specs/001-product-first-agent-platform/`
- `docs/architecture/`
- `docs/product/`
- `core/atendia/product_agents/`
- `core/atendia/api/product_agents_routes.py`
- `core/atendia/db/models/product_agent.py`
- `core/atendia/agent_runtime/agent_service.py`
- `core/atendia/agent_runtime/send_adapter.py`
- `core/atendia/agent_runtime/runtime_state_persistence.py`
- `core/atendia/agent_runtime/live_transcript_replay_gate.py`
- `frontend/src/features/product-agent-builder/`
- Product-First reports under `reports/product_first_*`
- Controlled smoke/readiness reports under `reports/controlled_*`

## Modified Runtime Areas Requiring Care

Runtime and live-adjacent modified files exist and must not be overwritten or
normalized casually:

- `core/atendia/agent_runtime/*`
- `core/atendia/runner/conversation_runner.py`
- `core/atendia/runner/confirmation_policy.py`
- `core/atendia/runner/handoff_helper.py`
- `core/atendia/main.py`
- `core/atendia/db/models/__init__.py`
- `docker-compose.yml`
- frontend navigation and route generated files

## Historical Deletes Requiring Human Decision

The status includes many tracked deletions for older docs, reports, QA images,
tenant source files, scripts, and runbooks. These are incident and migration
evidence. Do not run `git clean`, `git reset`, `git restore`, or any broad
cleanup command without explicit approval naming the exact command and target.

## Baseline Decision

Decision: `BASELINE_READY_FOR_PRODUCT_FIRST_REFACTOR`

Constraint: this baseline is ready only for documentation alignment and
implementation planning. Runtime/code/live implementation still requires a
separate approval that names files, tests, rollback, and side-effect scope.

Safety marker: `BASELINE_READY_FOR_DOCS_ONLY_PRODUCT_FIRST_REFACTOR`

This does not authorize runtime implementation. It authorizes only the
documentation alignment needed to make the next implementation Ready.

## Next Required Decisions

Before code implementation starts, the user must approve:

- branch/worktree or checkpoint strategy
- exact files allowed for runtime edits
- tests to run and coverage target for changed behavior
- rollback path for code/config/data/live effects
- legacy component classifications affected by the implementation
- confirmation that no live/send/outbox/workflow side effect is in scope

# Business Event Idempotency Ledger Implementation

## Decision

WORKFLOW_BUSINESS_EVENTS_READY

Reason: Docker Desktop was started, PostgreSQL test DB was raised, migrations
roundtripped successfully, ledger integration tests passed against real
PostgreSQL, duplicate/idempotency behavior passed, tenant-scope isolation passed,
and the non-DB agent runtime suites stayed green.

## Files Created

- `core/atendia/agent_runtime/business_event_ledger.py`
- `core/atendia/db/models/business_event_ledger.py`
- `core/atendia/db/migrations/versions/065_business_event_ledger.py`
- `core/tests/agent_runtime/test_business_event_ledger.py`

## Files Modified

- `core/atendia/db/models/__init__.py`
- `core/tests/db/test_migrations_roundtrip.py`

## Ledger Schema

Table: `business_event_ledger`

- `id`: UUID primary key
- `tenant_id`: tenant FK, indexed
- `conversation_id`: nullable conversation FK, indexed
- `event_type`: business event type, indexed
- `idempotency_key`: stable business fact key, indexed
- `status`: `dry_run`, `blocked`, `executed`, or `duplicate`
- `reason`: structured reason from event/workflow result
- `event_payload`: full universal `BusinessEvent` JSONB
- `workflow_result`: dry-run or blocked workflow result JSONB
- `trace_id`: optional universal trace id, indexed
- `side_effects_allowed`: boolean, false by default
- `created_at`, `updated_at`: audit timestamps

Unique constraint:

- `uq_business_event_ledger_scope_idempotency_key`
- `UNIQUE (tenant_id, conversation_id, event_type, idempotency_key)`

## Behavior Validated

- Business events persist idempotently with PostgreSQL `ON CONFLICT DO NOTHING`.
- Duplicate detection is scoped to `tenant_id`, `conversation_id`, `event_type`,
  and `idempotency_key`.
- A duplicate attempt in the same scope returns `duplicate=True`,
  `status="duplicate"`, and `reason="duplicate_idempotency_key"`.
- The same external `idempotency_key` in another tenant/conversation scope does
  not collide.
- `dry-run` workflow results normalize to ledger status `dry_run`.
- Safe-mode or blocked workflow results persist as `blocked`.
- Payload fields persisted correctly: `event_payload`, `workflow_result`,
  `trace_id`, `reason`, `status`, timestamps.
- No workflow execution, WhatsApp send, followup creation, action execution, or
  live tenant config change was triggered.

## PostgreSQL Schema Inspection

Constraints:

- `business_event_ledger_pkey`: `PRIMARY KEY (id)`
- `business_event_ledger_tenant_id_fkey`: tenant FK with `ON DELETE CASCADE`
- `business_event_ledger_conversation_id_fkey`: conversation FK with `ON DELETE SET NULL`
- `uq_business_event_ledger_scope_idempotency_key`:
  `UNIQUE (tenant_id, conversation_id, event_type, idempotency_key)`

Indexes:

- `business_event_ledger_pkey`
- `ix_business_event_ledger_conversation_id`
- `ix_business_event_ledger_event_type`
- `ix_business_event_ledger_idempotency_key`
- `ix_business_event_ledger_tenant_id`
- `ix_business_event_ledger_trace_id`
- `uq_business_event_ledger_scope_idempotency_key`

## Tests Added

- Unit test for dry-run ledger value construction without DB.
- Integration DB test for dry-run persistence without side effects.
- Integration DB test for duplicate scoped `idempotency_key` suppression.
- Integration DB test for same key allowed in a different tenant/conversation scope.
- Integration DB test for preserving safe-mode blocked status.

## Commands Executed

- `docker version`
  - Initial result: Docker CLI installed, daemon unavailable.

- `Start-Process Docker Desktop`
  - Result: Docker Desktop started.

- Docker readiness loop with `docker info`
  - Result: `DOCKER_READY`

- `docker compose -f docker-compose.test.yml up -d postgres-test`
  - Result: `Container atendia_postgres_test Started`

- `uv run ruff check atendia/agent_runtime/business_event_ledger.py atendia/db/models/business_event_ledger.py atendia/db/migrations/versions/065_business_event_ledger.py tests/agent_runtime/test_business_event_ledger.py`
  - Result: `All checks passed!`

- First `uv run pytest tests/agent_runtime/test_business_event_ledger.py -m "integration_db" -q`
  - Result: failed with fixture insert order bug, then failed with stale migration
    state after changing the unique scope.

- `uv run alembic downgrade base`
  - Result: downgraded test DB from `businesseventledger065` to base.

- `uv run pytest tests/agent_runtime/test_business_event_ledger.py -m "integration_db" -q`
  - Result: `4 passed, 1 deselected, 2 warnings in 3.22s`

- `uv run pytest tests/db/test_migrations_roundtrip.py -q`
  - Result: `1 passed, 2 warnings in 2.75s`

- PostgreSQL constraint/index inspection via `psql`
  - Result: unique scope constraint and indexes present.

- Re-run after roundtrip:
  `uv run pytest tests/agent_runtime/test_business_event_ledger.py -m "integration_db" -q`
  - Result: `4 passed, 1 deselected, 1 warning in 1.89s`

- `uv run pytest tests/agent_runtime/test_business_events.py tests/agent_runtime/test_universal_turn_trace.py -q`
  - Result: `22 passed, 1 warning in 0.28s`

- `uv run pytest tests/agent_runtime -m "not integration_db" -q`
  - Result: `202 passed, 34 deselected, 2 warnings in 3.22s`

- Final ruff:
  `uv run ruff check atendia/agent_runtime/business_event_ledger.py atendia/agent_runtime/business_events.py atendia/db/models/business_event_ledger.py atendia/db/models/__init__.py atendia/db/migrations/versions/065_business_event_ledger.py tests/agent_runtime/test_business_event_ledger.py tests/db/test_migrations_roundtrip.py`
  - Result: `All checks passed!`

## Tenant/Core Safety

- No traffic real was activated.
- No WhatsApp messages were sent.
- No actions/workflows real execution was enabled.
- No live tenant config was applied.
- The runtime send path was not touched.
- The ledger stores already-derived universal event payloads; it does not derive
  events from keywords or free text.

## Risks Remaining

- The ledger is still intentionally not wired to real workflow execution.
- Future live workflow execution must require an explicit tenant contract,
  action gating, safe-mode checks, and ledger insertion before any side effect.

## Recommended Next Step

Add the gated workflow bridge that consumes only ledger-recorded business events,
still in dry-run by default, and require an explicit tenant-level enablement before
any action execution path can move from dry-run to live.

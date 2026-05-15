# Test DB isolation & data-loss prevention — Design

Date: 2026-05-15
Status: Proposed (awaiting approval to implement)

## Context / Incident

On 2026-05-15 the live dev database (`atendia_v2`, container
`atendia_postgres_v2`, host port 5433) was found wiped: `tenant_users`,
`messages`, `events`, `human_handoffs` all at 0 rows, while leftover
test-fixture tenants (`dinamomotos_t40_happy` / `dinamomotos_t40_neg`,
synthetic phone `+5215555550042`, identical creation timestamps, 0 messages)
remained. The user could not log in ("invalid credentials") because no row
existed in `tenant_users`. A recovery seed restored the QA superadmin, but the
prior conversation data was unrecoverable (dev Postgres has no backups / WAL
archiving).

### Root cause

Every test `conftest.py` (11 of them) connects with
`create_async_engine(get_settings().database_url)`. There is **no dedicated
test database** and **no safety guard** — the repo's root
`core/tests/conftest.py` is empty. When `get_settings().database_url` resolves
to the real `atendia_v2` (via the container env, or the documented "copy
core/.env into the worktree" workflow), destructive per-test fixtures
(`DELETE FROM tenants ...`, table cleanups) mutate and destroy real data. A
"t40" test run did exactly this.

This was NOT caused by Docker, the recovery seed, or editing
`docker-compose.yml`. The external Postgres volume is persistent; no migration
deletes rows.

## Goals

- Make it **structurally impossible** for the test suite to run against the
  real (or production) database — fail closed, not by discipline.
- Provide a clean, isolated database for tests.
- Lay out what is additionally required before the product serves real users.

## Non-goals

- Recovering the already-lost data (not possible without a backup).
- Rewriting the 11 per-suite conftests' fixtures.
- Implementing production infrastructure now (documented as Phase 2).

## Ports

| Service | Host port | Container | Role |
|---|---|---|---|
| `atendia_postgres_v2` | 5433 | 5432 | live dev DB (protect) |
| `atendia_redis_v2` | 6380 | 6379 | dev redis |
| `atendia_backend` | 8001 | 8001 | dev API |
| `atendia_frontend` | 5173 | 5173 | dev UI |
| `atendia_baileys_bridge` | 7755 | 7755 | WhatsApp sidecar |
| `atendia_worker` / `atendia_workflow_worker` | — none | 8001 EXPOSEd, **not published** | arq workers; reach DB/Redis over the compose network (`postgres-v2:5432`, `redis-v2:6379`) |
| **test Postgres (new)** | **5432** | 5432 | dedicated test DB `atendia_v2_test` |

**Decision (user, 2026-05-15): the test Postgres is published on host 5432.**
This is acceptable **only because Layer 1 is the protection, not the port**:
the guard rejects any DB whose name is not a test DB regardless of which port
it is on, so a config mis-pointed at the real `atendia_v2` (host 5433) still
aborts the session. The test DB is named `atendia_v2_test`. Workers have **no
host port** — they connect to Postgres/Redis over the internal Docker network,
so the host test-DB port does not affect them; host 5432 only matters for
host-run tools (pytest, seed scripts).

Free host ports verified 2026-05-15: 5432, 5434, 5435, 5444, 5544, 6379,
6381, 15432.

## Design — Phase 1 (now: closes the incident)

### Layer 1 — Test session safety gate (critical, single file)

In the currently-empty `core/tests/conftest.py` add a `pytest_configure`
hook (runs once, before all sub-conftests and fixtures):

1. Resolve `get_settings().database_url`; parse out the database name.
2. Allow the session ONLY if the DB name marks it as a test DB
   (suffix `_test`, e.g. `atendia_v2_test`) **or** an explicit opt-in env
   `ATENDIA_V2_TEST_DB_OK=1` is set.
3. Otherwise call `pytest.exit(...)` with a clear message and non-zero code,
   aborting the entire session before any fixture/engine is created.

Rationale: one file sits above all 11 sub-conftests; centralizing is
unforgettable vs. patching each. Fail-closed: unknown/real/prod DB → abort.
This is the load-bearing protection — the port choice is irrelevant to safety.

### Layer 2 — Dedicated test database

- Add a `postgres-test` service (compose profile `test`, or a separate
  `docker-compose.test.yml`) on host port **5432**, database
  `atendia_v2_test`, on its own volume.
- Tests target it via `ATENDIA_V2_DATABASE_URL=postgresql+asyncpg://atendia:atendia@localhost:5432/atendia_v2_test`
  (a `.env.test` / documented invocation). With Layer 1, the normal path is
  safe and the guard enforces the boundary.
- Note: host 5432 is also the config *default*; the `_test` DB name + Layer 1
  guard are what keep an accidental default-resolution from hitting real data.

### Layer 3 — Production hard-block

Generalize the existing `assert_prod_secret_safety()` precedent: when an env
flag indicates production (e.g. `ATENDIA_ENV=production`), destructive
test/seed code paths refuse to run. Combined with Layer 1, even pytest pointed
at prod credentials aborts twice (DB-name gate + prod-env gate).

## Design — Phase 2 (required before serving real users)

Necessary but explicitly deferred; documented so it is not forgotten:

1. **Automated backups + tested restore** for the production DB. This is the
   single most important item: the test guard prevents *test* wipes only; it
   does not protect against bad migrations, app bugs, disk failure, or
   operator error. The data lost in this incident was unrecoverable precisely
   because no backup existed.
2. **Migration policy.** Backend runs `alembic upgrade head` on every boot;
   with real data require backup-before-migrate + migration review.
3. **Environment separation.** Isolated prod DB, distinct credentials,
   unreachable from developer machines / CI test jobs.
4. **Least-privilege DB role.** App runtime role without TRUNCATE/DROP;
   separate migration role. (Was "Layer 4 optional"; rises in priority with
   real users.)

## Error handling

- Guard failure → `pytest.exit(msg, returncode=2)`; message states the
  resolved DB and how to point at the test DB. No partial test run.
- Missing test DB → connection error from the normal pytest path (loud,
  not silent); document the one-command bring-up.

## Testing the guard

- Run pytest with `ATENDIA_V2_DATABASE_URL` → `atendia_v2`: expect immediate
  session abort, exit code ≠ 0, zero fixtures executed.
- Run with the `_test` DB: suite runs normally.
- Unit-test the name/opt-in predicate in isolation (allowed vs rejected).

## Rollout

1. Land Layer 1 (highest leverage, no infra change) — closes the risk.
2. Add Layer 2 service + documented invocation; update
   `db_verification_env.md` guidance.
3. Add Layer 3 prod assertion.
4. Phase 2 tracked separately for the production milestone.

## Decisions

- **Resolved (user, 2026-05-15):** test Postgres host port = **5432**;
  test DB name = `atendia_v2_test`. Safety comes from Layer 1, not the port.

## Open decisions

- Test-DB marker: `_test` suffix vs explicit `ATENDIA_V2_TEST_DB_OK=1` vs
  both (proposed: both — suffix is the norm, env is the escape hatch).
- Test DB delivery: compose `test` profile vs separate
  `docker-compose.test.yml` (proposed: profile — one file, less drift).

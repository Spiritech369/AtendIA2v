# DB-backed Frontend Config Precheck - 2026-06-02

## Result

- db_connected: true
- tenant_found: true
- agent_found: true
- tenant_user_email_found: true
- migrations_current: true

## Database Configuration

- Backend env: `core/.env`
- DATABASE_URL: `postgresql+asyncpg://atendia:atendia@localhost:5433/atendia_v2`
- Docker service: `postgres-v2`
- Container: `atendia_postgres_v2`
- Host port: `5433`
- Container port: `5432`
- User: `atendia`
- Database: `atendia_v2`

## Smoke Checks

- `SELECT 1`: passed
- tenant count: 529
- Alembic current: `read1nessv2 (head)`

## Dinamo Tenant

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- tenant name: `Dinamo Motos NL`
- tenant status: `active`
- tenant timezone: `America/Mexico_City`
- tenant user email: `dinamomotosnl@gmail.com`
- tenant user role: `tenant_admin`

## Dinamo Agent

- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`
- agent name: `Francisco de Dinamo NL`
- agent status: `production`

## Safety Gates Observed

Tenant config remains preview-only:

- `send_enabled`: false
- `manual_send_enabled`: false
- `auto_send_enabled`: false
- `outbox_enabled`: false
- `actions_enabled`: false
- `workflow_events_enabled`: false
- `shadow_mode_enabled`: false
- `ready_for_shadow`: false
- `ready_for_manual_send`: false
- `ready_for_live_preview`: false

## Failure Command If DB Is Down

Not needed in this run because Postgres is healthy. If it fails later, use:

```powershell
docker compose up -d postgres-v2
```


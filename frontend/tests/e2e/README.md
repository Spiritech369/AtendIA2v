# E2E (Playwright) smoke tests

## Why this directory exists

Vitest covers unit + component tests (`pnpm test`). Playwright covers
end-to-end behaviour against a real backend + real browser — the only
layer that can catch a regression like "the login form doesn't post
the CSRF cookie" or "the conversations page silently red-screens on a
production build".

The audit listed this as Sprint C.1:
> Playwright E2E smoke para 7 rutas principales (Conversations,
> Handoffs, Customers, Appointments, Knowledge, Agents, Workflows).

## What the smoke covers

`smoke-routes.spec.ts` logs in once via the API and then navigates to
every protected route, asserting:

* HTTP 200 from the SPA shell.
* The page mounts without a thrown error (no "Something went wrong" /
  React error boundary visible).
* The sidebar shows the route as active (proves the router resolved
  the path, not just that the shell loaded).

This is intentionally a smoke — no per-page interaction. Happy-path
tests can grow alongside features later.

## How to run locally

```bash
# 1. Install Playwright browsers once (the config comment promised this
#    would land in T54 — Sprint C.1).
pnpm exec playwright install chromium

# 2. Boot the backend + database (separate terminal).
docker compose up -d postgres-v2 redis-v2
cd ../core
uv run uvicorn atendia.main:app --reload --port 8001

# 3. Boot a fresh seed user so the smoke has credentials.
cd ../core
uv run python scripts/seed_zored_user.py

# 4. Run the smokes (this also starts the frontend dev server via
#    webServer config).
cd ../frontend
pnpm test:e2e
```

The default `webServer` block in `playwright.config.ts` proxies
`/api/*` to `http://localhost:8001` via Vite, so you don't need to
configure separate URLs.

## CI status

CI does NOT run these yet — Playwright would need the browser-install
step, plus a Postgres + Redis service block already in `.github/
workflows/ci.yml`. Both are achievable; deferred behind the decision
matrix as a follow-up to Sprint C.1.

When wiring CI:
1. Add a step `pnpm --filter frontend exec playwright install
   --with-deps chromium` after `pnpm install`.
2. Add another step `pnpm --filter frontend test:e2e`.
3. Make sure the backend is bound to `http://localhost:8001` and the
   migrations have run before the e2e step kicks off.

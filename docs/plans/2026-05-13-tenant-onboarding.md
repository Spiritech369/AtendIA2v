# Tenant onboarding — design for the real signup flow

Author: Claude
Date: 2026-05-13
Status: design only, no code yet (the runtime auto-seed in
`atendia.state_machine.default_pipeline` is the "fail-safe" half of the
plan; this doc covers the explicit half that the eventual signup UI
will own).

## Why this exists

Today new tenants only enter the system through `seed_zored_user.py` or
manual SQL — there is no public signup endpoint. As of commit `5796391`
we added `ensure_default_pipeline` so that *any* tenant which receives a
message before it has a pipeline gets a generic starter pipeline auto-
materialized on first inbound. That's the safety net. This doc designs
the explicit flow we expect to build when self-serve signup ships.

## Scope

Self-serve signup creates **one full working tenant** in a single
transaction. The operator should be able to send WhatsApp messages to a
demo number and see the bot respond — with the default pipeline,
default branding, default NLU/Composer settings — within minutes of
creating their account.

Out of scope:
* Billing, plan limits, payment.
* SAML / SSO. Email + password only for v1.
* WhatsApp Cloud API verification (handled in the Channels module).

## Endpoints

### `POST /api/v1/auth/signup`

```json
{
  "company_name": "Acme S.A. de C.V.",
  "email": "founder@acme.mx",
  "password": "min12chars",
  "timezone": "America/Mexico_City"
}
```

Behavior (single transaction):
1. `INSERT INTO tenants (name, created_at, timezone)`.
2. `INSERT INTO tenant_users (tenant_id, email, role='tenant_admin', password_hash)`.
3. `INSERT INTO tenant_pipelines (tenant_id, version=1, definition=DEFAULT_PIPELINE_DEFINITION, active=true)`.
4. `INSERT INTO tenant_branding (tenant_id, default_messages=DEFAULT_BRAND_FACTS, voice=DEFAULT_VOICE)`.
5. Emit `tenant.created` admin event.
6. Issue JWT + CSRF cookies (same shape as `/auth/login`).

Returns the same body as `/auth/me` so the SPA can hydrate the auth
store and route the user straight into the dashboard.

Failure modes:
* `409` if email already exists in `tenant_users`.
* `422` on weak password (min 12 chars, at least one non-letter).
* `429` on signup abuse (per-IP rate limit, 5/hour).

### `GET /api/v1/auth/onboarding-state`

After signup the SPA polls this to know which step of the welcome
checklist to highlight. Computed live, no extra column:

```json
{
  "pipeline_published": true,
  "whatsapp_connected": false,
  "brand_voice_set": false,
  "first_message_received": false,
  "first_message_sent": false
}
```

Each field is a SELECT against existing tables — `pipeline_published`
is true once the tenant has any pipeline row that isn't the auto-seeded
starter (i.e., `version > 1` or `definition != DEFAULT_PIPELINE_DEFINITION`).

## What the user sees

```
┌─────────────────────────────────────────────────────────────┐
│ Bienvenido a AtendIA                                        │
├─────────────────────────────────────────────────────────────┤
│ ✓ Cuenta creada                                             │
│ ✓ Pipeline inicial activo (puedes personalizarlo)           │
│ ☐ Conecta WhatsApp                              [Conectar] │
│ ☐ Personaliza la voz del bot                    [Editar]   │
│ ☐ Recibe tu primer mensaje                                  │
└─────────────────────────────────────────────────────────────┘
```

The pipeline check is auto-completed because of the starter — the user
isn't *forced* to edit it. The WhatsApp connection is the only blocking
step before incoming messages can flow.

## Default content shipped on signup

* **Pipeline**: `atendia.state_machine.default_pipeline.DEFAULT_PIPELINE_DEFINITION`.
  Five stages, two terminals, no auto-enter rules. The operator
  customizes through `PUT /tenants/pipeline` (single-version overwrite).
* **Branding** (to be added in a sibling `default_branding.py`):
  * `voice`: `{"tone": "friendly_professional", "language": "es-MX"}`.
  * `default_messages.brand_facts`: empty dict — the operator fills it.
* **NLU / Composer**: provider falls back to settings env (`nlu_provider`,
  `composer_provider`). No per-tenant override at signup.

## What the auto-seed (`ensure_default_pipeline`) covers vs. doesn't

The runtime auto-seed exists because of one race: a webhook for a brand-
new tenant arrives *before* the explicit signup flow has run. In
practice this happens when:

* A tenant is created manually (admin SQL, `seed_*` scripts) and the
  operator hands out the WhatsApp number before publishing a pipeline.
* A test environment spins a fresh tenant via API and skips the
  signup-time seed.

For the *real* signup endpoint the seed is redundant — the same
`DEFAULT_PIPELINE_DEFINITION` is inserted explicitly in step 3 above.
We keep the runtime seed as defense-in-depth: cheap, idempotent, and
guarantees that no inbound ever falls into the legacy `"greeting"`
fallback regardless of how the tenant was created.

## Open questions for the implementer

1. **Email verification before first login?** v1 says no — accept any
   email, send a "welcome / confirm" email post-hoc. v2 can add a
   token-gated `/auth/verify-email` if abuse becomes a problem.
2. **Demo WhatsApp number for trial users?** Would let signups send a
   real message in 30 seconds, before they connect their own Meta/
   Baileys account. Worth designing once we have ≥ 1 paying customer.
3. **Soft-delete vs. hard-delete on tenant offboarding?** Conversations
   already soft-delete (`deleted_at`). Tenants probably should too —
   makes "I want my account back" recoverable for 30 days.

## Pointer: where the code lives today

* Default pipeline content + idempotent seed:
  `core/atendia/state_machine/default_pipeline.py`.
* Pipeline single-version save policy:
  `core/atendia/api/tenants_routes.py:108` (`put_pipeline`).
* Pipeline live-reload (WS event):
  `core/atendia/api/tenants_routes.py` (`_broadcast_pipeline_change`).
* Auth shape to mirror in `/auth/signup`:
  `core/atendia/api/auth_routes.py` (login handler).
* Existing seed script to delete or repurpose once `/auth/signup`
  exists: `core/scripts/seed_zored_user.py`.

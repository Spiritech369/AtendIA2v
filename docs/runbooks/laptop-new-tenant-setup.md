# Laptop And New Tenant Configuration Guide

Last manual update: 2026-05-18.

This guide is for moving the current AtendIA v2 project to a laptop and
configuring a new tenant from zero. It has two parts:

1. A practical step-by-step checklist.
2. The reasoning behind the order, so future tenants can be configured without
   accidentally hardcoding one business vertical into the platform.

## Part 1 - Step By Step

### 1. Clone The Repository

```powershell
git clone https://github.com/Spiritech369/AtendIA2v.git
cd AtendIA2v
```

If the repo already exists on the laptop:

```powershell
cd AtendIA2v
git pull origin main
```

### 2. Install Local Prerequisites

Install:

- Docker Desktop
- Python 3.12
- Node.js 20+
- Git
- `uv`

Confirm:

```powershell
docker --version
python --version
node --version
npm --version
uv --version
```

### 3. Start Postgres And Redis

```powershell
docker compose up -d
docker ps
```

Expected local services:

- Postgres
- Redis

### 4. Configure Environment Variables

Create `core/.env` from the root example:

```powershell
Copy-Item .env.example core\.env
```

Open `core/.env` and fill the values you need. Minimum recommended for a real
AI tenant:

```env
ATENDIA_V2_OPENAI_API_KEY=...
ATENDIA_V2_NLU_PROVIDER=openai
ATENDIA_V2_COMPOSER_PROVIDER=openai
ATENDIA_V2_KB_PROVIDER=openai
ATENDIA_V2_AUTH_SESSION_SECRET=change-me-local
```

For WhatsApp Meta:

```env
ATENDIA_V2_META_APP_SECRET=...
ATENDIA_V2_META_ACCESS_TOKEN=...
```

### 5. Install Backend Dependencies And Run Migrations

```powershell
cd core
uv sync
uv run alembic upgrade head
```

### 6. Install Frontend Dependencies

```powershell
cd ..\frontend
npm install
npm run typecheck
```

### 7. Run Focused Backend Tests

```powershell
cd ..\core
uv run pytest tests/state_machine/test_pipeline_evaluator.py tests/runner/test_structured_quotes.py
```

### 8. Start The App Locally

Use the repo startup script if available in your branch:

```powershell
cd ..
.\scripts\start-demo.ps1
```

If you prefer manual terminals:

```powershell
# Terminal 1
cd core
uv run uvicorn atendia.main:app --reload

# Terminal 2
cd frontend
npm run dev
```

### 9. Create Or Select The New Tenant

Use the app UI or existing seed/admin scripts for the tenant. At minimum the new
tenant needs:

- Tenant row.
- Admin user.
- Active pipeline.
- Agent.
- Customer field definitions.
- Knowledge Base documents.
- Channel credentials if WhatsApp will be used.

If a helper script exists for your branch, start there:

```powershell
cd core
uv run python scripts/prepare_beta_tenant.py
```

Review the script before using it for a production tenant.

### 10. Configure Customer Fields

Go to the tenant configuration UI and create the commercial fields first:

| Key | Label | Type | Choices |
|---|---|---|---|
| `antiguedad` | Antiguedad laboral | checkbox | n/a |
| `tipo_credito` | Tipo de credito | select | Tenant-specific plan/type names |
| `credito_plan` | Plan de credito | select | Example: `10%`, `15%`, `20%`, `30%` |
| `modelo_moto` | Modelo moto | text | n/a |

Then create document status fields:

| Key | Label | Type | Choices |
|---|---|---|---|
| `DOCS_INE_FRENTE` | INE - Frente | select | `missing`, `ok`, `rejected` |
| `DOCS_INE_ATRAS` | INE - Reverso | select | `missing`, `ok`, `rejected` |
| `DOCS_DOMICILIO` | Comprobante de domicilio | select | `missing`, `ok`, `rejected` |

Add any extra tenant documents the same way, always using uppercase `DOCS_*`
keys.

### 11. Upload Knowledge Base Documents

Upload or seed:

- Product/catalog document.
- Requirements document.
- FAQ/policy document.

For the financing flow, the catalog must contain deterministic quote evidence:

- Canonical model name.
- Cash price.
- Plan percentage.
- Down payment.
- Payment amount.
- Number of payments/terms.

The requirements document should describe documents per plan/type. The prompt
can reference it, but the pipeline should still be configured with
`docs_per_plan` so document completion is deterministic.

### 12. Configure The Agent Prompts

Configure mode prompts for:

- PLAN
- SALES
- DOC
- OBSTACLE
- RETENTION
- SUPPORT

For progressive sales flows, include these behavior rules:

```text
State is progressive. Do not ask again for antiguedad, tipo_credito,
credito_plan, modelo_moto or documents already received. If the customer
changes a value, update it and continue from the current point.

When answering a question or comment, answer it briefly first, then add only the
next missing step.

Do not quote without catalog evidence. Do not invent prices, down payments,
payments, terms, requirements or availability.
```

For requirements formatting:

```text
Give requirements in one short message.
Use a short numbered list when there are several documents.
Do not duplicate equivalent documents.
"INE por ambos lados" equals front and back; if you use that phrase, do not add
"INE por detras" again as a separate item.
```

### 13. Configure Pipeline Documents

In the Expediente/Pipeline document configuration:

1. Add all documents to `documents_catalog`.
2. Set `docs_plan_field` to the field that selects the requirement set.
   - For the current financing flow, use `tipo_credito`.
3. Configure `docs_per_plan` with exact keys matching what the agent writes.
4. Configure `vision_doc_mapping`.

Example:

```json
{
  "docs_plan_field": "tipo_credito",
  "docs_per_plan": {
    "Sin Comprobantes": [
      "DOCS_INE_FRENTE",
      "DOCS_INE_ATRAS",
      "DOCS_DOMICILIO"
    ]
  },
  "vision_doc_mapping": {
    "ine": ["DOCS_INE_FRENTE", "DOCS_INE_ATRAS"],
    "comprobante": ["DOCS_DOMICILIO"]
  }
}
```

### 14. Configure Pipeline Stage Movement

For the stage that means paperwork is complete, use:

```json
{
  "enabled": true,
  "match": "all",
  "conditions": [
    {
      "field": "tipo_credito",
      "operator": "docs_complete_for_plan"
    }
  ]
}
```

This rule asks: "for the plan/type currently stored in `tipo_credito`, are all
required document statuses `ok`?"

### 15. Configure QoS

For sales flows where one customer turn should produce one bot response, set:

```json
{
  "enabled": true,
  "response_slo_ms": 8000,
  "max_messages_per_turn": 1
}
```

This avoids the quote or plan menu being split into separate outgoing jobs.

### 16. Configure WhatsApp Channel

For Meta Cloud API, add:

- `phone_number_id`
- `verify_token`
- access token/app secret through env or tenant config depending on environment.

For Baileys, configure the bridge and confirm the channel status page shows it
connected.

### 17. Run A Sandbox Conversation

Test this sequence:

1. Customer asks for a quote.
2. Bot asks only the first missing datum.
3. Customer provides antiguedad.
4. Bot asks income/plan type.
5. Customer answers with number or method.
6. Bot stores `tipo_credito` and `credito_plan`.
7. Customer gives model.
8. Bot quotes deterministically from catalog evidence.
9. Bot asks requirements in one clean message.
10. Customer sends documents.
11. Vision marks `DOCS_*` statuses.
12. Pipeline moves only when the plan's required docs are complete.

Check:

- Datos de cliente shows the fields.
- `DOCS_*` statuses show `ok`, `missing` or `rejected`.
- Turn traces show the evidence and decision path.
- Pipeline stage moves at the correct time.

## Part 2 - Why This Order Matters

### 1. Infrastructure First

Postgres and Redis must exist before backend migrations, workers, queues and
realtime can work. Starting Docker first prevents misleading errors from the API
or tests.

### 2. Migrations Before Tenant Setup

Tenant setup depends on current tables and JSON columns. Running migrations
first avoids configuring data into an old schema.

### 3. Customer Fields Before Prompts

The agent can only reliably extract and update fields that exist and are named
consistently. If `tipo_credito` is configured after the prompt is written, the
prompt might ask for something the backend cannot store cleanly.

### 4. Knowledge Base Before Quote Behavior

The quote must be evidence-based. If catalog evidence is missing, the system
should refuse or escalate instead of letting the LLM improvise numbers. Uploading
catalog and requirements before testing quotes makes failures honest and easy to
debug.

### 5. Agent Prompts After Fields And KB

Prompts should reference configured field names and KB documents. Writing prompts
after fields and KB keeps the language aligned with the actual system state.

### 6. Documents Catalog Before Docs-Per-Plan

`docs_per_plan` should only reference keys that exist in `documents_catalog`.
This keeps the UI readable and prevents invisible requirements.

### 7. Docs-Plan Field Before Pipeline Rule

The rule `docs_complete_for_plan` needs to know which customer value selects the
document set. For this flow that is usually `tipo_credito`, not `credito_plan`.
Set `docs_plan_field` first, then add the auto-enter rule.

### 8. Vision Mapping After Documents Exist

Vision maps categories like `ine` or `comprobante` into document keys. If the
keys do not exist yet, Vision can emit events but the operator will not see a
clean document status in Datos de cliente.

### 9. QoS After The Flow Is Known

`max_messages_per_turn` changes how responses are sent. In this sales flow, one
message per turn is cleaner because menus, quote details and closing lines stay
together. Other tenants may intentionally allow multiple messages, so keep it as
tenant config.

### 10. Sandbox Last

A sandbox conversation is the full integration test. It validates extraction,
prompt behavior, KB evidence, deterministic quotes, Vision mapping, document
completion and pipeline movement in one realistic path.

## Tenant Configuration Checklist

Use this checklist every time you create a tenant:

- [ ] Tenant exists.
- [ ] Admin user exists.
- [ ] Backend migrations are current.
- [ ] Customer fields exist and labels are readable.
- [ ] Commercial field values match what the agent will write.
- [ ] `DOCS_*` fields exist in Datos de cliente.
- [ ] Catalog KB is uploaded and indexed.
- [ ] Requirements KB is uploaded and indexed.
- [ ] Agent mode prompts are configured.
- [ ] `documents_catalog` is complete.
- [ ] `docs_per_plan` keys match exact customer field values.
- [ ] `docs_plan_field` points to the right field.
- [ ] `vision_doc_mapping` maps categories to `DOCS_*`.
- [ ] Pipeline has `docs_complete_for_plan` where needed.
- [ ] QoS is set for the desired response shape.
- [ ] WhatsApp channel is connected.
- [ ] Sandbox conversation passes.

## Common Mistakes

### Documents Do Not Complete

Usually one of these is wrong:

- `docs_plan_field` points to `credito_plan` but `docs_per_plan` keys are
  `tipo_credito` values.
- A doc key is misspelled, for example `docs_ine_frente` instead of
  `DOCS_INE_FRENTE`.
- Vision writes `DOCS_*` attrs but the UI field uses a different key.
- The plan really requires an extra document, such as `DOCS_ESTADOS_CUENTA`.

### The Bot Repeats A Step

Check:

- The field exists in customer fields.
- The runner saved it in Datos de cliente.
- The prompt says state is progressive and irreversible.
- The current turn trace shows the value in extracted/customer data.

### Quote Is Split Into Two Messages

Check tenant QoS:

```json
{
  "max_messages_per_turn": 1
}
```

### Requirements Duplicate INE

Update the DOC prompt with:

```text
"INE por ambos lados" equals front and back; do not also ask for INE por detras.
```

Also make sure your requirements KB does not list the same document under two
different labels unless the distinction is operationally real.

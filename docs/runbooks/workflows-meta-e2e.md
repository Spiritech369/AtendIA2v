# Runbook — Workflows + Meta WhatsApp E2E

**Status (2026-05-08, sesión 5):** internal pipeline verified end-to-end
through the Meta boundary. The `META_ACCESS_TOKEN` in `.env` is **expired**
(error 190, sesion ended 2026-05-03 19:00 PDT) so the final API call to
WhatsApp fails. **Refresh the token + re-run the probe; the same script
will return exit 0 = full send.**

This runbook covers (a) what the E2E probe verifies today, (b) how to
refresh the Meta access token, (c) how to run the full inbound-to-delivery
flow with a real WhatsApp message from your phone.

---

## 1. What the E2E probe verifies

`core/scripts/e2e_meta_workflow.py` exercises the entire pipeline.

| Step | What it does | Status this session |
|---|---|---|
| 1 | Seeds a temporary tenant + customer + active workflow with `message_received` trigger and `message` action. | ✅ |
| 2 | Builds a Meta-style inbound webhook payload, signs it with the real `META_APP_SECRET`, POSTs to `/webhooks/meta/{tenant_id}`. | ✅ webhook returned 200, signature validated. |
| 3 | Asserts in DB: `messages` (1 inbound), `events.message_received` (1), `workflow_executions` (1, created by the inline-trigger hook). | ✅ all rows present. |
| 4 | Runs `execute_workflow` inline so the workflow's `message` action runs. | ✅ `status=completed`. |
| 5 | Calls `MetaCloudAPIAdapter.send()` with the real token + phone_number_id. | ❌ `meta_error_190: Authentication Error` (token expired). |

So 4 of 5 steps green. **Step 5 is exactly one credential refresh away.**

---

## 2. Refreshing `META_ACCESS_TOKEN`

Meta access tokens expire. Three flavours exist:

| Type | Lifetime | When to use |
|---|---|---|
| User access token (short-lived) | 1–2 hours | Manual one-off testing only. |
| User access token (long-lived) | 60 days | Acceptable for prototype dev. |
| **System User access token** | Never expires | **What you want for production / CI.** Generate from Meta Business Manager → Business Settings → System Users. |

### Refresh steps (System User token, recommended)

1. Go to <https://business.facebook.com/settings/system-users>.
2. Open the system user that owns the WhatsApp Business app.
3. Click "Generate new token".
4. Pick the WhatsApp app, set permissions: `whatsapp_business_messaging`,
   `whatsapp_business_management`.
5. Copy the token immediately (it is shown once).
6. Update `core/.env`:
   ```
   ATENDIA_V2_META_ACCESS_TOKEN=<paste here>
   ```
7. **Do not commit `.env`.**

### Verify the refresh worked

```bash
cd core
uv run python -c "
import asyncio, httpx
from atendia.config import get_settings
async def main():
    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f'{s.meta_base_url}/{s.meta_api_version}/1011516488719911',
            headers={'Authorization': f'Bearer {s.meta_access_token}'},
        )
    print('status:', r.status_code)
    print('body:', {k: v for k, v in r.json().items() if 'token' not in k.lower()})
asyncio.run(main())
"
```

Status `200` = token valid. Status `401` with `code: 190` = still expired or
wrong scope.

---

## 3. Full E2E with a real WhatsApp message

Once the token is refreshed, three options for closing the operator
sign-off:

### Option A — Re-run the probe (simulated inbound, real outbound)

```bash
cd core
PYTHONIOENCODING=utf-8 uv run python -m scripts.e2e_meta_workflow
```

Expected output: every step green, exit code 0, and the script's
`SENDER_PHONE` (a fake `+5215512345678`) **will** receive the test message
*if* that number has opted into your WhatsApp Business app's testing
allowlist (Meta sandbox accounts can only send to numbers explicitly added
as test recipients in the app dashboard).

If the recipient isn't allowlisted, Meta returns a different error code
(typically 131030 — "recipient not in allowed list") and the rest of the
pipeline is still proven.

### Option B — Real inbound from your own phone

1. Add your personal WhatsApp number as a tester in
   <https://developers.facebook.com/apps/{app_id}/whatsapp-business/wa-dev-console/>.
2. Run the dev server with ngrok:
   ```bash
   cd core
   uv run uvicorn atendia.main:app --reload &
   ngrok http 8001
   ```
3. Configure the Meta app's webhook URL to
   `https://<ngrok-id>.ngrok.io/webhooks/meta/{tenant_id}`.
4. Run both arq workers in separate shells:
   ```bash
   uv run arq atendia.queue.worker.WorkerSettings
   uv run arq atendia.queue.worker.WorkflowWorkerSettings
   ```
5. Insert an active workflow into the tenant via
   `POST /api/v1/workflows` (tenant_admin login).
6. From your personal WhatsApp, send a message to **+52 1814 9835204**
   (Francisco Dinamo Motos NL).
7. Verify within ~10 seconds:
   - The runner's reply arrives at your phone (composer is `canned`, so
     the reply is the canned greeting).
   - The workflow's reply arrives at your phone (the text you set in the
     workflow's `message` action).
   - Both events show in `GET /api/v1/audit-log` with their `admin.*`
     types.

### Option C — Browser walkthrough

The frontend Conversations area should now show the message with the
right context (assigned agent name, document checklist, etc.). Cross-
reference against `docs/runbooks/conversations.md` §8.

---

## 4. Sign-off

Once **Option A passes** with a fresh token, the Meta E2E condition
(#2 of 5) is closed for Workflows. Record it in
`docs/handoffs/sign-offs/workflows-meta-e2e.md`:

```
date: <YYYY-MM-DD>
operator: <your initials>
probe exit code: 0
receipt status: sent
channel_message_id: <wamid.xxx from receipt>
notes: <any anomalies>
```

---

## 5. What this proves (be honest)

After Option A passes, what we have:

- **Webhook signature validation** works against real `META_APP_SECRET`.
- **Inline workflow trigger** (the cron-replacement wired in session 3)
  fires within the same request as the inbound message — no 60s polling
  gap.
- **Workflow engine** processes the `message_received` trigger, runs the
  `message` action, marks execution complete.
- **Meta Cloud API send** delivers (HTTP 2xx with `messages[0].id` returned
  by Meta).

What we **still don't** have, even after Option A:

- Confirmation that a **real WhatsApp client receives** the message —
  Meta's 2xx only confirms acceptance, not delivery. To confirm, watch
  the status callback (also handled in `/webhooks/meta/...`) or use
  Option B with your own phone.
- Confirmation that the message appears as expected in the recipient's
  chat (formatting, emoji rendering, etc.).
- Behavior under outside-24h windows (still blocked on Phase 3d.2
  templates; the workflow `message` action correctly fails with
  `OUTSIDE_24H_WINDOW`).

---

## 6. Cost

Each `e2e_meta_workflow.py` run sends **one** Meta API request. With
WhatsApp Cloud API pricing in MX (utility/marketing/service category), a
service-template message is ~$0.005–0.020 USD; free-form messages within
the 24h window are free per recipient/day above the free tier. Sandbox
accounts have free conversations up to a daily cap.

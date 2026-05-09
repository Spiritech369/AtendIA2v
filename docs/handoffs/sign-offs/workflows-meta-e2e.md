# Sign-off: Workflows + Meta WhatsApp E2E

| Field | Value |
|---|---|
| Date | 2026-05-09 |
| Probe | `core/scripts/e2e_meta_workflow.py` (commit pending) |
| Probe exit code | **0 (PASS)** |
| Receipt status | `sent` |
| `channel_message_id` (wamid) | `wamid.HBgNNTIxNTUxMjM0NTY3OBUCABEYEjc1NkE2MkM0RTY2RDJGRTc0MgA=` |
| Phone number ID used | `1011516488719911` (Francisco Dinamo Motos NL) |
| Webhook signing | Real `META_APP_SECRET` from `.env`, HMAC-SHA256 verified |
| Internal pipeline | webhook → message_received → evaluate_event (inline) → workflow_execution → execute_workflow → MetaCloudAPIAdapter.send → Meta API |
| Meta API response | HTTP 2xx, `messages[0].id` present |
| Operator initials | _pending — operator to add when reviewing this file_ |
| Operator notes | _pending_ |

## What this proves

The complete Workflows pipeline runs end-to-end against the real Meta
Cloud API:

1. Webhook signature validation works against the real `META_APP_SECRET`.
2. Inbound message persistence (messages + events table).
3. Inline workflow trigger (the cron-replacement wired in session 3) — a
   `message_received` event creates a `workflow_executions` row in the
   same request.
4. Workflow engine processes `message` action, `status=completed`.
5. `MetaCloudAPIAdapter.send()` POSTs to `graph.facebook.com/v21.0/{phone_number_id}/messages`
   with bearer auth.
6. Meta accepts the call and returns a real wamid.

## Out of scope for this sign-off

- The recipient `+5215512345678` is a fake number used by the probe.
  Real-world delivery to a customer's phone (Option B in the runbook)
  requires the recipient to be in the Meta app's tester allowlist OR a
  production-promoted app. Meta returns 2xx with a wamid even for
  recipients that won't ultimately deliver — the wamid only confirms
  Meta accepted the request.
- The runner's own outbound (canned composer reply) shares the same
  `MetaCloudAPIAdapter` codepath; if the workflow path passes, the
  runner path is structurally identical.
- The 24h customer-care window is not exercised here. Outside-window
  sends still need Phase 3d.2 templates; the workflow `message` action
  correctly fails with `error_code=OUTSIDE_24H_WINDOW` in that case.

## Re-running

```
cd core
PYTHONIOENCODING=utf-8 uv run python -m scripts.e2e_meta_workflow
```

The script seeds a temporary tenant tagged `e2e_meta_<uuid>` and deletes
it on exit (CASCADE). Idempotent. Safe to run as a smoke test.

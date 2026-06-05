# Dinamo Single Contact Smoke Scope

Generated: 2026-06-03T23:52:46-06:00

Decision: SCOPE_PHONE_APPROVED_CONTACT_ID_UNRESOLVED

No traffic was started. No tenant config was applied. No WhatsApp was sent. No actions or workflow side effects were enabled.

## Scope

| field | value |
| --- | --- |
| test_type | single_contact_live_smoke |
| tenant_name | Dinamo Motos NL |
| tenant_email | dinamomotosnl@gmail.com |
| tenant_id | 6ad78236-1fc9-467a-858d-90d248d57ee5 |
| domain | vehicle_credit_sales |
| agent_name | Francisco de Dinamo NL |
| agent_id | c169deec-226d-55b7-bd07-270f339e75a6 |
| agent_status | production |
| approved_test_phone | +528212889421 |
| approved_test_contact_id | unresolved |
| expected_volume | 1 conversation / 5-15 turns |
| business_owner | Francisco Esparza |
| technical_rollback_owner | Felipe Balderas |

## Contact Validation

The approved test phone is documented in:

- `docs/ops/rc5_canary_approved_scope.md`
- `docs/ops/rc5_canary_approved_scope.json`
- `reports/rc5_single_contact_smoke_contact_gate_verification.md`
- `reports/rc5_single_contact_smoke_activation_packet.md`

A read-only local DB lookup was attempted to resolve `approved_test_contact_id`, but Docker was unavailable and the configured localhost Postgres endpoint refused the connection. The contact ID remains unresolved in this package.

This is not treated as the primary blocker because the prior approved scope is phone based. The primary blocker is contact/phone gating in the universal `agent_runtime_v2` live-send path, documented in `reports/dinamo_single_contact_gate_verification.md`.

## Guardrails

- Do not start traffic automatically.
- Do not apply live config automatically.
- Do not activate canary 5 percent.
- Do not enable real actions.
- Do not enable real workflow side effects.
- Do not send WhatsApp until final human approval and a verified one-contact gate exist.
- Do not replace the legacy runner.

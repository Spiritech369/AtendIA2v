# Dinamo Single Contact Smoke Human Approval Request

Generated: 2026-06-03T23:52:46-06:00

Status: blocked_draft_only

Do not approve activation yet. The universal `agent_runtime_v2` live-send path does not currently enforce a one-contact phone/contact allowlist.

## Requested Scope After Blocker Is Fixed

| field | value |
| --- | --- |
| tenant | Dinamo Motos NL |
| tenant_id | 6ad78236-1fc9-467a-858d-90d248d57ee5 |
| agent | Francisco de Dinamo NL |
| agent_id | c169deec-226d-55b7-bd07-270f339e75a6 |
| approved phone | +528212889421 |
| approved contact_id | unresolved |
| volume | one conversation, 5-15 turns expected |
| live send | only to the approved phone/contact after gate fix |
| actions | off |
| workflow side effects | off |
| rollback | proposal ready |
| legacy fallback | available |
| canary 5 percent | not approved |

## Approval Preconditions

- Universal contact/phone gate implemented or a human-approved exception chooses the separate Dinamo live-limited path.
- Gate focused tests pass.
- Activation packet is regenerated with real enforceable config and proposal-only SQL.
- Human monitor is present.
- Rollback owner confirms readiness.
- No P0 stop condition is active.

## Stop Immediately If

- provider fallback > 0
- provider retry exhausted > 0
- WhatsApp sent to contact not approved
- outbox duplicated
- workflow side effect real
- action real
- price without quote snapshot
- stale quote
- cash quote when the customer asked for credit
- requirements mixed
- document_received without attachment
- approval promised
- buro treated as automatic rejection
- strong repetition
- false handoff
- unsafe response
- owner requests stop

## Required Final Approval Text

Use this exact text only after the blocker is fixed:

```text
Apruebo iniciar RC5 single_contact_live_smoke para 1 conversación desde el contacto aprobado.
No apruebo canary 5%.
No apruebo producción abierta.
Actions/workflows reales siguen apagados.
Acepto detener inmediatamente si aparece cualquier stop condition.
```

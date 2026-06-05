# RC5 Canary Result - Converted To Single Contact Smoke

Generated: 2026-06-03T17:18:31.5306424-06:00
Decision: READY_FOR_SINGLE_CONTACT_LIVE_SMOKE_APPROVAL
Ready for single-contact live smoke approval: true
Canary 5 percent activated: false
Traffic started: false
Tenant config applied: false

## Tenant Found

- tenant_id: 6ad78236-1fc9-467a-858d-90d248d57ee5
- name: Dinamo Motos NL
- email: dinamomotosnl@gmail.com
- status: active

## Agent Found

- agent_id: c169deec-226d-55b7-bd07-270f339e75a6
- name: Francisco de Dinamo NL
- status: production
- ambiguity: none

## Owners

- Business owner: Francisco Esparza
- Runtime owner: Felipe Balderas
- Provider owner: Felipe Balderas
- DB owner: Felipe Balderas
- Ops owner: Felipe Balderas
- Rollback owner: Felipe Balderas

## Smoke Scope

- Type: single_contact_live_smoke
- Expected volume: 1 conversation / 5-15 turns
- Approved test phone: +528212889421
- Provider real: approved for this smoke only
- Send real: approved only for +528212889421
- Actions enabled: false
- Workflow events enabled: false
- Escalation to 5 percent/10 percent/broad production: not approved

## Contact Gate

- Gate supported: true
- Mechanism: dinamo_agent_first_live_limited
- Focused test: 3 passed, 1 skipped
- Evidence: reports/rc5_single_contact_smoke_contact_gate_verification.md

## Preflight

- Ruff: pass
- Observability export: pass
- tests/agent_runtime -q: 169 passed, 2 warnings
- Provider stability: 5/5
- Provider fallback: 0
- Side effects: 0

## Remaining Before Start

- Final human approval.
- Manual application of the proposed config.
- Supervised window and monitoring active.

No traffic was started. No tenant config was applied.

# Dinamo Single Contact Smoke Readiness

Generated: 2026-06-03T23:52:46-06:00

Decision: NOT_READY_CONTACT_GATE_NOT_SUPPORTED

No traffic was started. No tenant config was applied. No WhatsApp was sent. Real actions and real workflow side effects remain off.

## Readiness Criteria

| criterion | result |
| --- | --- |
| approved phone exists | pass: +528212889421 |
| approved contact_id exists | unresolved: local DB unavailable |
| contact/phone gate confirmed for universal live path | fail |
| activation packet ready | fail: blocked, no activation SQL emitted |
| rollback packet ready | pass: proposal-only rollback ready |
| E2E pass | pass |
| backend no-DB pass | pass |
| real replay shadow pass | pass |
| actions/workflows real remain off | pass |
| config not applied automatically | pass |
| human approval request created | pass, blocked draft only |

## Preflight Results

1. `uv run pytest tests/agent_runtime/test_dinamo_shadow_e2e.py -q`

Result: `4 passed, 1 warning in 0.21s`.

2. `uv run pytest tests/agent_runtime -m "not integration_db" -q`

Result: `196 passed, 27 deselected, 2 warnings in 3.78s`.

3. `uv run python -m atendia.simulation.replay_eval --dataset ..\reports\dinamo_shadow_real_replay_dataset.anonymized.json --tenant-domain-contract tests\agent_runtime\fixtures\tenant_domain_contracts\dinamo_motos_nl_shadow.json --anonymized`

Result: pass.

Key replay metrics:

- replay_cases_passed: 20
- replay_cases_total: 20
- dataset_turns_total: 109
- definition_of_done_pass: true
- critical_failure_count: 0
- side_effect_count: 0
- whatsapp_sent_count: 0
- outbox_count: 0
- workflow_side_effect_count: 0
- provider_fallback_count: 0
- provider_fallback_response_count: 0
- provider_invoked: false
- stale_quote_count: 0
- price_without_quote_count: 0
- requirements_mixed_count: 0
- document_received_without_attachment_count: 0
- approval_promised_count: 0
- false_handoff_count: 0
- high_risk_conversations: 0 in regenerated human review artifact

Focused separate Dinamo gate test:

`3 passed, 1 skipped, 2 warnings in 1.36s`.

## Warnings Documented

- No real anonymized attachments existed in real replay; `document.check` real path remains covered by deterministic E2E.
- Coverage gaps remain: `por_fuera_como_no_apto`, `buro_como_rechazo_automatico`, `ok/va/si despues de cotizacion`, `referencias tipo la primera/esa/la otra`.
- `uv run pytest tests/simulation -q` previously had one preexisting failure in `advisor_first_multiturn case_05 repetition_detected`.

## Final Decision

`NOT_READY_CONTACT_GATE_NOT_SUPPORTED`

The package is not ready for live approval because `live_send_enabled=true` cannot currently be limited to the approved phone/contact in the universal `agent_runtime_v2` live-send path. The separate Dinamo-specific live-limited gate is real and tested, but using it would require an explicit human exception and a regenerated activation packet.

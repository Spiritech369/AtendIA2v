# Runner suite failure triage

Generated: 2026-06-05

Runner suite decision: RUNNER_SUITE_BLOCKS_SMOKE

Command:

```bash
uv run pytest tests/runner/test_conversation_runner.py -q -vv
```

Result: 7 failed, 21 passed, 3 warnings.

## Summary

The 7 failures reproduced in tenants without `agent_runtime_v2.runtime_v2_enabled`.
The three runtime v2 runner tests passed in the same file, which means the new v2 send path is not the direct cause.

No runner failures were fixed in this task because the instruction was to fix only failures caused by the v2 send path.
However, two failures touch legacy customer-visible fallback/handoff behavior, so they cannot be waived under the requested waiver criteria.

## Failures

| test | error | line | caused by v2 send path | affects smoke | classification | immediate fix |
| --- | --- | ---: | --- | --- | --- | --- |
| `test_runner_validator_blocks_unsafe_composer_output` | expected `trace.outbound_messages is None`, got `['Y para seguir, dime que modelo quieres revisar.']` | `tests/runner/test_conversation_runner.py:790` | no | blocks waiver because it touches visible fallback/outbound behavior | `LEGACY_BEHAVIOR_REGRESSION`, `BLOCKER_FOR_SMOKE` | yes, before approval |
| `test_runner_24h_handoff_creates_row_no_compose` | `TypeError: build_handoff_summary() got an unexpected keyword argument 'document_requirements'` | `atendia/runner/conversation_runner.py:6296` | no | not direct v2 smoke path; outside-24h legacy handoff | `PREEXISTING_TEST_DEBT`, `NON_BLOCKING_FOR_SMOKE_WITH_EVIDENCE` | no for v2 smoke |
| `test_runner_composer_failure_creates_handoff` | expected one handoff row, got zero | `tests/runner/test_conversation_runner.py:988` | no | blocks waiver because it touches composer failure/fallback handoff behavior | `LEGACY_BEHAVIOR_REGRESSION`, `BLOCKER_FOR_SMOKE` | yes, before approval |
| `test_runner_prefers_agent_flow_mode_rules_over_pipeline_rules` | expected `agent_retention:keyword_in_text`, got `agent_retention:keyword_in_text:agent_directed_from_ask_clarification` | `tests/runner/test_conversation_runner.py:1384` | no | no direct v2/send/outbox impact | `TEST_EXPECTATION_NEEDS_UPDATE`, `NON_BLOCKING_FOR_SMOKE_WITH_EVIDENCE` | no for v2 smoke |
| `test_pending_confirmation_si_assigns_tipo_credito` | expected `pending_confirmation is None`, got `is_nomina_tarjeta` | `tests/runner/test_conversation_runner.py:1478` | no | legacy confirmation state; no v2/send/outbox impact | `LEGACY_BEHAVIOR_REGRESSION`, `NON_BLOCKING_FOR_SMOKE_WITH_EVIDENCE` | no for v2 smoke |
| `test_pending_confirmation_no_to_negocio_sat_assigns_sin_comprobantes` | expected `pending_confirmation is None`, got `is_negocio_sat` | `tests/runner/test_conversation_runner.py:1523` | no | legacy confirmation state; no v2/send/outbox impact | `LEGACY_BEHAVIOR_REGRESSION`, `NON_BLOCKING_FOR_SMOKE_WITH_EVIDENCE` | no for v2 smoke |
| `test_composer_pending_confirmation_set_persists` | expected `is_nomina_recibos`, got `None` | `tests/runner/test_conversation_runner.py:1606` | no | legacy composer state persistence; no v2/send/outbox impact | `LEGACY_BEHAVIOR_REGRESSION`, `NON_BLOCKING_FOR_SMOKE_WITH_EVIDENCE` | no for v2 smoke |

## Evidence

- `test_v2_preview_only_tenant_skips_legacy_composer_and_visible_output`: passed.
- `test_v2_auto_send_tenant_skips_legacy_composer_and_visible_output`: passed.
- `test_v2_tenant_ignores_explicit_legacy_fallback_flags`: passed.
- The failing tests seed tenants via legacy helpers and do not enable `agent_runtime_v2.runtime_v2_enabled`.
- V2 send path tests pass separately: `tests/agent_runtime/test_runtime_v2_send_path_for_dinamo_smoke.py` result is 6 passed.

## Waiver status

Waiver denied for the full runner suite because at least two failures touch fallback visible/handoff behavior:

- `test_runner_validator_blocks_unsafe_composer_output`
- `test_runner_composer_failure_creates_handoff`

These are not v2-send-path regressions, but they prevent claiming runner preflight is non-blocking under the requested criteria.

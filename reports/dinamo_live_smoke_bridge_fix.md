# Dinamo live smoke bridge fix

Generated: 2026-06-05

Decision: NEEDS_RUNTIME_V2_SEND_PATH_INSTEAD

## Summary

The requested bridge was not implemented because the latest requirement is stricter: legacy must no longer be fallback, escape hatch, or visible response path for runtime v2 tenants.

For any tenant with `agent_runtime_v2.runtime_v2_enabled = true`, `ConversationRunner` now blocks the legacy composer/outbound path and writes a silent trace instead. If runtime v2 cannot produce/send the customer-facing answer, the system must stay no-send rather than falling back to legacy copy.

## Product change

- `core/atendia/runner/conversation_runner.py`
  - `_legacy_runner_disabled_for_v2` now disables legacy whenever `runtime_v2_enabled` is true.
  - The legacy fallback flags `legacy_runner_fallback_enabled`, `allow_legacy_runner_fallback`, and `disable_legacy_runner_fallback` no longer control this product path.
  - The trace hint now states that `agent_runtime_v2` must own the visible response path.

## Test updates

- `core/tests/runner/test_conversation_runner.py`
  - Preview-only runtime v2 tenants now assert silent no-send behavior, not legacy fallback.
  - Explicit legacy fallback flags are ignored for runtime v2 tenants.
- `core/tests/architecture/test_legacy_deactivation_after_persistent_simulation.py`
  - Architecture contract now rejects legacy fallback flags in `conversation_runner.py`.
- `core/tests/architecture/test_dinamo_live_state_mismatch_regression.py`
  - Replaced the previous xfail bridge tests with focused contract tests for legacy deactivation.
- `core/tests/agent_runtime/test_agent_runtime_v2.py`
  - Updated the obsolete direct-runtime assertion to match the new no-legacy contract.

## Validation

Executed against isolated `postgres-test` with migrated test database:

- `tests/architecture/test_dinamo_live_state_mismatch_regression.py`
  - Result: 3 passed, 2 warnings.
- Focused legacy deactivation and runner tests:
  - `tests/architecture/test_dinamo_live_state_mismatch_regression.py`
  - `tests/architecture/test_legacy_deactivation_after_persistent_simulation.py`
  - `tests/runner/test_conversation_runner.py::test_v2_preview_only_tenant_skips_legacy_composer_and_visible_output`
  - `tests/runner/test_conversation_runner.py::test_v2_auto_send_tenant_skips_legacy_composer_and_visible_output`
  - `tests/runner/test_conversation_runner.py::test_v2_tenant_ignores_explicit_legacy_fallback_flags`
  - Result: 10 passed, 2 warnings.
- `tests/agent_runtime -m "not integration_db"`
  - Result: 198 passed, 27 deselected, 2 warnings.
- Ruff on updated focused test files:
  - Result: passed.

## Not validated as clean

- Full `tests/runner` did not pass because existing collection/runtime failures remain outside this change:
  - missing `VisionCategory` import from `atendia.contracts.vision_result`
  - missing `_render_structured_quote_messages` import from `conversation_runner`
  - several pre-existing runner behavior mismatches in `tests/runner/test_conversation_runner.py`
- Full ruff over `conversation_runner.py` is still blocked by existing file-level lint debt unrelated to this small logic change.

## Live traffic impact

No WhatsApp traffic was sent and no live tenant configuration was changed during this fix.

For runtime v2 tenants still configured as preview-only/no-send, the expected behavior is now silence with traceability instead of legacy response text. Enabling visible live answers now requires the runtime v2 send path to be ready for that tenant.

## Remaining work

- Implement or enable the runtime v2 live send path for Dinamo before expecting customer-visible answers.
- Keep price, cash-payment, and manual-document policy handling inside tenant-scoped runtime v2 configuration/data, not legacy composer logic.
- Audit any manual recovery scripts outside `ConversationRunner`; this change blocks the main legacy runner path, not arbitrary external scripts.

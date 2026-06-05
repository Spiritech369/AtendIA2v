# Dinamo Single Contact Gate Verification

Generated: 2026-06-03T23:52:46-06:00

Decision: CONTACT_GATE_NOT_SUPPORTED

This decision is scoped to the universal `agent_runtime_v2` live-send path requested for the `single_contact_live_smoke` package.

## Universal Path Result

The universal `agent_runtime_v2` send path does not currently expose or enforce a contact/phone allowlist before staging an outbound message.

Evidence:

- `core/atendia/agent_runtime/rollout_policy.py:47` and `core/atendia/agent_runtime/rollout_policy.py:48` define tenant rollout allowlists for agents and channels only.
- `core/atendia/agent_runtime/rollout_policy.py:163` implements `can_send` without contact, customer, or phone inputs.
- `core/atendia/agent_runtime/pilot_policy.py:24` through `core/atendia/agent_runtime/pilot_policy.py:27` define pilot tenant, agent, channel, and daily send limits, but no contact or phone allowlist.
- `core/atendia/api/conversations_routes.py:1246` checks only conversation state, pause, handoff, inbound presence, and WhatsApp 24h window.
- `core/atendia/api/conversations_routes.py:1820` fetches `Customer.phone_e164` after rollout and pilot policy checks.
- `core/atendia/api/conversations_routes.py:1837` stages outbound without a contact allowlist check.

Therefore `live_send_enabled=true` cannot be honestly constrained to one approved contact in the universal send path today.

## Separate Dinamo-Specific Path

A separate, Dinamo-specific live-limited gate exists and was verified:

- `core/atendia/runner/dinamo_agent_runtime.py:151` passes customer ID and phone into `_live_limited_allowed`.
- `core/atendia/runner/dinamo_agent_runtime.py:169` blocks non-allowlisted live-limited traffic with `dinamo_live_limited_not_allowlisted`.
- `core/atendia/runner/dinamo_agent_runtime.py:1102` checks `allowed_contact_ids`.
- `core/atendia/runner/dinamo_agent_runtime.py:1106` checks `allowed_phone_numbers`.
- `core/atendia/runner/conversation_runner.py:3746` only enqueues through that path when `runtime_selection.live_limited_allowed` is true.

Focused verification command:

```powershell
uv run pytest tests/architecture/test_dinamo_agent_first_runtime.py::test_real_outbox_stays_blocked_without_live_limited_allowlist tests/architecture/test_dinamo_agent_first_runtime.py::test_live_limited_allowlist_unblocks_real_outbox_for_one_phone_only tests/architecture/test_advisor_brain_primary_canary_contract.py::test_primary_canary_allowlist_requires_target_customer_or_test_marker tests/architecture/test_advisor_brain_primary_canary_contract.py::test_manual_whatsapp_prepare_configures_allowlist_only_for_target_customer_and_phone -q
```

Result: `3 passed, 1 skipped, 2 warnings`.

## Gate Decision

The separate Dinamo-specific path is real and verifiable, but it is not the universal `agent_runtime_v2` live-send path requested for this approval package. Activation is blocked until the universal path supports a real contact/phone gate or a human explicitly approves using the separate Dinamo-specific live-limited path as an exception.

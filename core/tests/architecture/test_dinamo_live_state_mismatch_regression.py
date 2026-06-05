from __future__ import annotations

from atendia.runner.conversation_runner import _legacy_runner_disabled_for_v2


def test_runtime_v2_preview_only_disables_legacy_fallback() -> None:
    assert _legacy_runner_disabled_for_v2(
        {
            "agent_runtime_v2": {
                "runtime_v2_enabled": True,
                "preview_enabled": True,
                "send_enabled": False,
                "auto_send_enabled": False,
                "outbox_enabled": False,
                "rollout_mode": "preview_only",
            }
        }
    ) is True


def test_runtime_v2_ignores_legacy_fallback_escape_hatches() -> None:
    assert _legacy_runner_disabled_for_v2(
        {
            "agent_runtime_v2": {
                "runtime_v2_enabled": True,
                "legacy_runner_fallback_enabled": True,
                "allow_legacy_runner_fallback": True,
            }
        }
    ) is True


def test_non_runtime_v2_tenant_can_still_use_legacy_runner() -> None:
    assert _legacy_runner_disabled_for_v2(
        {
            "agent_runtime_v2": {
                "runtime_v2_enabled": False,
                "rollout_mode": "legacy",
            }
        }
    ) is False

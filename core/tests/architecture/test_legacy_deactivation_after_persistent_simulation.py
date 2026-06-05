from __future__ import annotations

from pathlib import Path

from atendia.agent_runtime import ActionRequest, PolicyValidator, TurnOutput

CORE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = CORE_ROOT.parent


def _source(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    if not path.exists() and relative_path.startswith("core/"):
        path = CORE_ROOT / relative_path.removeprefix("core/")
    return path.read_text(encoding="utf-8")


def test_simulation_lab_does_not_route_through_legacy_runner_or_composer() -> None:
    simulation_sources = "\n".join(
        _source(path)
        for path in (
            "core/atendia/simulation/runner.py",
            "core/atendia/simulation/run_dinamo_order_chaos.py",
            "core/atendia/simulation/service.py",
        )
    )

    forbidden_legacy_paths = (
        "atendia.runner.conversation_runner",
        "ConversationRunner",
        "advisor_brain",
        "sales_advisor_decision_policy",
        "flow_router",
        "turn_resolver",
        "response_frame",
        "response_contract",
        "composer_openai",
    )
    for forbidden in forbidden_legacy_paths:
        assert forbidden not in simulation_sources


def test_v2_tenants_never_use_legacy_runner_as_fallback() -> None:
    source = _source("core/atendia/runner/conversation_runner.py")

    assert "def _legacy_runner_disabled_for_v2" in source
    assert "runtime_v2_enabled" in source
    assert "legacy_runner_fallback_enabled" not in source
    assert "allow_legacy_runner_fallback" not in source
    assert "disable_legacy_runner_fallback" not in source
    assert "legacy_runner_disabled_for_v2" in source
    assert "visible_copy_written" in source


def test_legacy_modules_are_marked_as_fallback_not_v2_copy_authority() -> None:
    fallback_modules = (
        "core/atendia/runner/advisor_brain.py",
        "core/atendia/runner/sales_advisor_decision_policy.py",
        "core/atendia/runner/turn_resolver.py",
        "core/atendia/runner/response_contract.py",
    )
    for module in fallback_modules:
        source = _source(module).lower()
        assert "legacy" in source
        assert "fallback" in source

    response_frame = _source("core/atendia/runner/response_frame.py")
    composer_protocol = _source("core/atendia/runner/composer_protocol.py")
    assert "TurnOutput.final_message" in response_frame
    assert "TurnOutput.final_message" in composer_protocol


def test_v2_policy_rejects_action_payloads_with_visible_copy() -> None:
    output = TurnOutput(
        final_message="Te ayudo con eso.",
        confidence=0.9,
        actions=[
            ActionRequest(
                name="add_tag",
                payload={"tag": "handoff", "message": "Visible copy must not live here."},
            )
        ],
    )

    issues = PolicyValidator().validate(output)

    assert [issue.code for issue in issues] == ["action_returns_visible_text"]

import pytest

from atendia.product_agents.service import ProductAgentError, validate_action_permissions


def test_action_binding_permissions_allow_disabled_without_permissions() -> None:
    validate_action_permissions(
        execution_mode="disabled",
        permissions={},
        enabled=False,
    )


def test_action_binding_permissions_require_permissions_for_enabled_mode() -> None:
    with pytest.raises(ProductAgentError):
        validate_action_permissions(
            execution_mode="dry_run_only",
            permissions={},
            enabled=True,
        )


def test_action_binding_permissions_reject_enabled_disabled_mode() -> None:
    with pytest.raises(ProductAgentError):
        validate_action_permissions(
            execution_mode="disabled",
            permissions={"allowed": True},
            enabled=True,
        )


def test_action_binding_permissions_reject_unknown_mode() -> None:
    with pytest.raises(ProductAgentError):
        validate_action_permissions(
            execution_mode="send_live",
            permissions={"allowed": True},
            enabled=True,
        )


def test_action_binding_permissions_reject_non_object_permissions() -> None:
    with pytest.raises(ProductAgentError):
        validate_action_permissions(
            execution_mode="disabled",
            permissions=[],  # type: ignore[arg-type]
            enabled=False,
        )

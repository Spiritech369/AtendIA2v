from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from atendia.agent_runtime import (
    ActionDefinition,
    ActionRegistry,
    ActionRequest,
    ActionResult,
    AgentRuntime,
    FieldUpdate,
    LifecycleUpdate,
    PolicyValidationError,
    PolicyValidator,
    PostTurnActionExecutor,
    ToolExecutionResult,
    TurnInput,
    TurnOutput,
)
from atendia.agent_runtime.runtime import agent_runtime_v2_enabled
from atendia.config import Settings
from atendia.runner import conversation_runner as legacy_runner_module
from atendia.runner.conversation_runner import ConversationRunner


def _valid_output(**overrides) -> TurnOutput:
    data = {
        "final_message": "Claro, te ayudo con eso.",
        "confidence": 0.8,
        "needs_human": False,
    }
    data.update(overrides)
    return TurnOutput(**data)


def test_valid_turn_output_passes_validation():
    PolicyValidator().validate_or_raise(_valid_output())


def test_turn_output_without_final_message_and_without_human_fails():
    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(_valid_output(final_message=""))

    assert "missing_final_message" in str(exc.value)


def test_unknown_action_fails_validation():
    output = _valid_output(actions=[ActionRequest(name="invent_quote_pdf")])

    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(output)

    assert "unknown_action" in str(exc.value)


def test_turn_output_rejects_extra_output_contract_fields():
    with pytest.raises(ValidationError):
        TurnOutput.model_validate(
            {
                "final_message": "Uno solo.",
                "final_messages": ["Uno solo.", "Otro no permitido."],
                "confidence": 0.8,
            }
        )


def test_action_request_rejects_extra_visible_text_fields():
    with pytest.raises(ValidationError):
        ActionRequest.model_validate(
            {
                "name": "add_tag",
                "payload": {"tag": "vip"},
                "final_message": "No va aqui.",
            }
        )


def test_field_update_without_evidence_or_reason_fails():
    output = _valid_output(field_updates=[FieldUpdate(field_key="email", value="a@b.test")])

    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(output)

    assert "field_update_missing_evidence" in str(exc.value)


def test_field_update_requires_valid_confidence():
    missing = _valid_output(
        field_updates=[
            FieldUpdate(
                field_key="email",
                value="a@b.test",
                reason="Customer provided email.",
                evidence=["a@b.test"],
            )
        ]
    )
    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(missing)
    assert "field_update_missing_confidence" in str(exc.value)

    invalid = _valid_output(
        field_updates=[
            FieldUpdate(
                field_key="email",
                value="a@b.test",
                reason="Customer provided email.",
                evidence=["a@b.test"],
                confidence=1.2,
            )
        ]
    )
    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(invalid)
    assert "field_update_invalid_confidence" in str(exc.value)


def test_lifecycle_update_without_reason_fails():
    output = _valid_output(lifecycle_update=LifecycleUpdate(target_stage="qualified"))

    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(output)

    assert "lifecycle_update_missing_reason" in str(exc.value)


def test_sensitive_action_requires_approval_when_definition_requires_it():
    output = _valid_output(
        actions=[
            ActionRequest(
                name="call_webhook",
                payload={"webhook_id": "ops-alert"},
                reason="Customer explicitly requested an external escalation.",
            )
        ]
    )

    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(output)

    assert "sensitive_action_missing_approval" in str(exc.value)

    approved = _valid_output(
        actions=[
            ActionRequest(
                name="call_webhook",
                payload={"webhook_id": "ops-alert"},
                reason="Customer explicitly requested an external escalation.",
                evidence=["Customer explicitly requested an external escalation."],
                requires_approval=True,
            )
        ]
    )
    PolicyValidator().validate_or_raise(approved)


@pytest.mark.asyncio
async def test_runtime_produces_exactly_one_final_message():
    output = await AgentRuntime().run_turn(
        TurnInput(
            tenant_id="tenant-1",
            conversation_id="conversation-1",
            inbound_text="Hola",
        )
    )

    assert isinstance(output.final_message, str)
    assert output.final_message.strip()
    assert not hasattr(output, "final_messages")
    assert output.trace_metadata["provider"] == "advisor_first_pipeline"
    assert output.trace_metadata["architecture"] == [
        "context_builder",
        "advisor_brain",
        "tool_layer",
        "policy_validation",
        "state_update_proposal",
        "composer",
    ]


def test_tool_results_cannot_return_customer_visible_copy():
    with pytest.raises(ValidationError):
        ToolExecutionResult.model_validate(
            {
                "tool_name": "quote_resolver",
                "status": "succeeded",
                "data": {"final_message": "No va aqui."},
            }
        )


@pytest.mark.asyncio
async def test_post_turn_executor_does_not_execute_unknown_actions():
    output = _valid_output(actions=[ActionRequest(name="unknown_action")])
    results = await PostTurnActionExecutor().execute(output)

    assert results[0].status == "failed"
    assert results[0].trace_metadata["executed"] is False


def test_low_confidence_requires_human_or_risk_flag():
    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(_valid_output(confidence=0.2))

    assert "low_confidence_unflagged" in str(exc.value)

    PolicyValidator().validate_or_raise(_valid_output(confidence=0.2, needs_human=True))
    PolicyValidator().validate_or_raise(
        _valid_output(confidence=0.2, risk_flags=["low_confidence"])
    )


def test_actions_cannot_return_customer_visible_final_text():
    with pytest.raises(ValidationError):
        ActionResult.model_validate(
            {
                "action_name": "update_contact_field",
                "status": "succeeded",
                "data": {},
                "final_message": "This must stay in AgentRuntime, not actions.",
            }
        )

    with pytest.raises(ValidationError):
        ActionResult.model_validate(
            {
                "action_name": "update_contact_field",
                "status": "succeeded",
                "data": {"final_message": "This also must stay out of action data."},
            }
        )

    with pytest.raises(ValidationError):
        ActionResult.model_validate(
            {
                "action_name": "update_contact_field",
                "status": "succeeded",
                "data": {"nested": {"reply": "This must not be hidden in nested data."}},
            }
        )

    output = _valid_output(
        actions=[
            ActionRequest(
                name="add_tag",
                payload={"visible_text": "Do not send this to the customer."},
            )
        ]
    )
    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(output)
    assert "action_returns_visible_text" in str(exc.value)

    nested = _valid_output(
        actions=[
            ActionRequest(
                name="add_tag",
                payload={"tag": "vip", "nested": {"message": "Do not show this."}},
            )
        ]
    )
    with pytest.raises(PolicyValidationError) as exc:
        PolicyValidator().validate_or_raise(nested)
    assert "nested.message" in str(exc.value)


@pytest.mark.asyncio
async def test_executor_blocks_policy_invalid_known_action_before_handler_runs():
    registry = ActionRegistry()
    called = False

    async def handler(action, context):
        nonlocal called
        called = True
        return ActionResult(action_name=action.name, status="succeeded")

    registry.register(
        ActionDefinition(
            name="sensitive_action",
            description="test action",
            sensitive=True,
            requires_evidence=True,
        ),
        handler=handler,
    )
    output = _valid_output(actions=[ActionRequest(name="sensitive_action")])

    results = await PostTurnActionExecutor(
        registry=registry,
        dry_run=False,
        require_runtime_enabled=False,
    ).execute(output)

    assert called is False
    assert results[0].status == "failed"
    assert results[0].trace_metadata["policy_blocked"] is True


@pytest.mark.asyncio
async def test_registry_drops_stale_handler_when_action_is_reregistered_without_handler():
    registry = ActionRegistry()
    called = False

    async def handler(action, context):
        nonlocal called
        called = True
        return ActionResult(action_name=action.name, status="succeeded")

    registry.register(
        ActionDefinition(name="add_tag", description="first registration"),
        handler=handler,
    )
    registry.register(ActionDefinition(name="add_tag", description="stub registration"))

    output = _valid_output(actions=[ActionRequest(name="add_tag", payload={"tag": "vip"})])
    results = await PostTurnActionExecutor(
        registry=registry,
        dry_run=False,
        require_runtime_enabled=False,
    ).execute(output)

    assert called is False
    assert results[0].status == "skipped"
    assert results[0].data["stub"] is True


def test_legacy_runner_imports_and_runtime_v2_flag_is_off_by_default():
    settings = Settings(_env_file=None)  # type: ignore[arg-type]

    assert agent_runtime_v2_enabled(settings) is False
    assert settings.agent_runtime_v2_enabled is False
    assert hasattr(ConversationRunner, "run_turn")


def test_conversation_runner_wires_runtime_v2_only_behind_v2_guard():
    source = inspect.getsource(legacy_runner_module)

    assert "AgentRuntime(" in source
    assert "ContextBuilder(session)" in source
    assert "legacy_runner_disabled_for_v2" in source
    assert "agent_runtime_v2_prepared_send_path" in source
    assert "evaluate_prepared_send_policy" in source

from __future__ import annotations

from collections.abc import Awaitable, Callable

from atendia.agent_runtime.schemas import ActionDefinition, ActionRequest, ActionResult, TurnContext

ActionHandler = Callable[[ActionRequest, TurnContext | None], Awaitable[ActionResult]]


class UnknownActionError(KeyError):
    """Raised when an action is not registered for agent_runtime_v2."""


class ActionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ActionDefinition] = {}
        self._handlers: dict[str, ActionHandler] = {}

    def register(
        self,
        definition: ActionDefinition,
        handler: ActionHandler | None = None,
    ) -> None:
        self._definitions[definition.name] = definition
        if handler is not None:
            self._handlers[definition.name] = handler
        else:
            self._handlers.pop(definition.name, None)

    def has_action(self, name: str) -> bool:
        definition = self._definitions.get(name)
        return bool(definition and definition.enabled)

    def get(self, name: str) -> ActionDefinition:
        definition = self._definitions.get(name)
        if definition is None or not definition.enabled:
            raise UnknownActionError(name)
        return definition

    def handler_for(self, name: str) -> ActionHandler | None:
        self.get(name)
        return self._handlers.get(name)

    def list_definitions(self) -> list[ActionDefinition]:
        return [self._definitions[name] for name in sorted(self._definitions)]


def default_action_registry() -> ActionRegistry:
    registry = ActionRegistry()
    registry.register(
        ActionDefinition(
            id="update_contact_field",
            name="update_contact_field",
            description="Propose a structured update to a customer/contact field.",
            input_schema={
                "type": "object",
                "required": ["field_key", "value"],
                "properties": {
                    "field_key": {"type": "string"},
                    "value": {},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
            permissions=["contact_memory.write"],
            capabilities=["contact_memory"],
            risk_level="medium",
            execution_mode="execute",
            requires_evidence=True,
        )
    )
    registry.register(
        ActionDefinition(
            id="move_lifecycle",
            name="move_lifecycle",
            description="Move the conversation or customer lifecycle/pipeline stage.",
            input_schema={
                "type": "object",
                "required": ["target_stage"],
                "properties": {
                    "target_stage": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
            permissions=["lifecycle.write"],
            capabilities=["lifecycle"],
            risk_level="high",
            execution_mode="execute",
            sensitive=True,
            requires_evidence=True,
        )
    )
    registry.register(
        ActionDefinition(
            id="assign_conversation",
            name="assign_conversation",
            description="Assign the conversation to a human operator or team.",
            input_schema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "unassign": {"type": "boolean"},
                },
            },
            permissions=["conversation.assign"],
            capabilities=["inbox"],
            risk_level="medium",
            execution_mode="execute",
            sensitive=True,
            requires_evidence=True,
        )
    )
    registry.register(
        ActionDefinition(
            id="add_tag",
            name="add_tag",
            description="Add a structured tag to the conversation or customer.",
            input_schema={
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
            permissions=["conversation.tag"],
            capabilities=["inbox"],
            risk_level="low",
            execution_mode="execute",
        )
    )
    registry.register(
        ActionDefinition(
            id="trigger_workflow",
            name="trigger_workflow",
            description="Trigger a workflow by id or key after the agent turn.",
            input_schema={
                "type": "object",
                "required": ["workflow_id"],
                "properties": {"workflow_id": {"type": "string"}},
            },
            permissions=["workflow.trigger"],
            capabilities=["workflows"],
            risk_level="high",
            execution_mode="human_approval",
            sensitive=True,
            requires_evidence=True,
            requires_approval=True,
        )
    )
    registry.register(
        ActionDefinition(
            id="call_webhook",
            name="call_webhook",
            description="Call an outbound webhook through the action layer.",
            input_schema={
                "type": "object",
                "required": ["webhook_id"],
                "properties": {"webhook_id": {"type": "string"}},
            },
            permissions=["integration.webhook.call"],
            capabilities=["integrations"],
            risk_level="high",
            execution_mode="human_approval",
            sensitive=True,
            requires_evidence=True,
            requires_approval=True,
        )
    )
    registry.register(
        ActionDefinition(
            id="close_conversation",
            name="close_conversation",
            description="Close the conversation after an explicit lifecycle decision.",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["closed", "resolved"]},
                    "category": {"type": "string"},
                },
            },
            permissions=["conversation.close"],
            capabilities=["inbox"],
            risk_level="high",
            execution_mode="execute",
            sensitive=True,
            requires_evidence=True,
        )
    )
    return registry

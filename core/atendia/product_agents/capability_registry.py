from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CapabilityKind = Literal["tool", "action"]
ExecutionMode = Literal["disabled", "dry_run_only", "approval_required"]


@dataclass(frozen=True)
class ProductCapability:
    key: str
    label: str
    kind: CapabilityKind
    category: str
    description: str
    risk_level: str
    side_effect_type: str
    default_mode: ExecutionMode
    required_auth: bool = False
    required_permissions: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    publish_blockers: tuple[str, ...] = ()

    @property
    def has_side_effects(self) -> bool:
        return self.side_effect_type != "none"


OBJECT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}

PRODUCT_CAPABILITIES: tuple[ProductCapability, ...] = (
    ProductCapability(
        key="catalog.search",
        label="Catalog search",
        kind="tool",
        category="fact_lookup",
        description="Finds tenant catalog records and product references.",
        risk_level="read_only",
        side_effect_type="none",
        default_mode="dry_run_only",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema=OBJECT_SCHEMA,
    ),
    ProductCapability(
        key="quote.resolve",
        label="Quote resolver",
        kind="tool",
        category="fact_lookup",
        description="Resolves a quote from tenant-backed catalog and plan data.",
        risk_level="read_only",
        side_effect_type="none",
        default_mode="dry_run_only",
        input_schema=OBJECT_SCHEMA,
        output_schema=OBJECT_SCHEMA,
    ),
    ProductCapability(
        key="requirements.lookup",
        label="Requirements lookup",
        kind="tool",
        category="fact_lookup",
        description="Looks up tenant requirements and document rules.",
        risk_level="read_only",
        side_effect_type="none",
        default_mode="dry_run_only",
        input_schema=OBJECT_SCHEMA,
        output_schema=OBJECT_SCHEMA,
    ),
    ProductCapability(
        key="document.check",
        label="Document check",
        kind="tool",
        category="fact_lookup",
        description="Classifies and checks document evidence without writing state.",
        risk_level="read_only",
        side_effect_type="none",
        default_mode="dry_run_only",
        input_schema=OBJECT_SCHEMA,
        output_schema=OBJECT_SCHEMA,
    ),
    ProductCapability(
        key="update_contact_field",
        label="Update contact field",
        kind="action",
        category="state_write",
        description="Requests a governed contact field update.",
        risk_level="internal_write",
        side_effect_type="crm_write",
        default_mode="approval_required",
        required_permissions=("contact.write",),
        input_schema=OBJECT_SCHEMA,
        output_schema=OBJECT_SCHEMA,
        publish_blockers=("field_policy_required", "approval_policy_required"),
    ),
    ProductCapability(
        key="trigger_workflow",
        label="Trigger workflow",
        kind="action",
        category="workflow",
        description="Requests a workflow event through approved bindings.",
        risk_level="external_write",
        side_effect_type="workflow_trigger",
        default_mode="approval_required",
        required_permissions=("workflow.trigger",),
        input_schema=OBJECT_SCHEMA,
        output_schema=OBJECT_SCHEMA,
        publish_blockers=("workflow_binding_required", "side_effect_policy_required"),
    ),
    ProductCapability(
        key="call_webhook",
        label="Call webhook",
        kind="action",
        category="external_integration",
        description="Requests an external webhook call in dry-run or approved mode.",
        risk_level="external_write",
        side_effect_type="webhook",
        default_mode="approval_required",
        required_auth=True,
        required_permissions=("webhook.call",),
        input_schema=OBJECT_SCHEMA,
        output_schema=OBJECT_SCHEMA,
        publish_blockers=("auth_required", "idempotency_required", "approval_policy_required"),
    ),
    ProductCapability(
        key="send_message",
        label="Send message boundary",
        kind="action",
        category="send_boundary",
        description="Represents the customer-send boundary. It is blocked in Builder phases.",
        risk_level="critical",
        side_effect_type="message_send_request",
        default_mode="disabled",
        required_auth=True,
        required_permissions=("send.message",),
        input_schema=OBJECT_SCHEMA,
        output_schema=OBJECT_SCHEMA,
        publish_blockers=("send_adapter_boundary", "explicit_live_approval_required"),
    ),
)


def list_capabilities(kind: CapabilityKind | None = None) -> list[ProductCapability]:
    return [
        capability
        for capability in PRODUCT_CAPABILITIES
        if kind is None or capability.kind == kind
    ]


def get_capability(key: str, *, kind: CapabilityKind | None = None) -> ProductCapability | None:
    normalized = key.strip()
    for capability in PRODUCT_CAPABILITIES:
        if capability.key == normalized and (kind is None or capability.kind == kind):
            return capability
    return None

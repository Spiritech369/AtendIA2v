from __future__ import annotations

from typing import Any

from atendia.contact_memory.schemas import (
    ContactMemoryPolicyConfig,
    ContactMemoryWriteRequest,
    FieldUpdateStatus,
)
from atendia.db.models.customer_fields import CustomerFieldDefinition

CONTACT_MEMORY_OPTIONS_KEY = "contact_memory"


class ContactMemoryPolicy:
    def config_for(self, definition: CustomerFieldDefinition) -> ContactMemoryPolicyConfig:
        options = definition.field_options or {}
        raw = options.get(CONTACT_MEMORY_OPTIONS_KEY)
        if not isinstance(raw, dict):
            raw = {}
        return ContactMemoryPolicyConfig(**raw)

    def decide(
        self,
        *,
        definition: CustomerFieldDefinition | None,
        request: ContactMemoryWriteRequest,
        old_value: str | None,
    ) -> tuple[FieldUpdateStatus, str, bool]:
        if definition is None:
            return "rejected", "field definition not found for tenant", False

        config = self.config_for(definition)
        if not config.extractable_by_ai and request.source in {"ai_inference", "knowledge"}:
            return "rejected", "field is not extractable by AI", False
        if config.evidence_required and not _has_evidence(request):
            return "rejected", "field update requires evidence", False
        if config.write_policy == "human_only":
            return "rejected", "field write policy is human_only", False
        if config.write_policy == "ai_suggest":
            return "suggested", "field write policy requires human review", False
        if request.confidence < config.confidence_threshold:
            return (
                "needs_review",
                "confidence below field threshold",
                False,
            )
        if _has_confirmed_value(old_value) and request.confidence < config.confidence_threshold:
            return (
                "needs_review",
                "existing value requires higher confidence to overwrite",
                False,
            )
        return "auto_applied", "field update passed Contact Memory policy", True


def policy_options_from_flat_fields(values: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "extractable_by_ai",
        "write_policy",
        "confidence_threshold",
        "evidence_required",
        "prompt_visible",
        "lifecycle_relevant",
        "pii",
        "sensitive",
    }
    policy_values: dict[str, Any] = {}
    for key in list(values):
        if key not in keys:
            continue
        value = values.pop(key)
        if value is not None:
            policy_values[key] = value
    return policy_values


def merge_policy_options(field_options: dict | None, policy_values: dict[str, Any]) -> dict | None:
    if not policy_values:
        return field_options
    options = dict(field_options or {})
    current = dict(options.get(CONTACT_MEMORY_OPTIONS_KEY) or {})
    current.update(policy_values)
    config = ContactMemoryPolicyConfig(**current)
    options[CONTACT_MEMORY_OPTIONS_KEY] = config.model_dump()
    return options


def policy_config_dict(definition: CustomerFieldDefinition) -> dict[str, Any]:
    return ContactMemoryPolicy().config_for(definition).model_dump()


def _has_evidence(request: ContactMemoryWriteRequest) -> bool:
    return bool(
        request.reason
        or request.evidence
        or request.evidence_message_id
        or request.evidence_attachment_id
    )


def _has_confirmed_value(value: str | None) -> bool:
    return value not in (None, "")

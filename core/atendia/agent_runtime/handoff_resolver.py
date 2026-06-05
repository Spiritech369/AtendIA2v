from __future__ import annotations

import unicodedata
from typing import Any

from atendia.agent_runtime.agent_config import action_registry_for_agent
from atendia.agent_runtime.schemas import ActionRequest, TurnContext, TurnOutput


def resolve_handoff(context: TurnContext, output: TurnOutput) -> TurnOutput:
    if not (_customer_requested_human(context) or _risk_requires_handoff(context)):
        return output

    risk_flags = list(dict.fromkeys([*output.risk_flags, "human_requested"]))
    actions = list(output.actions)
    trace_metadata = dict(output.trace_metadata)
    trace_metadata["handoff_requested"] = True

    registry = action_registry_for_agent(context.active_agent)
    if registry.has_action("assign_conversation") and not any(
        action.name == "assign_conversation" for action in actions
    ):
        actions.append(
            ActionRequest(
                name="assign_conversation",
                payload={"agent_id": "human_queue"},
                reason="Customer or policy requires human review.",
                evidence=[context.inbound_text],
                metadata={"reconciler": True, "preview_only": True},
            )
        )
        trace_metadata["handoff_action_preview"] = True
    else:
        trace_metadata["handoff_action_preview"] = False

    lifecycle = output.lifecycle_update
    if (
        lifecycle is not None
        and lifecycle.target_stage
        and _looks_like_handoff(lifecycle.target_stage)
    ):
        lifecycle = None
        trace_metadata["handoff_stage_to_needs_human"] = True

    return output.model_copy(
        update={
            "needs_human": True,
            "risk_flags": risk_flags,
            "actions": actions,
            "lifecycle_update": lifecycle,
            "trace_metadata": trace_metadata,
        }
    )


def _customer_requested_human(context: TurnContext) -> bool:
    text = _fold(context.inbound_text)
    terms = _handoff_terms(context)
    return any(term in text for term in terms)


def _risk_requires_handoff(context: TurnContext) -> bool:
    config = _config(context)
    text = _fold(context.inbound_text)
    for rule in list(config.get("handoff_rules") or []):
        if not isinstance(rule, dict):
            continue
        terms = [_fold(str(term)) for term in list(rule.get("any_terms") or [])]
        if terms and any(term in text for term in terms):
            return True
    return False


def _handoff_terms(context: TurnContext) -> list[str]:
    config = _config(context)
    configured = list(config.get("handoff_terms") or [])
    defaults = ["asesor", "persona", "alguien real", "humano", "humana", "hablar con alguien"]
    return [_fold(str(term)) for term in [*configured, *defaults]]


def _config(context: TurnContext) -> dict[str, Any]:
    raw = context.metadata.get("structured_reliability") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _looks_like_handoff(value: str) -> bool:
    return _fold(value) in {"handoff", "human", "humano", "asesor", "human_handoff"}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")

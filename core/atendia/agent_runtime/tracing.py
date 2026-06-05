from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from atendia.agent_runtime.schemas import TurnContext, TurnOutput


def build_trace_metadata(
    *,
    context: TurnContext | None = None,
    provider: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "runtime": "agent_runtime_v2",
        "created_at": datetime.now(UTC).isoformat(),
    }
    if provider:
        metadata["provider"] = provider
    if context is not None:
        metadata["tenant_id"] = context.tenant_id
        metadata["conversation_id"] = context.conversation_id
    if extra:
        metadata.update(extra)
    return metadata


def summarize_turn_output(output: TurnOutput) -> dict[str, Any]:
    return {
        "has_final_message": bool(output.final_message.strip()),
        "action_count": len(output.actions),
        "field_update_count": len(output.field_updates),
        "has_lifecycle_update": output.lifecycle_update is not None,
        "confidence": output.confidence,
        "needs_human": output.needs_human,
        "risk_flags": list(output.risk_flags),
    }

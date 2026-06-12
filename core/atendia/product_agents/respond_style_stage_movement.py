"""Flag-gated pipeline stage movement for the Respond-Style direct route.

The tenant pipeline definition (config) owns the transition rules
(``auto_enter_rules``); this module only feeds the existing evaluator the
validated shadow field values of the current conversation. With the
deployment metadata flag off (the default) it is a pure no-op, so every
other tenant/deployment keeps today's behavior bit-for-bit.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

STAGE_MOVEMENT_FLAG = "respond_style_stage_movement_enabled"


async def maybe_move_stage(
    session: Any,
    *,
    deployment: Any,
    tenant_id: str,
    conversation_id: str,
    field_values: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Evaluate the tenant pipeline's auto_enter_rules over the validated
    shadow field state and apply the transition if one matches.

    Returns ``None`` when the deployment did not opt in (default), or an
    auditable dict (enabled/moved/reason/from/to) for the turn trace.
    """
    metadata = dict(getattr(deployment, "metadata_json", None) or {})
    if metadata.get(STAGE_MOVEMENT_FLAG) is not True:
        return None

    from atendia.state_machine.pipeline_evaluator import evaluate_pipeline_rules
    from atendia.state_machine.pipeline_loader import (
        PipelineNotFoundError,
        load_active_pipeline,
    )

    try:
        pipeline = await load_active_pipeline(session, UUID(str(tenant_id)))
    except PipelineNotFoundError:
        return {"enabled": True, "moved": False, "reason": "no_active_pipeline"}

    result = await evaluate_pipeline_rules(
        session,
        UUID(str(conversation_id)),
        pipeline,
        extra_fields=dict(field_values or {}),
    )
    info: dict[str, Any] = {
        "enabled": True,
        "moved": result.moved,
        "reason": result.reason,
        "from_stage": result.from_stage,
        "to_stage": result.to_stage,
        "matched_stage_ids": list(result.matched_stage_ids or []),
    }
    if result.moved:
        logger.info(
            "respond_style_stage_movement moved tenant=%s conversation=%s %s -> %s",
            tenant_id,
            conversation_id,
            result.from_stage,
            result.to_stage,
        )
    return info

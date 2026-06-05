from __future__ import annotations

from typing import Any

from atendia.contracts.turn_resolution import Evidence, ResolverAttempt, TurnResolverInput
from atendia.tools.base import ToolNoDataResult
from atendia.tools.deterministic import resolve_credit_plan


class CreditPlanResolver:
    """Resolve configured credit-plan aliases through the deterministic facade."""

    name = "credit_plan_resolver"

    async def resolve(self, input: TurnResolverInput) -> ResolverAttempt | None:
        selector_field = getattr(input.pipeline, "document_requirements_field", None)
        if not selector_field:
            return None
        if _has_value(input.extracted_data.get(str(selector_field))):
            return None

        result = resolve_credit_plan(
            input_text=input.inbound_text,
            pipeline=input.pipeline,
            context={"extracted_data": input.extracted_data},
        )
        if isinstance(result, ToolNoDataResult):
            return None

        payload = result.model_dump(mode="json")
        return ResolverAttempt(
            resolver=self.name,
            input=input.inbound_text,
            understood_as=result.selection_key,
            evidence=[
                Evidence(
                    type="tool_result",
                    source="resolveCreditPlan",
                    value=result.selection_key,
                    confidence=result.confidence,
                    metadata=payload,
                )
            ],
            confidence=result.confidence,
            can_write_state=True,
            requires_confirmation=False,
            field_updates=dict(result.field_updates),
            next_action="continue_flow",
        )


def _has_value(raw: Any) -> bool:
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")
    return raw not in (None, "", [], {})

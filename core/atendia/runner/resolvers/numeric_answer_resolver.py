from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.turn_resolution import Evidence, ResolverAttempt, TurnResolverInput
from atendia.db.models.customer_fields import CustomerFieldDefinition

_NUMBER_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*%?\s*$")


class NumericAnswerResolver:
    """Resolve bare numbers only when tenant config explicitly allows it."""

    name = "numeric_answer_resolver"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, input: TurnResolverInput) -> ResolverAttempt | None:
        match = _NUMBER_RE.match(input.inbound_text or "")
        if match is None:
            return None

        raw_number = match.group(1).replace(",", ".")
        numeric_value = float(raw_number)
        display_value = (
            f"{int(numeric_value)}%" if numeric_value.is_integer() else f"{raw_number}%"
        )
        fields = await self._eligible_numeric_fields(input, display_value)
        if len(fields) != 1:
            return ResolverAttempt(
                resolver=self.name,
                input=input.inbound_text,
                understood_as=display_value,
                confidence=0.0,
                can_write_state=False,
                blocked_reason=(
                    "no_compatible_pending_field"
                    if not fields
                    else "multiple_compatible_pending_fields"
                ),
            )

        field = fields[0]
        return ResolverAttempt(
            resolver=self.name,
            input=input.inbound_text,
            understood_as=display_value,
            evidence=[
                Evidence(
                    type="tenant_config",
                    source="customer_field_options.turn_resolver.numeric_answer",
                    value=field.key,
                    confidence=0.95,
                )
            ],
            confidence=0.95,
            can_write_state=True,
            requires_confirmation=False,
            field_updates={field.key: display_value},
            next_action="continue_flow",
        )

    async def _eligible_numeric_fields(
        self,
        input: TurnResolverInput,
        display_value: str,
    ) -> list[CustomerFieldDefinition]:
        rows = (
            (
                await self._session.execute(
                    select(CustomerFieldDefinition)
                    .where(CustomerFieldDefinition.tenant_id == input.tenant_id)
                    .order_by(
                        CustomerFieldDefinition.ordering.asc(),
                        CustomerFieldDefinition.created_at.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        flat_values = {
            key: value.get("value") if isinstance(value, dict) else value
            for key, value in input.extracted_data.items()
        }
        eligible: list[CustomerFieldDefinition] = []
        for row in rows:
            if flat_values.get(row.key) not in (None, "", [], {}):
                continue
            options = row.field_options if isinstance(row.field_options, dict) else {}
            resolver_config = options.get("turn_resolver")
            if not isinstance(resolver_config, dict):
                continue
            numeric_config: Any = resolver_config.get("numeric_answer")
            if not isinstance(numeric_config, dict) or numeric_config.get("enabled") is not True:
                continue
            allowed_values = numeric_config.get("allowed_values")
            if isinstance(allowed_values, list) and display_value not in {
                str(value) for value in allowed_values
            }:
                continue
            eligible.append(row)
        return eligible

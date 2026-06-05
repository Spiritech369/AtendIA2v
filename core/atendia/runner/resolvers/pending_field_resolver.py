from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.turn_resolution import Evidence, ResolverAttempt, TurnResolverInput
from atendia.db.models.customer_fields import CustomerFieldDefinition


def normalize_answer(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _field_options(row: CustomerFieldDefinition) -> dict[str, Any]:
    return row.field_options if isinstance(row.field_options, dict) else {}


def _configured_aliases(options: dict[str, Any]) -> dict[str, Any]:
    aliases: dict[str, Any] = {}
    for key in ("aliases", "option_aliases", "map"):
        raw = options.get(key)
        if isinstance(raw, dict):
            aliases.update(raw)
    resolver_config = options.get("turn_resolver")
    if isinstance(resolver_config, dict):
        pending_config = resolver_config.get("pending_field")
        if isinstance(pending_config, dict):
            raw = pending_config.get("aliases")
            if isinstance(raw, dict):
                aliases.update(raw)
    return aliases


def _configured_choices(options: dict[str, Any]) -> list[str]:
    raw = options.get("choices") or options.get("options")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if str(value).strip()]


def _resolver_pending_config(options: dict[str, Any]) -> dict[str, Any]:
    resolver_config = options.get("turn_resolver")
    if not isinstance(resolver_config, dict):
        return {}
    pending_config = resolver_config.get("pending_field")
    return pending_config if isinstance(pending_config, dict) else {}


def _side_effects_for_value(
    *,
    options: dict[str, Any],
    value: str,
    extracted_data: dict[str, Any],
) -> dict[str, Any]:
    pending_config = _resolver_pending_config(options)
    raw = pending_config.get("side_effects") or pending_config.get("set_fields")
    if not isinstance(raw, dict):
        return {}

    selected = raw.get(value)
    if selected is None:
        selected = raw.get(normalize_answer(value))
    if not isinstance(selected, dict):
        return {}

    updates: dict[str, Any] = {}
    for key, side_value in selected.items():
        if not isinstance(key, str) or not key.strip() or side_value in (None, ""):
            continue
        current = extracted_data.get(key)
        if isinstance(current, dict):
            current = current.get("value")
        if current in (None, "", [], {}):
            updates[key.strip()] = side_value
    return updates


class PendingFieldResolver:
    """Resolve missing tenant fields from explicit choices/aliases only."""

    name = "pending_field_resolver"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, input: TurnResolverInput) -> ResolverAttempt | None:
        inbound = normalize_answer(input.inbound_text)
        if not inbound:
            return None

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

        matches: list[tuple[CustomerFieldDefinition, str, str, dict[str, Any]]] = []
        for row in rows:
            current = input.extracted_data.get(row.key)
            if isinstance(current, dict):
                current = current.get("value")
            if current not in (None, "", [], {}):
                continue

            options = _field_options(row)
            pending_config = _resolver_pending_config(options)
            enabled = pending_config.get("enabled")
            aliases = _configured_aliases(options)
            choices = _configured_choices(options)
            if enabled is False:
                continue
            if not aliases and not choices:
                continue

            for alias, value in aliases.items():
                if normalize_answer(alias) == inbound and value not in (None, ""):
                    matches.append((row, str(value), "alias", options))
                    break
            else:
                for choice in choices:
                    if normalize_answer(choice) == inbound:
                        matches.append((row, choice, "choice", options))
                        break

        if not matches:
            return None
        if len(matches) > 1:
            return ResolverAttempt(
                resolver=self.name,
                input=input.inbound_text,
                understood_as="multiple_pending_field_matches",
                confidence=0.55,
                can_write_state=False,
                requires_confirmation=True,
                blocked_reason="multiple_pending_field_matches",
                suggested_clarification="Te sigo, pero necesito confirmar a que dato te refieres.",
            )

        field, value, match_kind, options = matches[0]
        field_updates = {field.key: value}
        field_updates.update(
            _side_effects_for_value(
                options=options,
                value=value,
                extracted_data=input.extracted_data,
            )
        )
        return ResolverAttempt(
            resolver=self.name,
            input=input.inbound_text,
            understood_as=value,
            evidence=[
                Evidence(
                    type="tenant_config",
                    source=f"customer_field_options.{match_kind}",
                    value=field.key,
                    confidence=0.95,
                )
            ],
            confidence=0.95,
            can_write_state=True,
            requires_confirmation=False,
            field_updates=field_updates,
            next_action="continue_flow",
        )

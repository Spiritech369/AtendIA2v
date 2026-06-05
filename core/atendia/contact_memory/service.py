from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.schemas import FieldUpdate, TurnContext, TurnOutput
from atendia.contact_memory.policy import ContactMemoryPolicy
from atendia.contact_memory.schemas import ContactMemoryDecision, ContactMemoryWriteRequest
from atendia.db.models.customer import Customer
from atendia.db.models.customer_fields import (
    CustomerFieldDefinition,
    CustomerFieldUpdateEvidence,
    CustomerFieldValue,
)
from atendia.db.models.field_suggestion import FieldSuggestion


class ContactMemoryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: ContactMemoryPolicy | None = None,
    ) -> None:
        self._session = session
        self._policy = policy or ContactMemoryPolicy()

    async def apply_turn_output(
        self,
        output: TurnOutput,
        *,
        context: TurnContext,
    ) -> list[ContactMemoryDecision]:
        if not output.field_updates:
            return []
        customer_id = _context_customer_id(context)
        if customer_id is None:
            return [
                ContactMemoryDecision(
                    field_key=update.field_key,
                    new_value=_stringify(update.value),
                    status="rejected",
                    reason="customer id missing from TurnContext",
                    confidence=_confidence(update, output.confidence),
                )
                for update in output.field_updates
            ]
        tenant_id = UUID(str(context.tenant_id))
        decisions: list[ContactMemoryDecision] = []
        for update in output.field_updates:
            decisions.append(
                await self.apply_update(
                    ContactMemoryWriteRequest(
                        tenant_id=tenant_id,
                        customer_id=customer_id,
                        field_key=update.field_key,
                        new_value=update.value,
                        source=update.source,
                        reason=update.reason,
                        evidence=list(update.evidence),
                        evidence_message_id=_maybe_uuid(update.evidence_message_id),
                        evidence_attachment_id=_maybe_uuid(update.evidence_attachment_id),
                        confidence=_confidence(update, output.confidence),
                        trace_id=update.trace_id
                        or str(output.trace_metadata.get("trace_id") or ""),
                        created_by=str(update.metadata.get("created_by") or "agent_runtime_v2"),
                        metadata={
                            **update.metadata,
                            "turn_conversation_id": context.conversation_id,
                        },
                    )
                )
            )
        return decisions

    async def apply_update(
        self,
        request: ContactMemoryWriteRequest,
    ) -> ContactMemoryDecision:
        customer = (
            await self._session.execute(
                select(Customer).where(
                    Customer.id == request.customer_id,
                    Customer.tenant_id == request.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if customer is None:
            return ContactMemoryDecision(
                field_key=request.field_key,
                new_value=_stringify(request.new_value),
                status="rejected",
                reason="customer not found for tenant",
                confidence=request.confidence,
            )

        definition = (
            await self._session.execute(
                select(CustomerFieldDefinition).where(
                    CustomerFieldDefinition.tenant_id == request.tenant_id,
                    CustomerFieldDefinition.key == request.field_key,
                )
            )
        ).scalar_one_or_none()
        existing = None
        if definition is not None:
            existing = (
                await self._session.execute(
                    select(CustomerFieldValue).where(
                        CustomerFieldValue.customer_id == request.customer_id,
                        CustomerFieldValue.field_definition_id == definition.id,
                    )
                )
            ).scalar_one_or_none()

        old_value = existing.value if existing is not None else None
        status, reason, should_apply = self._policy.decide(
            definition=definition,
            request=request,
            old_value=old_value,
        )
        new_value = _stringify(request.new_value)
        suggestion = None
        if should_apply and definition is not None:
            if existing is not None:
                existing.value = new_value
                self._session.add(existing)
            else:
                existing = CustomerFieldValue(
                    customer_id=request.customer_id,
                    field_definition_id=definition.id,
                    value=new_value,
                )
                self._session.add(existing)
        elif status in {"suggested", "needs_review"}:
            suggestion = FieldSuggestion(
                tenant_id=request.tenant_id,
                customer_id=request.customer_id,
                conversation_id=None,
                turn_number=None,
                key=request.field_key,
                suggested_value=new_value or "",
                confidence=request.confidence,
                evidence_text=_evidence_text(request),
                status="pending",
            )
            self._session.add(suggestion)

        evidence = CustomerFieldUpdateEvidence(
            tenant_id=request.tenant_id,
            customer_id=request.customer_id,
            field_definition_id=definition.id if definition is not None else None,
            field_key=request.field_key,
            old_value=old_value,
            new_value=new_value,
            source=request.source,
            evidence_message_id=request.evidence_message_id,
            evidence_attachment_id=request.evidence_attachment_id,
            reason=request.reason or reason,
            confidence=request.confidence,
            status=status,
            trace_id=request.trace_id,
            created_by=request.created_by,
            metadata_json={
                **request.metadata,
                "evidence": list(request.evidence),
                "policy_reason": reason,
            },
        )
        self._session.add(evidence)
        await self._session.flush()
        return ContactMemoryDecision(
            field_key=request.field_key,
            old_value=old_value,
            new_value=new_value,
            status=status,
            reason=reason,
            confidence=request.confidence,
            evidence_id=evidence.id,
            suggestion_id=suggestion.id if suggestion is not None else None,
            applied=should_apply,
            metadata={"field_definition_id": str(definition.id)} if definition else {},
        )


def _context_customer_id(context: TurnContext) -> UUID | None:
    if context.customer.id:
        return _maybe_uuid(context.customer.id)
    raw = context.metadata.get("customer_id")
    return _maybe_uuid(raw) if raw else None


def _confidence(update: FieldUpdate, fallback: float) -> float:
    if update.confidence is not None:
        return float(update.confidence)
    raw = update.metadata.get("confidence")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return float(fallback or 0.0)


def _maybe_uuid(value: Any) -> UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _evidence_text(request: ContactMemoryWriteRequest) -> str | None:
    if request.evidence:
        return "\n".join(request.evidence)
    return request.reason

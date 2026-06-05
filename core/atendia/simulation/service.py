from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.message import MessageRow
from atendia.db.models.turn_trace import TurnTrace

SIMULATION_CHANNEL = "simulation"
SIMULATION_TRACE_TRIGGER = "agent_runtime_v2_simulation"


class SimulationPersistenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_customer(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        case_id: str,
        initial_fields: dict[str, Any],
    ) -> Customer:
        customer = Customer(
            tenant_id=tenant_id,
            phone_e164=f"+52999{uuid4().hex[:10]}",
            name=f"Simulation {case_id}",
            source="agent_runtime_v2_simulation",
            attrs={
                "is_simulation": True,
                "simulation_run_id": str(run_id),
                "simulation_case_id": case_id,
                "initial_fields": dict(initial_fields),
            },
            tags=["simulation", f"simulation_run:{run_id}", f"simulation_case:{case_id}"],
        )
        self._session.add(customer)
        await self._session.flush()
        return customer

    async def create_conversation(
        self,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        customer_id: UUID,
        run_id: UUID,
        case_id: str,
        initial_stage: str,
    ) -> Conversation:
        conversation = Conversation(
            tenant_id=tenant_id,
            customer_id=customer_id,
            assigned_agent_id=agent_id,
            channel=SIMULATION_CHANNEL,
            status="active",
            current_stage=initial_stage,
            tags=["simulation", f"simulation_run:{run_id}", f"simulation_case:{case_id}"],
            unread_count=0,
        )
        self._session.add(conversation)
        await self._session.flush()
        self._session.add(
            ConversationStateRow(
                conversation_id=conversation.id,
                extracted_data={
                    "is_simulation": True,
                    "simulation_run_id": str(run_id),
                    "simulation_case_id": case_id,
                },
            )
        )
        await self._session.flush()
        return conversation

    async def insert_message(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        direction: str,
        text_value: str,
        run_id: UUID,
        case_id: str,
        turn_index: int,
        trace_id: UUID | None = None,
    ) -> MessageRow:
        row = MessageRow(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction=direction,
            text=text_value,
            channel_message_id=f"simulation:{run_id}:{case_id}:{turn_index}:{direction}",
            delivery_status="simulated",
            metadata_json={
                "is_simulation": True,
                "simulation_run_id": str(run_id),
                "simulation_case_id": case_id,
                "simulation_turn_index": turn_index,
                "trace_id": str(trace_id) if trace_id else None,
                "no_whatsapp": True,
                "no_outbox": True,
            },
            sent_at=datetime.now(UTC),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def record_trace(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        agent_id: UUID,
        inbound_message_id: UUID,
        inbound_text: str,
        turn_number: int,
        output: Any,
        context_metadata: dict[str, Any],
        policy_issues: list[dict[str, Any]],
        action_results: list[dict[str, Any]],
        run_id: UUID,
        case_id: str,
        provider_name: str,
    ) -> TurnTrace:
        trace = TurnTrace(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            turn_number=turn_number,
            inbound_message_id=inbound_message_id,
            inbound_text=inbound_text,
            state_before={
                "simulation_run_id": str(run_id),
                "simulation_case_id": case_id,
            },
            state_after={
                "agent_runtime_v2": True,
                "mode": "simulation_apply",
                "side_effects": {
                    "sent_message": False,
                    "outbox": False,
                    "real_customer_write": False,
                    "workflow_events_real": False,
                },
                "policy_valid": not policy_issues,
                "policy_issues": policy_issues,
                "action_results": action_results,
            },
            composer_input={
                "runtime": "agent_runtime_v2",
                "mode": "simulation_apply",
                "simulation_run_id": str(run_id),
                "simulation_case_id": case_id,
                "simulation_provider": provider_name,
            },
            composer_output=output.model_dump(mode="json"),
            composer_provider="openai" if provider_name == "openai" else "fallback",
            outbound_messages=None,
            errors=policy_issues or None,
            bot_paused=False,
            router_trigger=SIMULATION_TRACE_TRIGGER,
            raw_llm_response=output.model_dump_json(),
            agent_id=agent_id,
            kb_evidence={
                "citations": [
                    citation.model_dump(mode="json")
                    for citation in output.knowledge_citations
                ],
                "retrieval": context_metadata.get("knowledge", {}),
            },
            rules_evaluated=[
                {"rule": "simulation_no_whatsapp", "passed": True},
                {"rule": "simulation_no_outbox", "passed": True},
                {"rule": "policy_valid", "passed": not policy_issues},
                {"rule": "final_message_single_authority", "passed": True},
            ],
        )
        self._session.add(trace)
        await self._session.flush()
        return trace

    async def field_values_for_customer(
        self,
        *,
        customer_id: UUID,
    ) -> dict[str, str | None]:
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT cfd.key, cfv.value
                    FROM customer_field_values cfv
                    JOIN customer_field_definitions cfd
                      ON cfd.id = cfv.field_definition_id
                    WHERE cfv.customer_id = :customer_id
                    """
                ),
                {"customer_id": customer_id},
            )
        ).mappings().all()
        return {str(row["key"]): _deserialize_field_value(row["value"]) for row in rows}

    async def apply_simulation_field_updates(
        self,
        *,
        tenant_id: UUID,
        customer_id: UUID,
        field_updates: list[Any],
    ) -> int:
        is_simulation = (
            await self._session.execute(
                text(
                    """
                    SELECT COALESCE(attrs->>'is_simulation', 'false') = 'true'
                    FROM customers
                    WHERE id = :customer_id AND tenant_id = :tenant_id
                    """
                ),
                {"customer_id": customer_id, "tenant_id": tenant_id},
            )
        ).scalar_one_or_none()
        if is_simulation is not True:
            raise ValueError("simulation field updates require a simulated customer")
        applied = 0
        for update in field_updates:
            field_id = (
                await self._session.execute(
                    text(
                        """
                        SELECT id FROM customer_field_definitions
                        WHERE tenant_id = :tenant_id AND key = :field_key
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"tenant_id": tenant_id, "field_key": update.field_key},
                )
            ).scalar_one_or_none()
            if field_id is None:
                continue
            await self._session.execute(
                text(
                    """
                    INSERT INTO customer_field_values
                      (customer_id, field_definition_id, value)
                    VALUES (:customer_id, :field_id, :value)
                    ON CONFLICT (customer_id, field_definition_id)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                    """
                ),
                {
                    "customer_id": customer_id,
                    "field_id": field_id,
                    "value": _serialize_field_value(update.value),
                },
            )
            applied += 1
        await self._session.flush()
        return applied

    async def current_stage(self, *, conversation_id: UUID) -> str | None:
        return (
            await self._session.execute(
                select(Conversation.current_stage).where(Conversation.id == conversation_id)
            )
        ).scalar_one_or_none()


def _serialize_field_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _deserialize_field_value(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith(("{", "[")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return value
    return value

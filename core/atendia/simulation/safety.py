from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def safety_counters(session: AsyncSession, *, tenant_id: UUID) -> dict[str, int]:
    return {
        "whatsapp_sends": 0,
        "outbound_outbox": await _count(
            session,
            "SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :tenant_id",
            {"tenant_id": tenant_id},
        ),
        "messages": await _count(
            session,
            "SELECT COUNT(*) FROM messages WHERE tenant_id = :tenant_id",
            {"tenant_id": tenant_id},
        ),
        "real_customers": await _count(
            session,
            """
            SELECT COUNT(*) FROM customers
            WHERE tenant_id = :tenant_id
              AND COALESCE(attrs->>'is_simulation', 'false') != 'true'
            """,
            {"tenant_id": tenant_id},
        ),
        "simulated_customers": await _count(
            session,
            """
            SELECT COUNT(*) FROM customers
            WHERE tenant_id = :tenant_id
              AND attrs->>'is_simulation' = 'true'
            """,
            {"tenant_id": tenant_id},
        ),
        "customer_field_values": await _count(
            session,
            """
            SELECT COUNT(*)
            FROM customer_field_values cfv
            JOIN customer_field_definitions cfd
              ON cfd.id = cfv.field_definition_id
            WHERE cfd.tenant_id = :tenant_id
            """,
            {"tenant_id": tenant_id},
        ),
        "customer_field_update_evidence": await _count(
            session,
            """
            SELECT COUNT(*) FROM customer_field_update_evidence
            WHERE tenant_id = :tenant_id
            """,
            {"tenant_id": tenant_id},
        ),
        "lifecycle_stage_history": await _count(
            session,
            "SELECT COUNT(*) FROM lifecycle_stage_history WHERE tenant_id = :tenant_id",
            {"tenant_id": tenant_id},
        ),
        "action_execution_logs": await _count(
            session,
            "SELECT COUNT(*) FROM action_execution_logs WHERE tenant_id = :tenant_id",
            {"tenant_id": tenant_id},
        ),
        "workflow_executions": await _count(
            session,
            """
            SELECT COUNT(*)
            FROM workflow_executions we
            JOIN workflows w ON w.id = we.workflow_id
            WHERE w.tenant_id = :tenant_id
            """,
            {"tenant_id": tenant_id},
        ),
    }


def safety_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {key: after.get(key, 0) - before.get(key, 0) for key in sorted(before)}


def side_effect_failures(delta: dict[str, int]) -> list[str]:
    failures: list[str] = []
    blocked_keys = {
        "outbound_outbox",
        "real_customers",
        "workflow_executions",
        "whatsapp_sends",
    }
    for key in blocked_keys:
        if delta.get(key, 0) != 0:
            failures.append(f"{key} changed by {delta[key]}")
    return failures


async def assert_simulation_conversation(
    session: AsyncSession,
    *,
    conversation_id: UUID,
) -> None:
    tags = (
        await session.execute(
            text("SELECT tags FROM conversations WHERE id = :conversation_id"),
            {"conversation_id": conversation_id},
        )
    ).scalar_one_or_none()
    if "simulation" not in [str(item) for item in (tags or [])]:
        raise ValueError("simulation runner refused to mutate a non-simulation conversation")


async def _count(session: AsyncSession, sql: str, params: dict[str, Any]) -> int:
    return int((await session.execute(text(sql), params)).scalar() or 0)

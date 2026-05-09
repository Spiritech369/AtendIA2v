"""Tenant-scoped audit-event emit helper.

Admin actions (workflow CRUD/toggle/retry, KB document upload/delete/retry/
download) write to the same ``events`` table the runtime uses; the audit-log
read route surfaces them. Migration 028 made ``events.conversation_id``
nullable and added ``events.actor_user_id`` so admin events fit the schema
without a parallel table.

This helper is intentionally minimal — it doesn't go through ``EventEmitter``
because that path always sets a conversation_id. Admin events do not.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Reserved type prefix for admin actions. Keeping a prefix lets the audit-log
# UI filter by action class without needing a new column.
ADMIN_TYPE_PREFIX = "admin."


async def emit_admin_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    payload: dict[str, Any],
    conversation_id: UUID | None = None,
) -> None:
    """Insert an audit event. Caller commits.

    ``action`` is a short string like ``workflow.created`` or ``kb.document.deleted``;
    we prepend the ``admin.`` prefix.
    """
    # asyncpg doesn't auto-serialise dict -> jsonb when bound via text() — pass
    # JSON text and let postgres coerce on the column type.
    await session.execute(
        text(
            "INSERT INTO events "
            "(id, conversation_id, tenant_id, type, payload, occurred_at, actor_user_id) "
            "VALUES (:id, :c, :t, :ty, :p, :o, :u)"
        ),
        {
            "id": uuid4(),
            "c": conversation_id,
            "t": tenant_id,
            "ty": ADMIN_TYPE_PREFIX + action,
            "p": json.dumps(payload, default=str),
            "o": datetime.now(UTC),
            "u": actor_user_id,
        },
    )

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class OwnershipSnapshot:
    assigned_user_id: str | None
    active_handoff_id: str | None
    active_handoff_reason: str | None
    conversation_status: str | None

    @property
    def has_human_owner(self) -> bool:
        return self.assigned_user_id is not None

    @property
    def has_team_owner(self) -> bool:
        return self.active_handoff_id is not None


async def load_ownership_snapshot(
    session: AsyncSession,
    *,
    conversation_id: UUID,
) -> OwnershipSnapshot:
    row = (
        await session.execute(
            text(
                """
                SELECT c.assigned_user_id, c.status,
                       h.id AS handoff_id, h.reason AS handoff_reason
                FROM conversations c
                LEFT JOIN LATERAL (
                    SELECT id, reason
                    FROM human_handoffs
                    WHERE conversation_id = c.id
                      AND status IN ('pending', 'open')
                    ORDER BY requested_at DESC
                    LIMIT 1
                ) h ON true
                WHERE c.id = :cid
                """
            ),
            {"cid": conversation_id},
        )
    ).fetchone()
    if row is None:
        return OwnershipSnapshot(None, None, None, None)
    return OwnershipSnapshot(
        assigned_user_id=str(row.assigned_user_id) if row.assigned_user_id else None,
        active_handoff_id=str(row.handoff_id) if row.handoff_id else None,
        active_handoff_reason=str(row.handoff_reason) if row.handoff_reason else None,
        conversation_status=str(row.status) if row.status else None,
    )


__all__ = ["OwnershipSnapshot", "load_ownership_snapshot"]

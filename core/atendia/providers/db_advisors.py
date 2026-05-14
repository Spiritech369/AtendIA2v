"""DB-backed AdvisorProvider — replaces EmptyAdvisorProvider for non-demo tenants.

Reads from the `advisors` table (migration 047). Wire shape matches
DemoAdvisorProvider so existing /api/v1/appointments/advisors handlers
need no rewrite.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.advisor import Advisor


class DBAdvisorProvider:
    def __init__(self, *, session: AsyncSession, tenant_id: UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def list_advisors(self) -> list[dict]:
        stmt = (
            select(Advisor)
            .where(Advisor.tenant_id == self._tenant_id, Advisor.active.is_(True))
            .order_by(Advisor.name)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_advisor_to_dict(a) for a in rows]

    async def get_advisor(self, advisor_id: str) -> dict | None:
        stmt = select(Advisor).where(Advisor.tenant_id == self._tenant_id, Advisor.id == advisor_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _advisor_to_dict(row) if row is not None else None


def _advisor_to_dict(a: Advisor) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "phone": a.phone,
        "max_per_day": a.max_per_day,
        "close_rate": a.close_rate,
    }

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import TenantFAQ
from atendia.tools.base import Tool


class LookupFAQInput(BaseModel):
    tenant_id: UUID
    question: str
    top_k: int = 3


class FAQMatch(BaseModel):
    question: str
    answer: str


class LookupFAQTool(Tool):
    name = "lookup_faq"

    async def run(self, session: AsyncSession, **kwargs: Any) -> dict:
        params = LookupFAQInput.model_validate(kwargs)
        query_pattern = f"%{params.question}%"
        stmt = (
            select(TenantFAQ)
            .where(TenantFAQ.tenant_id == params.tenant_id)
            .where(or_(
                TenantFAQ.question.ilike(query_pattern),
                TenantFAQ.answer.ilike(query_pattern),
            ))
            .limit(params.top_k)
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {
            "matches": [
                FAQMatch(question=r.question, answer=r.answer).model_dump()
                for r in rows
            ]
        }

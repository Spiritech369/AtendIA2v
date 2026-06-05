from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def is_duplicate_outbound(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    messages: list[str],
    lookback: int = 3,
) -> bool:
    if not messages:
        return False
    rows = (
        await session.execute(
            text(
                """
                SELECT text
                FROM messages
                WHERE conversation_id = :cid
                  AND direction = 'outbound'
                ORDER BY sent_at DESC
                LIMIT :limit
                """
            ),
            {"cid": conversation_id, "limit": lookback},
        )
    ).fetchall()
    previous = [_normalize(str(row.text or "")) for row in rows]
    for message in messages:
        normalized = _normalize(message)
        if not normalized:
            continue
        for prior in previous:
            if not prior:
                continue
            if prior == normalized:
                return True
            if SequenceMatcher(None, prior, normalized).ratio() >= 0.94:
                return True
    return False


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).strip()


__all__ = ["is_duplicate_outbound"]

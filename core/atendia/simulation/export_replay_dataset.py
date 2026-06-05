from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.db.models.conversation import Conversation
from atendia.db.models.message import MessageRow
from atendia.simulation.rc5_common import anonymize_text, write_json

QUOTE_TERMS = ("precio", "cotiza", "cotizame", "cuanto", "contado", "credito")
HANDOFF_TERMS = ("humano", "persona", "asesor", "hablar")
DOC_TERMS = ("document", "ine", "comprobante", "papel")
PRODUCT_TERMS = ("moto", "modelo", "r4", "u5", "adventure", "work")


def _fold(value: object) -> str:
    return anonymize_text(value).casefold()


def _safe_customer_turn(text: str) -> str:
    folded = _fold(text)
    has_product = any(term in folded for term in PRODUCT_TERMS)
    asks_quote = any(term in folded for term in QUOTE_TERMS)
    asks_handoff = any(term in folded for term in HANDOFF_TERMS)
    asks_docs = any(term in folded for term in DOC_TERMS)

    if asks_quote and has_product:
        return "cliente solicita cotizacion de moto modelo anonimo"
    if asks_quote:
        return "cliente solicita cotizacion"
    if asks_handoff:
        return "cliente pide hablar con asesor humano"
    if asks_docs:
        return "cliente pregunta por documentos requeridos"
    if has_product:
        return "cliente menciona interes en moto modelo anonimo"
    return "cliente comparte informacion sin datos personales"


def _expected_tags(texts: Sequence[str]) -> list[str]:
    folded = " ".join(_fold(text) for text in texts)
    tags: list[str] = []
    if any(term in folded for term in QUOTE_TERMS) and any(
        term in folded for term in PRODUCT_TERMS
    ):
        tags.append("quote")
    if any(term in folded for term in HANDOFF_TERMS):
        tags.append("handoff")
    if any(term in folded for term in DOC_TERMS):
        tags.append("documents")
    return tags


async def export_dataset(
    *,
    tenant_id: UUID,
    agent_ids: list[UUID],
    output: Path,
    limit: int,
) -> dict[str, Any]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        conversations = await _load_conversations(
            session,
            tenant_id=tenant_id,
            agent_ids=agent_ids,
            limit=limit,
        )
        cases = []
        for conversation in conversations:
            messages = await _load_inbound_messages(session, conversation.id)
            if not messages:
                continue
            raw_texts = [message.text for message in messages]
            cases.append(
                {
                    "case_id": f"real_{str(conversation.id).replace('-', '')[:12]}",
                    "source": "sampled_real_conversation",
                    "conversation_hash": str(conversation.id).replace("-", "")[:12],
                    "expected_tags": _expected_tags(raw_texts),
                    "turns": [
                        {
                            "customer": _safe_customer_turn(message.text),
                            "attachments": [],
                        }
                        for message in messages
                    ],
                }
            )
    await engine.dispose()

    payload = {
        "version": 1,
        "anonymized": True,
        "raw_text_exported": False,
        "source": "database_sampled_real_conversations",
        "generated_at": datetime.now(UTC).isoformat(),
        "tenant_id": str(tenant_id),
        "agent_ids": [str(agent_id) for agent_id in agent_ids],
        "cases": cases,
    }
    write_json(output, payload)
    return payload


async def _load_conversations(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_ids: list[UUID],
    limit: int,
) -> list[Conversation]:
    filters = [
        Conversation.tenant_id == tenant_id,
        Conversation.deleted_at.is_(None),
        Conversation.assigned_agent_id.in_(agent_ids),
    ]
    result = await session.execute(
        select(Conversation)
        .where(and_(*filters))
        .order_by(Conversation.last_activity_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def _load_inbound_messages(
    session: AsyncSession,
    conversation_id: UUID,
) -> list[MessageRow]:
    result = await session.execute(
        select(MessageRow)
        .where(
            MessageRow.conversation_id == conversation_id,
            MessageRow.direction == "inbound",
            MessageRow.deleted_at.is_(None),
        )
        .order_by(MessageRow.sent_at.asc())
    )
    return list(result.scalars())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--agent-id", action="append", dest="agent_ids", type=UUID)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", default=20, type=int)
    args = parser.parse_args()
    if not args.agent_ids:
        raise SystemExit("At least one --agent-id is required")
    payload = asyncio.run(
        export_dataset(
            tenant_id=args.tenant_id,
            agent_ids=args.agent_ids,
            output=args.output,
            limit=args.limit,
        )
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cases": len(payload["cases"]),
                "raw_text_exported": payload["raw_text_exported"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

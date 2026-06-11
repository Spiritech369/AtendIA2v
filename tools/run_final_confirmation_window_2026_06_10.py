"""Final reduced confirmation window after W6-A/W6-B (no-send).

Runs INSIDE the backend container. Creates a FRESH conversation for the
allowlisted pilot customer and drives the 15-message script through
``run_inbound_shadow`` (the Baileys step 2c hook) against the armed
deployment/version. Observation only: no send, no outbox, no workflows,
no legacy.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text

from atendia.db.models.conversation import Conversation
from atendia.db.models.message import MessageRow
from atendia.db.session import _get_factory
from atendia.product_agents.inbound_shadow import run_inbound_shadow

TENANT_ID = "6ad78236-1fc9-467a-858d-90d248d57ee5"
EXPECTED_VERSION = "0cee95e8-542f-431e-ac66-5a0f046ff0b7"
PHONE = "+5218128889241"

MESSAGES = [
    "hola quiero mas informacion del credito",
    "que motos manejan?",
    "me interesa la U2",
    "y la metro?",
    "esa cuanto queda?",
    "y si estoy en buro?",
    "no quiero mandar tantos papeles",
    "me pagan por NOMINA",
    "perdon, realmente es transferencia bancaria no nomina",
    "tengo desde noviembre trabajando",
    "perdon tengo 5 años",
    "[MEDIA:image/jpeg sin caption]",
    "que ocupo mandar?",
    "esta caro",
    "pasame con alguien",
]


async def main() -> int:
    factory = _get_factory()
    async with factory() as session:
        customer_id = (
            await session.execute(
                text(
                    "SELECT id FROM customers WHERE tenant_id=:t AND "
                    "right(regexp_replace(phone_e164,'\\D','','g'),10)="
                    "right(regexp_replace(:p,'\\D','','g'),10) LIMIT 1"
                ),
                {"t": TENANT_ID, "p": PHONE},
            )
        ).scalar()
        if customer_id is None:
            print(json.dumps({"error": "pilot customer not found"}))
            return 1
        outbox_before = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()

        conversation = Conversation(
            id=uuid4(),
            tenant_id=TENANT_ID,
            customer_id=customer_id,
            channel="whatsapp",
        )
        session.add(conversation)
        await session.flush()

        turns = []
        for inbound in MESSAGES:
            media_type = "image/jpeg" if inbound.startswith("[MEDIA:") else None
            message = MessageRow(
                id=uuid4(),
                conversation_id=conversation.id,
                tenant_id=TENANT_ID,
                direction="inbound",
                text=inbound,
                sent_at=datetime.now(UTC),
                metadata_json={"final_confirmation_window": True},
            )
            session.add(message)
            await session.flush()
            summaries = await run_inbound_shadow(
                session,
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                inbound_text=inbound,
                inbound_message_id=message.id,
                from_phone_e164=PHONE,
            )
            summary = summaries[0] if summaries else {}
            candidate = summary.get("final_message_candidate")
            if candidate:
                session.add(
                    MessageRow(
                        id=uuid4(),
                        conversation_id=conversation.id,
                        tenant_id=TENANT_ID,
                        direction="outbound",
                        text=candidate,
                        sent_at=datetime.now(UTC),
                        metadata_json={
                            "final_confirmation_window": True,
                            "simulated_no_send": True,
                        },
                    )
                )
                await session.flush()
            turns.append({"inbound": inbound, "media_type": media_type, **summary})
        await session.commit()

        outbox_after = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()
        shadow_state = (
            await session.execute(
                text(
                    "SELECT field_values::text FROM respond_style_shadow_fields "
                    "WHERE conversation_id=:c"
                ),
                {"c": str(conversation.id)},
            )
        ).scalar()

    print(
        json.dumps(
            {
                "conversation_id": str(conversation.id),
                "expected_version": EXPECTED_VERSION,
                "outbox_delta": (outbox_after or 0) - (outbox_before or 0),
                "final_shadow_state": json.loads(shadow_state) if shadow_state else {},
                "turns": turns,
            },
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

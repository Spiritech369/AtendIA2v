from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DINAMO_TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
DINAMO_AGENT_ID = UUID("c169deec-226d-55b7-bd07-270f339e75a6")

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"


def dinamo_contract() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "dinamo_motos_nl_shadow.json").read_text(encoding="utf-8")
    )


def knowledge_os_sources() -> dict[str, Any]:
    return {
        "knowledge_os": {
            "mode": "tenant_structured_sources",
            "sources": {
                "catalog": {
                    "path": "docs/tenant_sources/dinamo/CatalogoMotos2026_DINAMO.json"
                },
                "requirements": {
                    "path": "docs/tenant_sources/dinamo/Requisitos_Credito_Dinamo.json"
                },
                "faq": {"path": "docs/tenant_sources/dinamo/FAQ_DINAMO.json"},
            },
        }
    }


def runtime_config(**overrides: Any) -> dict[str, Any]:
    config = {
        "runtime_v2_enabled": True,
        "runtime_mode": "runtime_v2_db_backed_parity_no_send",
        "send_enabled": False,
        "outbox_enabled": False,
        "live_send_enabled": False,
        "actions_enabled": False,
        "workflow_side_effects_enabled": False,
        "workflow_events_enabled": False,
        "single_contact_smoke_enabled": False,
        "legacy_fallback_enabled": False,
        "provider_visible_fallback_enabled": False,
        "manual_recovery_visible_enabled": False,
        "canary_enabled": False,
        "open_production_enabled": False,
        "send_scope": "approved_contact_only",
        "allowed_contact_ids": [],
        "allowed_test_phones": ["+5215555550037"],
        "agent_id": str(DINAMO_AGENT_ID),
        "allowed_agent_ids": [str(DINAMO_AGENT_ID)],
        "tenant_domain_contract": dinamo_contract(),
        "metadata": knowledge_os_sources(),
    }
    config.update(overrides)
    return config


async def seed_runtime_conversation(
    session: AsyncSession,
    *,
    runtime_overrides: dict[str, Any] | None = None,
    phone_e164: str = "+5215555550037",
    extracted_data: dict[str, Any] | None = None,
) -> tuple[UUID, UUID]:
    await session.execute(
        text(
            """INSERT INTO tenants (id, name, config)
            VALUES (:id, :name, CAST(:config AS jsonb))"""
        ),
        {
            "id": DINAMO_TENANT_ID,
            "name": "Dinamo Runtime V2 parity test",
            "config": json.dumps(
                {"agent_runtime_v2": runtime_config(**(runtime_overrides or {}))},
                ensure_ascii=False,
            ),
        },
    )
    contact_id = (
        await session.execute(
            text(
                """INSERT INTO customers (tenant_id, phone_e164, name, attrs)
                VALUES (:tenant_id, :phone, 'Contacto paridad', '{}'::jsonb)
                RETURNING id"""
            ),
            {"tenant_id": DINAMO_TENANT_ID, "phone": phone_e164},
        )
    ).scalar_one()
    conversation_id = (
        await session.execute(
            text(
                """INSERT INTO conversations (tenant_id, customer_id, current_stage)
                VALUES (:tenant_id, :customer_id, 'qualify')
                RETURNING id"""
            ),
            {"tenant_id": DINAMO_TENANT_ID, "customer_id": contact_id},
        )
    ).scalar_one()
    await session.execute(
        text(
            """INSERT INTO conversation_state (conversation_id, extracted_data)
            VALUES (:conversation_id, CAST(:extracted_data AS jsonb))"""
        ),
        {
            "conversation_id": conversation_id,
            "extracted_data": json.dumps(extracted_data or {}, ensure_ascii=False),
        },
    )
    await session.commit()
    return contact_id, conversation_id


async def insert_history(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    count: int,
) -> None:
    base = datetime.now(UTC) - timedelta(minutes=count)
    for idx in range(count):
        direction = "inbound" if idx % 2 == 0 else "outbound"
        await session.execute(
            text(
                """INSERT INTO messages
                    (tenant_id, conversation_id, direction, text, sent_at, metadata_json)
                VALUES
                    (:tenant_id, :conversation_id, :direction, :text, :sent_at,
                     CAST(:metadata AS jsonb))"""
            ),
            {
                "tenant_id": DINAMO_TENANT_ID,
                "conversation_id": conversation_id,
                "direction": direction,
                "text": f"historial {idx}",
                "sent_at": base + timedelta(minutes=idx),
                "metadata": json.dumps({"fixture_index": idx}),
            },
        )
    await session.commit()


async def outbox_count(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                text(
                    """SELECT COUNT(*)
                    FROM outbound_outbox
                    WHERE tenant_id = :tenant_id"""
                ),
                {"tenant_id": DINAMO_TENANT_ID},
            )
        ).scalar_one()
    )

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED"] = "true"
os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED"] = "false"
os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED"] = "false"
os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED"] = "false"
os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER"] = "disabled"
sys.path.insert(0, str(Path.cwd()))

from atendia.agent_runtime.rollout_policy import RolloutPolicyService
from atendia.config import get_settings
from atendia.db.models.tenant import Tenant

TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
AGENT_ID = UUID("ef541266-376c-4f77-92bb-6087133d674e")
CHANNEL_ID = "whatsapp_meta"


def shadow_paused_config() -> dict[str, Any]:
    return {
        "runtime_v2_enabled": True,
        "shadow_mode_enabled": False,
        "preview_enabled": True,
        "send_enabled": False,
        "actions_enabled": False,
        "workflow_events_enabled": False,
        "model_provider_enabled": False,
        "allowed_agent_ids": [str(AGENT_ID)],
        "allowed_channel_ids": ["whatsapp", "whatsapp_meta"],
        "required_eval_suite_passed": False,
        "rollout_mode": "preview",
        "metadata": {
            "mode_label": "preview_only",
            "shadow_paused_at": "2026-06-01",
            "shadow_pause_reason": "shadow_quality_failed_with_mock_provider",
            "last_shadow_sample_size": 26,
            "last_shadow_avg_confidence": 0.8,
            "last_shadow_knowledge_gap_rate": 0.6154,
            "last_shadow_weak_citation_count": 16,
            "last_shadow_robotic_generic_count": 26,
            "last_shadow_gate": "fail",
            "side_effects_allowed": False,
            "provider_approval_status": "not_approved",
        },
    }


async def _count(session, sql: str) -> int:
    return int((await session.execute(text(sql), {"tenant_id": TENANT_ID})).scalar() or 0)


async def _safety_counts(session) -> dict[str, int]:
    return {
        "outbound_outbox": await _count(
            session,
            "SELECT COUNT(*) FROM outbound_outbox WHERE tenant_id = :tenant_id",
        ),
        "messages": await _count(
            session,
            "SELECT COUNT(*) FROM messages WHERE tenant_id = :tenant_id",
        ),
        "action_execution_logs": await _count(
            session,
            "SELECT COUNT(*) FROM action_execution_logs WHERE tenant_id = :tenant_id",
        ),
        "customer_field_update_evidence": await _count(
            session,
            """
            SELECT COUNT(*)
            FROM customer_field_update_evidence
            WHERE tenant_id = :tenant_id
            """,
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
        ),
        "lifecycle_stage_history": await _count(
            session,
            "SELECT COUNT(*) FROM lifecycle_stage_history WHERE tenant_id = :tenant_id",
        ),
        "workflow_executions": await _count(
            session,
            """
            SELECT COUNT(*)
            FROM workflow_executions we
            JOIN workflows w ON w.id = we.workflow_id
            WHERE w.tenant_id = :tenant_id
            """,
        ),
    }


async def main() -> None:
    get_settings.cache_clear()
    engine = create_async_engine(get_settings().database_url)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            before = await _safety_counts(session)
            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == TENANT_ID))
            ).scalar_one()
            config = dict(tenant.config or {})
            config["agent_runtime_v2"] = shadow_paused_config()
            await session.execute(
                update(Tenant).where(Tenant.id == TENANT_ID).values(config=config)
            )
            await session.commit()

        async with session_factory() as session:
            rollout = RolloutPolicyService(session)
            policy = await rollout.get_policy(TENANT_ID, AGENT_ID)
            decisions = {
                "preview": (
                    await rollout.can_preview(
                        tenant_id=TENANT_ID,
                        agent_id=AGENT_ID,
                        channel_id=CHANNEL_ID,
                    )
                ).model_dump(mode="json"),
                "shadow": (
                    await rollout.can_shadow(
                        tenant_id=TENANT_ID,
                        agent_id=AGENT_ID,
                        channel_id=CHANNEL_ID,
                    )
                ).model_dump(mode="json"),
                "send": (
                    await rollout.can_send(
                        tenant_id=TENANT_ID,
                        agent_id=AGENT_ID,
                        channel_id=CHANNEL_ID,
                    )
                ).model_dump(mode="json"),
                "actions": (
                    await rollout.can_execute_actions(
                        tenant_id=TENANT_ID,
                        agent_id=AGENT_ID,
                        channel_id=CHANNEL_ID,
                    )
                ).model_dump(mode="json"),
                "workflow_events": (
                    await rollout.can_emit_workflow_events(
                        tenant_id=TENANT_ID,
                        agent_id=AGENT_ID,
                        channel_id=CHANNEL_ID,
                    )
                ).model_dump(mode="json"),
                "model_provider": (
                    await rollout.can_use_model_provider(
                        tenant_id=TENANT_ID,
                        agent_id=AGENT_ID,
                        channel_id=CHANNEL_ID,
                    )
                ).model_dump(mode="json"),
            }
            after = await _safety_counts(session)
            result = {
                "config": policy.model_dump(mode="json"),
                "decisions": decisions,
                "safety_delta": {
                    key: after.get(key, 0) - before.get(key, 0)
                    for key in sorted(before)
                },
            }
            assert policy.runtime_v2_enabled is True
            assert policy.preview_enabled is True
            assert policy.shadow_mode_enabled is False
            assert policy.send_enabled is False
            assert policy.actions_enabled is False
            assert policy.workflow_events_enabled is False
            assert policy.model_provider_enabled is False
            assert decisions["preview"]["allowed"] is True
            assert decisions["shadow"]["allowed"] is False
            assert decisions["send"]["allowed"] is False
            assert decisions["actions"]["allowed"] is False
            assert decisions["workflow_events"]["allowed"] is False
            assert decisions["model_provider"]["allowed"] is False
            assert all(delta == 0 for delta in result["safety_delta"].values())
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

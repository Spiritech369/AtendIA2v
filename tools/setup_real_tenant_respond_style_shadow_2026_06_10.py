"""Phase 18 — Arm Respond-Style inbound shadow on a REAL tenant (no-send).

Runs INSIDE the backend container with two args:
    uv run python setup.py <tenant_id> <agent_id> <config_path> <allowed_phone> [conversation_id] [replay_text]

Steps (all no-send; nothing is delivered to the customer):
1. Create a published AgentVersion for the REAL tenant carrying the
   battery-proven config (passed as JSON data — verticals live in config).
2. Run a REAL direct Test Lab suite against that version (real OpenAI) —
   this is the publish-gate evidence, earned not seeded.
3. Create/point the whatsapp deployment at the version with
   publish_state=published_no_send and metadata flags:
   respond_style_enabled, respond_style_inbound_shadow_enabled,
   respond_style_inbound_shadow_allowed_phones=[<allowed_phone>].
4. Verify publish gates are clear.
5. If a conversation id + replay text are given: run the inbound shadow
   exactly as the Baileys pipeline would, then read back the turn_traces
   evidence row (router_trigger=respond_style_inbound_shadow_auto).
"""

from __future__ import annotations

import asyncio
import json
import sys
from uuid import UUID, uuid4

from sqlalchemy import select, text

from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentTestScenario,
    AgentTestSuite,
    AgentVersion,
)
from atendia.db.session import _get_factory
from atendia.product_agents.inbound_shadow import run_inbound_shadow
from atendia.product_agents.publish_gates import respond_style_publish_blockers
from atendia.product_agents.test_lab_direct_adapter import run_direct_test_suite

# The model that passed the manual battery gate (r8o, 4.45/5).
MODEL = "gpt-4o"

SCENARIOS = [
    ("catalogo_primero", ["hola", "que motos manejas?", "busco algo economico"]),
    (
        "flujo_normal",
        ["hola", "tengo 3 años trabajando", "me pagan por tarjeta", "qué ocupo"],
    ),
    ("requisitos_primero", ["qué ocupo", "dame los papeles primero"]),
    (
        "eligibilidad_y_modelo",
        ["revisan buro?", "me interesa la R4", "tengo 2 años trabajando y me pagan por nomina, que ocupo"],
    ),
]


def _version_payload(config: dict) -> dict:
    persona = config.get("persona") or config.get("agent_name") or "asesor"
    instructions = config.get("instructions") or ""
    if len(persona) > 80:
        # role column is varchar(80); keep the full persona in instructions.
        instructions = f"Persona: {persona}. {instructions}"
    return {
        "role": persona[:80],
        "tone": (config.get("tone") or "breve, humano")[:80],
        "language": config.get("language") or "es",
        "instructions": instructions,
        "knowledge_policy": {"snippets": config.get("kb_snippets") or []},
        "tool_policy": {"bindings": config.get("tool_bindings") or []},
        "action_policy": {},
        "workflow_policy": {"bindings": config.get("workflow_bindings") or []},
        "field_policy": {"fields": config.get("field_definitions") or []},
        "safety_policy": {
            "handoff": config.get("handoff") or {},
            "hard_policies": config.get("hard_policies") or [],
        },
    }


async def main() -> int:
    tenant_id = UUID(sys.argv[1])
    agent_id = UUID(sys.argv[2])
    config = json.load(open(sys.argv[3], encoding="utf-8"))
    allowed_phone = sys.argv[4]
    conversation_id = UUID(sys.argv[5]) if len(sys.argv) > 5 else None
    replay_text = sys.argv[6] if len(sys.argv) > 6 else None

    factory = _get_factory()
    async with factory() as session:
        outbox_before = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()

        # 1. Published version with the proven config as data.
        max_version = (
            await session.execute(
                select(AgentVersion.version_number)
                .where(AgentVersion.tenant_id == tenant_id)
                .order_by(AgentVersion.version_number.desc())
                .limit(1)
            )
        ).scalar() or 0
        version = AgentVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            version_number=max_version + 1,
            status="published",
            **_version_payload(config),
        )
        session.add(version)
        await session.flush()

        # 2. REAL direct Test Lab run (publish-gate evidence).
        suite = AgentTestSuite(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_version_id=version.id,
            name=f"respond-style-shadow-gate-{uuid4().hex[:6]}",
            mode="no_send",
        )
        session.add(suite)
        await session.flush()
        for name, turns in SCENARIOS:
            session.add(
                AgentTestScenario(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    test_suite_id=suite.id,
                    name=name,
                    turns=turns,
                    status="active",
                )
            )
        await session.flush()
        from atendia.agent_runtime import (
            DryFactsToolExecutor,
            RespondStyleLLMTurnProvider,
            RespondStyleToolLoop,
        )
        from atendia.agent_runtime.respond_style_llm_provider import (
            RespondStyleLLMTurnProviderConfig,
        )
        from atendia.agent_runtime.respond_style_tool_loop import (
            RespondStyleToolLoopConfig,
        )
        from atendia.config import get_settings

        def _gate_factory(cfg):
            return RespondStyleToolLoop(
                provider=RespondStyleLLMTurnProvider(
                    api_key=get_settings().openai_api_key,
                    config=RespondStyleLLMTurnProviderConfig(model=MODEL),
                ),
                executor=DryFactsToolExecutor(cfg.tool_bindings),
                config=RespondStyleToolLoopConfig(max_tool_rounds=3),
            )

        run = await run_direct_test_suite(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            created_by_user_id=None,
            tool_loop_factory=_gate_factory,
        )
        print(
            json.dumps(
                {
                    "test_lab_direct": {
                        "decision": run.decision,
                        "pass_count": run.pass_count,
                        "blocked_count": run.blocked_count,
                    }
                },
                ensure_ascii=False,
            )
        )
        if run.decision != "RESPOND_STYLE_DIRECT_NO_SEND_READY":
            print(json.dumps({"decision": "BLOCKED_BY_TEST_LAB_DIRECT"}))
            await session.rollback()
            return 1

        # 3. Deployment armed for shadow, no-send.
        metadata = {
            "respond_style_enabled": True,
            "respond_style_inbound_shadow_enabled": True,
            "respond_style_inbound_shadow_allowed_phones": [allowed_phone],
            "respond_style_model": MODEL,
        }
        existing = (
            await session.execute(
                select(AgentDeployment).where(
                    AgentDeployment.tenant_id == tenant_id,
                    AgentDeployment.agent_id == agent_id,
                    AgentDeployment.channel == "whatsapp",
                    AgentDeployment.environment == "no_send",
                )
            )
        ).scalars().first()
        if existing is not None:
            existing.active_version_id = version.id
            existing.publish_state = "published_no_send"
            existing.runtime_mode = "test_lab_no_send"
            # Fix-forward mode: improvements re-arm WITHOUT dropping live
            # smoke flags/approval already granted — merge, never overwrite.
            existing.metadata_json = {
                **dict(existing.metadata_json or {}),
                **metadata,
            }
            deployment = existing
        else:
            deployment = AgentDeployment(
                id=uuid4(),
                tenant_id=tenant_id,
                agent_id=agent_id,
                active_version_id=version.id,
                name=f"respond-style-shadow-{uuid4().hex[:6]}",
                channel="whatsapp",
                environment="no_send",
                publish_state="published_no_send",
                runtime_mode="test_lab_no_send",
                metadata_json=metadata,
            )
            session.add(deployment)
        await session.flush()

        # 4. Publish gates must be clear.
        blockers = await respond_style_publish_blockers(
            session,
            tenant_id=tenant_id,
            version_id=version.id,
            deployment=deployment,
        )
        if blockers:
            print(json.dumps({"decision": "BLOCKED_BY_PUBLISH_GATES", "blockers": blockers}))
            await session.rollback()
            return 1
        # F28 state hygiene: captured shadow fields predating the new
        # version's validation rules are not trustworthy — reset them for
        # the allowlisted phone's conversations before the new window.
        cleaned = await session.execute(
            text(
                """DELETE FROM respond_style_shadow_fields
                WHERE conversation_id IN (
                    SELECT c.id FROM conversations c
                    JOIN customers cu ON cu.id = c.customer_id
                    WHERE c.tenant_id = :tenant
                      AND right(regexp_replace(cu.phone_e164, '\D', '', 'g'), 10)
                          = right(regexp_replace(:phone, '\D', '', 'g'), 10)
                )"""
            ),
            {"tenant": str(tenant_id), "phone": allowed_phone},
        )
        print(json.dumps({"f28_shadow_state_rows_cleaned": cleaned.rowcount}))
        await session.commit()
        print(
            json.dumps(
                {
                    "deployment_armed": {
                        "deployment_id": str(deployment.id),
                        "agent_version_id": str(version.id),
                        "publish_state": deployment.publish_state,
                        "metadata": metadata,
                    }
                },
                ensure_ascii=False,
            )
        )

        # 5. Optional: shadow replay on a REAL conversation turn.
        if conversation_id is not None and replay_text:
            inbound_id = (
                await session.execute(
                    text(
                        "SELECT id FROM messages WHERE conversation_id=:c "
                        "AND direction='inbound' AND text=:t "
                        "ORDER BY sent_at DESC LIMIT 1"
                    ),
                    {"c": str(conversation_id), "t": replay_text},
                )
            ).scalar()
            phone = (
                await session.execute(
                    text(
                        "SELECT cu.phone_e164 FROM conversations c "
                        "JOIN customers cu ON cu.id=c.customer_id WHERE c.id=:c"
                    ),
                    {"c": str(conversation_id)},
                )
            ).scalar()
            summaries = await run_inbound_shadow(
                session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=replay_text,
                inbound_message_id=inbound_id,
                from_phone_e164=phone,
            )
            await session.commit()
            print(json.dumps({"shadow_replay": summaries}, ensure_ascii=False, default=str))

        outbox_after = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()
        print(
            json.dumps(
                {
                    "outbox_delta": (outbox_after or 0) - (outbox_before or 0),
                    "decision": "REAL_TENANT_SHADOW_ARMED",
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

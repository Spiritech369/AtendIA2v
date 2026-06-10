"""Phase 13B — Docker harness for the opt-in inbound shadow.

Runs INSIDE the backend container: seeds a published deployment with
respond_style_enabled + respond_style_inbound_shadow_enabled and an active
generic version, then invokes the same shadow function the inbound pipeline
calls, against real Postgres and real OpenAI. Verifies no_send evidence and
a zero outbox delta.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from sqlalchemy import select, text

from atendia.db.models.agent import Agent
from atendia.db.models.product_agent import AgentDeployment, AgentVersion
from atendia.db.session import _get_factory
from atendia.product_agents.inbound_shadow import run_inbound_shadow

GENERIC_TOOL_POLICY = {
    "bindings": [
        {
            "name": "requirements.lookup",
            "description": "Returns the factual requirement list for a validated selection.",
            "preconditions": ["selected_option"],
            "dry_facts": {"requirements": ["valid identification", "proof of address"]},
        }
    ]
}


async def main() -> int:
    factory = _get_factory()
    async with factory() as session:
        tenant_id = (await session.execute(select(Agent.tenant_id).limit(1))).scalar()
        agent_id = (
            await session.execute(
                select(Agent.id).where(Agent.tenant_id == tenant_id).limit(1)
            )
        ).scalar()
        version = AgentVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            version_number=980000 + int(str(uuid4().int)[:4]),
            status="published",
            role="generic advisor",
            tone="brief, human",
            language="es",
            instructions="Use configured capabilities for exact sourced facts only.",
            tool_policy=GENERIC_TOOL_POLICY,
            field_policy={"fields": [{"field_key": "selected_option", "required": True}]},
            safety_policy={"handoff": {"enabled": True, "targets": ["support"]}},
        )
        session.add(version)
        await session.flush()
        deployment = AgentDeployment(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            active_version_id=version.id,
            name=f"phase13-shadow-{uuid4().hex[:6]}",
            channel="whatsapp",
            environment="no_send",
            publish_state="published_no_send",
            runtime_mode="test_lab_no_send",
            metadata_json={
                "respond_style_enabled": True,
                "respond_style_inbound_shadow_enabled": True,
            },
        )
        session.add(deployment)
        await session.commit()

        outbox_before = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()

        summaries = await run_inbound_shadow(
            session,
            tenant_id=tenant_id,
            conversation_id=uuid4(),
            inbound_text="hola, me interesa la opcion estandar, que necesito?",
        )

        outbox_after = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()
        outbox_pending = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM outbound_outbox "
                    "WHERE status IN ('pending','retry')"
                )
            )
        ).scalar()

    matched = [
        item for item in summaries if item["deployment_id"] == str(deployment.id)
    ]
    ready = (
        len(matched) == 1
        and matched[0]["send_decision"] == "no_send"
        and not any(matched[0]["side_effects"].values())
        and (outbox_after or 0) - (outbox_before or 0) == 0
    )
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_13B_INBOUND_SHADOW_DOCKER_PASSED"
                    if ready
                    else "PHASE_13B_INBOUND_SHADOW_BLOCKED"
                ),
                "mode": "no_send",
                "shadow_summaries": matched,
                "outbox_delta": (outbox_after or 0) - (outbox_before or 0),
                "outbox_pending_or_retry": outbox_pending,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

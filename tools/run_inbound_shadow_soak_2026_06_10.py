"""Phase 16 — Inbound shadow soak through AgentService (no-send).

Runs INSIDE the backend container. Seeds an opted-in deployment (direct
route + inbound shadow flags) over a generic credit-sales version with
publish-gate evidence, then processes a WINDOW of simulated inbound
messages using the SAME ``run_inbound_shadow`` function wired into the
Baileys inbound pipeline (step 2c). Each shadow turn goes through the REAL
AgentService -> ProductAgentRuntime with shadow field memory. Produces the
operator-review evidence JSON and a DB outbox audit. Nothing is delivered.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text

from atendia.db.models.agent import Agent
from atendia.db.models.conversation import Conversation
from atendia.db.models.customer import Customer
from atendia.db.models.message import MessageRow
from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentTestRun,
    AgentTestSuite,
    AgentVersion,
)
from atendia.db.session import _get_factory
from atendia.product_agents.inbound_shadow import run_inbound_shadow

VERSION_PAYLOAD = {
    "role": "asesor humano de ventas de un producto financiado: calido, directo",
    "tone": "breve, humano",
    "language": "es",
    "instructions": (
        "Califica de forma natural: primero antiguedad laboral, luego como "
        "recibe sus ingresos. Si piden requisitos antes de dar datos, responde "
        "los generales del conocimiento citando esa fuente. Nunca inventes "
        "datos exactos: usa las herramientas. Si piden humano, handoff."
    ),
    "knowledge_policy": {
        "snippets": [
            {
                "source_id": "general_requirements",
                "title": "Requisitos generales",
                "excerpt": (
                    "En general se pide identificacion oficial vigente, "
                    "comprobante de domicilio y alguna forma de demostrar "
                    "ingresos; la lista exacta depende del tipo de ingreso."
                ),
            },
            {
                "source_id": "kb-honestidad",
                "title": "Identidad",
                "excerpt": (
                    "El asistente es digital y puede pasar a un asesor humano "
                    "cuando el cliente lo prefiera."
                ),
            },
        ]
    },
    "tool_policy": {
        "bindings": [
            {
                "name": "eligibility_plan.resolve",
                "description": "Plan correcto; requiere income_type y employment_seniority.",
                "preconditions": ["income_type", "employment_seniority"],
                "dry_facts": {"plan": "plan semanal estandar", "down_payment_percent": 30},
            },
            {
                "name": "requirements.lookup",
                "description": "Lista exacta de papeles; requiere income_type.",
                "preconditions": ["income_type"],
                "dry_facts": {
                    "requirements": [
                        "identificacion oficial vigente",
                        "comprobante de domicilio reciente",
                        "comprobante de ingresos de los ultimos 3 meses",
                    ]
                },
            },
        ]
    },
    "action_policy": {},
    "workflow_policy": {},
    "field_policy": {
        "fields": [
            {"field_key": "employment_seniority", "required": True},
            {"field_key": "income_type", "required": True},
        ]
    },
    "safety_policy": {
        "handoff": {"enabled": True, "targets": ["ventas"]},
        "hard_policies": [
            {
                "policy_id": "requirements_require_support",
                "trigger_patterns": [
                    "\\b(?:requisitos?|papeles|documentos?)\\b[^.?!]*\\b(?:son|incluyen)\\b",
                    "(?:requisitos?|papeles|documentos?)\\s*:",
                ],
                "requires_any": [
                    "tool:requirements.lookup",
                    "basis:knowledge_source",
                ],
            }
        ],
    },
}

WINDOW = [
    (
        "flujo_normal",
        ["hola", "tengo 15 meses trabajando", "me pagan por transferencia", "qué ocupo"],
    ),
    ("requisitos_primero", ["hola", "qué ocupo", "dame los papeles primero"]),
    ("correccion", ["tengo 15 meses", "no, perdón, son 10 meses", "me pagan por nómina"]),
    ("humano", ["hola", "prefiero que me atienda una persona"]),
]


async def _seed(session):
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
        version_number=960000 + int(str(uuid4().int)[:4]),
        status="published",
        **{k: VERSION_PAYLOAD[k] for k in (
            "role", "tone", "language", "instructions", "knowledge_policy",
            "tool_policy", "action_policy", "workflow_policy", "field_policy",
            "safety_policy",
        )},
    )
    session.add(version)
    await session.flush()
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
    metadata = {
        "respond_style_enabled": True,
        "respond_style_inbound_shadow_enabled": True,
    }
    if existing is not None:
        existing.active_version_id = version.id
        existing.publish_state = "published_no_send"
        existing.runtime_mode = "test_lab_no_send"
        existing.metadata_json = metadata
    else:
        session.add(
            AgentDeployment(
                id=uuid4(),
                tenant_id=tenant_id,
                agent_id=agent_id,
                active_version_id=version.id,
                name=f"phase16-{uuid4().hex[:6]}",
                channel="whatsapp",
                environment="no_send",
                publish_state="published_no_send",
                runtime_mode="test_lab_no_send",
                metadata_json=metadata,
            )
        )
    suite = AgentTestSuite(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version.id,
        name=f"phase16-gate-{uuid4().hex[:6]}",
        mode="no_send",
    )
    session.add(suite)
    await session.flush()
    session.add(
        AgentTestRun(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_version_id=version.id,
            test_suite_id=suite.id,
            mode="no_send",
            status="passed",
            decision="RESPOND_STYLE_DIRECT_NO_SEND_READY",
            coverage_summary={
                "execution_mode": "respond_style_product_agent_direct",
                "send_decision": "no_send",
            },
        )
    )
    customer = Customer(
        id=uuid4(),
        tenant_id=tenant_id,
        phone_e164=f"+5210001{str(uuid4().int)[:6]}",
        name="phase16 soak",
    )
    session.add(customer)
    await session.commit()
    return tenant_id, customer.id


async def main() -> int:
    factory = _get_factory()
    async with factory() as session:
        tenant_id, customer_id = await _seed(session)
        outbox_before = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()

        conversations = []
        for name, turns in WINDOW:
            conversation = Conversation(
                id=uuid4(),
                tenant_id=tenant_id,
                customer_id=customer_id,
                channel="whatsapp",
            )
            session.add(conversation)
            await session.flush()
            convo_evidence = {"conversation": name, "turns": [], "transcript": []}
            for inbound in turns:
                session.add(
                    MessageRow(
                        id=uuid4(),
                        conversation_id=conversation.id,
                        tenant_id=tenant_id,
                        direction="inbound",
                        text=inbound,
                        sent_at=datetime.now(UTC),
                        metadata_json={"phase16_soak": name},
                    )
                )
                await session.flush()
                convo_evidence["transcript"].append({"role": "customer", "text": inbound})
                summaries = await run_inbound_shadow(
                    session,
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    inbound_text=inbound,
                )
                summary = summaries[0] if summaries else {}
                candidate = summary.get("final_message_candidate")
                if candidate:
                    session.add(
                        MessageRow(
                            id=uuid4(),
                            conversation_id=conversation.id,
                            tenant_id=tenant_id,
                            direction="outbound",
                            text=candidate,
                            sent_at=datetime.now(UTC),
                            metadata_json={
                                "phase16_soak": name,
                                "simulated_no_send": True,
                            },
                        )
                    )
                    await session.flush()
                    convo_evidence["transcript"].append(
                        {"role": "assistant_shadow", "text": candidate}
                    )
                convo_evidence["turns"].append({"inbound": inbound, **summary})
            conversations.append(convo_evidence)
        await session.commit()

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
        shadow_rows = (
            await session.execute(
                text("SELECT COUNT(*) FROM respond_style_shadow_fields")
            )
        ).scalar()

    all_turns = [turn for convo in conversations for turn in convo["turns"]]
    answered = sum(1 for turn in all_turns if turn.get("final_message_candidate"))
    followups = [
        {"inbound": turn["inbound"], **(turn.get("no_send_followup") or {})}
        for turn in all_turns
        if (turn.get("no_send_followup") or {}).get("action") not in (None, "none")
    ]
    checks = {
        "conversations": len(conversations),
        "turns": len(all_turns),
        "answered": answered,
        "all_no_send": all(
            turn.get("send_decision") == "no_send" for turn in all_turns
        ),
        "legacy_path_used_false": all(
            turn.get("legacy_path_used") is False for turn in all_turns
        ),
        "all_route_agent_service": all(
            turn.get("route") == "respond_style_agent_service_no_send"
            for turn in all_turns
        ),
        "no_outbox_attempts": all(
            turn.get("outbox_write_attempted") is False for turn in all_turns
        ),
        "no_silent_without_reason": all(
            turn.get("final_message_candidate") or turn.get("blocked_reason")
            for turn in all_turns
        ),
        "internal_attention_items": followups,
        "outbox_delta": (outbox_after or 0) - (outbox_before or 0),
        "outbox_pending_or_retry": outbox_pending,
        "shadow_field_rows": shadow_rows,
    }
    ready = (
        checks["all_no_send"]
        and checks["legacy_path_used_false"]
        and checks["all_route_agent_service"]
        and checks["no_outbox_attempts"]
        and checks["no_silent_without_reason"]
        and checks["outbox_delta"] == 0
        and answered > 0
    )
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_16_SOAK_HARNESS_PASSED"
                    if ready
                    else "PHASE_16_SOAK_HARNESS_BLOCKED"
                ),
                "mode": "no_send",
                "checks": checks,
                "conversations": conversations,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

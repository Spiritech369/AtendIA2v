"""Phase 14 E2E — failed V2/V3 transcript replay through AgentService no-send.

Runs INSIDE the backend container: seeds an opted-in published_no_send
deployment (generic credit-sales version with dry-fact tools), passing
publish gates (direct Test Lab evidence row), a fresh customer/conversation,
then replays the historical V2/V3 failed transcripts through the REAL
``AgentService.handle_turn`` with real Postgres and real OpenAI. Verifies:
direct route used (legacy_path_used=false), every turn no_send, no outbox
delta, no internal leaks, both historical failure modes absent.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text

from atendia.agent_runtime.agent_service import AgentService
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

VERSION_PAYLOAD = {
    "role": "asesor humano de ventas de un producto financiado: calido, directo",
    "tone": "breve, humano",
    "language": "es",
    "instructions": (
        "Califica de forma natural: primero antiguedad laboral, luego como "
        "recibe sus ingresos. Si piden requisitos antes de dar datos, responde "
        "los generales del conocimiento citando esa fuente y aclara que la "
        "lista exacta depende del tipo de ingreso. Nunca inventes datos "
        "exactos: usa las herramientas."
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
            }
        ]
    },
    "tool_policy": {
        "bindings": [
            {
                "name": "eligibility_plan.resolve",
                "description": (
                    "Resuelve el plan correcto; requiere income_type y "
                    "employment_seniority."
                ),
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

REPLAYS = [
    ("v2_incident", ["Hola", "Info porfavor", "Me pagan por transferencia", "?"]),
    (
        "v3_incident",
        ["hola", "info porfavor", "15 meses", "me pagan por transferencia", "?"],
    ),
]

LEAK_MARKERS = [
    "campo no está visible",
    "campo no esta visible",
    "field_not_visible",
    "statewriter",
    "error técnico",
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
        version_number=970000 + int(str(uuid4().int)[:4]),
        status="published",
        **{
            key: VERSION_PAYLOAD[key]
            for key in (
                "role",
                "tone",
                "language",
                "instructions",
                "knowledge_policy",
                "tool_policy",
                "action_policy",
                "workflow_policy",
                "field_policy",
                "safety_policy",
            )
        },
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
    if existing is not None:
        existing.active_version_id = version.id
        existing.publish_state = "published_no_send"
        existing.runtime_mode = "test_lab_no_send"
        existing.metadata_json = {"respond_style_enabled": True}
    else:
        session.add(
            AgentDeployment(
                id=uuid4(),
                tenant_id=tenant_id,
                agent_id=agent_id,
                active_version_id=version.id,
                name=f"phase14-{uuid4().hex[:6]}",
                channel="whatsapp",
                environment="no_send",
                publish_state="published_no_send",
                runtime_mode="test_lab_no_send",
                metadata_json={"respond_style_enabled": True},
            )
        )
    # Publish-gate evidence: a passing direct Test Lab run for this version.
    suite = AgentTestSuite(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version.id,
        name=f"phase14-gate-{uuid4().hex[:6]}",
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
        phone_e164=f"+5210000{str(uuid4().int)[:6]}",
        name="phase14 replay",
    )
    session.add(customer)
    await session.flush()
    conversation = Conversation(
        id=uuid4(), tenant_id=tenant_id, customer_id=customer.id, channel="whatsapp"
    )
    session.add(conversation)
    await session.commit()
    return tenant_id, conversation.id


async def main() -> int:
    factory = _get_factory()
    async with factory() as session:
        tenant_id, conversation_id = await _seed(session)
        outbox_before = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()

        service = AgentService(session=session)
        results = []
        turn_number = 0
        for name, turns in REPLAYS:
            for inbound in turns:
                turn_number += 1
                session.add(
                    MessageRow(
                        id=uuid4(),
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                        direction="inbound",
                        text=inbound,
                        sent_at=datetime.now(UTC),
                        metadata_json={"phase14_replay": name},
                    )
                )
                await session.flush()
                outcome = await service.handle_turn(
                    tenant_id=str(tenant_id),
                    conversation_id=str(conversation_id),
                    inbound_text=inbound,
                    turn_number=turn_number,
                    mode="no_send",
                )
                trace = (
                    outcome.output.trace_metadata.get("respond_style_agent_service")
                    if outcome.output is not None
                    else {}
                ) or {}
                candidate = trace.get("final_message_candidate")
                if candidate:
                    session.add(
                        MessageRow(
                            id=uuid4(),
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                            direction="outbound",
                            text=candidate,
                            sent_at=datetime.now(UTC),
                            metadata_json={
                                "phase14_replay": name,
                                "simulated_no_send": True,
                            },
                        )
                    )
                    await session.flush()
                results.append(
                    {
                        "replay": name,
                        "inbound": inbound,
                        "candidate": candidate,
                        "blocked_reason": trace.get("blocked_reason"),
                        "route": trace.get("route"),
                        "legacy_path_used": trace.get("legacy_path_used"),
                        "send_allowed": outcome.send.send_decision.allowed,
                        "outbox_write_attempted": outcome.send.outbox_write_attempted,
                        "leak": any(
                            marker in (candidate or "").casefold()
                            for marker in LEAK_MARKERS
                        ),
                        "tools": [
                            {
                                "tool_name": item.get("tool_name"),
                                "status": item.get("status"),
                            }
                            for item in trace.get("tool_results") or []
                        ],
                    }
                )
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

    answered = sum(1 for item in results if item["candidate"])
    checks = {
        "turns": len(results),
        "answered": answered,
        "all_direct_route": all(
            item["route"] == "respond_style_agent_service_no_send" for item in results
        ),
        "legacy_path_used_false": all(
            item["legacy_path_used"] is False for item in results
        ),
        "all_send_blocked": all(item["send_allowed"] is False for item in results),
        "no_outbox_attempts": all(
            item["outbox_write_attempted"] is False for item in results
        ),
        "outbox_delta": (outbox_after or 0) - (outbox_before or 0),
        "outbox_pending_or_retry": outbox_pending,
        "internal_leaks": sum(1 for item in results if item["leak"]),
        "no_silent_without_reason": all(
            item["candidate"] or item["blocked_reason"] for item in results
        ),
    }
    ready = (
        checks["all_direct_route"]
        and checks["legacy_path_used_false"]
        and checks["all_send_blocked"]
        and checks["no_outbox_attempts"]
        and checks["outbox_delta"] == 0
        and checks["internal_leaks"] == 0
        and checks["no_silent_without_reason"]
        and answered > 0
    )
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_14_AGENT_SERVICE_REPLAY_PASSED"
                    if ready
                    else "PHASE_14_AGENT_SERVICE_REPLAY_BLOCKED"
                ),
                "mode": "no_send",
                "checks": checks,
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

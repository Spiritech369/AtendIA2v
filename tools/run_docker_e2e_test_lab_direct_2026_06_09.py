"""Phase 12A — Docker E2E for the Respond-Style direct Test Lab endpoint.

Runs INSIDE the backend container (docker exec): exercises the real FastAPI
endpoint (ASGI transport, auth dependencies overridden with a synthetic
tenant-admin), real Postgres, real OpenAI provider, and verifies the stored
AgentTestRun evidence plus a global outbox audit. Also exercises the Phase
12B routing preview against the real DB. No send, no live.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
from sqlalchemy import func, select, text

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, require_tenant_admin
from atendia.db.models.agent import Agent
from atendia.db.models.product_agent import (
    AgentTestRun,
    AgentTestScenario,
    AgentTestSuite,
    AgentVersion,
)
from atendia.db.session import _get_factory
from atendia.main import app
from atendia.product_agents.routing_preview import preview_respond_style_routing

GENERIC_TOOL_POLICY = {
    "bindings": [
        {
            "name": "requirements.lookup",
            "description": "Returns the factual requirement list for a validated selected option.",
            "preconditions": ["selected_option"],
            "dry_facts": {
                "requirements": [
                    "valid identification",
                    "proof of address",
                ]
            },
        },
        {
            "name": "catalog.search",
            "description": "Finds catalog options and returns their option_id values.",
            "dry_facts": {
                "options": [
                    {"option_id": "opt-1", "label": "standard option"},
                ]
            },
        },
    ]
}


async def _seed(session) -> tuple:
    tenant_id = (await session.execute(select(Agent.tenant_id).limit(1))).scalar()
    agent_id = (
        await session.execute(
            select(Agent.id).where(Agent.tenant_id == tenant_id).limit(1)
        )
    ).scalar()
    assert tenant_id is not None and agent_id is not None, "dev DB has no agents"

    version = AgentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        version_number=990000 + int(str(uuid4().int)[:4]),
        status="published",
        role="generic advisor",
        tone="brief, human",
        language="es",
        instructions="Use configured capabilities for exact sourced facts only.",
        tool_policy=GENERIC_TOOL_POLICY,
        field_policy={"fields": [{"field_key": "selected_option", "required": True}]},
        safety_policy={
            "handoff": {"enabled": True, "targets": ["support"]},
            "hard_policies": [
                {
                    "policy_id": "requirements_claim_requires_support",
                    "trigger_patterns": [r"\b(?:requisitos?|requirements?)\b"],
                    "requires_any": [
                        "tool:requirements.lookup",
                        "basis:knowledge_source",
                    ],
                }
            ],
        },
    )
    suite = AgentTestSuite(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version.id,
        name=f"phase12-docker-e2e-{uuid4().hex[:6]}",
        mode="no_send",
    )
    scenario = AgentTestScenario(
        id=uuid4(),
        tenant_id=tenant_id,
        test_suite_id=suite.id,
        name="greeting_and_requirements",
        turns=[
            {"inbound_text": "hola"},
            {"inbound_text": "me interesa la opcion estandar, que necesito?"},
        ],
        expected={},
    )
    session.add(version)
    await session.flush()
    session.add(suite)
    await session.flush()
    session.add(scenario)
    await session.commit()
    return tenant_id, suite.id


async def main() -> int:
    async_session_factory = _get_factory()
    async with async_session_factory() as session:
        tenant_id, suite_id = await _seed(session)

        outbox_before = (
            await session.execute(text("SELECT COUNT(*) FROM outbound_outbox"))
        ).scalar()

        previews = await preview_respond_style_routing(session, tenant_id=tenant_id)

    app.dependency_overrides[current_tenant_id] = lambda: tenant_id
    app.dependency_overrides[require_tenant_admin] = lambda: AuthUser(
        user_id=uuid4(), tenant_id=tenant_id, role="tenant_admin", email="e2e@test.local"
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://e2e"
        ) as client:
            response = await client.post(
                f"/api/v1/product-agents/test-suites/{suite_id}/runs/respond-style-direct",
                timeout=300.0,
                headers={"X-CSRF-Token": "e2e-csrf"},
                cookies={"atendia_csrf": "e2e-csrf"},
            )
    finally:
        app.dependency_overrides.clear()

    run_payload = response.json() if response.status_code == 201 else None

    async with async_session_factory() as session:
        run_row = None
        if run_payload:
            run_row = await session.get(AgentTestRun, run_payload["id"])
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
        run_count_for_suite = (
            await session.execute(
                select(func.count())
                .select_from(AgentTestRun)
                .where(AgentTestRun.test_suite_id == suite_id)
            )
        ).scalar()

    turns = run_row.turn_results if run_row is not None else []
    checks = {
        "http_status": response.status_code,
        "run_persisted": run_row is not None,
        "runs_for_suite": run_count_for_suite,
        "run_mode": run_row.mode if run_row else None,
        "run_status": run_row.status if run_row else None,
        "run_decision": run_row.decision if run_row else None,
        "execution_mode": (run_row.coverage_summary or {}).get("execution_mode")
        if run_row
        else None,
        "turns": [
            {
                "inbound": item.get("inbound_text"),
                "send_decision": item.get("send_decision"),
                "blocked_reason": item.get("blocked_reason"),
                "final_message": (item.get("final_message") or "")[:120] or None,
                "tools": item.get("tools"),
            }
            for item in turns
        ],
        "all_turns_no_send": all(
            item.get("send_decision") == "no_send" for item in turns
        )
        and bool(turns),
        "outbox_audit": run_row.outbox_audit_result if run_row else None,
        "outbox_rows_before": outbox_before,
        "outbox_rows_after": outbox_after,
        "outbox_delta": (outbox_after or 0) - (outbox_before or 0),
        "outbox_pending_or_retry": outbox_pending,
        "routing_previews": previews,
        "routing_previews_all_no_send": all(
            item["send_decision"] == "no_send"
            and item["live_routing_active"] is False
            for item in previews
        ),
    }
    ready = (
        checks["http_status"] == 201
        and checks["run_persisted"]
        and checks["run_mode"] == "no_send"
        and checks["all_turns_no_send"]
        and checks["outbox_delta"] == 0
        and checks["execution_mode"] == "respond_style_product_agent_direct"
        and checks["routing_previews_all_no_send"]
    )
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_12A_DOCKER_E2E_TEST_LAB_DIRECT_PASSED"
                    if ready
                    else "PHASE_12A_DOCKER_E2E_BLOCKED"
                ),
                "mode": "no_send",
                "checks": checks,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

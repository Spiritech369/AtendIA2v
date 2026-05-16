"""Task 6 — Workflow create + trigger (committed, real) + execute, verified.

Goal: build a workflow mirroring the Prompt master's `#HANDOFF
ESTRUCTURADO` block (docs/Prompt master.txt:195-202 — "Before assigning to
@Francisco ... ALWAYS add internal comment: Resumen ..."), publish it,
trigger it via a REAL committed stage transition into `papeleria_completa`,
and prove an execution ran end-to-end (assign_agent + structured internal
note nodes), then restore the tenant to baseline.

Mechanism (pinned READ-ONLY from source — file:line in FINDINGS):

  - Workflow contract: `WorkflowBody` (workflows_routes.py:35-54) requires
    name + trigger_type (must be in engine.TRIGGERS); `definition` is
    structurally validated by engine.validate_definition (engine.py:179).
    `stage_entered` IS a valid trigger (engine.py:70). `_trigger_matches`
    (engine.py:643-669) fires when trigger_config {"to": X} == event
    payload {"to": X}.

  - The ONLY committed emitter of EventType.STAGE_ENTERED with payload
    {"to": <stage>} is the runner at conversation_runner.py:606-611, on a
    real stage transition inside run_turn. The PATCH /conversations/{id}
    stage-move endpoint does NOT emit STAGE_ENTERED — it only emits
    CONVERSATION_UPDATED (conversations_routes.py:1237-1242) — so an
    operator API stage move would NOT trigger a stage_entered workflow
    (recorded as finding #14). Therefore the committed trigger here is a
    REAL runner stage transition.

  - Bug #10 (Task 4) blocks text/NLU auto-advance out of `nuevo_lead`, but
    the DOCUMENT path works (Task 4 sub-goal 3 PASS): setting customer.attrs
    = {plan_credito:"sin_comprobantes_25", DOCS_INE_FRENTE/REVERSO/
    COMPROBANTE_DOMICILIO:{status:"ok"}} drives nuevo_lead ->
    papeleria_completa via the M3 evaluator. We COMMIT those attrs and run
    the REAL ConversationRunner once → it emits STAGE_ENTERED{to:
    papeleria_completa} and we commit.

  - The committed event is picked up by `poll_workflow_triggers`
    (workflow_jobs.py:38-104), an arq cron on the dedicated workflows
    queue (worker.py:367-374; cron seconds {5,15,25,35,45,55} → every
    ~10s) run by the `atendia_workflow_worker` container. It calls
    evaluate_event (creates a WorkflowExecution for each matching active
    workflow) then execute_workflow INLINE in worker context. So no
    manual enqueue is needed — committing the STAGE_ENTERED event is the
    whole trigger.

Verification (authoritative = DB, since _execution_replay is partly
synthetic — workflows_routes.py:750-788): poll workflow_executions +
workflow_action_runs for THIS workflow/conversation; assert a row with a
terminal non-running status and per-node WorkflowActionRun rows for the
assign_agent + notify_agent nodes. Also hit GET
/api/v1/workflows/{id}/executions (the UI's endpoint).

Cleanup: delete the workflow (CASCADE drops workflow_executions →
workflow_action_runs / steps via ondelete=CASCADE) + the seeded
conversation/customer/state/events; verify tenant 867a1047 == baseline
(agents=1, faqs=32, catalog=34, pipelines_active=1, conversations=0,
customers=0, turn_traces=0, workflows=0).

Budget: assign_agent + notify_agent are template/DB nodes (no LLM). The
single committed runner turn is on the document path — `papeleria_completa`
has pause_bot_on_enter:true so the composer is skipped; only NLU runs
(gpt-4o-mini, ~$0.0001). Real spend << $0.05.

Run via the core venv:
  cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python ../tools/e2e/task6_workflow.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_setup import Client  # noqa: E402

TENANT_ID = "867a1047-6aea-4b21-85d8-898aef0051cb"
DEFAULT_AGENT_ID = "e34419ae-3829-4004-ad08-e133d9eb7109"  # the tenant's 1 agent
SEED_PHONE = "+5218180000066"  # unique to this task
START_STAGE = "nuevo_lead"
TARGET_STAGE = "papeleria_completa"

# Task 4 sub-goal 3 (PASS): the minimal plan whose docs_per_plan is exactly
# these 3 DOCS_* (motos_credito_pipeline.json). Committing these on
# customer.attrs makes the M3 evaluator move nuevo_lead -> papeleria_completa.
DOC_PROOF_PLAN = "sin_comprobantes_25"
DOC_PROOF_DOCS = (
    "DOCS_INE_FRENTE",
    "DOCS_INE_REVERSO",
    "DOCS_COMPROBANTE_DOMICILIO",
)

# Mirrors docs/Prompt master.txt:197-201 (#HANDOFF ESTRUCTURADO). Plain text
# only — NO {{mustache}} tokens (a {{x}} token would surface as a
# MISSING_VARIABLE and 409 the publish via _operational_validate).
HANDOFF_NOTE = (
    "Resumen handoff (papeleria_completa). "
    "Plan: sin comprobantes 25%. Enganche: 25%. "
    "Docs recibidos: INE frente, INE reverso, comprobante de domicilio. "
    "Docs pendientes: ninguno (papeleria completa para el plan). "
    "Siguiente accion: asesor humano valida expediente y continua el cierre. "
    "Asignado a asesor para que no arranque a ciegas."
)

# Workflow definition. Node-type contract from engine.NODE_TYPES
# (engine.py:90-120). Publish gate _operational_validate
# (workflows_routes.py:502-639) requires a node type=="end"
# (MISSING_FINAL_NODE) and all edges to reference real nodes (BROKEN_EDGE);
# safety rules default all-true when ops.safety_rules is unset
# (_default_safety_rules :292-296) so we deliberately set NO ops block.
#   trigger_1 -> assign_1 (assign_agent) -> note_1 (notify_agent) -> end_1
WORKFLOW_NAME = "E2E HANDOFF ESTRUCTURADO papeleria_completa"
WORKFLOW_DEFINITION = {
    "nodes": [
        {"id": "trigger_1", "type": "trigger", "config": {"event": "stage_entered"}},
        {
            "id": "assign_1",
            "type": "assign_agent",
            "title": "Asignar a asesor (Francisco)",
            "config": {"agent_id": DEFAULT_AGENT_ID},
        },
        {
            "id": "note_1",
            "type": "notify_agent",
            "title": "Comentario interno estructurado",
            "config": {
                # engine VALID_ROLES = {operator,tenant_admin,superadmin}
                # (engine.py:122). This tenant's only TenantUser is
                # role=superadmin (verified live) — _resolve_notify_targets
                # (engine.py:1116-1135) returns [] for a role with zero
                # users and the node would no-op WITHOUT recording an
                # action. Target the role that actually exists so the
                # structured internal note (a Notification row) is created.
                "role": "superadmin",
                "title": "Resumen handoff - papeleria_completa",
                "body": HANDOFF_NOTE,
            },
        },
        {"id": "end_1", "type": "end", "config": {}},
    ],
    "edges": [
        {"from": "trigger_1", "to": "assign_1"},
        {"from": "assign_1", "to": "note_1"},
        {"from": "note_1", "to": "end_1"},
    ],
}

# poll_workflow_triggers cron runs at seconds {5,15,25,35,45,55} (~10s
# cadence) and processes a per-tenant event backlog (100/tick) before our
# fresh event. Generous wait + poll loop.
POLL_TIMEOUT_S = 150
POLL_INTERVAL_S = 5


# ---------------------------------------------------------------------------
# Step 1 — create + publish + read-back the workflow (UI's own REST API)
# ---------------------------------------------------------------------------


def _create_publish_workflow(client: Client) -> dict:
    out: dict = {}

    create_body = {
        "name": WORKFLOW_NAME,
        "description": "E2E task6 — mirrors Prompt master #HANDOFF ESTRUCTURADO",
        "trigger_type": "stage_entered",
        "trigger_config": {"to": TARGET_STAGE},
        "definition": WORKFLOW_DEFINITION,
        "active": True,
    }
    r_create = client.post("/api/v1/workflows", json_body=create_body)
    out["create_status"] = r_create.status_code
    if r_create.status_code != 201:
        out["create_body"] = r_create.text[:1500]
        return out
    created = r_create.json()
    wf_id = created.get("id")
    out["workflow_id"] = wf_id
    out["create_node_ids"] = [
        n.get("id") for n in (created.get("definition") or {}).get("nodes", [])
    ]
    out["create_trigger_type"] = created.get("trigger_type")
    out["create_trigger_config"] = created.get("trigger_config")
    out["create_active"] = created.get("active")

    # Publish (POST /{id}/publish). _operational_validate 409s on any
    # critical issue — capture the body if it does.
    r_pub = client.post(f"/api/v1/workflows/{wf_id}/publish")
    out["publish_status"] = r_pub.status_code
    if r_pub.status_code != 200:
        out["publish_body"] = r_pub.text[:1500]
    else:
        pub = r_pub.json()
        out["publish_active"] = pub.get("active")
        out["publish_version"] = pub.get("version")

    # Read-back (GET /{id}) — assert published/active + structure persisted.
    r_get = client.get(f"/api/v1/workflows/{wf_id}")
    out["get_status"] = r_get.status_code
    if r_get.status_code == 200:
        g = r_get.json()
        nodes = (g.get("definition") or {}).get("nodes", [])
        out["readback"] = {
            "active": g.get("active"),
            "trigger_type": g.get("trigger_type"),
            "trigger_config": g.get("trigger_config"),
            "node_ids": [n.get("id") for n in nodes],
            "node_types": [n.get("type") for n in nodes],
            "has_end_node": any(n.get("type") == "end" for n in nodes),
            "status": g.get("status"),
            "validation_critical": (g.get("validation") or {}).get("critical_count"),
        }
    return out


# ---------------------------------------------------------------------------
# Step 2a — seed + commit a real conversation, then a committed stage move
# ---------------------------------------------------------------------------


async def _seed(session) -> tuple[UUID, UUID]:
    """Insert ONLY customer + conversation + conversation_state under the
    EXISTING isolated tenant. Mirrors task4/task5 seed shape. attrs starts
    empty; the document attrs are set just before the runner turn."""
    from sqlalchemy import text

    customer_id = (
        await session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164, attrs) "
                "VALUES (:t, :p, '{}'::jsonb) RETURNING id"
            ),
            {"t": TENANT_ID, "p": SEED_PHONE},
        )
    ).scalar()
    conversation_id = (
        await session.execute(
            text(
                "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                "VALUES (:t, :c, :s) RETURNING id"
            ),
            {"t": TENANT_ID, "c": customer_id, "s": START_STAGE},
        )
    ).scalar()
    await session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
        {"c": conversation_id},
    )
    await session.commit()
    return UUID(str(conversation_id)), UUID(str(customer_id))


async def _commit_doc_transition(
    session, *, conversation_id: UUID, customer_id: UUID
) -> dict:
    """Set customer.attrs (docs complete for the minimal plan) and COMMIT,
    then run the REAL ConversationRunner ONCE and COMMIT. The runner emits
    EventType.STAGE_ENTERED{to: papeleria_completa} at
    conversation_runner.py:606-611 on the transition, persisted by the
    commit. papeleria_completa has pause_bot_on_enter:true so the composer
    is skipped (only NLU runs).

    Returns {stage_transition, stage_after, flow_mode, cost_usd, outbound}.
    """
    from datetime import UTC, datetime

    from sqlalchemy import select as _sel

    from atendia.config import get_settings
    from atendia.contracts.message import Message, MessageDirection
    from atendia.db.models.customer import Customer
    from atendia.runner.composer_openai import OpenAIComposer
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.runner.nlu_openai import OpenAINLU

    api_key = get_settings().openai_api_key
    if not api_key:
        raise RuntimeError("openai_api_key not set — cannot run real runner")

    # Commit the document attrs onto the customer (ORM, no ::jsonb cast —
    # asyncpg treats :: as a bind delimiter; mirror task4's approach).
    attrs_payload = {"plan_credito": DOC_PROOF_PLAN}
    for k in DOC_PROOF_DOCS:
        attrs_payload[k] = {"status": "ok"}
    cust = (
        await session.execute(_sel(Customer).where(Customer.id == customer_id))
    ).scalar_one()
    merged = dict(cust.attrs or {})
    merged.update(attrs_payload)
    cust.attrs = merged
    session.add(cust)
    await session.commit()

    nlu = OpenAINLU(api_key=api_key)
    composer = OpenAIComposer(api_key=api_key)
    runner = ConversationRunner(session, nlu, composer)
    inbound = Message(
        id=str(uuid4()),
        conversation_id=str(conversation_id),
        tenant_id=TENANT_ID,
        direction=MessageDirection.INBOUND,
        text="aqui estan mis documentos",
        sent_at=datetime.now(UTC),
    )
    trace = await runner.run_turn(
        conversation_id=conversation_id,
        tenant_id=UUID(TENANT_ID),
        inbound=inbound,
        turn_number=1,
    )
    await session.commit()  # persists turn_trace + STAGE_ENTERED event

    state_after = getattr(trace, "state_after", None) or {}
    cost = (
        (getattr(trace, "nlu_cost_usd", None) or Decimal("0"))
        + (getattr(trace, "composer_cost_usd", None) or Decimal("0"))
        + (getattr(trace, "tool_cost_usd", None) or Decimal("0"))
        + (getattr(trace, "vision_cost_usd", None) or Decimal("0"))
    )
    return {
        "stage_transition": getattr(trace, "stage_transition", None),
        "stage_after": state_after.get("current_stage")
        if isinstance(state_after, dict)
        else None,
        "flow_mode": getattr(trace, "flow_mode", None),
        "cost_usd": str(cost),
        "outbound": list(getattr(trace, "outbound_messages", None) or []),
    }


# ---------------------------------------------------------------------------
# Step 2b — poll for the workflow execution (DB = authoritative)
# ---------------------------------------------------------------------------


async def _poll_execution(
    session_factory, *, workflow_id: str, conversation_id: UUID
) -> dict:
    """Poll workflow_executions for a row tied to THIS workflow +
    conversation, started by the cron after our committed STAGE_ENTERED
    event. Returns the verbatim execution row + the per-node
    workflow_action_runs (the real replay/proof; _execution_replay is
    partly synthetic so the DB rows are authoritative).
    """
    from sqlalchemy import text

    deadline = time.time() + POLL_TIMEOUT_S
    last_seen: dict = {}
    while time.time() < deadline:
        session = session_factory()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, workflow_id, conversation_id, "
                        "trigger_event_id, status, current_node_id, "
                        "error, error_code, steps_completed, "
                        "started_at, finished_at "
                        "FROM workflow_executions "
                        "WHERE workflow_id = :w AND conversation_id = :c "
                        "ORDER BY started_at DESC LIMIT 1"
                    ),
                    {"w": workflow_id, "c": str(conversation_id)},
                )
            ).mappings().first()
            if row is not None:
                exec_id = str(row["id"])
                action_runs = (
                    (
                        await session.execute(
                            text(
                                "SELECT node_id, action_key, created_at "
                                "FROM workflow_action_runs "
                                "WHERE execution_id = :e "
                                "ORDER BY created_at ASC"
                            ),
                            {"e": exec_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                # Also fetch the event that triggered it for the proof trail.
                ev = None
                if row["trigger_event_id"] is not None:
                    ev = (
                        await session.execute(
                            text(
                                "SELECT type, payload, occurred_at "
                                "FROM events WHERE id = :i"
                            ),
                            {"i": str(row["trigger_event_id"])},
                        )
                    ).mappings().first()
                last_seen = {
                    "execution_row": {k: str(v) for k, v in dict(row).items()},
                    "trigger_event": (
                        {k: str(v) for k, v in dict(ev).items()} if ev else None
                    ),
                    "action_runs": [
                        {k: str(v) for k, v in dict(a).items()} for a in action_runs
                    ],
                }
                status = row["status"]
                # Terminal AND both side-effect nodes recorded.
                node_ids = {a["node_id"] for a in action_runs}
                if status in ("completed", "failed") and {
                    "assign_1",
                    "note_1",
                }.issubset(node_ids):
                    last_seen["terminal"] = True
                    return last_seen
                if status == "completed":
                    last_seen["terminal"] = True
                    return last_seen
        finally:
            await session.close()
        await asyncio.sleep(POLL_INTERVAL_S)
    last_seen["terminal"] = False
    last_seen["timed_out"] = True
    return last_seen


# ---------------------------------------------------------------------------
# Step 3 — cleanup + baseline verification
# ---------------------------------------------------------------------------


async def _cleanup(
    session, *, workflow_id: str | None, conversation_id: UUID, customer_id: UUID
) -> dict:
    """Delete the workflow (CASCADE → workflow_executions →
    workflow_action_runs/steps via ondelete=CASCADE; workflow.py:43-123)
    and the seeded conversation/customer chain. Verify tenant == baseline.
    """
    from sqlalchemy import text

    cid = str(conversation_id)
    custid = str(customer_id)

    # 1. Workflow first (FK CASCADE removes its executions + action_runs +
    #    steps). Defensive explicit deletes too in case of SET NULL races.
    if workflow_id:
        await session.execute(
            text(
                "DELETE FROM workflow_action_runs WHERE execution_id IN "
                "(SELECT id FROM workflow_executions WHERE workflow_id = :w)"
            ),
            {"w": workflow_id},
        )
        await session.execute(
            text(
                "DELETE FROM workflow_execution_steps WHERE execution_id IN "
                "(SELECT id FROM workflow_executions WHERE workflow_id = :w)"
            ),
            {"w": workflow_id},
        )
        await session.execute(
            text("DELETE FROM workflow_executions WHERE workflow_id = :w"),
            {"w": workflow_id},
        )
        await session.execute(
            text("DELETE FROM workflow_versions WHERE workflow_id = :w"),
            {"w": workflow_id},
        )
        await session.execute(
            text("DELETE FROM workflows WHERE id = :w AND tenant_id = :t"),
            {"w": workflow_id, "t": TENANT_ID},
        )

    # 2. Seeded conversation chain (scoped to the seeded ids only).
    await session.execute(
        text(
            "DELETE FROM tool_calls WHERE turn_trace_id IN "
            "(SELECT id FROM turn_traces WHERE conversation_id = :c)"
        ),
        {"c": cid},
    )
    await session.execute(
        text(
            "DELETE FROM outbound_outbox WHERE "
            "sent_message_id IN (SELECT id FROM messages WHERE conversation_id = :c) "
            "OR payload->>'conversation_id' = cast(:c AS text)"
        ),
        {"c": cid},
    )
    for tbl in (
        "turn_traces",
        "events",
        "messages",
        "field_suggestions",
        "human_handoffs",
        "conversation_reads",
        "conversation_state",
    ):
        await session.execute(
            text(f"DELETE FROM {tbl} WHERE conversation_id = :c"), {"c": cid}
        )
    await session.execute(
        text("DELETE FROM conversations WHERE id = :c"), {"c": cid}
    )
    await session.execute(
        text("DELETE FROM customers WHERE id = :id"), {"id": custid}
    )
    await session.commit()

    # ---- verification ----
    residual: dict[str, int] = {}
    if workflow_id:
        residual["workflows"] = (
            await session.execute(
                text("SELECT COUNT(*) FROM workflows WHERE id = :w"),
                {"w": workflow_id},
            )
        ).scalar()
        residual["workflow_executions"] = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM workflow_executions WHERE workflow_id = :w"
                ),
                {"w": workflow_id},
            )
        ).scalar()
    for tbl in (
        "turn_traces",
        "events",
        "messages",
        "conversation_state",
    ):
        residual[tbl] = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE conversation_id = :c"),
                {"c": cid},
            )
        ).scalar()
    residual["conversations"] = (
        await session.execute(
            text("SELECT COUNT(*) FROM conversations WHERE id = :c"), {"c": cid}
        )
    ).scalar()
    residual["customers"] = (
        await session.execute(
            text("SELECT COUNT(*) FROM customers WHERE id = :id"), {"id": custid}
        )
    ).scalar()

    # Tenant-wide baseline (the contract's exact numbers).
    tenant_counts = {
        "agents": (
            await session.execute(
                text("SELECT COUNT(*) FROM agents WHERE tenant_id = :t"),
                {"t": TENANT_ID},
            )
        ).scalar(),
        "tenant_faqs": (
            await session.execute(
                text("SELECT COUNT(*) FROM tenant_faqs WHERE tenant_id = :t"),
                {"t": TENANT_ID},
            )
        ).scalar(),
        "tenant_catalogs": (
            await session.execute(
                text("SELECT COUNT(*) FROM tenant_catalogs WHERE tenant_id = :t"),
                {"t": TENANT_ID},
            )
        ).scalar(),
        "tenant_pipelines_active": (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM tenant_pipelines "
                    "WHERE tenant_id = :t AND active = true"
                ),
                {"t": TENANT_ID},
            )
        ).scalar(),
        "conversations": (
            await session.execute(
                text("SELECT COUNT(*) FROM conversations WHERE tenant_id = :t"),
                {"t": TENANT_ID},
            )
        ).scalar(),
        "customers": (
            await session.execute(
                text("SELECT COUNT(*) FROM customers WHERE tenant_id = :t"),
                {"t": TENANT_ID},
            )
        ).scalar(),
        "workflows": (
            await session.execute(
                text("SELECT COUNT(*) FROM workflows WHERE tenant_id = :t"),
                {"t": TENANT_ID},
            )
        ).scalar(),
        "turn_traces": (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM turn_traces tt "
                    "JOIN conversations c ON c.id = tt.conversation_id "
                    "WHERE c.tenant_id = :t"
                ),
                {"t": TENANT_ID},
            )
        ).scalar(),
    }
    baseline = {
        "agents": 1,
        "tenant_faqs": 32,
        "tenant_catalogs": 34,
        "tenant_pipelines_active": 1,
        "conversations": 0,
        "customers": 0,
        "workflows": 0,
        "turn_traces": 0,
    }
    return {
        "residual_rows": residual,
        "all_residual_zero": all(v == 0 for v in residual.values()),
        "tenant_counts_after": tenant_counts,
        "baseline": baseline,
        "tenant_at_baseline": tenant_counts == baseline,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def _amain() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from atendia.db.session import _get_factory

    factory = _get_factory()

    client = Client()
    client.login()
    print(f"[auth] logged in OK — tenant_id={client.tenant_id}")
    if client.tenant_id != TENANT_ID:
        print(f"[auth] FAIL — expected {TENANT_ID}, got {client.tenant_id}")
        return 1

    workflow_id: str | None = None
    conversation_id: UUID | None = None
    customer_id: UUID | None = None
    wf_report: dict = {}
    move_report: dict = {}
    exec_report: dict = {}
    cleanup_report: dict = {}
    run_error: str | None = None

    try:
        # --- Step 1: create + publish + read-back ----------------------
        wf_report = _create_publish_workflow(client)
        workflow_id = wf_report.get("workflow_id")
        print("\n[workflow] ===== create/publish =====")
        print(json.dumps(wf_report, ensure_ascii=False, indent=2, default=str))
        if not workflow_id or wf_report.get("publish_status") != 200:
            raise RuntimeError(
                f"workflow create/publish failed: {wf_report.get('create_status')}/"
                f"{wf_report.get('publish_status')}"
            )

        # --- Step 2a: seed + committed real stage transition -----------
        seed_session = factory()
        try:
            conversation_id, customer_id = await _seed(seed_session)
        finally:
            await seed_session.close()
        print(
            f"\n[seed] conversation_id={conversation_id} "
            f"customer_id={customer_id} phone={SEED_PHONE} stage={START_STAGE}"
        )

        run_session = factory()
        try:
            move_report = await _commit_doc_transition(
                run_session,
                conversation_id=conversation_id,
                customer_id=customer_id,
            )
        finally:
            await run_session.close()
        print("\n[stage-move] ===== committed runner turn =====")
        print(json.dumps(move_report, ensure_ascii=False, indent=2, default=str))
        st = move_report.get("stage_transition")
        if not (st and str(st).endswith(f"->{TARGET_STAGE}")):
            raise RuntimeError(
                f"runner did NOT transition into {TARGET_STAGE} "
                f"(stage_transition={st!r}, stage_after="
                f"{move_report.get('stage_after')!r}) — cannot fire "
                f"stage_entered trigger"
            )

        # --- Step 2b: poll for the workflow execution (DB authority) ---
        print(
            f"\n[poll] waiting up to {POLL_TIMEOUT_S}s for the workflow "
            f"cron to pick up STAGE_ENTERED and run the execution..."
        )
        exec_report = await _poll_execution(
            factory, workflow_id=workflow_id, conversation_id=conversation_id
        )
        print("\n[execution] ===== workflow_executions + action_runs =====")
        print(json.dumps(exec_report, ensure_ascii=False, indent=2, default=str))

        # The UI's own endpoint too.
        r_ex = client.get(f"/api/v1/workflows/{workflow_id}/executions")
        api_execs = r_ex.json() if r_ex.status_code == 200 else None
        exec_report["api_executions_status"] = r_ex.status_code
        exec_report["api_executions"] = (
            [
                {
                    "id": e.get("id"),
                    "status": e.get("status"),
                    "conversation_id": e.get("conversation_id"),
                    "current_node_id": e.get("current_node_id"),
                    "error": e.get("error"),
                }
                for e in api_execs
            ]
            if isinstance(api_execs, list)
            else api_execs
        )
        print(
            f"[execution] GET /workflows/{{id}}/executions -> "
            f"{r_ex.status_code}: {exec_report['api_executions']}"
        )
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"
        print(f"\n[run] ABORTED: {run_error}")
    finally:
        if conversation_id is not None and customer_id is not None:
            clean_session = factory()
            try:
                cleanup_report = await _cleanup(
                    clean_session,
                    workflow_id=workflow_id,
                    conversation_id=conversation_id,
                    customer_id=customer_id,
                )
            finally:
                await clean_session.close()
            print("\n[cleanup] ===== residue + baseline verification =====")
            print(json.dumps(cleanup_report, ensure_ascii=False, indent=2, default=str))
        elif workflow_id:
            # Seed never happened but workflow exists — still delete it.
            clean_session = factory()
            try:
                from sqlalchemy import text

                await clean_session.execute(
                    text("DELETE FROM workflows WHERE id = :w AND tenant_id = :t"),
                    {"w": workflow_id, "t": TENANT_ID},
                )
                await clean_session.commit()
            finally:
                await clean_session.close()
            print(f"\n[cleanup] workflow {workflow_id} deleted (no seed to clean)")

    # ---- structured result + verdict ----
    exec_row = (exec_report or {}).get("execution_row") or {}
    action_runs = (exec_report or {}).get("action_runs") or []
    action_node_ids = {a.get("node_id") for a in action_runs}
    ok_workflow = (
        wf_report.get("create_status") == 201
        and wf_report.get("publish_status") == 200
        and (wf_report.get("readback") or {}).get("active") is True
    )
    ok_trigger = bool(
        move_report.get("stage_transition")
        and str(move_report["stage_transition"]).endswith(f"->{TARGET_STAGE}")
    )
    ok_execution = (
        exec_report.get("terminal") is True
        and exec_row.get("status") in ("completed", "failed")
        and {"assign_1", "note_1"}.issubset(action_node_ids)
    )
    ok_execution_clean = (
        ok_execution and exec_row.get("status") == "completed"
    )
    ok_cleanup = (
        cleanup_report.get("all_residual_zero") is True
        and cleanup_report.get("tenant_at_baseline") is True
    )

    move_cost = Decimal(move_report.get("cost_usd") or "0")
    if run_error is None and ok_workflow and ok_trigger and ok_execution_clean and ok_cleanup:
        verdict = "PASS"
    elif ok_workflow and ok_trigger and ok_execution and ok_cleanup:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    print("\n[task6] ===== STRUCTURED RESULT =====")
    print(
        json.dumps(
            {
                "workflow_id": workflow_id,
                "workflow": wf_report,
                "stage_move": move_report,
                "execution": exec_report,
                "cleanup": cleanup_report,
                "run_error": run_error,
                "real_cost_usd": str(move_cost),
                "checks": {
                    "ok_workflow": ok_workflow,
                    "ok_trigger": ok_trigger,
                    "ok_execution": ok_execution,
                    "ok_execution_clean": ok_execution_clean,
                    "ok_cleanup": ok_cleanup,
                },
                "verdict": verdict,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )[:14000]
    )
    print(
        f"\n[task6] workflow={'OK' if ok_workflow else 'FAIL'} "
        f"trigger={'OK' if ok_trigger else 'FAIL'} "
        f"execution={'OK' if ok_execution else 'FAIL'} "
        f"cleanup={'OK' if ok_cleanup else 'FAIL'} "
        f"real_cost=${move_cost} verdict={verdict}"
    )
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())

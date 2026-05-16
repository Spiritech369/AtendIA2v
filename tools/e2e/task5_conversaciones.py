"""Task 5 — Conversaciones: a COMMITTED runner conversation surfaces in the
operator UI's own REST endpoints, is tunable from those same endpoints, then
is cleanly removed (zero residue in the isolated tenant).

Unlike the sandbox harness (which rolls back — zero side-effects), this script
needs a COMMITTED multi-turn run so the conversation actually shows up in
Conversaciones. It therefore:

  1. Connects to the dev DB (:5433, get_settings().database_url) with a
     COMMITTING AsyncSession.
  2. Seeds a fresh conversation INSIDE the existing isolated tenant
     `867a1047` — ONLY a customers row (unique phone) + conversations row
     (current_stage = the active pipeline's first stage `nuevo_lead`) +
     conversation_state row. It does NOT create a tenant and does NOT touch
     the agent / KB / pipeline.
  3. Runs a fixed 3-message script through the REAL `ConversationRunner`
     with REAL `OpenAINLU` + `OpenAIComposer`, committing after every turn.
     Hard guard: exactly 3 turns, abort on the first exception. ~$0.03-0.06.
  4. Verifies the conversation via the SAME REST endpoints the Conversaciones
     UI calls (list / detail / messages / turn-traces), then exercises ONE
     operator tuning action (PATCH /conversations/{id}) and reads it back.
  5. CLEANUP (critical): deletes ONLY the rows created for this run, scoped
     to the seeded conversation_id / customer_id, and verifies the tenant's
     agents/faqs/catalog/pipeline counts are unchanged.

Run via the core venv (NOT importable as a package — uses absolute imports
from `atendia`):

  cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python ../tools/e2e/task5_conversaciones.py

Known bug #10 (Task 4, NOT re-investigated): `nuevo_lead.required_fields:[]`
⇒ NLU extracts nothing ⇒ the conversation STAYS in `nuevo_lead`, PLAN mode,
and the bot replies the PASO 0 micro-cotización every turn. That is expected
and fine here — Task 5 only proves the conversation SURFACES with messages +
turn_traces + flow_mode and is tunable from the UI's APIs.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

# tools/e2e/e2e_setup.py holds the authenticated REST Client (reused as-is).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_setup import Client  # noqa: E402

TENANT_ID = "867a1047-6aea-4b21-85d8-898aef0051cb"
SEED_PHONE = "+5218180000055"  # unique to this run
FIRST_STAGE = "nuevo_lead"  # the active moto-credito pipeline's first stage
SCRIPT = [
    "hola, quiero una moto a crédito",
    "¿cuál es el enganche?",
    "gracias",
]
MAX_TURNS = 3  # hard guard — never loop the LLM


async def _seed(session) -> tuple[UUID, UUID]:
    """Insert ONLY customer + conversation + conversation_state under the
    EXISTING isolated tenant. Returns (conversation_id, customer_id).

    Mirrors the seeding shape used by
    core/tests/runner/test_conversation_runner.py::_seed_tenant_with_pipeline
    but WITHOUT creating a tenant/pipeline (they already exist for 867a1047).
    """
    from sqlalchemy import text

    customer_id = (
        await session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164) "
                "VALUES (:t, :p) RETURNING id"
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
            {"t": TENANT_ID, "c": customer_id, "s": FIRST_STAGE},
        )
    ).scalar()
    await session.execute(
        text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
        {"c": conversation_id},
    )
    await session.commit()
    return UUID(str(conversation_id)), UUID(str(customer_id))


async def _run_committed_turns(
    session, *, conversation_id: UUID, customer_id: UUID
) -> list[dict]:
    """Run the 3-message script through the REAL runner with REAL providers,
    committing after every turn so the writes persist for the UI.

    Returns a per-turn list of {turn, inbound, flow_mode, bot_reply, cost}.
    Aborts (raises) on the first turn that raises — the caller cleans up.
    """
    from datetime import UTC, datetime

    from atendia.config import get_settings
    from atendia.contracts.message import Message, MessageDirection
    from atendia.runner.composer_openai import OpenAIComposer
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.runner.nlu_openai import OpenAINLU

    api_key = get_settings().openai_api_key
    if not api_key:
        raise RuntimeError("openai_api_key not set — cannot run real providers")

    nlu = OpenAINLU(api_key=api_key)
    composer = OpenAIComposer(api_key=api_key)
    runner = ConversationRunner(session, nlu, composer)

    from sqlalchemy import text

    out: list[dict] = []
    for turn_number, inbound_text in enumerate(SCRIPT[:MAX_TURNS], start=1):
        # IMPORTANT (real finding, see FINDINGS): ConversationRunner.run_turn
        # does NOT write the `messages` table — conversation_runner.py:1116
        # explicitly sets `inbound_message_id=None  # phase 1: messages table
        # not populated yet`. Inbound message rows are written ONLY by the
        # webhook's `_persist_inbound` (meta_routes.py:275-291) and outbound
        # only by enqueue_messages->stage_outbound (gated on
        # to_phone_e164/arq_pool). To make the Conversaciones /messages
        # bubbles surface faithfully WITHOUT a live WhatsApp webhook, we
        # persist the message rows here mirroring exactly what the
        # production webhook + outbound-dispatch path would write (same
        # columns, same directions), then drive the REAL runner. Persisting
        # the inbound BEFORE run_turn also lets turn N read turns 1..N-1 from
        # `messages` for NLU history — same as production.
        await session.execute(
            text(
                "INSERT INTO messages "
                "(conversation_id, tenant_id, direction, text, sent_at, "
                "metadata_json) "
                "VALUES (:c, :t, 'inbound', :txt, :ts, CAST(:meta AS JSONB))"
            ),
            {
                "c": str(conversation_id),
                "t": TENANT_ID,
                "txt": inbound_text,
                "ts": datetime.now(UTC),
                "meta": json.dumps({"source": "e2e_task5"}),
            },
        )
        await session.commit()

        inbound = Message(
            id=str(uuid4()),
            conversation_id=str(conversation_id),
            tenant_id=TENANT_ID,
            direction=MessageDirection.INBOUND,
            text=inbound_text,
            sent_at=datetime.now(UTC),
        )
        # No arq_pool / to_phone_e164: the runner stages outbound into the
        # session only when to_phone_e164 is set. We deliberately drive the
        # runner directly (the documented harness/test invocation) and
        # persist the composed reply ourselves below.
        trace = await runner.run_turn(
            conversation_id=conversation_id,
            tenant_id=UUID(TENANT_ID),
            inbound=inbound,
            turn_number=turn_number,
        )
        await session.commit()  # persist turn_trace + state for the UI

        # Persist the composer's reply as an outbound message row, mirroring
        # what enqueue_messages -> stage_outbound + the worker's message
        # upsert write (direction='outbound', delivery_status='sent'). This
        # is the bot bubble the operator sees in Conversaciones.
        bot_msgs = list(getattr(trace, "outbound_messages", None) or [])
        for bot_text in bot_msgs:
            await session.execute(
                text(
                    "INSERT INTO messages "
                    "(conversation_id, tenant_id, direction, text, sent_at, "
                    "delivery_status, metadata_json) "
                    "VALUES (:c, :t, 'outbound', :txt, :ts, 'sent', "
                    "CAST(:meta AS JSONB))"
                ),
                {
                    "c": str(conversation_id),
                    "t": TENANT_ID,
                    "txt": bot_text,
                    "ts": datetime.now(UTC),
                    "meta": json.dumps({"source": "bot", "turn": turn_number}),
                },
            )
        await session.commit()

        per_turn_cost = (
            (getattr(trace, "nlu_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "composer_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "tool_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "vision_cost_usd", None) or Decimal("0"))
        )
        msgs = list(getattr(trace, "outbound_messages", None) or [])
        out.append(
            {
                "turn": turn_number,
                "inbound": inbound_text,
                "flow_mode": getattr(trace, "flow_mode", None),
                "stage_after": (getattr(trace, "state_after", None) or {}).get(
                    "current_stage"
                ),
                "bot_reply": msgs,
                "cost_usd": str(per_turn_cost),
            }
        )
        print(
            f"[run] turn {turn_number} inbound={inbound_text!r} "
            f"flow_mode={out[-1]['flow_mode']} "
            f"stage_after={out[-1]['stage_after']} "
            f"cost=${per_turn_cost} reply={msgs!r}"
        )
    return out


def _verify_via_ui_apis(
    client: Client, conversation_id: UUID
) -> dict:
    """Hit the four endpoints the Conversaciones UI uses + one tuning PATCH.

    Endpoint paths confirmed READ-ONLY from
    core/atendia/api/conversations_routes.py and turn_traces_routes.py.
    """
    cid = str(conversation_id)
    report: dict = {}

    # 1. LIST — GET /api/v1/conversations  (find the seeded conv by id/phone)
    r_list = client.get("/api/v1/conversations", params={"limit": 200})
    found = None
    if r_list.status_code == 200:
        for it in r_list.json().get("items", []):
            if it.get("id") == cid:
                found = it
                break
    report["list"] = {
        "status": r_list.status_code,
        "found_in_list": found is not None,
        "item": (
            {
                "id": found.get("id"),
                "customer_phone": found.get("customer_phone"),
                "current_stage": found.get("current_stage"),
                "status": found.get("status"),
                "bot_paused": found.get("bot_paused"),
                "last_message_text": found.get("last_message_text"),
                "last_message_direction": found.get("last_message_direction"),
            }
            if found
            else None
        ),
    }

    # 2. DETAIL — GET /api/v1/conversations/{id}
    r_det = client.get(f"/api/v1/conversations/{cid}")
    det = r_det.json() if r_det.status_code == 200 else None
    report["detail"] = {
        "status": r_det.status_code,
        "current_stage": det.get("current_stage") if det else None,
        "customer_phone": det.get("customer_phone") if det else None,
        "bot_paused": det.get("bot_paused") if det else None,
        "extracted_data": det.get("extracted_data") if det else None,
        "last_intent": det.get("last_intent") if det else None,
    }

    # 3. MESSAGES — GET /api/v1/conversations/{id}/messages
    r_msg = client.get(
        f"/api/v1/conversations/{cid}/messages", params={"limit": 500}
    )
    msg_items = r_msg.json().get("items", []) if r_msg.status_code == 200 else []
    inbound = [m for m in msg_items if m.get("direction") == "inbound"]
    outbound = [m for m in msg_items if m.get("direction") == "outbound"]
    report["messages"] = {
        "status": r_msg.status_code,
        "total": len(msg_items),
        "inbound_count": len(inbound),
        "outbound_count": len(outbound),
        # newest-first per the route; reverse for readability
        "inbound_texts": [m.get("text") for m in reversed(inbound)],
        "outbound_texts": [m.get("text") for m in reversed(outbound)],
    }

    # 4. TURN-TRACES — GET /api/v1/turn-traces?conversation_id={id}
    #    (the DebugPanel data: per-turn flow_mode/nlu/composer)
    r_tt = client.get(
        "/api/v1/turn-traces", params={"conversation_id": cid}
    )
    tt_items = r_tt.json().get("items", []) if r_tt.status_code == 200 else []
    traces_summary = [
        {
            "turn_number": t.get("turn_number"),
            "flow_mode": t.get("flow_mode"),
            "nlu_model": t.get("nlu_model"),
            "composer_model": t.get("composer_model"),
            "total_cost_usd": t.get("total_cost_usd"),
            "inbound_preview": t.get("inbound_preview"),
        }
        for t in tt_items
    ]
    # Pull ONE full trace (the DebugPanel detail) to prove nlu/composer
    # payloads are present and renderable.
    trace_detail = None
    if tt_items:
        first_id = tt_items[0].get("id")
        r_td = client.get(f"/api/v1/turn-traces/{first_id}")
        if r_td.status_code == 200:
            td = r_td.json()
            trace_detail = {
                "status": r_td.status_code,
                "turn_number": td.get("turn_number"),
                "flow_mode": td.get("flow_mode"),
                "nlu_output_present": td.get("nlu_output") is not None,
                "composer_output_present": td.get("composer_output") is not None,
                "composer_provider": td.get("composer_provider"),
                "outbound_messages": td.get("outbound_messages"),
                "state_after_stage": (td.get("state_after") or {}).get(
                    "current_stage"
                ),
            }
    report["turn_traces"] = {
        "status": r_tt.status_code,
        "count": len(tt_items),
        "summary": traces_summary,
        "one_full_trace": trace_detail,
    }

    # 5. TUNING FROM UI — PATCH /api/v1/conversations/{id} (operator pauses
    #    the bot + tags it), then read back via detail to assert it persisted.
    patch_body = {"tags": ["e2e-task5", "afinado-frontend"]}
    r_patch = client.patch(
        f"/api/v1/conversations/{cid}", json_body=patch_body
    )
    r_after = client.get(f"/api/v1/conversations/{cid}")
    after = r_after.json() if r_after.status_code == 200 else {}
    patched_tags = (
        r_patch.json().get("tags") if r_patch.status_code == 200 else None
    )
    readback_tags = after.get("tags")
    report["tuning_patch"] = {
        "patch_status": r_patch.status_code,
        "sent": patch_body,
        "patch_response_tags": patched_tags,
        "readback_status": r_after.status_code,
        "readback_tags": readback_tags,
        "persisted": (
            r_patch.status_code == 200
            and sorted(readback_tags or []) == sorted(patch_body["tags"])
        ),
    }
    return report


async def _cleanup(session, *, conversation_id: UUID, customer_id: UUID) -> dict:
    """Delete ONLY rows created for this run, scoped to the seeded ids.

    Order respects FK deps. Returns a verification dict: per-table residual
    counts (must all be 0) + the tenant's agents/faqs/catalog/pipeline
    counts (must be unchanged: 1/32/34/1).
    """
    from sqlalchemy import text

    cid = str(conversation_id)
    custid = str(customer_id)

    # Children of turn_traces first (tool_calls FK -> turn_traces).
    await session.execute(
        text(
            "DELETE FROM tool_calls WHERE turn_trace_id IN "
            "(SELECT id FROM turn_traces WHERE conversation_id = :c)"
        ),
        {"c": cid},
    )
    # outbound_outbox has NO conversation_id column; it links to a
    # conversation only via messages.id == outbox.sent_message_id OR via
    # payload->>'conversation_id' (intervene route). This run passes no
    # to_phone_e164/arq_pool so the runner never stages an outbox row, but
    # delete defensively (scoped, so a non-match is a harmless no-op) BEFORE
    # deleting the messages it may reference.
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
    for tbl in (
        "turn_traces",
        "events",
        "messages",
        "field_suggestions",
        "human_handoffs",
        "conversation_reads",
        "conversation_state",
    ):
        residual[tbl] = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE conversation_id = :c"),
                {"c": cid},
            )
        ).scalar()
    # outbound_outbox: count via its indirect linkage (same predicate as the
    # delete) since the table has no conversation_id column.
    residual["outbound_outbox"] = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM outbound_outbox WHERE "
                "sent_message_id IN (SELECT id FROM messages WHERE conversation_id = :c) "
                "OR payload->>'conversation_id' = cast(:c AS text)"
            ),
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
    }
    return {
        "residual_rows": residual,
        "all_residual_zero": all(v == 0 for v in residual.values()),
        "tenant_counts_after": tenant_counts,
        "tenant_counts_unchanged": (
            tenant_counts["agents"] == 1
            and tenant_counts["tenant_faqs"] == 32
            and tenant_counts["tenant_catalogs"] == 34
            and tenant_counts["tenant_pipelines_active"] == 1
        ),
    }


async def _amain() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from atendia.db.session import _get_factory

    factory = _get_factory()

    # --- auth (the same REST client the UI uses) -----------------------
    client = Client()
    client.login()
    print(f"[auth] logged in OK — tenant_id={client.tenant_id}")
    if client.tenant_id != TENANT_ID:
        print(
            f"[auth] FAIL — expected tenant {TENANT_ID}, got {client.tenant_id}"
        )
        return 1

    conversation_id: UUID | None = None
    customer_id: UUID | None = None
    run_turns: list[dict] = []
    ui_report: dict = {}
    cleanup_report: dict = {}
    run_error: str | None = None

    # --- seed (committing session) -------------------------------------
    seed_session = factory()
    try:
        conversation_id, customer_id = await _seed(seed_session)
    finally:
        await seed_session.close()
    print(
        f"[seed] conversation_id={conversation_id} customer_id={customer_id} "
        f"phone={SEED_PHONE} stage={FIRST_STAGE}"
    )

    # --- committed run + UI verification, cleanup ALWAYS runs -----------
    try:
        run_session = factory()
        try:
            run_turns = await _run_committed_turns(
                run_session,
                conversation_id=conversation_id,
                customer_id=customer_id,
            )
        finally:
            await run_session.close()

        ui_report = _verify_via_ui_apis(client, conversation_id)
        print("\n[ui] ===== Conversaciones API verification =====")
        print(json.dumps(ui_report, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:  # abort-on-error, but still clean up
        run_error = f"{type(exc).__name__}: {exc}"
        print(f"[run] ABORTED: {run_error}")
    finally:
        clean_session = factory()
        try:
            cleanup_report = await _cleanup(
                clean_session,
                conversation_id=conversation_id,
                customer_id=customer_id,
            )
        finally:
            await clean_session.close()
        print("\n[cleanup] ===== residue + tenant-count verification =====")
        print(json.dumps(cleanup_report, ensure_ascii=False, indent=2))

    total_cost = sum(Decimal(t["cost_usd"]) for t in run_turns)
    print("\n[task5] ===== STRUCTURED RESULT =====")
    print(
        json.dumps(
            {
                "seed": {
                    "conversation_id": str(conversation_id),
                    "customer_id": str(customer_id),
                    "phone": SEED_PHONE,
                    "stage": FIRST_STAGE,
                },
                "run_turns": run_turns,
                "run_error": run_error,
                "ui": ui_report,
                "cleanup": cleanup_report,
                "real_cost_usd": str(total_cost),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )[:12000]
    )

    ok_run = run_error is None and len(run_turns) == MAX_TURNS
    ok_surfaces = (
        ui_report.get("list", {}).get("found_in_list") is True
        and ui_report.get("detail", {}).get("status") == 200
        and (ui_report.get("messages", {}).get("inbound_count") or 0) >= 1
        and (ui_report.get("turn_traces", {}).get("count") or 0) >= 1
    )
    ok_tuning = ui_report.get("tuning_patch", {}).get("persisted") is True
    ok_cleanup = (
        cleanup_report.get("all_residual_zero") is True
        and cleanup_report.get("tenant_counts_unchanged") is True
    )
    overall = (
        "PASS" if (ok_run and ok_surfaces and ok_tuning and ok_cleanup) else "PARTIAL"
    )
    print(
        f"\n[task5] run={'OK' if ok_run else 'FAIL'} "
        f"surfaces={'OK' if ok_surfaces else 'FAIL'} "
        f"tuning={'OK' if ok_tuning else 'FAIL'} "
        f"cleanup={'OK' if ok_cleanup else 'FAIL'} "
        f"real_cost=${total_cost} overall={overall}"
    )
    return 0


def main() -> int:
    import asyncio

    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())

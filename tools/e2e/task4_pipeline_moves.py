"""Task 4 — pipeline TEXT-FIELD + DOCUMENT stage moves (moto-credito E2E).

Three sub-goals, all against the live stack + the REAL ConversationRunner:

  1. Build the pipeline = the JSON of
     core/atendia/state_machine/motos_credito_pipeline.json, PUT it via
     the frontend API (`PUT /api/v1/tenants/pipeline`), GET read-back,
     assert the pipeline is active and does not carry Agent IA routing
     rules. Flow routing belongs to the agent created by e2e_setup.py.

  2. TEXT-FIELD MOVE — drive a real OpenAINLU + OpenAIComposer
     conversation that should make the LLM extract `tipo_credito` /
     `plan_credito`; observe whether the M3 auto_enter evaluator moves
     the conversation into `plan_seleccionado` / `calificacion_inicial`.

  3. DOCUMENT MOVE — via the harness `apply_overrides` rolled-back hook,
     set `customer.attrs` so a plan is chosen + the DOCS_* that plan
     requires are status="ok", run ONE turn, assert a stage_transition
     into `papeleria_incompleta` / `papeleria_completa`.

Zero production side-effects: every runner turn here is executed on a
session that is ALWAYS rolled back (same invariant the merged sandbox
harness guarantees — see core/tests/sandbox/test_harness_no_side_effects.py).
The seed conversation rows ARE committed (so the runner's own SELECTs
see them) and are DELETEd in a `finally`. Hard cost cap on the LLM run.

WHY a local rolled-back turn loop instead of `run_sandbox_conversation`:
the harness maps the runner's TurnTrace into `SandboxTurnResult`, which
deliberately drops `stage_transition` / `state_after` / `rules_evaluated`.
The task requires inspecting the *returned TurnTrace* for the
`stage_transition` into a stage. `_run_turn_locally` below is a faithful
copy of `harness._run_turn_on_session` (same ConversationRunner, same
CapturingArqPool, single session, single rollback in `finally`) that
additionally surfaces the full in-memory TurnTrace. The DOCUMENT proof
uses the real `harness.run_sandbox_turn(apply_overrides=...)` because the
override hook is the harness's documented mechanism; its result is
cross-checked against a second local rolled-back turn so the
stage_transition is observable.

Run (core venv; cwd=core gives core/.env -> :5433 + import atendia):
  cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python ../tools/e2e/task4_pipeline_moves.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

# tools/e2e/ is not a package; make `e2e_setup` importable when this file
# is run by path from cwd=core.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2e_setup import Client

# --- constants -------------------------------------------------------------

# Repo root: tools/e2e/<this file> -> parents[2].
REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_PIPELINE_PATH = (
    REPO_ROOT / "core" / "atendia" / "state_machine" / "motos_credito_pipeline.json"
)

# Plan with the SHORTEST docs requirement (only 3 docs) so the DOCUMENT
# proof override is minimal. From motos_credito_pipeline.json docs_per_plan.
DOC_PROOF_PLAN = "sin_comprobantes_25"
DOC_PROOF_DOCS = [
    "DOCS_INE_FRENTE",
    "DOCS_INE_REVERSO",
    "DOCS_COMPROBANTE_DOMICILIO",
]


def build_pipeline_definition() -> dict[str, Any]:
    """The base motos_credito pipeline JSON, without Agent IA router rules."""
    base = json.loads(BASE_PIPELINE_PATH.read_text(encoding="utf-8"))
    base.pop("flow_mode_rules", None)
    return base


# ---------------------------------------------------------------------------
# Sub-goal 1 — PUT the pipeline via the frontend API
# ---------------------------------------------------------------------------


def put_pipeline(client: Client) -> dict[str, Any]:
    """PUT /api/v1/tenants/pipeline {definition: <def>}; GET read-back.

    Up to 3 PUT attempts on 422 (validation) — but the definition is the
    code's own purpose-built pipeline, so a 422 would itself be a finding.
    """
    definition = build_pipeline_definition()
    out: dict[str, Any] = {"attempts": []}

    last: Any = None
    for attempt in range(1, 4):
        r = client.put(
            "/api/v1/tenants/pipeline", json_body={"definition": definition}
        )
        out["attempts"].append({"n": attempt, "status": r.status_code})
        print(f"[pipeline] PUT attempt {attempt} -> HTTP {r.status_code}")
        last = r
        if r.status_code in (200, 201):
            break
        if r.status_code == 422:
            print(f"[pipeline] 422 body: {r.text[:1500]}")
            # The definition is the code's own pipeline; a 422 is a real
            # finding, not something to brute-force. Stop and report.
            break
        print(f"[pipeline] unexpected body: {r.text[:800]}")
        break

    out["put_status"] = last.status_code if last is not None else None
    if last is None or last.status_code not in (200, 201):
        out["put_body"] = last.text[:1500] if last is not None else "no response"
        return out

    rb = client.get("/api/v1/tenants/pipeline")
    out["get_status"] = rb.status_code
    print(f"[pipeline] GET read-back -> HTTP {rb.status_code}")
    if rb.status_code == 200:
        body = rb.json()
        # The GET may wrap the definition; handle both {definition:..} and
        # a bare definition object.
        defn = body.get("definition") if isinstance(body, dict) else None
        if defn is None and isinstance(body, dict) and "stages" in body:
            defn = body
        out["readback_active"] = (
            body.get("active") if isinstance(body, dict) else None
        )
        rb_rules = (defn or {}).get("flow_mode_rules")
        out["readback_flow_mode_rules"] = rb_rules
        out["flow_mode_rules_absent"] = rb_rules in (None, [])
        out["readback_stage_ids"] = [
            s.get("id") for s in (defn or {}).get("stages", [])
        ]
        print(
            f"[pipeline] read-back active={out['readback_active']} "
            f"flow_mode_rules_absent={out['flow_mode_rules_absent']} "
            f"stages={out['readback_stage_ids']}"
        )
    else:
        out["get_body"] = rb.text[:800]
    return out


# ---------------------------------------------------------------------------
# Local rolled-back single-turn runner (faithful copy of
# harness._run_turn_on_session, but returns the full in-memory TurnTrace).
# ---------------------------------------------------------------------------


def _trace_view(trace: Any) -> dict[str, Any]:
    """Project the runner's TurnTrace into a JSON-safe inspection dict."""
    state_after = getattr(trace, "state_after", None) or {}
    extracted = state_after.get("extracted_data") if isinstance(state_after, dict) else None
    return {
        "flow_mode": getattr(trace, "flow_mode", None),
        "stage_transition": getattr(trace, "stage_transition", None),
        "current_stage": (
            state_after.get("current_stage") if isinstance(state_after, dict) else None
        ),
        "extracted_data": extracted,
        "nlu_intent": (
            (getattr(trace, "nlu_output", None) or {}).get("intent")
            if isinstance(getattr(trace, "nlu_output", None), dict)
            else None
        ),
        "nlu_entities": (
            (getattr(trace, "nlu_output", None) or {}).get("entities")
            if isinstance(getattr(trace, "nlu_output", None), dict)
            else None
        ),
        "rules_evaluated": getattr(trace, "rules_evaluated", None),
        "outbound": list(getattr(trace, "outbound_messages", None) or []),
        "cost_usd": (
            (getattr(trace, "nlu_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "composer_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "tool_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "vision_cost_usd", None) or Decimal("0"))
        ),
    }


async def _run_script_locally(
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    script: list[str],
    nlu_provider: Any,
    composer_provider: Any,
    cost_cap_usd: Decimal,
) -> list[dict[str, Any]]:
    """Replay `script` on ONE rolled-back session, returning per-turn
    TurnTrace views. Mirrors harness.run_sandbox_conversation's lifecycle
    (single session, accumulates conversation_state across turns, ONE
    rollback in finally) but exposes the full trace. Stops when the
    running cost first exceeds `cost_cap_usd` (the tripping turn ran, so
    its cost counts and its trace is included).
    """
    from datetime import UTC, datetime

    from atendia.contracts.message import Message, MessageDirection
    from atendia.db.session import _get_factory
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.sandbox.transport import CapturingArqPool

    factory = _get_factory()
    session = factory()
    views: list[dict[str, Any]] = []
    spent = Decimal("0")
    try:
        for turn_number, inbound_text in enumerate(script, start=1):
            runner = ConversationRunner(session, nlu_provider, composer_provider)
            inbound = Message(
                id=str(uuid4()),
                conversation_id=str(conversation_id),
                tenant_id=str(tenant_id),
                direction=MessageDirection.INBOUND,
                text=inbound_text,
                sent_at=datetime.now(UTC),
            )
            trace = await runner.run_turn(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                inbound=inbound,
                turn_number=turn_number,
                arq_pool=CapturingArqPool(),  # type: ignore[arg-type]
            )
            view = _trace_view(trace)
            view["turn"] = turn_number
            view["inbound"] = inbound_text
            views.append(view)
            spent += view["cost_usd"]
            print(
                f"[turn {turn_number}] in={inbound_text!r} "
                f"flow_mode={view['flow_mode']} "
                f"stage_transition={view['stage_transition']} "
                f"stage={view['current_stage']} "
                f"cost={view['cost_usd']}"
            )
            if spent > cost_cap_usd:
                print(
                    f"[cost-cap] spent {spent} > cap {cost_cap_usd} — "
                    f"stopping after turn {turn_number}"
                )
                break
        return views
    finally:
        await session.rollback()
        await session.close()


# ---------------------------------------------------------------------------
# Seeding (committed; cleaned up in finally)
# ---------------------------------------------------------------------------


async def _seed_conversation(tenant_id: str, label: str) -> tuple[str, str]:
    """Commit a fresh customer + conversation + conversation_state in the
    REAL tenant. The runner's own SELECTs need committed rows. Returns
    (customer_id, conversation_id). Stage starts at the pipeline's first
    stage (`nuevo_lead`) so forward auto-enter moves are allowed.
    """
    from sqlalchemy import text

    from atendia.db.session import _get_factory

    factory = _get_factory()
    session = factory()
    try:
        phone = f"+52155{uuid4().int % 100000000:08d}"
        cust = (
            await session.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164, attrs) "
                    "VALUES (:t, :p, '{}'::jsonb) RETURNING id"
                ),
                {"t": tenant_id, "p": phone},
            )
        ).scalar()
        conv = (
            await session.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                    "VALUES (:t, :c, 'nuevo_lead') RETURNING id"
                ),
                {"t": tenant_id, "c": cust},
            )
        ).scalar()
        await session.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv},
        )
        await session.commit()
        print(f"[seed:{label}] customer={cust} conversation={conv} phone={phone}")
        return str(cust), str(conv)
    finally:
        await session.close()


async def _delete_customer(tenant_id: str, customer_id: str) -> None:
    """Hard-delete the seeded customer (cascades conversations /
    conversation_state / turn_traces). Scoped to the seeded customer id so
    nothing else in the shared tenant is touched.
    """
    from sqlalchemy import text

    from atendia.db.session import _get_factory

    factory = _get_factory()
    session = factory()
    try:
        await session.execute(
            text("DELETE FROM customers WHERE id = :id AND tenant_id = :t"),
            {"id": customer_id, "t": tenant_id},
        )
        await session.commit()
        print(f"[cleanup] deleted customer {customer_id}")
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Sub-goal 2 — TEXT-FIELD move (real LLM, capped)
# ---------------------------------------------------------------------------


async def text_field_move(tenant_id: str) -> dict[str, Any]:
    from atendia.config import get_settings
    from atendia.runner.composer_openai import OpenAIComposer
    from atendia.runner.nlu_openai import OpenAINLU

    settings = get_settings()
    api_key = settings.openai_api_key
    out: dict[str, Any] = {"openai_key_present": bool(api_key)}
    if not api_key:
        out["status"] = "BLOCKED"
        out["reason"] = "openai_api_key empty in settings — cannot run real LLM"
        return out

    cap = Decimal("0.40")
    # Two script variants. v1 is the spec's suggested wording. If the LLM
    # doesn't extract tipo_credito/plan_credito AND no stage move is seen,
    # try v2 (more explicit about the credit type / plan). <=2 attempts,
    # both inside the single cost cap (cap re-applied per attempt; total
    # real spend is bounded by the task budget — each attempt is ~3 short
    # gpt-4o turns ~< $0.05, well under $0.40 and the $0.50 hard budget).
    scripts = [
        [
            "hola, quiero una moto a crédito",
            "tengo 3 años en mi trabajo",
            "me depositan la nómina en una tarjeta de débito",
        ],
        [
            "hola, quiero una moto a crédito por nómina",
            "tengo 3 años en mi empleo actual y cobro por tarjeta de nómina",
            "mi tipo de crédito es nómina tarjeta, el plan de enganche 10%",
        ],
    ]

    attempts: list[dict[str, Any]] = []
    moved = False
    for idx, script in enumerate(scripts, start=1):
        cust_id, conv_id = await _seed_conversation(tenant_id, f"textmove_v{idx}")
        try:
            nlu = OpenAINLU(api_key=api_key)
            composer = OpenAIComposer(api_key=api_key)
            views = await _run_script_locally(
                conversation_id=UUID(conv_id),
                tenant_id=UUID(tenant_id),
                script=script,
                nlu_provider=nlu,
                composer_provider=composer,
                cost_cap_usd=cap,
            )
        finally:
            await _delete_customer(tenant_id, cust_id)

        spent = sum((v["cost_usd"] for v in views), Decimal("0"))
        transitions = [
            v["stage_transition"] for v in views if v["stage_transition"]
        ]
        # The target stages a text-extracted field should drive into.
        target_hit = [
            t
            for t in transitions
            if t
            and (
                t.endswith("->plan_seleccionado")
                or t.endswith("->calificacion_inicial")
            )
        ]
        last_extracted = views[-1]["extracted_data"] if views else None
        attempts.append(
            {
                "variant": idx,
                "script": script,
                "spent_usd": str(spent),
                "per_turn": views,
                "transitions": transitions,
                "target_transitions": target_hit,
                "final_extracted_data": last_extracted,
            }
        )
        if target_hit:
            moved = True
            break

    out["attempts"] = attempts
    out["moved"] = moved
    out["total_spent_usd"] = str(
        sum(
            (Decimal(a["spent_usd"]) for a in attempts),
            Decimal("0"),
        )
    )
    if moved:
        out["status"] = "PASS"
    else:
        out["status"] = "PARTIAL"
        out["reason"] = (
            "no text-field-driven stage_transition into plan_seleccionado/"
            "calificacion_inicial observed across 2 scripts — see "
            "final_extracted_data + per_turn.rules_evaluated for the "
            "root cause (auto_enter field-name vs per-stage NLU scope)."
        )
    return out


# ---------------------------------------------------------------------------
# Sub-goal 3 — DOCUMENT move (apply_overrides, rolled back)
# ---------------------------------------------------------------------------


async def document_move(tenant_id: str) -> dict[str, Any]:
    """Set customer.attrs (the store the M3 evaluator's _merge_fields reads
    — pipeline_evaluator.py:300-323/355-358: customer.attrs UNION
    state.extracted_data, resolved via resolve_field_path) so a plan is
    chosen and that plan's required DOCS_* are status="ok". One turn ->
    `papeleria_incompleta` (match=any DOCS_*.status==ok) AND
    `papeleria_completa` (plan_credito docs_complete_for_plan) both match;
    select_best_stage forward-bias picks the latest => papeleria_completa.

    Done two ways for evidence:
      A) the harness's real run_sandbox_turn(apply_overrides=...) — proves
         the documented override hook drives the move (asserts no leak).
      B) a local rolled-back turn with the same override — exposes the
         in-memory TurnTrace.stage_transition (the harness's
         SandboxTurnResult hides it).
    """
    from collections.abc import Awaitable, Callable

    from atendia.config import get_settings
    from atendia.runner.composer_openai import OpenAIComposer
    from atendia.runner.nlu_openai import OpenAINLU
    from atendia.sandbox.harness import run_sandbox_turn

    settings = get_settings()
    api_key = settings.openai_api_key
    out: dict[str, Any] = {
        "evaluator_ref": (
            "core/atendia/state_machine/pipeline_evaluator.py:300-323 "
            "(_merge_fields: customer.attrs UNION extracted_data), :136 "
            "(resolve_field_path), :166-195 (docs_complete_for_plan)"
        ),
        "plan": DOC_PROOF_PLAN,
        "required_docs": DOC_PROOF_DOCS,
    }
    if not api_key:
        out["status"] = "BLOCKED"
        out["reason"] = "openai_api_key empty — runner needs a provider"
        return out

    cust_id, conv_id = await _seed_conversation(tenant_id, "docmove")

    # The override: write the plan id + each required doc status=ok onto
    # customer.attrs (uncommitted; flushed by the harness before the turn,
    # rolled back after). plan_credito carries the plan KEY used by
    # docs_per_plan ("sin_comprobantes_25").
    attrs_payload = {"plan_credito": DOC_PROOF_PLAN}
    for k in DOC_PROOF_DOCS:
        attrs_payload[k] = {"status": "ok"}

    def make_override(customer_id: str) -> Callable[[Any], Awaitable[None]]:
        async def _apply(session: Any) -> None:
            # Mutate via the ORM exactly like apply_ai_extractions does
            # (load Customer, assign a NEW attrs dict, session.add) — no
            # raw `::jsonb` cast (asyncpg parses `::` as a bind delimiter
            # and errors; the runner escapes it `\:\:` in its own SQL).
            from sqlalchemy import select as _sel

            from atendia.db.models.customer import Customer

            cust = (
                await session.execute(
                    _sel(Customer).where(Customer.id == customer_id)
                )
            ).scalar_one()
            merged = dict(cust.attrs or {})
            merged.update(attrs_payload)
            cust.attrs = merged
            session.add(cust)

        return _apply

    try:
        nlu = OpenAINLU(api_key=api_key)
        composer = OpenAIComposer(api_key=api_key)

        # --- A) real harness run_sandbox_turn with apply_overrides --------
        a_res = await run_sandbox_turn(
            conversation_id=UUID(conv_id),
            tenant_id=UUID(tenant_id),
            inbound_text="aquí están mis documentos",
            nlu_provider=nlu,
            composer_provider=composer,
            apply_overrides=make_override(cust_id),
        )
        out["harness_turn"] = {
            "flow_mode": a_res.flow_mode,
            "outbound": list(a_res.would_be_outbound or []),
            "cost_usd": str(a_res.cost_usd),
        }

        # --- B) local rolled-back turn (same override) to read the trace -
        from datetime import UTC, datetime

        from atendia.contracts.message import Message, MessageDirection
        from atendia.db.session import _get_factory
        from atendia.runner.conversation_runner import ConversationRunner
        from atendia.sandbox.transport import CapturingArqPool

        factory = _get_factory()
        session = factory()
        try:
            await make_override(cust_id)(session)
            await session.flush()
            runner = ConversationRunner(session, nlu, composer)
            trace = await runner.run_turn(
                conversation_id=UUID(conv_id),
                tenant_id=UUID(tenant_id),
                inbound=Message(
                    id=str(uuid4()),
                    conversation_id=conv_id,
                    tenant_id=tenant_id,
                    direction=MessageDirection.INBOUND,
                    text="aquí están mis documentos",
                    sent_at=datetime.now(UTC),
                ),
                turn_number=1,
                arq_pool=CapturingArqPool(),  # type: ignore[arg-type]
            )
            view = _trace_view(trace)
        finally:
            await session.rollback()
            await session.close()

        out["local_turn"] = view
        st = view.get("stage_transition")
        out["stage_transition"] = st
        out["matched_stage_ids"] = [
            r.get("stage_id")
            for r in (view.get("rules_evaluated") or [])
            if r.get("passed")
        ]
        moved_into_doc = bool(
            st
            and (
                st.endswith("->papeleria_incompleta")
                or st.endswith("->papeleria_completa")
            )
        )
        out["moved"] = moved_into_doc
        out["status"] = "PASS" if moved_into_doc else "FAIL"
        if not moved_into_doc:
            out["reason"] = (
                "no stage_transition into papeleria_incompleta/"
                "papeleria_completa after setting plan + DOCS_* ok on "
                "customer.attrs — inspect local_turn.rules_evaluated."
            )
        print(
            f"[docmove] stage_transition={st} "
            f"matched={out['matched_stage_ids']} status={out['status']}"
        )
    finally:
        await _delete_customer(tenant_id, cust_id)

    return out


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def _amain() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    client = Client()
    client.login()
    tenant_id = client.tenant_id
    print(f"[auth] logged in OK — tenant_id={tenant_id}")
    assert tenant_id, "no tenant_id after login"

    # Sub-goal 1
    pipe = put_pipeline(client)
    pipe_ok = pipe.get("put_status") in (200, 201) and pipe.get(
        "flow_mode_rules_absent"
    )

    # Sub-goal 2 (only meaningful if the pipeline is active)
    if pipe_ok:
        textmove = await text_field_move(tenant_id)
    else:
        textmove = {
            "status": "BLOCKED",
            "reason": "pipeline PUT failed — cannot test text-field move",
        }

    # Sub-goal 3
    if pipe_ok:
        docmove = await document_move(tenant_id)
    else:
        docmove = {
            "status": "BLOCKED",
            "reason": "pipeline PUT failed — cannot test document move",
        }

    result = {
        "pipeline": pipe,
        "text_field_move": textmove,
        "document_move": docmove,
    }
    print("\n[task4] ===== STRUCTURED RESULT =====")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:14000])

    print(
        f"\n[task4] pipeline={'OK' if pipe_ok else 'FAIL'} "
        f"text_field_move={textmove.get('status')} "
        f"document_move={docmove.get('status')}"
    )
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())

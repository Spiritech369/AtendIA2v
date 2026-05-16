"""$0 empirical probe of the inbound->process->outbound pipeline order.

Task 1 of the moto-credito E2E validation. This script does NOT trace by
reading code (that's the FINDINGS doc); it *confirms the order empirically*
by running the REAL ConversationRunner once through the merged sandbox
harness with FAKE providers — so it costs $0 and persists nothing (the
harness rolls the session back; see core/atendia/sandbox/harness.py).

What it proves:
  - The runner reaches the Composer only AFTER NLU + flow_router, i.e. one
    `run_sandbox_turn` returns a result whose `flow_mode` is set (router
    ran), `nlu_output` is populated (NLU ran), and `composer_output` is
    populated (Composer ran) — with NO exception. If the composer ran
    before NLU the runner would have crashed (NLU output drives
    process_turn -> decision.action which gates the composer).

Prediction (TDD-spirit, asserted below). Two of these were initially
mispredicted and corrected after the first run — kept honest here:
  - _FakeNLUWithCost -> Intent.GREETING; PIPELINE_QUALIFY_QUOTE has no
    `flow_mode_rules` key, so the router uses its default `always->SUPPORT`
    fallback => flow_mode == "SUPPORT". (FlowMode is a str-Enum whose
    *value* is upper-case "SUPPORT" — flow_mode.py:18; TurnTrace stores
    `flow_mode.value` — conversation_runner.py:1153. Initially predicted
    lowercase "support"; corrected.)
  - nlu_output is a dict (TurnTrace.nlu_output = nlu.model_dump).
  - composer_output is a dict carrying the _RecordingComposer messages.
  - would_be_outbound carries the composed messages. (SandboxTurnResult
    .would_be_outbound reads trace.outbound_messages, which the runner
    sets to composer_output.messages unconditionally at
    conversation_runner.py:1154 — independent of to_phone_e164, which
    only gates the *real* arq enqueue/outbox stage at line 1169.
    Initially predicted empty; corrected.)

Run:
  cd "C:/Users/Sprt/Documents/Proyectos IA/AtendIA-v2/core" && \
    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/e2e_flow_probe.py

Exit 0 with the printed evidence == PASS. Any exception == FAIL (do not
fake the trace; report the error).
"""

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.sandbox.harness import run_sandbox_turn

# Reuse the runner suite's committed seeding helper + fake providers (same
# pattern as core/tests/sandbox/test_harness_no_side_effects.py).
from tests.runner.test_conversation_runner import (
    _FakeNLUWithCost,
    _RecordingComposer,
    _seed_tenant_with_pipeline,
)


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()
    print(f"DB: {settings.database_url}")

    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Seed a throwaway tenant + customer + conversation + conversation_state
    # using the runner suite's COMMITTED helper (it commits internally).
    async with factory() as seed_session:
        tid, _cid, conv_id = await _seed_tenant_with_pipeline(
            seed_session, "e2e_flow_probe_task1"
        )
    print(f"seeded tenant={tid} conversation={conv_id}")

    try:
        # ONE real runner turn, fake providers => $0, zero side-effects.
        result = await run_sandbox_turn(
            conversation_id=conv_id,
            tenant_id=tid,
            inbound_text="hola, quiero una moto",
            nlu_provider=_FakeNLUWithCost(Decimal("0.000050")),
            composer_provider=_RecordingComposer(messages=["hola, con gusto te ayudo"]),
        )

        nlu_present = result.nlu_output is not None
        composer_present = result.composer_output is not None

        print("---- PROBE EVIDENCE ----")
        print(f"trace.flow_mode          = {result.flow_mode!r}")
        print(f"nlu_output present       = {nlu_present}")
        print(f"composer_output present  = {composer_present}")
        print(f"would_be_outbound        = {result.would_be_outbound!r}")
        print(f"cost_usd                 = {result.cost_usd}")
        print(f"composer messages        = "
              f"{(result.composer_output or {}).get('messages')!r}")
        print("------------------------")

        # The turn returning at all proves it did NOT raise: the runner
        # invokes NLU, then process_turn(decision), then flow_router, then
        # the Composer — composer_output being set means the Composer ran
        # strictly AFTER NLU produced the intent that gated it.
        assert nlu_present, "nlu_output missing => NLU stage did not run"
        assert composer_present, (
            "composer_output missing => Composer stage did not run after NLU"
        )
        assert result.flow_mode == "SUPPORT", (
            f"expected default router fallback 'SUPPORT', got {result.flow_mode!r}"
        )
        assert result.cost_usd == Decimal("0.000050"), (
            f"expected only the fake NLU component cost, got {result.cost_usd!r}"
        )
        # The composed text rides trace.outbound_messages (set to
        # composer_output.messages at conversation_runner.py:1154 regardless
        # of to_phone_e164); the harness surfaces that as would_be_outbound.
        assert result.would_be_outbound == ["hola, con gusto te ayudo"], (
            f"expected composed message in would_be_outbound, "
            f"got {result.would_be_outbound!r}"
        )
        assert (result.composer_output or {}).get("messages") == [
            "hola, con gusto te ayudo"
        ], "composer_output did not carry the RecordingComposer message"

        print(
            "PASS: msg -> NLU -> flow_router -> Composer order confirmed "
            "empirically ($0, zero side-effects)."
        )
        return 0
    finally:
        async with factory() as cleanup_session:
            await cleanup_session.execute(
                text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid}
            )
            await cleanup_session.commit()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

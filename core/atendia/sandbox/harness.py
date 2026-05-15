"""Run the real ConversationRunner with zero side effects.

Safe because the AsyncSession is ALWAYS rolled back and there is NO
.commit() anywhere in the runner or its callees, so every write —
messages, turn_traces, field_suggestions, AND the staged
`outbound_outbox` row — is undone. run_turn is called directly so the
webhook's publish_event WS broadcast never happens. CapturingArqPool is
only a defensive stub for the session=None/arq fallback branch; on the
real runner path outbound is staged into the (rolled-back) session
(and only when to_phone_e164 is set — the harness never passes it), and
the would-be reply text is read from the returned TurnTrace.

Session lifecycle is owned by the public entrypoints. `_run_turn_on_session`
runs ONE turn on a caller-owned session and does NOT open/rollback — that
is what lets `run_sandbox_conversation` loop N turns on a SINGLE session
(so conversation_state accumulates across turns: faithful multi-turn)
while still undoing everything with exactly ONE rollback at the end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.message import Message, MessageDirection
from atendia.db.session import _get_factory
from atendia.runner.composer_protocol import ComposerProvider
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_protocol import NLUProvider
from atendia.sandbox.result import CostCapExceeded, SandboxRunResult, SandboxTurnResult
from atendia.sandbox.transport import CapturingArqPool

# Per-turn cost guess used by estimate_cost when a tenant has no
# turn_traces history yet (rough Phase-3 average).
_FALLBACK_COST_PER_TURN = Decimal("0.02")
# How many of the tenant's most recent turns the cost estimate averages.
_RECENT_WINDOW = 50


async def _run_turn_on_session(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    inbound_text: str,
    turn_number: int,
    nlu_provider: NLUProvider,
    composer_provider: ComposerProvider,
) -> SandboxTurnResult:
    """Run ONE runner turn on a caller-owned session.

    Does the runner call + TurnTrace->SandboxTurnResult mapping only.
    Does NOT open, rollback, or close the session — the caller owns that
    lifecycle (so a multi-turn caller can keep state across turns and
    roll back once).
    """
    pool = CapturingArqPool()
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
        # Structural/duck typing: CapturingArqPool implements enqueue_job
        # so it satisfies the arq pool usage, but it isn't the declared
        # ArqRedis type. On the runner path outbound is staged into the
        # session (and only when to_phone_e164 is set, which the harness
        # never passes), so enqueue_job is never actually called here.
        arq_pool=pool,  # type: ignore[arg-type]
    )
    return SandboxTurnResult(
        flow_mode=getattr(trace, "flow_mode", None),
        nlu_output=getattr(trace, "nlu_output", None),
        composer_output=getattr(trace, "composer_output", None),
        would_be_outbound=list(getattr(trace, "outbound_messages", None) or []),
        # The runner never assigns TurnTrace.total_cost_usd on the
        # in-memory trace (it only accumulates per-turn cost into
        # conversation_state.total_cost_usd via raw SQL). It DOES set the
        # individual component costs on the trace, so sum those to get
        # the real per-turn cost (reading total_cost_usd was always 0).
        cost_usd=(
            (getattr(trace, "nlu_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "composer_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "tool_cost_usd", None) or Decimal("0"))
            + (getattr(trace, "vision_cost_usd", None) or Decimal("0"))
        ),
        latency_ms=getattr(trace, "total_latency_ms", None),
    )


async def run_sandbox_turn(
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    inbound_text: str,
    turn_number: int = 1,
    nlu_provider: NLUProvider,
    composer_provider: ComposerProvider,
) -> SandboxTurnResult:
    # Use the private _get_factory() (loop-scoped engine reuse) rather than
    # the public get_db_session(): the latter is an async-generator FastAPI
    # dependency that doesn't fit this explicit try/finally single-session
    # lifecycle (we need one session we own and roll back); no public
    # equivalent exposes the sessionmaker directly.
    factory = _get_factory()
    session = factory()
    try:
        return await _run_turn_on_session(
            session,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            inbound_text=inbound_text,
            turn_number=turn_number,
            nlu_provider=nlu_provider,
            composer_provider=composer_provider,
        )
    finally:
        await session.rollback()
        await session.close()


async def run_sandbox_conversation(
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    script: list[str],
    cost_cap_usd: Decimal | None = None,
    nlu_provider: NLUProvider,
    composer_provider: ComposerProvider,
) -> SandboxRunResult:
    """Replay a script of inbound messages as a faithful multi-turn run.

    ONE session for the whole script: turn N reads the (uncommitted)
    conversation_state that turn N-1 wrote within the same transaction,
    so stage/extracted-data accumulate exactly like production — without
    persisting. A single rollback in `finally` undoes all N turns (the
    zero-side-effects invariant still holds, including when the cost cap
    raises mid-script). When the running total first EXCEEDS
    `cost_cap_usd`, raise `CostCapExceeded`; the tripping turn already ran
    so it counts in `.spent` and `.partial`.
    """
    factory = _get_factory()
    session = factory()
    result = SandboxRunResult()
    spent = Decimal("0")
    try:
        for turn_number, inbound_text in enumerate(script, start=1):
            turn = await _run_turn_on_session(
                session,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                inbound_text=inbound_text,
                turn_number=turn_number,
                nlu_provider=nlu_provider,
                composer_provider=composer_provider,
            )
            result.turns.append(turn)
            spent += turn.cost_usd
            if cost_cap_usd is not None and spent > cost_cap_usd:
                raise CostCapExceeded(partial=list(result.turns), spent=spent)
        return result
    finally:
        await session.rollback()
        await session.close()


async def estimate_cost(*, tenant_id: UUID, n_turns: int) -> Decimal:
    """Rough pre-run cost guess: n_turns * mean recent per-turn cost.

    Mean is over the tenant's most recent turn_traces (sum of the four
    component cost columns per row). No history → a constant fallback so
    a brand-new tenant still gets a usable estimate.
    """
    factory = _get_factory()
    session = factory()
    try:
        avg = (
            await session.execute(
                text(
                    "SELECT AVG(per_turn) FROM ("
                    "  SELECT ("
                    "    COALESCE(nlu_cost_usd, 0) + COALESCE(composer_cost_usd, 0)"
                    "    + COALESCE(tool_cost_usd, 0) + COALESCE(vision_cost_usd, 0)"
                    "  ) AS per_turn"
                    "  FROM turn_traces"
                    "  WHERE tenant_id = :t"
                    "  ORDER BY created_at DESC"
                    "  LIMIT :lim"
                    ") recent"
                ),
                {"t": tenant_id, "lim": _RECENT_WINDOW},
            )
        ).scalar()
        avg_cost = Decimal(avg) if avg is not None else _FALLBACK_COST_PER_TURN
        return n_turns * avg_cost
    finally:
        await session.rollback()
        await session.close()

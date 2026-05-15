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
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from atendia.contracts.message import Message, MessageDirection
from atendia.db.session import _get_factory
from atendia.runner.composer_protocol import ComposerProvider
from atendia.runner.conversation_runner import ConversationRunner
from atendia.runner.nlu_protocol import NLUProvider
from atendia.sandbox.result import SandboxTurnResult
from atendia.sandbox.transport import CapturingArqPool


async def run_sandbox_turn(
    *,
    conversation_id: UUID,
    tenant_id: UUID,
    inbound_text: str,
    turn_number: int = 1,
    nlu_provider: NLUProvider,
    composer_provider: ComposerProvider,
) -> SandboxTurnResult:
    factory = _get_factory()
    pool = CapturingArqPool()
    session = factory()
    try:
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
            arq_pool=pool,  # type: ignore[arg-type]  # defensive; runner stages to session
        )
        return SandboxTurnResult(
            flow_mode=getattr(trace, "flow_mode", None),
            nlu_output=getattr(trace, "nlu_output", None),
            composer_output=getattr(trace, "composer_output", None),
            would_be_outbound=list(getattr(trace, "outbound_messages", None) or []),
            cost_usd=getattr(trace, "total_cost_usd", None) or Decimal("0"),
            latency_ms=getattr(trace, "total_latency_ms", None),
        )
    finally:
        await session.rollback()
        await session.close()

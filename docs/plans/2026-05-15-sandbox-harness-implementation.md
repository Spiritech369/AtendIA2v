# Sandbox Harness Implementation Plan (roadmap piece 0)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A side-effect-free way to run the real `ConversationRunner` against a real conversation and capture what it *would* do (composer output, NLU, cost, would-be outbound) without persisting anything or sending any WhatsApp message.

**Architecture:** Isolation over the *unchanged* runner. The **rolled-back `AsyncSession` is the real safety mechanism** — verified safe because there is **no `.commit()`** anywhere in the runner or its callees, so rollback fully undoes every write. The runner is invoked directly (not via the webhook), so the webhook's `publish_event` WS broadcast never happens.

> **Correction (code-review finding #1, Task 1):** `outbound_dispatcher.enqueue_messages(arq_pool, *, session=...)` (lines 55-58) takes the `stage_outbound(session, msg)` branch whenever a real `session` is passed — and the runner **always** passes `self._session`. So `arq_pool.enqueue_job` is **never called** on the runner path; the outbound is staged as an `outbox` row *inside the session* (and rolled back). Therefore:
> - **`would_be_outbound` is sourced from the returned `TurnTrace.outbound_messages`** (`conversation_runner.py:1154` sets `outbound_messages=composer_output.messages`), **NOT** from `pool.captured`.
> - `CapturingArqPool` stays as a **defensive stub** for the `session=None`/`arq_redis` fallback path (harmless, already built + approved in Task 1). It is *not* the capture mechanism.
> - The zero-side-effects invariant test (Task 3) **must also assert zero new `outbox` rows**, since `stage_outbound` writes there.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 async, asyncpg, pytest-asyncio, `uv`. Dev DB = Docker Postgres on host **5433** (copy `core/.env` from the main checkout into the worktree `core/` first; verify `uv run python -c "from atendia.config import get_settings; print(get_settings().database_url)"` shows `:5433`).

**Reference scaffold:** `core/tests/runner/test_conversation_runner.py` — copy its pattern for seeding a tenant+customer+conversation+`conversation_state` row and building `ConversationRunner(session, _FakeNLUWithCost(...), <fake composer>)`. The harness test is that scaffold + an assertion that nothing persisted.

**Working contract:** TDD RED→GREEN every task, commit per task, dev-DB pytest, no green claims unsold. This is its own session/worktree (piece 0 of `docs/plans/2026-05-15-sandbox-debug-roadmap-design.md`).

---

### Task 1: Package + `CapturingArqPool` transport stub

**Files:**
- Create: `core/atendia/sandbox/__init__.py` (empty)
- Create: `core/atendia/sandbox/transport.py`
- Create: `core/tests/sandbox/__init__.py` (empty)
- Test: `core/tests/sandbox/test_capturing_arq_pool.py`

**Step 1: Write the failing test**

```python
import pytest
from atendia.sandbox.transport import CapturingArqPool


@pytest.mark.asyncio
async def test_enqueue_job_is_captured_not_sent():
    pool = CapturingArqPool()
    job = await pool.enqueue_job("send_whatsapp", {"to": "+521", "text": "hola"})
    assert job is not None                       # callers expect a truthy job handle
    assert pool.captured == [("send_whatsapp", ({"to": "+521", "text": "hola"},), {})]
    assert pool.send_count == 0                  # nothing actually dispatched
```

**Step 2: Run test to verify it fails**

Run: `cd core && uv run pytest tests/sandbox/test_capturing_arq_pool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'atendia.sandbox'`

**Step 3: Write minimal implementation**

`core/atendia/sandbox/transport.py`:
```python
"""Side-effect-free arq pool: records would-be jobs, dispatches none."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class _CapturedJob:
    def __init__(self, function: str) -> None:
        self.function = function


@dataclass
class CapturingArqPool:
    captured: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    @property
    def send_count(self) -> int:
        return 0

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> _CapturedJob:
        self.captured.append((function, args, kwargs))
        return _CapturedJob(function)

    async def aclose(self) -> None:  # mirrors ArqRedis API used by callers
        return None
```

**Step 4: Run test to verify it passes**

Run: `cd core && uv run pytest tests/sandbox/test_capturing_arq_pool.py -v`
Expected: PASS (2 assertions green)

**Step 5: Commit**

```bash
git add core/atendia/sandbox/__init__.py core/atendia/sandbox/transport.py core/tests/sandbox/__init__.py core/tests/sandbox/test_capturing_arq_pool.py
git commit -m "feat(sandbox): CapturingArqPool transport stub (harness task 1)"
```

---

### Task 2: `SandboxResult` shape

**Files:**
- Create: `core/atendia/sandbox/result.py`
- Test: `core/tests/sandbox/test_sandbox_result.py`

**Step 1: Write the failing test**

```python
from decimal import Decimal
from atendia.sandbox.result import SandboxTurnResult


def test_turn_result_carries_composer_and_cost():
    r = SandboxTurnResult(
        flow_mode="SALES",
        nlu_output={"intent": "ASK_PRICE"},
        composer_output={"text": "El precio es..."},
        would_be_outbound=["El precio es..."],
        cost_usd=Decimal("0.0123"),
        latency_ms=812,
    )
    assert r.composer_output["text"].startswith("El precio")
    assert r.cost_usd == Decimal("0.0123")
    assert r.would_be_outbound == ["El precio es..."]
```

**Step 2: Run** `cd core && uv run pytest tests/sandbox/test_sandbox_result.py -v` → FAIL (`ModuleNotFoundError`).

**Step 3: Implement** `core/atendia/sandbox/result.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class SandboxTurnResult:
    flow_mode: str | None
    nlu_output: dict[str, Any] | None
    composer_output: dict[str, Any] | None
    would_be_outbound: list[str]
    cost_usd: Decimal
    latency_ms: int | None


@dataclass
class SandboxRunResult:
    turns: list[SandboxTurnResult] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> Decimal:
        return sum((t.cost_usd for t in self.turns), Decimal("0"))
```

**Step 4: Run** the test → PASS.

**Step 5: Commit**
```bash
git add core/atendia/sandbox/result.py core/tests/sandbox/test_sandbox_result.py
git commit -m "feat(sandbox): SandboxResult shapes (harness task 2)"
```

---

### Task 3: `run_sandbox_turn` — core harness + the zero-side-effects invariant

This is the safety-critical task. Reuse the seeding helpers from
`core/tests/runner/test_conversation_runner.py` (read it first: it shows
exactly how to insert a tenant, customer, conversation, `conversation_state`
row, and build `ConversationRunner` with `_FakeNLUWithCost` + a fake
composer). The fake providers keep this test free + deterministic (real-LLM
fidelity is a separate gated test, Task 6).

**Files:**
- Create: `core/atendia/sandbox/harness.py`
- Test: `core/tests/sandbox/test_harness_no_side_effects.py`

**Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import text

from atendia.sandbox.harness import run_sandbox_turn
# Reuse seeding + fake providers from the runner suite scaffold:
from tests.runner.test_conversation_runner import (  # adjust import to actual helpers
    _FakeNLUWithCost, _seed_conversation, _fake_composer,  # names per that file
)


@pytest.mark.asyncio
async def test_sandbox_turn_persists_nothing(db_session_factory):
    conv = await _seed_conversation(...)  # tenant, customer, conversation, state row

    async def _count(s, table):
        return (await s.execute(text(f"SELECT count(*) FROM {table} "
            "WHERE conversation_id = :c"), {"c": conv.id})).scalar()

    # snapshot row counts in a fresh session. `outbox` is included
    # because the runner stages outbound there (review finding #1) —
    # the rollback must undo it too.
    before = {t: await _count(s, t) for t in
              ("messages", "turn_traces", "field_suggestions", "outbox")}

    result = await run_sandbox_turn(
        conversation_id=conv.id, tenant_id=conv.tenant_id,
        inbound_text="quiero una moto",
        nlu_provider=_FakeNLUWithCost(...), composer_provider=_fake_composer(),
    )

    after = {t: await _count(s, t) for t in before}
    assert after == before                       # ← INVARIANT: zero persisted writes
    assert result.composer_output is not None     # but we still got the decision
    assert isinstance(result.would_be_outbound, list)
```

**Step 2: Run** `cd core && uv run pytest tests/sandbox/test_harness_no_side_effects.py -v` → FAIL (`ModuleNotFoundError: atendia.sandbox.harness`).

**Step 3: Implement** `core/atendia/sandbox/harness.py`:
```python
"""Run the real ConversationRunner with zero side effects.

Safe because the AsyncSession is ALWAYS rolled back and there is NO
.commit() anywhere in the runner or its callees, so every write —
messages, turn_traces, field_suggestions, AND the staged `outbox`
row — is undone. run_turn is called directly so the webhook's
publish_event WS broadcast never happens. CapturingArqPool is only a
defensive stub for the session=None/arq fallback branch; on the real
runner path outbound is staged into the (rolled-back) session, and
the would-be reply text is read from the returned TurnTrace.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

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
        inbound = Message(direction=MessageDirection.INBOUND, text=inbound_text)
        trace = await runner.run_turn(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            inbound=inbound,
            turn_number=turn_number,
            arq_pool=pool,  # type: ignore[arg-type]  # duck-typed enqueue_job
        )
        return SandboxTurnResult(
            flow_mode=getattr(trace, "flow_mode", None),
            nlu_output=getattr(trace, "nlu_output", None),
            composer_output=getattr(trace, "composer_output", None),
            # review finding #1: the runner stages outbound into the
            # session (rolled back); the would-be reply text lives on
            # the returned trace, NOT pool.captured.
            would_be_outbound=list(getattr(trace, "outbound_messages", None) or []),
            cost_usd=getattr(trace, "total_cost_usd", None) or Decimal("0"),
            latency_ms=getattr(trace, "total_latency_ms", None),
        )
    finally:
        await session.rollback()   # undoes EVERYTHING the runner wrote
        await session.close()
```
*(Implementer: confirm the exact `Message` constructor + `TurnTrace`
attribute names against `contracts/message.py` and the object `run_turn`
returns (esp. `outbound_messages` — set at `conversation_runner.py:1154`
to `composer_output.messages`); adjust the `getattr` mapping accordingly.
The invariant test is the source of truth — make it green without
changing the runner. Also apply review finding #2: add a `job_id`
attribute to `_CapturedJob` in `transport.py` (e.g.
`self.job_id = f"captured:{function}"`) so the defensive stub fully
duck-types `arq.jobs.Job` for the fallback path — small hardening,
commit it as part of this task.)*

**Step 4: Run** the test → PASS (`after == before`, composer_output present).

**Step 5: Commit**
```bash
git add core/atendia/sandbox/harness.py core/tests/sandbox/test_harness_no_side_effects.py
git commit -m "feat(sandbox): run_sandbox_turn + zero-side-effects invariant (harness task 3)"
```

---

### Task 4: Cost accumulation + confirmable cap

**Files:**
- Modify: `core/atendia/sandbox/harness.py` (add `run_sandbox_conversation`)
- Modify: `core/atendia/sandbox/result.py` (add `CostCapExceeded`)
- Test: `core/tests/sandbox/test_sandbox_cost_cap.py`

**Step 1: Failing test** — replay a 3-message script with each fake turn
costing `0.05`; `cost_cap_usd=0.08` → expect `CostCapExceeded` raised after
turn 2, with `.partial` holding the 2 completed `SandboxTurnResult`s and
`.spent == Decimal("0.10")` (the turn that tripped the cap still counts).

**Step 2: Run** → FAIL (`ImportError: CostCapExceeded`).

> **Design correction (controller, pre-Task-4 — same class as finding #1):** Task 4 must NOT "loop `run_sandbox_turn`". `run_sandbox_turn` opens its own session and rolls back **per turn**, so turn 2 would not see turn 1's `conversation_state`/extracted-data — that is not a faithful multi-turn replay (and A4/A3/P2 depend on faithful multi-turn). Refactor first: extract an internal `async def _run_turn_on_session(session, *, conversation_id, tenant_id, inbound_text, turn_number, nlu_provider, composer_provider) -> SandboxTurnResult` that does the runner call + `TurnTrace`→`SandboxTurnResult` mapping **but does NOT open/rollback the session** (caller owns the session lifecycle). Then:
> - `run_sandbox_turn(...)` = open one session → `_run_turn_on_session(...)` once → `finally: rollback + close` (behaviour unchanged; existing Task 3 invariant test must still pass untouched).
> - `run_sandbox_conversation(...)` = open **one** session, loop `_run_turn_on_session` over the script (state accumulates across turns within that session, faithful multi-turn), accumulate cost, and **`finally: rollback + close` exactly once** at the end (the zero-side-effects invariant still holds — one rollback undoes all N turns).
> Add a `test_sandbox_conversation_persists_nothing` invariant test for the multi-turn path too (same fresh-session row-count technique as Task 3, asserting `after == before` after an N-message script).

**Step 3: Implement** `run_sandbox_conversation(*, conversation_id, tenant_id, script: list[str], cost_cap_usd: Decimal | None, nlu_provider, composer_provider) -> SandboxRunResult` per the design correction above (one session, loop `_run_turn_on_session`, single rollback in `finally`). Accumulate `total_cost_usd` from each turn's `SandboxTurnResult.cost_usd` (now correct after Task-3 fix I1); raise `CostCapExceeded(partial=[...completed SandboxTurnResult...], spent=Decimal)` the moment the running total exceeds `cost_cap_usd` (the tripping turn still counts in `spent` and `partial`); the rollback in `finally` still runs when this raises. Add an `estimate_cost(*, tenant_id, n_turns) -> Decimal` helper returning `n_turns * avg_cost_per_turn`, where `avg_cost_per_turn` is the mean of recent `turn_traces` component costs for the tenant (fallback constant `Decimal("0.02")` when no history). `CostCapExceeded` goes in `result.py` (carries `.partial: list[SandboxTurnResult]` and `.spent: Decimal`).

**Step 4: Run** → PASS.

**Step 5: Commit** `feat(sandbox): cost accumulation + confirmable cap (harness task 4)`.

---

### Task 5: Override hook (apply agent/prompt override inside the rolled-back txn)

A4/A3 need to run with a *different* prompt without touching production.
Mechanism: a pre-run callback that mutates the agent row **inside the
sandbox session** — the rollback discards it, the runner naturally loads the
overridden config.

**Files:**
- Modify: `core/atendia/sandbox/harness.py` (add `apply_overrides` callback param)
- Test: `core/tests/sandbox/test_sandbox_override.py`

**Step 1: Failing test** — seed an agent with prompt `"A"`. Run a sandbox
turn passing `apply_overrides=lambda s: s.execute(update(Agent)...set prompt "B")`.
Assert: (a) the composer received prompt `"B"` (inspect captured composer
input on the result), and (b) **after** the run, a fresh session reads the
agent prompt still `"A"` (override was rolled back).

**Step 2: Run** → FAIL (`TypeError: unexpected kwarg apply_overrides`).

**Step 3: Implement** — add `apply_overrides: Callable[[AsyncSession], Awaitable[None]] | None = None`; call `await apply_overrides(session)` (and `await session.flush()`) *before* `runner.run_turn`. Nothing else changes (rollback already discards it).

**Step 4: Run** → PASS (both assertions).

**Step 5: Commit** `feat(sandbox): rolled-back override hook for prompt swap (harness task 5)`.

---

### Task 6: Live-LLM fidelity test (gated)

**Files:**
- Test: `core/tests/sandbox/test_harness_live_fidelity.py`

**Step 1: Write the test** guarded by `@pytest.mark.skipif(not os.getenv("RUN_LIVE_LLM_TESTS"), reason="costs money")`. It runs `run_sandbox_turn` with the **real** NLU + composer providers against a seeded conversation and asserts a non-empty `composer_output.text` + `cost_usd > 0` + still zero persisted rows.

**Step 2: Run** `cd core && RUN_LIVE_LLM_TESTS=1 uv run pytest tests/sandbox/test_harness_live_fidelity.py -v` → confirm PASS once (note the ~$ in the run summary, per contract).

**Step 3: Commit** `test(sandbox): gated live-LLM fidelity check (harness task 6)`.

---

### Task 7: Verify + finish

- Run the whole sandbox suite: `cd core && uv run pytest tests/sandbox -v` → all green (live test skipped without the env var).
- Run a regression sanity on the runner suite (we changed nothing there, but prove it): `cd core && uv run pytest tests/runner/test_conversation_runner.py -q` → no NEW failures vs the documented baseline (`test_runner_extracts_fields_then_transitions_to_quote` etc. are known-baseline per memory `db_verification_env.md`; do not treat as regressions).
- Invoke **superpowers:finishing-a-development-branch**.

---

## Out of scope (explicitly — future pieces, their own sessions)

A4 (`/agents/{id}/sandbox-replay`), A3 (`/agents/{id}/ab-test`), P2
(`/pipeline/test-run`) are **not** in this plan. They are thin services over
this harness and get their own brainstorm→plan at the start of their
sessions. W2 and K1 are independent of the harness entirely. This plan ships
**only the foundation**, fully tested, so the next sessions have a verified
base to build on.

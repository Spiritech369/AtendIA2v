# DebugPanel C2 Completion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the 8 remaining DebugPanel items from C2 (history count, agent name+role, actions panel, per-step latency, LLM provider, cleaned text, prompt template breakdown, tool calls timeline) so operators can debug any turn end-to-end without leaving the panel.

**Architecture:** Migration 048 adds `composer_provider` + `inbound_text_cleaned` to `turn_traces` (2 nullable columns, additive). Runner sets both on every turn. Frontend adds 4 new analyzer functions + 4 new panel components + tweaks to TurnStoryView. DebugPanel composes the new sections into the existing scroll layout.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · pytest-asyncio · React 19 · TanStack Query · Vitest · MSW · Tailwind v4.

**Design doc:** `docs/plans/2026-05-15-debugpanel-c2-design.md`

---

## Task 1: Migration 048 — turn_traces columns

**Files:**
- Create: `core/atendia/db/migrations/versions/048_turn_traces_composer_provider_cleaned.py`
- Modify: `core/atendia/db/models/turn_trace.py:50-72` (add 2 mapped columns)

**Step 1: Write the migration**

```python
"""048_turn_traces_composer_provider_cleaned

Revision ID: n1b2c3d4e5f6
Revises: m0a1b2c3d4e5
Create Date: 2026-05-15

Adds two nullable columns to turn_traces for C2 DebugPanel completion:

* composer_provider — which adapter served this turn ("openai",
  "canned", "fallback"). Helps operators distinguish "the LLM said X"
  from "the LLM was unreachable and the canned reply fired".
* inbound_text_cleaned — the normalized text the NLU actually saw
  (after diacritic strip, lowercase, markdown removal). Side-by-side
  with inbound_text in the story lets operators spot cases where the
  cleanup itself altered meaning.

Both nullable so legacy rows stay valid; runner populates them going
forward.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "m0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turn_traces",
        sa.Column("composer_provider", sa.String(20), nullable=True),
    )
    op.add_column(
        "turn_traces",
        sa.Column("inbound_text_cleaned", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_turn_traces_composer_provider",
        "turn_traces",
        "composer_provider IS NULL "
        "OR composer_provider IN ('openai', 'canned', 'fallback')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_turn_traces_composer_provider", "turn_traces", type_="check"
    )
    op.drop_column("turn_traces", "inbound_text_cleaned")
    op.drop_column("turn_traces", "composer_provider")
```

**Step 2: Add the mapped columns to the model**

In `core/atendia/db/models/turn_trace.py`, after `vision_latency_ms` (line 52):

```python
    # Migration 048 — DebugPanel C2 completion. Composer adapter +
    # cleaned NLU input persisted per row so the panel can render
    # provider badges + side-by-side text. Nullable on legacy rows.
    composer_provider: Mapped[str | None] = mapped_column(String(20))
    inbound_text_cleaned: Mapped[str | None] = mapped_column(Text)
```

**Step 3: Apply migration**

```bash
cd core
uv run alembic upgrade head
```

Expected: `INFO [alembic.runtime.migration] Running upgrade m0a1b2c3d4e5 -> n1b2c3d4e5f6, 048_turn_traces_composer_provider_cleaned`

**Step 4: Verify schema**

```bash
uv run python -c "
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from atendia.config import get_settings
async def main():
    e = create_async_engine(get_settings().database_url)
    async with e.begin() as conn:
        rows = (await conn.execute(text(
            \"SELECT column_name, data_type, is_nullable FROM information_schema.columns \"
            \"WHERE table_name='turn_traces' AND column_name IN ('composer_provider', 'inbound_text_cleaned')\"
        ))).all()
        for r in rows: print(r)
    await e.dispose()
asyncio.run(main())
"
```

Expected: 2 rows showing both columns nullable.

**Step 5: Commit**

```bash
git add core/atendia/db/migrations/versions/048_turn_traces_composer_provider_cleaned.py core/atendia/db/models/turn_trace.py
git commit -m "feat(db): migration 048 — turn_traces.composer_provider + inbound_text_cleaned (C2)"
```

---

## Task 2: Runner persists composer_provider + inbound_text_cleaned

**Files:**
- Modify: `core/atendia/runner/conversation_runner.py` (find the `_persist_turn_trace` or equivalent INSERT site)
- Test: `core/tests/runner/test_conversation_runner_c2_fields.py` (new)

**Step 1: Write the failing test**

```python
"""C2 — Runner persists composer_provider + inbound_text_cleaned on
every turn_traces row. Frontend reads these to render provider badge
+ side-by-side cleaned text in the story."""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


@pytest.fixture
def fresh_tenant() -> tuple[str, str, str]:
    """Tenant + customer + conversation, cleaned up after."""
    async def _seed() -> tuple[str, str, str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                tid = (await conn.execute(text(
                    "INSERT INTO tenants (name) VALUES (:n) RETURNING id"
                ), {"n": f"c2_runner_test_{uuid4().hex[:8]}"})).scalar()
                cid = (await conn.execute(text(
                    "INSERT INTO customers (tenant_id, phone_e164, name) "
                    "VALUES (:t, :p, 'C2 Test') RETURNING id"
                ), {"t": tid, "p": f"+5215{uuid4().hex[:9]}"})).scalar()
                from atendia.state_machine.pipeline_loader import ensure_default_pipeline
                from sqlalchemy.ext.asyncio import async_sessionmaker
                sm = async_sessionmaker(engine, expire_on_commit=False)
                async with sm() as s:
                    await ensure_default_pipeline(s, tid)
                    await s.commit()
                conv = (await conn.execute(text(
                    "INSERT INTO conversations (tenant_id, customer_id, current_stage) "
                    "VALUES (:t, :c, 'nuevo') RETURNING id"
                ), {"t": tid, "c": cid})).scalar()
                await conn.execute(text(
                    "INSERT INTO conversation_state (conversation_id) VALUES (:c)"
                ), {"c": conv})
            return str(tid), str(cid), str(conv)
        finally:
            await engine.dispose()

    async def _cleanup(tid: str) -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await engine.dispose()

    tid, cid, conv = asyncio.run(_seed())
    yield tid, cid, conv
    asyncio.run(_cleanup(tid))


async def test_runner_persists_composer_provider_and_cleaned_text(fresh_tenant):
    """A single run_turn against a fresh tenant lands a turn_traces
    row with composer_provider set ('canned' by default in tests) and
    inbound_text_cleaned set to the normalized text."""
    tid, cid, conv = fresh_tenant
    from atendia.runner.conversation_runner import ConversationRunner
    from atendia.webhooks.meta_routes import build_composer, build_nlu
    from atendia.contracts.message import Message, MessageDirection
    from atendia.config import get_settings
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    s = get_settings()
    engine = create_async_engine(s.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sm() as session:
            nlu = build_nlu(s)
            comp = build_composer(s)
            runner = ConversationRunner(session, nlu, comp)
            inbound = Message(
                id=str(uuid4()),
                conversation_id=conv,
                tenant_id=tid,
                direction=MessageDirection.INBOUND,
                text="¡HOLA! quiero info",  # has caps + accent → cleaning visible
                sent_at=datetime.now(UTC),
                attachments=[],
            )
            await runner.run_turn(
                conversation_id=UUID(conv),
                tenant_id=UUID(tid),
                inbound=inbound,
                turn_number=1,
                arq_pool=None,
                to_phone_e164="+5215999111222",
            )

        async with engine.begin() as conn:
            row = (await conn.execute(text(
                "SELECT composer_provider, inbound_text_cleaned, inbound_text "
                "FROM turn_traces WHERE conversation_id = :c"
            ), {"c": conv})).mappings().one()

        assert row["composer_provider"] in ("openai", "canned", "fallback"), (
            f"composer_provider must be one of the 3 enum values, got {row['composer_provider']!r}"
        )
        assert row["inbound_text_cleaned"] is not None, (
            "inbound_text_cleaned must be persisted (not NULL)"
        )
        # The cleaned text should differ from the raw text since the raw
        # had caps + accent.
        assert row["inbound_text_cleaned"] != row["inbound_text"], (
            "cleaning must alter the text (lowercase + diacritic strip)"
        )
        assert row["inbound_text_cleaned"] == row["inbound_text_cleaned"].lower()
    finally:
        await engine.dispose()
```

**Step 2: Run test to verify it fails**

```bash
cd core
uv run pytest tests/runner/test_conversation_runner_c2_fields.py -v
```

Expected: FAIL with `assert None == ('openai', 'canned', 'fallback')` or similar — the runner doesn't set the new fields yet.

**Step 3: Add helper + modify runner**

In `core/atendia/runner/conversation_runner.py`, find the function/method that inserts the turn_traces row (likely `_persist_turn_trace` or equivalent). Add:

```python
def _composer_provider_short_name(composer) -> str | None:
    """Return short adapter name for the composer instance.

    'openai' for OpenAIComposer hitting the API successfully.
    'fallback' for OpenAIComposer that fell back to canned (the
    OpenAIComposer instance carries a ``_fallback_triggered`` flag set
    by its retry loop when all LLM attempts failed).
    'canned' for CannedComposer (deterministic dev/test path).
    None for any future class we don't recognize — frontend degrades to
    no badge.
    """
    cls = type(composer).__name__
    if cls == "CannedComposer":
        return "canned"
    if cls == "OpenAIComposer":
        return "fallback" if getattr(composer, "_fallback_triggered", False) else "openai"
    return None
```

At the turn_traces INSERT site, add the two new columns:

```python
# ... existing INSERT INTO turn_traces (...) VALUES (...) ...
"composer_provider": _composer_provider_short_name(self._composer),
"inbound_text_cleaned": _clean_inbound(inbound.text),  # reuse existing _clean if present
```

If a `_clean_inbound` helper doesn't already exist, add:

```python
def _clean_inbound(text: str) -> str:
    """Mirror the cleanup the NLU already does on inbound text.
    Keep in sync with whatever the NLU normalizer does."""
    import unicodedata
    normalized = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in normalized if not unicodedata.combining(c))
    return stripped.lower().strip()
```

**Step 4: Run test to verify it passes**

```bash
cd core
uv run pytest tests/runner/test_conversation_runner_c2_fields.py -v
```

Expected: PASS — both fields present, cleaned text differs from original.

**Step 5: Regression on existing runner tests**

```bash
uv run pytest tests/runner -q
```

Expected: all green.

**Step 6: Commit**

```bash
git add core/atendia/runner/conversation_runner.py core/tests/runner/test_conversation_runner_c2_fields.py
git commit -m "feat(runner): persist composer_provider + inbound_text_cleaned (C2)"
```

---

## Task 3: API response includes new fields

**Files:**
- Modify: `core/atendia/api/turn_traces_routes.py` (TurnTraceDetail model + GET handler)
- Test: extend `core/tests/api/test_turn_traces_routes.py`

**Step 1: Write the failing test**

In `core/tests/api/test_turn_traces_routes.py`, append:

```python
def test_get_turn_trace_returns_composer_provider_and_cleaned_text(operator_with_traces):
    """C2 — the detail endpoint must expose the new migration-048 fields
    so the frontend DebugPanel can render the provider badge + side-by-
    side cleaned text. Legacy rows with NULL still return 200, just
    with the fields set to null."""
    _, _, email, plain, tids = operator_with_traces
    client = TestClient(app)
    _login(client, email, plain)

    resp = client.get(f"/api/v1/turn-traces/{tids[0]}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Fields are present even when null (json includes the key)
    assert "composer_provider" in body
    assert "inbound_text_cleaned" in body
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_turn_traces_routes.py::test_get_turn_trace_returns_composer_provider_and_cleaned_text -v
```

Expected: FAIL — `'composer_provider' not in body`.

**Step 3: Add fields to Pydantic model + handler**

In `core/atendia/api/turn_traces_routes.py`, find `TurnTraceDetail` (around line 60-90) and add the two new optional fields:

```python
class TurnTraceDetail(BaseModel):
    # ... existing fields ...
    composer_provider: str | None
    inbound_text_cleaned: str | None
    # ... rest ...
```

In the GET handler that returns the detail, add:

```python
return TurnTraceDetail(
    # ... existing field passes ...
    composer_provider=row.composer_provider,
    inbound_text_cleaned=row.inbound_text_cleaned,
)
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/api/test_turn_traces_routes.py -v
```

Expected: ALL PASS (existing 8 + new 1).

**Step 5: Commit**

```bash
git add core/atendia/api/turn_traces_routes.py core/tests/api/test_turn_traces_routes.py
git commit -m "feat(api): turn-traces detail exposes composer_provider + inbound_text_cleaned (C2)"
```

---

## Task 4: Frontend TurnTraceDetail interface update

**Files:**
- Modify: `frontend/src/features/turn-traces/api.ts`

**Step 1: Add the 2 fields to the TS interface**

In `frontend/src/features/turn-traces/api.ts`, find the `TurnTraceDetail` interface and add:

```typescript
export interface TurnTraceDetail extends TurnTraceListItem {
  // ... existing fields ...

  // Migration 048 — DebugPanel C2 completion. NULL on legacy rows
  // (recorded before the runner instrumentation).
  composer_provider: "openai" | "canned" | "fallback" | null;
  inbound_text_cleaned: string | null;
}
```

**Step 2: Typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: 8 pre-existing TS errors (in `DocumentRuleBuilder.test.tsx`), zero new errors.

**Step 3: Commit**

```bash
git add frontend/src/features/turn-traces/api.ts
git commit -m "types(turn-traces): add composer_provider + inbound_text_cleaned fields (C2)"
```

---

## Task 5: Item 1 — History count chip in StepInbound

**Files:**
- Modify: `frontend/src/features/conversations/components/DebugPanel.tsx` (pass totalTurns prop)
- Modify: `frontend/src/features/turn-traces/lib/turnStory.ts` (extend StoryStep inbound to carry counts)
- Modify: `frontend/src/features/turn-traces/components/TurnStoryView.tsx` (StepInbound renders chip)
- Test: `frontend/tests/features/turn-traces/HistoryCount.test.tsx` (new)

**Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import type { StoryStep } from "@/features/turn-traces/lib/turnStory";

describe("StepInbound history count chip", () => {
  it("renders 'turno 3 de 12' when totalTurns is known", () => {
    const steps: StoryStep[] = [
      {
        kind: "inbound",
        text: "hola",
        hasMedia: false,
        turnNumber: 3,
        totalTurns: 12,
      },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.getByText(/3 \/ 12/i)).toBeInTheDocument();
  });

  it("omits the chip when totalTurns is null (degrades cleanly)", () => {
    const steps: StoryStep[] = [
      {
        kind: "inbound",
        text: "hola",
        hasMedia: false,
        turnNumber: 1,
        totalTurns: null,
      },
    ];
    render(<TurnStoryView steps={steps} />);
    expect(screen.queryByText(/\/ /)).not.toBeInTheDocument();
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend
pnpm vitest run tests/features/turn-traces/HistoryCount.test.tsx
```

Expected: FAIL — `Property 'turnNumber' does not exist on type StoryStep`.

**Step 3: Extend the StoryStep type**

In `frontend/src/features/turn-traces/lib/turnStory.ts`:

```typescript
export type StoryStep =
  | {
      kind: "inbound";
      text: string | null;
      hasMedia: boolean;
      turnNumber: number;
      totalTurns: number | null;
    }
  // ... rest unchanged
```

Update `buildTurnStory(trace, opts?)` to accept an optional `totalTurns`:

```typescript
export function buildTurnStory(
  trace: TurnTraceDetail,
  opts: { totalTurns?: number | null } = {},
): StoryStep[] {
  const steps: StoryStep[] = [];
  steps.push({
    kind: "inbound",
    text: trace.inbound_text,
    hasMedia: /* existing logic */,
    turnNumber: trace.turn_number,
    totalTurns: opts.totalTurns ?? null,
  });
  // ... existing append logic
}
```

**Step 4: Render the chip in StepInbound**

In `TurnStoryView.tsx`, modify `StepInbound`:

```tsx
function StepInbound({ index, step }: { index: number; step: Extract<StoryStep, { kind: "inbound" }> }) {
  return (
    <StepShell
      index={index}
      icon={step.hasMedia ? Paperclip : MessageSquareText}
      primary={
        <span className="flex items-center gap-2">
          <span>
            <span className="text-muted-foreground">Cliente envió:</span>
            {/* existing content */}
          </span>
          {step.totalTurns != null && (
            <Badge
              variant="outline"
              className="ml-auto font-mono text-[10px] text-muted-foreground"
              title={`turno ${step.turnNumber} de ${step.totalTurns}`}
            >
              {step.turnNumber} / {step.totalTurns}
            </Badge>
          )}
        </span>
      }
    >
      {/* existing body */}
    </StepShell>
  );
}
```

**Step 5: Wire DebugPanel to pass totalTurns**

In `frontend/src/features/conversations/components/DebugPanel.tsx`, fetch the list to get the count:

```tsx
export function DebugPanel({ traceId, conversationId, onClose }: Props) {
  const { data: t, isLoading } = useQuery({
    queryKey: ["turn-trace", traceId],
    queryFn: () => turnTracesApi.getOne(traceId),
  });
  const list = useQuery({
    queryKey: ["turn-traces", conversationId],
    queryFn: () => turnTracesApi.list(conversationId),
    enabled: !!conversationId,
  });
  const totalTurns = list.data?.items.length ?? null;
  // ...
  // change buildTurnStory(t) to:
  <TurnStoryView steps={buildTurnStory(t, { totalTurns })} />
```

Add `conversationId: string` to `Props`. Update the parent of DebugPanel to pass it (likely `ConversationDetail.tsx`).

**Step 6: Run test to verify it passes**

```bash
pnpm vitest run tests/features/turn-traces/HistoryCount.test.tsx
```

Expected: PASS (2/2).

**Step 7: Regression**

```bash
pnpm vitest run tests/features/conversations
```

Expected: existing tests still pass.

**Step 8: Commit**

```bash
git add frontend/src/features/turn-traces frontend/src/features/conversations/components/DebugPanel.tsx frontend/tests/features/turn-traces/HistoryCount.test.tsx
git commit -m "feat(debug-panel): history count chip in StepInbound (C2 item 1)"
```

---

## Task 6: Item 5 — LLM provider badge in StepComposer

**Files:**
- Modify: `frontend/src/features/turn-traces/lib/turnStory.ts` (extend composer step)
- Modify: `frontend/src/features/turn-traces/components/TurnStoryView.tsx` (StepComposer renders badge)
- Test: `frontend/tests/features/turn-traces/ProviderBadge.test.tsx` (new)

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TurnStoryView } from "@/features/turn-traces/components/TurnStoryView";
import type { StoryStep } from "@/features/turn-traces/lib/turnStory";

describe("StepComposer provider badge", () => {
  const baseComposer: Extract<StoryStep, { kind: "composer" }> = {
    kind: "composer",
    messages: ["hola"],
    model: "gpt-4o",
    latencyMs: 100,
    costUsd: 0.001,
    pendingConfirmation: null,
    rawLlmResponse: null,
    provider: "openai",
  };

  it("renders the 'OpenAI' badge when provider is openai", () => {
    render(<TurnStoryView steps={[baseComposer]} />);
    expect(screen.getByText(/openai/i)).toBeInTheDocument();
  });
  it("renders a 'Canned' badge when provider is canned", () => {
    render(<TurnStoryView steps={[{ ...baseComposer, provider: "canned" }]} />);
    expect(screen.getByText(/canned/i)).toBeInTheDocument();
  });
  it("renders a 'Fallback' badge when provider is fallback", () => {
    render(<TurnStoryView steps={[{ ...baseComposer, provider: "fallback" }]} />);
    expect(screen.getByText(/fallback/i)).toBeInTheDocument();
  });
  it("omits the badge when provider is null (legacy rows)", () => {
    render(<TurnStoryView steps={[{ ...baseComposer, provider: null }]} />);
    expect(screen.queryByText(/openai|canned|fallback/i)).not.toBeInTheDocument();
  });
});
```

**Step 2: Verify RED**

```bash
pnpm vitest run tests/features/turn-traces/ProviderBadge.test.tsx
```

Expected: FAIL — type error on `provider` field.

**Step 3: Add provider to the composer story step**

In `turnStory.ts`, extend:

```typescript
| {
    kind: "composer";
    messages: string[];
    model: string | null;
    latencyMs: number | null;
    costUsd: number | null;
    pendingConfirmation: string | null;
    rawLlmResponse: string | null;
    provider: "openai" | "canned" | "fallback" | null;
  }
```

In `buildTurnStory`, the composer step now reads:

```typescript
steps.push({
  kind: "composer",
  messages: /* existing */,
  model: trace.composer_model,
  latencyMs: trace.composer_latency_ms,
  costUsd: trace.composer_cost_usd ? Number(trace.composer_cost_usd) : null,
  pendingConfirmation: /* existing */,
  rawLlmResponse: trace.raw_llm_response,
  provider: trace.composer_provider,
});
```

**Step 4: Render the badge in StepComposer**

In `TurnStoryView.tsx`, modify `StepComposer` — inside the metadata flex (where `step.model` is shown):

```tsx
{step.provider && (
  <Badge
    variant="outline"
    className={cn(
      "text-[10px]",
      step.provider === "openai" && "border-blue-500/40 bg-blue-500/10 text-blue-700",
      step.provider === "canned" && "border-amber-500/40 bg-amber-500/10 text-amber-700",
      step.provider === "fallback" && "border-rose-500/40 bg-rose-500/10 text-rose-700",
    )}
  >
    {step.provider}
  </Badge>
)}
```

**Step 5: GREEN**

```bash
pnpm vitest run tests/features/turn-traces/ProviderBadge.test.tsx
```

Expected: 4/4 PASS.

**Step 6: Commit**

```bash
git add frontend/src/features/turn-traces frontend/tests/features/turn-traces/ProviderBadge.test.tsx
git commit -m "feat(debug-panel): LLM provider badge in StepComposer (C2 item 5)"
```

---

## Task 7: Item 6 — Cleaned text side-by-side in StepInbound

**Files:**
- Modify: `frontend/src/features/turn-traces/lib/turnStory.ts` (extend inbound step)
- Modify: `frontend/src/features/turn-traces/components/TurnStoryView.tsx` (StepInbound shows cleaned)
- Test: extend `HistoryCount.test.tsx` to also cover cleaned text rendering

**Step 1: Failing test**

```tsx
// In HistoryCount.test.tsx or new CleanedText.test.tsx:
it("shows the cleaned text when it differs from raw", () => {
  render(<TurnStoryView steps={[{
    kind: "inbound",
    text: "¡HOLA!",
    cleanedText: "hola",
    hasMedia: false,
    turnNumber: 1,
    totalTurns: 1,
  }]} />);
  expect(screen.getByText(/hola/)).toBeInTheDocument();
  expect(screen.getByText(/Texto limpio/i)).toBeInTheDocument();
});

it("hides the cleaned section when it equals raw", () => {
  render(<TurnStoryView steps={[{
    kind: "inbound",
    text: "hola",
    cleanedText: "hola",
    hasMedia: false,
    turnNumber: 1,
    totalTurns: 1,
  }]} />);
  expect(screen.queryByText(/Texto limpio/i)).not.toBeInTheDocument();
});
```

**Step 2: Add `cleanedText: string | null` to the inbound StoryStep**, mirroring how Task 5 added provider. Update `buildTurnStory` to source from `trace.inbound_text_cleaned`.

**Step 3: In `StepInbound`, render a secondary card when `step.cleanedText && step.cleanedText !== step.text`**:

```tsx
{step.cleanedText && step.cleanedText !== step.text && (
  <div className="mt-1 rounded-md border border-dashed bg-muted/30 px-2 py-1 text-[11px] text-muted-foreground">
    <span className="mr-1 uppercase tracking-wide text-[9px]">Texto limpio:</span>
    «{step.cleanedText}»
  </div>
)}
```

**Step 4: GREEN + commit**

```bash
pnpm vitest run tests/features/turn-traces/HistoryCount.test.tsx
git add frontend/src/features/turn-traces
git commit -m "feat(debug-panel): cleaned-text side-by-side in StepInbound (C2 item 6)"
```

---

## Task 8: Item 2 — Agent name + role in StepComposer

**Files:**
- Add: `frontend/src/features/agents/api.ts` may already export an agent fetcher; if not, add a `get(id)` method.
- Modify: `frontend/src/features/conversations/components/DebugPanel.tsx` (pre-fetch the agent when `trace.agent_id` is set, pass name+role down)
- Modify: `frontend/src/features/turn-traces/lib/turnStory.ts` + `TurnStoryView.tsx` (composer step shows name+role)
- Test: `frontend/tests/features/turn-traces/AgentNameRole.test.tsx`

**Step 1: Failing test**

```tsx
it("renders agent name + role in composer step when provided", () => {
  render(<TurnStoryView steps={[{
    kind: "composer",
    messages: ["hola"],
    model: "gpt-4o",
    latencyMs: 100,
    costUsd: 0.001,
    pendingConfirmation: null,
    rawLlmResponse: null,
    provider: "openai",
    agentName: "Mariana",
    agentRole: "Ventas",
  }]} />);
  expect(screen.getByText(/Mariana/)).toBeInTheDocument();
  expect(screen.getByText(/Ventas/)).toBeInTheDocument();
});
```

**Step 2: Extend StoryStep + buildTurnStory** with `agentName: string | null; agentRole: string | null`. `buildTurnStory` accepts an `agent?: { name: string; role: string | null }` in opts and threads it through.

**Step 3: DebugPanel fetches agent via `agentsApi.get(trace.agent_id)`** when set, and passes `{ agent }` to `buildTurnStory`. Use `useQuery` with `enabled: !!trace.agent_id` and large stale time.

**Step 4: Render in StepComposer** above the model/latency line:

```tsx
{step.agentName && (
  <div className="text-[11px] text-muted-foreground">
    Agente: <span className="font-medium text-foreground">{step.agentName}</span>
    {step.agentRole && <span> · {step.agentRole}</span>}
  </div>
)}
```

**Step 5: GREEN + commit.**

```bash
pnpm vitest run tests/features/turn-traces/AgentNameRole.test.tsx
git add frontend/src/features
git commit -m "feat(debug-panel): agent name + role in StepComposer (C2 item 2)"
```

---

## Task 9: Item 3 — Actions panel

**Files:**
- Modify: `frontend/src/features/turn-traces/lib/turnAnalysis.ts` (new `analyzeActions(trace)`)
- Modify: `frontend/src/features/turn-traces/components/TurnPanels.tsx` (new `ActionsPanel` export)
- Modify: `frontend/src/features/conversations/components/DebugPanel.tsx` (add `<ActionsPanel />` below KnowledgePanel)
- Test: `frontend/tests/features/turn-traces/ActionsPanel.test.tsx`

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ActionsPanel } from "@/features/turn-traces/components/TurnPanels";

const baseTrace = {
  // ... minimal stub of TurnTraceDetail ...
  composer_output: {
    messages: ["..."],
    action_payload: {
      quote: { plan: "Premium", monto_mensual: 2400, plazo_meses: 12 },
      lookup_faq: { faq_id: "abc", question: "¿Qué documentos?", score: 0.91 },
    },
  },
} as any;

describe("ActionsPanel", () => {
  it("renders one chip per action with a short preview", () => {
    render(<ActionsPanel trace={baseTrace} />);
    expect(screen.getByText("quote")).toBeInTheDocument();
    expect(screen.getByText("lookup_faq")).toBeInTheDocument();
    expect(screen.getByText(/Premium/)).toBeInTheDocument();
    expect(screen.getByText(/¿Qué documentos\?/)).toBeInTheDocument();
  });
  it("renders empty state when action_payload is empty/missing", () => {
    render(<ActionsPanel trace={{ ...baseTrace, composer_output: { messages: [] } }} />);
    expect(screen.getByText(/sin acciones/i)).toBeInTheDocument();
  });
});
```

**Step 2: Verify RED.**

**Step 3: Implement `analyzeActions`** in `turnAnalysis.ts`:

```typescript
export interface ActionItem {
  name: string;
  preview: string;
  raw: unknown;
}

export function analyzeActions(trace: TurnTraceDetail): ActionItem[] {
  const co = trace.composer_output as { action_payload?: Record<string, unknown> } | null;
  const payload = co?.action_payload;
  if (!payload || typeof payload !== "object") return [];
  return Object.entries(payload).map(([name, raw]) => ({
    name,
    preview: previewForAction(name, raw),
    raw,
  }));
}

function previewForAction(name: string, raw: unknown): string {
  if (raw == null || typeof raw !== "object") return String(raw ?? "");
  const obj = raw as Record<string, unknown>;
  if (name === "quote") {
    return `plan=${obj.plan} · monto=${obj.monto_mensual} · ${obj.plazo_meses}m`;
  }
  if (name === "lookup_faq") {
    const q = String(obj.question ?? "");
    return q.length > 60 ? `${q.slice(0, 60)}…` : q;
  }
  // fallback: first 2 key/value pairs
  return Object.entries(obj).slice(0, 2).map(([k, v]) => `${k}=${v}`).join(" · ");
}
```

**Step 4: Implement `ActionsPanel`** in `TurnPanels.tsx`:

```tsx
import { Zap } from "lucide-react";

export function ActionsPanel({ trace }: { trace: TurnTraceDetail }) {
  const actions = analyzeActions(trace);
  if (actions.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={Zap} title="Acciones" />
        <div className="text-xs text-muted-foreground">
          Sin acciones disparadas este turno.
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <PanelHeader icon={Zap} title="Acciones" count={actions.length} />
      <div className="space-y-1">
        {actions.map((a) => (
          <details key={a.name} className="rounded-md border bg-card text-xs">
            <summary className="cursor-pointer px-2 py-1.5">
              <span className="font-mono font-medium">{a.name}</span>
              <span className="ml-2 text-muted-foreground">· {a.preview}</span>
            </summary>
            <pre className="max-h-32 overflow-auto border-t bg-muted/30 p-2 text-[10px]">
              {JSON.stringify(a.raw, null, 2)}
            </pre>
          </details>
        ))}
      </div>
    </div>
  );
}
```

**Step 5: Wire into DebugPanel** (just below `<KnowledgePanel />`):

```tsx
<Separator />
<ActionsPanel trace={t} />
```

**Step 6: GREEN.**

```bash
pnpm vitest run tests/features/turn-traces/ActionsPanel.test.tsx
```

Expected: 2/2 PASS.

**Step 7: Commit.**

```bash
git add frontend/src/features frontend/tests/features/turn-traces/ActionsPanel.test.tsx
git commit -m "feat(debug-panel): actions panel listing composer action_payload (C2 item 3)"
```

---

## Task 10: Item 4 — Per-step latency breakdown

**Files:**
- Modify: `frontend/src/features/turn-traces/lib/turnAnalysis.ts` (extend existing `latencySlices`)
- Modify: `frontend/src/features/turn-traces/components/TurnPanels.tsx` (replace `LatencyStackedBar` with `LatencyPerStepBar`)
- Test: `frontend/tests/features/turn-traces/LatencyPerStep.test.tsx`

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LatencyPerStepBar } from "@/features/turn-traces/components/TurnPanels";

const trace = {
  nlu_latency_ms: 342,
  vision_latency_ms: 0,
  composer_latency_ms: 1820,
  tool_calls: [
    { latency_ms: 210 },
    { latency_ms: 211 },
  ],
  total_latency_ms: 2847,
} as any;

describe("LatencyPerStepBar", () => {
  it("renders one row per slice with percentages summing to ≤100%", () => {
    render(<LatencyPerStepBar trace={trace} />);
    expect(screen.getByText(/NLU/i)).toBeInTheDocument();
    expect(screen.getByText(/Composer/i)).toBeInTheDocument();
    expect(screen.getByText(/Tools/i)).toBeInTheDocument();
    expect(screen.getByText(/Overhead/i)).toBeInTheDocument();
    // Vision is 0 → omitted
    expect(screen.queryByText(/Vision/i)).not.toBeInTheDocument();
  });
});
```

**Step 2: Verify RED.**

**Step 3: Implement (or extend) `analyzeLatencyPerStep`**:

```typescript
export interface StepLatency {
  label: string;
  ms: number;
  pct: number;
}

export function analyzeLatencyPerStep(trace: TurnTraceDetail): StepLatency[] {
  const slices: Array<[string, number | null | undefined]> = [
    ["NLU", trace.nlu_latency_ms],
    ["Vision", trace.vision_latency_ms],
    ["Composer", trace.composer_latency_ms],
    [
      "Tools",
      (trace.tool_calls ?? []).reduce<number>(
        (acc, tc) => acc + (tc.latency_ms ?? 0),
        0,
      ),
    ],
  ];
  const total = trace.total_latency_ms ?? 0;
  const tracked = slices.reduce<number>((acc, [, ms]) => acc + (ms ?? 0), 0);
  const overhead = Math.max(0, total - tracked);
  const all: Array<[string, number]> = slices
    .filter(([, ms]) => (ms ?? 0) > 0)
    .map(([l, ms]) => [l, ms as number]);
  if (overhead > 0) all.push(["Overhead", overhead]);
  return all.map(([label, ms]) => ({
    label,
    ms,
    pct: total > 0 ? Math.round((ms / total) * 100) : 0,
  }));
}
```

**Step 4: Implement `LatencyPerStepBar`** (replace `LatencyStackedBar`'s rendering — keep export name `LatencyStackedBar` as alias if other code refs it):

```tsx
export function LatencyPerStepBar({ trace }: { trace: TurnTraceDetail }) {
  const slices = analyzeLatencyPerStep(trace);
  const total = trace.total_latency_ms ?? 0;
  if (slices.length === 0) return null;
  return (
    <div className="space-y-2">
      <PanelHeader icon={Clock} title={`Latencia · ${total}ms`} />
      <div className="space-y-1">
        {slices.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-[11px]">
            <span className="w-20 text-muted-foreground">{s.label}</span>
            <div className="relative h-2 flex-1 overflow-hidden rounded bg-muted">
              <div
                className="absolute inset-y-0 left-0 bg-primary/60"
                style={{ width: `${s.pct}%` }}
              />
            </div>
            <span className="w-16 text-right font-mono text-muted-foreground">
              {s.ms}ms
            </span>
            <span className="w-10 text-right font-mono text-muted-foreground">
              {s.pct}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Keep old name working for any importer.
export const LatencyStackedBar = LatencyPerStepBar;
```

**Step 5: GREEN + commit.**

```bash
pnpm vitest run tests/features/turn-traces/LatencyPerStep.test.tsx
git add frontend/src/features/turn-traces frontend/tests/features/turn-traces/LatencyPerStep.test.tsx
git commit -m "feat(debug-panel): per-step latency breakdown panel (C2 item 4)"
```

---

## Task 11: Item 7 — Prompt template breakdown

**Files:**
- Modify: `frontend/src/features/turn-traces/lib/turnAnalysis.ts` (new `analyzePromptTemplate`)
- Modify: `frontend/src/features/turn-traces/components/TurnPanels.tsx` (new `PromptTemplateBreakdown`)
- Modify: `DebugPanel.tsx` to mount it
- Test: `frontend/tests/features/turn-traces/PromptTemplateBreakdown.test.tsx`

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PromptTemplateBreakdown } from "@/features/turn-traces/components/TurnPanels";

const SAMPLE_PROMPT = `### IDENTIDAD
Eres Mariana, asesora de ventas.

### REGLAS QUE NO PUEDES ROMPER
- No inventes precios.

### CONOCIMIENTO DEL TENANT
FAQ 1: ...

### CONTEXTO DEL CLIENTE
Nombre: Pedro`;

describe("PromptTemplateBreakdown", () => {
  it("parses sections by ### markers and shows per-section size", () => {
    const trace = {
      composer_input: {
        messages: [{ role: "system", content: SAMPLE_PROMPT }],
      },
    } as any;
    render(<PromptTemplateBreakdown trace={trace} />);
    expect(screen.getByText(/IDENTIDAD/i)).toBeInTheDocument();
    expect(screen.getByText(/REGLAS/i)).toBeInTheDocument();
    expect(screen.getByText(/CONOCIMIENTO/i)).toBeInTheDocument();
    expect(screen.getByText(/CONTEXTO/i)).toBeInTheDocument();
  });
  it("renders empty state when no system prompt or no markers", () => {
    const trace = { composer_input: null } as any;
    render(<PromptTemplateBreakdown trace={trace} />);
    expect(screen.getByText(/sin prompt analizable/i)).toBeInTheDocument();
  });
});
```

**Step 2: Verify RED.**

**Step 3: Implement `analyzePromptTemplate`**:

```typescript
export interface PromptSection {
  title: string;
  chars: number;
  tokens: number; // chars / 4 estimate
  pct: number;
}

const SECTION_RE = /###\s+([^\n]+)/g;

export function analyzePromptTemplate(trace: TurnTraceDetail): PromptSection[] {
  const ci = trace.composer_input as { messages?: Array<{ role: string; content: string }> } | null;
  const sys = ci?.messages?.find((m) => m.role === "system")?.content;
  if (!sys) return [];
  // Find each ### header position
  const markers: Array<{ title: string; start: number }> = [];
  let m: RegExpExecArray | null;
  while ((m = SECTION_RE.exec(sys)) !== null) {
    markers.push({ title: m[1].trim(), start: m.index });
  }
  if (markers.length === 0) return [];
  // Slice content between consecutive markers
  const out: PromptSection[] = [];
  for (let i = 0; i < markers.length; i++) {
    const next = markers[i + 1]?.start ?? sys.length;
    const chars = next - markers[i].start;
    out.push({
      title: markers[i].title,
      chars,
      tokens: Math.round(chars / 4),
      pct: 0, // filled below
    });
  }
  const total = out.reduce((acc, s) => acc + s.chars, 0);
  for (const s of out) s.pct = total > 0 ? Math.round((s.chars / total) * 100) : 0;
  return out;
}
```

**Step 4: Implement `PromptTemplateBreakdown`** (icon: `FileText` or `BookOpen`). Render: section name + bar + tokens.

```tsx
export function PromptTemplateBreakdown({ trace }: { trace: TurnTraceDetail }) {
  const sections = analyzePromptTemplate(trace);
  if (sections.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={BookOpen} title="Anatomía del prompt" />
        <div className="text-xs text-muted-foreground">Sin prompt analizable.</div>
      </div>
    );
  }
  const totalTokens = sections.reduce((a, s) => a + s.tokens, 0);
  return (
    <div className="space-y-2">
      <PanelHeader icon={BookOpen} title={`Anatomía del prompt · ~${totalTokens} tokens`} />
      <div className="space-y-1">
        {sections.map((s) => (
          <div key={s.title} className="flex items-center gap-2 text-[11px]">
            <span className="w-32 truncate text-muted-foreground">{s.title}</span>
            <div className="relative h-2 flex-1 overflow-hidden rounded bg-muted">
              <div className="absolute inset-y-0 left-0 bg-violet-500/60" style={{ width: `${s.pct}%` }} />
            </div>
            <span className="w-12 text-right font-mono text-muted-foreground">{s.tokens}t</span>
            <span className="w-10 text-right font-mono text-muted-foreground">{s.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 5: Mount in DebugPanel** below `FactPackCard`:

```tsx
<Separator />
<PromptTemplateBreakdown trace={t} />
```

**Step 6: GREEN + commit.**

```bash
pnpm vitest run tests/features/turn-traces/PromptTemplateBreakdown.test.tsx
git add frontend/src/features frontend/tests/features/turn-traces/PromptTemplateBreakdown.test.tsx
git commit -m "feat(debug-panel): prompt template breakdown (C2 item 7)"
```

---

## Task 12: Item 8 — Tool calls timeline rich

**Files:**
- Modify: `frontend/src/features/turn-traces/components/TurnPanels.tsx` (new `ToolCallsTimeline`)
- Modify: `DebugPanel.tsx` (mount panel)
- Test: `frontend/tests/features/turn-traces/ToolCallsTimeline.test.tsx`

**Step 1: Failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ToolCallsTimeline } from "@/features/turn-traces/components/TurnPanels";

describe("ToolCallsTimeline", () => {
  it("renders one row per tool call with name + latency + status", () => {
    const trace = {
      tool_calls: [
        {
          id: "1", tool_name: "search_catalog", latency_ms: 421,
          input_payload: { query: "moto" }, output_payload: { hits: 3 }, error: null,
        },
        {
          id: "2", tool_name: "lookup_faq", latency_ms: 213,
          input_payload: { query: "horario" }, output_payload: null, error: "no match",
        },
      ],
    } as any;
    render(<ToolCallsTimeline trace={trace} />);
    expect(screen.getByText(/search_catalog/)).toBeInTheDocument();
    expect(screen.getByText(/421ms/)).toBeInTheDocument();
    expect(screen.getByText(/lookup_faq/)).toBeInTheDocument();
    expect(screen.getByText(/no match/i)).toBeInTheDocument();
  });
  it("renders empty state when no tool calls", () => {
    render(<ToolCallsTimeline trace={{ tool_calls: [] } as any} />);
    expect(screen.getByText(/sin herramientas/i)).toBeInTheDocument();
  });
});
```

**Step 2: Verify RED.**

**Step 3: Implement `ToolCallsTimeline`** in `TurnPanels.tsx`. No analyzer needed — data shape is already flat.

```tsx
export function ToolCallsTimeline({ trace }: { trace: TurnTraceDetail }) {
  const calls = trace.tool_calls ?? [];
  if (calls.length === 0) {
    return (
      <div className="space-y-2">
        <PanelHeader icon={Wrench} title="Herramientas" />
        <div className="text-xs text-muted-foreground">
          Sin herramientas llamadas este turno.
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <PanelHeader icon={Wrench} title="Herramientas" count={calls.length} />
      <div className="space-y-1.5">
        {calls.map((c) => (
          <div key={c.id} className="rounded-md border bg-card p-2 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="font-mono font-medium">{c.tool_name}</span>
              <span className="flex items-center gap-1.5 text-muted-foreground">
                {c.latency_ms != null && <span>{c.latency_ms}ms</span>}
                {c.error ? (
                  <Badge variant="outline" className="border-rose-500/40 bg-rose-500/10 text-rose-700">
                    error
                  </Badge>
                ) : (
                  <Badge variant="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-700">
                    ok
                  </Badge>
                )}
              </span>
            </div>
            {c.error && (
              <div className="mt-1 text-rose-700">{c.error}</div>
            )}
            {!c.error && (
              <details className="mt-1">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                  input / output
                </summary>
                <pre className="mt-1 max-h-32 overflow-auto rounded bg-muted/30 p-2 text-[10px]">
                  {JSON.stringify({ input: c.input_payload, output: c.output_payload }, null, 2)}
                </pre>
              </details>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

Import `Wrench` from `lucide-react` at the top of TurnPanels.tsx.

**Step 4: Mount in DebugPanel** below `LatencyPerStepBar` / `CostBreakdown`:

```tsx
<Separator />
<ToolCallsTimeline trace={t} />
```

**Step 5: GREEN + commit.**

```bash
pnpm vitest run tests/features/turn-traces/ToolCallsTimeline.test.tsx
git add frontend/src/features frontend/tests/features/turn-traces/ToolCallsTimeline.test.tsx
git commit -m "feat(debug-panel): tool calls timeline panel (C2 item 8)"
```

---

## Task 13: Final regression + verification

**Step 1: Backend full regression**

```bash
cd core
uv run pytest tests/api tests/runner tests/state_machine tests/queue -q
```

Expected: all green (pre-existing 6 e2e fixture failures + 1 schema test are ok).

**Step 2: Frontend full regression**

```bash
cd frontend
pnpm vitest run
```

Expected: only the 6 pre-existing `DocumentRuleBuilder` failures remain. All new C2 tests pass.

**Step 3: Update ESTADO-Y-GAPS.md**

In `docs/ESTADO-Y-GAPS.md`, strike-through gap C2 in §2.3 and add to §0bis a new bullet for "Sprint C2 entregado" with the 8 sub-commits.

**Step 4: Verify migration applied**

```bash
cd core
uv run alembic current
```

Expected: `n1b2c3d4e5f6 (head)`.

**Step 5: Final commit + push**

```bash
git add docs/ESTADO-Y-GAPS.md
git commit -m "docs(state): mark C2 (DebugPanel) as closed in ESTADO-Y-GAPS"
```

---

## Done

Plan complete and saved to `docs/plans/2026-05-15-debugpanel-c2-implementation.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Parallel Session (separate)** — Open a new session with executing-plans, batch execution with checkpoints.

**Which approach?**

# W6 + W8 Workflow Nodes — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or superpowers:subagent-driven-development for same-session execution).

**Goal:** Land 2 new workflow node types (`trigger_workflow` for W6 sub-workflows, `ask_question` for W8 paused user-input flows) with engine support, recursion guard, MESSAGE_RECEIVED-driven resume, and minimum-viable UI config forms.

**Architecture:** Migration 051 adds 2 nullable columns to `workflow_executions` (`parent_execution_id`, `awaiting_variable`). Engine gets 2 new `_node_*` functions + a recursion-detection helper + resume hook in `evaluate_event`. Frontend gets 2 new node config forms in WorkflowEditor.

**Tech Stack:** SQLAlchemy 2.0 async · Alembic · FastAPI · pytest-asyncio · React 19 · TanStack Query · Vitest.

**Design doc:** `docs/plans/2026-05-15-w6-w8-workflows-design.md`

---

## Task 1: Migration 051 — workflow_executions schema

**Files:**
- Create: `core/atendia/db/migrations/versions/051_workflow_executions_w6_w8.py`
- Modify: `core/atendia/db/models/workflow.py` (add 2 mapped columns to `WorkflowExecution`)

**Step 1: Write migration**

Create the file with:

```python
"""051_workflow_executions_w6_w8

Revision ID: q3e4f5g6h7i8
Revises: p2d3e4f5g6h7
Create Date: 2026-05-15

W6+W8 — workflow_executions gains two nullable columns + a self-FK:

* parent_execution_id (UUID, FK → workflow_executions.id) — set when a
  trigger_workflow node creates a child execution. Walked at execute
  time to detect recursion.
* awaiting_variable (String(80)) — set by ask_question when it pauses
  the execution. The MESSAGE_RECEIVED handler reads this to know
  which variable to fill on resume.

Both nullable so legacy executions stay valid. ON DELETE SET NULL on
the parent FK so deleting an old parent execution doesn't cascade
through child history.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q3e4f5g6h7i8"
down_revision: str | Sequence[str] | None = "p2d3e4f5g6h7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_executions",
        sa.Column(
            "parent_execution_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_workflow_executions_parent",
        "workflow_executions",
        "workflow_executions",
        ["parent_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_workflow_executions_parent",
        "workflow_executions",
        ["parent_execution_id"],
    )
    op.add_column(
        "workflow_executions",
        sa.Column("awaiting_variable", sa.String(80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_executions", "awaiting_variable")
    op.drop_index("ix_workflow_executions_parent", table_name="workflow_executions")
    op.drop_constraint(
        "fk_workflow_executions_parent",
        "workflow_executions",
        type_="foreignkey",
    )
    op.drop_column("workflow_executions", "parent_execution_id")
```

**Step 2: Add mapped columns**

In `core/atendia/db/models/workflow.py`, inside `WorkflowExecution` (after `error_code`):

```python
    # Migration 051 (W6/W8). Both nullable; set by the engine when a
    # trigger_workflow node fires a child (parent_execution_id) or an
    # ask_question node pauses awaiting customer input
    # (awaiting_variable).
    parent_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="SET NULL"),
        index=True,
    )
    awaiting_variable: Mapped[str | None] = mapped_column(String(80))
```

**Step 3: Apply + verify**

```bash
cd core
uv run alembic upgrade head
```

Expected last line: `Running upgrade p2d3e4f5g6h7 -> q3e4f5g6h7i8`.

Verify schema:

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
            \"WHERE table_name='workflow_executions' \"
            \"AND column_name IN ('parent_execution_id', 'awaiting_variable')\"
        ))).all()
        for r in rows: print(r)
    await e.dispose()
asyncio.run(main())
"
```

Expected: 2 rows, both `YES` nullable.

**Step 4: Format + commit**

```bash
cd core
uv run ruff format atendia/db/migrations/versions/051_workflow_executions_w6_w8.py atendia/db/models/workflow.py
```

```bash
cd ..
git add core/atendia/db/migrations/versions/051_workflow_executions_w6_w8.py core/atendia/db/models/workflow.py
git commit -m "feat(db): migration 051 — workflow_executions.parent_execution_id + awaiting_variable (W6/W8 Task 1)"
```

---

## Task 2: Engine — recursion detection helper + NODE_TYPES

**Files:**
- Modify: `core/atendia/workflows/engine.py` (add `_detects_workflow_recursion`, register 2 new NODE_TYPES)
- Test: `core/tests/workflows/test_workflow_recursion_detection.py` (new)

**Step 1: Failing test FIRST**

Create `core/tests/workflows/test_workflow_recursion_detection.py`:

```python
"""W6 — recursion guard for trigger_workflow node.

Walks parent_execution_id chain. Returns True if the target workflow
id appears anywhere in the chain (or matches the immediate parent).
Capped at depth 5 to prevent infinite loops from corrupt data."""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings


@pytest.fixture
def workflow_chain() -> tuple[str, list[str]]:
    """Insert a tenant + 3 workflows + a linear execution chain
    (root → middle → leaf) all sharing tenant + conversation. Yields
    (tenant_id, [workflow_root, workflow_middle, workflow_leaf,
     execution_root, execution_middle, execution_leaf]).
    Cleaned up after."""

    async def _seed() -> tuple[str, list[str]]:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                tid = (await conn.execute(text(
                    "INSERT INTO tenants (name) VALUES (:n) RETURNING id"
                ), {"n": f"w6_recursion_{uuid4().hex[:8]}"})).scalar()
                wf_ids = []
                for label in ("root", "middle", "leaf"):
                    wid = (await conn.execute(text(
                        "INSERT INTO workflows (tenant_id, name, definition, status, "
                        " is_enabled) "
                        "VALUES (:t, :n, CAST('{}' AS jsonb), 'active', true) "
                        "RETURNING id"
                    ), {"t": tid, "n": f"wf_{label}_{uuid4().hex[:6]}"})).scalar()
                    wf_ids.append(str(wid))
                # Linear chain: root execution → middle execution
                #   (parent=root) → leaf execution (parent=middle)
                exec_ids = []
                prev = None
                for wid in wf_ids:
                    eid = (await conn.execute(text(
                        "INSERT INTO workflow_executions "
                        "(workflow_id, status, parent_execution_id) "
                        "VALUES (:w, 'running', :p) RETURNING id"
                    ), {"w": wid, "p": prev})).scalar()
                    exec_ids.append(str(eid))
                    prev = eid
            return str(tid), wf_ids + exec_ids
        finally:
            await e.dispose()

    async def _cleanup(tid: str) -> None:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await e.dispose()

    tid, ids = asyncio.run(_seed())
    yield tid, ids
    asyncio.run(_cleanup(tid))


async def test_detects_recursion_when_target_is_self(workflow_chain):
    """If a workflow tries to trigger itself, the guard fires
    immediately — without walking the parent chain at all."""
    from atendia.db.models.workflow import WorkflowExecution
    from atendia.workflows.engine import _detects_workflow_recursion

    tid, ids = workflow_chain
    wf_root, _, _, exec_root, _, _ = ids
    sm = async_sessionmaker(create_async_engine(get_settings().database_url),
                            expire_on_commit=False)
    async with sm() as session:
        from sqlalchemy import select
        execution = (await session.execute(
            select(WorkflowExecution).where(WorkflowExecution.id == exec_root)
        )).scalar_one()
        assert await _detects_workflow_recursion(
            session, execution, UUID(wf_root)
        ) is True


async def test_detects_recursion_in_ancestor(workflow_chain):
    """leaf execution tries to trigger workflow_root — root is an
    ancestor of leaf, so the guard fires."""
    from atendia.db.models.workflow import WorkflowExecution
    from atendia.workflows.engine import _detects_workflow_recursion

    tid, ids = workflow_chain
    wf_root, _, _, _, _, exec_leaf = ids
    sm = async_sessionmaker(create_async_engine(get_settings().database_url),
                            expire_on_commit=False)
    async with sm() as session:
        from sqlalchemy import select
        leaf_exec = (await session.execute(
            select(WorkflowExecution).where(WorkflowExecution.id == exec_leaf)
        )).scalar_one()
        assert await _detects_workflow_recursion(
            session, leaf_exec, UUID(wf_root)
        ) is True


async def test_no_recursion_for_unrelated_target(workflow_chain):
    """leaf execution triggers a completely different workflow not
    in its parent chain — no recursion."""
    from atendia.db.models.workflow import WorkflowExecution
    from atendia.workflows.engine import _detects_workflow_recursion

    tid, ids = workflow_chain
    sm = async_sessionmaker(create_async_engine(get_settings().database_url),
                            expire_on_commit=False)
    async with sm() as session:
        from sqlalchemy import select
        _, _, _, _, _, exec_leaf = ids
        leaf_exec = (await session.execute(
            select(WorkflowExecution).where(WorkflowExecution.id == exec_leaf)
        )).scalar_one()
        # A fresh UUID — not in the chain
        unrelated = uuid4()
        assert await _detects_workflow_recursion(
            session, leaf_exec, unrelated
        ) is False
```

**Step 2: Verify RED**

```bash
cd core
uv run pytest tests/workflows/test_workflow_recursion_detection.py -v
```

Expected: ImportError (`_detects_workflow_recursion` doesn't exist).

**Step 3: Implement**

In `core/atendia/workflows/engine.py`:

a) **Add to NODE_TYPES** frozenset:

```python
NODE_TYPES = frozenset({
    # ... existing entries ...
    "trigger_workflow",
    "ask_question",
})
```

b) **Add the helper** (near `_eval_group` / `_eval_rule`):

```python
async def _detects_workflow_recursion(
    session: AsyncSession,
    parent_execution: WorkflowExecution,
    target_workflow_id: UUID,
    max_depth: int = 5,
) -> bool:
    """W6 — walk parent_execution_id chain. True if target_workflow_id
    appears as workflow_id of any ancestor (or of the current parent
    execution itself). Max depth caps the walk."""
    if parent_execution.workflow_id == target_workflow_id:
        return True
    current = parent_execution.parent_execution_id
    for _ in range(max_depth):
        if current is None:
            return False
        row = (
            await session.execute(
                select(
                    WorkflowExecution.workflow_id,
                    WorkflowExecution.parent_execution_id,
                ).where(WorkflowExecution.id == current)
            )
        ).first()
        if row is None:
            return False
        if row.workflow_id == target_workflow_id:
            return True
        current = row.parent_execution_id
    return False
```

**Step 4: Verify GREEN + commit**

```bash
uv run pytest tests/workflows/test_workflow_recursion_detection.py -v
```

Expected: 3/3 PASS.

```bash
uv run ruff format atendia/workflows/engine.py tests/workflows/test_workflow_recursion_detection.py
cd ..
git add core/atendia/workflows/engine.py core/tests/workflows/test_workflow_recursion_detection.py
git commit -m "feat(workflows): recursion detection + NODE_TYPES for W6/W8 (W6/W8 Task 2)"
```

---

## Task 3: Engine — `_node_trigger_workflow`

**Files:**
- Modify: `core/atendia/workflows/engine.py` (add `_node_trigger_workflow` + dispatch case)
- Test: `core/tests/workflows/test_node_trigger_workflow.py` (new)

**Step 1: Failing tests**

```python
"""W6 — trigger_workflow node creates a child execution, sets the
parent_execution_id, and continues fire-and-forget."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings


@pytest.fixture
def two_workflows() -> tuple[str, str, str]:
    """Insert a tenant + 2 workflows (parent + child). Yields
    (tenant_id, parent_workflow_id, child_workflow_id)."""

    async def _seed() -> tuple[str, str, str]:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                tid = (await conn.execute(text(
                    "INSERT INTO tenants (name) VALUES (:n) RETURNING id"
                ), {"n": f"w6_trigger_{uuid4().hex[:8]}"})).scalar()
                child_def = {
                    "nodes": [{"id": "n1", "type": "end", "config": {}}],
                    "edges": [],
                }
                child_wid = (await conn.execute(text(
                    "INSERT INTO workflows "
                    "(tenant_id, name, definition, status, is_enabled) "
                    "VALUES (:t, 'child', CAST(:d AS jsonb), 'active', true) "
                    "RETURNING id"
                ), {"t": tid, "d": __import__("json").dumps(child_def)})).scalar()
                parent_def = {
                    "nodes": [
                        {"id": "trig", "type": "trigger_workflow",
                         "config": {"target_workflow_id": str(child_wid)}},
                        {"id": "end", "type": "end", "config": {}},
                    ],
                    "edges": [{"from": "trig", "to": "end"}],
                }
                parent_wid = (await conn.execute(text(
                    "INSERT INTO workflows "
                    "(tenant_id, name, definition, status, is_enabled) "
                    "VALUES (:t, 'parent', CAST(:d AS jsonb), 'active', true) "
                    "RETURNING id"
                ), {"t": tid, "d": __import__("json").dumps(parent_def)})).scalar()
            return str(tid), str(parent_wid), str(child_wid)
        finally:
            await e.dispose()

    async def _cleanup(tid: str) -> None:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                await conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
        finally:
            await e.dispose()

    tid, parent, child = asyncio.run(_seed())
    yield tid, parent, child
    asyncio.run(_cleanup(tid))


async def test_trigger_workflow_creates_child_execution(two_workflows):
    """Happy path: trigger_workflow node creates a child execution
    with parent_execution_id set and status 'running'."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _node_trigger_workflow

    tid, parent_wid, child_wid = two_workflows
    sm = async_sessionmaker(create_async_engine(get_settings().database_url),
                            expire_on_commit=False)
    async with sm() as session:
        parent_wf = (await session.execute(
            select(Workflow).where(Workflow.id == parent_wid)
        )).scalar_one()
        parent_exec = WorkflowExecution(workflow_id=parent_wf.id, status="running")
        session.add(parent_exec)
        await session.flush()

        node = {"id": "trig", "type": "trigger_workflow",
                "config": {"target_workflow_id": child_wid}}
        await _node_trigger_workflow(
            session, parent_wf, parent_exec, node, node["config"],
        )
        await session.commit()

        children = (await session.execute(
            select(WorkflowExecution).where(
                WorkflowExecution.parent_execution_id == parent_exec.id
            )
        )).scalars().all()
        assert len(children) == 1
        assert str(children[0].workflow_id) == child_wid
        assert children[0].status == "running"


async def test_trigger_workflow_rejects_missing_target(two_workflows):
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _ExecutionFailure, _node_trigger_workflow

    tid, parent_wid, _ = two_workflows
    sm = async_sessionmaker(create_async_engine(get_settings().database_url),
                            expire_on_commit=False)
    async with sm() as session:
        parent_wf = (await session.execute(
            select(Workflow).where(Workflow.id == parent_wid)
        )).scalar_one()
        parent_exec = WorkflowExecution(workflow_id=parent_wf.id, status="running")
        session.add(parent_exec)
        await session.flush()
        node = {"id": "trig", "type": "trigger_workflow", "config": {}}
        with pytest.raises(_ExecutionFailure) as exc:
            await _node_trigger_workflow(
                session, parent_wf, parent_exec, node, node["config"],
            )
        assert exc.value.code == "MISSING_TARGET_WORKFLOW"


async def test_trigger_workflow_rejects_recursion(two_workflows):
    """A workflow that triggers itself → WORKFLOW_RECURSION."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _ExecutionFailure, _node_trigger_workflow

    tid, parent_wid, _ = two_workflows
    sm = async_sessionmaker(create_async_engine(get_settings().database_url),
                            expire_on_commit=False)
    async with sm() as session:
        parent_wf = (await session.execute(
            select(Workflow).where(Workflow.id == parent_wid)
        )).scalar_one()
        parent_exec = WorkflowExecution(workflow_id=parent_wf.id, status="running")
        session.add(parent_exec)
        await session.flush()
        node = {"id": "trig", "type": "trigger_workflow",
                "config": {"target_workflow_id": parent_wid}}  # SELF
        with pytest.raises(_ExecutionFailure) as exc:
            await _node_trigger_workflow(
                session, parent_wf, parent_exec, node, node["config"],
            )
        assert exc.value.code == "WORKFLOW_RECURSION"


async def test_trigger_workflow_rejects_other_tenant(two_workflows):
    """Target workflow_id that belongs to a different tenant → not found."""
    from atendia.db.models.workflow import Workflow, WorkflowExecution
    from atendia.workflows.engine import _ExecutionFailure, _node_trigger_workflow

    tid, parent_wid, _ = two_workflows
    # Create a separate tenant + workflow
    async def _seed_other() -> str:
        e = create_async_engine(get_settings().database_url)
        try:
            async with e.begin() as conn:
                other_tid = (await conn.execute(text(
                    "INSERT INTO tenants (name) VALUES (:n) RETURNING id"
                ), {"n": f"w6_other_{uuid4().hex[:8]}"})).scalar()
                wid = (await conn.execute(text(
                    "INSERT INTO workflows "
                    "(tenant_id, name, definition, status, is_enabled) "
                    "VALUES (:t, 'foreign', CAST('{}' AS jsonb), 'active', true) "
                    "RETURNING id"
                ), {"t": other_tid})).scalar()
            return str(wid)
        finally:
            await e.dispose()
    foreign_wid = asyncio.run(_seed_other())

    sm = async_sessionmaker(create_async_engine(get_settings().database_url),
                            expire_on_commit=False)
    try:
        async with sm() as session:
            parent_wf = (await session.execute(
                select(Workflow).where(Workflow.id == parent_wid)
            )).scalar_one()
            parent_exec = WorkflowExecution(workflow_id=parent_wf.id, status="running")
            session.add(parent_exec)
            await session.flush()
            node = {"id": "trig", "type": "trigger_workflow",
                    "config": {"target_workflow_id": foreign_wid}}
            with pytest.raises(_ExecutionFailure) as exc:
                await _node_trigger_workflow(
                    session, parent_wf, parent_exec, node, node["config"],
                )
            assert exc.value.code == "TARGET_WORKFLOW_NOT_FOUND"
    finally:
        # Clean up foreign tenant
        async def _cleanup() -> None:
            e = create_async_engine(get_settings().database_url)
            try:
                async with e.begin() as conn:
                    await conn.execute(text(
                        "DELETE FROM tenants WHERE name LIKE 'w6_other_%'"
                    ))
            finally:
                await e.dispose()
        asyncio.run(_cleanup())
```

**Step 2: RED → Implement → GREEN**

Implement `_node_trigger_workflow` per design doc §2.2. Add dispatch case in `_execute_node`:

```python
elif node_type == "trigger_workflow":
    await _node_trigger_workflow(session, workflow, execution, node, config)
```

Run tests:

```bash
cd core
uv run pytest tests/workflows/test_node_trigger_workflow.py -v
```

Expected: 4/4 PASS.

**Step 3: Commit**

```bash
uv run ruff format atendia/workflows/engine.py tests/workflows/test_node_trigger_workflow.py
cd ..
git add core/atendia/workflows/engine.py core/tests/workflows/test_node_trigger_workflow.py
git commit -m "feat(workflows): _node_trigger_workflow — fire-and-forget sub-workflow (W6 Task 3)"
```

---

## Task 4: Engine — `_node_ask_question` + resume mechanism

**Files:**
- Modify: `core/atendia/workflows/engine.py` (add `_node_ask_question`, `_resume_paused_execution`, hook in `evaluate_event`)
- Test: `core/tests/workflows/test_node_ask_question.py` (new)

This is the biggest task. ~5 tests. Implement per design §2.3 and §2.4.

**Tests to write:**
1. `test_ask_question_pauses_execution` — after the node runs, execution.status == "waiting_for_response" and execution.awaiting_variable is set
2. `test_ask_question_rejects_missing_fields` — config without question or variable → `MISSING_ASK_QUESTION_FIELDS`
3. `test_ask_question_resumes_on_message_received` — second turn: MESSAGE_RECEIVED arrives → variable saved + execution advances to next node + status back to "running"
4. `test_ask_question_isolated_per_conversation` — paused execution in conv A is NOT resumed by message in conv B
5. `test_ask_question_persists_outbound_message` — the question text actually lands in messages table (or whatever the outbound persistence is)

**Implementation:**
- `_node_ask_question` per design § 2.3
- `_resume_paused_execution` per design § 2.4
- In `evaluate_event`, AFTER the existing trigger-evaluation logic, add the paused-execution sweep per design § 2.4

Dispatch case in `_execute_node`:

```python
elif node_type == "ask_question":
    return await _node_ask_question(session, workflow, execution, node, config)
```

Note: returns `None` to break the dispatch loop. Make sure `_execute_node` actually respects None return.

**Commit:**

```
feat(workflows): _node_ask_question + MESSAGE_RECEIVED resume hook (W8 Task 4)
```

---

## Task 5: Engine validator updates

The `validate_definition` function in `engine.py` (around line 175-220) checks node types via NODE_TYPES. With the 2 new types added in Task 2, NODE_TYPES already includes them. BUT the validator should also enforce per-type config:

- `trigger_workflow`: requires `config.target_workflow_id` to be a valid UUID
- `ask_question`: requires `config.question` (non-empty str) AND `config.variable` (slug)

**Files:**
- Modify: `core/atendia/workflows/engine.py` (extend `validate_definition`)
- Test: extend `core/tests/workflows/test_workflow_validation.py` (or wherever validation tests live; create if needed)

Tests:
1. `test_validate_rejects_trigger_workflow_without_target` — definition with `trigger_workflow` node missing `target_workflow_id` raises `WorkflowValidationError`
2. `test_validate_rejects_ask_question_without_variable` — definition with `ask_question` node missing `variable` raises
3. `test_validate_accepts_well_formed_trigger_workflow` — happy path
4. `test_validate_accepts_well_formed_ask_question` — happy path

Implement the validator extensions (small, inline in the existing per-type validator switch).

Commit: `feat(workflows): validation rules for trigger_workflow + ask_question (W6/W8 Task 5)`

---

## Task 6: Frontend — `TurnTraceDetail` types unrelated, skip

(This task slot reused — frontend types don't need updates since workflow definitions are stored as opaque JSONB on the API.)

---

## Task 6 (renumbered): Frontend — `trigger_workflow` node config form

**Files:**
- Modify: `frontend/src/features/workflows/components/WorkflowEditor.tsx` (add form block for trigger_workflow)
- Test: `frontend/tests/features/workflows/TriggerWorkflowNodeForm.test.tsx` (new — render test only, behavior tests deferred)

Find the existing node-type form switch in WorkflowEditor (`message`, `delay`, etc.). Add a new branch for `trigger_workflow`:

- Dropdown sourced from `workflowsApi.list()` query
- Filter out `workflow.id` itself (no self-recursion at edit-time)
- Helper text about MVP scope
- Calls onChange with `{ target_workflow_id }`

Test:
- Renders the dropdown
- Shows helper text
- Calls onChange when an option is selected

Commit: `feat(workflows): trigger_workflow node config form (W6 Task 6)`

---

## Task 7: Frontend — `ask_question` node config form

**Files:**
- Modify: `frontend/src/features/workflows/components/WorkflowEditor.tsx`
- Test: `frontend/tests/features/workflows/AskQuestionNodeForm.test.tsx` (new)

Add a form block for `ask_question`:
- Textarea for question
- Input for variable name (alphanumeric_underscore validation)
- Type select (only `text` enabled; others disabled with tooltip)
- Calls onChange with `{ question, variable, type: "text" }`

Test renders + variable-name validation logic.

Commit: `feat(workflows): ask_question node config form (W8 Task 7)`

---

## Task 8: Final regression + ESTADO-Y-GAPS update

**Steps:**

1. Backend full regression: `cd core && uv run pytest tests/ -q --ignore=tests/integration | tail -5`. Expected: same 8 baseline failures, all new W6/W8 tests passing.
2. Frontend full regression: `cd frontend && pnpm vitest run`. Expected: same 6 baseline failures, all new W6/W8 tests passing.
3. Typecheck: `pnpm typecheck 2>&1 | grep "error TS" | wc -l`. Expected: 2 (baseline since D10).
4. Update `docs/ESTADO-Y-GAPS.md`:
   - Add new §0bis subsection "Quick wins + W6/W8 entregados" combining D9/D10/D11 + W6/W8 into a single chronological table
   - Strike-through W6 + W8 rows in §5.3 (mirror the pattern for ~~C2~~, ~~C10~~, etc.)
   - Update §9 decision matrix: mark D9, D10, D11 as ✅ DONE
   - Update §10 verification block with new test invocations

Commit: `docs(state): mark W6/W8 + D9/D10/D11 as closed in ESTADO-Y-GAPS`

---

## Done

Plan complete. 8 tasks. Execution mode: subagent-driven within current session.

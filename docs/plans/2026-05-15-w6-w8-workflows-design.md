# Workflow node types: W6 (sub-workflow) + W8 (ask-question) — design

> **Estado:** approved (2026-05-15)
> **Cierra:** items W6 y W8 de `docs/ESTADO-Y-GAPS.md` §5.3
> **Próximo:** implementation plan (`2026-05-15-w6-w8-workflows-implementation.md`)

---

## 0. TL;DR

Añadir 2 node types al engine de workflows:

- **`trigger_workflow`** (W6) — fire-and-forget invoke de otro workflow del mismo tenant
- **`ask_question`** (W8) — pausa el flow esperando la próxima inbound del cliente, guarda en variable

Ambos comparten una migración (`051`) que extiende `workflow_executions` con 2 columnas + un status valor nuevo.

**Costo estimado:** 1 sesión (~12 tasks atómicos TDD, ~4h real).

---

## 1. Por qué importan

Del audit (§5.3):

| Item | Cita |
|---|---|
| W6 | "Sub-workflow step ('Trigger Another Workflow' tipo respond.io)" — respond.io lo tiene, AtendIA no. Compone workflows, multiplica reuso. |
| W8 | "Ask Question step (espera respuesta del cliente, valida tipo, guarda en variable)" — step básico de respond.io que no tenemos. |

**Use cases reales que desbloquean:**

* **W6**: "Cuando se crea una cita → triggerea el workflow de recordatorios". Hoy hay que copy-paste cada cadena de pasos en cada workflow.
* **W8**: "Pregunta al cliente su email → guarda → continúa con el siguiente paso". Hoy el bot tiene que improvisar o el operador lo arma manualmente.

---

## 2. Arquitectura

### 2.1 Migración 051 (aditiva, nullable)

```python
# core/atendia/db/migrations/versions/051_workflow_executions_w6_w8.py

def upgrade() -> None:
    # W6 — parent execution chain. Walked at execute-time to detect
    # recursion: a target workflow that's already in the ancestor chain
    # gets rejected with WORKFLOW_RECURSION.
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

    # W8 — when the engine pauses on an ask_question node, it stores the
    # variable name it's waiting to fill. The MESSAGE_RECEIVED handler
    # reads this to know "save the next inbound into variable X and
    # resume". NULL on every execution that isn't paused.
    op.add_column(
        "workflow_executions",
        sa.Column("awaiting_variable", sa.String(80), nullable=True),
    )
```

**Status enum**: el campo `status` es `String(20)` sin CHECK constraint en migración 042 (workflow_executions creation). El runtime ya tolera estados arbitrarios (`running`, `paused` por delay, `completed`, `failed`). Añadimos `waiting_for_response` SIN una nueva CHECK constraint para minimizar blast radius — el runtime es el authoritative validator.

### 2.2 Engine: `_node_trigger_workflow` (W6)

```python
async def _node_trigger_workflow(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    config: dict,
) -> None:
    """W6 — fire-and-forget child workflow.

    Looks up the target workflow (same tenant), enforces recursion
    guard (no ancestor with the same workflow_id), creates a new
    WorkflowExecution with parent_execution_id set, and enqueues
    its first node. The parent execution then continues without
    waiting — caller fans out, doesn't await.
    """
    target_id = config.get("target_workflow_id")
    if not target_id:
        raise _ExecutionFailure(
            "trigger_workflow requires target_workflow_id",
            code="MISSING_TARGET_WORKFLOW",
        )
    # 1. Recursion guard: walk parent chain
    if await _detects_workflow_recursion(session, execution, target_id):
        raise _ExecutionFailure(
            f"workflow {target_id} already in ancestor chain — refusing to recurse",
            code="WORKFLOW_RECURSION",
        )
    # 2. Load + validate target (same tenant)
    target = (await session.execute(
        select(Workflow).where(
            Workflow.id == target_id,
            Workflow.tenant_id == workflow.tenant_id,
        )
    )).scalar_one_or_none()
    if target is None:
        raise _ExecutionFailure(
            f"target workflow {target_id} not found in tenant",
            code="TARGET_WORKFLOW_NOT_FOUND",
        )
    # 3. Create child execution + enqueue
    child = WorkflowExecution(
        workflow_id=target.id,
        conversation_id=execution.conversation_id,
        customer_id=execution.customer_id,
        parent_execution_id=execution.id,
        status="running",
        current_node_id=_first_node_id(target.definition),
    )
    session.add(child)
    await session.flush()  # need child.id
    await _enqueue_workflow_step(
        child.id,
        child.current_node_id,
        defer_seconds=0,
        node_id=child.current_node_id,
    )
    # 4. Parent continues (fire-and-forget)
```

**Recursion guard** walks the parent chain with a SQL CTE or iterative SELECT, capping at depth 5.

```python
async def _detects_workflow_recursion(
    session: AsyncSession,
    parent_execution: WorkflowExecution,
    target_workflow_id: UUID,
    max_depth: int = 5,
) -> bool:
    """Walk parent_execution_id chain. True if target_workflow_id
    appears as the workflow_id of any ancestor (or of the current
    parent itself). Max depth caps the walk to prevent infinite loops
    from corrupt data."""
    if parent_execution.workflow_id == target_workflow_id:
        return True
    current_parent_id = parent_execution.parent_execution_id
    for _ in range(max_depth):
        if current_parent_id is None:
            return False
        row = (await session.execute(
            select(
                WorkflowExecution.workflow_id,
                WorkflowExecution.parent_execution_id,
            ).where(WorkflowExecution.id == current_parent_id)
        )).first()
        if row is None:
            return False
        if row.workflow_id == target_workflow_id:
            return True
        current_parent_id = row.parent_execution_id
    return False  # depth cap reached, assume no recursion
```

### 2.3 Engine: `_node_ask_question` (W8)

```python
async def _node_ask_question(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    config: dict,
) -> str | None:
    """W8 — pause the execution waiting for the customer's next message.

    Sends the question via the standard outbound path (same as
    _node_message), marks the execution `waiting_for_response`,
    stores the awaiting_variable, and returns None so the engine
    breaks the dispatch loop. Resume is driven by the
    MESSAGE_RECEIVED handler — see _resume_paused_executions.
    """
    question = config.get("question")
    variable = config.get("variable")
    if not question or not variable:
        raise _ExecutionFailure(
            "ask_question requires question + variable",
            code="MISSING_ASK_QUESTION_FIELDS",
        )
    # 1. Send the question (reuse the message node's outbound path)
    await _send_outbound_text(session, execution, question)
    # 2. Pause + record what we're waiting for
    execution.status = "waiting_for_response"
    execution.awaiting_variable = variable
    execution.current_node_id = node["id"]
    # 3. Return None to break the dispatch loop
    return None
```

### 2.4 Engine: resume from MESSAGE_RECEIVED

`evaluate_event(session, event_id)` already gets called from the runner inline (commit `2`). Today it scans triggers and starts NEW executions matching `message_received`. We extend it to ALSO check for paused executions:

```python
async def evaluate_event(session, event_id):
    # ... existing trigger-evaluation logic ...

    # W8 — resume any execution paused on ask_question for this
    # conversation. Multiple paused executions per conversation
    # is allowed but rare; resume each in order of started_at.
    if event.type == EventType.MESSAGE_RECEIVED:
        paused = (await session.execute(
            select(WorkflowExecution)
            .where(
                WorkflowExecution.conversation_id == event.conversation_id,
                WorkflowExecution.status == "waiting_for_response",
                WorkflowExecution.awaiting_variable.is_not(None),
            )
            .order_by(WorkflowExecution.started_at)
        )).scalars().all()
        for exec in paused:
            await _resume_paused_execution(session, exec, event.payload.get("text", ""))
    # ... rest of existing logic
```

```python
async def _resume_paused_execution(session, execution, customer_message: str):
    """Save customer_message into the awaiting variable, clear the
    waiting flags, and enqueue the next node so the engine continues.

    MVP: no validation per type. All inputs accepted as text. Future
    work: regex/format validation per `config.type` on ask_question."""
    variable_name = execution.awaiting_variable
    if not variable_name:
        return
    # Persist the variable (same WorkflowVariable table used by other nodes)
    await session.execute(text(
        "INSERT INTO workflow_variables (execution_id, name, value, type) "
        "VALUES (:e, :n, :v, 'text') "
        "ON CONFLICT (execution_id, name) DO UPDATE SET value = :v"
    ), {"e": execution.id, "n": variable_name, "v": customer_message})
    # Clear waiting flags + resume at the next node after the ask
    execution.awaiting_variable = None
    execution.status = "running"
    edges = _edges_for(execution)  # already a util
    next_node = _next_node(edges, execution.current_node_id)
    execution.current_node_id = next_node
    if next_node:
        await _enqueue_workflow_step(
            execution.id,
            next_node,
            defer_seconds=0,
            node_id=execution.current_node_id,
        )
    else:
        execution.status = "completed"
        execution.finished_at = datetime.now(UTC)
```

### 2.5 NODE_TYPES + dispatch

```python
NODE_TYPES = frozenset({
    # ... existing ...
    "trigger_workflow",
    "ask_question",
})

# In _execute_node:
elif node_type == "trigger_workflow":
    await _node_trigger_workflow(session, workflow, execution, node, config)
elif node_type == "ask_question":
    result = await _node_ask_question(session, workflow, execution, node, config)
    if result is None:
        return None  # break dispatch — execution paused
```

### 2.6 Frontend: node config forms

In `frontend/src/features/workflows/components/WorkflowEditor.tsx`, the node-type sidebar already has form blocks for `message`, `delay`, `condition`, etc. Add 2 new form blocks:

**`trigger_workflow` form:**
- Dropdown: "Workflow a invocar" — populated from `useQuery(["workflows"], workflowsApi.list)`, filtered to exclude `workflow.id` itself (no self-recursion at edit time)
- Helper text: "El workflow hijo arranca con su propio contexto. Variables del padre no se pasan en MVP."

**`ask_question` form:**
- Textarea: "Pregunta al cliente"
- Input: "Variable" (alphanumeric + underscore)
- Select: "Tipo" — fixed to `text` in MVP, with a disabled tooltip "Otros tipos en una versión futura"

Both add to the node-type registry on the toolbar/canvas.

---

## 3. Tests

### 3.1 Backend

`core/tests/workflows/test_node_trigger_workflow.py`:
- `test_trigger_workflow_creates_child_execution` — happy path: parent triggers, child execution exists with `parent_execution_id` set, status `running`
- `test_trigger_workflow_rejects_self_reference` — same workflow_id as target → `WORKFLOW_RECURSION`
- `test_trigger_workflow_rejects_ancestor_in_chain` — A→B→C trying to trigger A → recursion
- `test_trigger_workflow_rejects_other_tenant` — target workflow belongs to different tenant → `TARGET_WORKFLOW_NOT_FOUND`
- `test_trigger_workflow_fire_and_forget` — parent moves to next node before child starts

`core/tests/workflows/test_node_ask_question.py`:
- `test_ask_question_pauses_execution` — execution status flips to `waiting_for_response` after the node fires
- `test_ask_question_persists_question_as_outbound` — outbound message row created
- `test_ask_question_rejects_missing_fields` — config without `question` or `variable` raises
- `test_ask_question_resumes_on_message_received` — second turn captures customer text, saves to variable, advances to next node
- `test_ask_question_isolated_per_conversation` — paused execution in conv A is NOT resumed by message in conv B

### 3.2 Frontend

`frontend/tests/features/workflows/TriggerWorkflowNodeForm.test.tsx`:
- Renders dropdown populated from `workflowsApi.list`
- Excludes self from dropdown
- Calls onChange with `{ target_workflow_id }` on selection

`frontend/tests/features/workflows/AskQuestionNodeForm.test.tsx`:
- Renders question + variable + type inputs
- Disables non-`text` types
- Validates variable name format

---

## 4. Migration safety

Migración 051 es **completamente aditiva**:
- 1 columna nullable
- 1 columna nullable
- 1 FK con `ON DELETE SET NULL` (no cascade catastrophe possible)
- 1 índice

Cero risk de downtime, cero risk de data loss. Downgrade es trivial (drop column + drop FK + drop index).

---

## 5. No-goals (explícitos)

Items que el audit lista pero NO entran en este sprint:

- ❌ **Variable passing parent → child** en W6 (sub-workflow inherits/receives variables)
- ❌ **Sync/blocking mode** en W6 (parent espera a child completion)
- ❌ **Return values** de child → parent
- ❌ **Non-text validation** en W8 (email/phone/number regex)
- ❌ **Timeout** en W8 (si cliente no responde en N tiempo)
- ❌ **Retry/skip** en W8
- ❌ **Simulator updates** (los node forms se ven, pero el simulator visual no los ejecuta)
- ❌ **W18 NYI buttons** — separate sprint

Cada uno es 0.5-1d de trabajo aislado. Todos los dejamos para sesiones futuras una vez que tengamos data real sobre uso.

---

## 6. Riesgos + mitigaciones

| Riesgo | Mitigación |
|---|---|
| Sub-workflow infinite recursion crashes the worker | `_detects_workflow_recursion` walks chain with depth cap 5 + DB lookup is bounded |
| ask_question paused execution leaks if conversation closes | Migración futura: cron worker scans `waiting_for_response` older than 24h and marks them `cancelled`. Out of MVP scope |
| Multiple paused executions per conversation race | `_resume_paused_executions` iterates in `started_at` order; each consumes the same inbound. Operator-facing edge case; flag in commit |
| `MESSAGE_RECEIVED` event arrives BEFORE the workflow has paused (race) | `_resume_paused_execution` selects by status — if not yet `waiting_for_response`, this message just doesn't resume anything. Operator can retry. |

---

## 7. Working contract reminders

- TDD strict per task: red test → red verify → implement → green verify → commit
- Migration applied + verified BEFORE any code reads the new columns
- Single subagent per task; spec + quality review on Tasks 1-4 (the engine work); light review on UI tasks
- ESTADO-Y-GAPS.md updated in final commit, batching D9/D10/D11 + W6/W8

---

## 8. Next step

Invoke `writing-plans` to descompose into atomic TDD tasks.

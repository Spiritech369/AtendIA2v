"""Workflow execution engine.

Migration 026 introduced the schema; migration 027 adds the columns this
engine needs to be safe (event source-tagging, persisted step counter,
structured error_code).

Design notes baked in here:

- ``validate_definition`` is structural only. ``validate_references`` is async
  and resolves agent/stage/user IDs to the current tenant. ``toggle_workflow``
  in the API layer must call both before flipping a workflow ``active=true``.
- ``evaluate_event`` short-circuits self-triggering by checking whether the
  source event was produced by the same workflow's own execution.
- ``execute_workflow`` reads ``WorkflowExecution.steps_completed`` so the
  ``MAX_STEPS`` cap survives delay/resume.
- Every side-effecting node uses ``WorkflowActionRun(execution_id, action_key)``
  for idempotency. Retry-from-failed-node never duplicates messages or notifications.
- ``message`` nodes enqueue ``send_outbound`` (arq) instead of inserting a
  ``MessageRow`` directly, so realtime fan-out and ``last_activity_at``
  stay consistent. They also pre-flight WhatsApp's 24h customer-care window
  and fail with ``error_code=OUTSIDE_24H_WINDOW`` instead of silently dropping.
- ``notify_agent`` validates that ``user_id``/``role`` resolves inside the
  tenant — never creates cross-tenant notifications.
- The condition resolver uses an explicit namespace allowlist instead of
  generic dot-notation that could leak fields.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from arq.connections import ArqRedis, RedisSettings, create_pool
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.channels.base import OutboundMessage
from atendia.config import get_settings
from atendia.db.models.agent import Agent
from atendia.db.models.conversation import Conversation, ConversationStateRow
from atendia.db.models.customer import Customer
from atendia.db.models.event import EventRow
from atendia.db.models.message import MessageRow
from atendia.db.models.notification import Notification
from atendia.db.models.tenant import TenantUser
from atendia.db.models.tenant_config import TenantPipeline
from atendia.db.models.workflow import (
    Workflow,
    WorkflowActionRun,
    WorkflowExecution,
)
from atendia.queue.outbox import stage_outbound

# Trigger types match EventType.value (lowercase). Forward-contract triggers
# (conversation_created, appointment_created, bot_paused) don't emit events
# yet — they're listed so the API rejects unknown values.
TRIGGERS: frozenset[str] = frozenset({
    "message_received",
    "field_extracted",
    "stage_entered",
    "conversation_created",
    "appointment_created",
    "bot_paused",
})

NODE_TYPES: frozenset[str] = frozenset({
    "trigger",
    "message",
    "move_stage",
    "assign_agent",
    "notify_agent",
    "update_field",
    "pause_bot",
    "delay",
    "condition",
})

VALID_ROLES: frozenset[str] = frozenset({"operator", "tenant_admin", "superadmin"})

# Hard caps. Tweaked here intentionally: a single workflow execution
# (across delay/resume) cannot exceed 100 nodes; a single delay cannot
# exceed 30 days; a definition cannot exceed 100 nodes / 150 edges.
MAX_STEPS: int = 100
MAX_DELAY_SECONDS: int = 60 * 60 * 24 * 30
MAX_NODES: int = 100
MAX_EDGES: int = 150
WHATSAPP_WINDOW_SECONDS: int = 60 * 60 * 24

# Allowlists for the condition resolver. ``extracted.*`` is open by design
# (operator-defined keys) but the resolver only ever reads from
# ``conversation_state.extracted_data``.
_CONVERSATION_FIELDS: frozenset[str] = frozenset({
    "current_stage",
    "assigned_user_id",
    "assigned_agent_id",
    "status",
    "channel",
})
_CUSTOMER_FIELDS: frozenset[str] = frozenset({"score", "name", "phone_e164"})

# Workflow jobs run on a dedicated arq queue so a burst of long-running
# workflows can't starve send_outbound.
WORKFLOW_QUEUE_NAME: str = "arq:queue:workflows"
_OUTBOUND_SESSION: ContextVar[AsyncSession | None] = ContextVar(
    "_OUTBOUND_SESSION",
    default=None,
)


class WorkflowValidationError(ValueError):
    """Raised when ``validate_definition`` or ``validate_references`` rejects a workflow."""


class _ExecutionFailure(Exception):  # noqa: N818 — internal control-flow, not an Error class
    """Internal control-flow exception carrying an ``error_code``."""

    def __init__(self, error: str, *, code: str | None = None) -> None:
        super().__init__(error)
        self.code = code


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_definition(definition: dict) -> None:
    """Structural validation. Run on every save and on ``toggle`` to active."""
    if not isinstance(definition, dict):
        raise WorkflowValidationError("definition must be an object")
    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise WorkflowValidationError("definition must contain nodes and edges lists")
    if len(nodes) > MAX_NODES:
        raise WorkflowValidationError(f"workflow exceeds {MAX_NODES} nodes")
    if len(edges) > MAX_EDGES:
        raise WorkflowValidationError(f"workflow exceeds {MAX_EDGES} edges")

    ids: set[str] = set()
    node_by_id: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise WorkflowValidationError("every node needs a string id")
        if node["id"] in ids:
            raise WorkflowValidationError(f"duplicate node id {node['id']}")
        if node.get("type") not in NODE_TYPES:
            raise WorkflowValidationError(f"unknown node type {node.get('type')}")
        ids.add(node["id"])
        node_by_id[node["id"]] = node
        config = node.get("config") or {}
        if node.get("type") == "delay":
            seconds = int(config.get("seconds", 0) or 0)
            if seconds <= 0:
                raise WorkflowValidationError("delay seconds must be positive")
            if seconds > MAX_DELAY_SECONDS:
                raise WorkflowValidationError("delay cannot exceed 30 days")
        if node.get("type") == "condition":
            field = config.get("field", "")
            _ensure_condition_field_allowed(field)

    for edge in edges:
        if not isinstance(edge, dict):
            raise WorkflowValidationError("edges must be objects")
        if edge.get("from") not in ids or edge.get("to") not in ids:
            raise WorkflowValidationError("edge references an unknown node")

    # Condition nodes must have both true and false branches so executions
    # don't dead-end silently.
    for node in nodes:
        if node.get("type") != "condition":
            continue
        labels = {edge.get("label") for edge in edges if edge.get("from") == node["id"]}
        if "true" not in labels or "false" not in labels:
            raise WorkflowValidationError(
                f"condition node {node['id']} needs both 'true' and 'false' edges",
            )

    _ensure_acyclic(node_by_id, edges)


def _ensure_condition_field_allowed(field: str) -> None:
    namespace, _, key = field.partition(".")
    if not key:
        raise WorkflowValidationError(
            f"condition field must be 'namespace.key', got {field!r}",
        )
    if namespace == "conversation":
        if key not in _CONVERSATION_FIELDS:
            raise WorkflowValidationError(
                f"conversation.{key} is not in the allowlist",
            )
    elif namespace == "customer":
        if key not in _CUSTOMER_FIELDS:
            raise WorkflowValidationError(
                f"customer.{key} is not in the allowlist",
            )
    elif namespace == "extracted":
        if not key:
            raise WorkflowValidationError("extracted condition needs a key")
    else:
        raise WorkflowValidationError(
            f"condition namespace must be conversation/customer/extracted, got {namespace!r}",
        )


def _ensure_acyclic(node_by_id: dict[str, dict], edges: list[dict]) -> None:
    """Reject cycles in the synchronous control-flow graph.

    Edges leaving a ``delay`` node don't count: a delay pauses execution and
    re-enqueues the next node as a fresh job, so a back-edge through a delay
    isn't a tight loop — the persisted ``MAX_STEPS`` counter caps it.
    """
    delay_ids: set[str] = {
        nid for nid, n in node_by_id.items() if n.get("type") == "delay"
    }
    adj: dict[str, list[str]] = {nid: [] for nid in node_by_id}
    for edge in edges:
        src = edge.get("from")
        dst = edge.get("to")
        if src in delay_ids:
            continue
        if src in adj and dst is not None:
            adj[src].append(dst)

    state: dict[str, int] = {}  # 0 unseen, 1 in-stack, 2 done

    def dfs(node_id: str) -> None:
        if state.get(node_id) == 2:
            return
        if state.get(node_id) == 1:
            raise WorkflowValidationError(
                f"cycle detected through node {node_id} — break the loop with a delay",
            )
        state[node_id] = 1
        for next_id in adj.get(node_id, []):
            dfs(next_id)
        state[node_id] = 2

    for nid in list(adj.keys()):
        if state.get(nid) != 2:
            dfs(nid)


@dataclass
class _RefCheckResult:
    agent_ids: set[UUID]
    user_ids: set[UUID]
    stages: set[str]


async def validate_references(
    session: AsyncSession,
    definition: dict,
    tenant_id: UUID,
) -> _RefCheckResult:
    """Resolve every dynamic reference in the definition against the tenant.

    Run on ``toggle`` to active. Workflows in draft can hold stale references;
    activation is the moment of truth.
    """
    agent_ids: set[UUID] = set()
    user_ids: set[UUID] = set()
    stages: set[str] = set()

    for node in definition.get("nodes", []):
        if not isinstance(node, dict):
            continue
        config = node.get("config") or {}
        ntype = node.get("type")
        if ntype == "assign_agent" and config.get("agent_id"):
            agent_ids.add(_parse_uuid(config["agent_id"], "agent_id"))
        if ntype == "move_stage" and config.get("stage_id"):
            stages.add(str(config["stage_id"]))
        if ntype == "notify_agent":
            if config.get("user_id"):
                user_ids.add(_parse_uuid(config["user_id"], "user_id"))
            role = config.get("role")
            if role and role not in VALID_ROLES:
                raise WorkflowValidationError(f"unknown notify_agent role {role!r}")

    if agent_ids:
        found = set(
            (await session.execute(
                select(Agent.id).where(Agent.tenant_id == tenant_id, Agent.id.in_(agent_ids))
            )).scalars().all()
        )
        missing = agent_ids - found
        if missing:
            raise WorkflowValidationError(
                f"agent_id refs not found in tenant: {sorted(str(x) for x in missing)}",
            )

    if user_ids:
        found_u = set(
            (await session.execute(
                select(TenantUser.id).where(
                    TenantUser.tenant_id == tenant_id, TenantUser.id.in_(user_ids),
                )
            )).scalars().all()
        )
        missing_u = user_ids - found_u
        if missing_u:
            raise WorkflowValidationError(
                f"notify_agent user_id refs not in tenant: {sorted(str(x) for x in missing_u)}",
            )

    if stages:
        # Stages live as strings on conversations; canonical list is in
        # tenant_pipelines.definition['stages']. If no active pipeline exists,
        # we accept any stage — same behaviour as the conversations PATCH path.
        definition_jsonb = (
            await session.execute(
                select(TenantPipeline.definition)
                .where(
                    TenantPipeline.tenant_id == tenant_id,
                    TenantPipeline.active.is_(True),
                )
                .order_by(TenantPipeline.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if isinstance(definition_jsonb, dict):
            valid = {
                str(s["id"])
                for s in (definition_jsonb.get("stages") or [])
                if isinstance(s, dict) and isinstance(s.get("id"), str)
            }
            unknown = stages - valid
            if valid and unknown:
                raise WorkflowValidationError(
                    f"move_stage refs unknown stages: {sorted(unknown)}",
                )

    return _RefCheckResult(agent_ids=agent_ids, user_ids=user_ids, stages=stages)


def _parse_uuid(raw: Any, field: str) -> UUID:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError) as exc:
        raise WorkflowValidationError(f"{field} is not a valid UUID: {raw!r}") from exc


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------


async def evaluate_event(session: AsyncSession, event_id: UUID) -> list[UUID]:
    """For an event, start any matching active workflows.

    Returns the list of newly-started execution ids. Self-triggering is
    blocked: an event tagged with ``source_workflow_execution_id`` will never
    re-trigger the same workflow.
    """
    event = (
        await session.execute(select(EventRow).where(EventRow.id == event_id))
    ).scalar_one_or_none()
    if event is None:
        return []

    source_workflow_id: UUID | None = None
    if event.source_workflow_execution_id is not None:
        source_workflow_id = (
            await session.execute(
                select(WorkflowExecution.workflow_id).where(
                    WorkflowExecution.id == event.source_workflow_execution_id,
                )
            )
        ).scalar_one_or_none()

    workflows = (
        await session.execute(
            select(Workflow).where(
                Workflow.tenant_id == event.tenant_id,
                Workflow.active.is_(True),
                Workflow.trigger_type == event.type,
            )
        )
    ).scalars().all()

    started: list[UUID] = []
    for workflow in workflows:
        if source_workflow_id is not None and source_workflow_id == workflow.id:
            # Self-loop: this workflow's own execution produced the event.
            continue
        if not _trigger_matches(workflow.trigger_config or {}, event.payload or {}):
            continue
        # Idempotency on (workflow_id, trigger_event_id): unique index in 026.
        # Use a savepoint so a duplicate retry does not roll back the caller's
        # event/message transaction.
        try:
            async with session.begin_nested():
                execution = WorkflowExecution(
                    workflow_id=workflow.id,
                    conversation_id=event.conversation_id,
                    trigger_event_id=event.id,
                    status="running",
                )
                session.add(execution)
                await session.flush()
        except IntegrityError:
            continue
        started.append(execution.id)
    return started


def _trigger_matches(config: dict, payload: dict) -> bool:
    field = config.get("field")
    if field and payload.get("field") != field:
        return False
    to_stage = config.get("to")
    if to_stage and payload.get("to") != to_stage:
        return False
    from_stage = config.get("from")
    if from_stage and payload.get("from") != from_stage:
        return False
    return True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


async def execute_workflow(
    session: AsyncSession,
    execution_id: UUID,
    *,
    start_node_id: str | None = None,
) -> None:
    """Run an execution to completion or until the next delay.

    Step counter is persisted in ``WorkflowExecution.steps_completed`` so that
    a chain of ``[message -> delay 1s]`` repeated forever can't sidestep
    ``MAX_STEPS`` by pausing and resuming.
    """
    row = (
        await session.execute(
            select(WorkflowExecution, Workflow)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .where(WorkflowExecution.id == execution_id)
        )
    ).first()
    if row is None:
        return
    execution, workflow = row
    if execution.status not in ("running", "paused"):
        return  # already completed or failed
    execution.status = "running"
    execution.error = None
    execution.error_code = None

    definition = workflow.definition or {"nodes": [], "edges": []}
    nodes_by_id = {
        node["id"]: node
        for node in definition.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    edges = definition.get("edges", [])

    current = start_node_id or _first_action_node(definition)
    try:
        while current:
            if execution.steps_completed >= MAX_STEPS:
                raise _ExecutionFailure(
                    f"workflow exceeded {MAX_STEPS} steps",
                    code="MAX_STEPS_EXCEEDED",
                )
            node = nodes_by_id.get(current)
            if node is None:
                raise _ExecutionFailure(
                    f"node {current!r} not found in workflow definition",
                    code="UNKNOWN_NODE",
                )
            execution.current_node_id = current
            execution.steps_completed += 1
            next_node = await _execute_node(session, workflow, execution, node, edges)
            if node.get("type") == "delay":
                execution.status = "paused"
                await session.flush()
                return
            current = next_node
        execution.status = "completed"
        execution.finished_at = datetime.now(UTC)
        execution.current_node_id = None
        await session.flush()
    except _ExecutionFailure as exc:
        await _set_failed(session, execution, str(exc), exc.code)
    except Exception as exc:
        await _set_failed(session, execution, str(exc)[:1000], None)


async def _set_failed(
    session: AsyncSession,
    execution: WorkflowExecution,
    error: str,
    error_code: str | None,
) -> None:
    """Persist the failed status in a savepoint so an outer rollback can't
    erase the failure record."""
    execution.status = "failed"
    execution.error = error
    execution.error_code = error_code
    try:
        async with session.begin_nested():
            await session.flush()
    except Exception:
        # Last-ditch attempt without nested tx.
        await session.flush()


def _first_action_node(definition: dict) -> str | None:
    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])
    trigger = next((n for n in nodes if isinstance(n, dict) and n.get("type") == "trigger"), None)
    if trigger is not None:
        edge = next((e for e in edges if e.get("from") == trigger.get("id")), None)
        if edge:
            return edge.get("to")
    node = next((n for n in nodes if isinstance(n, dict) and n.get("type") != "trigger"), None)
    return node.get("id") if node else None


def _next_node(edges: list[dict], node_id: str, label: str | None = None) -> str | None:
    for edge in edges:
        if edge.get("from") == node_id and (label is None or edge.get("label") == label):
            return edge.get("to")
    return None


# ---------------------------------------------------------------------------
# Node dispatch
# ---------------------------------------------------------------------------


async def _execute_node(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    edges: list[dict],
) -> str | None:
    node_type = node.get("type")
    config = node.get("config") or {}

    if node_type == "message":
        await _node_message(session, workflow, execution, node, config)
    elif node_type == "move_stage":
        await _node_move_stage(session, workflow, execution, node, config)
    elif node_type == "assign_agent":
        await _node_assign_agent(session, workflow, execution, node, config)
    elif node_type == "notify_agent":
        await _node_notify_agent(session, workflow, execution, node, config)
    elif node_type == "update_field":
        await _node_update_field(session, workflow, execution, node, config)
    elif node_type == "pause_bot":
        await _node_pause_bot(session, workflow, execution, node, config)
    elif node_type == "delay":
        await _node_delay(session, workflow, execution, node, edges, config)
        return None
    elif node_type == "condition":
        result = await _resolve_condition(session, execution, config)
        return _next_node(edges, node["id"], "true" if result else "false")
    return _next_node(edges, node["id"])


def _idempotency_key(execution_id: UUID, node_id: str) -> str:
    """Deterministic dedupe key. ``WorkflowActionRun`` has a unique index on
    ``(execution_id, action_key)``; retries from the same node never duplicate."""
    return f"wf:{execution_id}:{node_id}"


async def _record_action(
    session: AsyncSession,
    execution: WorkflowExecution,
    node_id: str,
) -> bool:
    """Insert a WorkflowActionRun row. Returns True if newly recorded, False if
    the action already ran (idempotency hit)."""
    action_key = _idempotency_key(execution.id, node_id)
    try:
        async with session.begin_nested():
            session.add(
                WorkflowActionRun(
                    execution_id=execution.id,
                    node_id=node_id,
                    action_key=action_key,
                )
            )
            await session.flush()
        return True
    except IntegrityError:
        return False


async def _node_message(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    config: dict,
) -> None:
    text_body = (config.get("text") or "").strip()
    if not text_body:
        raise _ExecutionFailure("message node missing text", code="EMPTY_MESSAGE")
    if not execution.conversation_id:
        raise _ExecutionFailure(
            "message node requires a conversation context",
            code="NO_CONVERSATION_CONTEXT",
        )

    customer_phone = await _customer_phone_for_conversation(session, execution.conversation_id)
    if customer_phone is None:
        raise _ExecutionFailure(
            "conversation has no customer phone",
            code="NO_PHONE",
        )

    if not await _within_24h_window(session, execution.conversation_id):
        # Phase 3d.2 will add WhatsApp template support; until then, outside-24h
        # sends would silently drop. Fail loudly with a structured code.
        raise _ExecutionFailure(
            "last inbound was >24h ago; templates not yet implemented",
            code="OUTSIDE_24H_WINDOW",
        )

    fresh = await _record_action(session, execution, node["id"])
    if not fresh:
        return  # idempotent retry
    idempotency_key = _idempotency_key(execution.id, node["id"])
    msg = OutboundMessage(
        tenant_id=str(workflow.tenant_id),
        to_phone_e164=customer_phone,
        text=text_body,
        idempotency_key=idempotency_key,
        metadata={
            "source": "workflow",
            "workflow_id": str(workflow.id),
            "execution_id": str(execution.id),
            "node_id": node["id"],
        },
    )
    token = _OUTBOUND_SESSION.set(session)
    try:
        await _enqueue_outbound_for_workflow(msg)
    finally:
        _OUTBOUND_SESSION.reset(token)


async def _customer_phone_for_conversation(
    session: AsyncSession,
    conversation_id: UUID,
) -> str | None:
    return (
        await session.execute(
            select(Customer.phone_e164)
            .join(Conversation, Conversation.customer_id == Customer.id)
            .where(Conversation.id == conversation_id)
        )
    ).scalar_one_or_none()


async def _within_24h_window(session: AsyncSession, conversation_id: UUID) -> bool:
    """WhatsApp lets you reply only within 24h of the customer's last inbound.
    Outside the window you must use a template — not implemented yet."""
    last_inbound = (
        await session.execute(
            select(MessageRow.sent_at)
            .where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.direction == "inbound",
            )
            .order_by(MessageRow.sent_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_inbound is None:
        return False
    return (datetime.now(UTC) - last_inbound) <= timedelta(seconds=WHATSAPP_WINDOW_SECONDS)


async def _node_move_stage(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    config: dict,
) -> None:
    if not execution.conversation_id:
        return
    stage_id = config.get("stage_id")
    if not stage_id:
        return
    fresh = await _record_action(session, execution, node["id"])
    if not fresh:
        return
    now = datetime.now(UTC)
    await session.execute(
        update(Conversation)
        .where(
            Conversation.id == execution.conversation_id,
            Conversation.tenant_id == workflow.tenant_id,
        )
        .values(current_stage=stage_id, last_activity_at=now),
    )
    await session.execute(
        update(ConversationStateRow)
        .where(ConversationStateRow.conversation_id == execution.conversation_id)
        .values(stage_entered_at=now),
    )


async def _node_assign_agent(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    config: dict,
) -> None:
    if not execution.conversation_id:
        return
    raw = config.get("agent_id")
    if not raw:
        return
    agent_id = _parse_uuid(raw, "agent_id")
    exists = (
        await session.execute(
            select(Agent.id).where(
                Agent.id == agent_id,
                Agent.tenant_id == workflow.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not exists:
        raise _ExecutionFailure(
            f"assign_agent target {agent_id} not found in tenant",
            code="UNKNOWN_AGENT",
        )
    fresh = await _record_action(session, execution, node["id"])
    if not fresh:
        return
    await session.execute(
        update(Conversation)
        .where(
            Conversation.id == execution.conversation_id,
            Conversation.tenant_id == workflow.tenant_id,
        )
        .values(assigned_agent_id=exists),
    )


async def _node_notify_agent(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    config: dict,
) -> None:
    targets = await _resolve_notify_targets(session, workflow, config)
    if not targets:
        return
    fresh = await _record_action(session, execution, node["id"])
    if not fresh:
        return
    title = (config.get("title") or workflow.name)[:200]
    body = config.get("body")
    for user_id in targets:
        session.add(
            Notification(
                tenant_id=workflow.tenant_id,
                user_id=user_id,
                title=title,
                body=body,
                source_type="workflow",
                source_id=execution.id,
            )
        )


async def _resolve_notify_targets(
    session: AsyncSession,
    workflow: Workflow,
    config: dict,
) -> list[UUID]:
    raw_user = config.get("user_id")
    if raw_user:
        user_id = _parse_uuid(raw_user, "user_id")
        # Tenant cross-check: never create a notification for someone outside
        # the workflow's tenant.
        exists = (
            await session.execute(
                select(TenantUser.id).where(
                    TenantUser.id == user_id,
                    TenantUser.tenant_id == workflow.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if not exists:
            raise _ExecutionFailure(
                f"notify_agent user {user_id} not in tenant",
                code="UNKNOWN_USER",
            )
        return [exists]

    role = config.get("role")
    if role:
        if role not in VALID_ROLES:
            raise _ExecutionFailure(
                f"unknown notify_agent role {role!r}",
                code="UNKNOWN_ROLE",
            )
        rows = (
            await session.execute(
                select(TenantUser.id).where(
                    TenantUser.tenant_id == workflow.tenant_id,
                    TenantUser.role == role,
                )
            )
        ).scalars().all()
        return list(rows)

    return []


async def _node_update_field(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    config: dict,
) -> None:
    if not execution.conversation_id:
        return
    field = config.get("field")
    if not field or not isinstance(field, str):
        raise _ExecutionFailure("update_field requires a field name", code="MISSING_FIELD")
    fresh = await _record_action(session, execution, node["id"])
    if not fresh:
        return
    state = (
        await session.execute(
            select(ConversationStateRow).where(
                ConversationStateRow.conversation_id == execution.conversation_id,
            )
        )
    ).scalar_one_or_none()
    if state is None:
        raise _ExecutionFailure(
            "conversation_state row missing for update_field",
            code="MISSING_STATE",
        )
    data = dict(state.extracted_data or {})
    data[field] = {
        "value": config.get("value"),
        "confidence": 1.0,
        "source_turn": 0,
        "source": "workflow",
        "workflow_id": str(workflow.id),
    }
    state.extracted_data = data


async def _node_pause_bot(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    config: dict,
) -> None:
    if not execution.conversation_id:
        return
    fresh = await _record_action(session, execution, node["id"])
    if not fresh:
        return
    await session.execute(
        update(ConversationStateRow)
        .where(ConversationStateRow.conversation_id == execution.conversation_id)
        .values(bot_paused=True),
    )


async def _node_delay(
    session: AsyncSession,
    workflow: Workflow,
    execution: WorkflowExecution,
    node: dict,
    edges: list[dict],
    config: dict,
) -> None:
    seconds = max(1, int(config.get("seconds") or 1))
    if seconds > MAX_DELAY_SECONDS:
        raise _ExecutionFailure("delay exceeds 30 days", code="DELAY_TOO_LARGE")
    next_node = _next_node(edges, node["id"])
    execution.current_node_id = next_node
    await _enqueue_workflow_step(execution.id, next_node, defer_seconds=seconds, node_id=node["id"])


async def _resolve_condition(
    session: AsyncSession,
    execution: WorkflowExecution,
    config: dict,
) -> bool:
    field = config.get("field", "")
    _ensure_condition_field_allowed(field)  # safety: reject if validator was bypassed
    namespace, _, key = field.partition(".")
    operator = config.get("operator", "eq")
    expected = config.get("value")
    actual = await _read_condition_value(session, execution, namespace, key)
    if operator == "neq":
        return actual != expected
    if operator == "exists":
        return actual is not None
    return actual == expected


async def _read_condition_value(
    session: AsyncSession,
    execution: WorkflowExecution,
    namespace: str,
    key: str,
) -> Any:
    if not execution.conversation_id:
        return None
    if namespace == "conversation":
        if key not in _CONVERSATION_FIELDS:
            return None
        return (
            await session.execute(
                select(getattr(Conversation, key)).where(
                    Conversation.id == execution.conversation_id,
                )
            )
        ).scalar_one_or_none()
    if namespace == "customer":
        if key not in _CUSTOMER_FIELDS:
            return None
        return (
            await session.execute(
                select(getattr(Customer, key))
                .join(Conversation, Conversation.customer_id == Customer.id)
                .where(Conversation.id == execution.conversation_id)
            )
        ).scalar_one_or_none()
    if namespace == "extracted":
        state = (
            await session.execute(
                select(ConversationStateRow.extracted_data).where(
                    ConversationStateRow.conversation_id == execution.conversation_id,
                )
            )
        ).scalar_one_or_none()
        if state is None:
            return None
        raw = (state or {}).get(key)
        return raw.get("value") if isinstance(raw, dict) else raw
    return None


# ---------------------------------------------------------------------------
# Side-effect adapters (overridable for tests)
# ---------------------------------------------------------------------------


async def _enqueue_outbound_for_workflow(msg: OutboundMessage) -> str:
    """Encapsulated for testability — monkeypatch in tests to record calls."""
    session = _OUTBOUND_SESSION.get()
    if session is None:
        raise RuntimeError("workflow outbound staging requires an active DB session")
    return str(await stage_outbound(session, msg))


async def _enqueue_workflow_step(
    execution_id: UUID,
    next_node: str | None,
    *,
    defer_seconds: int,
    node_id: str,
) -> None:
    """Enqueue an ``execute_workflow_step`` job on the workflows queue with a
    deterministic ``_job_id`` so a retry doesn't double-fire the resume."""
    redis = await create_pool(
        RedisSettings.from_dsn(get_settings().redis_url),
        default_queue_name=WORKFLOW_QUEUE_NAME,
    )
    try:
        await redis.enqueue_job(
            "execute_workflow_step",
            str(execution_id),
            next_node,
            _defer_by=defer_seconds,
            _job_id=f"workflow:{execution_id}:{node_id}",
            _queue_name=WORKFLOW_QUEUE_NAME,
        )
    finally:
        await redis.aclose()


async def enqueue_executions_to_workflows_queue(
    redis: ArqRedis,
    execution_ids: list[UUID],
) -> None:
    """Caller-side helper for the runner hook (deferred to its own session).

    For now the cron-backed ``poll_workflow_triggers`` runs executions inline
    in worker context. When the runner inline-trigger is wired, it will call
    ``evaluate_event`` and pass the returned ids here.
    """
    for execution_id in execution_ids:
        await redis.enqueue_job(
            "execute_workflow_step",
            str(execution_id),
            None,
            _job_id=f"workflow:{execution_id}:start",
            _queue_name=WORKFLOW_QUEUE_NAME,
        )


# ---------------------------------------------------------------------------
# Helpers used by tests / seed data
# ---------------------------------------------------------------------------


def definition_for_steps(trigger_type: str, actions: list[dict]) -> dict:
    """Build a linear node graph from a trigger + ordered list of action specs."""
    nodes: list[dict] = [{"id": "trigger_1", "type": "trigger", "config": {"event": trigger_type}}]
    edges: list[dict] = []
    prev = "trigger_1"
    for i, action in enumerate(actions, start=1):
        node_id = f"action_{i}"
        nodes.append({"id": node_id, "type": action["type"], "config": action.get("config") or {}})
        edges.append({"from": prev, "to": node_id})
        prev = node_id
    return {"nodes": nodes, "edges": edges}

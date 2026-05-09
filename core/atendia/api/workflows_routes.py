from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._audit import emit_admin_event
from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.db.models.workflow import Workflow, WorkflowExecution
from atendia.db.session import get_db_session
from atendia.workflows.engine import (
    TRIGGERS,
    WorkflowValidationError,
    execute_workflow,
    validate_definition,
    validate_references,
)

router = APIRouter()


class WorkflowBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    trigger_type: str
    trigger_config: dict = Field(default_factory=dict)
    definition: dict = Field(default_factory=lambda: {"nodes": [], "edges": []})
    active: bool = False

    @field_validator("trigger_type")
    @classmethod
    def _trigger(cls, value: str) -> str:
        if value not in TRIGGERS:
            raise ValueError("invalid trigger_type")
        return value

    @field_validator("definition")
    @classmethod
    def _definition(cls, value: dict) -> dict:
        validate_definition(value)
        return value


class WorkflowPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    trigger_type: str | None = None
    trigger_config: dict | None = None
    definition: dict | None = None
    active: bool | None = None
    # Optimistic-lock check. When set, PATCH requires the row to still be at
    # this version; otherwise the response is 409. Omitting it is equivalent
    # to opting out of the check (last-write-wins) — provided for read-only
    # patches like description tweaks where conflict cost is low.
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("trigger_type")
    @classmethod
    def _patch_trigger(cls, value: str | None) -> str | None:
        if value is not None and value not in TRIGGERS:
            raise ValueError("invalid trigger_type")
        return value

    @field_validator("definition")
    @classmethod
    def _patch_definition(cls, value: dict | None) -> dict | None:
        if value is not None:
            validate_definition(value)
        return value


class WorkflowItem(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    trigger_type: str
    trigger_config: dict
    definition: dict
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class ExecutionItem(BaseModel):
    id: UUID
    workflow_id: UUID
    conversation_id: UUID | None
    customer_id: UUID | None
    trigger_event_id: UUID | None
    status: str
    current_node_id: str | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None


def _item(row: Workflow) -> WorkflowItem:
    return WorkflowItem.model_validate(row, from_attributes=True)


def _execution_item(row: WorkflowExecution) -> ExecutionItem:
    return ExecutionItem.model_validate(row, from_attributes=True)


@router.get("", response_model=list[WorkflowItem])
async def list_workflows(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[WorkflowItem]:
    rows = (
        await session.execute(select(Workflow).where(Workflow.tenant_id == tenant_id).order_by(Workflow.created_at.desc()))
    ).scalars().all()
    return [_item(row) for row in rows]


@router.post("", response_model=WorkflowItem, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    if body.active:
        # Activating a brand-new workflow re-validates dynamic refs against
        # the tenant. Drafts (active=False) skip this and can hold stale
        # references until the operator flips them on.
        try:
            await validate_references(session, body.definition, tenant_id)
        except WorkflowValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    row = Workflow(tenant_id=tenant_id, **body.model_dump())
    session.add(row)
    await session.flush()
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.created",
        payload={
            "workflow_id": str(row.id),
            "name": row.name,
            "trigger_type": row.trigger_type,
            "active": row.active,
        },
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.get("/{workflow_id}", response_model=WorkflowItem)
async def get_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    return _item(row)


@router.patch("/{workflow_id}", response_model=WorkflowItem)
async def patch_workflow(
    workflow_id: UUID,
    body: WorkflowPatch,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    values = body.model_dump(exclude_unset=True)
    expected_version = values.pop("expected_version", None)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    if expected_version is not None and row.version != expected_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"workflow has been modified by another session "
            f"(server version {row.version}, sent {expected_version})",
        )
    # Compute the post-patch state for ref validation when activation is involved.
    will_be_active = values.get("active", row.active)
    next_definition = values.get("definition", row.definition)
    if will_be_active:
        try:
            await validate_references(session, next_definition or {}, tenant_id)
        except WorkflowValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    for key, value in values.items():
        setattr(row, key, value)
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.patched",
        payload={
            "workflow_id": str(row.id),
            "fields": sorted(values.keys()),
            "new_version": row.version,
        },
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.deleted",
        payload={"workflow_id": str(row.id), "name": row.name},
    )
    await session.delete(row)
    await session.commit()


@router.post("/{workflow_id}/toggle", response_model=WorkflowItem)
async def toggle_workflow(
    workflow_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowItem:
    row = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    # Toggling to active is the moment dynamic refs must resolve. Toggling
    # off skips ref validation — broken refs shouldn't keep a workflow stuck on.
    if not row.active:
        try:
            validate_definition(row.definition or {})
            await validate_references(session, row.definition or {}, tenant_id)
        except WorkflowValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    row.active = not row.active
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(UTC)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.toggled",
        payload={"workflow_id": str(row.id), "active": row.active, "new_version": row.version},
    )
    await session.commit()
    await session.refresh(row)
    return _item(row)


@router.get("/{workflow_id}/executions", response_model=list[ExecutionItem])
async def list_executions(
    workflow_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[ExecutionItem]:
    own = (
        await session.execute(select(Workflow.id).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workflow not found")
    rows = (
        await session.execute(
            select(WorkflowExecution)
            .where(WorkflowExecution.workflow_id == workflow_id)
            .order_by(WorkflowExecution.started_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return [_execution_item(row) for row in rows]


@router.post("/{workflow_id}/executions/{execution_id}/retry", response_model=ExecutionItem)
async def retry_execution(
    workflow_id: UUID,
    execution_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionItem:
    row = (
        await session.execute(
            select(WorkflowExecution, Workflow)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .where(
                Workflow.id == workflow_id,
                Workflow.tenant_id == tenant_id,
                WorkflowExecution.id == execution_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "execution not found")
    execution, _workflow = row
    if execution.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "only failed executions can be retried")
    start = execution.current_node_id
    execution.status = "running"
    execution.error = None
    await execute_workflow(session, execution.id, start_node_id=start)
    await emit_admin_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=user.user_id,
        action="workflow.retry",
        payload={
            "workflow_id": str(workflow_id),
            "execution_id": str(execution_id),
            "resumed_from_node": start,
        },
    )
    await session.commit()
    await session.refresh(execution)
    return _execution_item(execution)

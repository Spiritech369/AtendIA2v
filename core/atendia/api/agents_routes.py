from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.db.models.agent import Agent
from atendia.db.session import get_db_session

router = APIRouter()

AGENT_ROLES = {"sales", "support", "collections", "documentation", "reception", "custom"}
NLU_INTENTS = {"GREETING", "ASK_INFO", "ASK_PRICE", "BUY", "SCHEDULE", "COMPLAIN", "OFF_TOPIC", "UNCLEAR"}


class AgentItem(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    role: str
    goal: str | None
    style: str | None
    tone: str | None
    language: str | None
    max_sentences: int | None
    no_emoji: bool
    return_to_flow: bool
    is_default: bool
    system_prompt: str | None
    active_intents: list[str]
    extraction_config: dict
    auto_actions: dict
    knowledge_config: dict
    flow_mode_rules: dict | None
    created_at: datetime
    updated_at: datetime


class AgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = "custom"
    goal: str | None = None
    style: str | None = Field(default=None, max_length=200)
    tone: str | None = Field(default="amigable", max_length=40)
    language: str | None = Field(default="es", max_length=20)
    max_sentences: int | None = Field(default=5, ge=1, le=20)
    no_emoji: bool = False
    return_to_flow: bool = True
    is_default: bool = False
    system_prompt: str | None = None
    active_intents: list[str] = Field(default_factory=list)
    extraction_config: dict = Field(default_factory=dict)
    auto_actions: dict = Field(default_factory=dict)
    knowledge_config: dict = Field(default_factory=dict)
    flow_mode_rules: dict | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, value: str) -> str:
        if value not in AGENT_ROLES:
            raise ValueError("invalid agent role")
        return value

    @field_validator("active_intents")
    @classmethod
    def _intents(cls, value: list[str]) -> list[str]:
        unknown = [item for item in value if item not in NLU_INTENTS]
        if unknown:
            raise ValueError(f"unknown intents: {', '.join(unknown)}")
        return list(dict.fromkeys(value))


class AgentPatch(AgentBody):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    no_emoji: bool | None = None
    return_to_flow: bool | None = None
    is_default: bool | None = None
    active_intents: list[str] | None = None
    extraction_config: dict | None = None
    auto_actions: dict | None = None
    knowledge_config: dict | None = None


class AgentTestBody(BaseModel):
    agent_config: dict
    message: str = Field(min_length=1, max_length=2000)


class AgentTestResponse(BaseModel):
    response: str
    flow_mode: str
    intent: str


def _item(row: Agent) -> AgentItem:
    return AgentItem.model_validate(row, from_attributes=True)


async def _clear_default(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        update(Agent).where(Agent.tenant_id == tenant_id, Agent.is_default.is_(True)).values(is_default=False)
    )


@router.get("", response_model=list[AgentItem])
async def list_agents(
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[AgentItem]:
    rows = (
        await session.execute(
            select(Agent).where(Agent.tenant_id == tenant_id).order_by(Agent.is_default.desc(), Agent.name.asc())
        )
    ).scalars().all()
    return [_item(row) for row in rows]


@router.post("", response_model=AgentItem, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentBody,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    if body.is_default:
        await _clear_default(session, tenant_id)
    row = Agent(tenant_id=tenant_id, **body.model_dump())
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "default agent already exists") from exc
    await session.refresh(row)
    return _item(row)


@router.get("/{agent_id}", response_model=AgentItem)
async def get_agent(
    agent_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = (
        await session.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return _item(row)


@router.patch("/{agent_id}", response_model=AgentItem)
async def patch_agent(
    agent_id: UUID,
    body: AgentPatch,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentItem:
    row = (
        await session.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields to update")
    if values.get("is_default") is True:
        await _clear_default(session, tenant_id)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "default agent already exists") from exc
    await session.refresh(row)
    return _item(row)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    user: AuthUser = Depends(require_tenant_admin),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    row = (
        await session.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    if row.is_default:
        count = (
            await session.execute(select(func.count()).select_from(Agent).where(Agent.tenant_id == tenant_id))
        ).scalar_one()
        if count <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "cannot delete the only default agent")
    await session.delete(row)
    await session.commit()


@router.post("/test", response_model=AgentTestResponse)
async def test_agent(
    body: AgentTestBody,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),  # noqa: ARG001
) -> AgentTestResponse:
    config = body.agent_config or {}
    name = config.get("name") or "Agente"
    role = config.get("role") or "custom"
    text = body.message.strip()
    intent = "ASK_PRICE" if "precio" in text.lower() else "GREETING" if "hola" in text.lower() else "ASK_INFO"
    return AgentTestResponse(
        response=f"{name}: respuesta de prueba para modo {role}.",
        flow_mode="SUPPORT",
        intent=intent,
    )

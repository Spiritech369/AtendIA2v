"""Read-only views over a tenant's external integrations.

Right now we expose just enough metadata for the operator to wire a Meta
WhatsApp Cloud API account into the system. Credentials are *not* mutable
through this endpoint — that flow involves Meta Business Manager OAuth and
is out of scope for the v1-parity sprint.

The plain-text fields (``verify_token``) are restricted to ``tenant_admin``
roles; operators only see the metadata they need to triage issues.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser
from atendia.api._deps import current_tenant_id, current_user, require_tenant_admin
from atendia.channels.base import InboundMessage
from atendia.config import get_settings
from atendia.db.models.tenant import Tenant
from atendia.db.session import get_db_session
from atendia.queue.circuit_breaker import is_open
from atendia.runner.provider_factory import (
    AIProviderSelection,
    ComposerProviderName,
    NLUProviderName,
    selection_from_config,
)
from atendia.webhooks.meta_routes import _get_redis, _persist_inbound

router = APIRouter()


class WhatsAppDetails(BaseModel):
    phone_number: str | None
    business_name: str | None
    phone_number_id: str | None
    business_id: str | None
    # Tenant-admin-only: the Meta webhook verification token the operator must
    # paste into Meta Business Manager. Empty string for non-admin callers.
    verify_token: str | None
    # Path to register in Meta Business Manager. The frontend prefixes
    # ``window.location.origin`` to build the full URL since the backend
    # doesn't know its public hostname.
    webhook_path: str
    last_webhook_at: datetime | None
    circuit_breaker_open: bool


class WhatsAppWebhookSandboxBody(BaseModel):
    from_phone: str = Field(default="+5215500100999", min_length=8, max_length=24)
    text: str = Field(
        default="Hola, quiero probar el sandbox de WhatsApp para una moto Dinamo U5.",
        min_length=1,
        max_length=500,
    )


class WhatsAppWebhookSandboxResponse(BaseModel):
    status: str
    channel_message_id: str
    conversation_id: UUID | None
    message_id: UUID | None
    trace_id: UUID | None
    started_execution_ids: list[UUID]
    last_webhook_at: datetime
    request_preview: dict
    response_preview: dict


class AIProviderInfo(BaseModel):
    """Read-only view of which LLM/NLU providers are wired up."""

    nlu_provider: str
    nlu_model: str
    nlu_fallback_provider: str
    nlu_fallback_model: str
    composer_provider: str
    composer_model: str
    has_openai_key: bool
    has_anthropic_key: bool


class AIProviderPutBody(BaseModel):
    nlu_provider: NLUProviderName
    nlu_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=80)
    composer_provider: ComposerProviderName
    composer_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=80)


def _ai_provider_info(settings, selection: AIProviderSelection) -> AIProviderInfo:
    return AIProviderInfo(
        nlu_provider=selection.nlu_provider,
        nlu_model=selection.nlu_model,
        nlu_fallback_provider=settings.nlu_fallback_provider,
        nlu_fallback_model=settings.nlu_fallback_model,
        composer_provider=selection.composer_provider,
        composer_model=selection.composer_model,
        has_openai_key=bool(settings.openai_api_key),
        has_anthropic_key=bool(settings.anthropic_api_key),
    )


@router.get("/whatsapp/details", response_model=WhatsAppDetails)
async def get_whatsapp_details(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppDetails:
    row = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    config = row.config or {}
    meta = config.get("meta", {}) if isinstance(config, dict) else {}

    is_admin = user.role in {"tenant_admin", "superadmin"}
    raw_token = meta.get("verify_token") if isinstance(meta, dict) else None
    verify_token = raw_token if (is_admin and raw_token) else None

    redis = Redis.from_url(get_settings().redis_url)
    try:
        cb_open = await is_open(redis, str(tenant_id))
        raw_ts = await redis.get(f"webhook:last_at:{tenant_id}")
    finally:
        await redis.aclose()
    last_webhook_at: datetime | None = None
    if raw_ts:
        last_webhook_at = datetime.fromisoformat(raw_ts.decode())

    return WhatsAppDetails(
        phone_number=meta.get("phone_number") or config.get("phone_number"),
        business_name=meta.get("business_name") or row.name,
        phone_number_id=meta.get("phone_number_id") or config.get("phone_number_id"),
        business_id=row.meta_business_id,
        verify_token=verify_token,
        webhook_path=f"/webhooks/meta/{tenant_id}",
        last_webhook_at=last_webhook_at,
        circuit_breaker_open=cb_open,
    )


@router.post("/whatsapp/test-webhook", response_model=WhatsAppWebhookSandboxResponse)
async def test_whatsapp_webhook(
    body: WhatsAppWebhookSandboxBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppWebhookSandboxResponse:
    """Run a local Meta-style inbound through the same persistence path.

    This is intentionally tenant-admin scoped: it creates a real sandbox
    conversation/message/trace for operator validation, without requiring
    Meta Business Manager to call the public webhook.
    """
    row = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    config = row.config or {}
    meta = config.get("meta", {}) if isinstance(config, dict) else {}
    phone_number_id = meta.get("phone_number_id") or config.get("phone_number_id")
    channel_message_id = f"wamid.sandbox.{uuid4().hex}"
    now = datetime.now(UTC)
    from_phone = body.from_phone.strip().replace(" ", "")
    inbound = InboundMessage(
        tenant_id=str(tenant_id),
        from_phone_e164=from_phone,
        channel_message_id=channel_message_id,
        text=body.text.strip(),
        received_at=now.isoformat(),
        metadata={
            "sandbox": True,
            "channel": "whatsapp_meta",
            "phone_number_id": phone_number_id,
            "triggered_by_user_id": str(user.user_id),
        },
    )

    redis = await _get_redis()
    try:
        await redis.set(f"webhook:last_at:{tenant_id}", now.isoformat(), ex=86400)
    finally:
        await redis.aclose()

    persisted = await _persist_inbound(session, tenant_id, inbound)
    started_execution_ids = persisted.started_execution_ids if persisted is not None else []
    await session.commit()
    if persisted is not None:
        from arq.connections import RedisSettings, create_pool

        from atendia.queue.inbound_burst import enqueue_inbound_burst
        from atendia.workflows.engine import enqueue_executions_to_workflows_queue

        arq_pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            if persisted.started_execution_ids:
                await enqueue_executions_to_workflows_queue(
                    arq_pool, persisted.started_execution_ids
                )
            await enqueue_inbound_burst(
                arq_pool,
                tenant_id=persisted.tenant_id,
                conversation_id=persisted.conversation_id,
                latest_message_id=persisted.message_id,
                from_phone_e164=persisted.from_phone_e164,
            )
        finally:
            await arq_pool.aclose()

    result = (
        await session.execute(
            text(
                "SELECT m.id AS message_id, m.conversation_id AS conversation_id "
                "FROM messages m "
                "WHERE m.tenant_id = :tenant_id AND m.channel_message_id = :channel_message_id"
            ),
            {"tenant_id": tenant_id, "channel_message_id": channel_message_id},
        )
    ).mappings().one_or_none()

    trace_id = None
    if result:
        trace_id = (
            await session.execute(
                text(
                    "SELECT id FROM turn_traces "
                    "WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id, "conversation_id": result["conversation_id"]},
            )
        ).scalar_one_or_none()

    return WhatsAppWebhookSandboxResponse(
        status="ok",
        channel_message_id=channel_message_id,
        conversation_id=result["conversation_id"] if result else None,
        message_id=result["message_id"] if result else None,
        trace_id=trace_id,
        started_execution_ids=started_execution_ids,
        last_webhook_at=now,
        request_preview={
            "object": "whatsapp_business_account",
            "phone_number_id": phone_number_id,
            "from": from_phone,
            "text": body.text.strip(),
        },
        response_preview={
            "status": "ok",
            "received": 1 if result else 0,
            "statuses": 0,
        },
    )


@router.get("/ai-provider", response_model=AIProviderInfo)
async def get_ai_provider_info(
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AIProviderInfo:
    settings = get_settings()
    row = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    return _ai_provider_info(settings, selection_from_config(settings, row.config))


@router.put("/ai-provider", response_model=AIProviderInfo)
async def put_ai_provider_info(
    body: AIProviderPutBody,
    user: AuthUser = Depends(require_tenant_admin),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AIProviderInfo:
    settings = get_settings()
    row = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    config = dict(row.config or {})
    config["ai"] = {
        "nlu_provider": body.nlu_provider,
        "nlu_model": body.nlu_model.strip(),
        "composer_provider": body.composer_provider,
        "composer_model": body.composer_model.strip(),
    }
    await session.execute(update(Tenant).where(Tenant.id == tenant_id).values(config=config))
    await session.commit()
    return _ai_provider_info(settings, selection_from_config(settings, config))

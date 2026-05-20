from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.config import Settings
from atendia.db.models.tenant import Tenant
from atendia.runner.composer_openai import OpenAIComposer
from atendia.runner.composer_protocol import ComposerProvider
from atendia.runner.nlu_anthropic import AnthropicHaikuNLU
from atendia.runner.nlu_fallback import FallbackNLU
from atendia.runner.nlu_openai import OpenAINLU
from atendia.runner.nlu_protocol import NLUProvider

NLUProviderName = Literal["openai"]
ComposerProviderName = Literal["openai"]


@dataclass(frozen=True)
class AIProviderSelection:
    nlu_provider: NLUProviderName
    nlu_model: str
    composer_provider: ComposerProviderName
    composer_model: str
    nlu_topics: list[dict]


def _as_nlu_provider(value: object, fallback: NLUProviderName) -> NLUProviderName:
    return value if value == "openai" else fallback  # type: ignore[return-value]


def _as_composer_provider(value: object, fallback: ComposerProviderName) -> ComposerProviderName:
    return value if value == "openai" else fallback  # type: ignore[return-value]


def selection_from_config(settings: Settings, config: dict | None) -> AIProviderSelection:
    ai = config.get("ai", {}) if isinstance(config, dict) else {}
    if not isinstance(ai, dict):
        ai = {}
    nlu_topics = config.get("nlu_topics", []) if isinstance(config, dict) else []
    if not isinstance(nlu_topics, list):
        nlu_topics = []
    return AIProviderSelection(
        nlu_provider=_as_nlu_provider(ai.get("nlu_provider"), settings.nlu_provider),
        nlu_model=str(ai.get("nlu_model") or settings.nlu_model),
        composer_provider=_as_composer_provider(
            ai.get("composer_provider"),
            settings.composer_provider,
        ),
        composer_model=str(ai.get("composer_model") or settings.composer_model),
        nlu_topics=[item for item in nlu_topics if isinstance(item, dict)],
    )


async def load_tenant_ai_selection(
    session: AsyncSession,
    tenant_id: UUID,
    settings: Settings,
) -> AIProviderSelection:
    config = (
        await session.execute(select(Tenant.config).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    return selection_from_config(settings, config)


def build_nlu(settings: Settings, selection: AIProviderSelection | None = None) -> NLUProvider:
    selected = selection or selection_from_config(settings, None)
    primary = OpenAINLU(
        api_key=settings.openai_api_key,
        model=selected.nlu_model,
        timeout_s=settings.nlu_timeout_s,
        retry_delays_ms=tuple(settings.nlu_retry_delays_ms),
        topics=selected.nlu_topics,
    )
    if settings.nlu_fallback_provider == "haiku" and settings.anthropic_api_key:
        return FallbackNLU(
            primary,
            AnthropicHaikuNLU(
                api_key=settings.anthropic_api_key,
                model=settings.nlu_fallback_model,
                timeout_s=settings.nlu_timeout_s,
                topics=selected.nlu_topics,
            ),
        )
    return primary


def build_composer(
    settings: Settings,
    selection: AIProviderSelection | None = None,
) -> ComposerProvider:
    selected = selection or selection_from_config(settings, None)
    if not settings.openai_api_key:
        raise RuntimeError("OpenAI API key is required for Composer")
    return OpenAIComposer(
        api_key=settings.openai_api_key,
        model=selected.composer_model,
        timeout_s=settings.composer_timeout_s,
        retry_delays_ms=tuple(settings.composer_retry_delays_ms),
    )

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_DEFAULT_ENV_FILE,
        env_prefix="ATENDIA_V2_",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://atendia:atendia@localhost:5432/atendia_v2"
    )
    test_database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ATENDIA_TEST_DATABASE_URL", "ATENDIA_V2_TEST_DATABASE_URL"),
    )
    redis_url: str = Field(default="redis://localhost:6379/1")
    log_level: str = Field(default="INFO")
    meta_app_secret: str = Field(default="")
    meta_access_token: str = Field(default="")
    meta_api_version: str = Field(default="v21.0")
    meta_base_url: str = Field(default="https://graph.facebook.com")
    openai_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    nlu_model: str = Field(default="gpt-4o-mini")
    nlu_provider: Literal["openai"] = Field(default="openai")
    nlu_fallback_provider: Literal["haiku", "none"] = Field(default="haiku")
    nlu_fallback_model: str = Field(default="claude-haiku-4-5-20251001")
    nlu_timeout_s: float = Field(default=8.0)
    nlu_retry_delays_ms: list[int] = Field(default_factory=lambda: [500, 2000])
    composer_provider: Literal["openai"] = Field(default="openai")
    composer_model: str = Field(default="gpt-4o-mini")
    composer_timeout_s: float = Field(default=8.0)
    composer_retry_delays_ms: list[int] = Field(default_factory=lambda: [500, 2000])
    composer_max_messages: int = Field(default=2, ge=1, le=3)
    upload_dir: str = Field(default="./uploads")
    upload_max_file_size_bytes: int = Field(default=20 * 1024 * 1024)
    upload_tenant_quota_bytes: int = Field(default=250 * 1024 * 1024)
    storage_backend: Literal["local"] = Field(default="local")
    # Phase 4 — operator session auth (separate from Meta webhook secret).
    # Override via ATENDIA_V2_AUTH_SESSION_SECRET in production.
    auth_session_secret: str = Field(default="dev-only-fallback-auth-secret-DO-NOT-USE-IN-PROD")
    auth_session_ttl_s: int = Field(default=28800)  # 8h operator workday
    auth_cookie_secure: bool = Field(default=False)  # True in production behind TLS
    # Phase B2 KB module — selects the LLM provider for retrieval/answer.
    # ``mock`` is forced when ``openai_api_key`` is empty regardless of this
    # value, so dev environments without keys still work.
    kb_provider: Literal["openai", "mock"] = Field(default="openai")
    respond_style_audio_transcription_model: str = Field(default="gpt-4o-mini-transcribe")
    respond_style_audio_transcription_timeout_s: float = Field(default=20.0)
    # Baileys WhatsApp sidecar — see core/baileys-bridge/.
    baileys_bridge_url: str = Field(default="http://baileys-bridge:7755")
    baileys_internal_token: str = Field(default="dev-only-baileys-token-change-me")
    baileys_timeout_s: float = Field(default=8.0)
    dinamo_agent_first_enabled: bool = Field(default=False)
    agent_runtime_v2_enabled: bool = Field(default=False)
    agent_runtime_v2_send_enabled: bool = Field(default=False)
    agent_runtime_v2_actions_enabled: bool = Field(default=False)
    agent_runtime_v2_workflow_events_enabled: bool = Field(default=False)
    agent_runtime_v2_model_provider: Literal["disabled", "openai"] = Field(default="disabled")
    agent_runtime_v2_model: str = Field(default="gpt-4o-mini")
    agent_runtime_v2_model_timeout_s: float = Field(default=8.0)
    agent_runtime_v2_model_retry_delays_ms: list[int] = Field(default_factory=lambda: [500, 2000])
    agent_runtime_v2_model_max_retries: int = Field(default=2, ge=0, le=8)
    agent_runtime_v2_model_retry_base_delay_ms: int = Field(default=500, ge=0, le=30000)
    agent_runtime_v2_model_retry_max_delay_ms: int = Field(default=4000, ge=0, le=60000)
    agent_runtime_v2_model_retry_jitter_ms: int = Field(default=250, ge=0, le=10000)
    agent_runtime_v2_provider_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    agent_runtime_v2_provider_circuit_cooldown_s: float = Field(default=30.0, ge=0.0)
    agent_runtime_v2_max_actions_per_turn: int = Field(default=5, ge=1, le=20)
    agent_runtime_v2_action_failure_policy: Literal["continue", "stop"] = Field(default="continue")
    quote_safety_guard_mode: Literal["shadow", "block"] = Field(default="block")
    conversation_progress_guard_mode: Literal["shadow", "block"] = Field(default="block")


@lru_cache
def get_settings() -> Settings:
    return Settings()

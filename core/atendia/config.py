from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ATENDIA_V2_",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://atendia:atendia@localhost:5432/atendia_v2"
    )
    redis_url: str = Field(default="redis://localhost:6379/1")
    log_level: str = Field(default="INFO")
    meta_app_secret: str = Field(default="")
    meta_access_token: str = Field(default="")
    meta_api_version: str = Field(default="v21.0")
    meta_base_url: str = Field(default="https://graph.facebook.com")
    openai_api_key: str = Field(default="")
    nlu_model: str = Field(default="gpt-4o-mini")
    nlu_provider: Literal["openai", "keyword"] = Field(default="keyword")
    nlu_timeout_s: float = Field(default=8.0)
    nlu_retry_delays_ms: list[int] = Field(default_factory=lambda: [500, 2000])
    composer_provider: Literal["openai", "canned"] = Field(default="canned")
    composer_model: str = Field(default="gpt-4o")
    composer_timeout_s: float = Field(default=8.0)
    composer_retry_delays_ms: list[int] = Field(default_factory=lambda: [500, 2000])
    composer_max_messages: int = Field(default=2, ge=1, le=3)


@lru_cache
def get_settings() -> Settings:
    return Settings()

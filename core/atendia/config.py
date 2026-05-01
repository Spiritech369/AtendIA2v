from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()

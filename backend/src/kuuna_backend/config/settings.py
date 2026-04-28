from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Kuuna Backend"
    app_env: str = "dev"

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/kuuna",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    s3_bucket: str = Field(default="kuuna-dev", alias="S3_BUCKET")
    s3_access_key: str | None = Field(default=None, alias="S3_ACCESS_KEY")
    s3_secret_key: str | None = Field(default=None, alias="S3_SECRET_KEY")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_public_base_url: str | None = Field(default=None, alias="S3_PUBLIC_BASE_URL")

    media_processing_enabled: bool = Field(default=True, alias="MEDIA_PROCESSING_ENABLED")
    media_download_timeout_seconds: float = Field(default=20.0, alias="MEDIA_DOWNLOAD_TIMEOUT_SECONDS")

    internal_ops_token: str | None = Field(default=None, alias="INTERNAL_OPS_TOKEN")

    template_build_context_path: str = Field(
        default="../../infra/runtime/template-agent",
        alias="TEMPLATE_BUILD_CONTEXT_PATH",
    )
    docker_cli_path: str = Field(default="docker", alias="DOCKER_CLI_PATH")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_timeout_seconds: float = Field(default=30.0, alias="OPENAI_TIMEOUT_SECONDS")
    openai_audio_transcription_model: str = Field(
        default="gpt-4o-mini-transcribe",
        alias="OPENAI_AUDIO_TRANSCRIPTION_MODEL",
    )
    openai_vision_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_VISION_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
    )

    auth_token_secret: str = Field(default="dev-insecure-change-me", alias="AUTH_TOKEN_SECRET")
    auth_token_ttl_seconds: int = Field(default=3600, alias="AUTH_TOKEN_TTL_SECONDS")
    auth_lockout_threshold: int = Field(default=5, alias="AUTH_LOCKOUT_THRESHOLD")
    auth_lockout_seconds: int = Field(default=900, alias="AUTH_LOCKOUT_SECONDS")
    auth_password_min_length: int = Field(default=12, alias="AUTH_PASSWORD_MIN_LENGTH")
    auth_password_max_consecutive: int = Field(default=3, alias="AUTH_PASSWORD_MAX_CONSECUTIVE")
    auth_rate_limit_window_seconds: int = Field(default=60, alias="AUTH_RATE_LIMIT_WINDOW_SECONDS")
    auth_rate_limit_max_attempts: int = Field(default=20, alias="AUTH_RATE_LIMIT_MAX_ATTEMPTS")

    sentry_dsn: str | None = Field(default=None, alias="SENTRY_DSN")


@lru_cache
def get_settings() -> Settings:
    return Settings()

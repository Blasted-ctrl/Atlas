"""Application configuration via pydantic-settings.

All settings are read from environment variables. See .env.example for the
full list of supported variables.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AnyHttpUrl
from pydantic import Field
from pydantic import PostgresDsn
from pydantic import RedisDsn
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "Atlas API"
    app_version: str = "0.0.1"
    debug: bool = False
    log_level: str = "info"

    # ── Server ───────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1
    api_reload: bool = False
    api_secret_key: str = Field(
        default="atlas-local-dev-secret-key-change-me-0001",
        min_length=32,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    api_cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, v: bool | str) -> bool:
        if isinstance(v, bool):
            return v
        normalized = v.strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False
        return False

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://atlas:atlas_dev_password@localhost:5432/atlas"
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")

    # ── Celery ───────────────────────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── S3 / MinIO ────────────────────────────────────────────────────────────
    s3_endpoint_url: AnyHttpUrl | None = None
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "us-east-1"
    minio_bucket_costs: str = "atlas-cost-reports"
    minio_bucket_exports: str = "atlas-exports"

    # Telemetry / observability
    otel_enabled: bool = True
    otel_service_name: str = "atlas-api"
    otel_environment: str = "development"
    otel_exporter_otlp_endpoint: str | None = "http://localhost:4318/v1/traces"
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()

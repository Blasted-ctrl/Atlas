"""Worker configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic import PostgresDsn
from pydantic import RedisDsn
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Celery ───────────────────────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_worker_concurrency: int = 4

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://atlas:atlas_dev_password@localhost:5432/atlas"
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")

    # ── S3 / MinIO ────────────────────────────────────────────────────────────
    s3_endpoint_url: str | None = None
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "us-east-1"
    minio_bucket_costs: str = "atlas-cost-reports"

    # ── Optimization worker ───────────────────────────────────────────────────
    optimization_batch_size: int = 100          # resources per batch task
    optimization_lookback_days: int = 14        # days of usage data to analyse
    cpu_underutil_threshold: float = 20.0       # % avg CPU below which = underutilized
    mem_underutil_threshold: float = 40.0       # % avg memory below which = underutilized
    cpu_idle_threshold: float = 2.0             # % — hard idle (terminate candidate)
    min_sample_count: int = 48                  # minimum data points to trust the analysis
    min_monthly_cost_usd: float = 10.0          # skip resources cheaper than this

    # ── Idempotency ───────────────────────────────────────────────────────────
    idempotency_ttl_seconds: int = 86_400       # 24 h — how long to remember a processed key

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_calls: int = 120                 # max calls per window
    rate_limit_window_seconds: int = 60         # sliding window size

    # ── Dead-letter queue ─────────────────────────────────────────────────────
    dlq_redis_key_prefix: str = "atlas:dlq"    # Redis list key prefix
    dlq_max_persist_days: int = 30             # TTL for DLQ entries in Redis
    dlq_retry_limit: int = 3                    # extra retries from DLQ processor

    # ── Retry ─────────────────────────────────────────────────────────────────
    task_max_retries: int = 5
    task_retry_backoff_base: int = 2            # seconds base for exponential backoff
    task_retry_backoff_max: int = 300           # cap at 5 minutes

    # ── Forecasting ───────────────────────────────────────────────────────────
    forecast_horizon_days: int = 30           # days ahead to forecast
    forecast_lookback_days: int = 90          # days of history to fetch
    forecast_max_training_samples: int = 500  # cap training set (< 500 ms budget)
    forecast_cache_ttl_seconds: int = 6 * 3_600  # 6 h Redis TTL
    forecast_batch_size: int = 50             # resources per forecast batch task
    forecast_metrics: list[str] = Field(
        default_factory=lambda: ["cpu_utilization", "memory_utilization", "cost_usd"]
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "info"

    # Telemetry / observability
    otel_enabled: bool = True
    otel_service_name: str = "atlas-worker"
    otel_environment: str = "development"
    otel_exporter_otlp_endpoint: str | None = "http://localhost:4318/v1/traces"
    metrics_enabled: bool = True
    worker_metrics_port: int = 9465


@lru_cache(maxsize=1)
def get_settings() -> WorkerSettings:
    return WorkerSettings()

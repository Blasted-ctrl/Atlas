"""Celery application factory.

Usage:
    # Start a worker process
    celery -A worker.main worker --loglevel=info --concurrency=4

    # Start a beat scheduler (for periodic tasks)
    celery -A worker.main beat --loglevel=info

    # Inspect registered tasks
    celery -A worker.main inspect registered
"""

from __future__ import annotations

import logging

import structlog
from celery import Celery
from celery.signals import setup_logging
from celery.signals import worker_ready
from celery.signals import worker_shutdown

from worker.config import get_settings
from worker.telemetry import current_trace_context
from worker.telemetry import setup_telemetry

settings = get_settings()
setup_telemetry(settings)


def add_trace_context(
    _: object,
    __: str,
    event_dict: dict[str, object],
) -> dict[str, object]:
    """Attach trace/span ids to worker logs when present."""
    event_dict.update(current_trace_context())
    return event_dict

# ─── Create Celery app ────────────────────────────────────────────────────────

app = Celery(
    "atlas",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "worker.tasks.cost_sync",
        "worker.tasks.recommendations",
        "worker.tasks.optimize",
        "worker.tasks.dlq_processor",
        "worker.tasks.forecast",
    ],
)

app.conf.update(
    # ── Serialisation ──────────────────────────────────────────────────────────
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # ── Timezone ───────────────────────────────────────────────────────────────
    timezone="UTC",
    enable_utc=True,

    # ── Reliability ────────────────────────────────────────────────────────────
    # acks_late: message stays in the broker until the task succeeds, so a
    # crashed worker doesn't silently drop work.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # prefetch=1: each worker requests one task at a time — better load
    # distribution for variable-duration optimization tasks.
    worker_prefetch_multiplier=1,

    # ── Results ────────────────────────────────────────────────────────────────
    result_expires=7200,   # 2 hours — optimization jobs can take a while
    result_persistent=True,

    # ── Queues ─────────────────────────────────────────────────────────────────
    task_default_queue="default",
    task_queues={
        "default":      {"exchange": "default",      "routing_key": "default"},
        "optimization": {"exchange": "optimization", "routing_key": "optimization"},
        "forecasting":  {"exchange": "forecasting",  "routing_key": "forecasting"},
        "low_priority": {"exchange": "low_priority", "routing_key": "low_priority"},
        "dlq":          {"exchange": "dlq",          "routing_key": "dlq"},
    },
    task_routes={
        "worker.tasks.cost_sync.*":    {"queue": "default"},
        "worker.tasks.recommendations.*": {"queue": "low_priority"},
        "worker.tasks.optimize.*":     {"queue": "optimization"},
        "worker.tasks.forecast.*":     {"queue": "forecasting"},
        "worker.tasks.dlq_processor.*": {"queue": "dlq"},
    },

    # ── Per-task rate limits (Celery built-in, per-worker) ─────────────────────
    # Distributed enforcement happens inside the task via rate_limiter.py.
    # These are a secondary guard against runaway workers.
    task_annotations={
        "worker.tasks.optimize.optimize_resource_batch": {
            "rate_limit": "30/m",   # 30 batches/min per worker process
        },
        "worker.tasks.optimize.optimize_single_resource": {
            "rate_limit": "120/m",  # 120 resources/min per worker process
        },
    },

    # ── Beat schedule ──────────────────────────────────────────────────────────
    beat_schedule={
        "sync-all-accounts-hourly": {
            "task": "worker.tasks.cost_sync.sync_all_accounts",
            "schedule": 3600.0,
            "options": {"queue": "default"},
        },
        "refresh-recommendations-daily": {
            "task": "worker.tasks.recommendations.refresh_all_recommendations",
            "schedule": 86_400.0,
            "options": {"queue": "low_priority"},
        },
        "process-dlq-every-15min": {
            "task": "worker.tasks.dlq_processor.process_dlq_jobs",
            "schedule": 900.0,   # every 15 minutes
            "options": {"queue": "dlq"},
        },
        "expire-stale-recommendations-daily": {
            "task": "worker.tasks.dlq_processor.expire_stale_recommendations",
            "schedule": 86_400.0,
            "options": {"queue": "low_priority"},
        },
        "run-forecasts-daily": {
            "task": "worker.tasks.forecast.run_forecast_pipeline",
            "schedule": 86_400.0,   # once per day — forecasts have 6 h cache TTL
            "kwargs": {"metrics": ["cpu_utilization", "memory_utilization", "cost_usd"]},
            "options": {"queue": "forecasting"},
        },
    },

    # ── Worker tuning ──────────────────────────────────────────────────────────
    worker_max_tasks_per_child=500,  # recycle after N tasks to prevent memory leaks
    worker_disable_rate_limits=False,
)


# ─── Logging ─────────────────────────────────────────────────────────────────

@setup_logging.connect
def configure_logging(**kwargs: object) -> None:  # type: ignore[misc]
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            add_trace_context,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=log_level, force=True)


logger = structlog.get_logger(__name__)


@worker_ready.connect
def on_worker_ready(**kwargs: object) -> None:  # type: ignore[misc]
    logger.info("atlas_worker_ready", broker=settings.celery_broker_url)


@worker_shutdown.connect
def on_worker_shutdown(**kwargs: object) -> None:  # type: ignore[misc]
    logger.info("atlas_worker_shutdown")

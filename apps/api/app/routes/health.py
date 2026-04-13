"""Health check endpoint.

GET /health — returns platform component status.
Used by Docker healthchecks, load balancers, and the web frontend.
"""

from __future__ import annotations

import time
from datetime import UTC
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


class ComponentStatus(BaseModel):
    database: Literal["ok", "error"]
    redis: Literal["ok", "error"]
    storage: Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    timestamp: str
    uptime_seconds: float
    checks: ComponentStatus


_start_time = time.monotonic()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Platform health check",
    description="Returns the operational status of all platform components.",
)
async def health_check() -> HealthResponse:
    settings = get_settings()
    checks = await _run_checks()
    failed = [v for v in (checks.database, checks.redis, checks.storage) if v == "error"]

    if not failed:
        status: Literal["ok", "degraded", "down"] = "ok"
    elif len(failed) < 3:
        status = "degraded"
    else:
        status = "down"

    if status != "ok":
        logger.warning("health_check_degraded", status=status, checks=checks.model_dump())

    return HealthResponse(
        status=status,
        version=settings.app_version,
        timestamp=datetime.now(UTC).isoformat(),
        uptime_seconds=round(time.monotonic() - _start_time, 2),
        checks=checks,
    )


async def _run_checks() -> ComponentStatus:
    """Probe each downstream dependency. Failures are non-fatal."""
    db_status = await _check_database()
    redis_status = await _check_redis()
    storage_status = await _check_storage()

    return ComponentStatus(
        database=db_status,
        redis=redis_status,
        storage=storage_status,
    )


async def _check_database() -> Literal["ok", "error"]:
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = get_settings()
        engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return "ok"
    except Exception as exc:
        logger.warning("database_health_check_failed", error=str(exc))
        return "error"


async def _check_redis() -> Literal["ok", "error"]:
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        client = aioredis.from_url(str(settings.redis_url), socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        return "ok"
    except Exception as exc:
        logger.warning("redis_health_check_failed", error=str(exc))
        return "error"


async def _check_storage() -> Literal["ok", "error"]:
    # MinIO / S3 check — just verifies connectivity, not bucket existence
    try:
        import httpx

        settings = get_settings()
        if not settings.s3_endpoint_url:
            return "ok"  # storage not configured, skip
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(str(settings.s3_endpoint_url))
            return "ok" if resp.status_code < 500 else "error"
    except Exception as exc:
        logger.warning("storage_health_check_failed", error=str(exc))
        return "error"

"""Shared Redis client for the worker process.

A single connection pool is created at import time and reused across all
tasks in the same worker process. The pool is thread-safe and sized to match
the worker's concurrency level.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import redis

from worker.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Return the shared Redis client (lazy, cached per process)."""
    settings = get_settings()
    url = str(settings.redis_url)
    pool = redis.ConnectionPool.from_url(
        url,
        max_connections=20,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    client = redis.Redis(connection_pool=pool)
    logger.info("Redis connection pool initialised url=%s", url)
    return client


def ping() -> bool:
    """Return True if Redis is reachable."""
    try:
        return get_redis().ping()
    except redis.RedisError:
        return False

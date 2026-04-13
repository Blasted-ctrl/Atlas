"""Redis cache layer for forecast results.

Cache key pattern
-----------------
    atlas:forecast:{resource_id}:{metric}

A cached entry stores the full JSON payload (same shape as the API response).
TTL defaults to 6 hours — forecasts are regenerated daily so stale entries
self-evict well before the next run.
"""

from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from worker.redis_client import get_redis

# ── Constants ─────────────────────────────────────────────────────────────────

_KEY_PREFIX = "atlas:forecast"
DEFAULT_TTL_SECONDS = 6 * 3_600   # 6 hours


# ── Key helper ────────────────────────────────────────────────────────────────

def _key(resource_id: str | UUID, metric: str) -> str:
    return f"{_KEY_PREFIX}:{resource_id}:{metric}"


# ── Write ─────────────────────────────────────────────────────────────────────

def cache_forecast(
    resource_id: str | UUID,
    metric: str,
    payload: dict[str, Any],
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    """Serialise *payload* to JSON and store it in Redis with *ttl_seconds*.

    *payload* should match the REST API response shape so callers can return
    it directly without hitting Postgres.
    """
    r = get_redis()
    r.setex(_key(resource_id, metric), ttl_seconds, json.dumps(payload, default=_json_default))


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


# ── Read ──────────────────────────────────────────────────────────────────────

def get_cached_forecast(
    resource_id: str | UUID,
    metric: str,
) -> dict[str, Any] | None:
    """Return the cached forecast dict or ``None`` if absent / expired."""
    r = get_redis()
    raw = r.get(_key(resource_id, metric))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# ── Invalidate ────────────────────────────────────────────────────────────────

def invalidate_forecast(resource_id: str | UUID, metric: str) -> None:
    """Delete the cache entry for a specific (resource, metric) pair."""
    r = get_redis()
    r.delete(_key(resource_id, metric))


def invalidate_all_forecasts(resource_id: str | UUID) -> int:
    """Delete all cached forecasts for *resource_id*.  Returns the count deleted."""
    r = get_redis()
    pattern = f"{_KEY_PREFIX}:{resource_id}:*"
    keys = r.keys(pattern)
    if not keys:
        return 0
    return r.delete(*keys)

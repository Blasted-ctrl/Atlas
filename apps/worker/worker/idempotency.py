"""Redis-backed idempotency guard for worker tasks.

Each unit of work is identified by a SHA-256 key derived from the inputs
(resource_id + run_id). Before processing, the worker checks whether the key
already exists. On completion (success or permanent failure) the key is stored
with a configurable TTL.

Key format:
    atlas:idempotency:<sha256(resource_id:run_id)>

Value (JSON):
    {
        "status":      "success" | "failed" | "skipped",
        "resource_id": "...",
        "run_id":      "...",
        "result":      {...},          # task-specific payload
        "processed_at": "ISO timestamp"
    }

Execution log (separate key, list):
    atlas:execlog:<run_id>  →  list of JSON log entries (LPUSH, capped to 10 000)

Both keys share the configured TTL so they expire together.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any

from worker.config import get_settings
from worker.redis_client import get_redis

logger = logging.getLogger(__name__)

_IDEMPOTENCY_PREFIX = "atlas:idempotency"
_EXECLOG_PREFIX = "atlas:execlog"
_EXECLOG_MAX_ENTRIES = 10_000


class ProcessingStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"


def make_key(resource_id: str, run_id: str) -> str:
    """Return the canonical idempotency key for a (resource, run) pair.

    Uses SHA-256 so the key length is fixed regardless of input length, and
    adversarial inputs cannot enumerate other resources' keys.
    """
    raw = f"{resource_id}:{run_id}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"{_IDEMPOTENCY_PREFIX}:{digest}"


def is_already_processed(resource_id: str, run_id: str) -> bool:
    """Return True if this (resource, run) pair has already been completed."""
    r = get_redis()
    key = make_key(resource_id, run_id)
    raw = r.get(key)
    if raw is None:
        return False
    try:
        data = json.loads(raw)
        return data.get("status") in (ProcessingStatus.SUCCESS, ProcessingStatus.FAILED)
    except (json.JSONDecodeError, KeyError):
        return False


def claim(resource_id: str, run_id: str) -> bool:
    """Atomically claim a processing slot.

    Uses SET NX (set if not exists) so only the first worker to call this for a
    given key wins. Returns True if the claim was granted, False if another
    worker already owns it (idempotency collision).
    """
    settings = get_settings()
    r = get_redis()
    key = make_key(resource_id, run_id)
    payload = json.dumps({
        "status": ProcessingStatus.IN_PROGRESS,
        "resource_id": resource_id,
        "run_id": run_id,
        "claimed_at": _now_iso(),
    })
    # NX = only set if key does not exist; EX = TTL in seconds
    granted = r.set(key, payload, nx=True, ex=settings.idempotency_ttl_seconds)
    return bool(granted)


def mark_done(
    resource_id: str,
    run_id: str,
    status: ProcessingStatus,
    result: dict[str, Any] | None = None,
) -> None:
    """Write the final state for this (resource, run) pair."""
    settings = get_settings()
    r = get_redis()
    key = make_key(resource_id, run_id)
    payload = json.dumps({
        "status": status,
        "resource_id": resource_id,
        "run_id": run_id,
        "result": result or {},
        "processed_at": _now_iso(),
    })
    r.set(key, payload, ex=settings.idempotency_ttl_seconds)


def log_execution(
    run_id: str,
    resource_id: str,
    status: ProcessingStatus,
    detail: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Append a structured entry to the run's execution log (Redis list).

    The list is capped at _EXECLOG_MAX_ENTRIES to prevent unbounded growth.
    """
    settings = get_settings()
    r = get_redis()
    log_key = f"{_EXECLOG_PREFIX}:{run_id}"
    entry = json.dumps({
        "resource_id": resource_id,
        "status": status,
        "detail": detail or {},
        "error": error,
        "ts": _now_iso(),
    })
    pipe = r.pipeline()
    pipe.lpush(log_key, entry)
    pipe.ltrim(log_key, 0, _EXECLOG_MAX_ENTRIES - 1)
    pipe.expire(log_key, settings.idempotency_ttl_seconds)
    pipe.execute()


def get_execution_log(run_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Return the most recent `limit` log entries for a run (newest first)."""
    r = get_redis()
    log_key = f"{_EXECLOG_PREFIX}:{run_id}"
    entries = r.lrange(log_key, 0, limit - 1)
    result = []
    for raw in entries:
        try:
            result.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return result


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

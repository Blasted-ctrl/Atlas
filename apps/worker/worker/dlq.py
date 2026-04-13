"""Dead-letter queue (DLQ) implementation.

Failed jobs that have exhausted their Celery retry budget are serialised and
pushed to two durable stores:

1. Redis list  atlas:dlq:<queue_name>
   Fast, low-latency, used by the DLQ processor task for re-processing.

2. Postgres table  worker_failed_jobs
   Long-term audit trail; survives Redis eviction.
   Created with CREATE TABLE IF NOT EXISTS so no migration file is required.

Schema of a FailedJob (JSON-serialised for Redis):
    {
        "id":               "<uuid>",
        "task_name":        "worker.tasks.optimize.optimize_resource_batch",
        "task_id":          "<celery task id>",
        "queue":            "optimization",
        "args":             [...],
        "kwargs":           {...},
        "exception_type":   "psycopg2.OperationalError",
        "exception_message": "...",
        "traceback":        "...",
        "retry_count":      5,
        "failed_at":        "2024-03-01T12:00:00Z",
        "dlq_attempts":     0       -- incremented each time DLQ processor tries it
    }
"""

from __future__ import annotations

import json
import logging
import traceback as tb_module
import uuid
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
from typing import Any

import redis

from worker.config import get_settings
from worker.db import get_cursor
from worker.redis_client import get_redis
from worker.telemetry import increment_job_failure
from worker.telemetry import update_queue_depth

logger = logging.getLogger(__name__)

_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS worker_failed_jobs (
    id              UUID         PRIMARY KEY,
    task_name       TEXT         NOT NULL,
    task_id         TEXT         NOT NULL,
    queue           TEXT         NOT NULL DEFAULT 'default',
    args            JSONB        NOT NULL DEFAULT '[]',
    kwargs          JSONB        NOT NULL DEFAULT '{}',
    exception_type  TEXT         NOT NULL,
    exception_msg   TEXT         NOT NULL,
    traceback       TEXT         NOT NULL DEFAULT '',
    retry_count     INTEGER      NOT NULL DEFAULT 0,
    dlq_attempts    INTEGER      NOT NULL DEFAULT 0,
    failed_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    resolution      TEXT         -- 'retried', 'discarded', 'manual'
);

CREATE INDEX IF NOT EXISTS idx_wfj_task_name  ON worker_failed_jobs (task_name);
CREATE INDEX IF NOT EXISTS idx_wfj_failed_at  ON worker_failed_jobs (failed_at DESC);
CREATE INDEX IF NOT EXISTS idx_wfj_unresolved ON worker_failed_jobs (failed_at DESC)
    WHERE resolved_at IS NULL;
"""

_table_ensured = False


def _ensure_table() -> None:
    global _table_ensured
    if _table_ensured:
        return
    try:
        with get_cursor() as cur:
            cur.execute(_ENSURE_TABLE_SQL)
        _table_ensured = True
    except Exception as exc:
        logger.error("dlq_ensure_table_failed error=%s", exc)


# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FailedJob:
    task_name: str
    task_id: str
    args: list[Any]
    kwargs: dict[str, Any]
    exception_type: str
    exception_message: str
    traceback: str
    retry_count: int
    queue: str = "default"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    dlq_attempts: int = 0
    failed_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "FailedJob":
        return cls(**json.loads(raw))

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        task_name: str,
        task_id: str,
        args: list[Any],
        kwargs: dict[str, Any],
        retry_count: int,
        queue: str = "default",
    ) -> "FailedJob":
        return cls(
            task_name=task_name,
            task_id=task_id,
            args=args,
            kwargs=kwargs,
            exception_type=type(exc).__qualname__,
            exception_message=str(exc),
            traceback=tb_module.format_exc(),
            retry_count=retry_count,
            queue=queue,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Push / pop
# ─────────────────────────────────────────────────────────────────────────────

def push(job: FailedJob) -> None:
    """Persist a failed job to Redis and Postgres.

    Both writes are attempted independently: a Redis failure doesn't prevent
    the Postgres write and vice versa.
    """
    settings = get_settings()
    redis_key = f"{settings.dlq_redis_key_prefix}:{job.queue}"
    ttl = settings.dlq_max_persist_days * 86_400

    # ── Redis ──────────────────────────────────────────────────────────────────
    try:
        r = get_redis()
        r.lpush(redis_key, job.to_json())
        r.expire(redis_key, ttl)
        increment_job_failure(job.task_name, job.queue)
        update_queue_depth(job.queue, int(r.llen(redis_key)))
        logger.info("dlq_push_redis task=%s task_id=%s key=%s",
                    job.task_name, job.task_id, redis_key)
    except redis.RedisError as exc:
        logger.error("dlq_push_redis_failed task=%s error=%s", job.task_name, exc)

    # ── Postgres ───────────────────────────────────────────────────────────────
    _ensure_table()
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO worker_failed_jobs
                    (id, task_name, task_id, queue, args, kwargs,
                     exception_type, exception_msg, traceback, retry_count,
                     dlq_attempts, failed_at)
                VALUES (%(id)s, %(task_name)s, %(task_id)s, %(queue)s,
                        %(args)s::jsonb, %(kwargs)s::jsonb,
                        %(exception_type)s, %(exception_message)s,
                        %(traceback)s, %(retry_count)s,
                        %(dlq_attempts)s, %(failed_at)s)
                ON CONFLICT (id) DO NOTHING
                """,
                {
                    **asdict(job),
                    "args": json.dumps(job.args),
                    "kwargs": json.dumps(job.kwargs),
                },
            )
        logger.info("dlq_push_postgres task=%s id=%s", job.task_name, job.id)
    except Exception as exc:
        logger.error("dlq_push_postgres_failed task=%s error=%s", job.task_name, exc)


def pop(queue: str = "default", count: int = 10) -> list[FailedJob]:
    """Pop up to `count` jobs from the Redis DLQ for a given queue name.

    Uses RPOP (FIFO order — oldest first) so jobs are reprocessed in the
    order they failed.
    """
    settings = get_settings()
    redis_key = f"{settings.dlq_redis_key_prefix}:{queue}"
    r = get_redis()

    jobs: list[FailedJob] = []
    for _ in range(count):
        raw = r.rpop(redis_key)
        if raw is None:
            break
        try:
            jobs.append(FailedJob.from_json(raw))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("dlq_pop_deserialise_failed error=%s raw=%s", exc, raw[:200])

    update_queue_depth(queue, int(r.llen(redis_key)))
    return jobs


def depth(queue: str = "default") -> int:
    """Return the number of jobs currently in the Redis DLQ."""
    settings = get_settings()
    redis_key = f"{settings.dlq_redis_key_prefix}:{queue}"
    current_depth = int(get_redis().llen(redis_key))
    update_queue_depth(queue, current_depth)
    return current_depth


def mark_resolved(job_id: str, resolution: str = "retried") -> None:
    """Update the Postgres record when a DLQ job is successfully reprocessed."""
    _ensure_table()
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE worker_failed_jobs
                   SET resolved_at = NOW(),
                       resolution  = %(resolution)s
                 WHERE id = %(id)s
                """,
                {"id": job_id, "resolution": resolution},
            )
    except Exception as exc:
        logger.error("dlq_mark_resolved_failed id=%s error=%s", job_id, exc)


def list_unresolved(limit: int = 100) -> list[dict[str, Any]]:
    """Return unresolved failed jobs from Postgres (for ops dashboards)."""
    _ensure_table()
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, task_name, task_id, queue, exception_type,
                   exception_msg, retry_count, dlq_attempts, failed_at
              FROM worker_failed_jobs
             WHERE resolved_at IS NULL
             ORDER BY failed_at DESC
             LIMIT %(limit)s
            """,
            {"limit": limit},
        )
        return [dict(row) for row in cur.fetchall()]

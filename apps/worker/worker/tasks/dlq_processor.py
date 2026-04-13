"""DLQ processor — periodic tasks that drain the dead-letter queue.

Responsibilities:
  1. Pop failed jobs from Redis DLQ
  2. Attempt re-queuing via Celery (up to dlq_retry_limit extra attempts)
  3. Discard or alert on jobs that keep failing
  4. Run the DB-level recommendation expiry sweep

Triggered by Celery Beat every 15 minutes (see main.py beat_schedule).
"""

from __future__ import annotations

from celery import Task
from celery.utils.log import get_task_logger

from worker import dlq
from worker.config import get_settings
from worker.db import get_cursor
from worker.main import app

logger = get_task_logger(__name__)
settings = get_settings()

# Queue names that have a DLQ
_MANAGED_QUEUES = ["optimization", "default", "low_priority"]


@app.task(
    bind=True,
    name="worker.tasks.dlq_processor.process_dlq_jobs",
    queue="dlq",
    max_retries=3,
    acks_late=True,
)
def process_dlq_jobs(self: Task) -> dict[str, int]:  # type: ignore[type-arg]
    """Drain DLQ items for all managed queues.

    For each failed job:
      - dlq_attempts < dlq_retry_limit  → re-queue the task
      - dlq_attempts >= dlq_retry_limit → mark as discarded (needs human review)

    Returns a summary dict with counts per outcome.
    """
    log = logger.bind(task_id=self.request.id)  # type: ignore[attr-defined]
    log.info("dlq_processor_start")

    summary = {"requeued": 0, "discarded": 0, "errors": 0}

    for queue_name in _MANAGED_QUEUES:
        depth = dlq.depth(queue_name)
        if depth == 0:
            continue

        log.info("dlq_draining", queue=queue_name, depth=depth)
        jobs = dlq.pop(queue=queue_name, count=min(depth, 50))  # process max 50 per run

        for job in jobs:
            try:
                if job.dlq_attempts >= settings.dlq_retry_limit:
                    log.warning(
                        "dlq_job_discarded",
                        task=job.task_name,
                        task_id=job.task_id,
                        attempts=job.dlq_attempts,
                    )
                    dlq.mark_resolved(job.id, resolution="discarded")
                    summary["discarded"] += 1
                    continue

                # Increment attempt count before re-queuing
                job.dlq_attempts += 1

                # Re-queue by sending to Celery directly by task name
                app.send_task(
                    job.task_name,
                    args=job.args,
                    kwargs=job.kwargs,
                    queue=job.queue,
                    countdown=60 * job.dlq_attempts,  # back-off per DLQ attempt
                )
                dlq.mark_resolved(job.id, resolution="retried")
                log.info(
                    "dlq_job_requeued",
                    task=job.task_name,
                    task_id=job.task_id,
                    dlq_attempts=job.dlq_attempts,
                )
                summary["requeued"] += 1

            except Exception as exc:  # noqa: BLE001
                log.error(
                    "dlq_requeue_error",
                    task=job.task_name,
                    error=str(exc),
                    exc_info=True,
                )
                # Push back to DLQ so it's not lost
                dlq.push(job)
                summary["errors"] += 1

    log.info("dlq_processor_complete", **summary)
    return summary


@app.task(
    bind=True,
    name="worker.tasks.dlq_processor.expire_stale_recommendations",
    queue="low_priority",
    max_retries=3,
    acks_late=True,
)
def expire_stale_recommendations(self: Task) -> dict[str, int]:  # type: ignore[type-arg]
    """Call the DB-level expiry sweep for overdue pending recommendations.

    Wraps the expire_stale_recommendations() Postgres function defined in
    migration 005_triggers.up.sql.
    """
    log = logger.bind(task_id=self.request.id)  # type: ignore[attr-defined]
    log.info("expire_recommendations_start")

    try:
        with get_cursor() as cur:
            cur.execute("SELECT expire_stale_recommendations()")
            row = cur.fetchone()
            expired = int(row["expire_stale_recommendations"]) if row else 0
    except Exception as exc:
        log.error("expire_recommendations_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60)

    log.info("expire_recommendations_complete", expired=expired)
    return {"expired": expired}

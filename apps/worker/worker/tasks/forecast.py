"""Celery tasks for the forecasting pipeline.

Task graph
----------
::

    run_forecast_pipeline(run_id, resource_ids, metrics)
        └─ chord(
               forecast_resource_batch.s(batch, metrics)
               for batch in chunked(resource_ids, batch_size)
           ) | finalize_forecast_run.s(run_id)

Each ``forecast_resource_batch`` task iterates resources × metrics, calls
``ForecastPipeline.run()``, and collects per-item outcomes.  Permanent failures
are isolated (the batch continues); transient failures are retried with
exponential back-off.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import uuid4

import structlog
from celery import chord

from worker.config import get_settings
from worker.dlq import FailedJob
from worker.dlq import push as dlq_push
from worker.forecasting.pipeline import ForecastPipeline
from worker.idempotency import claim
from worker.idempotency import is_already_processed
from worker.idempotency import log_execution
from worker.main import app as celery_app

logger = structlog.get_logger(__name__)

settings = get_settings()


# ── Exceptions ────────────────────────────────────────────────────────────────

class PermanentForecastError(Exception):
    """Non-retriable error for a single (resource, metric) pair."""


class TransientForecastError(Exception):
    """Retriable error; idempotency key is released so the retry can re-claim."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def _retry_countdown(attempt: int) -> int:
    base = settings.task_retry_backoff_base
    cap = settings.task_retry_backoff_max
    return min(cap, base ** (attempt + 1))


# ── Fan-out entry point ───────────────────────────────────────────────────────

@celery_app.task(
    name="worker.tasks.forecast.run_forecast_pipeline",
    bind=True,
    acks_late=True,
    task_reject_on_worker_lost=True,
    max_retries=settings.task_max_retries,
    queue="forecasting",
)
def run_forecast_pipeline(
    self,
    *,
    run_id: str | None = None,
    resource_ids: list[str],
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Fan-out: split resource list into batches, chord → finalize."""
    run_id = run_id or str(uuid4())
    metrics = metrics or settings.forecast_metrics
    batch_size = settings.forecast_batch_size

    log = logger.bind(run_id=run_id, total_resources=len(resource_ids))
    log.info("forecast_pipeline.start")

    batches = _chunk(resource_ids, batch_size)
    batch_tasks = [
        forecast_resource_batch.s(
            resource_ids=batch,
            metrics=metrics,
            run_id=run_id,
        )
        for batch in batches
    ]

    workflow = chord(batch_tasks)(finalize_forecast_run.s(run_id=run_id))
    return {"run_id": run_id, "batches": len(batches), "chord_id": workflow.id}


# ── Batch processor ───────────────────────────────────────────────────────────

@celery_app.task(
    name="worker.tasks.forecast.forecast_resource_batch",
    bind=True,
    acks_late=True,
    task_reject_on_worker_lost=True,
    max_retries=settings.task_max_retries,
    queue="forecasting",
)
def forecast_resource_batch(
    self,
    *,
    resource_ids: list[str],
    metrics: list[str],
    run_id: str,
) -> dict[str, Any]:
    """Process a batch of resources × metrics through the forecast pipeline.

    Each (resource_id, metric) pair is processed independently.  Permanent
    failures are recorded in the DLQ and skipped; transient failures are
    retried.  The task never fails the entire batch due to a single bad resource.
    """
    pipeline = ForecastPipeline()
    outcomes: dict[str, dict] = {}

    for resource_id in resource_ids:
        for metric in metrics:
            pair_key = f"{resource_id}:{metric}"
            idempotency_key = f"forecast:{run_id}:{pair_key}"

            # ── Idempotency check ─────────────────────────────────────────────
            if is_already_processed(idempotency_key):
                outcomes[pair_key] = {"status": "duplicate"}
                continue

            if not claim(idempotency_key, payload={"run_id": run_id, "metric": metric}):
                outcomes[pair_key] = {"status": "claimed_by_peer"}
                continue

            # ── Run pipeline ──────────────────────────────────────────────────
            try:
                result = pipeline.run(resource_id=resource_id, metric=metric)

                if result.skipped:
                    log_execution(
                        idempotency_key,
                        run_id=run_id,
                        status="SKIPPED",
                        reason=result.skip_reason,
                    )
                    outcomes[pair_key] = {"status": "skipped", "reason": result.skip_reason}
                else:
                    log_execution(
                        idempotency_key,
                        run_id=run_id,
                        status="SUCCESS",
                        forecast_id=str(result.forecast_id),
                        model=result.model_type,
                        training_ms=result.training_time_ms,
                        mape=result.metrics.mape if result.metrics else None,
                    )
                    logger.info(
                        "forecast.complete",
                        resource_id=resource_id,
                        metric=metric,
                        model=result.model_type,
                        training_ms=result.training_time_ms,
                        mape=result.metrics.mape if result.metrics else None,
                    )
                    outcomes[pair_key] = {
                        "status": "success",
                        "forecast_id": str(result.forecast_id),
                        "model": result.model_type,
                        "training_ms": result.training_time_ms,
                    }

            except TransientForecastError as exc:
                # Release idempotency claim so the retry can re-acquire
                from worker.redis_client import get_redis
                get_redis().delete(f"atlas:idempotency:{idempotency_key}")
                countdown = _retry_countdown(self.request.retries)
                logger.warning(
                    "forecast.transient_error",
                    resource_id=resource_id,
                    metric=metric,
                    error=str(exc),
                    retry_in=countdown,
                )
                raise self.retry(exc=exc, countdown=countdown)

            except PermanentForecastError as exc:
                log_execution(
                    idempotency_key,
                    run_id=run_id,
                    status="FAILED",
                    error=str(exc),
                )
                dlq_push(
                    FailedJob.from_exception(
                        exc,
                        task_name="forecast_resource_batch",
                        task_id=self.request.id or "",
                        args=[],
                        kwargs={"resource_id": resource_id, "metric": metric, "run_id": run_id},
                        queue="forecasting",
                    )
                )
                logger.error(
                    "forecast.permanent_error",
                    resource_id=resource_id,
                    metric=metric,
                    error=str(exc),
                )
                outcomes[pair_key] = {"status": "failed", "error": str(exc)}

            except Exception as exc:
                # Treat unexpected errors as permanent to avoid runaway retries
                log_execution(
                    idempotency_key,
                    run_id=run_id,
                    status="FAILED",
                    error=repr(exc),
                )
                dlq_push(
                    FailedJob.from_exception(
                        exc,
                        task_name="forecast_resource_batch",
                        task_id=self.request.id or "",
                        args=[],
                        kwargs={"resource_id": resource_id, "metric": metric, "run_id": run_id},
                        queue="forecasting",
                    )
                )
                logger.exception(
                    "forecast.unexpected_error",
                    resource_id=resource_id,
                    metric=metric,
                )
                outcomes[pair_key] = {"status": "failed", "error": repr(exc)}

    success = sum(1 for v in outcomes.values() if v["status"] == "success")
    skipped = sum(1 for v in outcomes.values() if v["status"] == "skipped")
    failed = sum(1 for v in outcomes.values() if v["status"] == "failed")

    return {
        "run_id": run_id,
        "total": len(outcomes),
        "success": success,
        "skipped": skipped,
        "failed": failed,
    }


# ── Chord callback ────────────────────────────────────────────────────────────

@celery_app.task(
    name="worker.tasks.forecast.finalize_forecast_run",
    bind=True,
    queue="forecasting",
)
def finalize_forecast_run(
    self,
    batch_results: list[dict[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Chord callback: aggregate batch outcomes and log the run summary."""
    total = sum(r.get("total", 0) for r in batch_results)
    success = sum(r.get("success", 0) for r in batch_results)
    skipped = sum(r.get("skipped", 0) for r in batch_results)
    failed = sum(r.get("failed", 0) for r in batch_results)

    logger.info(
        "forecast_pipeline.complete",
        run_id=run_id,
        total=total,
        success=success,
        skipped=skipped,
        failed=failed,
        completed_at=datetime.now(tz=timezone.utc).isoformat(),
    )

    return {
        "run_id": run_id,
        "total": total,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "completed_at": datetime.now(tz=timezone.utc).isoformat(),
    }

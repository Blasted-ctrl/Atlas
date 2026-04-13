"""optimize_resources — main optimization pipeline tasks.

Execution model
---------------
                        optimize_resources(run_id, scope)
                                 │
                    ┌────────────▼─────────────┐
                    │  fan-out to N batches     │  (Celery group)
                    └────────────┬─────────────┘
                                 │
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
  optimize_resource_batch   optimize_resource_batch   …
   [resource_ids 0-99]       [resource_ids 100-199]
             │
      for each resource_id:
             │
      ┌──────▼───────┐
      │ idempotency  │ ── already done? → skip
      │   claim      │
      └──────┬───────┘
             │
      ┌──────▼───────┐
      │ rate limiter │ ── wait for slot
      └──────┬───────┘
             │
      optimize_single_resource(run_id, resource_id)
             │
        ┌────┴─────────────────────────┐
        │  fetch_usage_metrics(14d)    │
        │  detect_underutilization()   │
        │  generate_recommendation()   │
        │  persist to DB               │
        └──────────────────────────────┘

Partial failures are contained at the per-resource level: one bad resource
does not abort the batch. The batch task retries as a whole only on
transient infrastructure errors (DB/Redis connectivity).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any

import psycopg2
import psycopg2.extras
import structlog
from celery import Task
from celery import chord
from celery import group

from worker import dlq
from worker import idempotency
from worker.config import get_settings
from worker.db import get_cursor
from worker.idempotency import ProcessingStatus
from worker.main import app
from worker.rate_limiter import RateLimiter
from worker.telemetry import observe_optimization
from worker.telemetry import update_queue_depth
from worker.telemetry import worker_span

logger = structlog.get_logger(__name__)
settings = get_settings()

# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class TransientError(Exception):
    """Retryable infrastructure error (DB/Redis unavailable, network blip)."""


class PermanentError(Exception):
    """Non-retryable error — resource invalid, data corrupt, etc."""


# ─────────────────────────────────────────────────────────────────────────────
# Data transfer objects
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MetricSummary:
    metric: str
    avg: float
    max: float
    p95: float
    samples: int


@dataclass
class UtilizationAnalysis:
    resource_id: str
    cpu_avg: float | None
    cpu_p95: float | None
    mem_avg: float | None
    net_in_avg: float | None
    samples: int
    is_underutilized: bool
    is_idle: bool
    recommendation_type: str | None     # 'resize_down' | 'terminate' | 'schedule' | None
    confidence: float
    observation_days: int


@dataclass
class BatchResult:
    run_id: str
    batch_index: int
    total: int
    succeeded: int
    skipped: int
    failed: int
    failed_resource_ids: list[str]
    duration_seconds: float


# ─────────────────────────────────────────────────────────────────────────────
# Base task with DLQ on_failure hook
# ─────────────────────────────────────────────────────────────────────────────


class AtlasBaseTask(Task):  # type: ignore[misc]
    """Task base class that pushes exhausted retries to the DLQ."""

    abstract = True

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,  # type: ignore[type-arg]
        kwargs: dict,  # type: ignore[type-arg]
        einfo: object,
    ) -> None:
        retry_count = self.request.retries if self.request.retries is not None else 0
        logger.error(
            "task_failed_permanently",
            task=self.name,
            task_id=task_id,
            retries=retry_count,
            error=str(exc),
        )
        failed_job = dlq.FailedJob.from_exception(
            exc=exc,
            task_name=self.name,
            task_id=task_id,
            args=list(args),
            kwargs=dict(kwargs),
            retry_count=retry_count,
            queue=self.queue or "optimization",
        )
        dlq.push(failed_job)

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,  # type: ignore[type-arg]
        kwargs: dict,  # type: ignore[type-arg]
        einfo: object,
    ) -> None:
        logger.warning(
            "task_retrying",
            task=self.name,
            task_id=task_id,
            attempt=self.request.retries,
            max_retries=self.max_retries,
            error=str(exc),
        )

    def _retry_countdown(self) -> int:
        """Exponential backoff with cap: 2s, 4s, 8s, 16s, 32s."""
        base = settings.task_retry_backoff_base
        attempt = self.request.retries or 0
        return min(settings.task_retry_backoff_max, base ** (attempt + 1))


# ─────────────────────────────────────────────────────────────────────────────
# Task 1 — Entry point: fan-out coordinator
# ─────────────────────────────────────────────────────────────────────────────


@app.task(
    bind=True,
    base=AtlasBaseTask,
    name="worker.tasks.optimize.optimize_resources",
    queue="optimization",
    max_retries=settings.task_max_retries,
    acks_late=True,
    task_reject_on_worker_lost=True,
)
def optimize_resources(
    self: Task,  # type: ignore[type-arg]
    run_id: str,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fan-out coordinator: fetches all in-scope resources and dispatches batches.

    Args:
        run_id: UUID of the optimization_runs record (must already exist in DB).
        scope:  Optional dict with keys: account_id, region, resource_type,
                resource_ids. All resources are included when scope is None.

    Returns:
        Dict with job counts (batches dispatched, total resources).
    """
    log = logger.bind(task_id=self.request.id, run_id=run_id)  # type: ignore[attr-defined]
    log.info("optimize_resources_start", scope=scope)
    started = time.perf_counter()

    # ── 1. Mark run as running ─────────────────────────────────────────────────
    with worker_span("optimization.task.optimize_resources", run_id=run_id):
        try:
            _mark_run_status(run_id, "running", started_at=datetime.now(tz=timezone.utc))
        except Exception as exc:
            raise self.retry(exc=exc, countdown=self._retry_countdown())

    # ── 2. Fetch resource IDs matching scope ───────────────────────────────────
    try:
        resource_ids = _fetch_resource_ids(scope)
    except psycopg2.Error as exc:
        raise self.retry(exc=TransientError(str(exc)), countdown=self._retry_countdown())

    if not resource_ids:
        log.info("optimize_resources_no_resources_in_scope")
        _mark_run_status(run_id, "completed", completed_at=datetime.now(tz=timezone.utc),
                         resources_analyzed=0)
        return {"run_id": run_id, "batches": 0, "resources": 0}

    # ── 3. Split into batches ──────────────────────────────────────────────────
    batch_size = settings.optimization_batch_size
    batches = [
        resource_ids[i : i + batch_size]
        for i in range(0, len(resource_ids), batch_size)
    ]
    log.info("optimize_resources_batched", total=len(resource_ids), batches=len(batches))

    # ── 4. Dispatch group → chord callback ────────────────────────────────────
    # The chord runs all batches in parallel; when all complete, the callback
    # aggregates results and finalises the run record.
    batch_tasks = group(
        optimize_resource_batch.s(
            run_id=run_id,
            resource_ids=batch,
            batch_index=idx,
        )
        for idx, batch in enumerate(batches)
    )
    callback = finalize_optimization_run.s(run_id=run_id, total_resources=len(resource_ids))
    chord(batch_tasks)(callback)
    update_queue_depth("optimization", len(batches))
    observe_optimization("batch_fanout", time.perf_counter() - started, scope="fanout")

    return {
        "run_id": run_id,
        "batches": len(batches),
        "resources": len(resource_ids),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — Batch processor (100 resources)
# ─────────────────────────────────────────────────────────────────────────────


@app.task(
    bind=True,
    base=AtlasBaseTask,
    name="worker.tasks.optimize.optimize_resource_batch",
    queue="optimization",
    max_retries=settings.task_max_retries,
    acks_late=True,
    task_reject_on_worker_lost=True,
    # Celery built-in rate limit (per-worker guard, not distributed)
    rate_limit="30/m",
)
def optimize_resource_batch(
    self: Task,  # type: ignore[type-arg]
    run_id: str,
    resource_ids: list[str],
    batch_index: int = 0,
) -> dict[str, Any]:
    """Process one batch of up to 100 resources.

    Partial failures are tolerated: a failed resource is logged and skipped so
    the rest of the batch can proceed. The batch itself retries (with exponential
    backoff) only on transient infrastructure errors.

    Returns a BatchResult-compatible dict for chord aggregation.
    """
    log = logger.bind(  # type: ignore[attr-defined]
        task_id=self.request.id,
        run_id=run_id,
        batch=batch_index,
        size=len(resource_ids),
    )
    log.info("batch_start")
    t0 = time.monotonic()
    update_queue_depth("optimization", len(resource_ids))

    # ── Distributed rate limiter (cross-worker, Redis-backed) ──────────────────
    limiter = RateLimiter("optimization_batch", max_calls=settings.rate_limit_calls,
                          window_seconds=settings.rate_limit_window_seconds)
    if not limiter.wait_and_acquire(timeout=30.0):
        # Rate limit not acquired — retry after a short delay rather than failing
        log.warning("batch_rate_limited_retrying")
        raise self.retry(exc=TransientError("rate limit"), countdown=5)

    succeeded = 0
    skipped = 0
    failed_ids: list[str] = []

    for resource_id in resource_ids:
        # ── Idempotency: claim or skip ─────────────────────────────────────────
        if idempotency.is_already_processed(resource_id, run_id):
            log.debug("resource_already_processed", resource_id=resource_id)
            skipped += 1
            idempotency.log_execution(run_id, resource_id, ProcessingStatus.SKIPPED)
            continue

        claimed = idempotency.claim(resource_id, run_id)
        if not claimed:
            # Another worker beat us to it (race condition in the group)
            skipped += 1
            continue

        # ── Process single resource (partial failure boundary) ────────────────
        try:
            result = _process_resource(run_id=run_id, resource_id=resource_id)
            idempotency.mark_done(resource_id, run_id, ProcessingStatus.SUCCESS, result)
            idempotency.log_execution(run_id, resource_id, ProcessingStatus.SUCCESS,
                                      detail=result)
            succeeded += 1

        except PermanentError as exc:
            # Non-retryable: data issue, resource gone, etc.
            log.warning("resource_permanent_error", resource_id=resource_id, error=str(exc))
            idempotency.mark_done(resource_id, run_id, ProcessingStatus.FAILED,
                                  {"error": str(exc)})
            idempotency.log_execution(run_id, resource_id, ProcessingStatus.FAILED,
                                      error=str(exc))
            failed_ids.append(resource_id)

        except TransientError as exc:
            # Transient: release the idempotency claim so a retry can re-process
            _release_claim(resource_id, run_id)
            log.warning("resource_transient_error", resource_id=resource_id, error=str(exc))
            failed_ids.append(resource_id)
            # Don't abort the batch — continue to next resource

        except Exception as exc:  # noqa: BLE001
            # Unexpected: treat as permanent to prevent infinite retries per resource
            log.error("resource_unexpected_error", resource_id=resource_id, error=str(exc),
                      exc_info=True)
            idempotency.mark_done(resource_id, run_id, ProcessingStatus.FAILED,
                                  {"error": str(exc)})
            idempotency.log_execution(run_id, resource_id, ProcessingStatus.FAILED,
                                      error=str(exc))
            failed_ids.append(resource_id)

    duration = round(time.monotonic() - t0, 3)
    result = asdict(BatchResult(
        run_id=run_id,
        batch_index=batch_index,
        total=len(resource_ids),
        succeeded=succeeded,
        skipped=skipped,
        failed=len(failed_ids),
        failed_resource_ids=failed_ids,
        duration_seconds=duration,
    ))
    observe_optimization("batch", duration, scope="batch")
    update_queue_depth("optimization", 0)
    log.info("batch_complete", **{k: v for k, v in result.items()
                                   if k != "failed_resource_ids"})
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Task 3 — Chord callback: aggregate + finalise
# ─────────────────────────────────────────────────────────────────────────────


@app.task(
    bind=True,
    base=AtlasBaseTask,
    name="worker.tasks.optimize.finalize_optimization_run",
    queue="optimization",
    max_retries=3,
    acks_late=True,
)
def finalize_optimization_run(
    self: Task,  # type: ignore[type-arg]
    batch_results: list[dict[str, Any]],
    run_id: str,
    total_resources: int,
) -> dict[str, Any]:
    """Chord callback: aggregate batch results and update the DB run record."""
    log = logger.bind(task_id=self.request.id, run_id=run_id)  # type: ignore[attr-defined]
    log.info("finalize_start", batch_count=len(batch_results))

    totals: dict[str, Any] = {
        "succeeded": 0,
        "skipped": 0,
        "failed": 0,
        "failed_resource_ids": [],
    }
    for br in batch_results:
        if not isinstance(br, dict):
            continue
        totals["succeeded"] += br.get("succeeded", 0)
        totals["skipped"] += br.get("skipped", 0)
        totals["failed"] += br.get("failed", 0)
        totals["failed_resource_ids"].extend(br.get("failed_resource_ids", []))

    # Count distinct recommendations generated in this run
    try:
        rec_count = _count_recommendations_for_run(run_id)
    except Exception:
        rec_count = 0

    try:
        _mark_run_status(
            run_id,
            "completed",
            completed_at=datetime.now(tz=timezone.utc),
            resources_analyzed=totals["succeeded"] + totals["skipped"],
            recommendations_generated=rec_count,
        )
    except Exception as exc:
        raise self.retry(exc=TransientError(str(exc)), countdown=10)

    summary = {
        "run_id": run_id,
        "total_resources": total_resources,
        **totals,
        "recommendations_generated": rec_count,
    }
    log.info("finalize_complete", **{k: v for k, v in summary.items()
                                      if k != "failed_resource_ids"})
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Processing logic (pure functions — no Celery dependency)
# ─────────────────────────────────────────────────────────────────────────────


def _process_resource(run_id: str, resource_id: str) -> dict[str, Any]:
    """Fetch metrics, analyse, and persist a recommendation if warranted.

    Returns a dict summarising what was done (for the idempotency store).
    Raises PermanentError or TransientError — never swallows exceptions.
    """
    # ── 1. Fetch resource metadata ─────────────────────────────────────────────
    try:
        resource = _fetch_resource(resource_id)
    except psycopg2.OperationalError as exc:
        raise TransientError(f"DB connection error: {exc}") from exc
    except psycopg2.Error as exc:
        raise PermanentError(f"DB query error: {exc}") from exc

    if resource is None:
        raise PermanentError(f"Resource {resource_id} not found or deleted")

    # ── 2. Fetch usage metrics ─────────────────────────────────────────────────
    try:
        metrics = _fetch_usage_metrics(resource_id, days=settings.optimization_lookback_days)
    except psycopg2.OperationalError as exc:
        raise TransientError(f"DB connection error fetching metrics: {exc}") from exc

    # ── 3. Analyse utilisation ─────────────────────────────────────────────────
    analysis = _detect_underutilization(resource_id, metrics)

    if analysis.recommendation_type is None:
        # Resource is healthy — nothing to do
        return {
            "action": "no_recommendation",
            "cpu_avg": analysis.cpu_avg,
            "samples": analysis.samples,
        }

    # ── 4. Generate and persist recommendation ─────────────────────────────────
    try:
        rec_id = _upsert_recommendation(resource, analysis, run_id)
    except psycopg2.OperationalError as exc:
        raise TransientError(f"DB write error: {exc}") from exc

    return {
        "action": "recommendation_created",
        "recommendation_id": rec_id,
        "type": analysis.recommendation_type,
        "confidence": analysis.confidence,
        "cpu_avg": analysis.cpu_avg,
    }


def _fetch_resource(resource_id: str) -> dict[str, Any] | None:
    """Return the resource row or None if deleted/missing."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, type, provider, account_id, region,
                   instance_type, monthly_cost_usd, status, tags
              FROM resources
             WHERE id = %s
               AND deleted_at IS NULL
               AND status != 'terminated'
            """,
            (resource_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _fetch_usage_metrics(
    resource_id: str,
    days: int = 14,
) -> list[MetricSummary]:
    """Return per-metric statistics over the lookback window.

    The WHERE clause on `ts` enables partition pruning on usage_metrics.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                metric,
                AVG(value)                                            AS avg,
                MAX(value)                                            AS max,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value)   AS p95,
                COUNT(*)                                              AS samples
              FROM usage_metrics
             WHERE resource_id = %s
               AND ts           >= NOW() - (%s || ' days')::INTERVAL  -- partition prune
               AND ts           <  NOW()
               AND granularity  IN ('1h', '6h')
             GROUP BY metric
            """,
            (resource_id, str(days)),
        )
        return [
            MetricSummary(
                metric=row["metric"],
                avg=float(row["avg"] or 0),
                max=float(row["max"] or 0),
                p95=float(row["p95"] or 0),
                samples=int(row["samples"]),
            )
            for row in cur.fetchall()
        ]


def _detect_underutilization(
    resource_id: str,
    metrics: list[MetricSummary],
) -> UtilizationAnalysis:
    """Classify the resource based on metric thresholds.

    Returns a UtilizationAnalysis with:
        recommendation_type = None            → resource is healthy
        recommendation_type = 'resize_down'   → underutilised but active
        recommendation_type = 'terminate'     → idle (near-zero CPU + net)
        recommendation_type = 'schedule'      → bursty / predictable off-hours
    """
    by_metric = {m.metric: m for m in metrics}

    cpu = by_metric.get("cpu_utilization")
    mem = by_metric.get("memory_utilization")
    net_in = by_metric.get("network_in_bytes")

    cpu_avg = cpu.avg if cpu else None
    cpu_p95 = cpu.p95 if cpu else None
    mem_avg = mem.avg if mem else None
    net_in_avg = net_in.avg if net_in else None
    samples = cpu.samples if cpu else 0

    rec_type: str | None = None
    confidence: float = 0.0

    not_enough_data = samples < settings.min_sample_count

    if not not_enough_data and cpu_avg is not None:
        if cpu_avg < settings.cpu_idle_threshold:
            rec_type = "terminate"
            confidence = min(0.99, 0.70 + (settings.cpu_idle_threshold - cpu_avg) * 0.05)
        elif cpu_avg < settings.cpu_underutil_threshold:
            if mem_avg is None or mem_avg < settings.mem_underutil_threshold:
                rec_type = "resize_down"
                # Confidence proportional to how far below threshold
                gap = settings.cpu_underutil_threshold - cpu_avg
                confidence = min(0.95, 0.65 + gap * 0.015)
                # Downgrade to schedule if p95 is high (bursty workload)
                if cpu_p95 is not None and cpu_p95 > 70:
                    rec_type = "schedule"
                    confidence = min(confidence, 0.80)

    return UtilizationAnalysis(
        resource_id=resource_id,
        cpu_avg=cpu_avg,
        cpu_p95=cpu_p95,
        mem_avg=mem_avg,
        net_in_avg=net_in_avg,
        samples=samples,
        is_underutilized=rec_type in ("resize_down", "schedule"),
        is_idle=rec_type == "terminate",
        recommendation_type=rec_type,
        confidence=round(confidence, 4),
        observation_days=settings.optimization_lookback_days,
    )


def _upsert_recommendation(
    resource: dict[str, Any],
    analysis: UtilizationAnalysis,
    run_id: str,
) -> str:
    """Persist or refresh a recommendation row. Returns the recommendation ID."""
    rec_id = str(uuid.uuid4())
    monthly_cost = float(resource.get("monthly_cost_usd") or 0)

    # Savings estimate: resize_down ≈ 50% savings; terminate ≈ 100%; schedule ≈ 40%
    savings_pct = {"resize_down": 0.50, "terminate": 1.0, "schedule": 0.40}.get(
        analysis.recommendation_type or "", 0
    )
    savings = round(monthly_cost * savings_pct, 4)

    title_map = {
        "resize_down": f"Downsize {resource.get('instance_type', 'instance')} — avg CPU {analysis.cpu_avg:.1f}%",
        "terminate":   f"Terminate idle resource — avg CPU {analysis.cpu_avg:.2f}%",
        "schedule":    "Schedule resource to stop outside business hours",
    }
    title = title_map.get(analysis.recommendation_type or "", "Optimization opportunity")

    details: dict[str, Any] = {
        "avg_cpu_utilization_percent": analysis.cpu_avg,
        "cpu_p95_percent": analysis.cpu_p95,
        "avg_memory_utilization_percent": analysis.mem_avg,
        "observation_period_days": analysis.observation_days,
        "sample_count": analysis.samples,
    }
    if analysis.recommendation_type == "resize_down":
        details["current_instance_type"] = resource.get("instance_type")
        details["current_monthly_cost_usd"] = monthly_cost
        details["projected_monthly_cost_usd"] = round(monthly_cost * 0.50, 4)
    if analysis.recommendation_type == "schedule":
        details["schedule_suggestion"] = {
            "start_cron": "0 8 * * MON-FRI",
            "stop_cron": "0 20 * * MON-FRI",
            "timezone": "UTC",
        }

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO recommendations (
                id, resource_id, optimization_run_id,
                type, status, title, description,
                savings_usd_monthly, confidence, details,
                expires_at, created_at, updated_at
            )
            VALUES (
                %(id)s, %(resource_id)s, %(run_id)s,
                %(type)s, 'pending',
                %(title)s,
                %(description)s,
                %(savings)s, %(confidence)s, %(details)s::jsonb,
                NOW() + INTERVAL '30 days', NOW(), NOW()
            )
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            {
                "id":          rec_id,
                "resource_id": analysis.resource_id,
                "run_id":      run_id,
                "type":        analysis.recommendation_type,
                "title":       title,
                "description": (
                    f"Resource {resource.get('name', resource['id'])} has averaged "
                    f"{analysis.cpu_avg:.1f}% CPU over the last "
                    f"{analysis.observation_days} days ({analysis.samples} samples)."
                ),
                "savings":     savings,
                "confidence":  analysis.confidence,
                "details":     json.dumps(details),
            },
        )
        row = cur.fetchone()
        # ON CONFLICT DO NOTHING returns nothing if row already existed
        return rec_id if row is None else row["id"]


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_resource_ids(scope: dict[str, Any] | None) -> list[str]:
    """Return IDs of all active resources matching the given scope."""
    conditions = ["deleted_at IS NULL", "status NOT IN ('terminated', 'unknown')"]
    params: dict[str, Any] = {}

    if scope:
        if scope.get("account_id"):
            conditions.append("account_id = %(account_id)s")
            params["account_id"] = scope["account_id"]
        if scope.get("region"):
            conditions.append("region = %(region)s")
            params["region"] = scope["region"]
        if scope.get("resource_type"):
            conditions.append("type = %(resource_type)s")
            params["resource_type"] = scope["resource_type"]
        if scope.get("resource_ids"):
            conditions.append("id = ANY(%(resource_ids)s)")
            params["resource_ids"] = scope["resource_ids"]

    where = " AND ".join(conditions)
    with get_cursor() as cur:
        cur.execute(f"SELECT id FROM resources WHERE {where} ORDER BY id", params)
        return [row["id"] for row in cur.fetchall()]


def _mark_run_status(
    run_id: str,
    status: str,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    resources_analyzed: int | None = None,
    recommendations_generated: int | None = None,
) -> None:
    sets = ["status = %(status)s", "updated_at = NOW()"]
    params: dict[str, Any] = {"run_id": run_id, "status": status}
    if started_at:
        sets.append("started_at = %(started_at)s")
        params["started_at"] = started_at
    if completed_at:
        sets.append("completed_at = %(completed_at)s")
        params["completed_at"] = completed_at
    if resources_analyzed is not None:
        sets.append("resources_analyzed = %(resources_analyzed)s")
        params["resources_analyzed"] = resources_analyzed
    if recommendations_generated is not None:
        sets.append("recommendations_generated = %(recommendations_generated)s")
        params["recommendations_generated"] = recommendations_generated

    with get_cursor() as cur:
        cur.execute(
            f"UPDATE optimization_runs SET {', '.join(sets)} WHERE id = %(run_id)s",
            params,
        )


def _count_recommendations_for_run(run_id: str) -> int:
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM recommendations WHERE optimization_run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        return int(row["count"]) if row else 0


def _release_claim(resource_id: str, run_id: str) -> None:
    """Delete the idempotency IN_PROGRESS key so retries can re-claim it."""
    from worker.redis_client import get_redis
    key = idempotency.make_key(resource_id, run_id)
    try:
        get_redis().delete(key)
    except Exception:
        pass  # best-effort; if Redis is down the key will expire via TTL

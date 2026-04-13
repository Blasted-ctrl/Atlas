"""Tests for the optimize_resources pipeline.

Covered:
  - Idempotency guard (claim / is_already_processed / mark_done)
  - RateLimiter (acquire / exhaustion / sliding window)
  - _detect_underutilization thresholds
  - optimize_resource_batch partial failure handling
  - DLQ push / pop / mark_resolved
  - on_failure DLQ hook on AtlasBaseTask
  - finalize_optimization_run aggregation

Uses pytest with unittest.mock — no live Redis or Postgres required.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def fake_redis():
    """In-memory dict that mimics the Redis methods we use."""

    class FakeRedis:
        def __init__(self):
            self._store: dict[str, Any] = {}
            self._lists: dict[str, list] = {}
            self._zsets: dict[str, dict] = {}
            self._ttls: dict[str, int] = {}

        # String ops
        def get(self, key):
            return self._store.get(key)

        def set(self, key, value, ex=None, nx=False):
            if nx and key in self._store:
                return None
            self._store[key] = value
            if ex:
                self._ttls[key] = ex
            return True

        def delete(self, *keys):
            for k in keys:
                self._store.pop(k, None)

        # List ops
        def lpush(self, key, *values):
            self._lists.setdefault(key, [])
            for v in values:
                self._lists[key].insert(0, v)
            return len(self._lists[key])

        def rpop(self, key):
            lst = self._lists.get(key, [])
            return lst.pop() if lst else None

        def lrange(self, key, start, end):
            lst = self._lists.get(key, [])
            end = None if end == -1 else end + 1
            return lst[start:end]

        def llen(self, key):
            return len(self._lists.get(key, []))

        def ltrim(self, key, start, end):
            lst = self._lists.get(key, [])
            self._lists[key] = lst[start : end + 1]

        def expire(self, key, ttl):
            self._ttls[key] = ttl

        # Sorted-set ops (for rate limiter)
        def zremrangebyscore(self, key, min_score, max_score):
            zset = self._zsets.get(key, {})
            # "-inf" means no lower bound; apply only the upper-bound filter.
            max_s = float("inf") if max_score == "+inf" else float(max_score)
            min_s = float("-inf") if min_score == "-inf" else float(min_score)
            to_del = [m for m, s in zset.items() if min_s <= s <= max_s]
            for m in to_del:
                del zset[m]
            self._zsets[key] = zset

        def zcard(self, key):
            return len(self._zsets.get(key, {}))

        def zadd(self, key, mapping):
            self._zsets.setdefault(key, {}).update(mapping)

        def zrem(self, key, *members):
            zset = self._zsets.get(key, {})
            for m in members:
                zset.pop(m, None)

        def ping(self):
            return True

        def pipeline(self):
            return FakePipeline(self)

    class FakePipeline:
        def __init__(self, redis):
            self._r = redis
            self._cmds: list = []

        def zremrangebyscore(self, *a, **kw):
            self._cmds.append(("zremrangebyscore", a, kw))
            return self

        def zcard(self, *a, **kw):
            self._cmds.append(("zcard", a, kw))
            return self

        def zadd(self, *a, **kw):
            self._cmds.append(("zadd", a, kw))
            return self

        def expire(self, *a, **kw):
            self._cmds.append(("expire", a, kw))
            return self

        def lpush(self, *a, **kw):
            self._cmds.append(("lpush", a, kw))
            return self

        def ltrim(self, *a, **kw):
            self._cmds.append(("ltrim", a, kw))
            return self

        def execute(self):
            results = []
            for cmd, args, kwargs in self._cmds:
                fn = getattr(self._r, cmd)
                results.append(fn(*args, **kwargs))
            self._cmds.clear()
            return results

    return FakeRedis()


@pytest.fixture()
def resource_id():
    return str(uuid.uuid4())


@pytest.fixture()
def run_id():
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency tests
# ─────────────────────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_make_key_is_deterministic(self, resource_id, run_id):
        from worker.idempotency import make_key

        k1 = make_key(resource_id, run_id)
        k2 = make_key(resource_id, run_id)
        assert k1 == k2

    def test_make_key_different_inputs_give_different_keys(self, run_id):
        from worker.idempotency import make_key

        id_a = str(uuid.uuid4())
        id_b = str(uuid.uuid4())
        assert make_key(id_a, run_id) != make_key(id_b, run_id)

    def test_make_key_has_expected_prefix(self, resource_id, run_id):
        from worker.idempotency import make_key

        key = make_key(resource_id, run_id)
        assert key.startswith("atlas:idempotency:")

    def test_claim_first_call_succeeds(self, fake_redis, resource_id, run_id):
        from worker import idempotency

        with patch("worker.idempotency.get_redis", return_value=fake_redis):
            assert idempotency.claim(resource_id, run_id) is True

    def test_claim_second_call_fails(self, fake_redis, resource_id, run_id):
        from worker import idempotency

        with patch("worker.idempotency.get_redis", return_value=fake_redis):
            assert idempotency.claim(resource_id, run_id) is True
            assert idempotency.claim(resource_id, run_id) is False  # NX guard

    def test_is_already_processed_false_when_missing(self, fake_redis, resource_id, run_id):
        from worker import idempotency

        with patch("worker.idempotency.get_redis", return_value=fake_redis):
            assert idempotency.is_already_processed(resource_id, run_id) is False

    def test_is_already_processed_true_after_mark_done(self, fake_redis, resource_id, run_id):
        from worker import idempotency
        from worker.idempotency import ProcessingStatus

        with patch("worker.idempotency.get_redis", return_value=fake_redis):
            idempotency.mark_done(resource_id, run_id, ProcessingStatus.SUCCESS, {})
            assert idempotency.is_already_processed(resource_id, run_id) is True

    def test_log_execution_appends_entry(self, fake_redis, resource_id, run_id):
        from worker import idempotency
        from worker.idempotency import ProcessingStatus

        with patch("worker.idempotency.get_redis", return_value=fake_redis):
            idempotency.log_execution(run_id, resource_id, ProcessingStatus.SUCCESS,
                                      detail={"foo": "bar"})
            logs = idempotency.get_execution_log(run_id)

        assert len(logs) == 1
        assert logs[0]["resource_id"] == resource_id
        assert logs[0]["status"] == ProcessingStatus.SUCCESS


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiter tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRateLimiter:
    def test_acquire_within_limit_succeeds(self, fake_redis):
        from worker.rate_limiter import RateLimiter

        with patch("worker.rate_limiter.get_redis", return_value=fake_redis):
            limiter = RateLimiter("test", max_calls=5, window_seconds=60)
            results = [limiter.acquire() for _ in range(5)]

        assert all(results)

    def test_acquire_beyond_limit_fails(self, fake_redis):
        from worker.rate_limiter import RateLimiter

        with patch("worker.rate_limiter.get_redis", return_value=fake_redis):
            limiter = RateLimiter("test", max_calls=3, window_seconds=60)
            results = [limiter.acquire() for _ in range(5)]

        assert results[:3] == [True, True, True]
        assert results[3] is False
        assert results[4] is False

    def test_reset_clears_the_window(self, fake_redis):
        from worker.rate_limiter import RateLimiter

        with patch("worker.rate_limiter.get_redis", return_value=fake_redis):
            limiter = RateLimiter("test", max_calls=2, window_seconds=60)
            limiter.acquire()
            limiter.acquire()
            assert limiter.acquire() is False
            limiter.reset()
            assert limiter.acquire() is True

    def test_remaining_counts_available_slots(self, fake_redis):
        from worker.rate_limiter import RateLimiter

        with patch("worker.rate_limiter.get_redis", return_value=fake_redis):
            limiter = RateLimiter("test", max_calls=10, window_seconds=60)
            limiter.acquire()
            limiter.acquire()
            remaining = limiter.remaining()

        assert remaining == 8


# ─────────────────────────────────────────────────────────────────────────────
# Underutilization detection
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectUnderutilization:
    def _run(self, metrics_data: dict[str, tuple[float, float, float, int]]):
        """Helper: metrics_data = {metric: (avg, max, p95, samples)}."""
        from worker.tasks.optimize import MetricSummary
        from worker.tasks.optimize import _detect_underutilization

        metrics = [
            MetricSummary(metric=m, avg=v[0], max=v[1], p95=v[2], samples=v[3])
            for m, v in metrics_data.items()
        ]
        return _detect_underutilization(str(uuid.uuid4()), metrics)

    def test_healthy_resource_no_recommendation(self):
        analysis = self._run({
            "cpu_utilization": (65.0, 95.0, 90.0, 200),
            "memory_utilization": (55.0, 80.0, 75.0, 200),
        })
        assert analysis.recommendation_type is None
        assert not analysis.is_underutilized
        assert not analysis.is_idle

    def test_underutilized_resource_resize_down(self):
        analysis = self._run({
            "cpu_utilization": (8.0, 15.0, 12.0, 200),
            "memory_utilization": (20.0, 35.0, 30.0, 200),
        })
        assert analysis.recommendation_type == "resize_down"
        assert analysis.is_underutilized
        assert analysis.confidence > 0.65

    def test_idle_resource_terminate(self):
        analysis = self._run({
            "cpu_utilization": (0.5, 1.2, 0.8, 200),
            "memory_utilization": (5.0, 8.0, 6.0, 200),
        })
        assert analysis.recommendation_type == "terminate"
        assert analysis.is_idle
        assert analysis.confidence > 0.70

    def test_bursty_resource_schedule(self):
        # Low avg but very high p95 → schedule, not resize
        analysis = self._run({
            "cpu_utilization": (12.0, 95.0, 88.0, 200),  # spikes at p95
            "memory_utilization": (15.0, 40.0, 35.0, 200),
        })
        assert analysis.recommendation_type == "schedule"

    def test_insufficient_samples_no_recommendation(self):
        # Only 10 samples — below min_sample_count (48)
        analysis = self._run({
            "cpu_utilization": (5.0, 8.0, 7.0, 10),
        })
        assert analysis.recommendation_type is None

    def test_no_metrics_no_recommendation(self):
        analysis = self._run({})
        assert analysis.recommendation_type is None
        assert analysis.cpu_avg is None

    def test_confidence_increases_with_lower_cpu(self):
        low_cpu = self._run({"cpu_utilization": (3.0, 5.0, 4.0, 200),
                              "memory_utilization": (10.0, 15.0, 12.0, 200)})
        high_cpu = self._run({"cpu_utilization": (18.0, 22.0, 20.0, 200),
                               "memory_utilization": (35.0, 40.0, 38.0, 200)})
        # Lower CPU → higher confidence for resize_down / terminate
        assert low_cpu.confidence >= high_cpu.confidence


# ─────────────────────────────────────────────────────────────────────────────
# DLQ tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDLQ:
    def _make_job(self, queue="optimization"):
        return dlq_module().FailedJob(
            task_name="worker.tasks.optimize.optimize_resource_batch",
            task_id=str(uuid.uuid4()),
            args=["run-1", ["res-1"]],
            kwargs={"batch_index": 0},
            exception_type="RuntimeError",
            exception_message="transient failure",
            traceback="Traceback...",
            retry_count=5,
            queue=queue,
        )

    def dlq_module(self):
        from worker import dlq as _dlq
        return _dlq

    def test_push_and_pop_roundtrip(self, fake_redis):
        from worker import dlq as dlq_m

        job = self._make_job()

        with (
            patch("worker.dlq.get_redis", return_value=fake_redis),
            patch("worker.dlq._ensure_table"),
            patch("worker.dlq.get_cursor") as mock_cursor,
        ):
            mock_cursor.return_value.__enter__ = Mock(return_value=MagicMock())
            mock_cursor.return_value.__exit__ = Mock(return_value=False)
            dlq_m.push(job)
            popped = dlq_m.pop(queue="optimization", count=1)

        assert len(popped) == 1
        assert popped[0].task_id == job.task_id
        assert popped[0].exception_message == "transient failure"

    def test_pop_empty_queue_returns_empty_list(self, fake_redis):
        from worker import dlq as dlq_m

        with patch("worker.dlq.get_redis", return_value=fake_redis):
            result = dlq_m.pop(queue="optimization", count=5)

        assert result == []

    def test_failed_job_from_exception(self):
        from worker import dlq as dlq_m

        exc = ValueError("bad data")
        job = dlq_m.FailedJob.from_exception(
            exc=exc,
            task_name="some.task",
            task_id="tid-1",
            args=["a"],
            kwargs={"k": "v"},
            retry_count=5,
        )
        assert job.exception_type == "ValueError"
        assert job.exception_message == "bad data"
        assert job.retry_count == 5

    def test_failed_job_json_roundtrip(self):
        from worker import dlq as dlq_m

        job = self._make_job()
        restored = dlq_m.FailedJob.from_json(job.to_json())
        assert restored.task_id == job.task_id
        assert restored.args == job.args
        assert restored.dlq_attempts == 0

    def test_depth_returns_list_length(self, fake_redis):
        from worker import dlq as dlq_m

        with (
            patch("worker.dlq.get_redis", return_value=fake_redis),
            patch("worker.dlq._ensure_table"),
            patch("worker.dlq.get_cursor") as mock_cursor,
        ):
            mock_cursor.return_value.__enter__ = Mock(return_value=MagicMock())
            mock_cursor.return_value.__exit__ = Mock(return_value=False)
            for _ in range(3):
                dlq_m.push(self._make_job())
            depth = dlq_m.depth("optimization")

        assert depth == 3


# helper to avoid forward-reference issues in test class body
def dlq_module():
    from worker import dlq
    return dlq


# ─────────────────────────────────────────────────────────────────────────────
# optimize_resource_batch integration-style tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOptimizeResourceBatch:
    """Tests for the batch task with mocked DB and Redis."""

    def _make_metric_rows(self, cpu_avg=8.0, samples=200):
        return [
            {
                "metric": "cpu_utilization",
                "avg": cpu_avg,
                "max": cpu_avg * 1.5,
                "p95": cpu_avg * 1.3,
                "samples": samples,
            },
            {
                "metric": "memory_utilization",
                "avg": 20.0,
                "max": 35.0,
                "p95": 28.0,
                "samples": samples,
            },
        ]

    def _make_resource_row(self, resource_id):
        return {
            "id": resource_id,
            "name": "test-instance",
            "type": "ec2_instance",
            "provider": "aws",
            "account_id": "123456789012",
            "region": "us-east-1",
            "instance_type": "m5.xlarge",
            "monthly_cost_usd": 150.0,
            "status": "running",
            "tags": {},
        }

    @patch("worker.tasks.optimize.idempotency.is_already_processed", return_value=False)
    @patch("worker.tasks.optimize.idempotency.claim", return_value=True)
    @patch("worker.tasks.optimize.idempotency.mark_done")
    @patch("worker.tasks.optimize.idempotency.log_execution")
    @patch("worker.tasks.optimize.RateLimiter")
    @patch("worker.tasks.optimize._fetch_resource")
    @patch("worker.tasks.optimize._fetch_usage_metrics")
    @patch("worker.tasks.optimize._upsert_recommendation", return_value=str(uuid.uuid4()))
    def test_successful_batch(
        self,
        mock_upsert,
        mock_metrics,
        mock_resource,
        mock_limiter_cls,
        mock_log_exec,
        mock_mark_done,
        mock_claim,
        mock_is_processed,
    ):
        from worker.tasks.optimize import MetricSummary
        from worker.tasks.optimize import optimize_resource_batch

        resource_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())

        mock_resource.return_value = self._make_resource_row(resource_id)
        mock_metrics.return_value = [
            MetricSummary("cpu_utilization", avg=8.0, max=12.0, p95=10.0, samples=200),
            MetricSummary("memory_utilization", avg=20.0, max=30.0, p95=25.0, samples=200),
        ]
        mock_limiter = MagicMock()
        mock_limiter.wait_and_acquire.return_value = True
        mock_limiter_cls.return_value = mock_limiter

        result = optimize_resource_batch(
            run_id=run_id,
            resource_ids=[resource_id],
            batch_index=0,
        )

        assert result["succeeded"] == 1
        assert result["skipped"] == 0
        assert result["failed"] == 0
        mock_upsert.assert_called_once()

    @patch("worker.tasks.optimize.idempotency.is_already_processed", return_value=True)
    @patch("worker.tasks.optimize.idempotency.log_execution")
    @patch("worker.tasks.optimize.RateLimiter")
    def test_already_processed_resource_is_skipped(
        self, mock_limiter_cls, mock_log_exec, mock_is_processed
    ):
        from worker.tasks.optimize import optimize_resource_batch

        mock_limiter = MagicMock()
        mock_limiter.wait_and_acquire.return_value = True
        mock_limiter_cls.return_value = mock_limiter

        resource_id = str(uuid.uuid4())
        result = optimize_resource_batch(
            run_id=str(uuid.uuid4()),
            resource_ids=[resource_id],
            batch_index=0,
        )

        assert result["skipped"] == 1
        assert result["succeeded"] == 0

    @patch("worker.tasks.optimize.idempotency.is_already_processed", return_value=False)
    @patch("worker.tasks.optimize.idempotency.claim", return_value=True)
    @patch("worker.tasks.optimize.idempotency.mark_done")
    @patch("worker.tasks.optimize.idempotency.log_execution")
    @patch("worker.tasks.optimize.RateLimiter")
    @patch("worker.tasks.optimize._fetch_resource")
    def test_permanent_error_continues_batch(
        self,
        mock_resource,
        mock_limiter_cls,
        mock_log_exec,
        mock_mark_done,
        mock_claim,
        mock_is_processed,
    ):
        """A PermanentError on one resource should not abort the batch."""
        from worker.tasks.optimize import PermanentError
        from worker.tasks.optimize import optimize_resource_batch

        mock_resource.side_effect = PermanentError("resource gone")
        mock_limiter = MagicMock()
        mock_limiter.wait_and_acquire.return_value = True
        mock_limiter_cls.return_value = mock_limiter

        ids = [str(uuid.uuid4()) for _ in range(3)]
        result = optimize_resource_batch(
            run_id=str(uuid.uuid4()),
            resource_ids=ids,
            batch_index=0,
        )

        # All 3 failed but the batch completed
        assert result["failed"] == 3
        assert result["succeeded"] == 0
        assert len(result["failed_resource_ids"]) == 3

    @patch("worker.tasks.optimize.idempotency.is_already_processed", return_value=False)
    @patch("worker.tasks.optimize.idempotency.claim", return_value=True)
    @patch("worker.tasks.optimize.idempotency.mark_done")
    @patch("worker.tasks.optimize.idempotency.log_execution")
    @patch("worker.tasks.optimize.RateLimiter")
    @patch("worker.tasks.optimize._fetch_resource")
    @patch("worker.tasks.optimize._fetch_usage_metrics")
    @patch("worker.tasks.optimize._upsert_recommendation")
    def test_mixed_success_and_failure(
        self,
        mock_upsert,
        mock_metrics,
        mock_resource,
        mock_limiter_cls,
        mock_log_exec,
        mock_mark_done,
        mock_claim,
        mock_is_processed,
    ):
        """2 succeed, 1 fails permanently → batch still returns partial results."""
        from worker.tasks.optimize import MetricSummary
        from worker.tasks.optimize import PermanentError
        from worker.tasks.optimize import optimize_resource_batch

        ids = [str(uuid.uuid4()) for _ in range(3)]
        good_resource = self._make_resource_row(ids[0])

        # Resource 2 raises a PermanentError
        def resource_side_effect(rid):
            if rid == ids[1]:
                raise PermanentError("not found")
            return good_resource

        mock_resource.side_effect = resource_side_effect
        mock_metrics.return_value = [
            MetricSummary("cpu_utilization", avg=8.0, max=12.0, p95=10.0, samples=200),
        ]
        mock_upsert.return_value = str(uuid.uuid4())
        mock_limiter = MagicMock()
        mock_limiter.wait_and_acquire.return_value = True
        mock_limiter_cls.return_value = mock_limiter

        result = optimize_resource_batch(
            run_id=str(uuid.uuid4()),
            resource_ids=ids,
            batch_index=0,
        )

        assert result["succeeded"] == 2
        assert result["failed"] == 1
        assert ids[1] in result["failed_resource_ids"]


# ─────────────────────────────────────────────────────────────────────────────
# finalize_optimization_run aggregation
# ─────────────────────────────────────────────────────────────────────────────


class TestFinalizeOptimizationRun:
    @patch("worker.tasks.optimize._count_recommendations_for_run", return_value=7)
    @patch("worker.tasks.optimize._mark_run_status")
    def test_aggregates_batch_results(self, mock_mark, mock_count):
        from worker.tasks.optimize import finalize_optimization_run

        run_id = str(uuid.uuid4())
        batch_results = [
            {"succeeded": 80, "skipped": 10, "failed": 10, "failed_resource_ids": ["a", "b"]},
            {"succeeded": 90, "skipped": 5, "failed": 5, "failed_resource_ids": ["c"]},
        ]

        result = finalize_optimization_run(
            batch_results=batch_results,
            run_id=run_id,
            total_resources=200,
        )

        assert result["succeeded"] == 170
        assert result["skipped"] == 15
        assert result["failed"] == 15
        assert result["recommendations_generated"] == 7
        mock_mark.assert_called_once()

    @patch("worker.tasks.optimize._count_recommendations_for_run", return_value=0)
    @patch("worker.tasks.optimize._mark_run_status")
    def test_handles_empty_batch_results(self, mock_mark, mock_count):
        from worker.tasks.optimize import finalize_optimization_run

        result = finalize_optimization_run(
            batch_results=[],
            run_id=str(uuid.uuid4()),
            total_resources=0,
        )
        assert result["succeeded"] == 0
        assert result["failed"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# AtlasBaseTask DLQ hook
# ─────────────────────────────────────────────────────────────────────────────


class TestAtlasBaseTaskDLQ:
    @patch("worker.tasks.optimize.dlq.push")
    def test_on_failure_pushes_to_dlq(self, mock_push):
        from celery.utils.threads import LocalStack

        from worker.tasks.optimize import AtlasBaseTask

        task = AtlasBaseTask()
        task.name = "worker.tasks.optimize.optimize_resource_batch"
        task.request_stack = LocalStack()
        task.push_request(id="task-id-1", retries=5)
        task.queue = "optimization"

        exc = RuntimeError("connection refused")
        task.on_failure(exc, "task-id-1", ("run-1", ["res-1"]), {}, None)

        mock_push.assert_called_once()
        pushed_job = mock_push.call_args[0][0]
        assert pushed_job.task_name == task.name
        assert pushed_job.exception_type == "RuntimeError"
        assert pushed_job.retry_count == 5

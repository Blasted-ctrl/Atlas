"""Integration-test fixtures.

These fixtures wire together multiple real components (preprocessor, model,
evaluator, optimizer) while replacing only the I/O boundaries (Postgres, Redis)
with deterministic in-process stubs.

DB stub
-------
An in-memory dict keyed by ``(resource_id, metric)`` stores upserted forecasts.
``fetch_usage_rows`` is monkeypatched per-test to return controlled time-series.

Redis stub
----------
``fakeredis.FakeRedis`` provides a real in-process Redis implementation with
TTL support, ``KEYS`` glob matching, and all commands used by the cache module.

Bridge
------
``forecast_result_to_usage()`` converts a ``PipelineResult`` (daily predictions
in original metric units) into ``ForecastedUsage`` (p50/p95 fractions) so the
forecasting output can be fed directly into the optimization engine.
"""

from __future__ import annotations

import math
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from uuid import uuid4

import numpy as np
import pytest

from worker.forecasting.pipeline import ForecastPipeline
from worker.forecasting.pipeline import PipelineResult
from worker.optimization.benchmark import build_instance_catalogue
from worker.optimization.engine import CostOptimizationEngine
from worker.optimization.types import ForecastedUsage

# ── In-process DB store ───────────────────────────────────────────────────────

class InMemoryForecastStore:
    """Thread-safe (GIL is sufficient for tests) in-memory forecast store."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_id: dict[tuple[str, str], str] = {}

    def save(self, *, resource_id: str, metric: str, **kwargs: Any) -> str:
        uid = str(uuid4())
        self._store[(resource_id, metric)] = {"id": uid, "resource_id": resource_id,
                                              "metric": metric, **kwargs}
        self._last_id[(resource_id, metric)] = uid
        return uid

    def get(self, resource_id: str, metric: str) -> dict | None:
        return self._store.get((resource_id, metric))

    def all_ids(self) -> list[str]:
        return list(self._last_id.values())

    def count(self) -> int:
        return len(self._store)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db_store() -> InMemoryForecastStore:
    return InMemoryForecastStore()


@pytest.fixture()
def fake_redis():
    """Real in-process Redis — no network required."""
    try:
        import fakeredis
        return fakeredis.FakeRedis(decode_responses=True)
    except ImportError:
        pytest.skip("fakeredis not installed")


@pytest.fixture()
def mock_redis(fake_redis, monkeypatch):
    """Patch worker.forecasting.cache to use the in-process Redis."""
    monkeypatch.setattr("worker.forecasting.cache.get_redis", lambda: fake_redis)
    return fake_redis


@pytest.fixture(scope="module")
def opt_engine() -> CostOptimizationEngine:
    return CostOptimizationEngine(instance_types=build_instance_catalogue())


@pytest.fixture()
def forecast_pipeline(db_store, mock_redis, monkeypatch) -> ForecastPipeline:
    """ForecastPipeline with DB I/O replaced by InMemoryForecastStore."""

    def _fake_save(**kwargs):
        return db_store.save(**kwargs)

    monkeypatch.setattr("worker.forecasting.pipeline.save_forecast", _fake_save)
    return ForecastPipeline(use_cache=True, max_training_samples=120)


# ── Time-series data factories ────────────────────────────────────────────────

def make_rows(
    n: int,
    *,
    base: float = 0.50,
    noise: float = 0.03,
    trend: float = 0.0,
    seasonal_amp: float = 0.0,
    seed: int = 0,
    start: datetime | None = None,
) -> list[tuple[datetime, float]]:
    """Generate *n* hourly (timestamp, value) tuples."""
    rng = np.random.default_rng(seed)
    t0 = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        ts = t0 + timedelta(hours=i)
        seasonal = seasonal_amp * math.sin(2 * math.pi * i / 24)
        value = base + trend * i + seasonal + float(rng.normal(0, noise))
        rows.append((ts, max(0.0, min(1.0, value))))
    return rows


def idle_rows(n: int = 200, seed: int = 1) -> list[tuple[datetime, float]]:
    """CPU/mem utilisation rows for an effectively-idle resource."""
    return make_rows(n, base=0.008, noise=0.003, seed=seed)


def oversized_rows(n: int = 200, seed: int = 2) -> list[tuple[datetime, float]]:
    """Rows for a resource running well below 25% utilisation."""
    return make_rows(n, base=0.14, noise=0.04, seed=seed)


def rightsized_rows(n: int = 200, seed: int = 3) -> list[tuple[datetime, float]]:
    """Rows for a resource running at ~70% utilisation."""
    return make_rows(n, base=0.70, noise=0.04, seed=seed)


def seasonal_rows(n: int = 300, seed: int = 4) -> list[tuple[datetime, float]]:
    """Daily seasonal pattern — low at night, high in business hours."""
    return make_rows(n, base=0.45, noise=0.03, seasonal_amp=0.25, seed=seed)


def sparse_rows(n: int = 10, seed: int = 5) -> list[tuple[datetime, float]]:
    """Very few samples → linear model."""
    return make_rows(n, base=0.30, noise=0.05, seed=seed)


# ── Bridge: forecast → optimization ──────────────────────────────────────────

def forecast_result_to_usage(
    resource_id: str,
    cpu_result: PipelineResult | None,
    mem_result: PipelineResult | None = None,
    *,
    avg_daily_hours: float = 24.0,
    horizon_days: int = 30,
) -> ForecastedUsage:
    """Convert pipeline results to ForecastedUsage for the optimization engine.

    The forecasting pipeline outputs daily values in original metric units
    (utilisation fractions for cpu/mem, cost USD for cost_usd).  We extract
    p50 and p95 from the predicted daily values to build ForecastedUsage.
    """
    def _extract(result: PipelineResult | None, fallback: tuple[float, float]) -> tuple[float, float]:
        if result is None or result.skipped or not result.predictions:
            return fallback
        values = np.array([p.value for p in result.predictions])
        values = np.clip(values, 0.0, 1.0)  # keep in [0, 1] for utilisation metrics
        return float(np.percentile(values, 50)), float(np.percentile(values, 95))

    cpu_p50, cpu_p95 = _extract(cpu_result, (0.30, 0.50))
    mem_fallback = (cpu_p50 * 0.8, cpu_p95 * 0.8)
    mem_p50, mem_p95 = _extract(mem_result, mem_fallback)

    return ForecastedUsage(
        resource_id=resource_id,
        cpu_p50=round(float(cpu_p50), 4),
        cpu_p95=round(float(cpu_p95), 4),
        mem_p50=round(float(mem_p50), 4),
        mem_p95=round(float(mem_p95), 4),
        avg_daily_hours=avg_daily_hours,
        horizon_days=horizon_days,
    )

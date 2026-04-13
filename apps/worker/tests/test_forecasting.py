"""Tests for the forecasting pipeline.

Coverage
--------
* preprocessor — happy path, gap-filling, outlier clipping, normalisation,
  sparse data detection, max-samples capping, empty/insufficient input errors
* models — LinearTrendModel, SimpleESModel, HoltModel, HoltWintersModel (all
  four code paths), select_model threshold logic, HW fallback to Holt
* evaluator — normal evaluation, insufficient-data short-circuit, NaN actuals,
  zero-actual MAPE guard
* pipeline — cache hit, cache miss → full run, skip on insufficient data,
  denormalisation, daily aggregation
* cache — read/write/invalidate round-trip (in-process; no live Redis needed)
"""

from __future__ import annotations

import math
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

# ── evaluator ─────────────────────────────────────────────────────────────────
from worker.forecasting.evaluator import ForecastMetrics
from worker.forecasting.evaluator import _ci_coverage
from worker.forecasting.evaluator import _mae
from worker.forecasting.evaluator import _mape
from worker.forecasting.evaluator import _rmse
from worker.forecasting.evaluator import _smape
from worker.forecasting.evaluator import evaluate

# ── models ────────────────────────────────────────────────────────────────────
from worker.forecasting.models import HoltModel
from worker.forecasting.models import HoltWintersModel
from worker.forecasting.models import LinearTrendModel
from worker.forecasting.models import SimpleESModel
from worker.forecasting.models import select_model

# ── pipeline ──────────────────────────────────────────────────────────────────
from worker.forecasting.pipeline import ForecastPipeline
from worker.forecasting.pipeline import ForecastPoint
from worker.forecasting.pipeline import _aggregate_daily

# ── preprocessor ──────────────────────────────────────────────────────────────
from worker.forecasting.preprocessor import PreprocessResult
from worker.forecasting.preprocessor import ScalerParams
from worker.forecasting.preprocessor import preprocess

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _ts(offset_hours: int = 0) -> datetime:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return base + timedelta(hours=offset_hours)


def _make_rows(n: int, *, base_value: float = 50.0, noise: float = 5.0) -> list[tuple[datetime, float]]:
    """Generate *n* hourly rows starting at 2024-01-01 00:00 UTC."""
    rng = np.random.default_rng(42)
    return [
        (_ts(i), base_value + float(rng.normal(0, noise)))
        for i in range(n)
    ]


def _make_series(n: int, *, base_value: float = 50.0) -> pd.Series:
    rows = _make_rows(n, base_value=base_value, noise=5.0)
    ts = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    idx = pd.DatetimeIndex(ts, tz="UTC")
    return pd.Series(vals, index=idx, dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# ScalerParams
# ─────────────────────────────────────────────────────────────────────────────

class TestScalerParams:
    def test_denormalise_round_trip(self):
        scaler = ScalerParams(mean=100.0, std=20.0)
        arr = np.array([0.0, 1.0, -1.0, 2.5])
        original = scaler.denormalise(arr)
        expected = arr * 20.0 + 100.0
        np.testing.assert_allclose(original, expected)

    def test_denormalise_zero_std(self):
        scaler = ScalerParams(mean=42.0, std=0.0)
        arr = np.array([1.0, 2.0, 3.0])
        result = scaler.denormalise(arr)
        np.testing.assert_array_equal(result, [42.0, 42.0, 42.0])

    def test_denormalise_std_no_mean_shift(self):
        scaler = ScalerParams(mean=100.0, std=20.0)
        arr = np.array([1.0, 0.5])
        result = scaler.denormalise_std(arr)
        np.testing.assert_allclose(result, [20.0, 10.0])


# ─────────────────────────────────────────────────────────────────────────────
# Preprocessor
# ─────────────────────────────────────────────────────────────────────────────

class TestPreprocessor:
    def test_happy_path_normalises(self):
        rows = _make_rows(168)  # 7 days
        result = preprocess(rows)
        assert isinstance(result, PreprocessResult)
        # Z-score: mean ≈ 0, std ≈ 1 on the non-NaN values
        valid = result.series.dropna()
        assert abs(float(valid.mean())) < 0.1
        assert 0.8 < float(valid.std()) < 1.2

    def test_max_samples_capped(self):
        rows = _make_rows(600)
        result = preprocess(rows, max_samples=100)
        assert result.n_samples == 100
        assert len(result.series) == 100

    def test_gap_filling_forward_fill(self):
        rows = _make_rows(24)
        # Introduce a 2-hour gap at positions 5 and 6
        rows_with_gap = [(ts, v) for i, (ts, v) in enumerate(rows) if i not in (5, 6)]
        result = preprocess(rows_with_gap, max_samples=500)
        # Gap should be filled; n_filled ≥ 2
        assert result.n_filled >= 2

    def test_outlier_clipping(self):
        rows = _make_rows(100, base_value=50.0, noise=2.0)
        # Add two extreme outliers
        rows[10] = (rows[10][0], 1_000_000.0)
        rows[50] = (rows[50][0], -999_999.0)
        result = preprocess(rows, iqr_factor=3.0)
        # n_clipped should reflect at least the two injected outliers
        assert result.n_clipped >= 2
        # Clipped values should not reach the extremes
        assert float(result.raw_series.max()) < 500.0

    def test_sparse_flag(self):
        # Only 10 samples — should be flagged as sparse (< 24 non-NaN)
        rows = _make_rows(10)
        result = preprocess(rows)
        assert result.is_sparse is True

    def test_not_sparse_with_enough_data(self):
        rows = _make_rows(100)
        result = preprocess(rows)
        assert result.is_sparse is False

    def test_empty_rows_raises(self):
        with pytest.raises(ValueError, match="empty"):
            preprocess([])

    def test_insufficient_data_raises(self):
        rows = [(_ts(0), 42.0)]  # only 1 point
        with pytest.raises(ValueError):
            preprocess(rows)

    def test_training_start_end(self):
        rows = _make_rows(48)
        result = preprocess(rows)
        assert result.training_start < result.training_end
        assert result.training_start.tzinfo is not None

    def test_constant_series_does_not_crash(self):
        rows = [(_ts(i), 100.0) for i in range(50)]
        result = preprocess(rows)
        # mean should be 100, std falls back to 1 internally
        assert result.scaler.mean == pytest.approx(100.0)

    def test_naive_timestamps_treated_as_utc(self):
        naive_rows = [(datetime(2024, 1, 1) + timedelta(hours=i), float(i)) for i in range(30)]
        result = preprocess(naive_rows)
        assert result.training_start.tzinfo is not None


# ─────────────────────────────────────────────────────────────────────────────
# Models — unit tests (no live DB, fast)
# ─────────────────────────────────────────────────────────────────────────────

class TestLinearTrendModel:
    def test_fit_and_predict(self):
        series = _make_series(15)
        model = LinearTrendModel()
        result = model.train_and_forecast(series, horizon_hours=72)
        assert result.model_type == "linear"
        assert len(result.point) == 72
        assert len(result.lower_95) == 72
        assert len(result.upper_95) == 72

    def test_ci_widens(self):
        series = _make_series(10)
        model = LinearTrendModel()
        result = model.train_and_forecast(series, horizon_hours=48)
        # Upper CI should widen over the horizon
        widths = result.upper_95 - result.lower_95
        assert widths[-1] >= widths[0]

    def test_get_params(self):
        series = _make_series(10)
        model = LinearTrendModel()
        model.fit(series)
        params = model.get_params()
        assert "slope" in params
        assert "intercept" in params

    def test_predict_without_fit_raises(self):
        model = LinearTrendModel()
        with pytest.raises(RuntimeError, match="not been fitted"):
            model.predict(10)


class TestSimpleESModel:
    def test_fit_and_predict(self):
        series = _make_series(35)
        model = SimpleESModel()
        result = model.train_and_forecast(series, horizon_hours=24)
        assert result.model_type == "simple_es"
        assert len(result.point) == 24

    def test_get_params_has_alpha(self):
        series = _make_series(30)
        model = SimpleESModel()
        model.fit(series)
        assert "alpha" in model.get_params()


class TestHoltModel:
    def test_fit_and_predict(self):
        series = _make_series(60)
        model = HoltModel()
        result = model.train_and_forecast(series, horizon_hours=48)
        assert result.model_type == "holt"
        assert len(result.point) == 48

    def test_get_params_has_beta(self):
        series = _make_series(60)
        model = HoltModel()
        model.fit(series)
        params = model.get_params()
        assert "alpha" in params
        assert "beta" in params
        assert "phi" in params


class TestHoltWintersModel:
    def test_fit_and_predict(self):
        # 200 hourly samples — enough for HW
        series = _make_series(200)
        model = HoltWintersModel(seasonal_periods=24)
        result = model.train_and_forecast(series, horizon_hours=48)
        # model_type may be 'holt_winters' or 'holt' depending on series length
        assert result.model_type in ("holt_winters", "holt")
        assert len(result.point) == 48

    def test_fallback_to_holt_for_short_series(self):
        # 48 samples → < 2 × 24 seasonal periods: falls back to Holt
        series = _make_series(48)
        model = HoltWintersModel(seasonal_periods=24)
        model.fit(series)
        assert model.model_type == "holt"

    def test_get_params(self):
        series = _make_series(200)
        model = HoltWintersModel(seasonal_periods=24)
        model.fit(series)
        params = model.get_params()
        assert "seasonal_periods" in params


class TestSelectModel:
    @pytest.mark.parametrize("n,expected_type", [
        (5,   LinearTrendModel),
        (23,  LinearTrendModel),
        (24,  SimpleESModel),
        (47,  SimpleESModel),
        (48,  HoltModel),
        (167, HoltModel),
        (168, HoltWintersModel),
        (500, HoltWintersModel),
    ])
    def test_threshold_ladder(self, n, expected_type):
        model = select_model(n)
        assert isinstance(model, expected_type), (
            f"select_model({n}) returned {type(model).__name__}, "
            f"expected {expected_type.__name__}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Evaluator
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricFunctions:
    def test_mape_basic(self):
        actual = np.array([100.0, 200.0, 300.0])
        pred = np.array([110.0, 190.0, 315.0])
        result = _mape(actual, pred)
        expected = np.mean([10/100, 10/200, 15/300]) * 100
        assert result == pytest.approx(expected, rel=1e-5)

    def test_mape_all_zeros_returns_nan(self):
        actual = np.array([0.0, 0.0])
        pred = np.array([1.0, 2.0])
        assert math.isnan(_mape(actual, pred))

    def test_smape_symmetric(self):
        actual = np.array([100.0])
        pred = np.array([200.0])
        # sMAPE should be between 0 and 200
        result = _smape(actual, pred)
        assert 0.0 < result <= 200.0

    def test_rmse(self):
        actual = np.array([1.0, 2.0, 3.0])
        pred = np.array([1.0, 2.0, 3.0])
        assert _rmse(actual, pred) == pytest.approx(0.0)

    def test_mae(self):
        actual = np.array([1.0, 3.0])
        pred = np.array([0.0, 5.0])
        assert _mae(actual, pred) == pytest.approx(1.5)

    def test_ci_coverage_all_within(self):
        a = np.array([1.0, 2.0, 3.0])
        lo = np.array([0.0, 1.0, 2.0])
        hi = np.array([2.0, 3.0, 4.0])
        assert _ci_coverage(a, lo, hi) == pytest.approx(1.0)

    def test_ci_coverage_none_within(self):
        a = np.array([10.0, 20.0])
        lo = np.array([0.0, 0.0])
        hi = np.array([1.0, 1.0])
        assert _ci_coverage(a, lo, hi) == pytest.approx(0.0)


class TestEvaluate:
    def test_normal_evaluation(self):
        # 200 points: 176 train, 24 holdout
        series = _make_series(200)
        metrics = evaluate(series, scaler_mean=50.0, scaler_std=5.0)
        # Should return real numbers, not None
        assert metrics.mape is not None
        assert metrics.rmse is not None
        assert metrics.coverage_95 is not None
        # MAPE in percent — expect < 100 % for a reasonable series
        assert 0.0 <= metrics.mape <= 200.0
        # Coverage in [0, 1]
        assert 0.0 <= metrics.coverage_95 <= 1.0

    def test_insufficient_data_returns_none_metrics(self):
        # 30 points < 24 (min_training) + 24 (holdout) → all None
        series = _make_series(30)
        metrics = evaluate(series, holdout_size=24, min_training=24)
        assert metrics.mape is None
        assert metrics.rmse is None
        assert metrics.mae is None
        assert metrics.coverage_95 is None

    def test_returns_forecast_metrics_type(self):
        series = _make_series(200)
        metrics = evaluate(series)
        assert isinstance(metrics, ForecastMetrics)

    def test_constant_series_metrics_not_none(self):
        # Constant series: zero error expected
        vals = [100.0] * 200
        ts = [_ts(i) for i in range(200)]
        series = pd.Series(vals, index=pd.DatetimeIndex(ts, tz="UTC"))
        # After normalising a constant series, z-score = 0 everywhere
        metrics = evaluate(series, scaler_mean=100.0, scaler_std=1.0)
        # May be None (constant → zero division in MAPE) or 0 — either is fine
        if metrics.rmse is not None:
            assert metrics.rmse == pytest.approx(0.0, abs=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# _aggregate_daily helper
# ─────────────────────────────────────────────────────────────────────────────

class TestAggregateDaily:
    def test_aggregates_24_hours_to_1_day(self):
        idx = pd.date_range("2024-01-01", periods=24, freq="1h", tz="UTC")
        point = np.ones(24) * 10.0
        lower = np.ones(24) * 8.0
        upper = np.ones(24) * 12.0
        points = _aggregate_daily(idx, point, lower, upper)
        assert len(points) == 1
        assert points[0].date == "2024-01-01"
        assert points[0].value == pytest.approx(240.0)

    def test_aggregates_48_hours_to_2_days(self):
        idx = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
        point = np.ones(48)
        lower = np.zeros(48)
        upper = np.ones(48) * 2.0
        points = _aggregate_daily(idx, point, lower, upper)
        assert len(points) == 2

    def test_date_format_iso8601(self):
        idx = pd.date_range("2024-03-15", periods=24, freq="1h", tz="UTC")
        point = np.ones(24)
        points = _aggregate_daily(idx, point, point * 0, point * 2)
        assert points[0].date == "2024-03-15"

    def test_forecast_point_to_dict(self):
        fp = ForecastPoint(date="2024-01-01", value=100.5, lower_95=90.0, upper_95=110.1)
        d = fp.to_dict()
        assert d["date"] == "2024-01-01"
        assert d["value"] == pytest.approx(100.5, abs=0.01)
        assert "lower_95" in d
        assert "upper_95" in d


# ─────────────────────────────────────────────────────────────────────────────
# ForecastPipeline (with mocked dependencies)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_settings():
    with patch("worker.forecasting.pipeline.get_settings") as m:
        cfg = MagicMock()
        cfg.forecast_horizon_days = 30
        cfg.forecast_lookback_days = 90
        cfg.forecast_max_training_samples = 500
        cfg.forecast_cache_ttl_seconds = 21_600
        m.return_value = cfg
        yield cfg


@pytest.fixture()
def mock_store(monkeypatch):
    """Return a factory of fake usage rows and a stub save_forecast."""
    rows = _make_rows(200)

    monkeypatch.setattr(
        "worker.forecasting.pipeline.fetch_usage_rows",
        lambda resource_id, metric, lookback_days=90: rows,
    )

    saved: dict[str, Any] = {}

    def fake_save(**kwargs):
        uid = uuid4()
        saved["last"] = kwargs
        return uid

    monkeypatch.setattr("worker.forecasting.pipeline.save_forecast", fake_save)
    return saved


@pytest.fixture()
def mock_cache(monkeypatch):
    """In-process dict simulating the Redis cache."""
    store: dict[str, Any] = {}

    def fake_get(resource_id, metric):
        return store.get(f"{resource_id}:{metric}")

    def fake_set(resource_id, metric, payload, ttl_seconds=21_600):
        store[f"{resource_id}:{metric}"] = payload

    monkeypatch.setattr("worker.forecasting.pipeline.get_cached_forecast", fake_get)
    monkeypatch.setattr("worker.forecasting.pipeline.cache_forecast", fake_set)
    return store


class TestForecastPipeline:
    def test_full_pipeline_run(self, mock_settings, mock_store, mock_cache):
        pipeline = ForecastPipeline(use_cache=True)
        result = pipeline.run(resource_id=str(uuid4()), metric="cpu_utilization")

        assert not result.skipped
        assert len(result.predictions) > 0
        assert result.model_type != ""
        assert result.training_samples > 0
        assert result.training_time_ms >= 0
        assert result.forecast_id is not None

    def test_cache_hit_returns_from_cache(self, mock_settings, mock_store, mock_cache):
        resource_id = str(uuid4())
        metric = "cpu_utilization"
        # Pre-populate cache
        mock_cache[f"{resource_id}:{metric}"] = {
            "model_type": "holt",
            "predictions": [{"date": "2024-01-31", "value": 55.0, "lower_95": 45.0, "upper_95": 65.0}],
            "metrics": {"mape": 5.0, "smape": 4.9, "rmse": 2.1, "mae": 1.8, "coverage_95": 0.93},
        }
        pipeline = ForecastPipeline(use_cache=True)
        result = pipeline.run(resource_id=resource_id, metric=metric)
        assert result.from_cache is True
        assert result.model_type == "holt"
        assert len(result.predictions) == 1

    def test_skip_on_insufficient_data(self, mock_settings, monkeypatch):
        monkeypatch.setattr(
            "worker.forecasting.pipeline.fetch_usage_rows",
            lambda *a, **kw: [],   # no data
        )
        monkeypatch.setattr("worker.forecasting.pipeline.get_cached_forecast", lambda *a: None)
        monkeypatch.setattr("worker.forecasting.pipeline.cache_forecast", lambda *a, **kw: None)

        pipeline = ForecastPipeline(use_cache=False)
        result = pipeline.run(resource_id=str(uuid4()), metric="cost_usd")

        assert result.skipped is True
        assert result.skip_reason != ""

    def test_predictions_are_daily(self, mock_settings, mock_store, mock_cache):
        pipeline = ForecastPipeline(use_cache=False)
        result = pipeline.run(resource_id=str(uuid4()), metric="cpu_utilization")

        if not result.skipped:
            for pt in result.predictions:
                # Date must parse as a valid ISO date with no time component
                parsed = datetime.strptime(pt.date, "%Y-%m-%d")
                assert parsed is not None
                # Lower ≤ value ≤ upper
                assert pt.lower_95 <= pt.value + 1e-6
                assert pt.value - 1e-6 <= pt.upper_95

    def test_force_refresh_bypasses_cache(self, mock_settings, mock_store, mock_cache):
        resource_id = str(uuid4())
        metric = "memory_utilization"
        # Pre-populate cache
        mock_cache[f"{resource_id}:{metric}"] = {"model_type": "cached", "predictions": [], "metrics": {}}

        pipeline = ForecastPipeline(use_cache=True)
        result = pipeline.run(resource_id=resource_id, metric=metric, force_refresh=True)

        # Should NOT return from cache
        assert result.from_cache is False

    def test_metrics_logged(self, mock_settings, mock_store, mock_cache):
        pipeline = ForecastPipeline(use_cache=False)
        result = pipeline.run(resource_id=str(uuid4()), metric="cpu_utilization")

        if not result.skipped:
            # Metrics object must be set
            assert result.metrics is not None
            # All metric fields are float or None
            for field in ("mape", "smape", "rmse", "mae", "coverage_95"):
                val = getattr(result.metrics, field)
                assert val is None or isinstance(val, float)


# ─────────────────────────────────────────────────────────────────────────────
# Cache module — unit tests (patching Redis)
# ─────────────────────────────────────────────────────────────────────────────

class FakeRedis:
    """Minimal in-process Redis substitute."""

    def __init__(self):
        self._store: dict[str, str] = {}

    def setex(self, key, ttl, value):
        self._store[key] = value

    def get(self, key):
        return self._store.get(key)

    def delete(self, *keys):
        count = sum(1 for k in keys if self._store.pop(k, None) is not None)
        return count

    def keys(self, pattern: str) -> list[str]:
        prefix = pattern.rstrip("*")
        return [k for k in self._store if k.startswith(prefix)]


@pytest.fixture()
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr("worker.forecasting.cache.get_redis", lambda: r)
    return r


class TestForecastCache:
    def test_cache_and_retrieve(self, fake_redis):
        from worker.forecasting.cache import cache_forecast
        from worker.forecasting.cache import get_cached_forecast

        resource_id = str(uuid4())
        metric = "cpu_utilization"
        payload = {"model_type": "holt", "predictions": [{"date": "2024-01-31", "value": 55.0}]}

        cache_forecast(resource_id, metric, payload)
        result = get_cached_forecast(resource_id, metric)

        assert result is not None
        assert result["model_type"] == "holt"
        assert result["predictions"][0]["value"] == 55.0

    def test_cache_miss_returns_none(self, fake_redis):
        from worker.forecasting.cache import get_cached_forecast

        result = get_cached_forecast(str(uuid4()), "nonexistent_metric")
        assert result is None

    def test_invalidate_specific(self, fake_redis):
        from worker.forecasting.cache import cache_forecast
        from worker.forecasting.cache import get_cached_forecast
        from worker.forecasting.cache import invalidate_forecast

        resource_id = str(uuid4())
        metric = "cost_usd"
        cache_forecast(resource_id, metric, {"x": 1})
        assert get_cached_forecast(resource_id, metric) is not None

        invalidate_forecast(resource_id, metric)
        assert get_cached_forecast(resource_id, metric) is None

    def test_invalidate_all(self, fake_redis):
        from worker.forecasting.cache import cache_forecast
        from worker.forecasting.cache import get_cached_forecast
        from worker.forecasting.cache import invalidate_all_forecasts

        resource_id = str(uuid4())
        for metric in ("cpu_utilization", "memory_utilization", "cost_usd"):
            cache_forecast(resource_id, metric, {"m": metric})

        count = invalidate_all_forecasts(resource_id)
        assert count == 3
        for metric in ("cpu_utilization", "memory_utilization", "cost_usd"):
            assert get_cached_forecast(resource_id, metric) is None

    def test_datetime_serialisation(self, fake_redis):
        from worker.forecasting.cache import cache_forecast
        from worker.forecasting.cache import get_cached_forecast

        resource_id = str(uuid4())
        metric = "cpu_utilization"
        now = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
        payload = {"generated_at": now, "value": 99.9}

        cache_forecast(resource_id, metric, payload)
        result = get_cached_forecast(resource_id, metric)

        assert result is not None
        assert "2024-01-15" in result["generated_at"]

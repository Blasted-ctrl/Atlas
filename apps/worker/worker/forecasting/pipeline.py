"""ForecastPipeline — orchestrates the full per-resource forecast lifecycle.

Usage
-----
    from worker.forecasting.pipeline import ForecastPipeline, PipelineResult

    pipeline = ForecastPipeline()
    result = pipeline.run(resource_id="...", metric="cpu_utilization")
    # result.predictions: list of ForecastPoint
    # result.metrics:     ForecastMetrics (MAPE, RMSE, …)
    # result.skipped:     True if insufficient data
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd

from worker.config import get_settings
from worker.telemetry import observe_forecast
from worker.telemetry import worker_span

from .cache import cache_forecast
from .cache import get_cached_forecast
from .evaluator import ForecastMetrics
from .evaluator import evaluate
from .models import ForecastModel
from .models import ForecastResult
from .models import select_model
from .preprocessor import PreprocessResult
from .preprocessor import preprocess
from .store import fetch_usage_rows
from .store import save_forecast

logger = logging.getLogger(__name__)


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ForecastPoint:
    """A single day-level forecast datapoint (denormalised, original units)."""

    date: str               # ISO-8601 date "YYYY-MM-DD"
    value: float
    lower_95: float
    upper_95: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "value": round(self.value, 4),
            "lower_95": round(self.lower_95, 4),
            "upper_95": round(self.upper_95, 4),
        }


@dataclass
class PipelineResult:
    """Full output from :py:meth:`ForecastPipeline.run`."""

    resource_id: str
    metric: str
    skipped: bool = False
    skip_reason: str = ""

    # Set when not skipped
    forecast_id: UUID | None = None
    predictions: list[ForecastPoint] = field(default_factory=list)
    metrics: ForecastMetrics | None = None
    model_type: str = ""
    training_samples: int = 0
    training_time_ms: int = 0
    training_start: datetime | None = None
    training_end: datetime | None = None
    forecast_start: datetime | None = None
    forecast_end: datetime | None = None
    from_cache: bool = False


# ── Pipeline ──────────────────────────────────────────────────────────────────

class ForecastPipeline:
    """Stateless orchestrator: fetch → preprocess → train → evaluate → store → cache.

    Parameters
    ----------
    horizon_days:
        Number of days to forecast ahead (default: 30).
    lookback_days:
        How many days of historical data to fetch from the DB (default: 90).
    max_training_samples:
        Cap on training set size to stay within the 500 ms training budget.
    cache_ttl_seconds:
        TTL for the Redis cache entry.
    use_cache:
        Set to ``False`` in tests or forced-refresh scenarios.
    """

    def __init__(
        self,
        *,
        horizon_days: int | None = None,
        lookback_days: int | None = None,
        max_training_samples: int | None = None,
        cache_ttl_seconds: int | None = None,
        use_cache: bool = True,
    ) -> None:
        settings = get_settings()
        self.horizon_days = horizon_days or settings.forecast_horizon_days
        self.lookback_days = lookback_days or settings.forecast_lookback_days
        self.max_training_samples = max_training_samples or settings.forecast_max_training_samples
        self.cache_ttl_seconds = cache_ttl_seconds or settings.forecast_cache_ttl_seconds
        self.use_cache = use_cache

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        resource_id: str | UUID,
        metric: str,
        *,
        force_refresh: bool = False,
    ) -> PipelineResult:
        """Run the full pipeline for one (resource_id, metric) pair.

        Returns a :class:`PipelineResult`.  When the series is too sparse the
        result has ``skipped=True`` and all forecast fields are None.
        """
        resource_id = str(resource_id)
        result = PipelineResult(resource_id=resource_id, metric=metric)
        started = time.perf_counter()

        # ── 1. Cache hit ──────────────────────────────────────────────────────
        if self.use_cache and not force_refresh:
            cached = get_cached_forecast(resource_id, metric)
            if cached is not None:
                result = self._result_from_cache(cached, resource_id, metric)
                observe_forecast(
                    metric,
                    time.perf_counter() - started,
                    from_cache=True,
                    mape=result.metrics.mape if result.metrics else None,
                )
                return result

        # ── 2. Fetch raw usage ────────────────────────────────────────────────
        with worker_span("forecast.pipeline.run", resource_id=resource_id, metric=metric):
            rows = fetch_usage_rows(resource_id, metric, lookback_days=self.lookback_days)
        if len(rows) < 2:
            result.skipped = True
            result.skip_reason = f"Insufficient data: {len(rows)} rows"
            logger.info(
                "forecast.skip",
                extra={"resource_id": resource_id, "metric": metric, "rows": len(rows)},
            )
            observe_forecast(metric, time.perf_counter() - started, from_cache=False, mape=None)
            return result

        # ── 3. Preprocess ─────────────────────────────────────────────────────
        try:
            prep: PreprocessResult = preprocess(
                rows,
                max_samples=self.max_training_samples,
            )
        except ValueError as exc:
            result.skipped = True
            result.skip_reason = str(exc)
            observe_forecast(metric, time.perf_counter() - started, from_cache=False, mape=None)
            return result

        if prep.is_sparse:
            logger.warning(
                "forecast.sparse",
                extra={
                    "resource_id": resource_id,
                    "metric": metric,
                    "n_samples": prep.n_samples,
                },
            )

        # ── 4. Model selection & training ─────────────────────────────────────
        n_valid = int(prep.series.dropna().count())
        model: ForecastModel = select_model(n_valid)
        horizon_hours = self.horizon_days * 24

        forecast_result: ForecastResult = model.train_and_forecast(
            prep.series, horizon_hours
        )

        logger.info(
            "forecast.trained",
            extra={
                "resource_id": resource_id,
                "metric": metric,
                "model": forecast_result.model_type,
                "training_ms": forecast_result.training_time_ms,
                "n_samples": prep.n_samples,
            },
        )

        # ── 5. Evaluate on holdout ────────────────────────────────────────────
        metrics = evaluate(
            prep.series,
            scaler_mean=prep.scaler.mean,
            scaler_std=prep.scaler.std,
        )

        # ── 6. Denormalise predictions ────────────────────────────────────────
        point_raw = prep.scaler.denormalise(forecast_result.point)
        lower_raw = prep.scaler.denormalise(forecast_result.lower_95)
        upper_raw = prep.scaler.denormalise(forecast_result.upper_95)

        # Clamp lower bound to 0 for non-negative metrics
        lower_raw = np.maximum(lower_raw, 0.0)

        # ── 7. Aggregate hourly → daily ───────────────────────────────────────
        predictions = _aggregate_daily(
            index=forecast_result.forecast_index,
            point=point_raw,
            lower=lower_raw,
            upper=upper_raw,
            metric=metric,
        )

        # ── 8. Build temporal metadata ────────────────────────────────────────
        forecast_start: datetime = forecast_result.forecast_index[0].to_pydatetime().replace(
            tzinfo=UTC
        )
        forecast_end: datetime = forecast_result.forecast_index[-1].to_pydatetime().replace(
            tzinfo=UTC
        )

        # ── 9. Persist to Postgres ────────────────────────────────────────────
        forecast_id = save_forecast(
            resource_id=resource_id,
            metric=metric,
            model_type=forecast_result.model_type,
            model_params=forecast_result.model_params,
            training_start=prep.training_start,
            training_end=prep.training_end,
            forecast_start=forecast_start,
            forecast_end=forecast_end,
            horizon_days=self.horizon_days,
            training_samples=prep.n_samples,
            training_time_ms=forecast_result.training_time_ms,
            mape=metrics.mape,
            smape=metrics.smape,
            rmse=metrics.rmse,
            mae=metrics.mae,
            coverage_95=metrics.coverage_95,
            predictions=[p.to_dict() for p in predictions],
        )

        # ── 10. Write-through cache ───────────────────────────────────────────
        if self.use_cache:
            cache_payload = _build_cache_payload(
                forecast_id=forecast_id,
                resource_id=resource_id,
                metric=metric,
                model_type=forecast_result.model_type,
                predictions=predictions,
                metrics=metrics,
                training_start=prep.training_start,
                training_end=prep.training_end,
                forecast_start=forecast_start,
                forecast_end=forecast_end,
                horizon_days=self.horizon_days,
            )
            cache_forecast(resource_id, metric, cache_payload, ttl_seconds=self.cache_ttl_seconds)

        # ── 11. Build result ──────────────────────────────────────────────────
        result.forecast_id = forecast_id
        result.predictions = predictions
        result.metrics = metrics
        result.model_type = forecast_result.model_type
        result.training_samples = prep.n_samples
        result.training_time_ms = forecast_result.training_time_ms
        result.training_start = prep.training_start
        result.training_end = prep.training_end
        result.forecast_start = forecast_start
        result.forecast_end = forecast_end
        observe_forecast(
            metric,
            time.perf_counter() - started,
            from_cache=False,
            mape=result.metrics.mape if result.metrics else None,
        )

        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _result_from_cache(cached: dict, resource_id: str, metric: str) -> PipelineResult:
        result = PipelineResult(resource_id=resource_id, metric=metric, from_cache=True)
        result.predictions = [
            ForecastPoint(
                date=p["date"],
                value=p["value"],
                lower_95=p["lower_95"],
                upper_95=p["upper_95"],
            )
            for p in cached.get("predictions", [])
        ]
        result.model_type = cached.get("model_type", "")
        if m := cached.get("metrics"):
            result.metrics = ForecastMetrics(
                mape=m.get("mape"),
                smape=m.get("smape"),
                rmse=m.get("rmse"),
                mae=m.get("mae"),
                coverage_95=m.get("coverage_95"),
            )
        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _aggregate_daily(
    index: pd.DatetimeIndex,
    point: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    metric: str = "cost_usd",
) -> list[ForecastPoint]:
    """Aggregate hourly arrays into daily :class:`ForecastPoint` objects.

    Utilization-like metrics are averaged over fixed 24-hour forecast windows
    from the forecast start, so a 30-day / 720-hour horizon always yields
    exactly 30 daily points even when the hourly forecast starts mid-day.

    Cost-like metrics preserve calendar-day resampling semantics, which keeps
    partial first/last days visible to callers that work with calendar buckets.
    """
    if len(index) == 0:
        return []

    is_utilization_metric = "utilization" in metric
    points: list[ForecastPoint] = []
    if is_utilization_metric:
        chunk_count = len(point) // 24
        if chunk_count == 0:
            return []

        point_daily = point[: chunk_count * 24].reshape(chunk_count, 24)
        lower_daily = lower[: chunk_count * 24].reshape(chunk_count, 24)
        upper_daily = upper[: chunk_count * 24].reshape(chunk_count, 24)
        start_date = index[0].date()

        for day in range(chunk_count):
            date_str = (start_date + timedelta(days=day)).strftime("%Y-%m-%d")
            value = float(np.clip(np.mean(point_daily[day]), 0.0, 1.0))
            lower_95 = float(np.clip(np.mean(lower_daily[day]), 0.0, 1.0))
            upper_95 = float(np.clip(np.mean(upper_daily[day]), 0.0, 1.0))
            points.append(
                ForecastPoint(
                    date=date_str,
                    value=value,
                    lower_95=lower_95,
                    upper_95=upper_95,
                )
            )
        return points

    df = pd.DataFrame({"point": point, "lower": lower, "upper": upper}, index=index)
    daily = df.resample("1D").agg({"point": "sum", "lower": "sum", "upper": "sum"})
    for date_idx, row in daily.iterrows():
        points.append(
            ForecastPoint(
                date=date_idx.strftime("%Y-%m-%d"),
                value=float(row["point"]),
                lower_95=float(row["lower"]),
                upper_95=float(row["upper"]),
            )
        )
    return points


def _build_cache_payload(
    *,
    forecast_id: UUID,
    resource_id: str,
    metric: str,
    model_type: str,
    predictions: list[ForecastPoint],
    metrics: ForecastMetrics,
    training_start: datetime,
    training_end: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
    horizon_days: int,
) -> dict:
    return {
        "id": str(forecast_id),
        "resource_id": resource_id,
        "metric": metric,
        "model_type": model_type,
        "horizon_days": horizon_days,
        "training_start": training_start.isoformat(),
        "training_end": training_end.isoformat(),
        "forecast_start": forecast_start.isoformat(),
        "forecast_end": forecast_end.isoformat(),
        "metrics": {
            "mape": metrics.mape,
            "smape": metrics.smape,
            "rmse": metrics.rmse,
            "mae": metrics.mae,
            "coverage_95": metrics.coverage_95,
        },
        "predictions": [p.to_dict() for p in predictions],
    }

"""CI gate for forecast accuracy."""

from __future__ import annotations

import math
import os
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import numpy as np

from worker.forecasting.evaluator import evaluate
from worker.forecasting.preprocessor import preprocess


def _make_series(
    *,
    hours: int,
    baseline: float,
    daily_amplitude: float,
    weekly_amplitude: float,
    trend_per_day: float,
    noise: float,
    seed: int,
) -> list[tuple[datetime, float]]:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows: list[tuple[datetime, float]] = []
    for hour in range(hours):
        timestamp = start + timedelta(hours=hour)
        daily = daily_amplitude * math.sin(2 * math.pi * (hour % 24) / 24)
        weekly = weekly_amplitude * math.sin(2 * math.pi * hour / (24 * 7))
        trend = trend_per_day * (hour / 24)
        value = baseline + daily + weekly + trend + float(rng.normal(0, noise))
        rows.append((timestamp, max(value, 0.1)))
    return rows


def _scenario_rows() -> dict[str, list[tuple[datetime, float]]]:
    return {
        "steady_compute": _make_series(
            hours=24 * 45,
            baseline=62.0,
            daily_amplitude=8.0,
            weekly_amplitude=4.0,
            trend_per_day=0.03,
            noise=1.8,
            seed=7,
        ),
        "memory_heavy": _make_series(
            hours=24 * 45,
            baseline=74.0,
            daily_amplitude=5.5,
            weekly_amplitude=3.2,
            trend_per_day=-0.02,
            noise=1.5,
            seed=11,
        ),
        "cloud_cost": _make_series(
            hours=24 * 60,
            baseline=14.0,
            daily_amplitude=1.8,
            weekly_amplitude=2.5,
            trend_per_day=0.05,
            noise=0.7,
            seed=23,
        ),
    }


def main() -> int:
    threshold = float(os.getenv("ATLAS_FORECAST_ERROR_THRESHOLD", "15"))
    scenario_mapes: dict[str, float] = {}

    for name, rows in _scenario_rows().items():
        prep = preprocess(rows, max_samples=500)
        metrics = evaluate(
            prep.series,
            scaler_mean=prep.scaler.mean,
            scaler_std=prep.scaler.std,
        )
        if metrics.mape is None:
            raise SystemExit(f"{name}: evaluator returned no MAPE")
        scenario_mapes[name] = metrics.mape

    worst_name, worst_mape = max(scenario_mapes.items(), key=lambda item: item[1])
    print("Forecast MAPE by scenario:")
    for name, mape in scenario_mapes.items():
        print(f"  - {name}: {mape:.3f}%")
    print(f"Worst-case MAPE: {worst_name} = {worst_mape:.3f}%")

    if worst_mape >= threshold:
        raise SystemExit(
            f"Forecast quality gate failed: {worst_mape:.3f}% >= {threshold:.3f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Forecast evaluation — computes MAPE, sMAPE, RMSE, MAE, and CI coverage.

Walk-forward cross-validation
------------------------------
When the series is long enough (≥ 2 × min_holdout), the evaluator holds out
the last ``holdout_size`` points, trains on the remainder, forecasts
``holdout_size`` steps ahead, and scores the predictions against the actuals.

When there are fewer than ``2 × min_holdout`` points the evaluator returns
``None`` for all metrics (the pipeline will store NULL in the DB and skip
MAPE-based model selection).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .models import ForecastModel
from .models import ForecastResult
from .models import select_model

# ── Public types ──────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ForecastMetrics:
    """Evaluation metrics computed on the holdout window."""

    mape: float | None          # Mean Absolute Percentage Error (%)
    smape: float | None         # Symmetric MAPE (%)
    rmse: float | None          # Root Mean Squared Error (original units)
    mae: float | None           # Mean Absolute Error (original units)
    coverage_95: float | None   # Fraction of holdout actuals within 95 % CI


# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_HOLDOUT_SIZE = 24       # 1 day of hourly data
MIN_TRAINING_FOR_EVAL = 24     # must have at least this many training points


# ── Public API ────────────────────────────────────────────────────────────────

def evaluate(
    series: pd.Series,
    *,
    scaler_mean: float = 0.0,
    scaler_std: float = 1.0,
    holdout_size: int = DEFAULT_HOLDOUT_SIZE,
    min_training: int = MIN_TRAINING_FOR_EVAL,
) -> ForecastMetrics:
    """Perform walk-forward evaluation on *series*.

    Parameters
    ----------
    series:
        Normalised hourly series (same as passed to the model).
    scaler_mean / scaler_std:
        Z-score parameters used to convert normalised predictions back to
        original units for RMSE / MAE.
    holdout_size:
        Number of trailing points to hold out.
    min_training:
        Minimum number of non-NaN training points required; returns all-None
        metrics when not met.

    Returns
    -------
    ForecastMetrics with all fields populated (or all None if insufficient data).
    """
    valid = series.dropna()
    total = len(valid)

    if total < min_training + holdout_size:
        return ForecastMetrics(
            mape=None, smape=None, rmse=None, mae=None, coverage_95=None
        )

    # Split
    train_series = series.iloc[:-holdout_size]
    holdout_series = series.iloc[-holdout_size:]

    n_train = int(train_series.dropna().count())
    if n_train < min_training:
        return ForecastMetrics(
            mape=None, smape=None, rmse=None, mae=None, coverage_95=None
        )

    # Fit the same model that would be chosen for this training window size
    model: ForecastModel = select_model(n_train)
    try:
        result: ForecastResult = model.train_and_forecast(train_series, horizon_hours=holdout_size)
    except Exception:
        return ForecastMetrics(
            mape=None, smape=None, rmse=None, mae=None, coverage_95=None
        )

    actuals_norm = holdout_series.values.astype(float)
    preds_norm = result.point
    lower_norm = result.lower_95
    upper_norm = result.upper_95

    # Align lengths (in case model truncated)
    n = min(len(actuals_norm), len(preds_norm))
    actuals_norm = actuals_norm[:n]
    preds_norm = preds_norm[:n]
    lower_norm = lower_norm[:n]
    upper_norm = upper_norm[:n]

    # Filter out NaN actuals for metric computation
    mask = ~np.isnan(actuals_norm) & ~np.isnan(preds_norm)
    if mask.sum() == 0:
        return ForecastMetrics(
            mape=None, smape=None, rmse=None, mae=None, coverage_95=None
        )

    a = actuals_norm[mask]
    p = preds_norm[mask]
    lo = lower_norm[mask]
    hi = upper_norm[mask]

    # ── Denormalise for RMSE / MAE ────────────────────────────────────────────
    a_raw = a * scaler_std + scaler_mean
    p_raw = p * scaler_std + scaler_mean

    mape = _mape(a_raw, p_raw)
    smape = _smape(a_raw, p_raw)
    rmse = _rmse(a_raw, p_raw)
    mae = _mae(a_raw, p_raw)
    coverage = _ci_coverage(a, lo, hi)

    return ForecastMetrics(
        mape=_safe(mape),
        smape=_safe(smape),
        rmse=_safe(rmse),
        mae=_safe(mae),
        coverage_95=_safe(coverage),
    )


# ── Metric functions ──────────────────────────────────────────────────────────

def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Percentage Error in percent.

    Zero actuals are excluded from the mean to avoid division by zero.
    Returns NaN when all actuals are zero.
    """
    nonzero = actual != 0
    if nonzero.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100)


def _smape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Symmetric Mean Absolute Percentage Error in percent."""
    denom = (np.abs(actual) + np.abs(predicted)) / 2
    nonzero = denom != 0
    if nonzero.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs(actual[nonzero] - predicted[nonzero]) / denom[nonzero]) * 100)


def _rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def _mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def _ci_coverage(
    actual: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> float:
    """Fraction of actuals that fall within [lower, upper] (95 % CI)."""
    within = ((actual >= lower) & (actual <= upper)).sum()
    return float(within / len(actual))


def _safe(v: float) -> float | None:
    """Return None for NaN / Inf so Postgres accepts the value."""
    if v is None or math.isnan(v) or math.isinf(v):
        return None
    return round(v, 6)

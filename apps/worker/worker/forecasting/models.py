"""Forecasting model implementations.

Model selection ladder (based on number of non-NaN training samples):

    <  24 samples  → LinearTrendModel     (numpy polyfit, no seasonal)
    24–47 samples  → SimpleESModel        (level-only exponential smoothing)
    48–167 samples → HoltModel            (level + trend)
    ≥ 168 samples  → HoltWintersModel     (level + trend + daily seasonality)

Each model:
  - is trained on a normalised ``pd.Series``
  - returns a ``ForecastResult`` whose ``point`` and ``lower/upper_95``
    arrays are **still in normalised space** — the pipeline denormalises
    after evaluation.
"""

from __future__ import annotations

import time
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.holtwinters import SimpleExpSmoothing

# ── Public types ──────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ForecastResult:
    """Output from any model's :py:meth:`ForecastModel.predict` call."""

    point: np.ndarray          # Shape (horizon,) — point estimates (normalised)
    lower_95: np.ndarray       # Shape (horizon,) — lower 95 % CI (normalised)
    upper_95: np.ndarray       # Shape (horizon,) — upper 95 % CI (normalised)
    model_type: str            # e.g. 'holt_winters'
    model_params: dict         # hyper-params used (for DB provenance)
    training_time_ms: int      # wall-clock training time in milliseconds
    forecast_index: pd.DatetimeIndex  # hourly timestamps for predictions


# ── Thresholds ────────────────────────────────────────────────────────────────

THRESHOLD_SIMPLE_ES: Final = 24    # min samples for SimpleES
THRESHOLD_HOLT: Final = 48         # min samples for Holt
THRESHOLD_HOLT_WINTERS: Final = 168  # min samples (≥ 7 days × 24 h)
SEASONAL_PERIOD: Final = 24        # hourly → 24 h seasonality


# ── Abstract base ─────────────────────────────────────────────────────────────

class ForecastModel(ABC):
    """Base class for all Atlas forecasting models."""

    model_type: str = ""

    @abstractmethod
    def fit(self, series: pd.Series) -> None:
        """Fit the model to *series* (normalised hourly data)."""

    @abstractmethod
    def predict(self, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (point, lower_95, upper_95) arrays of length *horizon*."""

    @abstractmethod
    def get_params(self) -> dict:
        """Return hyper-parameter dict for DB storage."""

    def train_and_forecast(
        self,
        series: pd.Series,
        horizon_hours: int,
    ) -> ForecastResult:
        """Fit, measure training time, build forecast index, return result."""
        t0 = time.perf_counter()
        self.fit(series)
        training_time_ms = int((time.perf_counter() - t0) * 1000)

        point, lower, upper = self.predict(horizon_hours)

        # Build a continuous hourly index starting 1 h after training end
        last_ts: pd.Timestamp = series.index[-1]
        forecast_index = pd.date_range(
            start=last_ts + pd.Timedelta(hours=1),
            periods=horizon_hours,
            freq="1h",
            tz="UTC",
        )

        return ForecastResult(
            point=point,
            lower_95=lower,
            upper_95=upper,
            model_type=self.model_type,
            model_params=self.get_params(),
            training_time_ms=training_time_ms,
            forecast_index=forecast_index,
        )


# ── LinearTrendModel ──────────────────────────────────────────────────────────

class LinearTrendModel(ForecastModel):
    """Ordinary-least-squares linear trend.  Used for very sparse data (< 24 pts).

    Confidence interval width grows with ``sqrt(horizon)`` using the residual
    standard deviation as the noise estimate.
    """

    model_type = "linear"

    def __init__(self) -> None:
        self._coeffs: np.ndarray | None = None   # [slope, intercept]
        self._residual_std: float = 0.0
        self._n: int = 0

    def fit(self, series: pd.Series) -> None:
        valid = series.dropna()
        x = np.arange(len(valid), dtype=float)
        y = valid.values.astype(float)
        self._coeffs = np.polyfit(x, y, deg=1)
        y_hat = np.polyval(self._coeffs, x)
        residuals = y - y_hat
        self._residual_std = float(np.std(residuals, ddof=2)) if len(residuals) > 2 else 0.0
        self._n = len(valid)

    def predict(self, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._coeffs is None:
            raise RuntimeError("Model has not been fitted yet")
        x_future = np.arange(self._n, self._n + horizon, dtype=float)
        point = np.polyval(self._coeffs, x_future)
        # CI widens as sqrt(h) — captures increasing uncertainty over time
        half_width = 1.96 * self._residual_std * np.sqrt(
            np.arange(1, horizon + 1, dtype=float)
        )
        return point, point - half_width, point + half_width

    def get_params(self) -> dict:
        if self._coeffs is None:
            return {}
        return {
            "slope": round(float(self._coeffs[0]), 6),
            "intercept": round(float(self._coeffs[1]), 6),
            "residual_std": round(self._residual_std, 6),
        }


# ── SimpleESModel ─────────────────────────────────────────────────────────────

class SimpleESModel(ForecastModel):
    """Simple (level-only) exponential smoothing.  Used for 24–47 samples."""

    model_type = "simple_es"

    def __init__(self) -> None:
        self._model_fit = None
        self._alpha: float = 0.0
        self._level: float = 0.0
        self._residual_std: float = 0.0

    def fit(self, series: pd.Series) -> None:
        valid = series.dropna()
        m = SimpleExpSmoothing(valid.values.astype(float), initialization_method="estimated")
        self._model_fit = m.fit(optimized=True)
        self._alpha = float(self._model_fit.params["smoothing_level"])
        self._level = float(self._model_fit.level[-1])
        fitted = self._model_fit.fittedvalues
        residuals = valid.values.astype(float) - fitted
        self._residual_std = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0

    def predict(self, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._model_fit is None:
            raise RuntimeError("Model has not been fitted yet")
        point = self._model_fit.forecast(horizon)
        half_width = 1.96 * self._residual_std * np.sqrt(
            np.arange(1, horizon + 1, dtype=float)
        )
        return point, point - half_width, point + half_width

    def get_params(self) -> dict:
        return {
            "alpha": round(self._alpha, 6),
            "level": round(self._level, 6),
            "residual_std": round(self._residual_std, 6),
        }


# ── HoltModel ─────────────────────────────────────────────────────────────────

class HoltModel(ForecastModel):
    """Holt's double exponential smoothing (level + trend).  48–167 samples."""

    model_type = "holt"

    def __init__(self, damped_trend: bool = True) -> None:
        self._damped_trend = damped_trend
        self._model_fit = None
        self._alpha: float = 0.0
        self._beta: float = 0.0
        self._phi: float = 1.0
        self._residual_std: float = 0.0

    def fit(self, series: pd.Series) -> None:
        valid = series.dropna()
        m = ExponentialSmoothing(
            valid.values.astype(float),
            trend="add",
            damped_trend=self._damped_trend,
            initialization_method="estimated",
        )
        self._model_fit = m.fit(optimized=True)
        p = self._model_fit.params
        self._alpha = float(p["smoothing_level"])
        self._beta = float(p["smoothing_trend"])
        self._phi = float(p.get("damping_trend", 1.0))
        fitted = self._model_fit.fittedvalues
        residuals = valid.values.astype(float) - fitted
        self._residual_std = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0

    def predict(self, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._model_fit is None:
            raise RuntimeError("Model has not been fitted yet")
        point = self._model_fit.forecast(horizon)
        half_width = 1.96 * self._residual_std * np.sqrt(
            np.arange(1, horizon + 1, dtype=float)
        )
        return point, point - half_width, point + half_width

    def get_params(self) -> dict:
        return {
            "alpha": round(self._alpha, 6),
            "beta": round(self._beta, 6),
            "phi": round(self._phi, 6),
            "damped_trend": self._damped_trend,
            "residual_std": round(self._residual_std, 6),
        }


# ── HoltWintersModel ──────────────────────────────────────────────────────────

class HoltWintersModel(ForecastModel):
    """Holt-Winters triple exponential smoothing (additive seasonal, 24 h).

    Used for ≥ 168 samples (≥ 7 full days of hourly data).
    """

    model_type = "holt_winters"

    def __init__(
        self,
        seasonal_periods: int = SEASONAL_PERIOD,
        damped_trend: bool = True,
    ) -> None:
        self._seasonal_periods = seasonal_periods
        self._damped_trend = damped_trend
        self._model_fit = None
        self._alpha: float = 0.0
        self._beta: float = 0.0
        self._gamma: float = 0.0
        self._phi: float = 1.0
        self._residual_std: float = 0.0

    def fit(self, series: pd.Series) -> None:
        valid = series.dropna()
        # Need at least 2 full seasons to estimate seasonal component
        if len(valid) <= 2 * self._seasonal_periods:
            # Fall back to Holt if insufficient for Holt-Winters
            fallback = HoltModel(damped_trend=self._damped_trend)
            fallback.fit(series)
            self._model_fit = fallback._model_fit
            self.model_type = "holt"          # update provenance
            self._alpha = fallback._alpha
            self._beta = fallback._beta
            self._phi = fallback._phi
            self._residual_std = fallback._residual_std
            return

        m = ExponentialSmoothing(
            valid.values.astype(float),
            trend="add",
            damped_trend=self._damped_trend,
            seasonal="add",
            seasonal_periods=self._seasonal_periods,
            initialization_method="estimated",
        )
        self._model_fit = m.fit(optimized=True)
        p = self._model_fit.params
        self._alpha = float(p["smoothing_level"])
        self._beta = float(p["smoothing_trend"])
        self._gamma = float(p["smoothing_seasonal"])
        self._phi = float(p.get("damping_trend", 1.0))
        fitted = self._model_fit.fittedvalues
        residuals = valid.values.astype(float) - fitted
        self._residual_std = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0

    def predict(self, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self._model_fit is None:
            raise RuntimeError("Model has not been fitted yet")
        point = self._model_fit.forecast(horizon)
        half_width = 1.96 * self._residual_std * np.sqrt(
            np.arange(1, horizon + 1, dtype=float)
        )
        return point, point - half_width, point + half_width

    def get_params(self) -> dict:
        return {
            "alpha": round(self._alpha, 6),
            "beta": round(self._beta, 6),
            "gamma": round(self._gamma, 6),
            "phi": round(self._phi, 6),
            "seasonal_periods": self._seasonal_periods,
            "damped_trend": self._damped_trend,
            "residual_std": round(self._residual_std, 6),
        }


# ── Model selection ───────────────────────────────────────────────────────────

def select_model(n_samples: int) -> ForecastModel:
    """Return the appropriate model class instance for *n_samples* data points.

    Selection ladder
    ~~~~~~~~~~~~~~~~
    <  24   LinearTrendModel     — too sparse for smoothing
    24–47   SimpleESModel        — level only (no trend/seasonal)
    48–167  HoltModel            — level + damped trend
    ≥ 168   HoltWintersModel     — level + damped trend + 24 h seasonal
    """
    if n_samples < THRESHOLD_SIMPLE_ES:
        return LinearTrendModel()
    if n_samples < THRESHOLD_HOLT:
        return SimpleESModel()
    if n_samples < THRESHOLD_HOLT_WINTERS:
        return HoltModel(damped_trend=True)
    return HoltWintersModel(seasonal_periods=SEASONAL_PERIOD, damped_trend=True)

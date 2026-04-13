"""Time-series preprocessor for the forecasting pipeline.

Responsibilities
----------------
1. Ingest raw (timestamp, value) rows from the database.
2. Build a ``pd.Series`` with a continuous hourly ``DatetimeIndex``.
3. Fill short gaps (≤ 3 h forward-fill, ≤ 6 h linear interpolation).
4. Remove extreme outliers via IQR clipping.
5. Z-score normalise and return scaler parameters for later inversion.
6. Cap at ``max_samples`` to stay under the 500 ms training budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Sequence

import numpy as np
import pandas as pd

# ── Public types ──────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ScalerParams:
    """Parameters for z-score normalisation / denormalisation."""

    mean: float
    std: float

    def denormalise(self, arr: np.ndarray) -> np.ndarray:
        """Invert z-score: value = z * std + mean."""
        if self.std == 0.0:
            return np.full_like(arr, self.mean, dtype=float)
        return arr * self.std + self.mean

    def denormalise_std(self, arr: np.ndarray) -> np.ndarray:
        """Denormalise a standard-deviation / error term (no mean shift)."""
        return arr * abs(self.std)


@dataclass(slots=True)
class PreprocessResult:
    """Output from :func:`preprocess`."""

    series: pd.Series          # Normalised hourly series, DatetimeIndex UTC
    raw_series: pd.Series      # Clipped (non-normalised) hourly series
    scaler: ScalerParams
    n_original: int            # Number of raw rows supplied
    n_filled: int              # Data points added by gap-filling
    n_clipped: int             # Outliers clipped by IQR
    n_samples: int             # Final length (≤ max_samples)
    training_start: datetime
    training_end: datetime
    is_sparse: bool            # True when < 24 non-NaN points after filling


# ── Constants ─────────────────────────────────────────────────────────────────

_FFILL_LIMIT_H = 3     # forward-fill up to 3 consecutive missing hours
_INTERP_LIMIT_H = 6    # linear interpolation up to 6 consecutive missing hours
_IQR_FACTOR = 3.0      # clip beyond Q1 − k*IQR … Q3 + k*IQR
_MIN_NON_NULL = 2      # need at least 2 real points to do anything sensible


# ── Public API ────────────────────────────────────────────────────────────────

def preprocess(
    rows: Sequence[tuple[datetime, float]],
    *,
    max_samples: int = 500,
    iqr_factor: float = _IQR_FACTOR,
    ffill_limit: int = _FFILL_LIMIT_H,
    interp_limit: int = _INTERP_LIMIT_H,
) -> PreprocessResult:
    """Preprocess raw metric rows into a normalised hourly series.

    Parameters
    ----------
    rows:
        Sequence of ``(timestamp, value)`` tuples as returned from the DB.
        Timestamps may be tz-aware or tz-naive (treated as UTC if naive).
    max_samples:
        Hard cap on the returned series length.  Older data is discarded first.
    iqr_factor:
        Multiplier for the IQR-based clipping fence.
    ffill_limit:
        Maximum consecutive NaN hours to fill via forward-fill.
    interp_limit:
        Maximum consecutive NaN hours to fill via linear interpolation after
        forward-fill.  Applied to any remaining NaNs (including backward-fill).

    Returns
    -------
    PreprocessResult
    """
    if not rows:
        raise ValueError("preprocess() received an empty row sequence")

    # ── 1. Build initial series ───────────────────────────────────────────────
    raw = _rows_to_series(rows)
    n_original = int(raw.notna().sum())

    if n_original < _MIN_NON_NULL:
        raise ValueError(
            f"Insufficient non-null data points: {n_original} < {_MIN_NON_NULL}"
        )

    # ── 2. Resample to hourly grid ────────────────────────────────────────────
    hourly = raw.resample("1h").mean()          # aggregates sub-hour duplicates

    # ── 3. Gap-filling ────────────────────────────────────────────────────────
    before_fill = int(hourly.notna().sum())

    # 3a. Forward-fill short gaps
    hourly = hourly.ffill(limit=ffill_limit)

    # 3b. Linear interpolation for remaining medium gaps
    hourly = hourly.interpolate(method="linear", limit=interp_limit, limit_area="inside")

    after_fill = int(hourly.notna().sum())
    n_filled = after_fill - before_fill

    # ── 4. Outlier clipping (IQR) ─────────────────────────────────────────────
    non_null = hourly.dropna()
    q1 = float(non_null.quantile(0.25))
    q3 = float(non_null.quantile(0.75))
    iqr = q3 - q1

    if iqr > 0:
        lower = q1 - iqr_factor * iqr
        upper = q3 + iqr_factor * iqr
        before_clip = hourly.copy()
        hourly = hourly.clip(lower=lower, upper=upper)
        n_clipped = int((hourly != before_clip).sum())
    else:
        n_clipped = 0

    raw_series = hourly.copy()

    # ── 5. Subsample to max_samples (drop oldest) ─────────────────────────────
    if len(hourly) > max_samples:
        hourly = hourly.iloc[-max_samples:]

    # ── 6. Z-score normalisation ──────────────────────────────────────────────
    valid = hourly.dropna()
    mu = float(valid.mean())
    sigma = float(valid.std(ddof=1)) if len(valid) > 1 else 0.0

    if sigma == 0.0 or math.isnan(sigma):
        normalised = hourly - mu          # constant series: centre at zero
        sigma = 1.0                       # safe divisor for later inversion
    else:
        normalised = (hourly - mu) / sigma

    # ── 7. Metadata ───────────────────────────────────────────────────────────
    training_start: datetime = hourly.index[0].to_pydatetime().replace(tzinfo=timezone.utc)
    training_end: datetime = hourly.index[-1].to_pydatetime().replace(tzinfo=timezone.utc)
    is_sparse = int(normalised.notna().sum()) < 24

    return PreprocessResult(
        series=normalised,
        raw_series=raw_series.iloc[-max_samples:] if len(raw_series) > max_samples else raw_series,
        scaler=ScalerParams(mean=mu, std=sigma),
        n_original=n_original,
        n_filled=n_filled,
        n_clipped=n_clipped,
        n_samples=len(normalised),
        training_start=training_start,
        training_end=training_end,
        is_sparse=is_sparse,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _rows_to_series(rows: Sequence[tuple[datetime, float]]) -> pd.Series:
    """Convert raw DB rows to a ``pd.Series`` with UTC ``DatetimeIndex``."""
    timestamps: list[pd.Timestamp] = []
    values: list[float] = []

    for ts, val in rows:
        pt = pd.Timestamp(ts)
        if pt.tzinfo is None:
            pt = pt.tz_localize("UTC")
        else:
            pt = pt.tz_convert("UTC")

        try:
            v = float(val)
        except (TypeError, ValueError):
            v = float("nan")

        timestamps.append(pt)
        values.append(v)

    idx = pd.DatetimeIndex(timestamps, tz="UTC")
    return pd.Series(values, index=idx, dtype=float, name="value").sort_index()

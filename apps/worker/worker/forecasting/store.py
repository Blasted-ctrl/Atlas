"""Persist and retrieve forecast records in Postgres.

Uses the ``resource_forecasts`` table created by migration 006.  The
``UNIQUE (resource_id, metric)`` constraint means every upsert replaces the
previous forecast in-place — no stale rows accumulate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from psycopg2.extras import RealDictRow

from worker.db import get_cursor

# ── Public types ──────────────────────────────────────────────────────────────

@dataclass
class StoredForecast:
    """A row returned by :func:`get_forecast`."""

    id: UUID
    resource_id: UUID
    metric: str
    model_type: str
    model_params: dict
    generated_at: datetime
    training_start: datetime
    training_end: datetime
    forecast_start: datetime
    forecast_end: datetime
    horizon_days: int
    training_samples: int
    training_time_ms: int
    mape: float | None
    smape: float | None
    rmse: float | None
    mae: float | None
    coverage_95: float | None
    predictions: list[dict]

    @classmethod
    def from_row(cls, row: RealDictRow) -> "StoredForecast":
        def _uuid(v: Any) -> UUID:
            return v if isinstance(v, UUID) else UUID(str(v))

        def _dt(v: Any) -> datetime:
            if isinstance(v, datetime):
                return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
            return datetime.fromisoformat(str(v)).replace(tzinfo=timezone.utc)

        predictions = row["predictions"]
        if isinstance(predictions, str):
            predictions = json.loads(predictions)

        return cls(
            id=_uuid(row["id"]),
            resource_id=_uuid(row["resource_id"]),
            metric=row["metric"],
            model_type=row["model_type"],
            model_params=row["model_params"] if isinstance(row["model_params"], dict) else json.loads(row["model_params"]),
            generated_at=_dt(row["generated_at"]),
            training_start=_dt(row["training_start"]),
            training_end=_dt(row["training_end"]),
            forecast_start=_dt(row["forecast_start"]),
            forecast_end=_dt(row["forecast_end"]),
            horizon_days=int(row["horizon_days"]),
            training_samples=int(row["training_samples"]),
            training_time_ms=int(row["training_time_ms"]),
            mape=row["mape"],
            smape=row["smape"],
            rmse=row["rmse"],
            mae=row["mae"],
            coverage_95=row["coverage_95"],
            predictions=predictions,
        )


# ── Write ─────────────────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO resource_forecasts (
    resource_id,
    metric,
    model_type,
    model_params,
    generated_at,
    training_start,
    training_end,
    forecast_start,
    forecast_end,
    horizon_days,
    training_samples,
    training_time_ms,
    mape,
    smape,
    rmse,
    mae,
    coverage_95,
    predictions
)
VALUES (
    %(resource_id)s,
    %(metric)s,
    %(model_type)s,
    %(model_params)s,
    %(generated_at)s,
    %(training_start)s,
    %(training_end)s,
    %(forecast_start)s,
    %(forecast_end)s,
    %(horizon_days)s,
    %(training_samples)s,
    %(training_time_ms)s,
    %(mape)s,
    %(smape)s,
    %(rmse)s,
    %(mae)s,
    %(coverage_95)s,
    %(predictions)s
)
ON CONFLICT ON CONSTRAINT uq_forecast_resource_metric
DO UPDATE SET
    model_type        = EXCLUDED.model_type,
    model_params      = EXCLUDED.model_params,
    generated_at      = EXCLUDED.generated_at,
    training_start    = EXCLUDED.training_start,
    training_end      = EXCLUDED.training_end,
    forecast_start    = EXCLUDED.forecast_start,
    forecast_end      = EXCLUDED.forecast_end,
    horizon_days      = EXCLUDED.horizon_days,
    training_samples  = EXCLUDED.training_samples,
    training_time_ms  = EXCLUDED.training_time_ms,
    mape              = EXCLUDED.mape,
    smape             = EXCLUDED.smape,
    rmse              = EXCLUDED.rmse,
    mae               = EXCLUDED.mae,
    coverage_95       = EXCLUDED.coverage_95,
    predictions       = EXCLUDED.predictions
RETURNING id
"""


def save_forecast(
    *,
    resource_id: str | UUID,
    metric: str,
    model_type: str,
    model_params: dict,
    training_start: datetime,
    training_end: datetime,
    forecast_start: datetime,
    forecast_end: datetime,
    horizon_days: int,
    training_samples: int,
    training_time_ms: int,
    mape: float | None,
    smape: float | None,
    rmse: float | None,
    mae: float | None,
    coverage_95: float | None,
    predictions: list[dict],
) -> UUID:
    """Upsert a forecast row and return its UUID.

    The ``UNIQUE (resource_id, metric)`` constraint ensures only one active
    forecast exists per (resource, metric) pair; old data is replaced in-place.
    """
    params = {
        "resource_id": str(resource_id),
        "metric": metric,
        "model_type": model_type,
        "model_params": json.dumps(model_params),
        "generated_at": datetime.now(tz=timezone.utc),
        "training_start": training_start,
        "training_end": training_end,
        "forecast_start": forecast_start,
        "forecast_end": forecast_end,
        "horizon_days": horizon_days,
        "training_samples": training_samples,
        "training_time_ms": training_time_ms,
        "mape": mape,
        "smape": smape,
        "rmse": rmse,
        "mae": mae,
        "coverage_95": coverage_95,
        "predictions": json.dumps(predictions),
    }

    with get_cursor() as cur:
        cur.execute(_UPSERT_SQL, params)
        row = cur.fetchone()

    return UUID(str(row["id"]))


# ── Read ──────────────────────────────────────────────────────────────────────

_SELECT_SQL = """
SELECT
    id, resource_id, metric, model_type, model_params,
    generated_at, training_start, training_end,
    forecast_start, forecast_end, horizon_days,
    training_samples, training_time_ms,
    mape, smape, rmse, mae, coverage_95,
    predictions
FROM resource_forecasts
WHERE resource_id = %(resource_id)s
  AND metric = %(metric)s
"""


def get_forecast(resource_id: str | UUID, metric: str) -> StoredForecast | None:
    """Return the active forecast for *(resource_id, metric)* or ``None``."""
    with get_cursor() as cur:
        cur.execute(_SELECT_SQL, {"resource_id": str(resource_id), "metric": metric})
        row = cur.fetchone()

    if row is None:
        return None
    return StoredForecast.from_row(row)


_SELECT_RESOURCE_SQL = """
SELECT
    id, resource_id, metric, model_type, model_params,
    generated_at, training_start, training_end,
    forecast_start, forecast_end, horizon_days,
    training_samples, training_time_ms,
    mape, smape, rmse, mae, coverage_95,
    predictions
FROM resource_forecasts
WHERE resource_id = %(resource_id)s
ORDER BY metric
"""


def get_forecasts_for_resource(resource_id: str | UUID) -> list[StoredForecast]:
    """Return all metric forecasts for a given resource."""
    with get_cursor() as cur:
        cur.execute(_SELECT_RESOURCE_SQL, {"resource_id": str(resource_id)})
        rows = cur.fetchall()

    return [StoredForecast.from_row(r) for r in rows]


# ── Fetch raw usage data ──────────────────────────────────────────────────────

_FETCH_USAGE_SQL = """
SELECT ts, value
FROM usage_metrics
WHERE resource_id = %(resource_id)s
  AND metric = %(metric)s
  AND granularity = '1h'
  AND ts >= NOW() - %(lookback)s::INTERVAL
ORDER BY ts ASC
"""


def fetch_usage_rows(
    resource_id: str | UUID,
    metric: str,
    *,
    lookback_days: int = 90,
) -> list[tuple[datetime, float]]:
    """Fetch hourly usage time-series rows from the DB for a resource/metric.

    Returns a list of ``(ts, value)`` tuples sorted ascending by time.
    Partition pruning is guaranteed because the ``ts >= NOW() - INTERVAL``
    predicate is always present.
    """
    with get_cursor() as cur:
        cur.execute(
            _FETCH_USAGE_SQL,
            {
                "resource_id": str(resource_id),
                "metric": metric,
                "lookback": f"{lookback_days} days",
            },
        )
        rows = cur.fetchall()

    return [(row["ts"], float(row["value"])) for row in rows]

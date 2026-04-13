-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 006 — Resource Forecasts
-- ─────────────────────────────────────────────────────────────────────────────
-- Stores 30-day ahead cost/utilisation forecasts produced by the forecasting
-- pipeline.  Each row is the latest forecast for a (resource, metric) pair.
-- Older forecasts are replaced in-place via ON CONFLICT DO UPDATE.
--
-- Predictions are stored as a JSONB array of datapoints:
--   [{"date": "2024-04-01", "value": 4521.3,
--     "lower_95": 4200.0, "upper_95": 4800.0}, ...]
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE resource_forecasts (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scope
    resource_id         UUID            NOT NULL
                            REFERENCES resources(id) ON DELETE CASCADE,
    metric              metric_name     NOT NULL,

    -- Model provenance
    model_type          TEXT            NOT NULL,       -- 'linear' | 'simple_es' | 'holt' | 'holt_winters'
    model_params        JSONB           NOT NULL DEFAULT '{}',

    -- Temporal scope
    generated_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    training_start      TIMESTAMPTZ     NOT NULL,       -- first ts in training window
    training_end        TIMESTAMPTZ     NOT NULL,       -- last ts in training window
    forecast_start      TIMESTAMPTZ     NOT NULL,       -- first predicted ts
    forecast_end        TIMESTAMPTZ     NOT NULL,       -- last predicted ts (30d out)
    horizon_days        INTEGER         NOT NULL DEFAULT 30,

    -- Training provenance
    training_samples    INTEGER         NOT NULL,
    training_time_ms    INTEGER         NOT NULL,       -- wall-clock ms

    -- Evaluation metrics (computed on holdout set; NULL if < 24 samples)
    mape                DOUBLE PRECISION,               -- Mean Absolute Percentage Error (%)
    smape               DOUBLE PRECISION,               -- Symmetric MAPE (%)
    rmse                DOUBLE PRECISION,               -- Root Mean Squared Error (raw units)
    mae                 DOUBLE PRECISION,               -- Mean Absolute Error
    coverage_95         DOUBLE PRECISION,               -- % of holdout within 95 % CI

    -- Forecast output
    predictions         JSONB           NOT NULL,

    -- Audit
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- One active forecast per (resource, metric) — upsert replaces in-place
    CONSTRAINT uq_forecast_resource_metric UNIQUE (resource_id, metric)
);

COMMENT ON TABLE  resource_forecasts               IS '30-day utilisation/cost forecasts per resource and metric.';
COMMENT ON COLUMN resource_forecasts.model_type    IS 'linear | simple_es | holt | holt_winters — chosen by pipeline based on data density.';
COMMENT ON COLUMN resource_forecasts.mape          IS 'Mean Absolute Percentage Error on holdout (lower = better). NULL when holdout was too small.';
COMMENT ON COLUMN resource_forecasts.coverage_95   IS 'Fraction of holdout actuals that fall within the forecast 95% CI.';
COMMENT ON COLUMN resource_forecasts.predictions   IS 'JSON array: [{date, value, lower_95, upper_95}]. Date is ISO-8601.';

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Primary lookup: all forecasts for a resource
CREATE INDEX idx_forecast_resource_id
    ON resource_forecasts (resource_id, generated_at DESC);

-- Stale-forecast sweep (forecasts generated > N hours ago)
CREATE INDEX idx_forecast_generated_at
    ON resource_forecasts (generated_at DESC);

-- Find recently-evaluated forecasts with poor accuracy
CREATE INDEX idx_forecast_mape
    ON resource_forecasts (mape ASC)
    WHERE mape IS NOT NULL;


INSERT INTO schema_migrations (version, name)
VALUES (6, '006_forecasts');

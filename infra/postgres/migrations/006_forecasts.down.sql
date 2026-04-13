-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 006 — Rollback
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM schema_migrations WHERE version = 6;

DROP INDEX IF EXISTS idx_forecast_mape;
DROP INDEX IF EXISTS idx_forecast_generated_at;
DROP INDEX IF EXISTS idx_forecast_resource_id;
DROP TABLE IF EXISTS resource_forecasts CASCADE;

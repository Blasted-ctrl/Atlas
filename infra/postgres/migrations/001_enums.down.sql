-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 001 — Rollback
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM schema_migrations WHERE version = 1;

DROP TYPE IF EXISTS optimization_job_status;
DROP TYPE IF EXISTS recommendation_status;
DROP TYPE IF EXISTS recommendation_type;
DROP TYPE IF EXISTS metric_granularity;
DROP TYPE IF EXISTS metric_name;
DROP TYPE IF EXISTS resource_status;
DROP TYPE IF EXISTS resource_type;
DROP TYPE IF EXISTS cloud_provider;

DROP TABLE IF EXISTS schema_migrations;

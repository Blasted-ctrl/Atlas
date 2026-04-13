-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 003 — Rollback
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM schema_migrations WHERE version = 3;

DROP VIEW     IF EXISTS usage_metrics_partitions;
DROP FUNCTION IF EXISTS create_usage_metric_partitions(DATE, DATE);

-- Individual partitions are dropped as part of DROP TABLE usage_metrics CASCADE
-- in 002_tables.down.sql.  No need to enumerate them here.

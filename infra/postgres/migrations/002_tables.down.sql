-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 002 — Rollback
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM schema_migrations WHERE version = 2;

-- Drop in reverse dependency order.
-- usage_metrics CASCADE drops all daily partitions automatically.
DROP TABLE IF EXISTS usage_metrics        CASCADE;
DROP TABLE IF EXISTS recommendations      CASCADE;
DROP TABLE IF EXISTS optimization_runs    CASCADE;
DROP TABLE IF EXISTS resources            CASCADE;

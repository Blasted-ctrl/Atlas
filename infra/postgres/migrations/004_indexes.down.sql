-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 004 — Rollback
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM schema_migrations WHERE version = 4;

-- optimization_runs
DROP INDEX CONCURRENTLY IF EXISTS idx_runs_created_at;
DROP INDEX CONCURRENTLY IF EXISTS idx_runs_status_created;

-- recommendations
DROP INDEX CONCURRENTLY IF EXISTS idx_rec_expires_at;
DROP INDEX CONCURRENTLY IF EXISTS idx_rec_status_type;
DROP INDEX CONCURRENTLY IF EXISTS idx_rec_savings_desc;
DROP INDEX CONCURRENTLY IF EXISTS idx_rec_resource_pending;
DROP INDEX CONCURRENTLY IF EXISTS idx_rec_run_id;
DROP INDEX CONCURRENTLY IF EXISTS idx_rec_resource_id;

-- usage_metrics
DROP INDEX CONCURRENTLY IF EXISTS idx_usage_ts;
DROP INDEX CONCURRENTLY IF EXISTS idx_usage_resource_metric_gran_ts;
DROP INDEX CONCURRENTLY IF EXISTS idx_usage_metric_ts;
DROP INDEX CONCURRENTLY IF EXISTS idx_usage_resource_ts;

-- resources
DROP INDEX CONCURRENTLY IF EXISTS idx_resources_name_trgm;
DROP INDEX CONCURRENTLY IF EXISTS idx_resources_tags_gin;
DROP INDEX CONCURRENTLY IF EXISTS idx_resources_last_seen;
DROP INDEX CONCURRENTLY IF EXISTS idx_resources_account_region;
DROP INDEX CONCURRENTLY IF EXISTS idx_resources_type_status;
DROP INDEX CONCURRENTLY IF EXISTS idx_resources_cost_desc;
DROP INDEX CONCURRENTLY IF EXISTS idx_resources_external_id;

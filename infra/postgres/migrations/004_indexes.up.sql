-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 004 — Indexes
-- ─────────────────────────────────────────────────────────────────────────────
-- Index strategy:
--   • Every FK column gets a plain B-tree index (prevents sequential scans
--     on the referencing side during FK checks and JOINs).
--   • High-cardinality filter columns get B-tree or composite indexes sized
--     to the most common query shapes.
--   • JSONB columns that are searched by key/value get GIN indexes.
--   • All indexes are created CONCURRENTLY (safe on live databases) and are
--     partial where the filter excludes deleted/inactive rows.
--
-- Note: usage_metrics is partitioned — indexes created on the parent table
-- propagate automatically to all current and future partitions (Postgres 11+).
-- ─────────────────────────────────────────────────────────────────────────────

-- ═══════════════════════════════════════════════════════════════════════════════
-- resources
-- ═══════════════════════════════════════════════════════════════════════════════

-- Lookup by cloud-native ID (used by sync pipeline)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resources_external_id
    ON resources (provider, account_id, external_id)
    WHERE deleted_at IS NULL;

-- Cost sorting — most common dashboard sort
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resources_cost_desc
    ON resources (monthly_cost_usd DESC)
    WHERE deleted_at IS NULL;

-- Type + status filtering (resource list endpoint)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resources_type_status
    ON resources (type, status)
    WHERE deleted_at IS NULL;

-- Account + region filtering (most recommendation queries scope here)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resources_account_region
    ON resources (account_id, region)
    WHERE deleted_at IS NULL;

-- last_seen_at — detect stale resources (sync monitoring)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resources_last_seen
    ON resources (last_seen_at DESC)
    WHERE deleted_at IS NULL;

-- GIN on tags for arbitrary tag queries: WHERE tags @> '{"Env":"prod"}'
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resources_tags_gin
    ON resources USING GIN (tags)
    WHERE deleted_at IS NULL;

-- GIN on specs (optional — enable if specs are searched often)
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resources_specs_gin
--     ON resources USING GIN (specs);

-- Trigram index on name for ILIKE-based search
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_resources_name_trgm
    ON resources USING GIN (name gin_trgm_ops)
    WHERE deleted_at IS NULL AND name IS NOT NULL;


-- ═══════════════════════════════════════════════════════════════════════════════
-- usage_metrics
-- ═══════════════════════════════════════════════════════════════════════════════
-- These indexes are created on the parent table and automatically replicated
-- to all existing and future child partitions.

-- Primary access: all metrics for a resource over a time range
-- Covers: WHERE resource_id = $1 AND ts BETWEEN $2 AND $3
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_usage_resource_ts
    ON usage_metrics (resource_id, ts DESC);

-- Metric + time filtering (cross-resource metric queries)
-- Covers: WHERE metric = $1 AND ts BETWEEN $2 AND $3
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_usage_metric_ts
    ON usage_metrics (metric, ts DESC);

-- Resource + metric + granularity (for deduplication / upsert lookups)
-- Matches the unique constraint key
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_usage_resource_metric_gran_ts
    ON usage_metrics (resource_id, metric, granularity, ts DESC);

-- Pure time-range scans (global cost-over-time queries)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_usage_ts
    ON usage_metrics (ts DESC);


-- ═══════════════════════════════════════════════════════════════════════════════
-- recommendations
-- ═══════════════════════════════════════════════════════════════════════════════

-- FK index — prevents seq-scan when checking referential integrity
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rec_resource_id
    ON recommendations (resource_id)
    WHERE deleted_at IS NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rec_run_id
    ON recommendations (optimization_run_id)
    WHERE deleted_at IS NULL AND optimization_run_id IS NOT NULL;

-- Pending recommendations for a resource (widget / API default view)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rec_resource_pending
    ON recommendations (resource_id, savings_usd_monthly DESC)
    WHERE status = 'pending' AND deleted_at IS NULL;

-- Top savings across all resources (dashboard aggregate)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rec_savings_desc
    ON recommendations (savings_usd_monthly DESC, confidence DESC)
    WHERE status = 'pending' AND deleted_at IS NULL;

-- Status + type filtering
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rec_status_type
    ON recommendations (status, type)
    WHERE deleted_at IS NULL;

-- Expiry sweep job
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rec_expires_at
    ON recommendations (expires_at)
    WHERE status = 'pending' AND deleted_at IS NULL;


-- ═══════════════════════════════════════════════════════════════════════════════
-- optimization_runs
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_runs_status_created
    ON optimization_runs (status, created_at DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_runs_created_at
    ON optimization_runs (created_at DESC);


INSERT INTO schema_migrations (version, name)
VALUES (4, '004_indexes');

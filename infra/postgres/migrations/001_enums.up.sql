-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 001 — Enums & Schema Version Tracking
-- ─────────────────────────────────────────────────────────────────────────────

-- Schema migration registry (used by our own migration runner or Flyway / golang-migrate)
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     BIGINT       PRIMARY KEY,
    name        TEXT         NOT NULL,
    applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    checksum    TEXT                                  -- SHA-256 of the migration file
);

-- ── Cloud Provider ────────────────────────────────────────────────────────────
CREATE TYPE cloud_provider AS ENUM (
    'aws',
    'gcp',
    'azure'
);

-- ── Resource ──────────────────────────────────────────────────────────────────
CREATE TYPE resource_type AS ENUM (
    'ec2_instance',
    'rds_instance',
    'rds_cluster',
    'elasticache_cluster',
    'lambda_function',
    's3_bucket',
    'eks_node_group',
    'elb',
    'ebs_volume',
    'cloudfront_distribution',
    'nat_gateway'
);

CREATE TYPE resource_status AS ENUM (
    'running',
    'stopped',
    'terminated',
    'pending',
    'unknown'
);

-- ── Usage / Metrics ───────────────────────────────────────────────────────────
CREATE TYPE metric_name AS ENUM (
    'cpu_utilization',
    'memory_utilization',
    'network_in_bytes',
    'network_out_bytes',
    'disk_read_ops',
    'disk_write_ops',
    'connections',
    'request_count',
    'error_rate'
);

CREATE TYPE metric_granularity AS ENUM (
    '1m',
    '5m',
    '15m',
    '1h',
    '6h',
    '1d'
);

-- ── Recommendations ───────────────────────────────────────────────────────────
CREATE TYPE recommendation_type AS ENUM (
    'resize_down',
    'resize_up',
    'terminate',
    'schedule',
    'reserved_instance',
    'savings_plan',
    'graviton_migration'
);

CREATE TYPE recommendation_status AS ENUM (
    'pending',
    'accepted',
    'rejected',
    'applied',
    'dismissed',
    'expired'
);

-- ── Optimization Jobs ─────────────────────────────────────────────────────────
CREATE TYPE optimization_job_status AS ENUM (
    'queued',
    'running',
    'completed',
    'failed'
);

INSERT INTO schema_migrations (version, name)
VALUES (1, '001_enums');

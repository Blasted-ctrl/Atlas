-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 002 — Core Tables
-- ─────────────────────────────────────────────────────────────────────────────

-- ── resources ────────────────────────────────────────────────────────────────
--
-- Central inventory of cloud resources across all providers/accounts.
-- Soft-deleted via deleted_at; all application queries should filter
-- WHERE deleted_at IS NULL.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE resources (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Cloud-provider identity
    external_id         TEXT            NOT NULL,        -- e.g. "i-0abc123def456789a"
    name                TEXT,                            -- from tags or provider metadata
    type                resource_type   NOT NULL,
    provider            cloud_provider  NOT NULL,
    account_id          TEXT            NOT NULL,        -- AWS account ID / GCP project / Azure sub
    region              TEXT            NOT NULL,        -- e.g. "us-east-1"
    availability_zone   TEXT,

    -- State
    status              resource_status NOT NULL DEFAULT 'unknown',
    instance_type       TEXT,                            -- e.g. "m5.xlarge"; null for non-compute

    -- Flexible metadata (avoids ALTER TABLE for every new provider field)
    tags                JSONB           NOT NULL DEFAULT '{}',
    specs               JSONB           NOT NULL DEFAULT '{}',  -- vcpus, memory_gib, etc.
    network             JSONB           NOT NULL DEFAULT '{}',  -- vpc_id, subnet_id, ips

    -- Cost (updated on each sync from cost explorer / billing API)
    monthly_cost_usd    NUMERIC(12, 4)  NOT NULL DEFAULT 0,

    -- Audit / soft-delete
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,                     -- NULL = active; non-NULL = soft-deleted
    last_seen_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Uniqueness: one live record per cloud resource
    CONSTRAINT uq_resources_provider_account_external
        UNIQUE (provider, account_id, external_id)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE  resources                 IS 'Cloud resource inventory (EC2, RDS, Lambda, …).';
COMMENT ON COLUMN resources.external_id     IS 'Provider-native resource ID.';
COMMENT ON COLUMN resources.tags            IS 'Key-value tags; searchable via GIN index.';
COMMENT ON COLUMN resources.specs           IS 'Provider-specific hardware specs (arbitrary JSON).';
COMMENT ON COLUMN resources.deleted_at      IS 'Non-NULL = soft-deleted. Never hard-delete rows.';
COMMENT ON COLUMN resources.last_seen_at    IS 'Set to NOW() on every cloud-sync sweep.';


-- ── optimization_runs ────────────────────────────────────────────────────────
--
-- Tracks each async optimization analysis job. Recommendations belong to
-- the run that generated them, enabling retracing.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE optimization_runs (
    id                          UUID                    PRIMARY KEY DEFAULT gen_random_uuid(),
    status                      optimization_job_status NOT NULL DEFAULT 'queued',

    -- Scope (matches TriggerOptimizationInput from API)
    scope                       JSONB                   NOT NULL DEFAULT '{}',
    options                     JSONB                   NOT NULL DEFAULT '{}',

    -- Lifecycle timestamps
    started_at                  TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,

    -- Outcome
    recommendations_generated   INTEGER                 NOT NULL DEFAULT 0,
    resources_analyzed          INTEGER                 NOT NULL DEFAULT 0,
    total_savings_found_usd     NUMERIC(14, 4)          NOT NULL DEFAULT 0,
    error_message               TEXT,

    -- Audit
    created_at                  TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ             NOT NULL DEFAULT NOW(),

    -- A run that hasn't updated in 2 h is probably stale (application enforces this)
    CONSTRAINT chk_run_times CHECK (
        started_at IS NULL
        OR completed_at IS NULL
        OR completed_at >= started_at
    )
);

COMMENT ON TABLE optimization_runs IS 'Async optimization analysis jobs.';


-- ── recommendations ───────────────────────────────────────────────────────────
--
-- One recommendation per (resource, type) pair per optimization run.
-- Multiple pending recommendations for the same resource are allowed when
-- they cover different action types (e.g. resize + reserved_instance).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE recommendations (
    id                  UUID                    PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Relationships
    resource_id         UUID                    NOT NULL
                            REFERENCES resources(id) ON DELETE RESTRICT,
    optimization_run_id UUID
                            REFERENCES optimization_runs(id) ON DELETE SET NULL,

    -- Classification
    type                recommendation_type     NOT NULL,
    status              recommendation_status   NOT NULL DEFAULT 'pending',

    -- Human-readable content
    title               TEXT                    NOT NULL,
    description         TEXT                    NOT NULL DEFAULT '',

    -- Financials
    savings_usd_monthly NUMERIC(12, 4)          NOT NULL DEFAULT 0,
    savings_usd_annual  NUMERIC(14, 4)          NOT NULL GENERATED ALWAYS AS
                            (savings_usd_monthly * 12) STORED,

    -- Model output
    confidence          DOUBLE PRECISION        NOT NULL
                            CHECK (confidence BETWEEN 0.0 AND 1.0),
    details             JSONB                   NOT NULL DEFAULT '{}',

    -- Lifecycle
    expires_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW() + INTERVAL '30 days',
    applied_at          TIMESTAMPTZ,
    dismissed_at        TIMESTAMPTZ,
    rejection_reason    TEXT,

    -- Audit / soft-delete
    created_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,

    CONSTRAINT chk_rec_savings_nonneg CHECK (savings_usd_monthly >= 0),
    CONSTRAINT chk_rec_expires_future CHECK (expires_at > created_at)
);

COMMENT ON TABLE  recommendations                   IS 'Cost optimization recommendations per resource.';
COMMENT ON COLUMN recommendations.savings_usd_annual IS 'Generated column: savings_usd_monthly × 12.';
COMMENT ON COLUMN recommendations.confidence         IS 'Model confidence score [0.0, 1.0].';
COMMENT ON COLUMN recommendations.details            IS 'Recommendation-specific payload (resize params, schedule crons, etc.).';


-- ── usage_metrics — PARTITIONED PARENT ───────────────────────────────────────
--
-- High-volume time-series table. Partitioned by DAY on `ts` so that:
--   • Queries with time-range filters prune irrelevant partitions.
--   • Old data can be dropped by dropping its partition (O(1) vs DELETE).
--   • Vacuum works per-partition, minimising bloat on the hot partition.
--
-- Child partitions are named usage_metrics_YYYYMMDD and created either by
-- the create_usage_metric_partitions() helper or an external scheduler
-- (pg_partman, Kubernetes CronJob, etc.).
--
-- NOTE: This table has NO primary key on the parent — each partition defines
-- its own unique constraint on (resource_id, metric, granularity, ts).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE usage_metrics (
    -- Identity (bigint is more compact than UUID for 1 B+ rows)
    id              BIGSERIAL,

    -- The resource this measurement belongs to
    resource_id     UUID                NOT NULL
                        REFERENCES resources(id) ON DELETE CASCADE,

    -- What was measured
    metric          metric_name         NOT NULL,
    granularity     metric_granularity  NOT NULL DEFAULT '1h',

    -- When it was measured (partition key — MUST be part of every unique constraint)
    ts              TIMESTAMPTZ         NOT NULL,

    -- The measurement
    value           DOUBLE PRECISION    NOT NULL,
    unit            TEXT                NOT NULL DEFAULT '',

    -- Write-once: ingestion timestamp
    created_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW()

) PARTITION BY RANGE (ts);

COMMENT ON TABLE  usage_metrics             IS 'Time-series utilisation metrics; partitioned daily on ts.';
COMMENT ON COLUMN usage_metrics.ts          IS 'Partition key. Always provide in queries for partition pruning.';
COMMENT ON COLUMN usage_metrics.granularity IS 'Bucket size the data point represents (1m … 1d).';


INSERT INTO schema_migrations (version, name)
VALUES (2, '002_tables');

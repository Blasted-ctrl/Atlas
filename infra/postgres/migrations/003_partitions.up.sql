-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 003 — Partition Management
-- ─────────────────────────────────────────────────────────────────────────────
-- Provides a helper function to create daily partitions for usage_metrics
-- and bootstraps the initial window (90 days back + 60 days forward).
--
-- In production, call create_usage_metric_partitions() from:
--   • A pg_partman maintenance job, OR
--   • A Kubernetes CronJob that runs daily:
--       SELECT create_usage_metric_partitions(
--           CURRENT_DATE + 29,   -- create the partition 30 days ahead
--           CURRENT_DATE + 30
--       );
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Partition creation helper ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION create_usage_metric_partitions(
    from_date DATE,
    to_date   DATE
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    cur_date  DATE    := from_date;
    tbl_name  TEXT;
    created   INTEGER := 0;
BEGIN
    WHILE cur_date <= to_date LOOP
        tbl_name := 'usage_metrics_' || to_char(cur_date, 'YYYYMMDD');

        -- Idempotent: only create if partition does not already exist
        IF NOT EXISTS (
            SELECT 1
              FROM pg_class     c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = current_schema()
               AND c.relname = tbl_name
        ) THEN
            EXECUTE format(
                'CREATE TABLE %I
                 PARTITION OF usage_metrics
                 FOR VALUES FROM (%L::TIMESTAMPTZ)
                           TO   (%L::TIMESTAMPTZ)',
                tbl_name,
                cur_date::TIMESTAMPTZ,
                (cur_date + 1)::TIMESTAMPTZ
            );

            -- Per-partition unique constraint (composite includes ts for correctness)
            EXECUTE format(
                'ALTER TABLE %I
                 ADD CONSTRAINT %I
                 UNIQUE (resource_id, metric, granularity, ts)',
                tbl_name,
                tbl_name || '_uq_resource_metric_ts'
            );

            created := created + 1;
        END IF;

        cur_date := cur_date + 1;
    END LOOP;

    RETURN created;
END;
$$;

COMMENT ON FUNCTION create_usage_metric_partitions(DATE, DATE) IS
    'Creates daily usage_metrics_YYYYMMDD partitions for [from_date, to_date]. Idempotent.';


-- ── Default partition — catches rows outside the managed range ─────────────────
-- Prevents inserts from failing if the scheduler is late.
-- Rows land here when no specific partition exists; the scheduler can then
-- move them via PARTITION OF … ATTACH / DETACH if needed.
CREATE TABLE usage_metrics_default
    PARTITION OF usage_metrics DEFAULT;

COMMENT ON TABLE usage_metrics_default IS
    'Catch-all for rows outside the managed daily partition range.';


-- ── Bootstrap: create partitions for the initial operational window ────────────
--
-- 90 days back   → covers historical data imports / backfills
-- 60 days ahead  → avoids gaps during the first 2 months of operation
SELECT create_usage_metric_partitions(
    CURRENT_DATE - INTERVAL '90 days',
    CURRENT_DATE + INTERVAL '60 days'
);


-- ── Partition inventory view ───────────────────────────────────────────────────
-- Useful for ops / debugging: shows all partitions with their row estimates.
CREATE OR REPLACE VIEW usage_metrics_partitions AS
SELECT
    c.relname                                               AS partition_name,
    pg_get_expr(c.relpartbound, c.oid, TRUE)                AS bounds,
    pg_size_pretty(pg_relation_size(c.oid))                 AS size,
    pg_stat_get_live_tuples(c.oid)                          AS live_rows,
    pg_stat_get_dead_tuples(c.oid)                          AS dead_rows,
    pg_stat_get_last_vacuum_time(c.oid)                     AS last_vacuum,
    pg_stat_get_last_autovacuum_time(c.oid)                 AS last_autovacuum
FROM   pg_class      c
JOIN   pg_inherits   i ON i.inhrelid = c.oid
JOIN   pg_class      p ON p.oid      = i.inhparent
WHERE  p.relname = 'usage_metrics'
ORDER  BY c.relname;

COMMENT ON VIEW usage_metrics_partitions IS
    'Partition inventory for usage_metrics including size and vacuum stats.';


INSERT INTO schema_migrations (version, name)
VALUES (3, '003_partitions');

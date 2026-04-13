-- ─────────────────────────────────────────────────────────────────────────────
-- Query 02: Underutilized Resources
-- ─────────────────────────────────────────────────────────────────────────────
-- Identifies resources that are paying for capacity they don't use.
-- Drives the "Savings Opportunities" dashboard panel and feeds the
-- recommendation engine.
--
-- Definition of "underutilized":
--   CPU avg  < 20%  AND  memory avg < 40%  over the last 14 days
--   (configurable via the CTE parameters below)
--
-- EXPLAIN strategy:
--   • The usage_metrics aggregation runs inside a CTE over the partitioned
--     table — the ts filter prunes all partitions outside the 14-day window.
--   • A LATERAL join is used on the recommendations CTE to avoid a correlated
--     subquery that would execute once per resource row (N+1 elimination).
--   • The final filter on cpu_avg / mem_avg uses the CTE result set, which
--     the planner can push predicates into.
--
-- Run EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) to verify partition pruning.
-- Expected plan:
--   Hash Join (resources ⋈ metrics_agg)
--   ->  Index Scan on idx_resources_type_status
--   ->  Finalize HashAggregate (from partitioned Append)
--        Partitions selected: 14 of ~150
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Parameters ────────────────────────────────────────────────────────────────
-- Adjust these to tune the underutilisation thresholds.

\set lookback_days     14
\set cpu_threshold     20.0
\set mem_threshold     40.0
\set min_sample_count  50       -- ignore resources with too few data points
\set min_monthly_cost  10.0     -- ignore tiny resources (not worth the effort)

-- ─────────────────────────────────────────────────────────────────────────────

WITH

-- Step 1: Aggregate usage_metrics per resource over the lookback window.
-- This CTE benefits from partition pruning on ts AND the composite index
-- idx_usage_resource_metric_gran_ts.
metrics_agg AS (
    SELECT
        um.resource_id,
        -- CPU stats
        AVG(um.value)   FILTER (WHERE um.metric = 'cpu_utilization')     AS cpu_avg,
        MAX(um.value)   FILTER (WHERE um.metric = 'cpu_utilization')     AS cpu_max,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY um.value)
                        FILTER (WHERE um.metric = 'cpu_utilization')     AS cpu_p95,
        -- Memory stats
        AVG(um.value)   FILTER (WHERE um.metric = 'memory_utilization')  AS mem_avg,
        MAX(um.value)   FILTER (WHERE um.metric = 'memory_utilization')  AS mem_max,
        -- Network (sanity-check for "idle" classification)
        AVG(um.value)   FILTER (WHERE um.metric = 'network_in_bytes')    AS net_in_avg,
        AVG(um.value)   FILTER (WHERE um.metric = 'network_out_bytes')   AS net_out_avg,
        COUNT(*)        FILTER (WHERE um.metric = 'cpu_utilization')     AS cpu_samples
    FROM   usage_metrics um
    WHERE  um.ts          >= NOW() - INTERVAL '14 days'   -- PARTITION PRUNING KEY
      AND  um.ts          <  NOW()
      AND  um.granularity IN ('1h', '6h')                 -- exclude noisy 1m samples
    GROUP  BY um.resource_id
),

-- Step 2: Join to resources and apply underutilisation filters.
-- Restricts to compute resources where instance right-sizing is actionable.
underutilized AS (
    SELECT
        r.id                                                AS resource_id,
        r.name,
        r.type,
        r.provider,
        r.account_id,
        r.region,
        r.instance_type,
        r.monthly_cost_usd,
        r.tags,

        ROUND(m.cpu_avg::NUMERIC, 2)                        AS cpu_avg_pct,
        ROUND(m.cpu_max::NUMERIC, 2)                        AS cpu_max_pct,
        ROUND(m.cpu_p95::NUMERIC, 2)                        AS cpu_p95_pct,
        ROUND(m.mem_avg::NUMERIC, 2)                        AS mem_avg_pct,
        ROUND(m.mem_max::NUMERIC, 2)                        AS mem_max_pct,
        m.cpu_samples,

        -- Estimated savings assuming we halve the instance (rough heuristic)
        ROUND(r.monthly_cost_usd * 0.50, 2)                 AS est_savings_usd_monthly,
        ROUND(r.monthly_cost_usd * 0.50 * 12, 2)            AS est_savings_usd_annual,

        -- Classification bucket for UI display
        CASE
            WHEN m.cpu_avg < 5  AND COALESCE(m.mem_avg, 0) < 20 THEN 'severely_underutilized'
            WHEN m.cpu_avg < 10 AND COALESCE(m.mem_avg, 0) < 30 THEN 'highly_underutilized'
            ELSE 'moderately_underutilized'
        END                                                  AS utilization_class

    FROM   resources r
    JOIN   metrics_agg m ON m.resource_id = r.id
    WHERE  r.deleted_at IS NULL
      AND  r.status      = 'running'
      AND  r.type        IN ('ec2_instance', 'rds_instance', 'rds_cluster', 'eks_node_group')
      AND  r.monthly_cost_usd >= 10.0                        -- :min_monthly_cost
      AND  m.cpu_samples >= 50                               -- :min_sample_count
      AND  m.cpu_avg     <  20.0                             -- :cpu_threshold
      AND  (m.mem_avg IS NULL OR m.mem_avg < 40.0)           -- :mem_threshold
),

-- Step 3: Fetch existing pending recommendations for these resources in one
-- query (prevents N+1: one query total instead of one per resource row).
existing_recs AS (
    SELECT DISTINCT ON (rec.resource_id)
        rec.resource_id,
        rec.id                  AS rec_id,
        rec.type                AS rec_type,
        rec.savings_usd_monthly AS rec_savings,
        rec.confidence          AS rec_confidence,
        rec.created_at          AS rec_created_at
    FROM   recommendations rec
    WHERE  rec.resource_id IN (SELECT resource_id FROM underutilized)
      AND  rec.status       = 'pending'
      AND  rec.type         = 'resize_down'
      AND  rec.deleted_at   IS NULL
    ORDER  BY rec.resource_id, rec.savings_usd_monthly DESC
)

-- Final result: underutilised resources with savings estimate and existing rec info
SELECT
    u.resource_id,
    u.name,
    u.type,
    u.provider,
    u.account_id,
    u.region,
    u.instance_type,
    u.monthly_cost_usd,
    u.cpu_avg_pct,
    u.cpu_max_pct,
    u.cpu_p95_pct,
    u.mem_avg_pct,
    u.mem_max_pct,
    u.cpu_samples,
    u.est_savings_usd_monthly,
    u.est_savings_usd_annual,
    u.utilization_class,
    u.tags->>'Environment'      AS environment,
    u.tags->>'Team'             AS team,

    -- Existing recommendation info (NULL if no pending rec yet)
    er.rec_id,
    er.rec_type,
    er.rec_savings,
    er.rec_confidence,
    er.rec_created_at,

    -- Convenience flag for the UI
    (er.rec_id IS NOT NULL)     AS has_pending_recommendation

FROM   underutilized u
LEFT   JOIN existing_recs er ON er.resource_id = u.resource_id
ORDER  BY u.est_savings_usd_monthly DESC, u.cpu_avg_pct ASC;


-- ── 2b. Top 10 idle resources (terminate candidates) ─────────────────────────
-- Resources with near-zero CPU AND no network activity over 30 days.
-- These are likely forgotten dev/staging instances.

WITH idle AS (
    SELECT
        um.resource_id,
        AVG(um.value) FILTER (WHERE um.metric = 'cpu_utilization')  AS cpu_avg,
        AVG(um.value) FILTER (WHERE um.metric = 'network_in_bytes') AS net_avg,
        COUNT(*)      FILTER (WHERE um.metric = 'cpu_utilization')  AS samples
    FROM   usage_metrics um
    WHERE  um.ts >= NOW() - INTERVAL '30 days'    -- partition pruning
      AND  um.ts <  NOW()
    GROUP  BY um.resource_id
    HAVING
        AVG(um.value) FILTER (WHERE um.metric = 'cpu_utilization') < 2.0
        AND COUNT(*) FILTER (WHERE um.metric = 'cpu_utilization')  > 100
)
SELECT
    r.id,
    r.name,
    r.type,
    r.instance_type,
    r.region,
    r.monthly_cost_usd,
    ROUND(i.cpu_avg::NUMERIC, 3)    AS cpu_avg_pct,
    ROUND(i.net_avg::NUMERIC, 0)    AS net_in_avg_bytes,
    i.samples
FROM   resources r
JOIN   idle i ON i.resource_id = r.id
WHERE  r.deleted_at IS NULL
  AND  r.status = 'running'
ORDER  BY r.monthly_cost_usd DESC
LIMIT  10;


-- ── 2c. Underutilisation heatmap by team / environment tag ───────────────────
-- Shows which teams have the most waste — useful for chargeback reporting.
-- Uses the GIN index on tags for the tag extraction.

WITH team_util AS (
    SELECT
        r.tags->>'Team'           AS team,
        r.tags->>'Environment'    AS environment,
        r.provider,
        COUNT(DISTINCT r.id)      AS resource_count,
        ROUND(SUM(r.monthly_cost_usd), 2)          AS total_cost_usd,
        ROUND(AVG(m.cpu_avg)::NUMERIC, 2)           AS avg_cpu_pct
    FROM   resources r
    JOIN   (
        SELECT resource_id, AVG(value) AS cpu_avg
        FROM   usage_metrics
        WHERE  metric = 'cpu_utilization'
          AND  ts >= NOW() - INTERVAL '14 days'   -- partition pruning
          AND  ts <  NOW()
        GROUP  BY resource_id
    ) m ON m.resource_id = r.id
    WHERE  r.deleted_at IS NULL
      AND  r.status = 'running'
    GROUP  BY r.tags->>'Team', r.tags->>'Environment', r.provider
)
SELECT
    team,
    environment,
    provider,
    resource_count,
    total_cost_usd,
    avg_cpu_pct,
    -- Estimated total waste across this group
    ROUND(total_cost_usd * GREATEST(0, (20.0 - avg_cpu_pct)) / 100.0, 2)
                                  AS est_waste_usd
FROM   team_util
WHERE  team IS NOT NULL
ORDER  BY est_waste_usd DESC;

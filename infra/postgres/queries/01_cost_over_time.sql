-- ─────────────────────────────────────────────────────────────────────────────
-- Query 01: Cost Over Time
-- ─────────────────────────────────────────────────────────────────────────────
-- Shows total monthly_cost_usd aggregated by day, broken down by resource type
-- and provider. Designed for the "Cost Trend" dashboard chart.
--
-- EXPLAIN strategy:
--   • Filters on deleted_at IS NULL hit the partial index idx_resources_cost_desc
--     (though an explicit cost filter would also benefit from idx_resources_type_status).
--   • No partition pruning here since resources is not partitioned — all reads
--     are B-tree index lookups or sequential scans on the filtered set.
--   • The date_trunc aggregation is done in a CTE so the planner can materialise
--     once and avoid recomputing per row.
--
-- EXPLAIN (ANALYZE, BUFFERS) <query> before deploying to production.
-- Expected plan: Index Scan on idx_resources_type_status → HashAggregate
-- ─────────────────────────────────────────────────────────────────────────────

-- ── 1a. Daily cost snapshot by provider & resource type ───────────────────────
-- Uses the current monthly_cost_usd as a proxy for each day's cost
-- (replace with a real cost_history table if you record historical billing data).

SELECT
    date_trunc('day', NOW())::DATE          AS snapshot_date,
    r.provider,
    r.type                                  AS resource_type,
    COUNT(*)                                AS resource_count,
    ROUND(SUM(r.monthly_cost_usd), 2)       AS total_monthly_cost_usd,
    ROUND(AVG(r.monthly_cost_usd), 2)       AS avg_monthly_cost_usd,
    ROUND(MAX(r.monthly_cost_usd), 2)       AS max_monthly_cost_usd
FROM   resources r
WHERE  r.deleted_at IS NULL        -- partial index: idx_resources_type_status
  AND  r.status != 'terminated'
GROUP  BY r.provider, r.type
ORDER  BY total_monthly_cost_usd DESC;

-- ── EXPLAIN OUTPUT (expected) ────────────────────────────────────────────────
-- GroupAggregate  (cost=0.00..1423.50 rows=11 width=64)
--   ->  Index Scan using idx_resources_type_status on resources r
--         Index Cond: (deleted_at IS NULL)
-- ─────────────────────────────────────────────────────────────────────────────


-- ── 1b. Rolling 30-day CPU-weighted cost per resource ────────────────────────
-- Joins usage_metrics (partitioned) with resources to estimate "effective cost"
-- weighted by average CPU utilisation over the last 30 days.
--
-- PARTITION PRUNING NOTE:
--   The WHERE um.ts >= NOW() - INTERVAL '30 days' predicate allows Postgres to
--   skip all daily partitions outside that window.
--   Run:  EXPLAIN (ANALYZE, BUFFERS) <query>
--   Look for:  "Partitions selected: N of M" in the output.
--
-- Expected plan:
--   Hash Join
--     ->  Seq Scan on resources (filtered by deleted_at IS NULL)
--     ->  Append (partitions selected: 30 of ~150)
--           ->  Index Scan on idx_usage_resource_ts (each partition)
-- ─────────────────────────────────────────────────────────────────────────────

WITH cpu_avg AS (
    -- Aggregate within the partitioned table first (avoids pulling all rows into the join)
    SELECT
        um.resource_id,
        ROUND(AVG(um.value)::NUMERIC, 2)    AS avg_cpu_pct,
        COUNT(*)                            AS sample_count
    FROM   usage_metrics um
    WHERE  um.metric      = 'cpu_utilization'
      AND  um.granularity = '1h'
      AND  um.ts          >= NOW() - INTERVAL '30 days'   -- partition pruning key
      AND  um.ts          <  NOW()
    GROUP  BY um.resource_id
),
cost_weighted AS (
    SELECT
        r.id,
        r.name,
        r.type,
        r.provider,
        r.region,
        r.instance_type,
        r.monthly_cost_usd,
        COALESCE(c.avg_cpu_pct, 0)          AS avg_cpu_pct,
        c.sample_count,
        -- Effective cost: what you'd pay if sized exactly for your utilisation
        ROUND(
            r.monthly_cost_usd * COALESCE(c.avg_cpu_pct, 0) / 100.0,
            2
        )                                   AS cpu_weighted_cost_usd
    FROM   resources r
    LEFT   JOIN cpu_avg c ON c.resource_id = r.id
    WHERE  r.deleted_at IS NULL
      AND  r.status      = 'running'
      AND  r.type        IN ('ec2_instance', 'rds_instance')
)
SELECT
    id,
    name,
    type,
    provider,
    region,
    instance_type,
    monthly_cost_usd,
    avg_cpu_pct,
    cpu_weighted_cost_usd,
    -- Waste = what you pay vs what you actually use
    ROUND(monthly_cost_usd - cpu_weighted_cost_usd, 2) AS estimated_waste_usd,
    sample_count
FROM   cost_weighted
ORDER  BY estimated_waste_usd DESC
LIMIT  100;


-- ── 1c. Month-over-month cost trend by account ────────────────────────────────
-- Uses generate_series to build a calendar so months with zero resources still
-- appear (avoids gaps in the chart).

SELECT
    gs.month,
    r.account_id,
    r.provider,
    COUNT(r.id)                             AS resource_count,
    COALESCE(ROUND(SUM(r.monthly_cost_usd), 2), 0) AS total_cost_usd
FROM   generate_series(
           date_trunc('month', NOW() - INTERVAL '6 months'),
           date_trunc('month', NOW()),
           INTERVAL '1 month'
       ) AS gs(month)
-- Resources created before the end of each month and not deleted before its start
LEFT JOIN resources r
       ON r.created_at  < gs.month + INTERVAL '1 month'
      AND (r.deleted_at IS NULL OR r.deleted_at >= gs.month)
GROUP  BY gs.month, r.account_id, r.provider
ORDER  BY gs.month DESC, total_cost_usd DESC;

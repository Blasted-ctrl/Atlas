-- ─────────────────────────────────────────────────────────────────────────────
-- Query 03: Top Savings Opportunities & Recommendation Analytics
-- ─────────────────────────────────────────────────────────────────────────────
-- Aggregate views used by the "Savings Summary" dashboard panel.
--
-- EXPLAIN strategy:
--   • All queries filter status = 'pending' AND deleted_at IS NULL, which hits
--     the partial index idx_rec_savings_desc and idx_rec_resource_pending.
--   • The resource JOIN uses idx_resources_account_region (FK lookup).
--   • No correlated subqueries — all aggregation uses single-pass GROUP BY.
-- ─────────────────────────────────────────────────────────────────────────────


-- ── 3a. Total savings available right now ────────────────────────────────────
-- Single-row summary card for the dashboard header.

SELECT
    COUNT(*)                                AS total_recommendations,
    COUNT(*) FILTER (WHERE type = 'resize_down')         AS resize_down_count,
    COUNT(*) FILTER (WHERE type = 'terminate')            AS terminate_count,
    COUNT(*) FILTER (WHERE type = 'reserved_instance')    AS ri_count,
    COUNT(*) FILTER (WHERE type = 'savings_plan')         AS sp_count,
    COUNT(*) FILTER (WHERE type = 'schedule')             AS schedule_count,
    ROUND(SUM(savings_usd_monthly),  2)     AS total_savings_usd_monthly,
    ROUND(SUM(savings_usd_annual),   2)     AS total_savings_usd_annual,
    ROUND(AVG(confidence) * 100, 1)        AS avg_confidence_pct
FROM   recommendations
WHERE  status     = 'pending'
  AND  deleted_at IS NULL;
-- Expected plan: Index Scan on idx_rec_savings_desc → Aggregate


-- ── 3b. Top 25 recommendations by monthly savings ────────────────────────────
-- Powers the main recommendations table.
-- Uses a single JOIN to resources (no N+1).

SELECT
    rec.id                              AS recommendation_id,
    rec.type,
    rec.title,
    rec.savings_usd_monthly,
    rec.savings_usd_annual,
    ROUND(rec.confidence * 100, 1)      AS confidence_pct,
    rec.created_at,
    rec.expires_at,

    -- Resource context (all from the FK join — single lookup via PK)
    r.id                                AS resource_id,
    r.name                              AS resource_name,
    r.type                              AS resource_type,
    r.instance_type,
    r.provider,
    r.account_id,
    r.region,
    r.monthly_cost_usd                  AS current_monthly_cost,
    r.tags->>'Environment'              AS environment,
    r.tags->>'Team'                     AS team,

    -- Savings as a % of current spend (context for the user)
    CASE
        WHEN r.monthly_cost_usd > 0
        THEN ROUND(rec.savings_usd_monthly / r.monthly_cost_usd * 100, 1)
        ELSE 0
    END                                 AS savings_pct_of_cost

FROM   recommendations rec
JOIN   resources r ON r.id = rec.resource_id
WHERE  rec.status       = 'pending'
  AND  rec.deleted_at   IS NULL
  AND  r.deleted_at     IS NULL
ORDER  BY rec.savings_usd_monthly DESC, rec.confidence DESC
LIMIT  25;
-- Expected plan:
--   Limit
--     Sort (savings_usd_monthly DESC)
--       Hash Join
--         Seq Scan on resources (small, fits in memory)
--         Index Scan on idx_rec_savings_desc


-- ── 3c. Savings breakdown by recommendation type ──────────────────────────────

SELECT
    rec.type,
    COUNT(*)                                    AS count,
    ROUND(SUM(rec.savings_usd_monthly),  2)     AS total_savings_usd_monthly,
    ROUND(AVG(rec.savings_usd_monthly),  2)     AS avg_savings_usd_monthly,
    ROUND(MAX(rec.savings_usd_monthly),  2)     AS max_savings_usd_monthly,
    ROUND(AVG(rec.confidence) * 100, 1)        AS avg_confidence_pct,
    COUNT(DISTINCT rec.resource_id)             AS distinct_resources_affected
FROM   recommendations rec
WHERE  rec.status     = 'pending'
  AND  rec.deleted_at IS NULL
GROUP  BY rec.type
ORDER  BY total_savings_usd_monthly DESC;


-- ── 3d. Recommendation conversion funnel ─────────────────────────────────────
-- Shows how recommendations progress through the pipeline.
-- Helps identify if users are accepting, rejecting, or ignoring them.

WITH funnel AS (
    SELECT
        DATE_TRUNC('week', created_at)          AS week,
        status,
        COUNT(*)                                AS count,
        ROUND(SUM(savings_usd_monthly), 2)      AS savings_usd_monthly
    FROM   recommendations
    WHERE  created_at >= NOW() - INTERVAL '90 days'
      AND  deleted_at  IS NULL
    GROUP  BY DATE_TRUNC('week', created_at), status
)
SELECT
    week,
    SUM(count) FILTER (WHERE status = 'pending')   AS pending,
    SUM(count) FILTER (WHERE status = 'accepted')  AS accepted,
    SUM(count) FILTER (WHERE status = 'applied')   AS applied,
    SUM(count) FILTER (WHERE status = 'rejected')  AS rejected,
    SUM(count) FILTER (WHERE status = 'dismissed') AS dismissed,
    SUM(count) FILTER (WHERE status = 'expired')   AS expired,
    ROUND(
        SUM(savings_usd_monthly) FILTER (WHERE status = 'applied'), 2
    )                                              AS savings_actually_applied_usd
FROM   funnel
GROUP  BY week
ORDER  BY week DESC;


-- ── 3e. Resources with no recommendations yet ─────────────────────────────────
-- Identifies blind spots — resources that have never been analyzed.
-- Useful for scheduling targeted optimization runs.
-- Uses a LEFT JOIN ANTI-PATTERN (WHERE rec.id IS NULL) which Postgres
-- transforms into a Hash Anti Join.

SELECT
    r.id,
    r.name,
    r.type,
    r.instance_type,
    r.provider,
    r.region,
    r.monthly_cost_usd,
    r.last_seen_at
FROM   resources r
LEFT   JOIN recommendations rec
         ON rec.resource_id = r.id
        AND rec.deleted_at  IS NULL
WHERE  r.deleted_at IS NULL
  AND  r.status      = 'running'
  AND  rec.id        IS NULL                 -- anti-join: no recommendations exist
ORDER  BY r.monthly_cost_usd DESC
LIMIT  100;
-- Expected plan:
--   Limit
--     Hash Anti Join
--       Seq Scan on resources (running, not deleted)
--       Index Scan on idx_rec_resource_id (covering rec.resource_id)


-- ── 3f. EXPLAIN template ─────────────────────────────────────────────────────
-- Copy-paste this wrapper around any query to get the full execution plan
-- with actual runtime statistics and buffer hit/miss counts.
--
-- IMPORTANT: Run against a database with realistic data volume (post-seed).
-- Never run EXPLAIN ANALYZE on a production write path.

/*
EXPLAIN (
    ANALYZE,            -- actually execute and show real timings
    BUFFERS,            -- show shared/local buffer hits and misses
    FORMAT TEXT,        -- human-readable (use FORMAT JSON for tooling)
    VERBOSE             -- show output columns per node
)
-- paste query here
;
*/

-- ── Key things to check in the plan ──────────────────────────────────────────
-- 1. "Partitions selected: N of M"  → partition pruning is working on usage_metrics
-- 2. "Index Scan using idx_*"       → correct indexes are being used
-- 3. "Seq Scan on resources"        → acceptable when the table is small enough
--    to fit in shared_buffers; flag if rows >> 100k
-- 4. "Hash Join" / "Nested Loop"    → Hash Join preferred for large tables;
--    Nested Loop only OK if inner side is index-scannable and small
-- 5. "Sort Method: quicksort Memory: Xk" → if X > work_mem, tune work_mem
--    or add a covering index that returns rows pre-sorted

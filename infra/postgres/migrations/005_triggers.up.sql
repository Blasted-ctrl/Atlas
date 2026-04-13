-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 005 — Triggers, Functions, & Audit Infrastructure
-- ─────────────────────────────────────────────────────────────────────────────

-- ── updated_at maintenance ────────────────────────────────────────────────────
--
-- Single function, attached to every mutable table.
-- The trigger fires BEFORE UPDATE so the new row already has the correct value
-- before it hits storage — no extra write.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION set_updated_at() IS
    'Trigger function: stamps updated_at on every row modification.';

-- Attach to each mutable table
CREATE TRIGGER trg_resources_updated_at
    BEFORE UPDATE ON resources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_optimization_runs_updated_at
    BEFORE UPDATE ON optimization_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_recommendations_updated_at
    BEFORE UPDATE ON recommendations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ── Audit log ─────────────────────────────────────────────────────────────────
--
-- Append-only ledger of mutations on business-critical tables.
-- Populated by the trg_*_audit triggers below.
-- The jsonb columns store only the changed columns (NEW / OLD diff).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE audit_log (
    id          BIGSERIAL    PRIMARY KEY,
    table_name  TEXT         NOT NULL,
    row_id      UUID         NOT NULL,         -- PK of the affected row
    operation   TEXT         NOT NULL          -- INSERT | UPDATE | DELETE
                    CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    old_data    JSONB,                         -- NULL for INSERT
    new_data    JSONB,                         -- NULL for DELETE
    changed_by  TEXT         NOT NULL DEFAULT current_user,
    changed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (changed_at);

-- Monthly audit partitions (lower volume than usage_metrics)
CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;

COMMENT ON TABLE  audit_log            IS 'Append-only audit trail for resources and recommendations.';
COMMENT ON COLUMN audit_log.old_data   IS 'Full row image before the change; NULL for INSERT.';
COMMENT ON COLUMN audit_log.new_data   IS 'Full row image after the change; NULL for DELETE.';
COMMENT ON COLUMN audit_log.changed_by IS 'Database role / application user at the time of change.';

CREATE INDEX idx_audit_table_row  ON audit_log (table_name, row_id, changed_at DESC);
CREATE INDEX idx_audit_changed_at ON audit_log (changed_at DESC);


-- ── Generic audit trigger function ───────────────────────────────────────────

CREATE OR REPLACE FUNCTION record_audit()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER          -- runs as owner regardless of calling role
AS $$
BEGIN
    INSERT INTO audit_log (table_name, row_id, operation, old_data, new_data)
    VALUES (
        TG_TABLE_NAME,
        CASE TG_OP
            WHEN 'DELETE' THEN OLD.id
            ELSE NEW.id
        END,
        TG_OP,
        CASE TG_OP WHEN 'INSERT' THEN NULL ELSE to_jsonb(OLD) END,
        CASE TG_OP WHEN 'DELETE' THEN NULL ELSE to_jsonb(NEW) END
    );
    RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

COMMENT ON FUNCTION record_audit() IS
    'Trigger function: writes INSERT/UPDATE/DELETE events to audit_log.';

-- Attach audit trigger to business-critical tables
CREATE TRIGGER trg_resources_audit
    AFTER INSERT OR UPDATE OR DELETE ON resources
    FOR EACH ROW EXECUTE FUNCTION record_audit();

CREATE TRIGGER trg_recommendations_audit
    AFTER INSERT OR UPDATE OR DELETE ON recommendations
    FOR EACH ROW EXECUTE FUNCTION record_audit();


-- ── Recommendation status guard ───────────────────────────────────────────────
--
-- Prevents rolling back a terminal status (applied, dismissed, expired)
-- at the database level — defence-in-depth against buggy application code.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION guard_recommendation_status()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status IN ('applied', 'dismissed', 'expired')
       AND NEW.status != OLD.status THEN
        RAISE EXCEPTION
            'recommendation % is in terminal status "%" and cannot be transitioned to "%"',
            OLD.id, OLD.status, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_rec_status_guard
    BEFORE UPDATE OF status ON recommendations
    FOR EACH ROW EXECUTE FUNCTION guard_recommendation_status();


-- ── Resource last_seen_at auto-refresh ────────────────────────────────────────
--
-- When a sync pipeline UPSERTs a resource, if any non-audit column changes
-- we bump last_seen_at automatically, removing the need for the pipeline
-- to track it explicitly.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION refresh_resource_last_seen()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    -- Only bump if substantive fields changed (ignore audit column churn)
    IF (
        NEW.status        IS DISTINCT FROM OLD.status        OR
        NEW.instance_type IS DISTINCT FROM OLD.instance_type OR
        NEW.monthly_cost_usd IS DISTINCT FROM OLD.monthly_cost_usd OR
        NEW.specs         IS DISTINCT FROM OLD.specs         OR
        NEW.network       IS DISTINCT FROM OLD.network       OR
        NEW.tags          IS DISTINCT FROM OLD.tags
    ) THEN
        NEW.last_seen_at := NOW();
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_resources_last_seen
    BEFORE UPDATE ON resources
    FOR EACH ROW EXECUTE FUNCTION refresh_resource_last_seen();


-- ── Soft-delete helper ────────────────────────────────────────────────────────
--
-- Applications should call this instead of DELETE to preserve referential
-- integrity and the audit trail.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION soft_delete_resource(p_resource_id UUID)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE resources
       SET deleted_at = NOW(),
           status     = 'terminated'
     WHERE id = p_resource_id
       AND deleted_at IS NULL;

    IF NOT FOUND THEN
        RAISE NOTICE 'resource % not found or already deleted', p_resource_id;
    END IF;
END;
$$;

COMMENT ON FUNCTION soft_delete_resource(UUID) IS
    'Soft-deletes a resource and marks it terminated. Preserves FK references.';


-- ── Expiry sweep ──────────────────────────────────────────────────────────────
--
-- Mark stale pending recommendations as expired.
-- Call periodically (e.g. daily) from a CronJob or pg_cron:
--   SELECT expire_stale_recommendations();
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION expire_stale_recommendations()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    affected INTEGER;
BEGIN
    WITH expired AS (
        UPDATE recommendations
           SET status     = 'expired',
               updated_at = NOW()
         WHERE status     = 'pending'
           AND expires_at < NOW()
           AND deleted_at IS NULL
        RETURNING id
    )
    SELECT COUNT(*) INTO affected FROM expired;

    RETURN affected;
END;
$$;

COMMENT ON FUNCTION expire_stale_recommendations() IS
    'Transitions overdue pending recommendations to expired. Returns row count.';


INSERT INTO schema_migrations (version, name)
VALUES (5, '005_triggers');

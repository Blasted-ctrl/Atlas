-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 005 — Rollback
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM schema_migrations WHERE version = 5;

-- Functions
DROP FUNCTION IF EXISTS expire_stale_recommendations();
DROP FUNCTION IF EXISTS soft_delete_resource(UUID);
DROP FUNCTION IF EXISTS refresh_resource_last_seen();
DROP FUNCTION IF EXISTS guard_recommendation_status();
DROP FUNCTION IF EXISTS record_audit();
DROP FUNCTION IF EXISTS set_updated_at();

-- Triggers are dropped automatically when their function or table is dropped.
-- Dropping the audit table separately since it's not cascaded from the main tables.
DROP TABLE IF EXISTS audit_log CASCADE;

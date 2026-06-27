-- 0002_indexes.sql
--
-- Adds obvious lookup indexes to the initial schema. None are unique
-- because the substrate tables are append-mostly — uniqueness is enforced
-- by the application layer or by primary-key constraints added in 0001.

CREATE INDEX IF NOT EXISTS ix_adapters_active_settings_tenant
    ON adapters_active_settings_version (tenant_id, activated_at DESC);

CREATE INDEX IF NOT EXISTS ix_tenants_context_versions_tenant
    ON tenants_context_versions (tenant_id, published_at DESC);

CREATE INDEX IF NOT EXISTS ix_workflows_progress_snapshots_workflow
    ON workflows_progress_snapshots (workflow_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS ix_dhara_audit_log_tenant_time
    ON dhara_audit_log (tenant_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS ix_dhara_audit_log_event_type
    ON dhara_audit_log (event_type, occurred_at DESC);

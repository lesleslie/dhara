-- 0001_initial.sql
--
-- Dhara substrate initial schema.
-- Creates the three SPEC-10 / events-substrate tables:
--   * adapters_active_settings_version
--   * tenants_context_versions
--   * workflows_progress_snapshots
--
-- plus the bookkeeping table ``dhara_audit_log`` required by the bundled
-- AuditLogSubscriber.
--
-- All IDs are TEXT (ULIDs) to match the existing adapter metadata layer.
-- Timestamps are TIMESTAMP (UTC) — DuckDB-friendly and Postgres-compatible.

CREATE TABLE IF NOT EXISTS adapters_active_settings_version (
    version_id       TEXT PRIMARY KEY,
    adapter_name     TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    settings_blob    TEXT NOT NULL,
    activated_by     TEXT NOT NULL,
    activated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tenants_context_versions (
    version_id       TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL,
    context_blob     TEXT NOT NULL,
    published_by     TEXT NOT NULL,
    published_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflows_progress_snapshots (
    snapshot_id      TEXT PRIMARY KEY,
    workflow_id      TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    step             TEXT NOT NULL,
    progress_percent DOUBLE PRECISION NOT NULL,
    recorded_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dhara_audit_log (
    id               INTEGER PRIMARY KEY,
    event_type       TEXT NOT NULL,
    event_id         TEXT NOT NULL,
    occurred_at      TIMESTAMP NOT NULL,
    tenant_id        TEXT,
    payload          TEXT NOT NULL
);

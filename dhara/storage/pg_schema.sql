-- dhara/storage/pg_schema.sql
-- Run against your Postgres instance before using PostgresStorageAdapter.
-- Supports both Homebrew local Postgres and Neon cloud Postgres.

-- Objects table
CREATE TABLE IF NOT EXISTS dhara_objects (
    oid BIGINT PRIMARY KEY,
    data BYTEA NOT NULL
);

-- Atomic OID generation (no singleton row bottleneck)
CREATE SEQUENCE IF NOT EXISTS dhara_oid_seq;

-- Change tracking for sync()
CREATE TABLE IF NOT EXISTS dhara_dirty_oids (
    oid BIGINT NOT NULL,
    marked_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dhara_dirty_oids_marked_at ON dhara_dirty_oids (marked_at);
CREATE INDEX IF NOT EXISTS idx_dhara_dirty_oids_oid ON dhara_dirty_oids (oid);
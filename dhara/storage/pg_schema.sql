-- dhara/storage/pg_schema.sql
-- Run against your Postgres instance before using PostgresStorageAdapter.
-- Supports both Homebrew local Postgres and Neon cloud Postgres.

-- Objects table
-- Mirrors dhara/storage/sqlite.py:_ASYNC_DB_SCHEMA (id INTEGER PRIMARY KEY,
-- data BLOB, refs BLOB) and the _PG_SCHEMA constant in
-- dhara/storage/postgres.py. The `refs` column is required at runtime for
-- the load() path; do NOT drop it without also updating postgres.py.
CREATE TABLE IF NOT EXISTS dhara_objects (
    oid BIGINT PRIMARY KEY,
    data BYTEA NOT NULL,
    refs BYTEA
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

-- Locks table (mirrors 0003_locks.sql DuckDB schema, with PG types)
CREATE TABLE IF NOT EXISTS substrate_locks (
    lock_key TEXT PRIMARY KEY,
    owner_token TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    is_permanent BOOLEAN NOT NULL DEFAULT FALSE,
    original_ttl_seconds INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_substrate_locks_expires_at ON substrate_locks (expires_at);
CREATE INDEX IF NOT EXISTS idx_substrate_locks_is_permanent ON substrate_locks (is_permanent);
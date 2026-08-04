-- dhara/migrations/sql/0003_locks.sql
-- D-LOCK substrate: distributed lock + audit ledger primitive
-- See docs/superpowers/specs/2026-08-04-d-lock-design.md

CREATE TABLE IF NOT EXISTS substrate_locks (
    lock_key              TEXT PRIMARY KEY,
    owner_token           TEXT NOT NULL,
    acquired_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at            TIMESTAMPTZ,                 -- NULL = advisory or permanent lock
    is_permanent          BOOLEAN NOT NULL DEFAULT FALSE,
    original_ttl_seconds  INTEGER,                     -- NULL = no original lease; required for extend_seconds=None semantic
    metadata              TEXT NOT NULL DEFAULT '{}'   -- JSON blob; empty object default. Callers embed their own signatures inside this JSON.
);

-- Plain indexes (not partial) for DuckDB compatibility. Partial indexes
-- (WHERE expires_at IS NOT NULL) are a Postgres-only optimization; deferred
-- to a follow-up if expiration-row counts warrant the storage savings.
CREATE INDEX IF NOT EXISTS ix_substrate_locks_expires_at
    ON substrate_locks (expires_at);

CREATE INDEX IF NOT EXISTS ix_substrate_locks_is_permanent
    ON substrate_locks (is_permanent);

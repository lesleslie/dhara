-- 0004_audit_log.sql: durable AuditLog subscriber substrate table.
-- D-AUDIT substrate (Layer 0) — see docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md

CREATE SEQUENCE IF NOT EXISTS audit_log_id_seq START 1;

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT          PRIMARY KEY DEFAULT nextval('audit_log_id_seq'),
    entity_type VARCHAR         NOT NULL,
    entity_id   VARCHAR         NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payload     TEXT            NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS audit_log_entity_type_recorded_at
    ON audit_log (entity_type, recorded_at DESC);
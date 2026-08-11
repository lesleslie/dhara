---
status: draft
role: implementation
date: 2026-08-10
last_reviewed: 2026-08-10
topic: audit-substrate
entity: audit_record (substrate producer)
owner_repo: dhara
subscribes_to: dhara.schema.audit_record
---

# D-AUDIT Design Spec (Layer 0 substrate)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Layer 0 durable `AuditLogSubscriber` substrate. Every `dhara.put(...)` call across the Bodai ecosystem produces a structured `audit_record` (validated via the just-shipped `dhara.schema.audit_record` entity). Single producer (the subscriber); many readers (any module that calls `audit_record` query MCP tool).

**Architecture:**
- **Producer side**: A Dhara-internal `AuditLogSubscriber` (`dhara/audit/subscriber.py`) hooks into `dhara.put`. Each write triggers a structured `audit_record` payload validated via `validate("audit_record", payload)` from `SCHEMA_REGISTRY`. Emits **asynchronously** via MemoryOutbox (the original `dhara.put` returns immediately; the audit_record is enqueued in a memory outbox and flushed by a background task). On validation failure, the subscriber emits a fallback log entry but does NOT raise — durability of the original write is preserved (G6-style "substrate failures NEVER break the producer").
- **Consumer side**: `AuditLogQueryTool` (new MCP tool under Dhara, registered in `DharaMCPServer._register_tools()`) accepts `(entity_type, since, until, limit)` and returns a list of validated `audit_record` structs via `from_dict("audit_record", payload)`.
- **Persistence**: migration 0004 (`dhara/migrations/sql/0004_audit_log.sql`) creates `audit_log` table with `(entity_type, entity_id, recorded_at, payload TEXT)` columns.

**Tech Stack:** Python 3.13, msgspec.Struct (substrate), Dhara subscriber pattern (existing), FastMCP for query tool, pytest-asyncio, no new third-party deps.

## Integration Contract

- **Triggered from:** every `dhara.put(...)` call (Dhara internal write primitive)
- **Returns to / updates:** `audit_log` table in Dhara (substrate-level)
- **Demonstrable by:** pytest `tests/integration/audit/test_subscriber.py::test_audit_record_emitted_on_put` + smoke `pytest tests/integration/audit/test_query_tool.py::test_query_returns_validated_records`
- **Rollback signal:** disable subscriber registration in `DharaMCPServer._register_tools()`; subscriber import + wiring removed; durable writes still succeed (audit emission loss only)
- **Observability added:** counter `audit_record_emitted_total{entity_type, status}` (success/fallback) + counter `audit_record_invalid_total{entity_type, reason}` (validation_error, outbox_overflow)

## Tasks (Sketch)

1. Migration 0004: `audit_log` table schema (Dhara migration runner precedent)
2. Implement `AuditLogSubscriber` in `dhara/audit/subscriber.py` + MemoryOutbox flush task + tests (RED-first)
3. Implement `AuditLogQueryTool` MCP tool + tests (RED-first)
4. Wire subscriber + query tool into `DharaMCPServer._register_tools()` (same pattern as `register_lock_routes` from D-LOCK)
5. Cross-system test: arbitrary `dhara.put` → audit_record emitted + retrievable
6. Crackerjack gate + completion report

## Open questions

None.

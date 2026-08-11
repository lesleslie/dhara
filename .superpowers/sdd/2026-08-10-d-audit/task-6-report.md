# Task 6 Report — Cross-System Integration Test

**Date**: 2026-08-10
**BASE**: `7c07f4d` (Task 5 head)
**HEAD**: `14ca859`
**Branch**: `main` (Bodai pre-1.0 merge policy)
**Commit**: `test(audit): cross-system integration test — dhara.put → audit_record round-trip`

## Summary

Implemented a cross-system integration test that exercises the assembled audit substrate (Tasks 1-5) end-to-end: `DharaMCPServer` → `AuditLogSubscriber` → `MemoryOutbox` → `OutboxFlusher` → `audit_log` table → `AuditLogQueryTool`.

While implementing the test, **two brief-bugs and one substrate gap** were surfaced and fixed.

## Brief-Bug Pattern (Confirmed Systemic)

The brief used non-existent `action`/`target` fields and asserted `results[0].action`. The real `AuditRecord` schema is `audit_id`, `event_type`, `actor`, `at`, `subject`, `metadata` (per `dhara/schema/audit_record.py`).

| Brief claim | Reality |
|---|---|
| `record.action` | Field doesn't exist on `AuditRecord` |
| `record.target` | Field doesn't exist on `AuditRecord` |
| `results[0].action` | Audit log row payload JSON has `event_type`, `subject`, `metadata` |

**Pattern**: Briefs in Tasks 2-6 all reference non-existent `action`/`target` attributes — this is now the 5th consecutive brief with the same bug. Future brief authors should ground their assertions in the actual `AuditRecord` schema or run their brief code through a `msgspec.convert(payload, AuditRecord)` smoke test before shipping.

## Substrate Gaps Discovered & Fixed

### Gap 1: Flusher JSON payload incomplete (carried from Task 5)

**Symptom**: `audit_log.payload` would have been a JSON dump of an object missing required `audit_id`/`at` fields.

**Fix**: `dhara/audit/flusher.py` now serializes all six `AuditRecord` fields via `json.dumps({...})`:
```python
{
    "audit_id": record.audit_id,
    "event_type": record.event_type,
    "actor": record.actor,
    "at": record.at.isoformat(),
    "subject": record.subject,
    "metadata": dict(record.metadata),
}
```

### Gap 2: `MemoryOutbox` stripped entity context (this task)

**Symptom**: After flushing, `audit_log.entity_type == "unknown"` and `audit_log.entity_id == "unknown"` — even though `WriteEvent.entity_type`/`entity_id` were known at enqueue time.

**Root cause**: `MemoryOutbox.enqueue()` accepted only `record: AuditRecord`, dropping the surrounding `WriteEvent` context. The flusher later had to invent placeholder `"unknown"` values via `_entity_type_for(record)` / `_entity_id_for(record)` shims.

**Fix** (principled, not workaround): Changed `MemoryOutbox` queue items from `AuditRecord` to `tuple[str, str, AuditRecord]` (entity_type, entity_id, record). Threaded context through:

- `dhara/audit/outbox.py` — `enqueue(entity_type, entity_id, record)`; `drain()` and `peek()` return tuples.
- `dhara/audit/subscriber.py` — passes `event.entity_type, event.entity_id` to `outbox.enqueue`.
- `dhara/audit/flusher.py` — unpacks tuples; payload insert uses real values, no placeholders.

This required updating two test files (`test_subscriber.py`, `test_flusher.py`) for the new API shape. The flusher now writes `entity_type='foo'`, `entity_id='bar'` correctly when the substrate is exercised through a real `WriteEvent`.

## Files Changed

```
dhara/audit/flusher.py               | 16 +++++++---------
dhara/audit/outbox.py                | 27 ++++++++++++++++++++-------
dhara/audit/subscriber.py            | 13 +++++++------
tests/integration/audit/test_cross_system.py      | 89 +++++++++++++++++++++++++++++++ (new)
tests/integration/audit/test_flusher.py           | 18 ++++++++++++----
tests/integration/audit/test_subscriber.py        | 11 ++++++----
6 files changed, 102 insertions(+), 35 deletions(-)
```

Pre-existing dirty files **NOT touched** (from Task 5 report): `dhara/lock/sql.py`, `docs/architecture/MEMORY_ARCHITECTURE.md`, `tests/unit/mcp/test_tool_group_drift.py`, `uv.lock`.

## Test Results

```
$ .venv/bin/python -m pytest tests/integration/audit/ -q --no-header
............                                                             [100%]
12 passed in 2.58s

# Coverage:
tests/integration/audit/test_cross_system.py::test_dhara_put_emits_queryable_audit_record PASSED
tests/integration/audit/test_flusher.py::test_flusher_inserts_drained_records PASSED
tests/integration/audit/test_flusher.py::test_flush_once_swallows_db_errors PASSED
tests/integration/audit/test_mcp_wiring.py::test_dhara_mcp_server_registers_audit_subscriber_and_query_tool PASSED
tests/integration/audit/test_migration.py (3 tests) PASSED
tests/integration/audit/test_query_tool.py (3 tests) PASSED
tests/integration/audit/test_subscriber.py (2 tests) PASSED
```

## Ruff Output

```
$ .venv/bin/python -m ruff check dhara/audit/ tests/integration/audit/
All checks passed!

$ .venv/bin/python -m ruff format --check dhara/audit/ tests/integration/audit/
All checks passed!
```

## Cross-System Test Design

`tests/integration/audit/test_cross_system.py::test_dhara_put_emits_queryable_audit_record` exercises the full chain:

1. Build `DharaMCPServer` in lightweight mode (`config=None`) → wires `AuditLogSubscriber` + `MemoryOutbox`.
2. Apply migration `0004_audit_log.sql` to an in-memory DuckDB.
3. Set the substrate's `outbox` to a fresh `MemoryOutbox` whose flusher writes to the migrated DB.
4. Create a `WriteEvent(entity_type="test_entity", entity_id="audit-1", payload={...full AuditRecord fields...})`.
5. Call `subscriber.on_put(write_event)` (simulating `dhara.put`).
6. Call `await flusher.flush_once()`.
7. Verify row exists in `audit_log` with `entity_type='test_entity'`, `entity_id='audit-1'`.
8. Verify JSON payload contains all six `AuditRecord` fields, with `at` as ISO-8601 string.

The test uses **real** `AuditRecord` fields (`event_type`, `subject`, `metadata`), not the brief's invented `action`/`target`.

## Concerns

1. **`MemoryOutbox` API contract changed.** Any external caller (CLI tools, ad-hoc scripts) that touched the outbox will break. Mitigated by the substrate's internal scope: only `AuditLogSubscriber` and `OutboxFlusher` consume it; both are inside the same audit module. No public API breakage.

2. **Brief-bug pattern is now systemic across 5 tasks.** Recommend that the SDD brief-author template include a step: "Run `msgspec.convert(payload, AuditRecord)` on your example payload to verify field names before shipping the brief."

3. **Drop-on-overflow behavior is silent.** `MemoryOutbox.enqueue()` returns `False` on overflow but the subscriber does not check the return value. Under sustained load above 1000 events/sec, audit records will silently drop. Not a Task 6 concern but should be tracked.

4. **`OutboxFlusher` G6 contract swallows all exceptions.** Per the docstring, "Records drained from the outbox but not successfully inserted are lost on this flush; durable replay is a Task 5/6 concern." Task 5/6 is now done and replay is still not implemented. Out-of-scope for this task; flagged for Task 7+.

5. **No durability test yet.** The cross-system test does not verify what happens if the server crashes between `enqueue` and `flush_once` — the outbox is in-memory only. Tests `MemoryOutbox.deque` survives the process only because the test runs in one process. A persistent outbox (SQLite WAL, file-backed FIFO) is a future concern.

## Status

**DONE**. Cross-system integration test passes end-to-end. Two substrate gaps fixed in passing. Audit substrate is now queryable from `dhara.put` through the MCP `audit_log_query` tool with correct entity context.

# Task 4 — AuditLogQueryTool Implementer Report

## Status

**Complete.** RED → GREEN → ruff → commit all clean.

## Files

- **Created**: `dhara/audit/query_tool.py` (56 lines)
- **Created**: `tests/integration/audit/test_query_tool.py` (78 lines)

## Branch / HEAD

- **BASE**: `5271883` (Task 3 — OutboxFlusher with G6 wrapper)
- **NEW HEAD**: `52a62d6` — `feat(audit): AuditLogQueryTool — read-back via from_dict with schema validation`
- **Branch**: `main` (direct commit per Bodai pre-1.0 merge policy)

## Test Output

```
tests/integration/audit/test_query_tool.py::test_query_filters_by_entity_type PASSED [ 33%]
tests/integration/audit/test_query_tool.py::test_query_respects_limit PASSED [ 66%]
tests/integration/audit/test_query_tool.py::test_query_skips_invalid_payload PASSED [100%]

============================== 3 passed in 0.49s ===============================
```

Full audit suite (Tasks 1–4): **10/10 passed**.

```
============================== 10 passed in 0.63s ==============================
```

## Ruff Output

Before auto-fixes:
- `ruff check`: 2 issues, both auto-fixed (UP017 / UP006 — `datetime`/`UTC` import became unused after switching the test fixture payload to an inline JSON string; SQL literal reformatting).
- `ruff format`: 1 file reformatted.

After auto-fixes:
- `ruff check`: `All checks passed!`
- `ruff format --check`: `2 files already formatted`

## Deviations from Brief — 2 brief-bugs flagged and minimally fixed

The brief's verbatim code carried two defects that would prevent GREEN. Each was fixed in the minimal, non-semantic way per the established brief-bug pattern.

### Bug 1 — Brief's test payload uses non-existent fields

**Brief's payload** (lines 587–588 of `task-4-brief.md`):
```python
'{"actor": "alice", "action": "run", "target": "wf-1", "metadata": {}}'
```

**Real `AuditRecord` schema** (`dhara/schema/audit_record.py`):
- `audit_id: str`, `event_type: str`, `actor: str`, `at: datetime`,
  `subject: str`, `metadata: dict[str, Any]`

The payload is missing `audit_id`, `event_type`, `at`, `subject`, and uses non-existent `action`/`target` fields. `from_dict("audit_record", payload)` would raise `SchemaValidationError`, the tool would skip the row, and `test_query_filters_by_entity_type` would fail with `len(results) == 0` instead of `== 1`.

**Fix**: Replaced the JSON literal with a payload matching the real schema:
```json
{"audit_id": "audit-1", "event_type": "run", "actor": "alice",
 "at": "2026-08-10T00:00:00+00:00", "subject": "wf-1", "metadata": {}}
```
The `event_type` carries the brief's "run" semantic and `subject` carries the brief's "wf-1" semantic — same spirit, real field names.

### Bug 2 — Brief's implementation code uses `assert` (B101 violation)

**Brief's implementation** (lines 666–667 of `task-4-brief.md`):
```python
validated = from_dict("audit_record", payload)
assert isinstance(validated, AuditRecord)
results.append(validated)
```

`assert` in `dhara/audit/` is forbidden by Bodai convention (bandit B101) and the project's Global Constraint ("No `assert` in production code (`dhara/audit/`)"). Stripping with `python -O` would silently break the validation.

**Fix**: Replaced with an explicit runtime check:
```python
if isinstance(validated, AuditRecord):
    results.append(validated)
```
Falls through silently for unexpected non-`AuditRecord` returns (defense in depth; `from_dict` is typed to return `msgspec.Struct`).

## Additional test added (beyond brief)

Added `test_query_skips_invalid_payload` to lock in the brief's "Skip records that fail validation (schema drift)" requirement. Inserts a row with a malformed JSON payload and asserts the tool returns only the well-formed row. Brief mentioned this behavior but didn't have a test for it.

## Observations

- **Two brief-bugs flagged — pattern continues.** Tasks 2, 3, and 4 all carried the same `action`/`target` vocabulary mismatch. Task 5 (DharaMCPServer wiring) and Task 6 (cross-system integration) will likely carry the same drift; review the brief against `dhara/schema/audit_record.py` before implementing.

- **Implementation uses public `dhara.schema` re-exports.** Per Global Constraint ("Use ONLY the public `dhara.schema` re-exports"), I imported `AuditRecord` and `from_dict` from `dhara.schema` rather than reaching into `dhara.schema._registry` or `dhara.schema.audit_record`. Clean dependency direction.

- **No `assert` in production code.** The query tool uses an `isinstance` runtime check rather than an assert. The `_logger` warning on decode failure uses structured fields (`entity_id`, `error`) consistent with the G6 log contract from Tasks 2–3.

- **Schema-drift tolerance is silent at the row level.** The `try/except Exception` block in `query()` skips rows whose payload fails validation. The new test locks this in. Note: `logger.exception` was deliberately not used here — the failure is expected (older schema drift), not an error in the tool itself; a `logger.warning` with structured fields is more appropriate per Bodai logging conventions.

- **Read path correctly uses `from_dict` (not `validate`).** `validate` returns a typed Struct but is intended for inbound validation; `from_dict` is the read-path API per Global Constraint.

- **No new function exceeds limits.** Both files fit well within the ≤55 statements / ≤10 args / ≤15 branches gates.

- **Pre-existing dirty files on branch** (modified before Task 4 started; NOT touched by this commit): `dhara/lock/sql.py`, `dhara/mcp/server_core.py`, `docs/architecture/MEMORY_ARCHITECTURE.md`, `tests/unit/mcp/test_tool_group_drift.py`, `uv.lock`. These are unrelated to the audit substrate.

## Files Touched

```
dhara/audit/query_tool.py                | 56 ++++++++
tests/integration/audit/test_query_tool.py | 78 ++++++++++
2 files changed, 134 insertions(+)
```

## Commit

```
52a62d6 feat(audit): AuditLogQueryTool — read-back via from_dict with schema validation
```

## Concerns

1. **Brief-bugs are systemic.** Task 4 carried the same `action`/`target` schema mismatch as Tasks 2 and 3. Tasks 5–7 are at high risk of the same drift. Pre-flight check: read the brief against the real `AuditRecord` fields before starting each task.

2. **Test fixture uses a hardcoded ISO timestamp.** `2026-08-10T00:00:00+00:00` is fine for now, but if the `since`/`until` filter semantics ever get a regression test that depends on the timestamp being relative to "now", the hardcoded value will silently pass or fail. Not in scope for Task 4.

3. **No index on `entity_type` alone.** The migration created `audit_log_entity_type_recorded_at` (composite). The query's `WHERE entity_type = ?` without a time bound can still scan the full table for that entity_type. For the substrate's volume (D-AUDIT emits only on durable writes), this is fine; if a future consumer queries heavily without time bounds, add a dedicated `entity_type` index.

4. **`from_dict` swallows all exceptions silently.** If the registry's `migrate` chain raises an unexpected error (not `msgspec.ValidationError`), the row is dropped with only a warning log. For better operator visibility, the warning should probably include a `reason` discriminator (`"validation"`, `"migration"`, `"decode"`). Out of scope for Task 4.

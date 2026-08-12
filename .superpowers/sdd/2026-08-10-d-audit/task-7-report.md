# Task 7 implementation report

## Status

PARTIAL / PASS WITH UNEXPECTED GATE DEBT. The completion report was committed in Dhara and
the audit integration suite passes. Crackerjack did not reach the expected 15/16 fast-hook
state: it stopped in comprehensive hooks at 9/11 because `ty` reported 27 issues and
`refurb` reported 1 issue. The portfolio source file is owned by the Mahavishnu repository,
not Dhara, and already had unrelated working-tree edits; its D-AUDIT row was updated but was
not committed to avoid bundling pre-existing changes.

## Base and resulting HEAD

- Review base: `14ca859d6328611cbdbe5ad91b4960cc258c8b9d`
- New Dhara HEAD: `ae177ea`

## Crackerjack output (truncated)

```text
Crackerjack v0.70.3
project: dhara @ main
Comprehensive Hooks - Type, security, and complexity checking
pyscn ✅ betterleaks ✅ cohesion ✅ ty ❌ check-jsonschema ✅ creosote ✅
lychee ✅ linkcheckmd ✅ semgrep ✅ pymetrica ✅ refurb ❌
Comprehensive hooks attempt 1: 9/11 passed
- ty: FAILED, issues=27
- refurb: FAILED, issues=1
Workflow failed: comprehensive_hooks
```

## Pytest output

```text
............                                                             [100%]
12 passed in 4.28s
```

## Files committed

- `docs/feature-tracking/2026-08-10-d-audit.md`

Commit: `ae177ea docs(audit): completion report + portfolio status update for D-AUDIT`

## Deviations

- The expected portfolio file does not exist in the Dhara repository. It is at
  `/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md`.
  The D-AUDIT row was changed from `parked` to `adopted` with a completion-report link, but
  that file was not committed because Mahavishnu had pre-existing unrelated edits and the
  requested commit was scoped to Dhara main.
- The Task 7 brief expected 10 tests; the shipped suite contains 12 and all 12 pass.
- Crackerjack failure differs from the anticipated pip-audit-only `cryptography 49.0.0`
  debt. It stopped earlier on `ty` and `refurb`; no Task 7 code fix was authorized.

## Observations

- Pre-existing Dhara changes were left untouched: `dhara/lock/sql.py`,
  `docs/architecture/MEMORY_ARCHITECTURE.md`, `tests/unit/mcp/test_tool_group_drift.py`,
  `uv.lock`, and `.superprofits/` content.
- The completion report records the actual 12-test suite and the current quality-gate debt.

## Follow-up: Wire OutboxFlusher into DharaMCPServer startup

### Status

PASS. The audit substrate is now complete end-to-end: subscribers enqueue
into `MemoryOutbox`, and a periodic background task drains it into
`audit_log`. `AuditLogQueryTool.query()` returns real rows in production.

### HEAD

- Review base for this follow-up: `ae177ea` (the prior task-7 commit)
- New Dhara HEAD: `8f66fb34380aedd9a7b6bae80034e394550befb9`
- Commit: `8f66fb3 feat(audit): wire OutboxFlusher periodic flush into DharaMCPServer startup`
- Files: `dhara/audit/flusher.py` (+30), `dhara/mcp/server_core.py` (+24),
  `tests/integration/audit/test_periodic_flush.py` (new, +106)

### Pytest output (audit integration suite, 14 tests)

```
$ .venv/bin/python -m pytest tests/integration/audit/ -q --timeout=60
..............                                                           [100%]
14 passed in 2.85s
```

All 14 tests pass, including the two new wiring tests:

- `test_periodic_flush.py::test_periodic_flush_loop_drains_outbox_into_audit_log`
  — fires three `subscriber.on_put` events, awaits the loop, asserts
  `audit_log` receives 3 rows with `audit-0..audit-2` entity_ids. **GREEN**
  (this test fails on `ae177ea` because no production caller ever invokes
  `flush_once`).
- `test_periodic_flush.py::test_periodic_flush_loop_task_is_stored_on_server`
  — verifies `_register_tools` retains the background task on
  `self._audit_flush_task` for future shutdown cancellation. **GREEN**.

The pre-existing `test_mcp_wiring.py::test_dhara_mcp_server_registers_audit_subscriber_and_query_tool`
still passes because the wiring was written to *guard* on a running
event loop (sync `__init__` path used by that test) rather than crashing
with `RuntimeError: no running event loop`.

### Ruff output

```
$ .venv/bin/python -m ruff check dhara/audit/flusher.py \
    dhara/mcp/server_core.py tests/integration/audit/test_periodic_flush.py
All checks passed!
```

After two lint iterations:

1. Removed an unused `# noqa: BLE001` directive in `flusher.py` (ruff RUF100).
1. Replaced the over-broad `with pytest.raises(BaseException):` in the
   cleanup test with `pytest.raises(asyncio.CancelledError)` (ruff B017 —
   "blind exception assertion").

### Confirmation: audit_log receives rows

`test_periodic_flush_loop_drains_outbox_into_audit_log` directly queries
`audit_log` after the loop has run and verifies both row count (3) and
identity (`{audit-0, audit-1, audit-2}`). The full 14-test audit suite
now exercises the end-to-end flow:

```
subscriber.on_put -> MemoryOutbox.enqueue -> periodic_flush_loop ->
    OutboxFlusher.flush_once -> audit_log INSERT -> AuditLogQueryTool.query
```

### Wiring details

- **New public API** in `dhara/audit/flusher.py`:
  `async def periodic_flush_loop(flusher, interval_seconds=0.1)` —
  loops `await flusher.flush_once()` then `await asyncio.sleep(...)`,
  swallows every exception per the G6 contract and logs via the Oneiric
  logger with structured `exception_type` context.
- **Server init** (`DharaMCPServer.__init__`): declares
  `self._audit_flush_task: asyncio.Task[None] | None = None` so the
  attribute is always present for clean shutdown.
- **`_register_tools` wiring** (inside the existing
  `if self._storage_conn is not None:` block, immediately after the
  `audit_record_query` tool is registered): gates on
  `asyncio.get_running_loop()` — production callers (FastMCP's running
  loop) schedule the task; sync-construction callers (`test_mcp_wiring`,
  lightweight audit-only construction) leave it as `None`.

### Deviations

- The integration suite was chosen over a full `pytest tests/integration`
  sweep because broader runs hit the 300s tool timeout in the parent
  Mahavishnu session; 14/14 audit tests is well above the brief's 13+
  requirement and exercises every audit-side surface.
- Pre-existing dirty files (`dhara/lock/sql.py`,
  `docs/architecture/MEMORY_ARCHITECTURE.md`,
  `tests/unit/mcp/test_tool_group_drift.py`, `uv.lock`,
  `.superprofits/` content) remain untouched per the commit scope.

### Observations

- The `# noqa: BLE001` initial directive was overcautious — ruff's
  RUF100 rule flagged the unused comment. Replaced with a plain code
  comment ("G6 contract: never raise") that documents intent without
  suppressing a non-existent warning.
- `pytest.raises(BaseException)` is a lint smell: CancelledError is the
  only exception `Task.cancel()` triggers on `await task`, and asserting
  on it is exact.
- The `asyncio.get_running_loop()` guard is the simplest way to keep the
  sync `test_mcp_wiring` test alive without adding an event-loop fixture;
  the brief's `DharaMCPServer(storage_conn=conn, audit_outbox=outbox)`
  construction is tested purely as a registration check, no loop needed.
- G6 contract is now satisfied at two layers: `OutboxFlusher.flush_once`
  absorbs DB errors locally, *and* `periodic_flush_loop` catches
  anything the inner loop could still propagate, so a permanent failure
  mode cannot crash the host FastMCP server.

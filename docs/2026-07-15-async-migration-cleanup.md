# Async Migration Cleanup Plan

> **Active plan.** Supersedes the incorrect removal claims in `docs/LEGACY_COMPATIBILITY_AND_REMOVAL_PLAN.md`.
> Created 2026-07-15 after drift-sync audit found the historical plan's "removed in 0.11.0" claims were factually wrong.

## Purpose

Close the remaining gaps in the async-first migration so that:

1. `FileStorage` is genuinely deleted (not just claimed).
2. The CLI / `__main__.py` actually run async.
3. The legacy `bin/db_renumber.py` (and friends) stop using `dhara.connection.Connection`.
4. The deprecated `event_loop` fixture leaves the test suite.
5. Druva compatibility aliases stop appearing in core modules.
6. Tests targeting the new async surface exist and pass.

This plan is the single source of truth for the actual remaining cleanup; the historical
`docs/LEGACY_COMPATIBILITY_AND_REMOVAL_PLAN.md` is now marked "do not cite for current state."

## Scope

### In scope (verified still remaining as of 2026-07-15)

| # | Task | Files | Risk | Status |
|---|------|-------|------|--------|
| 1 | Port all `FileStorage` callers to async and delete `dhara/storage/file.py` | See Task 1 sub-tasks 1a–1l | **HIGH** | Open |
| 2 | Convert `dhara/cli.py` to async entry point | `dhara/cli.py` | Medium | Open |
| 3 | Convert `dhara/__main__.py` to async entry point | `dhara/__main__.py` | Medium | Open |
| 4 | Convert `bin/db_renumber.py` to `AsyncConnection` (currently uses `from dhara.connection import Connection`) | `bin/db_renumber.py` | Low (also repairs pre-existing ModuleNotFoundError bug) | Open |
| 5 | Move Druva aliases out of core (currently `dhara/core/connection.py`, `dhara/core/config.py`, `dhara/config/__init__.py`) into a dedicated compat module | `dhara/core/connection.py`, `dhara/core/config.py`, `dhara/config/__init__.py` | Low | Open |
| 6 | Remove deprecated `event_loop` fixture from `tests/conftest.py:111` | `tests/conftest.py` | Low | Open |

### Out of scope (already done)

- Tasks 1–4, 7, 8, 10–16 of the original `2026-05-31-dhara-async-first-plan.md` are verified done (see plan annotations).
- Phases 2, 3, 5, 6, 7 of the remediation plan are verified done (see phase annotations).

### Out of scope (deferred to a separate plan)

- `dhara.persistent_dict` / `dhara.persistent_list` legacy aliases — needs an audit of `examples/backup_example.py:25` and other call sites before deletion. Defer until a "legacy alias sweep" plan exists.
- Async conversion of `tests/test_core_connection_methods.py`, `tests/test_mcp_kv_timeseries.py`, `tests/test_mcp_server_core.py`.
- Crackerjack `DharaAdapterLearner` MCP-client rewrite (Option B) — lives in the crackerjack repo, not dhara.

## Detailed Tasks

### Task 1: Port callers and delete `FileStorage`

**Risk: HIGH.** Originally scoped as a single-file delete, the scope audit revealed
`FileStorage` is imported across 10 production modules, 13 test files, 1 example,
2 benchmarks, and 1 unrelated setup script. Estimated 12 commits across sub-tasks 1a–1l.

**Pre-existing breakage to repair:**

- `examples/backup_example.py` already imports `dhara.file_storage` which does not
  exist (already broken at HEAD). Delete the file outright (sub-task 1k).

#### Task 1a: Verify `AsyncSqliteStorage` covers all `FileStorage` use cases

Before porting, confirm `AsyncSqliteStorage` (or equivalent async backend) supports
every operation pattern currently used by callers: `__enter__/__exit__`, `readonly`
mode, `root[key]` get/set, `len()`, iteration, and connection-bound `Connection`
usage in `dhara/core/connection.py:80-82`. If a behavior is missing, decide whether
to extend `AsyncSqliteStorage` or create a new `AsyncFileStorage` that wraps the
Durus file format. This decision drives every subsequent sub-task.

**Acceptance criteria:**

- Decision recorded (extend vs. new module).
- If new module: `dhara/storage/file_async.py` exists with a documented API.

#### Task 1b: Port `dhara/backup/` (catalog, manager, cli, restore)

4 modules import `FileStorage`:

- `dhara/backup/catalog.py:23`
- `dhara/backup/manager.py`
- `dhara/backup/cli.py`
- `dhara/backup/restore.py`

Replace each with the chosen async backend (1a). Preserve public APIs; if any
function returned sync context managers, change return type to `AsyncIterator` /
awaitable.

**Acceptance criteria:**

- `grep -n "FileStorage" dhara/backup/*.py` returns nothing.
- Backup CLI subcommands run end-to-end against the async backend.

#### Task 1c: Port `dhara/mcp/server_core.py`

3 references:

- Line 48 (import)
- Lines 190–191 (default storage factory)
- Line 947 (`with FileStorage(catalog_path, readonly=True) as storage:`)

Replace with the async backend; ensure `await storage.__aenter__()` and the
catalog path is consistent with the backup port (1b).

#### Task 1d: Port `dhara/core/connection.py:80-82`

The sync-storage factory path used by `Connection`:

```python
from dhara.storage.file import FileStorage
storage = FileStorage(storage)
```

Replace with the async backend. `AsyncConnection.new(...)` is the canonical
constructor; ensure this factory is only invoked from async call sites.

#### Task 1e: Port `dhara/security/signing.py:242-246`

```python
from dhara.storage import FileStorage
base_storage = FileStorage("data.dhara")
```

Replace with async backend. Verify the signing flow still produces the same
signatures (this is security-critical — do not change signature semantics).

#### Task 1f: Port `dhara/shell/__init__.py`

Docstring references at lines 42, 44. Update examples to the async backend.
If the shell module constructs a `FileStorage` at runtime, port that too.

#### Task 1g: Port `dhara/cli.py`

`dhara/cli.py` has 5 reference sites (lines 62, 87, 377, 408, 455) plus a comment at line 225.
This overlaps with Task 2; sub-task 1g ports the storage layer while Task 2
converts the entry point to `asyncio.run(cli_async())`. Coordinate to avoid
duplicate edits — Task 2 should land on top of 1g.

#### Task 1h: Port `dhara/__main__.py`

References at lines 212, 340, 344, 356, 364, 382, 452 plus imports. Overlaps
with Task 3; coordinate with Task 3 to avoid duplicate edits.

#### Task 1i: Delete `dhara/storage/file.py` and update re-exports

- `git rm dhara/storage/file.py`
- `dhara/__init__.py:49,70` — remove `FileStorage` from imports and `__all__`
- `dhara/storage/__init__.py:33` — remove `"FileStorage"` from `__all__`
- `dhara/storage/__init__.py:20` — remove `from dhara.storage.file import FileStorage`
- `dhara/storage/__init__.py:5` — update module docstring (drop FileStorage mention)

#### Task 1j: Update tests

Test files referencing `FileStorage`:

- `tests/conftest.py`
- `tests/test_main.py`
- `tests/test_cli.py`
- `tests/test_storage_file.py` — DELETE (this entire test module is for the removed class)
- `tests/test_storage_simple.py`
- `tests/test_mcp_server_core.py`
- `tests/test_backup_cli.py`
- `tests/test_backup_catalog.py`
- `tests/test_backup_manager_actual.py`
- `tests/test_backup_restore.py`
- `tests/test_core_connection_methods.py`
- `tests/unit/test_server_core.py`
- `tests/integration/mcp/test_http_crud_routes.py`
- `tests/integration/test_backup_restore_integration.py`

For each, port the test to use the async backend selected in 1a. Async tests
inherit `asyncio_mode = "auto"` (see Task 6). Verify each port with `pytest <file>`.

#### Task 1k: Delete broken example and orphan script

- `examples/backup_example.py` — already broken (imports `dhara.file_storage` which
  does not exist). DELETE outright; do not attempt repair.
- `setup_backup_system.py` — unrelated setup script that imports `FileStorage`.
  Investigate whether this script is run by any tests/CI; if not, DELETE.

#### Task 1l: Update benchmarks

- `benchmarks/conftest.py`
- `benchmarks/test_fallback_performance.py`

Port to async backend. Re-run benchmarks; record baseline metrics before/after.

**Task 1 acceptance criteria (overall):**

- `dhara/storage/file.py` does not exist.
- `grep -rn "FileStorage" dhara/ --include="*.py"` returns no production hits.
- All 13 test files updated and green.
- Benchmarks re-baselined.
- Examples and orphan scripts removed.

---

### Task 2: Async CLI entry point

**Files:**

- Modify: `dhara/cli.py`

After Task 1g lands (storage port), `dhara/cli.py` still uses sync `Connection` at
lines 61, 86, 375, 407, 453. Convert commands to `await conn.get(...)` and route
through `asyncio.run(...)` at the CLI boundary.

**Steps:**

1. Confirm Task 1g is merged.
2. Inventory every sync `Connection(...)` usage in `dhara/cli.py`.
3. Replace with `await AsyncConnection.new(...)` from `dhara.core.connection`.
4. Wrap `cli()` in `asyncio.run(cli_async())`.
5. Update CLI smoke tests if any.

**Acceptance criteria:**

- `dhara --help` works in an async event loop.
- All CLI subcommands reach storage via `await`.
- No sync `Connection` import remains in `dhara/cli.py`.

---

### Task 3: Async `__main__.py`

**Files:**

- Modify: `dhara/__main__.py`

After Task 1h lands, convert `python -m dhara` to an async entry point. Same
shape as Task 2. Verify the `--storage-class` help text (line 212) is updated
to point at the async backend.

---

### Task 4: Convert `bin/db_renumber.py`

**Files:**

- Modify: `bin/db_renumber.py`

**Pre-existing bug to repair:** `bin/db_renumber.py:13` currently has
`from dhara.connection import Connection` — but `dhara/connection.py` does not
exist (the canonical module is `dhara/core/connection.py`). The script raises
`ModuleNotFoundError` on every execution. This migration repairs that
pre-existing bug as a side effect.

**Steps:**

1. Replace line 13 with `from dhara.core.connection import AsyncConnection`.
2. Add `await` to every `Connection` call.
3. Wrap the body in `async def main()` and invoke via `asyncio.run(main())`.

**Acceptance criteria:**

- `python bin/db_renumber.py --help` runs without `ModuleNotFoundError`.
- All storage operations are awaited.

---

### Task 5: Move Druva aliases out of core

**Files:**

- Modify: `dhara/core/connection.py`
- Modify: `dhara/core/config.py`
- Modify: `dhara/config/__init__.py`
- Modify: `dhara/config/defaults.py`

The scope audit found only **two** true aliases (not three):

- `DruvaSettings = DharaSettings` at `dhara/core/config.py:247`
- `DruvaConfig = DharaConfig` at `dhara/config/defaults.py:198` (re-exported in
  `dhara/config/__init__.py:16,34`)

**Note (audit correction):** `DruvaKeyError` is **NOT** an alias. It is the
canonical error class defined in `dhara/error.py:14`. The references at
`dhara/core/connection.py:17,239,601` are legitimate imports and usages of the
canonical class. The original plan incorrectly listed `DruvaKeyError` as an
alias to extract; leave it as-is.

Create a dedicated compat module (e.g., `dhara/_compat/druva.py`) that re-exports
`DruvaSettings` and `DruvaConfig` under their historical names. Replace the
inline aliases in core modules with imports from the compat module.

**Acceptance criteria:**

- `grep -n "DruvaSettings\|DruvaConfig" dhara/core/ dhara/config/` returns only
  the compat module's re-exports and the compat module's own consumers.
- `DruvaKeyError` remains canonical in `dhara/error.py` and is imported by all
  consumers unchanged.

---

### Task 6: Remove deprecated `event_loop` fixture

**Files:**

- Modify: `tests/conftest.py` (line 111)

`tests/conftest.py:111` still defines `def event_loop():` — deprecated since
pytest-asyncio 0.21. Replace with `asyncio_mode = "auto"` in `pyproject.toml`
if not already set, and remove the function.

---

## Dependency Order (recommended execution sequence)

After scope-audit correction, the recommended execution order is:

1. **Task 6 (event_loop fixture)** — independent, safe; enables async-mode test infrastructure used by later tasks.
2. **Task 5 (Druva aliases)** — independent, small; reduces noise in subsequent diffs.
3. **Task 4 (db_renumber.py)** — small, standalone, also fixes a pre-existing `ModuleNotFoundError` bug.
4. **Task 1 (FileStorage port)** — bulk of the work, 12 sub-tasks (1a → 1l). Sequence the sub-tasks in numerical order; 1a must complete before 1b–1l begin.
5. **Task 2 (async CLI)** — depends on Task 1 sub-task 1g (storage layer in `dhara/cli.py`).
6. **Task 3 (async `__main__`)** — depends on Task 1 sub-task 1h (storage layer in `dhara/__main__.py`) and Task 2 (CLI patterns).

Dependency graph (textual):

```
Task 6 (event_loop)            ── independent
Task 5 (Druva aliases)         ── independent
Task 4 (db_renumber.py)        ── independent (also repairs ModuleNotFoundError)
Task 1 (FileStorage port)
   └─ 1a  Verify AsyncSqliteStorage / decide on async backend
        ├─ 1b  Port dhara/backup/  (catalog, manager, cli, restore)
        ├─ 1c  Port dhara/mcp/server_core.py
        ├─ 1d  Port dhara/core/connection.py:80-82
        ├─ 1e  Port dhara/security/signing.py:242-246
        ├─ 1f  Port dhara/shell/__init__.py
        ├─ 1g  Port dhara/cli.py (storage only)
        ├─ 1h  Port dhara/__main__.py (storage only)
        ├─ 1i  Delete dhara/storage/file.py + update re-exports
        ├─ 1j  Update 13 test files
        ├─ 1k  Delete examples/backup_example.py and setup_backup_system.py
        └─ 1l  Update benchmarks/conftest.py and benchmarks/test_fallback_performance.py
Task 2 (async CLI)             ── depends on Task 1.1g
Task 3 (async __main__)        ── depends on Task 1.1h and Task 2
```

## Definition of Done

- `dhara/storage/file.py` deleted; `FileStorage` no longer importable from `dhara`.
- `dhara/cli` and `python -m dhara` run through an async event loop.
- `bin/db_renumber.py` uses `AsyncConnection` and no longer raises `ModuleNotFoundError`.
- `tests/conftest.py` no longer defines `event_loop`; `asyncio_mode = "auto"` configured.
- `dhara/core/connection.py`, `dhara/core/config.py`, `dhara/config/__init__.py` no longer define Druva aliases inline (compat module owns them). `DruvaKeyError` remains canonical.
- Full `pytest` suite green.
- Crackerjack quality gates pass.

## References

- `docs/superpowers/plans/2026-05-31-dhara-async-first-plan.md` — original async-first plan with verified-done annotations.
- `docs/LEGACY_COMPATIBILITY_AND_REMOVAL_PLAN.md` — historical (now struck; do not cite for current state).
- `docs/implementation-plans/DHARA_REMEDIATION_AND_CANONICALIZATION_PLAN.md` — orthogonal plan covering packaging/lifecycle/config/MCP consolidation.

## Plan Amendment (2026-07-15)

Three corrections were applied based on a scope audit:
1. Task 1 expanded from a single-file delete into a 12-sub-task port
2. Task 5 (db_to_py3k.py) deleted (file doesn't exist)
3. Task 7 (Druva aliases) reduced scope: DruvaKeyError is canonical, not an alias

Original scope audit: see [audit transcript in this session's conversation log]
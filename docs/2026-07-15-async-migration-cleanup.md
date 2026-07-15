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

| # | Task | Files | Status |
|---|------|-------|--------|
| 1 | Delete `dhara/storage/file.py` and remove `FileStorage` from `dhara/__init__.py` exports | `dhara/storage/file.py`, `dhara/__init__.py` | Open |
| 2 | Convert `dhara/cli.py` to async entry point | `dhara/cli.py` | Open |
| 3 | Convert `dhara/__main__.py` to async entry point | `dhara/__main__.py` | Open |
| 4 | Convert `bin/db_renumber.py` to `AsyncConnection` (currently uses `from dhara.connection import Connection`) | `bin/db_renumber.py` | Open |
| 5 | Convert `bin/db_to_py3k.py` to `AsyncConnection` (TBD; verify before scheduling) | `bin/db_to_py3k.py` | Open |
| 6 | Remove deprecated `event_loop` fixture from `tests/conftest.py:111` | `tests/conftest.py` | Open |
| 7 | Move Druva aliases out of core (currently `dhara/core/connection.py`, `dhara/core/config.py`, `dhara/config/__init__.py`) into a dedicated compat module | `dhara/core/connection.py`, `dhara/core/config.py`, `dhara/config/__init__.py` | Open |

### Out of scope (already done)

- Tasks 1–4, 7, 8, 10–16 of the original `2026-05-31-dhara-async-first-plan.md` are verified done (see plan annotations).
- Phases 2, 3, 5, 6, 7 of the remediation plan are verified done (see phase annotations).

### Out of scope (deferred to a separate plan)

- `dhara.persistent_dict` / `dhara.persistent_list` legacy aliases — needs an audit of `examples/backup_example.py:25` and other call sites before deletion. Defer until a "legacy alias sweep" plan exists.
- Async conversion of `tests/test_core_connection_methods.py`, `tests/test_mcp_kv_timeseries.py`, `tests/test_mcp_server_core.py`.
- Crackerjack `DharaAdapterLearner` MCP-client rewrite (Option B) — lives in the crackerjack repo, not dhara.

## Detailed Tasks

### Task 1: Delete FileStorage

**Files:**

- Delete: `dhara/storage/file.py`
- Modify: `dhara/__init__.py` (remove `FileStorage` from imports and `__all__`)
- Verify: `grep -r "FileStorage" dhara/ --include="*.py"` returns only the deletion candidate itself, no remaining references.

**Steps:**

1. Confirm no remaining internal callers (CLI, MCP, backup, bin/).
2. Remove `FileStorage` import and `"FileStorage"` from `__all__` in `dhara/__init__.py`.
3. `git rm dhara/storage/file.py`.
4. Run the test suite to ensure no surprise dependents.

**Acceptance criteria:**

- `dhara/storage/file.py` no longer exists.
- `FileStorage` not importable from `dhara`.
- Tests green.

### Task 2: Async CLI entry point

**Files:**

- Modify: `dhara/cli.py`

`dhara/cli.py` currently imports sync `Connection` from `dhara.core.connection` at lines 61, 86, 375, 407, 453. Convert commands to `await conn.get(...)` and route through `asyncio.run(...)` at the CLI boundary.

**Steps:**

1. Inventory every sync `Connection(...)` usage in `dhara/cli.py`.
2. Replace with `await AsyncConnection.new(...)` from `dhara.core.connection`.
3. Wrap `cli()` in `asyncio.run(cli_async())`.
4. Update CLI smoke tests if any.

**Acceptance criteria:**

- `dhara --help` works in an async event loop.
- All CLI subcommands reach storage via `await`.
- No sync `Connection` import remains in `dhara/cli.py`.

### Task 3: Async `__main__.py`

**Files:**

- Modify: `dhara/__main__.py`

Same shape as Task 2 but for the `python -m dhara` entry point.

### Task 4: Convert `bin/db_renumber.py`

**Files:**

- Modify: `bin/db_renumber.py`

Current line 13: `from dhara.connection import Connection`. Replace with `from dhara.core.connection import AsyncConnection` and add `await` to all calls. This script is standalone — wrap body in `async def main()` and call via `asyncio.run`.

### Task 5: Convert `bin/db_to_py3k.py`

**Files:**

- Modify: `bin/db_to_py3k.py`

Verify current import surface first; apply same async conversion pattern as Task 4.

### Task 6: Remove deprecated `event_loop` fixture

**Files:**

- Modify: `tests/conftest.py` (line 111)

`tests/conftest.py:111` still defines `def event_loop():` — deprecated since pytest-asyncio 0.21. Replace with `asyncio_mode = "auto"` in `pyproject.toml` if not already set, and remove the function.

### Task 7: Move Druva aliases out of core

**Files:**

- Modify: `dhara/core/connection.py` (line 17, 239, 601: `DruvaKeyError`)
- Modify: `dhara/core/config.py` (line 247: `DruvaSettings = DharaSettings`)
- Modify: `dhara/config/__init__.py` (line 16, 34: `DruvaConfig`)

Create a dedicated compat module (e.g., `dhara/_compat/druva.py`) that re-exports these symbols under their historical names. Replace the inline aliases in core modules with imports from the compat module — or, if compat is only the symbol alias, move the alias definitions there. The audit verified these three locations still expose Druva names in core.

## Dependency Order

```
Task 1 (delete FileStorage)
  └─ Task 2 (CLI async — was importing FileStorage transitively)
       └─ Task 3 (__main__ async)
            └─ Task 4 (bin/db_renumber.py async)
                 └─ Task 5 (bin/db_to_py3k.py async — verify first)
Task 6 (conftest event_loop) — independent; can run any time
Task 7 (Druva compat extraction) — independent; can run any time
```

## Definition of Done

- `dhara/storage/file.py` deleted; `FileStorage` no longer importable from `dhara`.
- `dhara.cli` and `python -m dhara` run through an async event loop.
- `bin/db_renumber.py` (and `db_to_py3k.py` if applicable) use `AsyncConnection`.
- `tests/conftest.py` no longer defines `event_loop`; `asyncio_mode = "auto"` configured.
- `dhara/core/connection.py`, `dhara/core/config.py`, `dhara/config/__init__.py` no longer define Druva aliases inline.
- Full `pytest` suite green.
- Crackerjack quality gates pass.

## References

- `docs/superpowers/plans/2026-05-31-dhara-async-first-plan.md` — original async-first plan with verified-done annotations.
- `docs/LEGACY_COMPATIBILITY_AND_REMOVAL_PLAN.md` — historical (now struck; do not cite for current state).
- `docs/implementation-plans/DHARA_REMEDIATION_AND_CANONICALIZATION_PLAN.md` — orthogonal plan covering packaging/lifecycle/config/MCP consolidation.
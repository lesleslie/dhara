# Dhara Test Coverage Summary

## Current Status (refreshed 2026-09-05)

| Metric | Value |
|--------|-------|
| **Total coverage** | **88.03%** (10,440 / 11,638 statements) |
| Tests passing | 3,825 |
| Tests skipped | 140 |
| Tests failing | 3 (all version-consistency, unrelated to coverage) |
| Modules at 0% | 0 |
| Coverage gate (`--cov-fail-under`) | 80.49% — exceeded |

Run with: `pytest --cov=dhara --cov-report=term-missing`.

## Coverage Push Session (2026-09-05)

Five recommendations from the prior coverage audit were addressed in one session:

### 1. Removed zero-coverage duplicate: `dhara/config/security_test.py` ✅

This file was a leftover from the June 2026 durus-elimination refactor. It was
not imported anywhere in the codebase (grep returned zero hits), and coverage
reported it at 0% (217 statements, 217 missing). Removed; the live module is
`dhara/config/security.py`.

Commit: `fix(docs): remove stale dhara/config/security_test.py duplicate`

### 2. Pushed `dhara/lock/in_memory.py` from 13.6% to 98% ✅

Test file `tests/unit/lock/test_in_memory.py` (41 tests) now exercises every
public branch:

- `try_acquire` (9 cases): defaults, explicit owner/token, ttl, metadata,
  permanent, mutual-exclusion raise, duplicate-returns-none,
  duplicate-permanent-raises, distinct-keys-independent.
- `async acquire` (7 cases): first-try, wait-then-succeed, timeout-expires,
  timeout-zero-immediate, timeout-none-blocks, mutual-exclusion raise,
  permanent-holder.
- `try_release` (4 cases), `release` (5 cases), `heartbeat` (8 cases),
  `get` (2 cases), `list_keys` (4 cases).

The 2 missing lines are defensive `except ValueError` translation in the
acquire polling loop — practically unreachable through the public API.

Commit: `test(lock): add comprehensive InMemoryDharaLock coverage`

### 3. Pushed `dhara/server/server.py` from 17.2% to 79% ✅

Test file `tests/integration/test_storage_server.py` (62 tests, 5 macOS-skipped)
now covers:

- End-to-end smoke test: spin up StorageServer on an ephemeral port,
  connect via ClientStorage, commit + load a packed record.
- Both server modes: `serve()` (single-threaded, threads=0) and
  `serve_threaded()` (multi-threaded, threads>0).
- Raw-socket protocol: every `handle_*` command (N, M, L, C, S, P, Q, V, B)
  exercised via hand-rolled wire bytes; STATUS_OKAY / STATUS_INVALID /
  STATUS_KEYERROR paths, client invalidation propagation, ConflictError
  during commit, ReadConflictError during load, the empty-tdata commit-abort
  path, and the already-in-progress packer branch.
- Two-client interactions: invalid OID reuse triggers ClientError.
- TLS handshake: StorageServer rejects plain-text connections when
  tls_enabled=True.
- StorageServer.__init__: threads=-1 cpu*2 calculation, tls_enabled
  validation, address= accepting a pre-built SocketAddress.
- SocketAddress subclasses: HostPortAddress (IPv4+IPv6), UnixAbstractAddress,
  UnixDomainSocketAddress (umask, stale-file cleanup, ownership),
  InheritedSocket. Unix-domain bind tests are marked `needs_short_sun_path`
  and skipped on macOS where sun_path is 104 bytes and pytest tmp paths
  routinely exceed that limit.
- `wait_for_server` (success and timeout), `_get_cpu_count` (int / None /
  exception fallback), `run()` picks serve vs serve_threaded correctly.
- `_handle_command_threaded` read/write dispatch: lock-state tracing via
  a wrapping RLock verifies read commands skip the storage lock while
  write commands acquire it.

**Production fix shipped alongside**: `dhara/storage/sqlite.py` was passing
`check_same_thread=True` (default) to `sqlite3.connect()`. The threaded
StorageServer dispatches handlers to a ThreadPoolExecutor worker thread,
so any write command from a worker thread crashed with `'SQLite objects
created in a thread can only be used in that same thread.'` Concurrency
is bounded by the server's `storage_lock` for write commands, and SQLite
serialises per-connection access on its own. Setting `check_same_thread=False`
is therefore safe and lets the threaded server actually work.

Commits:
- `fix(storage): allow SqliteStorage to be used across worker threads`
- `test(integration): add comprehensive StorageServer coverage`

The remaining ~21% gaps are:
- macOS-skipped unix-domain code (~50 lines; would be covered on Linux).
- Windows-specific imports (lines 53–59).
- systemd socket activation paths (lines 409 etc.).
- Defensive branches unreachable in Python 3 (e.g. line 599
  `else: command_code = command_byte` — Python 3 socket.recv always
  returns bytes, so the int branch is always taken).

### 4. Pushed `dhara/backup/scheduler.py` from 72% to 90% ✅

The async variant `AsyncBackupScheduler` was under-tested. New tests in
`tests/test_async_backup_scheduler.py`:

- `_run_job_async` for each BackupType (FULL, INCREMENTAL, DIFFERENTIAL).
- Unknown backup type surfaces as `failed` with the failure callback.
- `on_success` / `on_failure` callback invocation.
- Cloud-upload-failed-but-still-success path.
- `run_job_async` skipped when disabled; returns None for unknown names.
- `start_async` / `stop_async` lifecycle (idempotent).
- `_get_verification_engine` lazy init + caching.
- `close()` releases the verification engine.

Commit: `test(scheduler): push AsyncBackupScheduler coverage from 72% to 90%`

### 5. Refreshed this worklog ✅

This file.

## Bottom 10 Modules (current)

| Coverage | Module | Notes |
|----------|--------|-------|
| 51.6% | `dhara/lock/postgres.py` | Real SQL backend; needs Postgres fixture |
| 57.9% | `dhara/backup/restore.py` | Restore path |
| 58.2% | `dhara/storage/postgres.py` | Real SQL backend |
| 65.2% | `dhara/backup/verification.py` | Backup verification |
| 65.7% | `dhara/events/subscribers/audit_log_subscriber.py` | Small file, mostly untested |
| 68.6% | `dhara/tools/mermaid_validator/renderer.py` | Tooling |
| 69.0% | `dhara/__main__.py` | CLI entry — many subcommands uncovered |
| 70.5% | `dhara/lock/routes.py` | Lock HTTP routes |
| 74.2% | `dhara/storage/async_file.py` | Small thin wrapper |
| 77.2% | `dhara/mcp/adapter_tools.py` | MCP glue |

These are all reasonable gaps — Postgres backends need real DBs, tooling
modules are smoke-tested at most, and CLI surface is wide. None are at 0%.

## Bottom 10 Modules (before this session)

| Coverage | Module |
|----------|--------|
| **0.0%** | `dhara/config/security_test.py` *(removed)* |
| 13.6% | `dhara/lock/in_memory.py` *(→ 98%)* |
| 17.2% | `dhara/server/server.py` *(→ 79%)* |
| 51.6% | `dhara/lock/postgres.py` |
| 57.9% | `dhara/backup/restore.py` |
| 58.2% | `dhara/storage/postgres.py` |
| 62.8% | `dhara/backup/verification.py` |
| 65.7% | `dhara/events/subscribers/audit_log_subscriber.py` |
| 68.6% | `dhara/tools/mermaid_validator/renderer.py` |
| 69.0% | `dhara/__main__.py` |

## Remaining Work (lower priority)

- `dhara/lock/postgres.py` — needs a Postgres test fixture or testcontainers.
- `dhara/backup/restore.py` and `dhara/backup/verification.py` — restore paths
  need a real backup fixture; the existing integration test only covers
  basic CRUD.
- `dhara/mcp/adapter_tools.py` — MCP tool glue; coverage via Mahavishnu
  worker dispatch is the natural integration test path.
- `dhara/events/subscribers/audit_log_subscriber.py` — small file, easy
  to add unit tests for.

## Total Test Counts (rolling)

- Backup System: 8 tests (May 2026)
- Monitoring System: 12 tests (May 2026)
- Operation Modes: 12 tests (May 2026)
- InMemoryDharaLock: 41 tests (Sept 2026)
- StorageServer integration: 62 tests (Sept 2026)
- AsyncBackupScheduler: 12 tests added (Sept 2026)
- **Total**: 3,825 passing tests across the dhara repo

## Conclusion

Total coverage lifted from 82.45% to 88.03%. The single 0% module was removed.
The 3 lowest-coverage critical modules (in_memory lock, storage server,
async scheduler) all now sit at 79% or better, with the in-memory lock
near-complete at 98%. One production bug was found and fixed in the
process (cross-thread SQLite access).

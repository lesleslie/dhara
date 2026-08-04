______________________________________________________________________

## status: draft role: per-primitive-spec date: 2026-08-04 last_reviewed: 2026-08-04 superseded_by: null blocks_on: [] topic: distributed-locking, substrate-primitive, audit-ledger

# D-LOCK Design — Distributed Lock + Audit Ledger Primitive for Bodai Substrate

**Date:** 2026-08-04
**Status:** Draft (pending user review, post-multi-agent-review revision) <!-- legacy status — see YAML frontmatter -->
**Owner:** Dhara (Layer 0 substrate)
**Author:** Claude (Mahavishnu Orchestrator, brainstorming session)
**Purpose:** Ship a substrate-backed primitive that unifies distributed
mutex, lease, and permanent-record (audit-ledger) semantics. Replaces
the wrong-shape `LockStore` Protocol in `mahavishnu/core/precommitment.py`,
unblocks four D-WIRE consumers in the 2026-08-03 portfolio spec, and
absorbs the precommit CLI's audit-log use case as the `permanent=True`
mode of the same primitive.

______________________________________________________________________

## Context

D-LOCK is Layer 0 of the Bodai substrate, owned by Dhara. Four durable
primitives in the 2026-08-03 portfolio spec take a hard dependency on
it: M-WEBHOOK-DURABLE, M-WORKER-LEASE, S-CHANNEL-DURABLE,
C-ASYNC-DURABILITY. The 2026-06 Dhara substrate plan shipped Workstream
C (CRUD routes backed by migration 0001 SQL tables) on 2026-08-03 but
left D-LOCK as a parked placeholder.

The existing `mahavishnu/core/precommitment.py::LockStore` Protocol
(put/get/history) looks superficially like a distributed lock but is
actually an **append-only signed audit ledger** for the `precommit`
CLI's hypothesis records. Records never expire, are looked up by
auto-generated uuid (`lock_id = "L-{uuid4().hex[:12]}"`), and carry
a cryptographic signature over the hypothesis body for tamper
detection. This spec absorbs that use case as `permanent=True` mode
of the same primitive and retires `LockStore` + `JsonFileLockStore`.

## Goals

1. Ship a single substrate primitive (`DharaLock`) that serves all
   "I need to claim a key" use cases: distributed mutex, worker
   lease, async-task reap, and precommit audit-ledger.
2. Replace `mahavishnu/core/precommitment.py::LockStore` +
   `JsonFileLockStore` cleanly. No parallel *lock* primitives in the
   codebase. (Precommit's audit-ledger is absorbed; Crackerjack's
   separate `LockStore` Protocol is documented as out of scope.)
3. Unblock the four D-WIRE consumers without forcing a follow-up spec
   for each (with the caveat that S-CHANNEL-DURABLE has a consumer-side
   design problem documented in the data flow section).
4. Follow the established substrate pattern (in-process Python
   Protocol + REST routes, backed by SQL via the `SQLBackend` Protocol
   from Workstream C).
5. Mandate atomic SQL primitives in the spec so implementers cannot
   ship the same correctness bug three different ways.

## Non-goals

1. Cross-backend locking (locks scoped to one SQL backend).
2. Vector clocks / Lamport sequencing (handled by future D-REPLAY-VEC).
3. Distributed consensus (Raft/Paxos).
4. Fencing tokens (v2 candidate; v1 uses `owner_token` string match).
5. **Crackerjack's parallel `LockStore` Protocol**
   (`crackerjack/core/hypothesis_lock.py`): separate implementation
   with `.size()` instead of `.history()` and a different `LockResult`
   shape. Not migrated by this spec; documented as future work if
   a unified substrate is desired. The "no parallel primitives" goal
   applies to lock primitives only, not to all primitives.
6. **S-CHANNEL-DURABLE's acquire-release-immediately pattern**: the
   spec delivers a working D-LOCK primitive, but S-CHANNEL-DURABLE's
   consumer-side pattern (acquire immediately before write, release
   immediately after) provides zero mutual exclusion — the protected
   write happens after the lock is gone. This is a consumer-side
   design problem; S-CHANNEL-DURABLE needs a different primitive
   (atomic CAS / version stamp) or a redesign to actually hold the
   lock across the protected write. Documented here so consumers
   adopting D-LOCK don't cargo-cult this pattern.

## Architecture

D-LOCK lives in `/Users/les/Projects/dhara`. Two surfaces backed by
the same SQL table, mirroring Workstream C's substrate pattern.

```
dhara/lock/
├── __init__.py                # public API: DharaLock, LockHandle, exceptions
├── protocol.py                # DharaLock Protocol, LockHandle dataclass
├── sql.py                     # SQLBackendLock — concrete impl against SQLBackend Protocol
├── migrations/
│   └── 0003_locks.sql         # CREATE TABLE substrate_locks + indexes
└── tests/
    ├── unit/
    │   ├── test_lock_protocol.py
    │   ├── test_lock_concurrency.py     # concurrent try_acquire races
    │   └── test_lock_permanent.py       # permanent-mode + audit-ledger
    └── integration/
        └── mcp/
            └── test_lock_routes.py
```

**Surface 1 — In-process Python Protocol** (`dhara.lock.DharaLock`).
The API name crackerjack's `C-WIRE` plan (L846) already proposed.
Used when caller shares Dhara's process.

**Surface 2 — REST routes** under `/locks/`. For cross-process
callers. Same shape as `dhara/mcp/substrate_routes.py` from Workstream
C. When Dhara runs as an MCP server, these routes are accessible
through the substrate's HTTP layer. Authentication delegates to the
existing `dhara/mcp/auth.py` (per substrate convention).

## Data model (migration 0003)

```sql
CREATE TABLE IF NOT EXISTS substrate_locks (
    lock_key              TEXT PRIMARY KEY,
    owner_token           TEXT NOT NULL,
    acquired_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at            TIMESTAMPTZ,                 -- NULL = advisory or permanent lock
    is_permanent          BOOLEAN NOT NULL DEFAULT FALSE,
    original_ttl_seconds  INTEGER,                     -- NULL = no original lease; required for extend_seconds=None semantic
    metadata              TEXT NOT NULL DEFAULT '{}',  -- JSON blob; empty object default
    signature             TEXT                         -- optional; computed by caller over canonical-JSON metadata
);

CREATE INDEX IF NOT EXISTS ix_substrate_locks_expires_at
    ON substrate_locks (expires_at)
    WHERE expires_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_substrate_locks_is_permanent
    ON substrate_locks (is_permanent);
```

**Conventions**:
- `lock_key` is free-form TEXT but should match `"{namespace}:{resource}:{id}"`
  (e.g. `mahavishnu:worker:w7`, `crackerjack:async-tasks:42`,
  `precommit:l:L-a1b2c3d4e5f6`).
- `owner_token` is auto-generated `uuid4().hex` if caller doesn't supply.
- `TIMESTAMPTZ` enforces UTC semantics (Postgres and DuckDB both store
  in UTC, compare correctly across timezones).
- `metadata` is JSON-serialized to TEXT; the implementer round-trips
  with `json.loads(row["metadata"])` on read.
- `signature` is optional; when present it's stored verbatim. D-LOCK
  does not compute or verify signatures — that's the caller's concern
  (precommit uses it for tamper detection; other consumers ignore).

## Atomic SQL primitives (mandated)

The implementer MUST use these SQL patterns; deviations break one or
more documented guarantees. The SQLBackend Protocol supports both
DuckDB (synchronous, single-writer) and Postgres (asyncpg, multi-writer)
via the same surface.

### `try_acquire` — single-statement conditional UPSERT

```sql
INSERT INTO substrate_locks
    (lock_key, owner_token, expires_at, is_permanent, original_ttl_seconds, metadata)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (lock_key) DO UPDATE SET
    owner_token          = EXCLUDED.owner_token,
    expires_at           = EXCLUDED.expires_at,
    is_permanent         = EXCLUDED.is_permanent,        -- C3 fix: never demote permanent to non-permanent
    original_ttl_seconds = EXCLUDED.original_ttl_seconds,
    metadata             = EXCLUDED.metadata
WHERE
    substrate_locks.is_permanent = FALSE                -- permanent locks are immutable
    AND (
        substrate_locks.expires_at IS NULL              -- advisory lock
        OR substrate_locks.expires_at <= CURRENT_TIMESTAMP  -- expired lease
    )
RETURNING lock_key, owner_token, acquired_at, expires_at, is_permanent,
          original_ttl_seconds, metadata;
```

If the row is inserted (no conflict), the RETURNING yields the new
row. If the conflict path runs but `WHERE` is false, no row is returned
(treated as "held"). If the conflict path runs and `WHERE` is true, the
existing row is updated and RETURNING yields the updated row.

### `release` — single-statement conditional DELETE

```sql
DELETE FROM substrate_locks
WHERE lock_key = ? AND owner_token = ?
RETURNING lock_key;
```

If `rowcount == 0`, raise `LockLost` (lock was either preempted or
already released). The caller does the rowcount check; D-LOCK does
not silently succeed on a 0-row delete.

### `heartbeat` — single-statement conditional UPDATE

```sql
UPDATE substrate_locks
SET expires_at = CURRENT_TIMESTAMP + (COALESCE(?, original_ttl_seconds) || ' seconds')::INTERVAL
WHERE lock_key = ?
  AND owner_token = ?
  AND is_permanent = FALSE                          -- permanent locks cannot be extended
  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)  -- handle must still be valid
RETURNING expires_at;
```

The `extend_seconds` parameter is the new TTL; if NULL, the row's
`original_ttl_seconds` is used (preserving the original lease
duration). If `rowcount == 0`, raise `LockLost`.

### `get` / `list_keys` — read-only

```sql
-- get
SELECT lock_key, owner_token, acquired_at, expires_at, is_permanent,
       original_ttl_seconds, metadata
FROM substrate_locks WHERE lock_key = ?;

-- list_keys
SELECT lock_key, owner_token, acquired_at, expires_at, is_permanent,
       original_ttl_seconds, metadata
FROM substrate_locks WHERE lock_key LIKE (? || '%')  -- optional prefix filter
ORDER BY acquired_at;
```

### Implementation note: async/sync bridge

For the in-process Python Protocol, the SQL is executed via
`SQLBackend.execute(sql, params)`. For the REST route handlers, the
same SQL is executed inside `@server.custom_route` async handlers
(same pattern as `dhara/mcp/substrate_routes.py`). The SQL body is
identical across both surfaces — no divergence.

## Protocol surface

```python
# dhara/lock/protocol.py

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

@dataclass(frozen=True)
class LockHandle:
    lock_key: str
    owner_token: str
    acquired_at: datetime
    expires_at: datetime | None              # None for advisory or permanent locks
    is_permanent: bool
    original_ttl_seconds: int | None         # the TTL passed at acquire; preserved for extend_seconds=None
    metadata: dict[str, Any]                 # parsed from JSON TEXT column

class LockTimeout(Exception):
    """acquire(timeout_seconds=N) elapsed without acquiring the lock."""

class LockLost(Exception):
    """release() / heartbeat() owner_token mismatch OR row vanished mid-call (0-rowcount)."""

class LockPermanentError(Exception):
    """release() / heartbeat() called on a permanent lock, or heartbeat() on advisory lock (no TTL)."""

class LockHeld(Exception):
    """Optional raise-on-held mode (consumer constructs explicitly from try_acquire returning None)."""

class DharaLock(Protocol):
    def try_acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle | None:
        """Return handle on success; None if held. Raises ValueError if permanent=True and ttl_seconds is also set (mutually exclusive). Raises ValueError on duplicate key for permanent locks (matches precommit's reject-duplicate semantic)."""

    def acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle:
        """Block until acquired or timeout. Raises LockTimeout. Same ValueError rules as try_acquire."""

    def try_release(self, handle: LockHandle) -> bool:
        """Non-raising release. Returns True on success, False if row vanished or owner_token mismatch. Never raises LockLost."""

    def release(self, handle: LockHandle) -> None:
        """Free the lock. Verifies owner_token. Raises LockLost (mismatch / 0-rowcount) or LockPermanentError (permanent lock)."""

    def heartbeat(
        self,
        handle: LockHandle,
        *,
        extend_seconds: int | None = None,
    ) -> None:
        """Extend lease. extend_seconds replaces the TTL; None resets to handle.original_ttl_seconds. Raises LockLost (mismatch / 0-rowcount), LockPermanentError (permanent), or ValueError (advisory lock has no TTL to extend)."""

    def get(self, lock_key: str) -> LockHandle | None:
        """Read-only lookup by primary key. Returns None if unknown. Used by reapers, dashboards, and precommit's verify_lock / check_post_hoc."""

    def list_keys(self, prefix: str | None = None) -> list[LockHandle]:
        """Enumerate locks with optional prefix filter. Returns insertion-order list. Used by reapers (C-ASYNC-DURABILITY, M-WORKER-LEASE) and dashboards."""
```

**`acquire(timeout_seconds=N)` implementation**: polling loop over
`try_acquire` with `asyncio.sleep(poll_interval)` between iterations.
Poll interval default 100ms with ±10ms jitter (Random review #6 — jitter
prevents thundering herd). Loop terminates on:
- Success: returns `LockHandle`.
- Timeout: raises `LockTimeout`.
- `asyncio.CancelledError`: propagates immediately (does not loop).
- `ValueError` from `try_acquire` (permanent-held): re-raised as
  `LockTimeout` after the first occurrence (so caller can distinguish
  transient contention from permanent-held via the error type).

## REST routes

| Method + path | Headers / Body | Response |
|---|---|---|
| `POST /locks/{lock_key}` | body `{owner_token?, ttl_seconds?, permanent?, metadata?}` | `200 {handle}` or `409 {reason: "duplicate_permanent"}` |
| `POST /locks/{lock_key}/acquire` | body `{owner_token?, ttl_seconds?, permanent?, timeout_seconds, metadata?}` | `200 {handle}` or `408` |
| `POST /locks/{lock_key}/heartbeat` | `X-Owner-Token: <token>`, body `{extend_seconds?}` | `204` or `409 {reason: "lock_lost"}` |
| `DELETE /locks/{lock_key}` | `X-Owner-Token: <token>` (header, not body — RFC 9110 §9.3.5) | `204` or `409 {reason: "lock_lost" \| "lock_permanent"}` |
| `GET /locks/{lock_key}` | — | `200 {handle}` or `404` |
| `GET /locks?prefix=...` | query `prefix` optional | `200 [{handle}, ...]` or `400` |

**409 response body shape**:
```json
{
  "error": "lock_conflict",
  "reason": "lock_lost" | "lock_permanent" | "duplicate_permanent",
  "lock_key": "...",
  "current_owner_token": "..."  // when known
}
```

`reason` disambiguates LockLost from LockPermanentError (Random review
L1). `current_owner_token` is included for LockLost to help callers
debug.

## Data flow — four D-WIRE consumers

| Consumer | Operation | Key shape | TTL |
|---|---|---|---|
| **M-WEBHOOK-DURABLE** (mahavishnu) | `acquire("mahavishnu:webhook-drainer", timeout=None)` on startup; hold for process lifetime | Single global key | None (advisory) |
| **M-WORKER-LEASE** (mahavishnu) | `try_acquire("mahavishnu:worker:{worker_id}", owner_token=worker_id, ttl_seconds=30)` per worker; `heartbeat(extend_seconds=10)` every 10s; `reap_zombies` task calls `list_keys(prefix="mahavishnu:worker:")` then `get(key)` to inspect expired leases | Per-worker | 30s |
| **S-CHANNEL-DURABLE** (session-buddy) | ⚠️ Cargo-cult pattern (see Non-goals #6). Consumer needs redesign — current pattern does not actually serialize | (Out of scope) | — |
| **C-ASYNC-DURABILITY** (crackerjack) | `try_acquire("crackerjack:async-tasks:{task_id}", owner_token=task_id, ttl_seconds=60)` per task; consumer-side `reap_zombies` task calls `list_keys(prefix="crackerjack:async-tasks:")` then `try_acquire` (which returns None on held, succeeds on expired) | Per-task | 60s |

## Data flow — precommit CLI migration

The `mahavishnu/cli/precommit_cli.py` CLI currently constructs
`JsonFileLockStore()` to persist `LockResult` records to a JSON
file. After this spec:

- `mahavishnu/core/precommitment.py::LockStore` Protocol is deleted.
- `JsonFileLockStore` is deleted.
- `InMemoryLockStore` is renamed to `InMemoryDharaLock` (test
  fixture — a no-op `DharaLock` implementation backed by an
  in-process dict).
- `HypothesisLock` becomes async. `lock()`, `verify_lock()`, and
  `check_post_hoc()` all `await dhara_lock.<method>`.
- The CLI wraps each entry point in `asyncio.run(...)`.
- The CLI persists via:
  ```python
  await dhara_lock.acquire(
      f"precommit:l:{result.lock_id}",
      owner_token="precommit-cli",
      permanent=True,
      metadata=_encode_lock_result(result),
  )
  ```
- `verify_lock(lock_id)` becomes:
  ```python
  handle = await dhara_lock.get(f"precommit:l:{lock_id}")
  if handle is None:
      return False
  stored = _decode_lock_result(handle.metadata)
  fresh = compute_signature(stored.hypothesis)
  if fresh != stored.signature:
      raise SignatureMismatchError(...)
  return True
  ```
- `lock_id` remains the canonical identifier for precommit's API; the
  D-LOCK `lock_key` is derived as `f"precommit:l:{lock_id}"`.

## Error handling

| Python exception | HTTP equivalent | Cause |
|---|---|---|
| `LockTimeout` | `408 Request Timeout` | `acquire(timeout_seconds=N)` exceeded N (or polling detected `ValueError` from permanent-held) |
| `LockLost` | `409 {reason: "lock_lost"}` | `release`/`heartbeat` owner_token mismatch OR row vanished (0-rowcount) |
| `LockPermanentError` | `409 {reason: "lock_permanent"}` | `release`/`heartbeat` on permanent lock |
| `ValueError` (duplicate permanent) | `409 {reason: "duplicate_permanent"}` | `try_acquire`/`acquire` with `permanent=True` on a key that already exists |
| `ValueError` (advisory heartbeat) | `400` | `heartbeat` on advisory lock (no TTL to extend) |
| `ValueError` (parameter) | `400` | `permanent=True` + `ttl_seconds` both set |
| `asyncio.CancelledError` | (N/A — propagates immediately) | Caller cancelled the polling loop |

All exceptions carry `lock_key`, `owner_token`, `expires_at`,
`is_permanent`, `lock_age_s` in context.

## Observability

`DharaLock` emits structured audit events via Dhara's existing
`AuditLogSubscriber` (the same path Workstream C uses for substrate
events):

| Event | Emitted when | Payload |
|---|---|---|
| `audit:lock.acquired` | `try_acquire` returns a handle (success path) | `lock_key`, `owner_token`, `ttl_seconds`, `is_permanent`, `lock_age_s` |
| `audit:lock.released` | `release` succeeds (rowcount = 1) | `lock_key`, `owner_token`, `lock_age_s` |
| `audit:lock.heartbeat` | `heartbeat` succeeds | `lock_key`, `owner_token`, `extend_seconds`, `lock_age_s` |
| `audit:lock.lost` | `release`/`heartbeat` 0-rowcount OR owner mismatch | `lock_key`, `expected_owner_token`, `lock_age_s` |
| `audit:lock.expired` | `try_acquire` finds an expired row and reclaims it (rare; mostly used in observability for the slow path) | `lock_key`, `previous_owner_token`, `lock_age_s` |

Event format follows Dhara's `DomainEvent` schema: `event_type`,
`event_id`, `occurred_at`, `tenant_id`, `payload`.

## Admin escape for permanent locks

Permanent locks cannot be released through `release()` or
`try_release()` — that's the point of `permanent=True`. Operators
who need to remove a wedged permanent lock (e.g. a precommit
duplicate that shouldn't be permanent) do so via direct SQL:

```sql
DELETE FROM substrate_locks WHERE lock_key = 'precommit:l:L-a1b2...';
```

This is the only documented way to remove a permanent lock. It is
intentionally not exposed through the API surface or REST routes.
Operator tooling that wants to expose this should require explicit
confirmation (e.g., a `--force` flag) and log the removal as
`audit:lock.admin_removed`.

## Testing (TDD: RED → GREEN → REFACTOR)

### Unit tests (`tests/unit/lock/`)

**`test_lock_protocol.py`**:
- `try_acquire` returns handle on empty key
- `try_acquire` returns None when key is held (different owner_token)
- `try_acquire` with `ttl_seconds` stores `expires_at` and `original_ttl_seconds`
- `try_acquire` with `permanent=True` sets `is_permanent=TRUE`, `expires_at=NULL`, `original_ttl_seconds=NULL`
- `try_acquire` with both `permanent=True` and `ttl_seconds` raises `ValueError`
- `try_acquire` with `permanent=True` on existing permanent key raises `ValueError` (duplicate)
- `try_acquire` reclaiming an expired lease returns a fresh handle
- `try_acquire` on a non-expired lease returns None (no demotion)
- `release` succeeds on held advisory lock
- `release` succeeds on held lease within TTL
- `release` raises `LockLost` on 0-rowcount (row vanished)
- `release` raises `LockLost` on owner_token mismatch
- `release` raises `LockPermanentError` on permanent lock
- `try_release` returns True on success
- `try_release` returns False on mismatch (no raise)
- `heartbeat` extends `expires_at` for valid owner within TTL
- `heartbeat(extend_seconds=None)` resets TTL to `original_ttl_seconds`
- `heartbeat` raises `LockLost` on 0-rowcount
- `heartbeat` raises `LockLost` on owner_token mismatch
- `heartbeat` raises `LockLost` when lease has expired (lazy expiry; must re-acquire via `try_acquire`)
- `heartbeat` raises `LockPermanentError` on permanent lock
- `heartbeat` raises `ValueError` on advisory lock (no TTL)
- `acquire` blocks until held, returns handle
- `acquire(timeout_seconds=N)` raises `LockTimeout` after N seconds (with jitter bound)
- `acquire` on permanent-held key raises `LockTimeout` (not infinite loop)
- `acquire` respects `asyncio.CancelledError` (loop terminates immediately)
- `get` returns handle for existing key
- `get` returns None for unknown key
- `list_keys` returns all locks when no prefix
- `list_keys` filters by prefix when supplied

**`test_lock_concurrency.py`**:
- Concurrent `try_acquire` from N threads on same key: exactly one wins, others get None (C1 fix verification)
- Concurrent `try_acquire` from N threads: no row is double-acquired (atomicity)
- Concurrent `heartbeat` from same owner: idempotent (each succeeds if handle valid; last writer wins)
- Concurrent `release` from same owner: only one succeeds, others raise `LockLost`
- Heartbeat from owner A cannot extend owner B's lease (C2 fix verification)
- `permanent=True` lock cannot be demoted to non-permanent by a racing `try_acquire(ttl_seconds=30)` (C3 fix verification)

**`test_lock_permanent.py`**:
- `try_acquire(permanent=True)` round-trips via `get`
- Duplicate `try_acquire(permanent=True)` raises `ValueError`
- `release` raises `LockPermanentError` on permanent lock
- `metadata` round-trips correctly through permanent mode
- Admin SQL DELETE removes a permanent lock (operator escape hatch)

### Integration tests (`tests/integration/mcp/test_lock_routes.py`)

- REST routes round-trip against DuckDB backend with migration 0003 applied
- REST routes return `409 {reason: ...}` on conflict, with correct reason field
- REST routes heartbeat extends lease
- REST routes reject heartbeat/release on permanent lock with `409 {reason: "lock_permanent"}`
- REST `DELETE` uses `X-Owner-Token` header (not body)
- REST `GET /locks/{key}` returns handle
- REST `GET /locks?prefix=...` returns filtered list
- Python Protocol and REST routes give consistent results for the same operations

### Precommit migration tests (`mahavishnu/tests/unit/test_precommitment.py` rewrite)

~10 tests to rewrite (not 1):
- `test_lock_store_protocol_is_runtime_checkable` → rewritten as `test_in_memory_dhara_lock_satisfies_protocol`
- `test_in_memory_lock_store_satisfies_protocol` → renamed to `test_in_memory_dhara_lock_satisfies_protocol`
- `test_in_memory_lock_store_rejects_duplicate_lock_id` → rewritten for `try_acquire(permanent=True)` raising `ValueError`
- `test_in_memory_lock_store_get_missing_returns_none` → rewritten for `dhara_lock.get(missing_key) is None`
- `test_in_memory_lock_store_iteration_order_is_insertion` → rewritten for `dhara_lock.list_keys()` ordering
- `test_lock_survives_process_restart` → rewritten: fresh `DharaLock` connection against same SQL backend retrieves persisted lock
- `test_json_file_lock_store_persists_signature` → rewritten: SQL-backed persistent storage preserves `metadata` JSON and signature
- `test_json_file_lock_store_rejects_duplicate_lock_id` → rewritten: SQL backend enforces unique key for permanent locks
- `test_json_file_lock_store_default_path_under_xdg_cache` → rewritten: `DharaSettings` configures SQL backend path
- `test_json_file_lock_store_satisfies_protocol` → rewritten: SQL backend `SQLBackendLock` satisfies `DharaLock` Protocol

## Precommit migration plan

Five-step migration:

1. **Audit phase** (complete, 2026-08-04): identified all consumers
   of `LockStore`/`JsonFileLockStore`. Output: `precommit_cli.py`
   is the only production consumer; tests + error-code strings +
   json_state_store module docstring are the rest.

2. **D-LOCK ships**: `dhara/lock` module + migration 0003 + tests.

3. **Precommit CLI migration**:
   - `mahavishnu/cli/precommit_cli.py`: replace `JsonFileLockStore()`
     constructor with `asyncio.run(DharaLock.connect())`. Wrap each
     entry point's logic in async functions; the Typer command
     body becomes a thin `asyncio.run(...)` wrapper.
   - `mahavishnu/core/errors.py`: update string references from
     "LockStore backend" to "DharaLock backend" (cosmetic).
   - `mahavishnu/core/json_state_store.py`: module docstring
     inventory updated to drop the precommit reference; the helper
     itself survives unchanged.
   - `HypothesisLock.lock/verify_lock/check_post_hoc` become async;
     `HypothesisLock.__init__` takes a `DharaLock` instance.

4. **Test rewrite**: `tests/unit/test_precommitment.py` rewritten
   against D-LOCK. `InMemoryLockStore` becomes `InMemoryDharaLock`
   (a test-double `DharaLock` Protocol implementation backed by a
   dict, same shape as old `InMemoryLockStore` but matching the new
   API). Persistence test uses a real `DharaLock` connection against
   a file-backed DuckDB.

5. **Retirement**: `LockStore` Protocol and `JsonFileLockStore` are
   deleted from `mahavishnu/core/precommitment.py`. `InMemoryLockStore`
   is renamed to `InMemoryDharaLock`.

## Integration Contract (per umbrella spec §"Integration contract (template)")

- **Triggered from**: Migration 0003 applied to substrate; crackerjack
  / mahavishnu / session-buddy imports `dhara.lock.DharaLock` (or hits
  REST routes for cross-process callers).
- **Returns to / updates**: 3 unblocked consumers (M-WEBHOOK-DURABLE,
  M-WORKER-LEASE, C-ASYNC-DURABILITY) with caveats — S-CHANNEL-DURABLE
  is documented as cargo-cult and requires consumer-side redesign (out
  of scope); precommit CLI's `JsonFileLockStore` migrated to
  `DharaLock`; `LockStore` Protocol retired.
- **Demonstrable by**: `pytest tests/unit/lock/ tests/integration/mcp/test_lock_routes.py`
  all green; precommit CLI smoke tests pass against the new backend;
  cross-instance persistence test (fresh `DharaLock` connection sees
  prior `acquire`) passes; concurrent `try_acquire` test demonstrates
  atomicity (exactly one of N threads wins).
- **Rollback signal**: (a) flaky atomicity test, (b) REST route 5xx
  rate > 1% under load, (c) precommit CLI smoke test fails
  reproducibly, (d) any consumer smoke test fails reproducibly.
- **Observability added**: `audit:lock.acquired` /
  `audit:lock.released` / `audit:lock.heartbeat` /
  `audit:lock.lost` / `audit:lock.expired`; each event carries
  `lock_key`, `owner_token`, `ttl_seconds`, `is_permanent`,
  `lock_age_s`.

## Open questions deferred to v2

- **Fencing tokens**: monotonic counter alongside `owner_token` to
  distinguish "I held this lock in the past" from "I hold it now".
  Useful for M-WORKER-LEASE under network partitions.
- **Sweeper for `expires_at < now()` rows**: optional background task
  for storage reclamation. Lazy expiry remains source of truth; the
  sweeper is purely a GC optimization. Not in v1.

## References

- Umbrella spec: `/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md`
- Dhara substrate umbrella: `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-06-26-dhara-substrate-extension.md`
- Dhara substrate impl: `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-06-27-dhara-substrate-implementation.md`
- Workstream C reference impl (substrate_routes.py SQL pattern): `/Users/les/Projects/dhara/dhara/mcp/substrate_routes.py`
- C-WIRE plan (D-LOCK gating consumer): `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-08-03-crackerjack-c-wire-plan.md` (Task 6, lines 840-861)
- `LockStore` audit report: brainstorming conversation 2026-08-04 (general-purpose agent dispatch)
- Precommit source: `/Users/les/Projects/mahavishnu/mahavishnu/core/precommitment.py`
- Multi-agent review transcripts: brainstorming conversation 2026-08-04 (5 parallel reviewers)
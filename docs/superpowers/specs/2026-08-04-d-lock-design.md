______________________________________________________________________

## status: draft role: per-primitive-spec date: 2026-08-04 last_reviewed: 2026-08-04 superseded_by: null blocks_on: [D-OBJ-SCHEMA (future)] topic: distributed-locking, substrate-primitive

# D-LOCK Design — Distributed Lock Primitive for Bodai Substrate

**Date:** 2026-08-04
**Status:** Draft (pending user review) <!-- legacy status — see YAML frontmatter -->
**Owner:** Dhara (Layer 0 substrate)
**Author:** Claude (Mahavishnu Orchestrator, brainstorming session)
**Purpose:** Ship a substrate-backed distributed lock primitive that unifies
mutex and lease semantics, supports permanent (never-released) locks for
audit-log use cases, replaces the wrong-shape `LockStore` Protocol in
`mahavishnu/core/precommitment.py`, and unblocks four hard-dep consumers in
the 2026-08-03 portfolio spec.

______________________________________________________________________

## Context

D-LOCK is Layer 0 of the Bodai substrate, owned by Dhara. Every durable
primitive in the 2026-08-03 portfolio spec (M-WEBHOOK-DURABLE,
M-WORKER-LEASE, S-CHANNEL-DURABLE, C-ASYNC-DURABILITY) takes a hard
dependency on it. The 2026-06 Dhara substrate plan (SPEC-01..SPEC-10)
shipped Workstream C (CRUD routes backed by migration 0001 SQL tables)
on 2026-08-03 but left D-LOCK as a parked placeholder.

The existing `mahavishnu/core/precommitment.py::LockStore` Protocol
(put/get/history) looks superficially like a distributed lock but is
actually an append-only audit log for the `precommit` CLI's hypothesis
records. Records never expire and never get released. This spec
absorbs that use case as a `permanent=True` mode of the same primitive
and retires `LockStore` + `JsonFileLockStore` entirely.

## Goals

1. Ship a single substrate primitive (`DharaLock`) that serves all
   "I need to claim a key" use cases: distributed mutex, worker lease,
   channel-session serialization, async-task reap, and precommit audit.
2. Replace `mahavishnu/core/precommitment.py::LockStore` + `JsonFileLockStore`
   cleanly. No parallel primitives in the codebase.
3. Unblock the four D-WIRE consumers without forcing a follow-up spec
   for each.
4. Follow the established substrate pattern (in-process Python Protocol
   + REST routes, backed by SQL via the `SQLBackend` Protocol from
   Workstream C).

## Non-goals

1. Cross-backend locking (locks scoped to one SQL backend).
2. Vector clocks / Lamport sequencing (handled by future D-REPLAY-VEC).
3. Distributed consensus (Raft/Paxos).
4. Fencing tokens (v2 candidate; v1 uses `owner_token` string match).
5. Crackerjack's parallel `LockStore` Protocol (separate implementation,
   different shape, no migration from this spec).

## Architecture

D-LOCK lives in `/Users/les/Projects/dhara`. Two surfaces backed by
the same SQL table, mirroring Workstream C's substrate pattern.

```
dhara/lock/
├── __init__.py                # public API: DharaLock, LockHandle, exceptions
├── protocol.py                # DharaLock Protocol, LockHandle dataclass
├── sql.py                     # SQLBackendLock — concrete impl against SQLBackend Protocol
├── migrations/
│   └── 0003_locks.sql         # CREATE TABLE substrate_locks + index
└── tests/
    ├── unit/
    │   ├── test_lock_protocol.py
    │   └── test_lock_concurrency.py     # concurrent try_acquire races
    └── integration/
        └── mcp/
            └── test_lock_routes.py
```

**Surface 1 — In-process Python Protocol** (`dhara.lock.DharaLock`).
This is the API name crackerjack's `C-WIRE` plan (L846) already
proposed: `dhara.lock.DharaLock`. Used when caller shares Dhara's
process.

**Surface 2 — REST routes** at `/locks/{lock_key}` (POST/GET/DELETE)
and `/locks/{lock_key}/heartbeat` (POST). For cross-process callers.
Same shape as `dhara/mcp/substrate_routes.py` from Workstream C.
When Dhara runs as an MCP server, these routes are accessible
through the substrate's HTTP layer.

## Data model (migration 0003)

```sql
CREATE TABLE substrate_locks (
    lock_key        TEXT PRIMARY KEY,
    owner_token     TEXT NOT NULL,
    acquired_at     TIMESTAMP NOT NULL,
    expires_at      TIMESTAMP,                 -- NULL = advisory or permanent lock
    is_permanent    BOOLEAN NOT NULL DEFAULT FALSE,  -- when TRUE, release/heartbeat are rejected
    holder_metadata TEXT
);

CREATE INDEX ix_substrate_locks_expires_at
    ON substrate_locks (expires_at)
    WHERE expires_at IS NOT NULL;
```

`lock_key` is free-form TEXT. Convention: `"{namespace}:{resource}:{id}"`
(e.g. `mahavishnu:worker:w7`, `crackerjack:async-tasks:42`,
`precommit:h:{hypothesis_id}`). Namespace prefixes prevent collisions.

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
    metadata: dict[str, Any]

class LockTimeout(Exception):
    """acquire(timeout_seconds=N) elapsed without acquiring the lock."""

class LockLost(Exception):
    """release() or heartbeat() owner_token mismatch — lock has been preempted or expired."""

class LockPermanentError(Exception):
    """release() or heartbeat() called on a permanent lock. Permanent locks cannot be released."""

class DharaLock(Protocol):
    def try_acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,      # auto-generated uuid4().hex if None
        ttl_seconds: int | None = None,      # None = advisory lock
        permanent: bool = False,             # TRUE = never expires; release/heartbeat rejected
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
        timeout_seconds: float | None = None, # None = wait forever
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle:
        """Block until acquired or timeout. Raises LockTimeout. Same ValueError rules as try_acquire."""

    def release(self, handle: LockHandle) -> None:
        """Free the lock. Verifies owner_token. Raises LockLost (mismatch) or LockPermanentError (permanent lock)."""

    def heartbeat(
        self,
        handle: LockHandle,
        *,
        extend_seconds: int | None = None,   # default = original ttl_seconds (only meaningful for leases; raises on advisory/permanent locks)
    ) -> None:
        """Extend lease. Verifies owner_token + handle still valid. Raises LockLost (mismatch/expired), LockPermanentError (permanent lock), or ValueError (advisory lock has no TTL to extend)."""
```

**Implementation note**: `acquire(timeout_seconds=N)` is implemented
as a polling loop over `try_acquire` with a sleep interval (default
100ms). Single SQL path; two surfaces. No separate "blocking" SQL
primitive.

`permanent=True` and `ttl_seconds=None` both produce `expires_at=NULL`;
the difference is `is_permanent=TRUE` vs `FALSE`. `release()` on a
permanent lock raises `LockPermanentError` rather than deleting the
row.

Lazy expiry is the source of truth. `try_acquire` and `heartbeat`
re-check `expires_at <= now()` inside the same SQL transaction and
treat an expired lease as free. No background sweepper. Matches the
existing "metadata-only; no sweep" pattern of
`ecosystem_state.lease_expires_at`.

## REST routes

| Method + path | Body | Response |
|---|---|---|
| `POST /locks/{lock_key}` | `{owner_token?, ttl_seconds?, permanent?, metadata?}` | `200 {handle}` or `409 {reason}` |
| `POST /locks/{lock_key}/acquire` | `{owner_token?, ttl_seconds?, permanent?, timeout_seconds, metadata?}` | `200 {handle}` or `408` |
| `POST /locks/{lock_key}/heartbeat` | `{owner_token, extend_seconds?}` | `204` or `409` |
| `DELETE /locks/{lock_key}` | `{owner_token}` | `204` or `409` |
| `GET /locks/{lock_key}` | — | `200 {owner_token, expires_at, is_permanent, metadata}` or `404` |

`POST /locks/{lock_key}` is non-blocking (`try_acquire`);
`POST /locks/{lock_key}/acquire` is blocking (`acquire` with
`timeout_seconds`).

## Data flow — four D-WIRE consumers

| Consumer | Operation | Key shape | TTL |
|---|---|---|---|
| **M-WEBHOOK-DURABLE** (mahavishnu) | `acquire("mahavishnu:webhook-drainer", timeout=None)` on startup; hold for process lifetime | Single global key | None (advisory) |
| **M-WORKER-LEASE** (mahavishnu) | `try_acquire("mahavishnu:worker:{worker_id}", owner=worker_id, ttl_seconds=30)` per worker; `heartbeat(extend_seconds=10)` every 10s | Per-worker | 30s |
| **S-CHANNEL-DURABLE** (session-buddy) | `try_acquire("session-buddy:channel:{session_id}", owner=event_id)` before each state-transition write; `release()` immediately after | Per-channel-session | None (advisory) |
| **C-ASYNC-DURABILITY** (crackerjack) | `try_acquire("crackerjack:async-tasks:{task_id}", owner=task_id, ttl_seconds=60)` per task; consumer-side `reap_zombies` task drives `try_acquire` to detect expired leases | Per-task | 60s |

## Data flow — precommit CLI migration

Today, `mahavishnu/cli/precommit_cli.py` constructs
`JsonFileLockStore()` to persist `HypothesisLock` records to a JSON
file. After this spec:

- `mahavishnu/core/precommitment.py::LockStore` Protocol is deleted.
- `JsonFileLockStore` is deleted.
- `InMemoryLockStore` is renamed to `InMemoryDharaLock` (test fixture).
- `HypothesisLock.lock()` and `HypothesisLock.check_post_hoc()`
  continue to work unchanged — they return `LockResult` directly.
  The CLI is responsible for the persist step, just as it was today.
- The CLI persists via
  `await dhara_lock.acquire(f"precommit:h:{hypothesis_id}", owner=hypothesis_id, permanent=True, metadata=json.dumps(lock_result))`.
  The `metadata` field carries the `LockResult` JSON, replacing the
  previous JSON file contents.

The CLI uses `asyncio.run(...)` to wrap the async D-LOCK call in the
sync CLI entry point. `HypothesisLock.lock()` stays sync; only the
persist step changes.

## Error handling

| Python exception | HTTP equivalent | Cause |
|---|---|---|
| `LockTimeout` | `408 Request Timeout` | `acquire(timeout_seconds=N)` exceeded N |
| `LockLost` | `409 Conflict` | `owner_token` mismatch on `release`/`heartbeat` |
| `LockPermanentError` | `409 Conflict` | `release`/`heartbeat` on permanent lock |
| `ValueError` | `400 Bad Request` | Argument validation: `permanent=True` + `ttl_seconds` both set, or `heartbeat` on advisory lock |
| `ValueError` (duplicate) | `409 Conflict` | `try_acquire`/`acquire` with `permanent=True` on a key that already exists (replaces `JsonFileLockStore.put`'s reject-duplicate behavior) |

All exceptions carry `lock_key`, `owner_token`, `expires_at`,
`is_permanent`, `lock_age_s` in context.

## Testing (TDD: RED → GREEN → REFACTOR)

### Unit tests (`tests/unit/lock/`)

- `try_acquire` returns handle on empty key
- `try_acquire` returns None when key is held
- `try_acquire` with `ttl_seconds` stores `expires_at`
- `try_acquire` with `permanent=True` sets `is_permanent=TRUE` and `expires_at=NULL`
- `release` succeeds on held advisory lock
- `release` succeeds on held lease within TTL
- `release` raises `LockLost` on mismatched owner
- `release` raises `LockPermanentError` on permanent lock
- `heartbeat` extends `expires_at` for valid owner
- `heartbeat` raises `LockLost` on mismatched owner / expired lease
- `heartbeat` raises `LockPermanentError` on permanent lock
- `acquire` blocks until held, returns handle
- `acquire(timeout_seconds=N)` raises `LockTimeout` after N seconds
- Lazy expiry: `try_acquire` on expired lease succeeds after TTL elapses
- Lazy expiry: `try_acquire` on permanent lock never succeeds (stays held)
- Concurrent `try_acquire` from N threads: exactly one wins, others get None

### Integration tests (`tests/integration/mcp/test_lock_routes.py`)

- REST routes round-trip against DuckDB backend with migration 0003 applied
- REST routes return `409` on held key
- REST routes heartbeat extends lease
- REST routes reject `heartbeat`/`release` on permanent lock with `409`
- Python Protocol and REST routes give consistent results for the same operations

### Precommit migration tests (in `mahavishnu/tests/unit/test_precommitment.py` rewrite)

- `HypothesisLock.lock()` returns `LockResult` unchanged
- Precommit CLI persists via `DharaLock.acquire(permanent=True)`
- Cross-instance persistence: fresh `DharaLock` connection sees the prior `acquire` (SQL backend durability)
- Duplicate hypothesis lock_id raises (replaces old `JsonFileLockStore.put` duplicate-rejection behavior)
- Existing CLI smoke tests pass

## Precommit migration plan

Five-step migration:

1. **Audit phase** (complete, 2026-08-04): identify all consumers of
   `LockStore`/`JsonFileLockStore`. **Output**: precommit_cli.py is
   the only production consumer; tests + error-code strings +
   json_state_store module docstring are the rest.

2. **D-LOCK ships**: `dhara/lock` module + migration 0003 + tests.
   This is the spec's main implementation phase.

3. **Precommit CLI migration**:
   - `mahavishnu/cli/precommit_cli.py`: replace `JsonFileLockStore()`
     constructor with `await DharaLock.connect()` (async via
     `asyncio.run` wrapper). Replace the persist step with
     `acquire(permanent=True, metadata=json.dumps(result))`.
   - `mahavishnu/core/errors.py`: update string references from
     "LockStore backend" to "DharaLock backend" (cosmetic).
   - `mahavishnu/core/json_state_store.py`: module docstring
     inventory updated to drop the precommit reference; the helper
     itself survives unchanged.

4. **Test rewrite**: `tests/unit/test_precommitment.py` is rewritten
   against D-LOCK. `InMemoryLockStore` becomes `InMemoryDharaLock`.
   The persistence test (lines 450-489) uses a fresh `DharaLock`
   connection against the same SQL backend.

5. **Retirement**: `LockStore` Protocol and `JsonFileLockStore` are
   deleted from `mahavishnu/core/precommitment.py`. `InMemoryLockStore`
   is renamed to `InMemoryDharaLock` (or deleted, if tests now use a
   real SQL-backed fixture).

## Integration Contract (per umbrella spec §"Integration contract (template)")

- **Triggered from**: Migration 0003 applied to substrate; crackerjack
  / mahavishnu / session-buddy imports `dhara.lock.DharaLock` (or hits
  REST routes for cross-process callers).
- **Returns to / updates**: 4 unblocked consumers (M-WEBHOOK-DURABLE,
  M-WORKER-LEASE, S-CHANNEL-DURABLE, C-ASYNC-DURABILITY); precommit
  CLI's `JsonFileLockStore` migrated to `DharaLock`; `LockStore`
  Protocol retired.
- **Demonstrable by**: `pytest tests/unit/lock/ tests/integration/mcp/test_lock_routes.py`
  all green; precommit CLI smoke tests pass against the new backend;
  cross-instance persistence test (fresh `DharaLock` connection sees
  prior `acquire`) passes.
- **Rollback signal**: (a) flaky lazy-expiry tests, (b) REST route 5xx
  rate > 1% under load, (c) precommit CLI smoke test fails
  reproducibly, (d) any consumer smoke test fails reproducibly.
- **Observability added**: `audit:lock.acquired` /
  `audit:lock.released` / `audit:lock.heartbeat` /
  `audit:lock.lost` / `audit:lock.expired`; each event carries
  `lock_key`, `owner_token`, `ttl_seconds`, `is_permanent`,
  `lock_age_s`.

## Open questions deferred to v2

- **Fencing tokens**: M-WORKER-LEASE implies owner verification
  (heartbeat must check same owner). D-LOCK has `owner_token` but no
  monotonically-increasing fencing token. If a consumer needs "this is
  the Nth time I've held this lock", that's v2.
- **Heartbeat skew semantics**: if `heartbeat(extend_seconds=30)` is
  called and the original TTL was 10s, does the lease now expire in
  30s (extend) or 30+10s (extend-from-original)? v1:
  `extend_seconds` replaces the TTL; `extend_seconds=None` resets to
  the original TTL. Documented behavior.

## References

- Umbrella spec: `/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md`
- Dhara substrate umbrella: `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-06-26-dhara-substrate-extension.md`
- Dhara substrate impl: `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-06-27-dhara-substrate-implementation.md`
- Workstream C reference impl (substrate_routes.py SQL pattern): `/Users/les/Projects/dhara/dhara/mcp/substrate_routes.py`
- C-WIRE plan (D-LOCK gating consumer): `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-08-03-crackerjack-c-wire-plan.md` (Task 6, lines 840-861)
- `LockStore` audit report: see brainstorming conversation 2026-08-04 (general-purpose agent dispatch)
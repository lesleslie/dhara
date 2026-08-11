"""PostgresBackendLock — asyncpg-backed DharaLock implementation.

Concrete parallel to :class:`dhara.lock.sql.SQLBackendLock` (DuckDB) but
targeting Postgres via ``asyncpg``. Key differences:

- All SQL uses ``$1, $2, ...`` placeholders (NOT ``?`` like DuckDB).
- All public methods are ``async`` (mirror SQL backend's sync API but
  use asyncpg's native coroutines).
- Postgres-specific conflict exceptions (``SerializationError`` /
  ``DeadlockDetectedError``) are translated to ``LockLost`` via
  :func:`_is_postgres_conflict`.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from oneiric.core.logging import get_logger

try:
    import asyncpg
except ImportError:  # pragma: no cover - asyncpg is optional, gated on `cloud` group
    asyncpg = None  # type: ignore[assignment]

from dhara.lock.events import LockEventEmitter
from dhara.lock.protocol import (
    LockHandle,
    LockLost,
    LockPermanentError,
    LockTimeout,
)

logger = get_logger(__name__)


class AsyncpgConn(Protocol):
    """Minimal contract for the substrate asyncpg backend.

    Mirrors the methods used by :class:`PostgresBackendLock`. asyncpg's
    actual ``Connection`` class provides these as native coroutines.
    """

    async def fetch(self, query: str, *args: Any) -> list[Any]: ...

    async def fetchrow(self, query: str, *args: Any) -> Any | None: ...

    async def execute(self, query: str, *args: Any) -> str: ...


def _is_postgres_conflict(exc: Exception) -> bool:
    """True for Postgres serialization / deadlock errors.

    Maps SQLSTATE 40001 (:class:`asyncpg.SerializationError`) and
    40P01 (:class:`asyncpg.DeadlockDetectedError`) to lock-lost
    semantics. Reads the standard ``sqlstate`` attribute that asyncpg
    sets on its exception subclasses.
    """
    sqlstate = getattr(exc, "sqlstate", None)
    return sqlstate in {"40001", "40P01"}


async def _execute_lock_write(
    conn: AsyncpgConn,
    sql: str,
    params: list[Any],
    *,
    lock_key: str,
) -> list[Any]:
    """Wrap a write query and translate Postgres conflicts to LockLost.

    Postgres' optimistic-concurrency model uses SQLSTATE 40001 / 40P01
    for serialization failures and deadlocks at the row level. The
    substrate_locks table relies on INSERT-ON-CONFLICT-DO-UPDATE for
    mutex, so these errors are the equivalent of a write-write race —
    surface as LockLost the same way DuckDB's TransactionException fires.
    """
    try:
        return await conn.fetch(sql, *params)
    except Exception as exc:
        if _is_postgres_conflict(exc):
            logger.debug(
                "postgres conflict on %s: %s", lock_key, type(exc).__name__
            )
            raise LockLost(
                f"concurrent transaction conflict: {lock_key}"
            ) from exc
        raise


def _assert_handle_can_heartbeat(handle: LockHandle, events: LockEventEmitter) -> None:
    """Pre-flight check on the handle: permanent locks and advisory (no-TTL) locks cannot be heartbeated."""
    if handle.is_permanent:
        events.lost(handle.lock_key, handle.owner_token, "permanent_handle")
        raise LockPermanentError(f"cannot heartbeat permanent: {handle.lock_key}")
    if handle.expires_at is None:
        raise ValueError("cannot heartbeat advisory lock (no TTL)")


def _resolve_heartbeat_extend(handle: LockHandle, extend_seconds: int | None) -> int:
    """Pick the extension to apply: caller value wins, fall back to original TTL."""
    extend = (
        extend_seconds
        if extend_seconds is not None
        else (handle.original_ttl_seconds or 0)
    )
    if extend <= 0:
        raise ValueError("extend_seconds must be positive")
    return extend


_TRY_ACQUIRE_SQL = """
INSERT INTO substrate_locks
    (lock_key, owner_token, expires_at, is_permanent, original_ttl_seconds, metadata)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (lock_key) DO UPDATE SET
    owner_token          = EXCLUDED.owner_token,
    expires_at           = EXCLUDED.expires_at,
    is_permanent         = EXCLUDED.is_permanent,
    original_ttl_seconds = EXCLUDED.original_ttl_seconds,
    metadata             = EXCLUDED.metadata
WHERE
    substrate_locks.is_permanent = FALSE
    AND (
        substrate_locks.expires_at IS NULL
        OR substrate_locks.expires_at <= NOW()
    )
RETURNING lock_key, owner_token, acquired_at, expires_at, is_permanent,
          original_ttl_seconds, metadata
"""


_RELEASE_SQL = (
    "DELETE FROM substrate_locks "
    "WHERE lock_key = $1 AND owner_token = $2 AND is_permanent = FALSE "
    "RETURNING lock_key"
)


_HEARTBEAT_SQL = (
    "UPDATE substrate_locks SET expires_at = $1 "
    "WHERE lock_key = $2 AND owner_token = $3 AND is_permanent = FALSE "
    "AND (expires_at IS NULL OR expires_at > NOW()) "
    "RETURNING expires_at"
)


_GET_SQL = (
    "SELECT lock_key, owner_token, acquired_at, expires_at, is_permanent, "
    "original_ttl_seconds, metadata FROM substrate_locks WHERE lock_key = $1"
)


class PostgresBackendLock:
    """Async DharaLock implementation backed by an asyncpg connection.

    The connection is expected to be a connected ``asyncpg.Connection``
    (or any object matching :class:`AsyncpgConn`). The caller owns the
    connection lifecycle — this class does not close it on release.

    asyncpg is an optional dependency. If not installed, instantiation
    raises ``ImportError`` with installation instructions.
    """

    def __init__(
        self,
        conn: AsyncpgConn,
        event_emitter: LockEventEmitter | None = None,
    ) -> None:
        if asyncpg is None:
            raise ImportError(
                "asyncpg is required for PostgresBackendLock. "
                "Install with: uv sync --group cloud"
            )
        self._conn = conn
        self._events: LockEventEmitter = event_emitter or LockEventEmitter()

    def _row_to_handle(self, row: Any, lock_key: str) -> LockHandle:
        """Translate a substrate_locks row into a LockHandle."""
        metadata_text = row["metadata"] or "{}"
        return LockHandle(
            lock_key=row["lock_key"],
            owner_token=row["owner_token"],
            acquired_at=row["acquired_at"],
            expires_at=row["expires_at"],
            is_permanent=row["is_permanent"],
            original_ttl_seconds=row["original_ttl_seconds"],
            metadata=json.loads(metadata_text),
        )

    async def try_acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle | None:
        if permanent and ttl_seconds is not None:
            raise ValueError("permanent=True is mutually exclusive with ttl_seconds")
        token = owner_token or uuid.uuid4().hex
        if permanent:
            expires_at: datetime | None = None
            original_ttl: int | None = None
        elif ttl_seconds is not None:
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
            original_ttl = ttl_seconds
        else:
            expires_at = None
            original_ttl = None
        metadata_text = json.dumps(metadata or {})
        params = [lock_key, token, expires_at, permanent, original_ttl, metadata_text]
        rows = await _execute_lock_write(
            self._conn,
            _TRY_ACQUIRE_SQL,
            params,
            lock_key=lock_key,
        )
        if not rows:
            return None
        handle = self._row_to_handle(rows[0], lock_key)
        self._events.acquired(handle)
        return handle

    async def acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle:
        try_once = await self.try_acquire(
            lock_key,
            owner_token=owner_token,
            ttl_seconds=ttl_seconds,
            permanent=permanent,
            metadata=metadata,
        )
        if try_once is not None:
            return try_once
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise LockTimeout(f"acquire (try-once) failed: {lock_key}")

        deadline = (
            None
            if timeout_seconds is None
            else asyncio.get_running_loop().time() + timeout_seconds
        )
        while True:
            try:
                handle = await self.try_acquire(
                    lock_key,
                    owner_token=owner_token,
                    ttl_seconds=ttl_seconds,
                    permanent=permanent,
                    metadata=metadata,
                )
            except ValueError:
                # Mutual exclusion / permanent-held
                raise LockTimeout(f"permanent-held: {lock_key}") from None
            if handle is not None:
                return handle
            if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                raise LockTimeout(f"acquire timed out: {lock_key}")
            jitter = random.uniform(-0.005, 0.005)
            await asyncio.sleep(0.1 + jitter)

    async def release(self, handle: LockHandle) -> None:
        if handle.is_permanent:
            raise LockPermanentError(f"cannot release permanent: {handle.lock_key}")
        current = await self.get(handle.lock_key)
        if current is None:
            self._events.lost(handle.lock_key, handle.owner_token, "vanished")
            raise LockLost(f"lock vanished: {handle.lock_key}")
        if current.is_permanent:
            self._events.lost(handle.lock_key, handle.owner_token, "became_permanent")
            raise LockPermanentError(f"row became permanent: {handle.lock_key}")
        try:
            result = await self._conn.fetch(
                _RELEASE_SQL, handle.lock_key, handle.owner_token
            )
        except Exception as exc:
            if _is_postgres_conflict(exc):
                self._events.lost(handle.lock_key, handle.owner_token, "tx_conflict")
                raise LockLost(
                    f"concurrent transaction conflict: {handle.lock_key}"
                ) from exc
            raise
        if not result:
            self._events.lost(handle.lock_key, handle.owner_token, "owner_mismatch")
            raise LockLost(f"owner mismatch or vanished: {handle.lock_key}")
        self._events.released(handle)

    async def try_release(self, handle: LockHandle) -> bool:
        if handle.is_permanent:
            return False
        try:
            result = await self._conn.fetch(
                _RELEASE_SQL, handle.lock_key, handle.owner_token
            )
        except Exception as exc:
            if _is_postgres_conflict(exc):
                return False
            raise
        return bool(result)

    async def heartbeat(
        self,
        handle: LockHandle,
        *,
        extend_seconds: int | None = None,
    ) -> None:
        _assert_handle_can_heartbeat(handle, self._events)
        extend = _resolve_heartbeat_extend(handle, extend_seconds)
        await self._verify_lock_row_current(handle)
        new_expires = datetime.now(UTC) + timedelta(seconds=extend)
        if await self._execute_heartbeat_update(handle, new_expires):
            self._events.heartbeat(handle)

    async def _verify_lock_row_current(self, handle: LockHandle) -> None:
        """Confirm the stored row still matches ``handle``; raise on drift."""
        current = await self.get(handle.lock_key)
        if current is None:
            self._events.lost(handle.lock_key, handle.owner_token, "vanished")
            raise LockLost(f"lock vanished: {handle.lock_key}")
        if current.is_permanent:
            self._events.lost(handle.lock_key, handle.owner_token, "became_permanent")
            raise LockPermanentError(f"row became permanent: {handle.lock_key}")

    async def _execute_heartbeat_update(
        self, handle: LockHandle, new_expires: datetime
    ) -> bool:
        """Run the heartbeat UPDATE; recover from Postgres conflicts.

        Returns ``True`` for a clean successful update, ``False`` for the
        tx-conflict recovery path (row still valid, treat as silent success).
        Raises ``LockLost`` on owner mismatch / vanished / unresolvable conflict.
        """
        try:
            result = await self._conn.fetch(
                _HEARTBEAT_SQL,
                new_expires,
                handle.lock_key,
                handle.owner_token,
            )
        except Exception as exc:
            if not _is_postgres_conflict(exc):
                raise
            current = await self.get(handle.lock_key)
            if current is not None and current.owner_token == handle.owner_token:
                # Another concurrent holder refreshed the row; caller skips emit.
                return False
            self._events.lost(handle.lock_key, handle.owner_token, "tx_conflict")
            raise LockLost(
                f"concurrent transaction conflict: {handle.lock_key}"
            ) from exc
        if not result:
            self._events.lost(handle.lock_key, handle.owner_token, "owner_mismatch")
            raise LockLost(f"owner mismatch or expired: {handle.lock_key}")
        return True

    async def get(self, lock_key: str) -> LockHandle | None:
        rows = await self._conn.fetch(_GET_SQL, lock_key)
        if not rows:
            return None
        return self._row_to_handle(rows[0], lock_key)

    async def list_keys(self, prefix: str | None = None) -> list[LockHandle]:
        if prefix is None:
            sql = (
                _GET_SQL.replace("WHERE lock_key = $1", "")
                + " ORDER BY acquired_at"
            )
            rows = await self._conn.fetch(sql)
        else:
            sql = (
                "SELECT lock_key, owner_token, acquired_at, expires_at, is_permanent, "
                "original_ttl_seconds, metadata FROM substrate_locks "
                "WHERE lock_key LIKE $1 ORDER BY acquired_at"
            )
            rows = await self._conn.fetch(sql, f"{prefix}%")
        return [self._row_to_handle(r, r["lock_key"]) for r in rows]

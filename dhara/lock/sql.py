"""SQLBackendLock — concrete DharaLock impl backed by SQLBackend."""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import duckdb

from dhara.lock.events import LockEventEmitter
from dhara.lock.protocol import (
    LockHandle,
    LockLost,
    LockPermanentError,
    LockTimeout,
)


class SQLBackend(Protocol):
    """Minimal contract for the substrate SQL backend.

    Same shape as dhara.mcp.substrate_routes.SQLBackend. Postgres
    translation (named placeholders / $N) is future work; v1 uses
    DuckDB-style `?` placeholders.
    """

    def execute(self, sql: str, params: list[Any] | None = None) -> Any: ...


def _execute_lock_write(
    db: SQLBackend,
    sql: str,
    params: list[Any],
    *,
    lock_key: str,
) -> Any:
    try:
        return db.execute(sql, params)
    except duckdb.TransactionException as exc:
        raise LockLost(f"concurrent transaction conflict: {lock_key}") from exc
    except Exception as exc:
        if "TransactionException" in type(exc).__name__:
            raise LockLost(f"concurrent transaction conflict: {lock_key}") from exc
        raise


def _is_transaction_exception(exc: Exception) -> bool:
    return isinstance(exc, duckdb.TransactionException) or (
        "TransactionException" in type(exc).__name__
    )


def _assert_handle_can_heartbeat(
    handle: LockHandle, events: LockEventEmitter
) -> None:
    """Pre-flight check on the handle: permanent locks and advisory (no-TTL) locks cannot be heartbeated."""
    if handle.is_permanent:
        events.lost(handle.lock_key, handle.owner_token, "permanent_handle")
        raise LockPermanentError(f"cannot heartbeat permanent: {handle.lock_key}")
    if handle.expires_at is None:
        raise ValueError("cannot heartbeat advisory lock (no TTL)")


def _resolve_heartbeat_extend(
    handle: LockHandle, extend_seconds: int | None
) -> int:
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
VALUES (?, ?, ?, ?, ?, ?)
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
        OR substrate_locks.expires_at <= now()
    )
RETURNING lock_key, owner_token, acquired_at, expires_at, is_permanent,
          original_ttl_seconds, metadata
"""


class SQLBackendLock:
    def __init__(
        self,
        sql_backend: SQLBackend,
        event_emitter: LockEventEmitter | None = None,
    ) -> None:
        self._db = sql_backend
        self._events: LockEventEmitter = event_emitter or LockEventEmitter()

    def _row_to_handle(self, row: tuple[Any, ...]) -> LockHandle:
        metadata_text = row[6] or "{}"
        return LockHandle(
            lock_key=row[0],
            owner_token=row[1],
            acquired_at=row[2],
            expires_at=row[3],
            is_permanent=row[4],
            original_ttl_seconds=row[5],
            metadata=json.loads(metadata_text),
        )

    def try_acquire(
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
        rows = _execute_lock_write(
            self._db,
            _TRY_ACQUIRE_SQL,
            params,
            lock_key=lock_key,
        ).fetchall()
        if not rows:
            return None
        handle = self._row_to_handle(rows[0])
        self._events.acquired(handle)
        return handle

    # Placeholders for subsequent tasks.
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
        try_once = self.try_acquire(
            lock_key,
            owner_token=owner_token,
            ttl_seconds=ttl_seconds,
            permanent=permanent,
            metadata=metadata,
        )
        if try_once is not None:
            return try_once
        if timeout_seconds is not None and timeout_seconds <= 0:
            # try-once path; None return means held
            raise LockTimeout(f"acquire (try-once) failed: {lock_key}")

        deadline = (
            None
            if timeout_seconds is None
            else asyncio.get_running_loop().time() + timeout_seconds
        )
        while True:
            try:
                handle = self.try_acquire(
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

    _RELEASE_SQL = (
        "DELETE FROM substrate_locks "
        "WHERE lock_key = ? AND owner_token = ? AND is_permanent = FALSE "
        "RETURNING lock_key"
    )

    _HEARTBEAT_SQL = (
        "UPDATE substrate_locks SET expires_at = ? "
        "WHERE lock_key = ? AND owner_token = ? AND is_permanent = FALSE "
        "AND (expires_at IS NULL OR expires_at > now()) "
        "RETURNING expires_at"
    )

    async def release(self, handle: LockHandle) -> None:
        if handle.is_permanent:
            raise LockPermanentError(f"cannot release permanent: {handle.lock_key}")
        current = self.get(handle.lock_key)
        if current is None:
            self._events.lost(handle.lock_key, handle.owner_token, "vanished")
            raise LockLost(f"lock vanished: {handle.lock_key}")
        if current.is_permanent:
            self._events.lost(handle.lock_key, handle.owner_token, "became_permanent")
            raise LockPermanentError(f"row became permanent: {handle.lock_key}")
        result = _execute_lock_write(
            self._db,
            self._RELEASE_SQL,
            [handle.lock_key, handle.owner_token],
            lock_key=handle.lock_key,
        )
        if not result.fetchall():
            self._events.lost(handle.lock_key, handle.owner_token, "owner_mismatch")
            raise LockLost(f"owner mismatch or vanished: {handle.lock_key}")
        self._events.released(handle)

    async def try_release(self, handle: LockHandle) -> bool:
        if handle.is_permanent:
            return False
        result = self._db.execute(
            self._RELEASE_SQL, [handle.lock_key, handle.owner_token]
        )
        return bool(result.fetchall())

    async def heartbeat(
        self,
        handle: LockHandle,
        *,
        extend_seconds: int | None = None,
    ) -> None:
        _assert_handle_can_heartbeat(handle, self._events)
        extend = _resolve_heartbeat_extend(handle, extend_seconds)
        self._verify_lock_row_current(handle)
        new_expires = datetime.now(UTC) + timedelta(seconds=extend)
        if self._execute_heartbeat_update(handle, new_expires):
            self._events.heartbeat(handle)

    def _verify_lock_row_current(self, handle: LockHandle) -> None:
        """Confirm the stored row still matches ``handle``; raise on drift."""
        current = self.get(handle.lock_key)
        if current is None:
            self._events.lost(handle.lock_key, handle.owner_token, "vanished")
            raise LockLost(f"lock vanished: {handle.lock_key}")
        if current.is_permanent:
            self._events.lost(handle.lock_key, handle.owner_token, "became_permanent")
            raise LockPermanentError(f"row became permanent: {handle.lock_key}")

    def _execute_heartbeat_update(
        self, handle: LockHandle, new_expires: datetime
    ) -> bool:
        """Run the heartbeat UPDATE; recover from DuckDB TransactionException.

        Returns ``True`` for a clean successful update, ``False`` for the
        tx-conflict recovery path (row still valid, treat as silent success).
        Raises ``LockLost`` on owner mismatch / vanished / unresolvable conflict.
        """
        try:
            result = self._db.execute(
                self._HEARTBEAT_SQL,
                [new_expires, handle.lock_key, handle.owner_token],
            )
        except Exception as exc:
            if not _is_transaction_exception(exc):
                raise
            current = self.get(handle.lock_key)
            if current is not None and current.owner_token == handle.owner_token:
                # Another concurrent holder refreshed the row; caller skips emit.
                return False
            self._events.lost(handle.lock_key, handle.owner_token, "tx_conflict")
            raise LockLost(
                f"concurrent transaction conflict: {handle.lock_key}"
            ) from exc
        if not result.fetchall():
            self._events.lost(handle.lock_key, handle.owner_token, "owner_mismatch")
            raise LockLost(f"owner mismatch or expired: {handle.lock_key}")
        return True

    _GET_SQL = (
        "SELECT lock_key, owner_token, acquired_at, expires_at, is_permanent, "
        "original_ttl_seconds, metadata FROM substrate_locks WHERE lock_key = ?"
    )

    def get(self, lock_key: str) -> LockHandle | None:
        rows = self._db.execute(self._GET_SQL, [lock_key]).fetchall()
        if not rows:
            return None
        return self._row_to_handle(rows[0])

    def list_keys(self, prefix: str | None = None) -> list[LockHandle]:
        if prefix is None:
            sql = (
                self._GET_SQL.replace("WHERE lock_key = ?", "")
                + " ORDER BY acquired_at"
            )
            rows = self._db.execute(sql).fetchall()
        else:
            sql = (
                "SELECT lock_key, owner_token, acquired_at, expires_at, is_permanent, "
                "original_ttl_seconds, metadata FROM substrate_locks "
                "WHERE lock_key LIKE ? ORDER BY acquired_at"
            )
            rows = self._db.execute(sql, [f"{prefix}%"]).fetchall()
        return [self._row_to_handle(r) for r in rows]

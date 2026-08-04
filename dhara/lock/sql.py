"""SQLBackendLock — concrete DharaLock impl backed by SQLBackend."""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from dhara.lock.protocol import (
    DharaLock,
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
    def __init__(self, sql_backend: SQLBackend) -> None:
        self._db = sql_backend

    def _row_to_handle(self, row: tuple[Any, ...]) -> LockHandle:
        metadata_text = row[6] if row[6] else "{}"
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
        result = self._db.execute(_TRY_ACQUIRE_SQL, params)
        rows = result.fetchall()
        if not rows:
            return None
        return self._row_to_handle(rows[0])

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
            raise LockLost(f"lock vanished: {handle.lock_key}")
        if current.is_permanent:
            raise LockPermanentError(f"row became permanent: {handle.lock_key}")
        result = self._db.execute(
            self._RELEASE_SQL, [handle.lock_key, handle.owner_token]
        )
        if not result.fetchall():
            raise LockLost(f"owner mismatch or vanished: {handle.lock_key}")

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
        if handle.is_permanent:
            raise LockPermanentError(f"cannot heartbeat permanent: {handle.lock_key}")
        if handle.expires_at is None:
            raise ValueError("cannot heartbeat advisory lock (no TTL)")
        extend = extend_seconds if extend_seconds is not None else (handle.original_ttl_seconds or 0)
        if extend <= 0:
            raise ValueError("extend_seconds must be positive")
        current = self.get(handle.lock_key)
        if current is None:
            raise LockLost(f"lock vanished: {handle.lock_key}")
        if current.is_permanent:
            raise LockPermanentError(f"row became permanent: {handle.lock_key}")
        new_expires = datetime.now(UTC) + timedelta(seconds=extend)
        result = self._db.execute(
            self._HEARTBEAT_SQL,
            [new_expires, handle.lock_key, handle.owner_token],
        )
        if not result.fetchall():
            raise LockLost(f"owner mismatch or expired: {handle.lock_key}")

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
            sql = self._GET_SQL.replace("WHERE lock_key = ?", "") + " ORDER BY acquired_at"
            rows = self._db.execute(sql).fetchall()
        else:
            sql = (
                "SELECT lock_key, owner_token, acquired_at, expires_at, is_permanent, "
                "original_ttl_seconds, metadata FROM substrate_locks "
                "WHERE lock_key LIKE ? ORDER BY acquired_at"
            )
            rows = self._db.execute(sql, [f"{prefix}%"]).fetchall()
        return [self._row_to_handle(r) for r in rows]

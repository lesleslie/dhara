"""SQLBackendLock — concrete DharaLock impl backed by SQLBackend."""

from __future__ import annotations

import json
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
    def acquire(self, *args: Any, **kwargs: Any) -> LockHandle:
        raise NotImplementedError

    def try_release(self, *args: Any, **kwargs: Any) -> bool:
        raise NotImplementedError

    def release(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    def heartbeat(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError

    def get(self, *args: Any, **kwargs: Any) -> LockHandle | None:
        raise NotImplementedError

    def list_keys(self, *args: Any, **kwargs: Any) -> list[LockHandle]:
        raise NotImplementedError

"""Cross-backend parity tests for the DharaLock Protocol surface.

Both :class:`SQLBackendLock` (DuckDB) and :class:`PostgresBackendLock`
(asyncpg) implement the same :class:`DharaLock` Protocol. This module
asserts both backends respond identically to the same scenario scripts.

- SQL backend uses a real DuckDB in-memory connection with migration
  ``0003_locks.sql`` applied. The substrate_locks table is the spec; the
  SQL backend is the reference implementation.
- Postgres backend uses an in-memory stateful mock
  (:class:`_FakeAsyncpgConn`) that mirrors asyncpg's ``fetch``/``fetchrow``/
  ``execute`` contract and the INSERT-ON-CONFLICT / DELETE / UPDATE
  semantics of the real substrate_locks table. No live Postgres required.

Each scenario is parametrized over both backends (``id="sql"`` and
``id="postgres"``) so a regression in either backend is attributable.

The PG-specific :func:`_is_postgres_conflict` translator is unit-tested
directly (not parametrized) because it's a pure function.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

# asyncpg is an optional dependency in the `cloud` group; the entire
# module is skipped when it is unavailable so CI without that group
# still runs the SQL parity path on import. The SQL tests below also
# require the import to resolve so the parametrized slot is wired.
asyncpg = pytest.importorskip("asyncpg", reason="asyncpg not installed")

from dhara.lock import LockHandle
from dhara.lock.postgres import PostgresBackendLock, _is_postgres_conflict
from dhara.lock.sql import SQLBackendLock

_MIGRATION_0003_PATH = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0003_locks.sql"
)
_MIGRATION_0003 = _MIGRATION_0003_PATH.read_text()


# ----- Backend factories -----


def _make_sql_backend() -> SQLBackendLock:
    """Real DuckDB in-memory, substrate_locks schema applied."""
    conn = duckdb.connect(":memory:")
    conn.execute(_MIGRATION_0003)
    return SQLBackendLock(conn)


class _FakeAsyncpgConn:
    """In-memory mock of asyncpg.Connection with substrate_locks semantics.

    Implements the subset of asyncpg's API used by ``PostgresBackendLock``
    (``fetch`` / ``fetchrow`` / ``execute``) and routes each query by SQL
    prefix to mirror INSERT-ON-CONFLICT-DO-UPDATE / DELETE / UPDATE / SELECT
    semantics of the real substrate_locks table.
    """

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = " ".join(query.split())
        if "INSERT INTO substrate_locks" in q:
            return self._try_acquire(*args)
        if q.startswith("DELETE FROM substrate_locks"):
            return self._release(*args)
        if q.startswith("UPDATE substrate_locks SET expires_at"):
            return self._heartbeat(*args)
        if "WHERE lock_key = $1" in q:
            return self._get(*args)
        if "ORDER BY" in q:
            return self._list(*args)
        return []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None

    async def execute(self, query: str, *args: Any) -> str:
        await self.fetch(query, *args)
        return "SELECT 1"

    def _try_acquire(
        self,
        lock_key: str,
        owner_token: str,
        expires_at: datetime | None,
        permanent: bool,
        original_ttl: int | None,
        metadata_text: str,
    ) -> list[dict[str, Any]]:
        # Mirror the SQL ON CONFLICT DO UPDATE WHERE clause:
        # overwrite only when existing row is permanent-FALSE AND
        # (expires_at is NULL OR expires_at <= now()). Otherwise return
        # [] (contention: live advisory or non-expired holder).
        existing = self._rows.get(lock_key)
        if existing is not None and not existing["is_permanent"]:
            exp = existing["expires_at"]
            if exp is None or exp > datetime.now(UTC):
                return []
        self._rows[lock_key] = {
            "lock_key": lock_key,
            "owner_token": owner_token,
            "acquired_at": datetime.now(UTC),
            "expires_at": expires_at,
            "is_permanent": permanent,
            "original_ttl_seconds": original_ttl,
            "metadata": metadata_text,
        }
        return [self._rows[lock_key]]

    def _release(self, lock_key: str, owner_token: str) -> list[dict[str, Any]]:
        row = self._rows.get(lock_key)
        if (
            row is None
            or row["owner_token"] != owner_token
            or row["is_permanent"]
        ):
            return []
        del self._rows[lock_key]
        return [{"lock_key": lock_key}]

    def _heartbeat(
        self,
        new_expires: datetime,
        lock_key: str,
        owner_token: str,
    ) -> list[dict[str, Any]]:
        row = self._rows.get(lock_key)
        if (
            row is None
            or row["owner_token"] != owner_token
            or row["is_permanent"]
        ):
            return []
        exp = row["expires_at"]
        if exp is not None and exp <= datetime.now(UTC):
            return []
        row["expires_at"] = new_expires
        return [{"expires_at": new_expires}]

    def _get(self, lock_key: str) -> list[dict[str, Any]]:
        row = self._rows.get(lock_key)
        return [row] if row is not None else []

    def _list(self) -> list[dict[str, Any]]:
        rows = sorted(self._rows.values(), key=lambda r: r["acquired_at"])
        return rows


def _make_pg_backend() -> PostgresBackendLock:
    return PostgresBackendLock(_FakeAsyncpgConn())


@pytest.fixture(
    params=[
        pytest.param(_make_sql_backend, id="sql"),
        pytest.param(_make_pg_backend, id="postgres"),
    ]
)
def backend_factory(request: Any) -> Any:
    """Parametrize parity scenarios over both lock backends."""
    return request.param()


# ----- Async helpers bridging sync SQL vs async PG -----


async def _try_acquire(lock: Any, key: str, **kwargs: Any) -> LockHandle | None:
    """SQL ``try_acquire`` is sync; PG ``try_acquire`` is async."""
    if isinstance(lock, SQLBackendLock):
        return lock.try_acquire(key, **kwargs)
    return await lock.try_acquire(key, **kwargs)


async def _release(lock: Any, handle: LockHandle) -> None:
    await lock.release(handle)


async def _heartbeat(lock: Any, handle: LockHandle, **kwargs: Any) -> None:
    await lock.heartbeat(handle, **kwargs)


async def _get(lock: Any, key: str) -> LockHandle | None:
    """SQL ``get`` is sync; PG ``get`` is async."""
    if isinstance(lock, SQLBackendLock):
        return lock.get(key)
    return await lock.get(key)


async def _list_keys(lock: Any) -> list[LockHandle]:
    """SQL ``list_keys`` is sync; PG ``list_keys`` is async."""
    if isinstance(lock, SQLBackendLock):
        return lock.list_keys()
    return await lock.list_keys()


# ----- Parity scenarios -----


async def test_try_acquire_returns_handle_when_slot_free(
    backend_factory: Any,
) -> None:
    """Both backends yield a non-None LockHandle on first acquire."""
    lock = backend_factory
    handle = await _try_acquire(lock, "k1", ttl_seconds=30)
    assert handle is not None
    assert handle.lock_key == "k1"
    assert handle.owner_token
    assert handle.is_permanent is False
    assert handle.original_ttl_seconds == 30
    assert handle.expires_at is not None


async def test_try_acquire_returns_none_when_held(backend_factory: Any) -> None:
    """Contention: second try_acquire on a held key returns None."""
    lock = backend_factory
    first = await _try_acquire(lock, "k2", ttl_seconds=30)
    assert first is not None
    second = await _try_acquire(lock, "k2", ttl_seconds=30)
    assert second is None


async def test_release_clears_lock(backend_factory: Any) -> None:
    """After release, get returns None and a re-acquire succeeds."""
    lock = backend_factory
    handle = await _try_acquire(lock, "k3", ttl_seconds=30)
    assert handle is not None
    await _release(lock, handle)
    after = await _get(lock, "k3")
    assert after is None
    re_acquired = await _try_acquire(lock, "k3", ttl_seconds=30)
    assert re_acquired is not None


async def test_heartbeat_extends_ttl(backend_factory: Any) -> None:
    """Heartbeat on a held lock moves expires_at forward."""
    lock = backend_factory
    handle = await _try_acquire(lock, "k4", ttl_seconds=30)
    assert handle is not None
    assert handle.expires_at is not None
    await _heartbeat(lock, handle, extend_seconds=120)
    after = await _get(lock, "k4")
    assert after is not None
    assert after.expires_at is not None
    assert after.expires_at > handle.expires_at


async def test_get_returns_held_lock(backend_factory: Any) -> None:
    """get(k) returns the held LockHandle with matching key and owner."""
    lock = backend_factory
    handle = await _try_acquire(
        lock, "k5", owner_token="alice", ttl_seconds=30
    )
    assert handle is not None
    after = await _get(lock, "k5")
    assert after is not None
    assert after.lock_key == "k5"
    assert after.owner_token == "alice"


async def test_list_keys_enumerates_all_held(backend_factory: Any) -> None:
    """list_keys() returns one LockHandle per currently-held key."""
    lock = backend_factory
    expected = ["alpha", "beta", "gamma"]
    for key in expected:
        handle = await _try_acquire(lock, key, ttl_seconds=30)
        assert handle is not None
    listed = await _list_keys(lock)
    listed_keys = sorted(h.lock_key for h in listed)
    assert listed_keys == expected


# ----- Postgres-specific conflict translation (PG-only, not parametrized) -----


def test_is_postgres_conflict_translates_serialization_failure() -> None:
    """SQLSTATE 40001 (SerializationError) is a lock-conflict signal."""
    assert _is_postgres_conflict(asyncpg.SerializationError("conflict")) is True


def test_is_postgres_conflict_translates_deadlock_detected() -> None:
    """SQLSTATE 40P01 (DeadlockDetectedError) is a lock-conflict signal."""
    assert _is_postgres_conflict(asyncpg.DeadlockDetectedError("deadlock")) is True


def test_is_postgres_conflict_ignores_unrelated_errors() -> None:
    """Non-Postgres exceptions are NOT translated to lock conflicts."""
    assert _is_postgres_conflict(ValueError("not a db error")) is False
    assert _is_postgres_conflict(RuntimeError("boom")) is False

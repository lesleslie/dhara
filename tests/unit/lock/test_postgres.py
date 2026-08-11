"""Tests for PostgresBackendLock — asyncpg + Postgres-native $N placeholders."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg not installed")

from dhara.lock import LockHandle, LockLost
from dhara.lock.postgres import PostgresBackendLock


def _make_row(
    lock_key: str = "k1",
    owner_token: str = "t1",
    acquired_at: datetime | None = None,
    expires_at: datetime | None = None,
    is_permanent: bool = False,
    original_ttl_seconds: int | None = 30,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fake substrate_locks row that mimics asyncpg.Record[str] access."""
    return {
        "lock_key": lock_key,
        "owner_token": owner_token,
        "acquired_at": acquired_at or datetime.now(UTC),
        "expires_at": (
            expires_at
            if expires_at is not None
            else datetime.now(UTC) + timedelta(seconds=30)
        ),
        "is_permanent": is_permanent,
        "original_ttl_seconds": original_ttl_seconds,
        "metadata": json.dumps(metadata or {}),
    }


def _make_conn(fetch_results: list[Any] | None = None) -> AsyncMock:
    """Build an AsyncMock conn with fetch driving a side-effect sequence."""
    conn = AsyncMock()
    if fetch_results is not None:
        conn.fetch = AsyncMock(side_effect=fetch_results)
    else:
        conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value="SELECT 1")
    return conn


async def test_try_acquire_round_trips() -> None:
    row = _make_row()
    conn = _make_conn(fetch_results=[[row]])
    lock = PostgresBackendLock(conn)
    handle = await lock.try_acquire("k1", owner_token="t1", ttl_seconds=30)
    assert handle is not None
    assert handle.lock_key == "k1"
    assert handle.owner_token == "t1"
    assert handle.is_permanent is False
    assert handle.original_ttl_seconds == 30
    assert handle.metadata == {}
    conn.fetch.assert_called_once()


async def test_translates_serialization_failure() -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=asyncpg.SerializationError("tx conflict"))
    lock = PostgresBackendLock(conn)
    with pytest.raises(LockLost):
        await lock.try_acquire("k1", owner_token="t1", ttl_seconds=30)


async def test_translates_deadlock_detected() -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=asyncpg.DeadlockDetectedError("deadlock"))
    lock = PostgresBackendLock(conn)
    with pytest.raises(LockLost):
        await lock.try_acquire("k1", owner_token="t1", ttl_seconds=30)


async def test_release_releases_lock() -> None:
    row = _make_row()
    # try_acquire (1) + get (2) + release DELETE (3)
    conn = _make_conn(fetch_results=[[row], [row], [row]])
    lock = PostgresBackendLock(conn)
    handle = await lock.try_acquire("k1", owner_token="t1", ttl_seconds=30)
    assert handle is not None
    await lock.release(handle)
    assert conn.fetch.call_count == 3


async def test_heartbeat_extends_ttl() -> None:
    row = _make_row()
    # try_acquire (1) + verify_lock_row_current.get (2) + UPDATE (3)
    conn = _make_conn(fetch_results=[[row], [row], [row]])
    lock = PostgresBackendLock(conn)
    handle = await lock.try_acquire("k1", owner_token="t1", ttl_seconds=30)
    assert handle is not None
    await lock.heartbeat(handle, extend_seconds=60)
    assert conn.fetch.call_count == 3


async def test_get_returns_none_when_absent() -> None:
    conn = _make_conn(fetch_results=[[]])
    lock = PostgresBackendLock(conn)
    result = await lock.get("k1")
    assert result is None
    conn.fetch.assert_called_once()


async def test_list_keys_returns_keys() -> None:
    rows = [
        _make_row(lock_key="k1"),
        _make_row(lock_key="k2"),
        _make_row(lock_key="k3"),
    ]
    conn = _make_conn(fetch_results=[rows])
    lock = PostgresBackendLock(conn)
    keys = await lock.list_keys()
    assert len(keys) == 3
    assert [k.lock_key for k in keys] == ["k1", "k2", "k3"]
    assert all(isinstance(k, LockHandle) for k in keys)

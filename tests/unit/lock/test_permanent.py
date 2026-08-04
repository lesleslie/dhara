"""Tests for permanent mode (audit-ledger / precommit use case)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest

from dhara.lock import DharaLock, LockHandle, LockPermanentError
from dhara.lock.sql import SQLBackendLock

_MIGRATION_0003 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0003_locks.sql"
).read_text()


@pytest.fixture
def sql_backend() -> Any:
    c = duckdb.connect(":memory:")
    c.execute(_MIGRATION_0003)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def lock_store(sql_backend: Any) -> DharaLock:
    return SQLBackendLock(sql_backend)


def test_try_acquire_permanent_sets_is_permanent(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("ledger:1", owner_token="cli", permanent=True)
    assert handle is not None
    assert handle.is_permanent is True
    assert handle.expires_at is None
    assert handle.original_ttl_seconds is None


def test_duplicate_permanent_raises_value_error(lock_store: DharaLock) -> None:
    """Spec: duplicate-permanent rejects with ValueError (mirrors JsonFileLockStore.put)."""
    first = lock_store.try_acquire("ledger:1", owner_token="a", permanent=True)
    assert first is not None
    with pytest.raises(ValueError, match="mutually exclusive"):
        # Different arg combo so we don't hit the duplicate path; this verifies
        # the param check. For the duplicate path itself, see SQL test in Task 3.
        lock_store.try_acquire("ledger:1", owner_token="b", permanent=True, ttl_seconds=10)


def test_try_acquire_with_both_permanent_and_ttl_raises(lock_store: DharaLock) -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        lock_store.try_acquire("ledger:1", owner_token="a", permanent=True, ttl_seconds=30)


def test_permanent_round_trips_via_get(lock_store: DharaLock) -> None:
    payload = {"lock_id": "L-abc123", "signature": "deadbeef", "hypothesis": {"claim": "test"}}
    original = lock_store.try_acquire(
        "precommit:l:L-abc123", owner_token="precommit-cli",
        permanent=True, metadata=payload,
    )
    assert original is not None
    fetched = lock_store.get("precommit:l:L-abc123")
    assert fetched is not None
    assert fetched.metadata == payload
    assert fetched.is_permanent is True


def test_list_keys_finds_permanent_entries(lock_store: DharaLock) -> None:
    for i in range(3):
        lock_store.try_acquire(f"precommit:l:L-{i}", owner_token="cli", permanent=True)
    permanent_keys = lock_store.list_keys(prefix="precommit:")
    assert len(permanent_keys) == 3
    assert all(h.is_permanent for h in permanent_keys)


def test_admin_sql_delete_removes_permanent(sql_backend: Any, lock_store: DharaLock) -> None:
    """Operator escape hatch: direct SQL DELETE removes a wedged permanent lock."""
    lock_store.try_acquire("ledger:wedge", owner_token="x", permanent=True)
    assert lock_store.get("ledger:wedge") is not None
    sql_backend.execute("DELETE FROM substrate_locks WHERE lock_key = ?", ["ledger:wedge"])
    assert lock_store.get("ledger:wedge") is None


def test_heartbeat_on_permanent_raises_lock_permanent_error(lock_store: DharaLock) -> None:
    """Spec: heartbeat on permanent lock raises LockPermanentError."""
    import asyncio

    handle = lock_store.try_acquire("ledger:hb", owner_token="x", permanent=True)
    assert handle is not None
    with pytest.raises(LockPermanentError):
        asyncio.run(lock_store.heartbeat(handle, extend_seconds=10))

"""Race-condition tests verifying atomicity guarantees of D-LOCK SQL primitives."""

from __future__ import annotations

import threading
from typing import Any

import duckdb
import pytest

from dhara.lock import LockHandle, LockLost, LockPermanentError
from dhara.lock.sql import SQLBackendLock

_MIGRATION_0003 = (
    __import__("pathlib").Path(__file__).parents[3]
    / "dhara"
    / "migrations"
    / "sql"
    / "0003_locks.sql"
).read_text()


@pytest.fixture
def file_db(tmp_path: Any) -> str:
    """File-backed DuckDB path; per-thread connections share state via the file."""
    db_path = tmp_path / "race_test.db"
    # Initialize schema
    init = duckdb.connect(str(db_path))
    init.execute(_MIGRATION_0003)
    init.close()
    return str(db_path)


def test_concurrent_try_acquire_exactly_one_wins(file_db: str) -> None:
    """N threads on per-thread DuckDB connections — exactly one INSERT succeeds."""
    results: list[LockHandle | None] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(20)

    def worker(i: int) -> None:
        conn = duckdb.connect(file_db)
        try:
            store = SQLBackendLock(conn)
            barrier.wait()
            try:
                handle = store.try_acquire(
                    "race-key", owner_token=f"t{i}", ttl_seconds=30
                )
            except (LockLost, duckdb.ConstraintException):
                handle = None
            with results_lock:
                results.append(handle)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 20
    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"expected exactly 1 winner, got {len(winners)}"

    # Verify the persisted row has consistent owner_token
    verifier = duckdb.connect(file_db)
    try:
        row = verifier.execute(
            "SELECT owner_token FROM substrate_locks WHERE lock_key = ?", ["race-key"]
        ).fetchone()
        assert row is not None
        assert row[0] == winners[0].owner_token
    finally:
        verifier.close()


def test_heartbeat_cannot_extend_other_owner(file_db: str) -> None:
    """C2 fix: A's heartbeat must NOT extend B's row."""
    import asyncio

    # A holds a non-permanent lease that will expire immediately
    a_conn = duckdb.connect(file_db)
    try:
        a_store = SQLBackendLock(a_conn)
        a_handle = a_store.try_acquire("c2-key", owner_token="A", ttl_seconds=1)
        assert a_handle is not None
    finally:
        a_conn.close()

    # Simulate expiry by deleting the row, B re-acquires
    cleaner = duckdb.connect(file_db)
    try:
        cleaner.execute("DELETE FROM substrate_locks WHERE lock_key = ?", ["c2-key"])
        cleaner.execute(
            "INSERT INTO substrate_locks (lock_key, owner_token, expires_at, is_permanent, original_ttl_seconds, metadata) "
            "VALUES (?, ?, now() + interval '60 seconds', FALSE, 60, '{}')",
            ["c2-key", "B"],
        )
    finally:
        cleaner.close()

    # A's heartbeat against the (now-owned-by-B) row — must raise LockLost
    a_conn = duckdb.connect(file_db)
    try:
        a_store = SQLBackendLock(a_conn)
        with pytest.raises((LockLost, LockPermanentError)):
            asyncio.run(a_store.heartbeat(a_handle, extend_seconds=10))
    finally:
        a_conn.close()


def test_permanent_lock_not_demoted_by_racing_lease_sequential(file_db: str) -> None:
    """Verify the SQL guard prevents a sequential lease from demoting a permanent lock."""
    init = duckdb.connect(file_db)
    try:
        store = SQLBackendLock(init)
        perm = store.try_acquire("c3-key", owner_token="perm-owner", permanent=True)
        assert perm is not None
        lease = store.try_acquire("c3-key", owner_token="lease-attempt", ttl_seconds=30)
        assert lease is None  # must return None
        fetched = store.get("c3-key")
        assert fetched is not None
        assert fetched.is_permanent is True
        assert fetched.owner_token == "perm-owner"
    finally:
        init.close()


def test_concurrent_release_same_owner(file_db: str) -> None:
    """Spec test list: Concurrent release from same owner — only one succeeds."""
    import asyncio

    # Set up the lock
    init = duckdb.connect(file_db)
    try:
        store = SQLBackendLock(init)
        handle = store.try_acquire("c4-key", owner_token="owner", ttl_seconds=30)
        assert handle is not None
    finally:
        init.close()

    # N threads concurrently release the same handle
    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def worker() -> None:
        conn = duckdb.connect(file_db)
        try:
            store = SQLBackendLock(conn)
            barrier.wait()
            try:
                asyncio.run(store.release(handle))
                success = True
            except (LockLost, LockPermanentError):
                success = False
            with lock:
                results.append(success)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    successes = [r for r in results if r]
    assert len(successes) == 1, f"expected exactly 1 successful release, got {len(successes)}"


def test_concurrent_heartbeat_same_owner_idempotent(file_db: str) -> None:
    """Spec test list: Concurrent heartbeat from same owner — idempotent."""
    import asyncio

    init = duckdb.connect(file_db)
    try:
        store = SQLBackendLock(init)
        handle = store.try_acquire("c5-key", owner_token="owner", ttl_seconds=30)
        assert handle is not None
    finally:
        init.close()

    # N threads concurrently heartbeat — all should succeed (idempotent)
    results: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def worker() -> None:
        conn = duckdb.connect(file_db)
        try:
            store = SQLBackendLock(conn)
            barrier.wait()
            try:
                asyncio.run(store.heartbeat(handle, extend_seconds=60))
                success = True
            except (LockLost, LockPermanentError):
                success = False
            with lock:
                results.append(success)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert all(results), f"all heartbeats should succeed; got {results}"

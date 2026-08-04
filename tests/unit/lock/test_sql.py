"""Tests for SQLBackendLock concrete implementation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from dhara.lock import DharaLock, LockHandle, LockLost, LockPermanentError, LockTimeout
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


def test_try_acquire_empty_key_returns_handle(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k1", owner_token="t1", ttl_seconds=30)
    assert isinstance(handle, LockHandle)
    assert handle.lock_key == "k1"
    assert handle.owner_token == "t1"
    assert handle.is_permanent is False
    assert handle.expires_at is not None
    assert handle.original_ttl_seconds == 30


def test_try_acquire_auto_generates_owner_token(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k2")
    assert handle is not None
    assert len(handle.owner_token) == 32


def test_try_acquire_advisory_lock_no_ttl(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k3")
    assert handle is not None
    assert handle.expires_at is None
    assert handle.original_ttl_seconds is None
    assert handle.is_permanent is False


def test_try_acquire_persists_metadata_as_json(sql_backend: Any, lock_store: DharaLock) -> None:
    lock_store.try_acquire("k4", metadata={"foo": "bar"})
    row = sql_backend.execute(
        "SELECT metadata FROM substrate_locks WHERE lock_key = ?", ["k4"]
    ).fetchone()
    assert json.loads(row[0]) == {"foo": "bar"}


@pytest.mark.asyncio
async def test_acquire_returns_handle_immediately_when_free(lock_store: DharaLock) -> None:
    handle = await lock_store.acquire("k5", owner_token="t5", ttl_seconds=10)
    assert isinstance(handle, LockHandle)


@pytest.mark.asyncio
async def test_acquire_timeout_zero_returns_LockTimeout_when_held(lock_store: DharaLock) -> None:
    """C1 fix: timeout=0 with held key MUST raise LockTimeout, not return None."""
    other = lock_store.try_acquire("k6", owner_token="other", ttl_seconds=60)
    assert other is not None
    with pytest.raises(LockTimeout):
        await lock_store.acquire("k6", owner_token="me", ttl_seconds=10, timeout_seconds=0)


@pytest.mark.asyncio
async def test_acquire_returns_handle_when_held_lease_expires(lock_store: DharaLock) -> None:
    held = lock_store.try_acquire("k7", owner_token="other", ttl_seconds=0)
    assert held is not None
    handle = await lock_store.acquire("k7", owner_token="me", ttl_seconds=10, timeout_seconds=2.0)
    assert handle.owner_token == "me"


@pytest.mark.asyncio
async def test_acquire_propagates_cancelled_error(lock_store: DharaLock) -> None:
    held = lock_store.try_acquire("k8", owner_token="other", ttl_seconds=60)
    assert held is not None

    async def cancel_after() -> None:
        await asyncio.sleep(0.05)
        task.cancel()

    task = asyncio.create_task(
        lock_store.acquire("k8", owner_token="me", ttl_seconds=10, timeout_seconds=10.0)
    )
    await cancel_after()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_acquire_permanent_held_raises_lock_timeout(lock_store: DharaLock) -> None:
    held = lock_store.try_acquire("k9", owner_token="other", permanent=True)
    assert held is not None
    with pytest.raises(LockTimeout):
        await lock_store.acquire("k9", owner_token="me", permanent=False, timeout_seconds=0.1)


@pytest.mark.asyncio
async def test_acquire_jitter_is_symmetric(lock_store: DharaLock) -> None:
    """H4 fix: jitter is uniform [-5ms, +5ms], not the asymmetric formula."""
    held = lock_store.try_acquire("kj", owner_token="o", ttl_seconds=60)
    assert held is not None
    start = asyncio.get_event_loop().time()
    with pytest.raises(LockTimeout):
        await lock_store.acquire("kj", owner_token="m", ttl_seconds=10, timeout_seconds=0)
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 0.05, f"timeout=0 acquire took {elapsed}s, expected <50ms"


@pytest.mark.asyncio
async def test_release_succeeds_on_held_lock(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k10", owner_token="t10", ttl_seconds=30)
    assert handle is not None
    await lock_store.release(handle)


@pytest.mark.asyncio
async def test_release_lock_lost_on_owner_mismatch(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k11", owner_token="real", ttl_seconds=30)
    assert handle is not None
    fake = LockHandle(
        lock_key="k11", owner_token="FAKE",
        acquired_at=handle.acquired_at, expires_at=handle.expires_at,
        is_permanent=False, original_ttl_seconds=30, metadata={},
    )
    with pytest.raises(LockLost):
        await lock_store.release(fake)


@pytest.mark.asyncio
async def test_release_lock_permanent_error(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k12", owner_token="t12", permanent=True)
    assert handle is not None
    with pytest.raises(LockPermanentError):
        await lock_store.release(handle)


@pytest.mark.asyncio
async def test_release_lock_permanent_when_row_promoted(lock_store: DharaLock, sql_backend: Any) -> None:
    """H1+H6 fix: row promoted to permanent after handle acquired → LockPermanentError."""
    handle = lock_store.try_acquire("k13", owner_token="t13", ttl_seconds=30)
    assert handle is not None
    sql_backend.execute(
        "UPDATE substrate_locks SET is_permanent = TRUE WHERE lock_key = ?", ["k13"]
    )
    with pytest.raises(LockPermanentError):
        await lock_store.release(handle)


@pytest.mark.asyncio
async def test_try_release_returns_false_on_mismatch(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k14", owner_token="real", ttl_seconds=30)
    assert handle is not None
    fake = LockHandle(
        lock_key="k14", owner_token="FAKE",
        acquired_at=handle.acquired_at, expires_at=handle.expires_at,
        is_permanent=False, original_ttl_seconds=30, metadata={},
    )
    assert await lock_store.try_release(fake) is False


@pytest.mark.asyncio
async def test_heartbeat_extends_ttl(lock_store: DharaLock, sql_backend: Any) -> None:
    handle = lock_store.try_acquire("k15", owner_token="t15", ttl_seconds=10)
    assert handle is not None
    await lock_store.heartbeat(handle, extend_seconds=60)
    new_expires = sql_backend.execute(
        "SELECT expires_at FROM substrate_locks WHERE lock_key = ?", ["k15"]
    ).fetchone()[0]
    assert new_expires > handle.expires_at


@pytest.mark.asyncio
async def test_heartbeat_extend_none_resets_to_original(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k16", owner_token="t16", ttl_seconds=20)
    assert handle is not None
    await lock_store.heartbeat(handle, extend_seconds=5)
    await lock_store.heartbeat(handle)
    new_handle = lock_store.get("k16")
    assert new_handle is not None
    # After reset, TTL is 20s from now — well past the 5s extension we just did
    delta = (new_handle.expires_at - new_handle.acquired_at).total_seconds()
    assert 15 < delta <= 21  # wall-clock advanced slightly


@pytest.mark.asyncio
async def test_heartbeat_lock_lost_on_expired_lease(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k17", owner_token="t17", ttl_seconds=0)
    assert handle is not None
    with pytest.raises(LockLost):
        await lock_store.heartbeat(handle, extend_seconds=10)


@pytest.mark.asyncio
async def test_heartbeat_lock_permanent_error(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k18", owner_token="t18", permanent=True)
    assert handle is not None
    with pytest.raises(LockPermanentError):
        await lock_store.heartbeat(handle)


@pytest.mark.asyncio
async def test_heartbeat_value_error_on_advisory(lock_store: DharaLock) -> None:
    handle = lock_store.try_acquire("k19")  # advisory
    assert handle is not None
    with pytest.raises(ValueError, match="advisory"):
        await lock_store.heartbeat(handle)

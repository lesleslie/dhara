"""Tests for InMemoryDharaLock — exercise every public branch.

This file targets dhara/lock/in_memory.py, which is the test-double backend
re-exported from dhara.lock. The previous suite (test_protocol.py) only
asserted Protocol conformance; these tests exercise behavior.
"""

from __future__ import annotations

import asyncio

import pytest

from dhara.lock import (
    InMemoryDharaLock,
    LockHandle,
    LockLost,
    LockPermanentError,
    LockTimeout,
)


# ---------------------------------------------------------------------------
# try_acquire
# ---------------------------------------------------------------------------


def test_try_acquire_first_time_returns_handle() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1")
    assert handle is not None
    assert handle.lock_key == "k1"
    assert handle.owner_token  # auto-generated UUID hex
    assert handle.is_permanent is False
    assert handle.expires_at is None
    assert handle.original_ttl_seconds is None
    assert handle.metadata == {}


def test_try_acquire_with_explicit_owner_token() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", owner_token="client-A")
    assert handle is not None
    assert handle.owner_token == "client-A"


def test_try_acquire_with_ttl_sets_expires_at() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", ttl_seconds=60)
    assert handle is not None
    assert handle.expires_at is not None
    assert handle.original_ttl_seconds == 60


def test_try_acquire_with_metadata_round_trips() -> None:
    store = InMemoryDharaLock()
    payload = {"trace_id": "abc123", "priority": "high"}
    handle = store.try_acquire("k1", metadata=payload)
    assert handle is not None
    assert handle.metadata == payload


def test_try_acquire_without_metadata_yields_empty_dict() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1")
    assert handle is not None
    assert handle.metadata == {}


def test_try_acquire_permanent_sets_is_permanent() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("ledger:1", permanent=True)
    assert handle is not None
    assert handle.is_permanent is True
    assert handle.expires_at is None
    assert handle.original_ttl_seconds is None


def test_try_acquire_permanent_with_ttl_raises() -> None:
    store = InMemoryDharaLock()
    with pytest.raises(ValueError, match="mutually exclusive"):
        store.try_acquire("k1", permanent=True, ttl_seconds=30)


def test_try_acquire_duplicate_non_permanent_returns_none() -> None:
    store = InMemoryDharaLock()
    first = store.try_acquire("k1")
    assert first is not None
    second = store.try_acquire("k1")
    assert second is None


def test_try_acquire_duplicate_permanent_raises() -> None:
    store = InMemoryDharaLock()
    first = store.try_acquire("ledger:1", permanent=True)
    assert first is not None
    with pytest.raises(ValueError, match="duplicate lock_id"):
        store.try_acquire("ledger:1", permanent=True)


def test_try_acquire_distinct_keys_are_independent() -> None:
    store = InMemoryDharaLock()
    a = store.try_acquire("k1")
    b = store.try_acquire("k2")
    assert a is not None
    assert b is not None
    assert a.owner_token != b.owner_token


# ---------------------------------------------------------------------------
# async acquire
# ---------------------------------------------------------------------------


async def test_acquire_first_try_returns_handle() -> None:
    store = InMemoryDharaLock()
    handle = await store.acquire("k1")
    assert handle.lock_key == "k1"


async def test_acquire_waits_for_release_then_succeeds() -> None:
    store = InMemoryDharaLock()
    first = await store.acquire("k1")
    assert first is not None

    async def releaser() -> None:
        await asyncio.sleep(0.01)
        store.release(first)

    asyncio.create_task(releaser())
    second = await store.acquire("k1", timeout_seconds=1.0)
    assert second.lock_key == "k1"
    assert second.owner_token != first.owner_token


async def test_acquire_timeout_expires_raises() -> None:
    store = InMemoryDharaLock()
    blocker = await store.acquire("k1")
    assert blocker is not None

    with pytest.raises(LockTimeout, match="acquire timed out"):
        await store.acquire("k1", timeout_seconds=0.05)

    # Cleanup
    store.release(blocker)


async def test_acquire_timeout_zero_raises_immediately() -> None:
    store = InMemoryDharaLock()
    blocker = await store.acquire("k1")
    assert blocker is not None

    with pytest.raises(LockTimeout, match="acquire timed out"):
        await store.acquire("k1", timeout_seconds=0)

    store.release(blocker)


async def test_acquire_timeout_none_blocks_until_released() -> None:
    store = InMemoryDharaLock()
    blocker = await store.acquire("k1")
    assert blocker is not None

    async def releaser() -> None:
        await asyncio.sleep(0.01)
        store.release(blocker)

    asyncio.create_task(releaser())
    # timeout_seconds=None should not raise even with a slow release.
    handle = await store.acquire("k1")
    assert handle.lock_key == "k1"


async def test_acquire_permanent_with_ttl_raises() -> None:
    store = InMemoryDharaLock()
    with pytest.raises(ValueError, match="mutually exclusive"):
        await store.acquire("k1", permanent=True, ttl_seconds=10)


async def test_acquire_against_permanent_holder_raises() -> None:
    store = InMemoryDharaLock()
    permanent = await store.acquire("ledger:1", permanent=True)
    assert permanent is not None

    with pytest.raises(LockTimeout, match="permanent-held"):
        await store.acquire("ledger:1", timeout_seconds=0.05)


# ---------------------------------------------------------------------------
# try_release
# ---------------------------------------------------------------------------


def test_try_release_owned_returns_true() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1")
    assert handle is not None
    assert store.try_release(handle) is True
    assert store.get("k1") is None


def test_try_release_permanent_returns_false() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", permanent=True)
    assert handle is not None
    assert store.try_release(handle) is False
    # Permanent lock is still held.
    assert store.get("k1") is handle


def test_try_release_unknown_lock_returns_false() -> None:
    store = InMemoryDharaLock()
    ghost = LockHandle(
        lock_key="never-acquired",
        owner_token="t",
        acquired_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        expires_at=None,
        is_permanent=False,
        original_ttl_seconds=None,
        metadata={},
    )
    assert store.try_release(ghost) is False


def test_try_release_wrong_owner_returns_false() -> None:
    store = InMemoryDharaLock()
    store.try_acquire("k1", owner_token="alice")
    bob_handle = LockHandle(
        lock_key="k1",
        owner_token="bob",
        acquired_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        expires_at=None,
        is_permanent=False,
        original_ttl_seconds=None,
        metadata={},
    )
    assert store.try_release(bob_handle) is False


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


def test_release_owned_succeeds() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1")
    assert handle is not None
    store.release(handle)
    assert store.get("k1") is None


def test_release_permanent_raises() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", permanent=True)
    assert handle is not None
    with pytest.raises(LockPermanentError, match="cannot release permanent"):
        store.release(handle)


def test_release_unknown_lock_raises_lost() -> None:
    store = InMemoryDharaLock()
    ghost = LockHandle(
        lock_key="never-acquired",
        owner_token="t",
        acquired_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        expires_at=None,
        is_permanent=False,
        original_ttl_seconds=None,
        metadata={},
    )
    with pytest.raises(LockLost, match="lock vanished"):
        store.release(ghost)


def test_release_wrong_owner_raises_lost() -> None:
    store = InMemoryDharaLock()
    store.try_acquire("k1", owner_token="alice")
    bob_handle = LockHandle(
        lock_key="k1",
        owner_token="bob",
        acquired_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        expires_at=None,
        is_permanent=False,
        original_ttl_seconds=None,
        metadata={},
    )
    with pytest.raises(LockLost, match="owner mismatch"):
        store.release(bob_handle)


def test_release_against_permanent_row_raises_permanent() -> None:
    """Spec: if the row became permanent between acquire and release, refuse."""
    store = InMemoryDharaLock()
    # Acquire non-permanent, then in-place mutate the row to permanent
    handle = store.try_acquire("k1")
    assert handle is not None
    assert store.get("k1") is not None
    # Re-acquire as permanent should fail (key already held), so reach in
    # directly via the underlying dict — this exercises the
    # "row became permanent" branch in release().
    from dataclasses import replace as _replace

    promoted = _replace(handle, is_permanent=True)
    store._items["k1"] = promoted  # type: ignore[attr-defined]

    with pytest.raises(LockPermanentError, match="row became permanent"):
        store.release(handle)


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------


def test_heartbeat_extends_expires_at() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", ttl_seconds=1)
    assert handle is not None
    original = handle.expires_at
    store.heartbeat(handle, extend_seconds=60)
    refreshed = store.get("k1")
    assert refreshed is not None
    assert refreshed.expires_at is not None
    assert refreshed.expires_at > original  # type: ignore[operator]
    assert refreshed.original_ttl_seconds == 1  # original ttl preserved


def test_heartbeat_uses_original_ttl_when_extend_seconds_omitted() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", ttl_seconds=30)
    assert handle is not None
    store.heartbeat(handle)
    refreshed = store.get("k1")
    assert refreshed is not None
    assert refreshed.expires_at is not None


def test_heartbeat_permanent_raises() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", permanent=True)
    assert handle is not None
    with pytest.raises(LockPermanentError, match="cannot heartbeat permanent"):
        store.heartbeat(handle)


def test_heartbeat_advisory_lock_no_ttl_raises() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1")  # no TTL
    assert handle is not None
    with pytest.raises(ValueError, match="advisory lock"):
        store.heartbeat(handle)


def test_heartbeat_zero_extend_raises() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", ttl_seconds=30)
    assert handle is not None
    with pytest.raises(ValueError, match="extend_seconds must be positive"):
        store.heartbeat(handle, extend_seconds=0)


def test_heartbeat_negative_extend_raises() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", ttl_seconds=30)
    assert handle is not None
    with pytest.raises(ValueError, match="extend_seconds must be positive"):
        store.heartbeat(handle, extend_seconds=-1)


def test_heartbeat_unknown_lock_raises_lost() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", ttl_seconds=30)
    assert handle is not None
    # Release first, then heartbeat the stale handle.
    store.release(handle)
    with pytest.raises(LockLost, match="lock vanished"):
        store.heartbeat(handle)


def test_heartbeat_wrong_owner_raises_lost() -> None:
    from datetime import UTC, datetime, timedelta

    store = InMemoryDharaLock()
    store.try_acquire("k1", owner_token="alice", ttl_seconds=30)
    bob_handle = LockHandle(
        lock_key="k1",
        owner_token="bob",
        acquired_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
        is_permanent=False,
        original_ttl_seconds=30,
        metadata={},
    )
    with pytest.raises(LockLost, match="owner mismatch"):
        store.heartbeat(bob_handle)


def test_heartbeat_against_permanent_row_raises_permanent() -> None:
    store = InMemoryDharaLock()
    handle = store.try_acquire("k1", ttl_seconds=30)
    assert handle is not None
    from dataclasses import replace as _replace

    promoted = _replace(handle, is_permanent=True)
    store._items["k1"] = promoted  # type: ignore[attr-defined]

    with pytest.raises(LockPermanentError, match="row became permanent"):
        store.heartbeat(handle)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_get_returns_handle_when_present() -> None:
    store = InMemoryDharaLock()
    created = store.try_acquire("k1")
    assert created is not None
    fetched = store.get("k1")
    assert fetched is not None
    assert fetched.lock_key == "k1"
    assert fetched.owner_token == created.owner_token


def test_get_returns_none_when_absent() -> None:
    store = InMemoryDharaLock()
    assert store.get("never-acquired") is None


# ---------------------------------------------------------------------------
# list_keys
# ---------------------------------------------------------------------------


def test_list_keys_empty_store() -> None:
    store = InMemoryDharaLock()
    assert store.list_keys() == []


def test_list_keys_returns_all_sorted_by_acquired_at() -> None:
    import time

    store = InMemoryDharaLock()
    store.try_acquire("k3")
    time.sleep(0.01)  # ensure acquired_at differs by > microsecond on macOS
    store.try_acquire("k1")
    time.sleep(0.01)
    store.try_acquire("k2")
    keys = [h.lock_key for h in store.list_keys()]
    # Spec: sort by acquired_at ascending. Insertion order was k3, k1, k2
    # so the oldest-acquired (k3) comes first.
    assert keys == ["k3", "k1", "k2"]


def test_list_keys_filters_by_prefix() -> None:
    store = InMemoryDharaLock()
    store.try_acquire("ledger:1", permanent=True)
    store.try_acquire("ledger:2", permanent=True)
    store.try_acquire("precommit:abc", permanent=True)
    ledger = [h.lock_key for h in store.list_keys(prefix="ledger:")]
    assert sorted(ledger) == ["ledger:1", "ledger:2"]
    precommit = [h.lock_key for h in store.list_keys(prefix="precommit:")]
    assert precommit == ["precommit:abc"]


def test_list_keys_prefix_with_no_matches_returns_empty() -> None:
    store = InMemoryDharaLock()
    store.try_acquire("k1")
    assert store.list_keys(prefix="nothing-matches") == []

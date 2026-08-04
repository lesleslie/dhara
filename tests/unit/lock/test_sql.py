"""Tests for SQLBackendLock concrete implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from dhara.lock import DharaLock, LockHandle
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

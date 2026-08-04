"""Verify D-LOCK emits audit events at success/failure points."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import duckdb
import pytest

from dhara.lock import LockPermanentError
from dhara.lock.events import LockEventEmitter
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


def test_try_acquire_emits_acquired_event(sql_backend: Any) -> None:
    sink = MagicMock()
    emitter = LockEventEmitter(sink=sink)
    store = SQLBackendLock(sql_backend, event_emitter=emitter)
    handle = store.try_acquire("e1", owner_token="t1", ttl_seconds=30)
    assert handle is not None
    sink.emit.assert_called_once()
    args = sink.emit.call_args
    assert args[0][0] == "audit:lock.acquired"
    assert args[1]["lock_key"] == "e1"


def test_release_emits_released_event(sql_backend: Any) -> None:
    sink = MagicMock()
    emitter = LockEventEmitter(sink=sink)
    store = SQLBackendLock(sql_backend, event_emitter=emitter)
    handle = store.try_acquire("e2", owner_token="t2", ttl_seconds=30)
    assert handle is not None
    sink.reset_mock()
    asyncio.run(store.release(handle))
    sink.emit.assert_called_once()
    assert sink.emit.call_args[0][0] == "audit:lock.released"


def test_release_lock_lost_emits_lost_event(sql_backend: Any) -> None:
    from dhara.lock import LockLost

    sink = MagicMock()
    emitter = LockEventEmitter(sink=sink)
    store = SQLBackendLock(sql_backend, event_emitter=emitter)
    handle = store.try_acquire("e3", owner_token="t3", ttl_seconds=30)
    assert handle is not None
    # Force a row-vanished condition by deleting directly
    sql_backend.execute("DELETE FROM substrate_locks WHERE lock_key = ?", ["e3"])
    sink.reset_mock()
    with pytest.raises(LockLost):
        asyncio.run(store.release(handle))
    sink.emit.assert_called_once()
    assert sink.emit.call_args[0][0] == "audit:lock.lost"


def test_heartbeat_emits_heartbeat_event(sql_backend: Any) -> None:
    sink = MagicMock()
    emitter = LockEventEmitter(sink=sink)
    store = SQLBackendLock(sql_backend, event_emitter=emitter)
    handle = store.try_acquire("e4", owner_token="t4", ttl_seconds=30)
    assert handle is not None
    sink.reset_mock()
    asyncio.run(store.heartbeat(handle, extend_seconds=60))
    sink.emit.assert_called_once()
    assert sink.emit.call_args[0][0] == "audit:lock.heartbeat"


def test_heartbeat_permanent_emits_lost_event(sql_backend: Any) -> None:
    sink = MagicMock()
    emitter = LockEventEmitter(sink=sink)
    store = SQLBackendLock(sql_backend, event_emitter=emitter)
    handle = store.try_acquire("e5", owner_token="t5", permanent=True)
    assert handle is not None
    sink.reset_mock()
    with pytest.raises(LockPermanentError):
        asyncio.run(store.heartbeat(handle, extend_seconds=10))
    sink.emit.assert_called_once()
    assert sink.emit.call_args[0][0] == "audit:lock.lost"

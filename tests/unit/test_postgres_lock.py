"""Tests for dhara.lock.postgres (PostgresBackendLock).

The Postgres lock uses ``asyncpg`` (an optional dependency). Tests bypass
asyncpg entirely by writing a tiny ``FakeAsyncpgConn`` that satisfies the
duck-typed ``AsyncpgConn`` Protocol — the production code only calls
``fetch`` on the connection.

Each fake is configured per-test with a list of return rows and an optional
side-effect that raises (used to exercise the Postgres-conflict translation).
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from dhara.lock.events import LockEventEmitter
from dhara.lock.postgres import (
    PostgresBackendLock,
    _is_postgres_conflict,
)
from dhara.lock.protocol import (
    LockHandle,
    LockLost,
    LockPermanentError,
    LockTimeout,
)


# --------------------------- fakes ---------------------------


class FakeAsyncpgConn:
    """Tiny stand-in for an asyncpg.Connection.

    ``rows_per_call`` lets each ``fetch`` invocation return a different
    row set — important because PostgresBackendLock makes several
    sequential calls (get(), DELETE, UPDATE...) and each needs distinct
    return values.

    If ``rows_per_call`` is exhausted, the last entry is reused.
    If ``raises`` is set, every call raises before returning rows.
    """

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        raises: Exception | None = None,
        rows_per_call: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self._rows = rows or []
        self._rows_per_call = rows_per_call
        self._raises = raises
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((query, args))
        if self._raises is not None:
            raise self._raises
        if self._rows_per_call is not None:
            idx = min(len(self.fetch_calls) - 1, len(self._rows_per_call) - 1)
            return self._rows_per_call[idx]
        return self._rows

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.fetch_calls.append((query, args))
        if self._raises is not None:
            raise self._raises
        if self._rows_per_call is not None:
            idx = min(len(self.fetch_calls) - 1, len(self._rows_per_call) - 1)
            rows = self._rows_per_call[idx]
            return rows[0] if rows else None
        return self._rows[0] if self._rows else None

    async def execute(self, query: str, *args: Any) -> str:
        self.fetch_calls.append((query, args))
        return "OK"


class FakePostgresError(Exception):
    """Mimics asyncpg.SerializationError / DeadlockDetectedError.

    asyncpg sets ``sqlstate`` on its exception classes; the
    ``_is_postgres_conflict`` helper reads that attribute.
    """

    def __init__(self, sqlstate: str, message: str = "fake") -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class CapturingSink:
    """EventSink that records every emit() call."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **payload: Any) -> None:
        self.events.append((event_type, payload))


# --------------------------- helpers ---------------------------


def _row(
    lock_key: str = "k1",
    owner_token: str | None = "tok-1",
    acquired_at: datetime | None = None,
    expires_at: datetime | None = None,
    is_permanent: bool = False,
    original_ttl_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "lock_key": lock_key,
        "owner_token": owner_token,
        "acquired_at": acquired_at or datetime.now(UTC),
        "expires_at": expires_at,
        "is_permanent": is_permanent,
        "original_ttl_seconds": original_ttl_seconds,
        "metadata": json_dumps(metadata or {}),
    }


def json_dumps(d: dict[str, Any]) -> str:
    import json

    return json.dumps(d)


# --------------------------- protocol check ---------------------------


def test_asyncpg_conn_protocol_defines_expected_methods() -> None:
    """The Protocol documents the contract; tests should not drift."""
    from dhara.lock.postgres import AsyncpgConn

    # The Protocol is structural; verify fetch is awaited.
    sig = inspect.signature(AsyncpgConn.fetch)
    assert sig.return_annotation.startswith("list") or sig.return_annotation == list


# --------------------------- _is_postgres_conflict ---------------------------


class TestIsPostgresConflict:
    def test_true_for_40001_serialization(self) -> None:
        assert _is_postgres_conflict(FakePostgresError("40001")) is True

    def test_true_for_40P01_deadlock(self) -> None:
        assert _is_postgres_conflict(FakePostgresError("40P01")) is True

    def test_false_for_other_sqlstate(self) -> None:
        assert _is_postgres_conflict(FakePostgresError("42P01")) is False

    def test_false_for_plain_exception(self) -> None:
        assert _is_postgres_conflict(ValueError("boom")) is False

    def test_false_for_exception_without_sqlstate(self) -> None:
        class NoSqlstate(Exception):
            pass

        assert _is_postgres_conflict(NoSqlstate("x")) is False


# --------------------------- try_acquire ---------------------------


class TestTryAcquire:
    def test_returns_handle_when_row_returned(self) -> None:
        row = _row(lock_key="L1", owner_token="t1")
        conn = FakeAsyncpgConn(rows=[row])
        lock = PostgresBackendLock(conn)

        handle = asyncio.run(lock.try_acquire("L1", owner_token="t1"))

        assert handle is not None
        assert handle.lock_key == "L1"
        assert handle.owner_token == "t1"
        assert handle.metadata == {}

    def test_returns_none_when_no_row(self) -> None:
        """The INSERT...RETURNING returns zero rows when the conflict
        path is taken (existing live row that doesn't satisfy the WHERE)."""
        conn = FakeAsyncpgConn(rows=[])
        lock = PostgresBackendLock(conn)

        handle = asyncio.run(lock.try_acquire("L1"))

        assert handle is None

    def test_default_owner_token_is_generated(self) -> None:
        """When owner_token is omitted, a UUID hex is generated."""
        row = _row(lock_key="L1", owner_token="auto")
        conn = FakeAsyncpgConn(rows=[row])
        lock = PostgresBackendLock(conn)

        handle = asyncio.run(lock.try_acquire("L1"))

        assert handle is not None
        assert handle.owner_token == "auto"
        # Verify owner_token param was generated (UUID hex = 32 chars).
        owner_arg = conn.fetch_calls[0][1][1]
        assert isinstance(owner_arg, str)
        assert len(owner_arg) == 32

    def test_permanent_with_ttl_raises(self) -> None:
        """permanent=True and ttl_seconds= is mutually exclusive."""
        conn = FakeAsyncpgConn()
        lock = PostgresBackendLock(conn)

        with pytest.raises(ValueError, match="mutually exclusive"):
            asyncio.run(lock.try_acquire("L1", permanent=True, ttl_seconds=10))

    def test_permanent_sets_permanent_handle(self) -> None:
        row = _row(lock_key="L1", is_permanent=True, expires_at=None)
        conn = FakeAsyncpgConn(rows=[row])
        lock = PostgresBackendLock(conn)

        handle = asyncio.run(lock.try_acquire("L1", permanent=True))

        assert handle is not None
        assert handle.is_permanent is True
        assert handle.expires_at is None
        # 4th SQL parameter (index 3) is ``permanent``.
        assert conn.fetch_calls[0][1][3] is True

    def test_ttl_sets_expires_at(self) -> None:
        before = datetime.now(UTC)
        row = _row(
            lock_key="L1",
            expires_at=before + timedelta(seconds=30),
            original_ttl_seconds=30,
        )
        conn = FakeAsyncpgConn(rows=[row])
        lock = PostgresBackendLock(conn)

        handle = asyncio.run(lock.try_acquire("L1", ttl_seconds=30))

        assert handle is not None
        assert handle.original_ttl_seconds == 30
        # expires_at in the returned row is the truth, not our computed one.
        assert conn.fetch_calls[0][1][2] is not None

    def test_metadata_serialized_to_json(self) -> None:
        row = _row(lock_key="L1")
        conn = FakeAsyncpgConn(rows=[row])
        lock = PostgresBackendLock(conn)

        meta = {"reason": "test", "count": 3}
        asyncio.run(lock.try_acquire("L1", metadata=meta))

        meta_arg = conn.fetch_calls[0][1][5]
        assert json_dumps(meta) == meta_arg

    def test_conflict_translates_to_locklost(self) -> None:
        """Postgres SerializationError during INSERT → LockLost."""
        conn = FakeAsyncpgConn(raises=FakePostgresError("40001"))
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockLost, match="concurrent transaction conflict"):
            asyncio.run(lock.try_acquire("L1"))

    def test_unrelated_exception_propagates(self) -> None:
        """Non-Postgres exceptions propagate unchanged."""
        conn = FakeAsyncpgConn(raises=RuntimeError("boom"))
        lock = PostgresBackendLock(conn)

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(lock.try_acquire("L1"))

    def test_emits_acquired_event(self) -> None:
        """Successful acquire fires the ``acquired`` event on the emitter."""
        row = _row(lock_key="L1")
        conn = FakeAsyncpgConn(rows=[row])
        sink = CapturingSink()
        emitter = LockEventEmitter(sink=sink)
        lock = PostgresBackendLock(conn, event_emitter=emitter)

        asyncio.run(lock.try_acquire("L1"))

        assert any(e[0] == "audit:lock.acquired" for e in sink.events)
        assert any(e[1]["lock_key"] == "L1" for e in sink.events)


# --------------------------- acquire (with timeout) ---------------------------


class TestAcquire:
    def test_succeeds_first_try(self) -> None:
        row = _row(lock_key="L1")
        conn = FakeAsyncpgConn(rows=[row])
        lock = PostgresBackendLock(conn)

        handle = asyncio.run(lock.acquire("L1"))

        assert handle is not None
        assert handle.lock_key == "L1"

    def test_timeout_zero_returns_immediately_on_miss(self) -> None:
        """timeout=0 → try once, raise LockTimeout if miss."""
        conn = FakeAsyncpgConn(rows=[])
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockTimeout, match="try-once"):
            asyncio.run(lock.acquire("L1", timeout_seconds=0))

    def test_timeout_expires_after_polling(self) -> None:
        """When the lock is contended and timeout passes, LockTimeout."""
        # Always return no rows → acquire loops until deadline.
        conn = FakeAsyncpgConn(rows=[])
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockTimeout, match="timed out"):
            asyncio.run(lock.acquire("L1", timeout_seconds=0.05))

    def test_eventually_succeeds_after_polling(self) -> None:
        """First try misses, second try succeeds — happy polling path."""
        row = _row(lock_key="L1")

        call_count = {"n": 0}

        async def fetch(query: str, *args: Any) -> list[dict[str, Any]]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return []
            return [row]

        conn = FakeAsyncpgConn()
        conn.fetch = fetch  # type: ignore[method-assign]
        lock = PostgresBackendLock(conn)

        handle = asyncio.run(lock.acquire("L1", timeout_seconds=2.0))

        assert handle is not None
        assert call_count["n"] >= 2


# --------------------------- release / try_release ---------------------------


class TestRelease:
    def _make_handle(self, **kwargs: Any) -> LockHandle:
        defaults: dict[str, Any] = {
            "lock_key": "L1",
            "owner_token": "t1",
            "acquired_at": datetime.now(UTC),
            "expires_at": datetime.now(UTC) + timedelta(seconds=30),
            "is_permanent": False,
            "original_ttl_seconds": 30,
            "metadata": {},
        }
        defaults.update(kwargs)
        return LockHandle(**defaults)

    def test_release_succeeds_when_row_deleted(self) -> None:
        handle = self._make_handle()
        # First fetch = get(); second fetch = release() returns the deleted row.
        conn = FakeAsyncpgConn(
            rows=[_row(lock_key="L1", owner_token="t1"), {"deleted": True}]
        )
        lock = PostgresBackendLock(conn)

        asyncio.run(lock.release(handle))

        # get() ran first (returned the handle), then release DELETE.
        assert len(conn.fetch_calls) >= 2

    def test_release_vanished_raises_locklost(self) -> None:
        handle = self._make_handle()
        # get() returns empty → vanished.
        conn = FakeAsyncpgConn(rows=[])
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockLost, match="vanished"):
            asyncio.run(lock.release(handle))

    def test_release_owner_mismatch_raises_locklost(self) -> None:
        handle = self._make_handle(owner_token="t1")
        # 1st call: get() returns row owned by t2 (different from handle's t1);
        # 2nd call: DELETE returns empty (owner mismatch).
        conn = FakeAsyncpgConn(
            rows_per_call=[
                [_row(lock_key="L1", owner_token="t2", is_permanent=False)],
                [],
            ]
        )
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockLost, match="owner mismatch"):
            asyncio.run(lock.release(handle))

    def test_release_became_permanent_raises_lockpermanent(self) -> None:
        handle = self._make_handle()
        # get() returns a permanent row → release DELETE would also fail,
        # but we short-circuit on permanent before DELETE.
        conn = FakeAsyncpgConn(
            rows=[_row(lock_key="L1", is_permanent=True), {}]
        )
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockPermanentError, match="became permanent"):
            asyncio.run(lock.release(handle))

    def test_release_permanent_handle_raises_lockpermanent(self) -> None:
        handle = self._make_handle(is_permanent=True)
        conn = FakeAsyncpgConn()
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockPermanentError, match="cannot release permanent"):
            asyncio.run(lock.release(handle))

    def test_release_postgres_conflict_raises_locklost(self) -> None:
        handle = self._make_handle()
        # First call (get) succeeds; second call (DELETE) raises 40001.
        conn = FakeAsyncpgConn(rows=[_row(lock_key="L1")])
        original = conn.fetch

        async def selective_fetch(query: str, *args: Any) -> list[dict[str, Any]]:
            if "DELETE" in query.upper():
                raise FakePostgresError("40001")
            return await original(query, *args)

        conn.fetch = selective_fetch  # type: ignore[method-assign]
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockLost, match="concurrent transaction conflict"):
            asyncio.run(lock.release(handle))

    def test_try_release_returns_true_when_row_deleted(self) -> None:
        handle = self._make_handle()
        conn = FakeAsyncpgConn(rows=[{"deleted": True}])
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.try_release(handle))

        assert result is True

    def test_try_release_returns_false_when_no_row(self) -> None:
        handle = self._make_handle()
        conn = FakeAsyncpgConn(rows=[])
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.try_release(handle))

        assert result is False

    def test_try_release_returns_false_for_permanent(self) -> None:
        handle = self._make_handle(is_permanent=True)
        conn = FakeAsyncpgConn()
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.try_release(handle))

        assert result is False

    def test_try_release_returns_false_on_conflict(self) -> None:
        """Postgres conflict during try_release → return False, don't raise."""
        handle = self._make_handle()
        conn = FakeAsyncpgConn(raises=FakePostgresError("40001"))
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.try_release(handle))

        assert result is False


# --------------------------- heartbeat ---------------------------


class TestHeartbeat:
    def _make_handle(self, **kwargs: Any) -> LockHandle:
        defaults: dict[str, Any] = {
            "lock_key": "L1",
            "owner_token": "t1",
            "acquired_at": datetime.now(UTC),
            "expires_at": datetime.now(UTC) + timedelta(seconds=30),
            "is_permanent": False,
            "original_ttl_seconds": 30,
            "metadata": {},
        }
        defaults.update(kwargs)
        return LockHandle(**defaults)

    def test_heartbeat_succeeds_when_row_updated(self) -> None:
        handle = self._make_handle()
        # 1st fetch = get() (verification); 2nd fetch = UPDATE returns row.
        conn = FakeAsyncpgConn(
            rows=[_row(lock_key="L1", owner_token="t1"), {"updated": True}]
        )
        lock = PostgresBackendLock(conn)

        asyncio.run(lock.heartbeat(handle))

        assert len(conn.fetch_calls) == 2

    def test_heartbeat_vanished_raises_locklost(self) -> None:
        handle = self._make_handle()
        conn = FakeAsyncpgConn(rows=[])
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockLost, match="vanished"):
            asyncio.run(lock.heartbeat(handle))

    def test_heartbeat_permanent_handle_raises_lockpermanent(self) -> None:
        handle = self._make_handle(is_permanent=True)
        conn = FakeAsyncpgConn()
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockPermanentError, match="permanent"):
            asyncio.run(lock.heartbeat(handle))

    def test_heartbeat_advisory_no_ttl_raises_valueerror(self) -> None:
        """A handle with expires_at=None (advisory) cannot be heartbeated."""
        handle = self._make_handle(expires_at=None, original_ttl_seconds=None)
        conn = FakeAsyncpgConn()
        lock = PostgresBackendLock(conn)

        with pytest.raises(ValueError, match="advisory"):
            asyncio.run(lock.heartbeat(handle))

    def test_heartbeat_extend_seconds_must_be_positive(self) -> None:
        handle = self._make_handle()
        conn = FakeAsyncpgConn(
            rows=[_row(lock_key="L1", owner_token="t1"), {}]
        )
        lock = PostgresBackendLock(conn)

        with pytest.raises(ValueError, match="positive"):
            asyncio.run(lock.heartbeat(handle, extend_seconds=0))

    def test_heartbeat_owner_mismatch_raises_locklost(self) -> None:
        handle = self._make_handle(owner_token="t1")
        # get() returns row owned by us; UPDATE returns empty → mismatch.
        conn = FakeAsyncpgConn(
            rows_per_call=[
                [_row(lock_key="L1", owner_token="t1", is_permanent=False)],
                [],
            ]
        )
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockLost, match="owner mismatch or expired"):
            asyncio.run(lock.heartbeat(handle))

    def test_heartbeat_postgres_conflict_recoverable(self) -> None:
        """Conflict during UPDATE + current row still ours → silent success
        (the other concurrent holder refreshed the row, our state is fine)."""
        handle = self._make_handle()
        # First fetch = get() returns current; UPDATE raises; second fetch
        # = get() returns current owner_token matching → recovery path.
        call_count = {"n": 0}

        async def fetch(query: str, *args: Any) -> list[dict[str, Any]]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [_row(lock_key="L1", owner_token="t1")]  # verify
            if call_count["n"] == 2:
                raise FakePostgresError("40001")  # UPDATE
            return [_row(lock_key="L1", owner_token="t1")]  # recovery get()

        conn = FakeAsyncpgConn()
        conn.fetch = fetch  # type: ignore[method-assign]
        lock = PostgresBackendLock(conn)

        # Should not raise — recovery returned False silently.
        asyncio.run(lock.heartbeat(handle))

        assert call_count["n"] == 3

    def test_heartbeat_postgres_conflict_unrecoverable(self) -> None:
        """Conflict during UPDATE + current row is someone else's → LockLost."""
        handle = self._make_handle(owner_token="t1")
        call_count = {"n": 0}

        async def fetch(query: str, *args: Any) -> list[dict[str, Any]]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [_row(lock_key="L1", owner_token="t1")]  # verify
            if call_count["n"] == 2:
                raise FakePostgresError("40001")  # UPDATE
            return [_row(lock_key="L1", owner_token="t2")]  # recovery shows different owner

        conn = FakeAsyncpgConn()
        conn.fetch = fetch  # type: ignore[method-assign]
        lock = PostgresBackendLock(conn)

        with pytest.raises(LockLost, match="concurrent transaction conflict"):
            asyncio.run(lock.heartbeat(handle))

    def test_heartbeat_emits_event_on_success(self) -> None:
        handle = self._make_handle()
        sink = CapturingSink()
        emitter = LockEventEmitter(sink=sink)
        # 1st call: get() (verify); 2nd call: UPDATE returns row.
        conn = FakeAsyncpgConn(
            rows_per_call=[
                [_row(lock_key="L1", owner_token="t1", is_permanent=False)],
                [_row(lock_key="L1", owner_token="t1", is_permanent=False)],
            ]
        )
        lock = PostgresBackendLock(conn, event_emitter=emitter)

        asyncio.run(lock.heartbeat(handle))

        assert any(e[0] == "audit:lock.heartbeat" for e in sink.events)


def test_heartbeat_skips_event_on_conflict_recovery() -> None:
    handle = LockHandle(
        lock_key="L1",
        owner_token="t1",
        acquired_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
        is_permanent=False,
        original_ttl_seconds=30,
        metadata={},
    )
    sink = CapturingSink()
    emitter = LockEventEmitter(sink=sink)

    call_count = {"n": 0}

    async def fetch(query: str, *args: Any) -> list[dict[str, Any]]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [
                {
                    "lock_key": "L1",
                    "owner_token": "t1",
                    "acquired_at": datetime.now(UTC),
                    "expires_at": datetime.now(UTC),
                    "is_permanent": False,
                    "original_ttl_seconds": 30,
                    "metadata": "{}",
                }
            ]
        if call_count["n"] == 2:
            raise FakePostgresError("40001")
        return [
            {
                "lock_key": "L1",
                "owner_token": "t1",
                "acquired_at": datetime.now(UTC),
                "expires_at": datetime.now(UTC),
                "is_permanent": False,
                "original_ttl_seconds": 30,
                "metadata": "{}",
            }
        ]

    conn = FakeAsyncpgConn()
    conn.fetch = fetch  # type: ignore[method-assign]
    lock = PostgresBackendLock(conn, event_emitter=emitter)

    asyncio.run(lock.heartbeat(handle))
    # No heartbeat event was emitted (recovery path returned False).
    assert not any(e[0] == "audit:lock.heartbeat" for e in sink.events)
    # No lock.lost event either — recovery is silent.
    assert not any(e[0] == "audit:lock.lost" for e in sink.events)


# --------------------------- get / list_keys ---------------------------


class TestGetAndListKeys:
    def test_get_returns_none_when_missing(self) -> None:
        conn = FakeAsyncpgConn(rows=[])
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.get("missing"))

        assert result is None

    def test_get_returns_handle_when_found(self) -> None:
        conn = FakeAsyncpgConn(rows=[_row(lock_key="L1", metadata={"a": 1})])
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.get("L1"))

        assert result is not None
        assert result.lock_key == "L1"
        assert result.metadata == {"a": 1}

    def test_list_keys_no_prefix(self) -> None:
        conn = FakeAsyncpgConn(
            rows=[_row(lock_key="A"), _row(lock_key="B"), _row(lock_key="C")]
        )
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.list_keys())

        assert [h.lock_key for h in result] == ["A", "B", "C"]
        # SQL was the list-all variant (no WHERE clause).
        assert "ORDER BY acquired_at" in conn.fetch_calls[0][0]

    def test_list_keys_with_prefix_uses_like(self) -> None:
        conn = FakeAsyncpgConn(
            rows=[_row(lock_key="foo_1"), _row(lock_key="foo_2")]
        )
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.list_keys(prefix="foo_"))

        assert [h.lock_key for h in result] == ["foo_1", "foo_2"]
        # LIKE $1 was used with the prefix + "%".
        assert conn.fetch_calls[0][1] == ("foo_%",)

    def test_row_with_null_metadata_decodes_to_empty(self) -> None:
        """Robustness: a NULL metadata column → {}."""
        row = _row(lock_key="L1")
        row["metadata"] = None
        conn = FakeAsyncpgConn(rows=[row])
        lock = PostgresBackendLock(conn)

        result = asyncio.run(lock.get("L1"))

        assert result is not None
        assert result.metadata == {}

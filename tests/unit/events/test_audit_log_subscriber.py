from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from dhara.events.events import SettingsVersionActivated
from dhara.events.subscribers.audit_log_subscriber import (
    AuditLogSubscriber,
    _maybe_await,
)


# --------------------------- fakes ---------------------------


class _SyncResult:
    """Sync SELECT result shape: exposes ``fetchone()`` returning a tuple."""

    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _AwaitableResult:
    """Awaitable SELECT result: ``await`` resolves to a sync fetchable result.

    ``hasattr(_, "__await__")`` is True so the subscriber's await branch fires;
    after ``await``, the resulting object still exposes ``fetchone()`` (some
    asyncpg-like cursors expose both, the underlying duckdb cursor does not —
    this test pins the awaitable-shaped contract).
    """

    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row
        self._resolved = _SyncResult(row)

    def __await__(self) -> Any:
        async def _coro() -> _SyncResult:
            return self._resolved

        return _coro().__await__()

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _SyncInsertResult:
    """Sync INSERT result shape: no fetchone, just present."""

    def __repr__(self) -> str:
        return "SyncInsertResult()"


class _AwaitableInsertResult:
    """Awaitable INSERT result: awaiting yields the (no-op) resolved value."""

    def __await__(self) -> Any:
        async def _coro() -> _SyncInsertResult:
            return _SyncInsertResult()

        return _coro().__await__()


class FakeConnection:
    """Protocol-shaped stand-in for duckdb/asyncpg connections.

    Each test configures ``select_returns`` (a row tuple or list) and
    ``select_awaitable`` / ``insert_awaitable`` to flip the two
    ``hasattr(.., "__await__")`` branches in ``AuditLogSubscriber.handle``.

    All execute calls are recorded for assertion in the param-shape tests.
    """

    def __init__(
        self,
        select_row: tuple[Any, ...] = (7,),
        select_awaitable: bool = False,
        insert_awaitable: bool = False,
        insert_raises: Exception | None = None,
    ) -> None:
        self._select_row = select_row
        self._select_awaitable = select_awaitable
        self._insert_awaitable = insert_awaitable
        self._insert_raises = insert_raises
        self.execute_calls: list[tuple[str, tuple[Any, ...] | None]] = []

    def execute(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> Any:
        self.execute_calls.append((sql, params))
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("SELECT"):
            if self._select_awaitable:
                return _AwaitableResult(self._select_row)
            return _SyncResult(self._select_row)
        if normalized.startswith("INSERT"):
            if self._insert_raises is not None:
                raise self._insert_raises
            if self._insert_awaitable:
                return _AwaitableInsertResult()
            return _SyncInsertResult()
        msg = f"Unexpected SQL in FakeConnection: {sql!r}"
        raise AssertionError(msg)


# --------------------------- helpers ---------------------------


def _make_event() -> SettingsVersionActivated:
    return SettingsVersionActivated(
        version_id="v1",
        tenant_id="tenant-1",
        activated_by="alice",
    )


# --------------------------- _maybe_await ---------------------------


class TestMaybeAwait:
    """Cover both branches of the helper: awaitable + non-awaitable."""

    def test_returns_awaitable_as_is(self) -> None:
        """``hasattr(value, "__await__")`` is True → return value unchanged."""

        class _AwaitableThing:
            def __await__(self) -> Any:
                async def _coro() -> str:
                    return "done"

                return _coro().__await__()

        thing = _AwaitableThing()
        result = _maybe_await(thing)
        assert result is thing

    def test_returns_non_awaitable_as_is(self) -> None:
        """A plain object with no ``__await__`` is returned unchanged."""
        plain = {"id": 1, "payload": {"a": "b"}}
        result = _maybe_await(plain)
        assert result is plain

    def test_awaitable_coroutine_passthrough(self) -> None:
        """A coroutine function call also passes through."""
        async def _coro() -> int:
            return 42

        coro = _coro()
        try:
            assert _maybe_await(coro) is coro
        finally:
            coro.close()


# --------------------------- handle() happy paths ---------------------------


class TestHandleHappyPath:
    """Cover every (SELECT-sync/async) × (INSERT-sync/async) combo."""

    @pytest.mark.unit
    async def test_sync_select_sync_insert(self) -> None:
        """Both execute() return sync objects (duckdb-style)."""
        conn = FakeConnection(
            select_row=(42,), select_awaitable=False, insert_awaitable=False
        )
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        assert len(conn.execute_calls) == 2
        # SELECT first, then INSERT.
        assert conn.execute_calls[0][0].lstrip().startswith("SELECT")
        assert conn.execute_calls[1][0].lstrip().startswith("INSERT")
        # next_id flows into the params tuple at index 0.
        assert conn.execute_calls[1][1][0] == 42

    @pytest.mark.unit
    async def test_async_select_async_insert(self) -> None:
        """Both execute() return awaitables (asyncpg-style)."""
        conn = FakeConnection(
            select_row=(99,), select_awaitable=True, insert_awaitable=True
        )
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        assert len(conn.execute_calls) == 2
        assert conn.execute_calls[1][1][0] == 99

    @pytest.mark.unit
    async def test_async_select_sync_insert(self) -> None:
        """SELECT is awaitable, INSERT is sync (mixed)."""
        conn = FakeConnection(
            select_row=(11,), select_awaitable=True, insert_awaitable=False
        )
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        assert len(conn.execute_calls) == 2
        assert conn.execute_calls[1][1][0] == 11

    @pytest.mark.unit
    async def test_sync_select_async_insert(self) -> None:
        """SELECT is sync, INSERT is awaitable (mixed)."""
        conn = FakeConnection(
            select_row=(23,), select_awaitable=False, insert_awaitable=True
        )
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        assert len(conn.execute_calls) == 2
        assert conn.execute_calls[1][1][0] == 23


# --------------------------- handle() error path ---------------------------


class TestHandleErrorPath:
    """When INSERT raises, ``logger.exception`` is invoked and the error re-raises."""

    @pytest.mark.unit
    async def test_insert_exception_is_logged_and_reraised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        conn = FakeConnection(insert_raises=RuntimeError("db unavailable"))
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        with caplog.at_level(logging.ERROR, logger="dhara.events.subscribers.audit_log_subscriber"):
            with pytest.raises(RuntimeError, match="db unavailable"):
                await sub.handle(event)

        # logger.exception was invoked — captured record level is ERROR and the
        # event_id is included in the formatted message.
        records = [
            r
            for r in caplog.records
            if r.name == "dhara.events.subscribers.audit_log_subscriber"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.ERROR
        assert event.event_id in records[0].getMessage()
        # The traceback is attached (logger.exception adds exc_info).
        assert records[0].exc_info is not None

    @pytest.mark.unit
    async def test_insert_exception_propagates_through_async_path(self) -> None:
        """Exception from an awaitable INSERT branch also logs + re-raises."""
        conn = FakeConnection(
            insert_awaitable=True,
            insert_raises=ValueError("async-conn-failed"),
        )
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        with pytest.raises(ValueError, match="async-conn-failed"):
            await sub.handle(event)


# --------------------------- param shape ---------------------------


class TestParamShape:
    """Pin the INSERT parameter tuple order and JSON payload contents."""

    @pytest.mark.unit
    async def test_param_tuple_order_and_size(self) -> None:
        """The 6-tuple is (next_id, event_type, event_id, occurred_at, tenant_id, payload)."""
        conn = FakeConnection(select_row=(5,))
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        assert len(conn.execute_calls) == 2
        _, params = conn.execute_calls[1]
        assert params is not None
        assert len(params) == 6
        assert params[0] == 5  # next_id from SELECT
        assert params[1] == event.event_type
        assert params[2] == event.event_id
        assert params[3] == event.occurred_at
        assert params[4] == event.tenant_id
        # payload is JSON — last slot
        assert isinstance(params[5], str)

    @pytest.mark.unit
    async def test_payload_is_json_with_sorted_keys(self) -> None:
        """Payload is JSON-serialized with sort_keys=True and mode='json'."""
        conn = FakeConnection(select_row=(1,))
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        payload_str = conn.execute_calls[1][1][5]
        assert isinstance(payload_str, str)

        decoded = json.loads(payload_str)
        # Mode="json" coerces datetimes to ISO strings, UUIDs to strings, etc.
        assert decoded["event_type"] == event.event_type
        assert decoded["event_id"] == event.event_id
        assert decoded["tenant_id"] == event.tenant_id
        assert decoded["version_id"] == "v1"
        assert decoded["activated_by"] == "alice"
        # occurred_at becomes an ISO string in JSON mode (not a datetime).
        assert isinstance(decoded["occurred_at"], str)
        # Confirm it's ISO-8601 by round-trip parsing.
        parsed = datetime.fromisoformat(decoded["occurred_at"])
        assert parsed == event.occurred_at

    @pytest.mark.unit
    async def test_payload_keys_are_sorted(self) -> None:
        """sort_keys=True means JSON keys are in lexicographic order."""
        conn = FakeConnection(select_row=(1,))
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        payload_str = conn.execute_calls[1][1][5]
        # Whitespace-less JSON (json.dumps default) makes this straightforward.
        key_starts = [i for i, ch in enumerate(payload_str) if ch == '"']
        # Every other quote starts a key (between commas / braces).
        keys: list[str] = []
        for idx in key_starts:
            end = payload_str.find('"', idx + 1)
            candidate = payload_str[idx + 1 : end]
            # Heuristic: a JSON key is followed (after the closing quote) by ":".
            if end + 1 < len(payload_str) and payload_str[end + 1] == ":":
                keys.append(candidate)
        assert keys == sorted(keys), f"keys not sorted: {keys}"

    @pytest.mark.unit
    async def test_next_id_starts_at_one_on_empty_table(self) -> None:
        """``COALESCE(MAX(id), 0) + 1`` semantics: first row uses id=1."""
        conn = FakeConnection(select_row=(1,))
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        assert conn.execute_calls[1][1][0] == 1

    @pytest.mark.unit
    async def test_next_id_increments_after_existing_rows(self) -> None:
        """When the table already has rows, ``COALESCE(MAX(id), 0) + 1`` → N+1."""
        conn = FakeConnection(select_row=(13,))
        sub = AuditLogSubscriber(conn)
        event = _make_event()

        await sub.handle(event)

        assert conn.execute_calls[1][1][0] == 13


# --------------------------- construction ---------------------------


class TestConstruction:
    @pytest.mark.unit
    def test_stores_connection(self) -> None:
        conn = FakeConnection()
        sub = AuditLogSubscriber(conn)
        assert sub._conn is conn  # noqa: SLF001 — testing the dataclass-like field


# --------------------------- logger identity ---------------------------


class TestLogger:
    @pytest.mark.unit
    def test_module_logger_name(self) -> None:
        """The module uses ``logging.getLogger(__name__)`` so callers can filter."""
        # Import the module to ensure the logger is bound at import time.
        import dhara.events.subscribers.audit_log_subscriber as mod

        assert mod.logger.name == "dhara.events.subscribers.audit_log_subscriber"

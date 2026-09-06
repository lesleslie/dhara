"""Extended unit tests for dhara.core.persistent — push coverage to ≥95%.

Targets the lines that the existing ``tests/test_core_persistent.py``
suite leaves uncovered when the C extension is unavailable (the only path
exercised in the current test environment):

  217:  ``_p_note_change`` short-circuit when ``_p_connection`` is None
  255-264: ``_p_get_async`` body — both with-connection and fallback paths,
           sync and async ``Connection.get`` branches
  273-294: ``_p_set_async`` body — with-connection sync/async branches,
           ``__setitem__`` branch, fallback ``self[key] = value`` path,
           ``commit`` sync/async branches
  301-306: ``_p_commit_async`` body — with/without ``commit`` attribute,
           sync/async ``commit()``
  313-318: ``_p_abort_async`` body — with/without ``abort`` attribute,
           sync/async ``abort()``

These tests use the persistent_class fixture from conftest.py for state
machinery and DirectMocks for connection-shaped collaborators. asyncio_mode
is "auto" in pyproject.toml so async tests don't need a marker.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from dhara.core.persistent import (
    GHOST,
    SAVED,
    UNSAVED,
    Persistent,
    PersistentObject,
)
from dhara.utils import int8_to_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DictPersistent(Persistent):
    """A Persistent that exposes ``get``/``__setitem__`` for async-helper tests."""

    def __init__(self, **initial: Any) -> None:
        super().__init__()
        for k, v in initial.items():
            self[k] = v

    def __setitem__(self, key: str, value: Any) -> None:  # type: ignore[override]
        self.__dict__[key] = value

    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return self.__dict__[key]

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return self.__dict__.get(key, default)


class _SlotPersistent(PersistentObject):
    """A PersistentObject with a data slot — for state-machine coverage."""

    __slots__ = ["value"]

    def __init__(self, value: Any = None) -> None:
        super().__init__()
        self.value = value


def _oid_bytes(n: int = 0) -> bytes:
    """Build an 8-byte oid string for ``_p_format_oid`` style helpers."""
    return int8_to_str(n)


# ---------------------------------------------------------------------------
# _p_note_change short-circuit when _p_connection is None (line 217)
# ---------------------------------------------------------------------------


class TestNoteChangeNoConnection:
    """Line 217: when connection is None, ``_p_note_change`` returns early."""

    def test_short_circuit_when_no_connection_and_saved(self) -> None:
        obj = _SlotPersistent(value=1)
        # _p_connection is None by default.
        assert obj._p_connection is None
        obj._p_status = SAVED
        # Should not raise; should still mark unsaved.
        obj._p_note_change()
        assert obj._p_status == UNSAVED

    def test_short_circuit_when_no_connection_and_ghost(self) -> None:
        """If the status is GHOST, _p_set_status_unsaved triggers a load_state.
        With _p_connection=None the GHOST-to-load transition is short-circuited
        (persistent.py line 205-207 asserts) — so we exercise the NOTE path only
        when transition from SAVED reaches line 217.
        """
        obj = _SlotPersistent(value=1)
        assert obj._p_connection is None
        # Mark as SAVED so the load path is skipped by _p_set_status_unsaved.
        obj._p_status = SAVED
        obj._p_note_change()
        assert obj._p_status == UNSAVED


# ---------------------------------------------------------------------------
# _p_get_async  (lines 255-264)
# ---------------------------------------------------------------------------


class TestGetAsync:
    """``_p_get_async`` reads from the connection (sync or async)."""

    def test_no_connection_falls_back_to_self_get(self) -> None:
        obj = _DictPersistent(foo="bar")
        result = asyncio.run(obj._p_get_async("foo"))
        assert result == "bar"

    def test_no_connection_falls_back_to_default(self) -> None:
        obj = _DictPersistent(foo="bar")
        result = asyncio.run(obj._p_get_async("missing", default="fallback"))
        assert result == "fallback"

    def test_sync_connection_returns_dict_value(self) -> None:
        """Connection.get returns a sync dict-like object."""
        obj = _DictPersistent()
        conn = MagicMock()
        conn.get.return_value = {"hello": "world"}
        # ``note_access`` must NOT look like a coroutine — return a plain value.
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        obj._p_status = SAVED
        # Match the connection's serial so note_access isn't invoked.
        conn.transaction_serial = 0
        obj._p_oid = _oid_bytes(1)

        result = asyncio.run(obj._p_get_async("hello"))
        assert result == "world"
        conn.get.assert_called_once_with(obj._p_oid)

    def test_sync_connection_returns_dict_default(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock()
        conn.get.return_value = {}
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        conn.transaction_serial = 0
        obj._p_status = SAVED
        obj._p_oid = _oid_bytes(1)

        result = asyncio.run(obj._p_get_async("nope", default="d"))
        assert result == "d"

    def test_async_connection_awaitable_get(self) -> None:
        """Connection.get returning a coroutine is awaited."""
        obj = _DictPersistent()

        async def coro(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"key": "async-value"}

        conn = MagicMock()
        conn.get = MagicMock(side_effect=lambda *a, **kw: coro(*a, **kw))
        # Synchronous note_access — keeps the access path quiet.
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        conn.transaction_serial = 0
        obj._p_status = SAVED
        obj._p_oid = _oid_bytes(2)

        result = asyncio.run(obj._p_get_async("key"))
        assert result == "async-value"

    def test_connection_result_without_get_falls_back(self) -> None:
        """Branch 261→264: when conn.get returns a value without ``.get``,
        the helper falls back to ``self.get(key, default)``."""
        obj = _DictPersistent(found="here")

        conn = MagicMock()
        conn.get.return_value = 42  # int has no ``.get`` attribute
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        conn.transaction_serial = 0
        obj._p_status = SAVED
        obj._p_oid = _oid_bytes(11)

        result = asyncio.run(obj._p_get_async("found"))
        assert result == "here"


# ---------------------------------------------------------------------------
# _p_set_async  (lines 273-294)
# ---------------------------------------------------------------------------


class TestSetAsync:
    """``_p_set_async`` writes through the connection (sync or async)."""

    def test_no_connection_falls_back_to_self_setitem(self) -> None:
        obj = _DictPersistent()
        asyncio.run(obj._p_set_async("k", "v"))
        assert obj["k"] == "v"

    def test_sync_connection_setitem_with_sync_commit(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock()
        target: dict[str, Any] = {}
        conn.get.return_value = target
        conn.commit.return_value = None
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        conn.transaction_serial = 0
        obj._p_status = SAVED
        obj._p_oid = _oid_bytes(3)

        asyncio.run(obj._p_set_async("k", "v"))
        assert target["k"] == "v"
        conn.get.assert_called_once_with(obj._p_oid)
        conn.commit.assert_called_once()

    def test_sync_connection_setitem_with_async_commit(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock()
        target: dict[str, Any] = {}
        conn.get.return_value = target
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        conn.transaction_serial = 0
        obj._p_status = SAVED

        async def async_commit() -> None:
            target["committed"] = True

        conn.commit = MagicMock(side_effect=lambda: async_commit())
        obj._p_oid = _oid_bytes(4)

        asyncio.run(obj._p_set_async("k", "v"))
        assert target["k"] == "v"
        assert target["committed"] is True

    def test_async_connection_get_awaitable(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock()
        target: dict[str, Any] = {}
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        conn.transaction_serial = 0
        obj._p_status = SAVED

        async def async_get(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return target

        conn.get = MagicMock(side_effect=lambda *a, **kw: async_get(*a, **kw))
        conn.commit.return_value = None
        obj._p_oid = _oid_bytes(5)

        asyncio.run(obj._p_set_async("k", "v"))
        assert target["k"] == "v"

    def test_connection_object_without_setitem_skips_set(self) -> None:
        """If conn.get(...) returns something without __setitem__, the helper no-ops."""
        obj = _DictPersistent()
        conn = MagicMock()
        conn.get.return_value = 42
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        conn.transaction_serial = 0
        obj._p_status = SAVED
        obj._p_oid = _oid_bytes(6)

        # Should not raise.
        asyncio.run(obj._p_set_async("k", "v"))

    def test_connection_without_commit_attr(self) -> None:
        """``hasattr(conn, 'commit')`` False → commit path skipped."""
        obj = _DictPersistent()
        conn = MagicMock(spec=["get", "note_access", "transaction_serial"])
        target: dict[str, Any] = {}
        conn.get.return_value = target
        conn.note_access.return_value = None
        obj._p_connection = conn
        obj._p_serial = 0
        conn.transaction_serial = 0
        obj._p_status = SAVED
        obj._p_oid = _oid_bytes(7)

        asyncio.run(obj._p_set_async("k", "v"))
        assert target["k"] == "v"

    def test_no_connection_no_setitem_is_noop(self) -> None:
        """Branch 293→exit: when connection is None and the persistent has no
        ``__setitem__``, the helper completes as a no-op instead of blowing up."""

        class _NoSetItemPersistent(Persistent):
            """A bare Persistent without ``__setitem__``/``__getitem__``/``get``."""

        obj = _NoSetItemPersistent()
        # _p_connection is None; ``hasattr(self, '__setitem__')`` is False.
        asyncio.run(obj._p_set_async("k", "v"))
        # Helper returns without setting anything.
        assert not hasattr(obj, "k")


# ---------------------------------------------------------------------------
# _p_commit_async  (lines 301-306)
# ---------------------------------------------------------------------------


class TestCommitAsync:
    """``_p_commit_async`` invokes ``connection.commit`` (sync or async)."""

    def test_no_connection_no_call(self) -> None:
        obj = _DictPersistent()
        # _p_connection is None — the body short-circuits.
        result = asyncio.run(obj._p_commit_async())
        assert result is None

    def test_sync_commit(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock()
        conn.commit.return_value = None
        obj._p_connection = conn
        asyncio.run(obj._p_commit_async())
        conn.commit.assert_called_once()

    def test_async_commit_is_awaited(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock()

        async def async_commit() -> str:
            return "committed"

        conn.commit = MagicMock(side_effect=lambda: async_commit())
        obj._p_connection = conn
        asyncio.run(obj._p_commit_async())
        conn.commit.assert_called_once()

    def test_connection_without_commit_attr(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock(spec=[])  # no ``commit``
        obj._p_connection = conn
        # No error.
        asyncio.run(obj._p_commit_async())


# ---------------------------------------------------------------------------
# _p_abort_async  (lines 313-318)
# ---------------------------------------------------------------------------


class TestAbortAsync:
    """``_p_abort_async`` invokes ``connection.abort`` (sync or async)."""

    def test_no_connection_no_call(self) -> None:
        obj = _DictPersistent()
        result = asyncio.run(obj._p_abort_async())
        assert result is None

    def test_sync_abort(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock()
        conn.abort.return_value = None
        obj._p_connection = conn
        asyncio.run(obj._p_abort_async())
        conn.abort.assert_called_once()

    def test_async_abort_is_awaited(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock()

        async def async_abort() -> str:
            return "aborted"

        conn.abort = MagicMock(side_effect=lambda: async_abort())
        obj._p_connection = conn
        asyncio.run(obj._p_abort_async())
        conn.abort.assert_called_once()

    def test_connection_without_abort_attr(self) -> None:
        obj = _DictPersistent()
        conn = MagicMock(spec=[])  # no ``abort``
        obj._p_connection = conn
        # No error.
        asyncio.run(obj._p_abort_async())


# ---------------------------------------------------------------------------
# Coverage of __getattribute__ async-connection (lines 132-137)
# ---------------------------------------------------------------------------


class TestGetAttributeAsyncConnection:
    """``__getattribute__`` schedules a task when ``note_access`` is async.

    The production code path is:

        if connection.serial != self._p_serial:
            result = connection.note_access(self)
            if asyncio.iscoroutine(result) or hasattr(result, "send"):
                import asyncio
                with suppress(RuntimeError):
                    asyncio.get_running_loop()
                    asyncio.create_task(result)

    When there's no running event loop, the suppress() catches the RuntimeError
    and the helper still completes. We assert the asynchronous connection's
    note_access was invoked.
    """

    def test_note_access_sync_when_no_loop_returns_immediately(self) -> None:
        """Sync note_access returns a plain value; no task scheduling needed.

        This also exercises the ``hasattr(result, "__await__")`` False branch
        in production code (since ``str`` has neither attribute), so the
        ``asyncio`` import is skipped entirely.
        """
        obj = _SlotPersistent(value="x")
        obj._p_status = SAVED
        obj._p_serial = 0

        conn = MagicMock()
        conn.transaction_serial = 99
        conn.note_access.return_value = "sync"
        obj._p_connection = conn

        assert obj.value == "x"
        conn.note_access.assert_called_once_with(obj)

    def test_note_access_returns_plain_value_no_scheduling(self) -> None:
        """A non-awaitable, non-sendable value (like ``None`` or ``int``) skips
        the asyncio import in ``__getattribute__``."""
        obj = _SlotPersistent(value="hello")
        obj._p_status = SAVED
        obj._p_serial = 0

        conn = MagicMock()
        conn.transaction_serial = 1
        conn.note_access.return_value = 0  # int — no __await__, no send
        obj._p_connection = conn

        assert obj.value == "hello"
        conn.note_access.assert_called_once_with(obj)

    def test_getattribute_with_running_loop_schedules_task(self) -> None:
        """With a live loop, an async note_access is scheduled and awaited."""

        obj = _SlotPersistent(value=7)
        obj._p_status = SAVED
        obj._p_serial = 0

        async def coro() -> None:
            return None

        conn = MagicMock()
        conn.transaction_serial = 1
        conn.note_access = MagicMock(side_effect=lambda *_a, **_kw: coro())
        obj._p_connection = conn

        async def driver() -> None:
            # Yield enough times to ensure the scheduled task can run.
            assert obj.value == 7
            for _ in range(5):
                await asyncio.sleep(0)

        asyncio.run(driver())
        # The note_access was invoked when we accessed ``value``.
        conn.note_access.assert_called_once_with(obj)

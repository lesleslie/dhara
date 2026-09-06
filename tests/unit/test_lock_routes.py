"""Tests for dhara.lock.routes — REST route handlers for D-LOCK.

Covers every route handler exposed via :func:`register_lock_routes` plus the
``_handle_to_dict`` / ``_safe_json`` / ``_owner_header`` helpers and the
``_bind`` wrapper.

duckdb is mocked at import time so the test module loads under pytest-cov
without needing the duckdb C extension to be importable.
"""

from __future__ import annotations

import json as json_mod
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# CRITICAL: mock duckdb BEFORE importing any dhara.lock modules.
# dhara.lock.sql does `import duckdb` at module level; under pytest-cov
# the C extension import fails on some runners.
sys.modules.setdefault("duckdb", MagicMock())
sys.modules.setdefault("_duckdb", MagicMock())
sys.modules.setdefault("_duckdb._sqltypes", MagicMock())

from starlette.responses import JSONResponse  # noqa: E402

from dhara.lock import routes  # noqa: E402
from dhara.lock.protocol import (  # noqa: E402
    LockHandle,
    LockLost,
    LockPermanentError,
    LockTimeout,
)


# --------------------------- fakes ---------------------------


def _make_handle(
    lock_key: str = "k1",
    owner_token: str = "tok-abc",
    *,
    is_permanent: bool = False,
    ttl_seconds: int | None = 60,
    metadata: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> LockHandle:
    """Build a LockHandle with sensible defaults."""
    now = datetime.now(UTC)
    if is_permanent:
        # Permanent locks never expire; honours the LockHandle dataclass invariant.
        handle_expires: datetime | None = None
        handle_original_ttl: int | None = None
    elif expires_at is not None:
        handle_expires = expires_at
        handle_original_ttl = ttl_seconds
    else:
        handle_expires = now + timedelta(seconds=ttl_seconds or 60)
        handle_original_ttl = ttl_seconds
    return LockHandle(
        lock_key=lock_key,
        owner_token=owner_token,
        acquired_at=now,
        expires_at=handle_expires,
        is_permanent=is_permanent,
        original_ttl_seconds=handle_original_ttl,
        metadata=metadata or {},
    )


class FakeSQLBackendLock:
    """Duck-typed stand-in for SQLBackendLock.

    Each method's behaviour is fully programmable per test:

    * ``try_acquire_return`` — what ``try_acquire`` returns (handle or None).
    * ``try_acquire_raises`` — exception to raise instead.
    * ``acquire_return`` / ``acquire_raises`` — same for ``acquire``.
    * ``heartbeat_raises`` / ``release_raises`` — exception control.
    * ``get_return`` — value returned by ``get`` (handle or None).
    * ``list_return`` — list returned by ``list_keys``.
    * Calls are recorded so tests can assert ordering / arguments.
    """

    def __init__(
        self,
        *,
        try_acquire_return: LockHandle | None = None,
        try_acquire_raises: Exception | None = None,
        acquire_return: LockHandle | None = None,
        acquire_raises: Exception | None = None,
        heartbeat_raises: Exception | None = None,
        release_raises: Exception | None = None,
        get_return: LockHandle | None = None,
        list_return: list[LockHandle] | None = None,
    ) -> None:
        self._try_acquire_return = try_acquire_return
        self._try_acquire_raises = try_acquire_raises
        self._acquire_return = acquire_return
        self._acquire_raises = acquire_raises
        self._heartbeat_raises = heartbeat_raises
        self._release_raises = release_raises
        self._get_return = get_return
        self._list_return = list_return or []
        self.try_acquire_calls: list[dict[str, Any]] = []
        self.acquire_calls: list[dict[str, Any]] = []
        self.heartbeat_calls: list[dict[str, Any]] = []
        self.release_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.list_calls: list[str | None] = []

    def try_acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle | None:
        self.try_acquire_calls.append(
            {
                "lock_key": lock_key,
                "owner_token": owner_token,
                "ttl_seconds": ttl_seconds,
                "permanent": permanent,
                "metadata": metadata,
            }
        )
        if self._try_acquire_raises is not None:
            raise self._try_acquire_raises
        return self._try_acquire_return

    async def acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle:
        self.acquire_calls.append(
            {
                "lock_key": lock_key,
                "owner_token": owner_token,
                "ttl_seconds": ttl_seconds,
                "permanent": permanent,
                "timeout_seconds": timeout_seconds,
                "metadata": metadata,
            }
        )
        if self._acquire_raises is not None:
            raise self._acquire_raises
        assert self._acquire_return is not None, "acquire_return must be set"
        return self._acquire_return

    async def heartbeat(
        self,
        handle: LockHandle,
        *,
        extend_seconds: int | None = None,
    ) -> None:
        self.heartbeat_calls.append(
            {"handle": handle, "extend_seconds": extend_seconds}
        )
        if self._heartbeat_raises is not None:
            raise self._heartbeat_raises

    async def release(self, handle: LockHandle) -> None:
        self.release_calls.append({"handle": handle})
        if self._release_raises is not None:
            raise self._release_raises

    def get(self, lock_key: str) -> LockHandle | None:
        self.get_calls.append(lock_key)
        return self._get_return

    def list_keys(self, prefix: str | None = None) -> list[LockHandle]:
        self.list_calls.append(prefix)
        return list(self._list_return)


def _make_request(
    *,
    lock_key: str | None = "k1",
    body: Any = None,
    body_raw: Any = None,
    owner_token: str | None = None,
    prefix: str | None = None,
) -> MagicMock:
    """Build a Starlette/FastMCP request double."""
    request = MagicMock()
    request.path_params = {"lock_key": lock_key} if lock_key is not None else {}
    request.headers = {"X-Owner-Token": owner_token} if owner_token else {}
    request.query_params = {"prefix": prefix} if prefix is not None else {}

    if body is not None:

        async def _json() -> Any:
            return body

        request.json = _json
    else:

        async def _json() -> Any:
            return {}

        request.json = _json
    return request


# --------------------------- helpers ---------------------------


class TestHandleToDict:
    """Cover the pure helper that serializes LockHandle to JSON."""

    def test_basic(self) -> None:
        handle = _make_handle(metadata={"a": 1})
        out = routes._handle_to_dict(handle)
        assert out["lock_key"] == "k1"
        assert out["owner_token"] == "tok-abc"
        assert isinstance(out["acquired_at"], str)
        assert isinstance(out["expires_at"], str)
        assert out["is_permanent"] is False
        assert out["original_ttl_seconds"] == 60
        assert out["metadata"] == {"a": 1}

    def test_permanent_with_no_expiry(self) -> None:
        handle = _make_handle(is_permanent=True, ttl_seconds=None)
        out = routes._handle_to_dict(handle)
        assert out["is_permanent"] is True
        assert out["expires_at"] is None
        assert out["original_ttl_seconds"] is None

    def test_metadata_dict(self) -> None:
        handle = _make_handle(metadata={"k": "v"})
        out = routes._handle_to_dict(handle)
        assert out["metadata"] == {"k": "v"}


class TestSafeJson:
    """Cover the body parser including both error paths."""

    async def test_dict_returns_dict(self) -> None:
        req = _make_request(body={"owner_token": "x"})
        result = await routes._safe_json(req)
        assert result == {"owner_token": "x"}

    async def test_invalid_json_returns_400(self) -> None:
        req = _make_request(body_raw="not-valid-json")
        # Override .json to raise
        async def _bad() -> Any:
            raise ValueError("boom")

        req.json = _bad
        result = await routes._safe_json(req)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400
        body = json_mod.loads(result.body)
        assert body == {"error": "invalid json body"}

    async def test_non_dict_body_returns_400(self) -> None:
        req = _make_request(body=[1, 2, 3])
        result = await routes._safe_json(req)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400
        body = json_mod.loads(result.body)
        assert body == {"error": "body must be a JSON object"}


class TestOwnerHeader:
    def test_returns_value_when_present(self) -> None:
        req = _make_request(owner_token="tok-xyz")
        assert routes._owner_header(req) == "tok-xyz"

    def test_returns_none_when_absent(self) -> None:
        req = _make_request()
        assert routes._owner_header(req) is None


# --------------------------- POST /locks/{lock_key} ---------------------------


class TestPostLock:
    """POST /locks/{lock_key} — try_acquire (non-blocking)."""

    @pytest.mark.unit
    async def test_success(self) -> None:
        handle = _make_handle(owner_token="tok")
        store = FakeSQLBackendLock(try_acquire_return=handle)
        req = _make_request(body={"owner_token": "tok", "ttl_seconds": 60})
        resp = await routes._post_lock(req, store)
        assert resp.status_code == 200
        body = json_mod.loads(resp.body)
        assert body["lock_key"] == "k1"
        assert body["owner_token"] == "tok"
        assert store.try_acquire_calls[0]["lock_key"] == "k1"

    @pytest.mark.unit
    async def test_conflict_held_by_another(self) -> None:
        holder = _make_handle(owner_token="other-owner", is_permanent=False)
        store = FakeSQLBackendLock(try_acquire_return=None, get_return=holder)
        req = _make_request(body={})
        resp = await routes._post_lock(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["error"] == "lock_conflict"
        assert body["reason"] == "lock_lost"
        assert body["current_owner_token"] == "other-owner"

    @pytest.mark.unit
    async def test_conflict_duplicate_permanent(self) -> None:
        holder = _make_handle(owner_token="perm-owner", is_permanent=True)
        store = FakeSQLBackendLock(try_acquire_return=None, get_return=holder)
        req = _make_request(body={})
        resp = await routes._post_lock(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "duplicate_permanent"
        assert body["current_owner_token"] == "perm-owner"

    @pytest.mark.unit
    async def test_conflict_no_current_owner(self) -> None:
        """ try_acquire returns None and get() returns None — lock_lost with no owner. """
        store = FakeSQLBackendLock(try_acquire_return=None, get_return=None)
        req = _make_request(body={})
        resp = await routes._post_lock(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_lost"
        assert body["current_owner_token"] is None

    @pytest.mark.unit
    async def test_value_error_returns_400(self) -> None:
        store = FakeSQLBackendLock(
            try_acquire_raises=ValueError("permanent=True + ttl_seconds"),
        )
        req = _make_request(body={"permanent": True, "ttl_seconds": 30})
        resp = await routes._post_lock(req, store)
        assert resp.status_code == 400
        body = json_mod.loads(resp.body)
        assert body["error"] == "value_error"
        assert "permanent" in body["details"]

    @pytest.mark.unit
    async def test_invalid_json_returns_400(self) -> None:
        store = FakeSQLBackendLock()

        async def _bad() -> Any:
            raise ValueError("nope")

        req = _make_request()
        req.json = _bad
        resp = await routes._post_lock(req, store)
        assert resp.status_code == 400
        assert json_mod.loads(resp.body) == {"error": "invalid json body"}

    @pytest.mark.unit
    async def test_body_not_dict_returns_400(self) -> None:
        store = FakeSQLBackendLock()
        req = _make_request(body="a string")
        resp = await routes._post_lock(req, store)
        assert resp.status_code == 400
        assert json_mod.loads(resp.body) == {"error": "body must be a JSON object"}


# --------------------------- POST /locks/{lock_key}/acquire ---------------------------


class TestPostAcquire:
    """POST /locks/{lock_key}/acquire — acquire with wait/timeout."""

    @pytest.mark.unit
    async def test_success(self) -> None:
        handle = _make_handle()
        store = FakeSQLBackendLock(acquire_return=handle)
        req = _make_request(body={"timeout_seconds": 5})
        resp = await routes._post_acquire(req, store)
        assert resp.status_code == 200
        body = json_mod.loads(resp.body)
        assert body["lock_key"] == "k1"
        assert store.acquire_calls[0]["timeout_seconds"] == 5

    @pytest.mark.unit
    async def test_lock_timeout_returns_408(self) -> None:
        store = FakeSQLBackendLock(acquire_raises=LockTimeout("nope"))
        req = _make_request(body={})
        resp = await routes._post_acquire(req, store)
        assert resp.status_code == 408
        assert json_mod.loads(resp.body) == {"error": "lock_timeout"}

    @pytest.mark.unit
    async def test_value_error_returns_400(self) -> None:
        store = FakeSQLBackendLock(
            acquire_raises=ValueError("permanent=True + ttl_seconds"),
        )
        req = _make_request(body={"permanent": True, "ttl_seconds": 30})
        resp = await routes._post_acquire(req, store)
        assert resp.status_code == 400
        body = json_mod.loads(resp.body)
        assert body["error"] == "value_error"

    @pytest.mark.unit
    async def test_invalid_json_returns_400(self) -> None:
        store = FakeSQLBackendLock()

        async def _bad() -> Any:
            raise ValueError("bad")

        req = _make_request()
        req.json = _bad
        resp = await routes._post_acquire(req, store)
        assert resp.status_code == 400
        assert json_mod.loads(resp.body) == {"error": "invalid json body"}

    @pytest.mark.unit
    async def test_body_not_dict_returns_400(self) -> None:
        store = FakeSQLBackendLock()
        req = _make_request(body=[1, 2])
        resp = await routes._post_acquire(req, store)
        assert resp.status_code == 400
        assert json_mod.loads(resp.body) == {"error": "body must be a JSON object"}


# --------------------------- POST /locks/{lock_key}/heartbeat ---------------------------


class TestPostHeartbeat:
    """POST /locks/{lock_key}/heartbeat — extend TTL."""

    @pytest.mark.unit
    async def test_success(self) -> None:
        current = _make_handle(owner_token="mytok")
        store = FakeSQLBackendLock(get_return=current)
        req = _make_request(owner_token="mytok", body={"extend_seconds": 30})
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 204
        assert json_mod.loads(resp.body) == {}
        assert store.heartbeat_calls[0]["extend_seconds"] == 30

    @pytest.mark.unit
    async def test_missing_owner_header(self) -> None:
        store = FakeSQLBackendLock()
        req = _make_request(body={})
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 400
        assert json_mod.loads(resp.body) == {"error": "missing X-Owner-Token header"}

    @pytest.mark.unit
    async def test_lock_not_held(self) -> None:
        store = FakeSQLBackendLock(get_return=None)
        req = _make_request(owner_token="mytok", body={})
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_lost"
        assert "current_owner_token" not in body

    @pytest.mark.unit
    async def test_owner_mismatch(self) -> None:
        current = _make_handle(owner_token="someone-else")
        store = FakeSQLBackendLock(get_return=current)
        req = _make_request(owner_token="mytok", body={})
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_lost"
        assert body["current_owner_token"] == "someone-else"

    @pytest.mark.unit
    async def test_lock_permanent(self) -> None:
        current = _make_handle(owner_token="mytok", is_permanent=True)
        store = FakeSQLBackendLock(
            get_return=current,
            heartbeat_raises=LockPermanentError("permanent!"),
        )
        req = _make_request(owner_token="mytok", body={})
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_permanent"

    @pytest.mark.unit
    async def test_lock_lost_during_heartbeat(self) -> None:
        current = _make_handle(owner_token="mytok")
        store = FakeSQLBackendLock(
            get_return=current,
            heartbeat_raises=LockLost("expired"),
        )
        req = _make_request(owner_token="mytok", body={})
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_lost"
        assert "details" in body

    @pytest.mark.unit
    async def test_value_error_during_heartbeat(self) -> None:
        current = _make_handle(owner_token="mytok")
        store = FakeSQLBackendLock(
            get_return=current,
            heartbeat_raises=ValueError("advisory lock"),
        )
        req = _make_request(owner_token="mytok", body={})
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_lost"

    @pytest.mark.unit
    async def test_invalid_json(self) -> None:
        current = _make_handle(owner_token="mytok")
        store = FakeSQLBackendLock(get_return=current)

        async def _bad() -> Any:
            raise ValueError("bad")

        req = _make_request(owner_token="mytok")
        req.json = _bad
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 400
        assert json_mod.loads(resp.body) == {"error": "invalid json body"}

    @pytest.mark.unit
    async def test_body_not_dict(self) -> None:
        current = _make_handle(owner_token="mytok")
        store = FakeSQLBackendLock(get_return=current)
        req = _make_request(owner_token="mytok", body=[1])
        resp = await routes._post_heartbeat(req, store)
        assert resp.status_code == 400
        assert json_mod.loads(resp.body) == {"error": "body must be a JSON object"}


# --------------------------- DELETE /locks/{lock_key} ---------------------------


class TestDeleteLock:
    """DELETE /locks/{lock_key} — release a held lock."""

    @pytest.mark.unit
    async def test_success(self) -> None:
        current = _make_handle(owner_token="mytok")
        store = FakeSQLBackendLock(get_return=current)
        req = _make_request(owner_token="mytok")
        resp = await routes._delete_lock(req, store)
        assert resp.status_code == 204
        assert json_mod.loads(resp.body) == {}
        assert len(store.release_calls) == 1

    @pytest.mark.unit
    async def test_missing_owner_header(self) -> None:
        store = FakeSQLBackendLock()
        req = _make_request()
        resp = await routes._delete_lock(req, store)
        assert resp.status_code == 400
        assert json_mod.loads(resp.body) == {"error": "missing X-Owner-Token header"}

    @pytest.mark.unit
    async def test_lock_not_held(self) -> None:
        store = FakeSQLBackendLock(get_return=None)
        req = _make_request(owner_token="mytok")
        resp = await routes._delete_lock(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_lost"
        assert "current_owner_token" not in body

    @pytest.mark.unit
    async def test_owner_mismatch(self) -> None:
        current = _make_handle(owner_token="someone-else")
        store = FakeSQLBackendLock(get_return=current)
        req = _make_request(owner_token="mytok")
        resp = await routes._delete_lock(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_lost"
        assert body["current_owner_token"] == "someone-else"

    @pytest.mark.unit
    async def test_lock_permanent(self) -> None:
        current = _make_handle(owner_token="mytok")
        store = FakeSQLBackendLock(
            get_return=current,
            release_raises=LockPermanentError("permanent!"),
        )
        req = _make_request(owner_token="mytok")
        resp = await routes._delete_lock(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_permanent"

    @pytest.mark.unit
    async def test_lock_lost(self) -> None:
        current = _make_handle(owner_token="mytok")
        store = FakeSQLBackendLock(
            get_return=current,
            release_raises=LockLost("expired"),
        )
        req = _make_request(owner_token="mytok")
        resp = await routes._delete_lock(req, store)
        assert resp.status_code == 409
        body = json_mod.loads(resp.body)
        assert body["reason"] == "lock_lost"


# --------------------------- GET /locks/{lock_key} ---------------------------


class TestGetLock:
    """GET /locks/{lock_key} — fetch a single handle."""

    @pytest.mark.unit
    async def test_found(self) -> None:
        handle = _make_handle()
        store = FakeSQLBackendLock(get_return=handle)
        req = _make_request()
        resp = await routes._get_lock(req, store)
        assert resp.status_code == 200
        body = json_mod.loads(resp.body)
        assert body["lock_key"] == "k1"
        assert store.get_calls == ["k1"]

    @pytest.mark.unit
    async def test_not_found(self) -> None:
        store = FakeSQLBackendLock(get_return=None)
        req = _make_request()
        resp = await routes._get_lock(req, store)
        assert resp.status_code == 404
        assert json_mod.loads(resp.body) == {"error": "not_found"}


# --------------------------- GET /locks ---------------------------


class TestListLocks:
    """GET /locks?prefix=... — list handles, optionally filtered."""

    @pytest.mark.unit
    async def test_empty(self) -> None:
        store = FakeSQLBackendLock(list_return=[])
        req = _make_request()
        resp = await routes._list_locks(req, store)
        assert resp.status_code == 200
        assert json_mod.loads(resp.body) == []
        assert store.list_calls == [None]

    @pytest.mark.unit
    async def test_with_prefix(self) -> None:
        h1 = _make_handle(lock_key="alpha:1")
        h2 = _make_handle(lock_key="alpha:2", owner_token="t2")
        store = FakeSQLBackendLock(list_return=[h1, h2])
        req = _make_request(prefix="alpha:")
        resp = await routes._list_locks(req, store)
        assert resp.status_code == 200
        body = json_mod.loads(resp.body)
        assert len(body) == 2
        assert body[0]["lock_key"] == "alpha:1"
        assert body[1]["lock_key"] == "alpha:2"
        assert store.list_calls == ["alpha:"]

    @pytest.mark.unit
    async def test_without_prefix(self) -> None:
        h1 = _make_handle(lock_key="x")
        h2 = _make_handle(lock_key="y", owner_token="t2")
        store = FakeSQLBackendLock(list_return=[h1, h2])
        req = _make_request()  # no prefix
        resp = await routes._list_locks(req, store)
        assert resp.status_code == 200
        body = json_mod.loads(resp.body)
        assert len(body) == 2
        assert store.list_calls == [None]


# --------------------------- _bind / register_lock_routes ---------------------------


class TestBind:
    """Cover _bind — the FastMCP handler wrapper."""

    @pytest.mark.unit
    async def test_wrapper_calls_handler_with_request_and_store(self) -> None:
        async def fake_handler(request: Any, store: Any) -> str:
            return f"{request}-{store}"

        sentinel_request = MagicMock(name="request")
        store = FakeSQLBackendLock()
        wrapped = routes._bind(fake_handler, store)
        result = await wrapped(sentinel_request)
        assert result == f"{sentinel_request}-{store}"


class TestRegisterLockRoutes:
    """Cover register_lock_routes — registers all 6 routes via custom_route."""

    @pytest.mark.unit
    def test_registers_all_six_routes(self) -> None:
        # Track every (path, methods) tuple that custom_route is invoked with.
        captured: list[tuple[str, tuple[str, ...]]] = []
        decorator = MagicMock()

        def fake_custom_route(path: str, *, methods: list[str]):
            captured.append((path, tuple(methods)))
            return decorator

        server = MagicMock()
        server.custom_route = MagicMock(side_effect=fake_custom_route)
        sql_backend = MagicMock()

        routes.register_lock_routes(server, sql_backend)

        # Six routes registered.
        assert len(captured) == 6

        expected_paths = {
            "/locks/{lock_key}",
            "/locks/{lock_key}/acquire",
            "/locks/{lock_key}/heartbeat",
            "/locks",
        }
        seen_paths = {path for path, _ in captured}
        assert seen_paths == expected_paths

        # The /locks/{lock_key} path is registered three times (POST + DELETE + GET).
        path_methods: dict[str, list[str]] = {p: [] for p in expected_paths}
        for path, methods in captured:
            path_methods[path].extend(methods)
        assert sorted(path_methods["/locks/{lock_key}"]) == ["DELETE", "GET", "POST"]
        assert path_methods["/locks/{lock_key}/acquire"] == ["POST"]
        assert path_methods["/locks/{lock_key}/heartbeat"] == ["POST"]
        assert path_methods["/locks"] == ["GET"]

        # The decorator (returned from custom_route) was called with each
        # bound wrapper from _bind, so the server received a handler per route.
        assert decorator.call_count == 6
        for call in decorator.call_args_list:
            registered_handler = call.args[0]
            assert callable(registered_handler)

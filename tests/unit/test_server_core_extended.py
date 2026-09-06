"""Extended coverage for :mod:`dhara.mcp.server_core`.

Complements ``tests/test_mcp_server_core.py`` (init/probe/status paths) and
``tests/unit/test_server_core_cache.py`` (cache resolution) by exercising the
branches those files leave uncovered:

* the sync/async bridge helpers (``_run_cache_wire``,
  ``_run_async_connection_wire``, ``_ensure_loop_background_thread``,
  ``_SyncConnectionFacade``)
* the lightweight (``config=None``) construction mode and the D-AUDIT
  substrate wiring, including the ``storage_conn`` read-back tool and the
  periodic-flush task
* the ``postgres`` storage-backend branch and the D-LOCK route branch
* the HTTP route error handlers (``/health``, ``/ready``, ``/readyz``)
* the whole ``/tools/call`` REST shim
* ``_read_backup_catalog_async``'s ``__state__`` envelope unwrapping

Everything is mocked: no sockets, no real storage, no network.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dhara.audit.subscriber import AuditLogSubscriber
from dhara.core.config import (
    AuthenticationConfig,
    BackupRuntimeConfig,
    DharaSettings,
    StorageConfig,
)
from dhara.mcp import server_core
from dhara.mcp.server_core import DharaMCPServer

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _stop_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Stop the daemon-driven wire loop and release its thread."""
    with suppress(Exception):
        loop.call_soon_threadsafe(loop.stop)
    thread = getattr(loop, "_dhara_wire_thread", None)
    if thread is not None:
        with suppress(Exception):
            thread.join(timeout=2)
        loop._dhara_wire_thread = None  # ty: ignore[unresolved-attribute]
    with suppress(Exception):
        if not loop.is_closed():
            loop.close()


@pytest.fixture(autouse=True)
def _reset_wire_loop() -> Iterator[None]:
    """Reset the module-global wire loop before and after each test.

    ``_run_cache_wire`` / ``_run_async_connection_wire`` memoize a persistent
    loop in ``server_core._CACHE_WIRE_LOOP`` and spin a daemon thread over it.
    Leaving that loop installed makes later ``run_until_complete`` calls raise
    ``RuntimeError: This event loop is already running``.
    """

    def _reset() -> None:
        loop = server_core._CACHE_WIRE_LOOP
        if loop is not None:
            _stop_loop(loop)
        server_core._CACHE_WIRE_LOOP = None

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _reset_audit_singleton() -> Iterator[None]:
    """Keep ``AuditLogSubscriber._instance`` from leaking between tests."""
    previous = AuditLogSubscriber._instance
    yield
    AuditLogSubscriber._instance = previous


def _make_config(tmp_path: Path, **overrides: Any) -> DharaSettings:
    defaults: dict[str, Any] = {
        "server_name": "extended-dhara",
        "storage": StorageConfig(path=tmp_path / "test.dhara"),
        "authentication": AuthenticationConfig(enabled=False),
        "backups": BackupRuntimeConfig(enabled=False, directory=tmp_path / "backups"),
    }
    defaults.update(overrides)
    return DharaSettings(**defaults)


def _make_capturing_server() -> tuple[MagicMock, dict[str, Any]]:
    """Build a FastMCP stand-in that records ``custom_route`` handlers."""
    routes: dict[str, Any] = {}
    server = MagicMock(name="FastMCP")

    def _custom_route(path: str, **_kw: Any) -> Any:
        def _decorator(fn: Any) -> Any:
            routes[path] = fn
            return fn

        return _decorator

    server.custom_route = MagicMock(side_effect=_custom_route)
    server.tool = MagicMock(side_effect=lambda **_kw: (lambda fn: fn))
    server.add_tool = MagicMock(side_effect=lambda tool: tool)
    server.list_tools = AsyncMock(return_value=[])
    server.get_tools = AsyncMock(return_value=[])
    return server, routes


@contextmanager
def _stubbed_server(config: DharaSettings) -> Iterator[tuple[Any, dict[str, Any]]]:
    """Construct a ``DharaMCPServer`` with every heavy collaborator stubbed."""
    server_mock, routes = _make_capturing_server()
    with (
        patch.object(server_core, "FastMCP", return_value=server_mock),
        patch.object(server_core, "build_token_verifier", return_value=None),
        patch.object(server_core, "_run_cache_wire", return_value=MagicMock()),
        patch.object(
            server_core, "_run_async_connection_wire", return_value=MagicMock()
        ),
        patch.object(server_core, "AdapterRegistry", return_value=MagicMock()),
        patch.object(DharaMCPServer, "_register_tools", MagicMock()),
    ):
        srv = DharaMCPServer(config)
    yield srv, routes


def _bare_server(**attrs: Any) -> Any:
    """Build a ``DharaMCPServer`` without running ``__init__``."""
    from dhara.audit.outbox import MemoryOutbox

    srv = DharaMCPServer.__new__(DharaMCPServer)
    srv._storage_conn = None
    srv._audit_outbox = MemoryOutbox()
    srv._registered_tools = {}
    srv._audit_subscriber = None
    srv._audit_flush_task = None
    srv._async_kv_store = None
    srv._async_ecosystem_state = None
    srv._async_adapter_registry = None
    for key, value in attrs.items():
        setattr(srv, key, value)
    return srv


class _FakeRequest:
    """Minimal Starlette-request stand-in for the ``/tools/call`` shim."""

    def __init__(self, payload: Any = None, *, raise_on_json: bool = False) -> None:
        self._payload = payload
        self._raise = raise_on_json

    async def json(self) -> Any:
        if self._raise:
            raise ValueError("not json")
        return self._payload


def _body(response: Any) -> dict[str, Any]:
    return json.loads(response.body)


# ---------------------------------------------------------------------------
# _run_cache_wire
# ---------------------------------------------------------------------------


async def test_run_cache_wire_rejects_active_event_loop() -> None:
    """Running inside a live loop is a programming error, not a fallback."""
    with pytest.raises(RuntimeError, match="cache wiring cannot run"):
        server_core._run_cache_wire(MagicMock(), MagicMock())


def test_run_cache_wire_reuses_existing_open_loop() -> None:
    """An already-created, still-open wire loop is reused verbatim."""
    loop = asyncio.new_event_loop()
    server_core._CACHE_WIRE_LOOP = loop

    async def _fake_wire(_config: Any, _core: Any) -> str:
        return "wired"

    try:
        with patch.object(server_core, "_wire_cache", _fake_wire):
            result = server_core._run_cache_wire(MagicMock(), MagicMock())
        assert result == "wired"
        assert server_core._CACHE_WIRE_LOOP is loop
    finally:
        _stop_loop(loop)
        server_core._CACHE_WIRE_LOOP = None


def test_run_cache_wire_replaces_closed_loop() -> None:
    """A closed wire loop is discarded and rebuilt."""
    closed = asyncio.new_event_loop()
    closed.close()
    server_core._CACHE_WIRE_LOOP = closed

    async def _fake_wire(_config: Any, _core: Any) -> str:
        return "fresh"

    with patch.object(server_core, "_wire_cache", _fake_wire):
        assert server_core._run_cache_wire(MagicMock(), MagicMock()) == "fresh"

    assert server_core._CACHE_WIRE_LOOP is not closed
    assert not server_core._CACHE_WIRE_LOOP.is_closed()


# ---------------------------------------------------------------------------
# _BuiltinCacheRegistry
# ---------------------------------------------------------------------------


async def test_builtin_registry_returns_known_factory_paths() -> None:
    registry = server_core._BuiltinCacheRegistry()
    memory = await registry.get_adapter_async("adapter", "cache", "memory")
    redis = await registry.get_adapter_async("adapter", "cache", "redis")
    assert memory == {
        "factory_path": "oneiric.adapters.cache.memory:MemoryCacheAdapter"
    }
    assert redis == {"factory_path": "oneiric.adapters.cache.redis:RedisCacheAdapter"}


async def test_builtin_registry_returns_none_for_unknown_provider() -> None:
    registry = server_core._BuiltinCacheRegistry()
    assert await registry.get_adapter_async("adapter", "cache", "nope") is None


# ---------------------------------------------------------------------------
# _SyncConnectionFacade
# ---------------------------------------------------------------------------


def test_sync_connection_facade_bridges_all_sync_call_sites() -> None:
    """``get_root``/``commit``/``abort``/``cache`` all dispatch to the async conn."""
    loop = asyncio.new_event_loop()
    server_core._ensure_loop_background_thread(loop)
    try:
        cache_sentinel = MagicMock(name="cache")
        async_conn = AsyncMock(name="AsyncConnection")
        async_conn.storage = MagicMock(name="storage")
        async_conn.cache = cache_sentinel
        async_conn.get_root = AsyncMock(return_value={"a": 1})
        async_conn.commit = AsyncMock(return_value=None)
        async_conn.abort = AsyncMock(return_value=None)

        facade = server_core._SyncConnectionFacade(async_conn, loop)

        assert facade.storage is async_conn.storage
        assert facade.get_root() == {"a": 1}
        assert facade.commit() is None
        assert facade.abort() is None
        assert facade.cache is cache_sentinel

        async_conn.get_root.assert_awaited_once()
        async_conn.commit.assert_awaited_once()
        async_conn.abort.assert_awaited_once()
    finally:
        _stop_loop(loop)


# ---------------------------------------------------------------------------
# _run_async_connection_wire / _ensure_loop_background_thread
# ---------------------------------------------------------------------------


async def test_run_async_connection_wire_rejects_active_event_loop() -> None:
    with pytest.raises(RuntimeError, match="async-connection wire cannot run"):
        server_core._run_async_connection_wire(MagicMock())


def test_run_async_connection_wire_creates_loop_and_enters_storage() -> None:
    """A ``None`` wire loop is created, and un-entered storage is ``__aenter__``ed."""
    server_core._CACHE_WIRE_LOOP = None

    storage = AsyncMock(name="AsyncFileStorage")
    storage._conn = None  # forces the explicit __aenter__ path

    async_conn = AsyncMock(name="AsyncConnection")
    async_conn.storage = storage
    async_conn.cache = MagicMock()

    with patch(
        "dhara.core.connection.AsyncConnection.new",
        new=AsyncMock(return_value=async_conn),
    ):
        facade = server_core._run_async_connection_wire(storage)

    assert isinstance(facade, server_core._SyncConnectionFacade)
    assert facade._async is async_conn
    storage.__aenter__.assert_awaited_once()
    assert server_core._CACHE_WIRE_LOOP is not None
    assert facade._loop is server_core._CACHE_WIRE_LOOP


def test_run_async_connection_wire_skips_aenter_when_storage_ready() -> None:
    """A pre-entered storage (``_conn`` truthy) is not re-entered."""
    server_core._CACHE_WIRE_LOOP = None

    storage = AsyncMock(name="AsyncFileStorage")
    storage._conn = True

    async_conn = AsyncMock(name="AsyncConnection")
    async_conn.storage = storage
    async_conn.cache = MagicMock()

    with patch(
        "dhara.core.connection.AsyncConnection.new",
        new=AsyncMock(return_value=async_conn),
    ):
        facade = server_core._run_async_connection_wire(storage)

    assert isinstance(facade, server_core._SyncConnectionFacade)
    storage.__aenter__.assert_not_awaited()


def test_ensure_loop_background_thread_is_idempotent() -> None:
    loop = asyncio.new_event_loop()
    try:
        server_core._ensure_loop_background_thread(loop)
        first = loop._dhara_wire_thread
        assert first is not None

        server_core._ensure_loop_background_thread(loop)
        assert loop._dhara_wire_thread is first
    finally:
        _stop_loop(loop)


# ---------------------------------------------------------------------------
# Lightweight (config=None) construction + D-AUDIT substrate
# ---------------------------------------------------------------------------


def test_lightweight_construction_skips_infrastructure() -> None:
    """``config=None`` wires only the audit substrate."""
    srv = DharaMCPServer(config=None)

    assert srv.config is None
    assert srv.server is None
    assert srv.auth_verifier is None
    assert srv._audit_outbox is not None
    assert srv._audit_subscriber is None
    assert srv._audit_flush_task is None
    assert srv._registered_tools == {}
    assert srv._start_time > 0


def test_lightweight_register_tools_registers_audit_subscriber() -> None:
    """Without a ``storage_conn`` the read-back tool is skipped."""
    srv = DharaMCPServer(config=None)
    srv._register_tools()

    assert srv._audit_subscriber is not None
    assert AuditLogSubscriber.get_instance() is srv._audit_subscriber
    assert "audit_record_query" not in srv._registered_tools
    assert srv._audit_flush_task is None


def test_lightweight_register_tools_exposes_query_tool_with_storage_conn() -> None:
    """A DuckDB handle enables ``audit_record_query`` registration."""
    srv = DharaMCPServer(config=None, storage_conn=MagicMock(name="duckdb"))
    srv._register_tools()

    assert callable(srv._registered_tools["audit_record_query"])
    # No running loop during a sync call, so the flush task is not scheduled.
    assert srv._audit_flush_task is None


async def test_register_tools_schedules_flush_task_inside_running_loop() -> None:
    """Inside a live loop the periodic flush loop is scheduled and retained."""
    started = asyncio.Event()

    async def _fake_flush_loop(_flusher: Any) -> None:
        started.set()
        await asyncio.sleep(3600)

    srv = DharaMCPServer(config=None, storage_conn=MagicMock(name="duckdb"))
    with (
        patch.object(server_core, "OutboxFlusher", MagicMock()),
        patch.object(server_core, "periodic_flush_loop", _fake_flush_loop),
    ):
        srv._register_tools()

        assert srv._audit_flush_task is not None
        await asyncio.wait_for(started.wait(), timeout=2)
        srv._audit_flush_task.cancel()
        with suppress(asyncio.CancelledError):
            await srv._audit_flush_task


def test_register_audit_routes_delegates_to_register_tools() -> None:
    """The module-level helper mirrors D-LOCK's ``register_lock_routes``."""
    srv = DharaMCPServer(config=None)
    with patch.object(srv, "_register_tools") as mock_register:
        server_core.register_audit_routes(srv)
    mock_register.assert_called_once_with()


def test_register_audit_routes_end_to_end_on_lightweight_server() -> None:
    srv = DharaMCPServer(config=None, storage_conn=MagicMock(name="duckdb"))
    server_core.register_audit_routes(srv)
    assert "audit_record_query" in srv._registered_tools


# ---------------------------------------------------------------------------
# Storage backend selection
# ---------------------------------------------------------------------------


def test_postgres_storage_backend_builds_postgres_adapter(tmp_path: Path) -> None:
    config = _make_config(
        tmp_path,
        storage_backend="postgres",
        storage_pg_url="postgresql://example/dharatest",
    )
    adapter = MagicMock(name="PostgresStorageAdapter instance")
    with patch(
        "dhara.storage.postgres.PostgresStorageAdapter", return_value=adapter
    ) as adapter_cls:
        with _stubbed_server(config) as (srv, _routes):
            assert srv.storage is adapter
    adapter_cls.assert_called_once_with(url="postgresql://example/dharatest")


def test_postgres_backend_falls_back_to_default_url(tmp_path: Path) -> None:
    """A missing ``storage_pg_url`` yields the localhost default."""
    config = _make_config(tmp_path, storage_backend="postgres")
    with patch("dhara.storage.postgres.PostgresStorageAdapter") as adapter_cls:
        with _stubbed_server(config):
            pass
    assert adapter_cls.call_args.kwargs["url"].startswith("postgresql://")


# ---------------------------------------------------------------------------
# D-LOCK route branch
# ---------------------------------------------------------------------------


def test_register_tools_registers_lock_routes_when_sql_backend_present() -> None:
    fastmcp, _routes = _make_capturing_server()
    sql_backend = MagicMock(name="sql_backend")
    srv = _bare_server(server=fastmcp, connection=MagicMock(), sql_backend=sql_backend)

    with (
        patch.object(DharaMCPServer, "_apply_w0_profile", AsyncMock()),
        patch.object(server_core, "register_substrate_routes") as substrate,
        patch("dhara.lock.routes.register_lock_routes") as lock_routes,
        patch.object(DharaMCPServer, "_register_tools_call_route", MagicMock()),
    ):
        srv._register_tools()

    substrate.assert_called_once_with(fastmcp, srv.connection)
    lock_routes.assert_called_once_with(fastmcp, sql_backend)


def test_register_tools_skips_lock_routes_without_sql_backend() -> None:
    fastmcp, _routes = _make_capturing_server()
    srv = _bare_server(server=fastmcp, connection=MagicMock())

    with (
        patch.object(DharaMCPServer, "_apply_w0_profile", AsyncMock()),
        patch.object(server_core, "register_substrate_routes"),
        patch("dhara.lock.routes.register_lock_routes") as lock_routes,
        patch.object(DharaMCPServer, "_register_tools_call_route", MagicMock()),
    ):
        srv._register_tools()

    lock_routes.assert_not_called()


# ---------------------------------------------------------------------------
# HTTP route error handlers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["/health", "/ready", "/readyz"])
async def test_probe_routes_return_503_on_runtime_status_error(
    tmp_path: Path, route: str
) -> None:
    """A raising ``_runtime_status`` surfaces as a typed 503 payload."""
    config = _make_config(tmp_path)
    with _stubbed_server(config) as (srv, routes):
        handler = routes[route]
        with patch.object(
            srv, "_runtime_status", side_effect=RuntimeError("probe exploded")
        ):
            response = await handler(_FakeRequest())

    assert response.status_code == 503
    payload = _body(response)
    assert payload == {
        "status": "error",
        "service": "dhara",
        "error": "probe exploded",
    }


@pytest.mark.parametrize("route", ["/health", "/ready", "/readyz"])
async def test_probe_routes_return_200_when_ready(tmp_path: Path, route: str) -> None:
    config = _make_config(tmp_path)
    with _stubbed_server(config) as (srv, routes):
        with patch.object(srv, "_runtime_status", return_value={"ready": True}):
            response = await routes[route](_FakeRequest())
    assert response.status_code == 200


async def test_healthz_route_is_unconditional(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    with _stubbed_server(config) as (_srv, routes):
        response = await routes["/healthz"](_FakeRequest())
    assert response.status_code == 200
    assert _body(response) == {"status": "ok"}


# ---------------------------------------------------------------------------
# /tools/call REST shim
# ---------------------------------------------------------------------------


@contextmanager
def _tools_call_handler(**attrs: Any) -> Iterator[Any]:
    fastmcp, routes = _make_capturing_server()
    srv = _bare_server(server=fastmcp, **attrs)
    srv._register_tools_call_route()
    yield srv, routes["/tools/call"]


async def test_tools_call_rejects_invalid_json() -> None:
    with _tools_call_handler() as (_srv, handler):
        response = await handler(_FakeRequest(raise_on_json=True))
    assert response.status_code == 400
    assert _body(response) == {"error": "Invalid JSON"}


async def test_tools_call_requires_tool_name() -> None:
    with _tools_call_handler() as (_srv, handler):
        response = await handler(_FakeRequest({"arguments": {}}))
    assert response.status_code == 400
    assert _body(response) == {"error": "Missing tool name"}


async def test_tools_call_rejects_unknown_tool() -> None:
    with _tools_call_handler() as (_srv, handler):
        response = await handler(_FakeRequest({"name": "nope"}))
    assert response.status_code == 404
    assert _body(response) == {"error": "Unknown tool: nope"}


@pytest.mark.parametrize("tool_name", ["get", "put", "list_prefix"])
async def test_tools_call_reports_uninitialized_kv_store(tool_name: str) -> None:
    with _tools_call_handler() as (_srv, handler):
        response = await handler(_FakeRequest({"name": tool_name}))
    assert response.status_code == 500
    assert _body(response) == {"error": f"Store not initialized: {tool_name}"}


@pytest.mark.parametrize(
    "tool_name",
    ["list_services", "get_service", "record_event", "list_events"],
)
async def test_tools_call_reports_uninitialized_ecosystem_store(
    tool_name: str,
) -> None:
    with _tools_call_handler() as (_srv, handler):
        response = await handler(_FakeRequest({"name": tool_name}))
    assert response.status_code == 500
    assert _body(response) == {"error": f"Store not initialized: {tool_name}"}


async def test_tools_call_returns_akosha_content_envelope() -> None:
    kv_store = MagicMock(name="AsyncKVTimeSeriesStore")
    kv_store.get_async = MagicMock(return_value={"value": 42})
    with _tools_call_handler(_async_kv_store=kv_store) as (_srv, handler):
        response = await handler(
            _FakeRequest({"name": "get", "arguments": {"key": "k"}})
        )

    kv_store.get_async.assert_called_once_with(key="k")
    payload = _body(response)
    assert payload["isError"] is False
    assert json.loads(payload["content"][0]["text"]) == {"value": 42}


async def test_tools_call_dispatches_ecosystem_state_tools() -> None:
    eco = MagicMock(name="AsyncEcosystemStateStore")
    eco.list_services_async = MagicMock(return_value=["dhara"])
    with _tools_call_handler(_async_ecosystem_state=eco) as (_srv, handler):
        response = await handler(_FakeRequest({"name": "list_services"}))

    payload = _body(response)
    assert payload["isError"] is False
    assert json.loads(payload["content"][0]["text"]) == ["dhara"]


async def test_tools_call_wraps_store_exceptions_as_is_error() -> None:
    kv_store = MagicMock(name="AsyncKVTimeSeriesStore")
    kv_store.put_async = MagicMock(side_effect=RuntimeError("write failed"))
    with _tools_call_handler(_async_kv_store=kv_store) as (_srv, handler):
        response = await handler(
            _FakeRequest({"name": "put", "arguments": {"key": "k", "value": 1}})
        )

    assert response.status_code == 500
    payload = _body(response)
    assert payload["isError"] is True
    assert json.loads(payload["content"][0]["text"]) == {"error": "write failed"}


# ---------------------------------------------------------------------------
# _read_backup_catalog_async
# ---------------------------------------------------------------------------


@contextmanager
def _patched_catalog_root(root: dict[str, Any]) -> Iterator[AsyncMock]:
    storage = AsyncMock(name="AsyncFileStorage")
    async_conn = AsyncMock(name="AsyncConnection")
    async_conn.get_root = AsyncMock(return_value=root)
    with (
        patch.object(server_core, "AsyncFileStorage", return_value=storage),
        patch(
            "dhara.core.connection.AsyncConnection.new",
            new=AsyncMock(return_value=async_conn),
        ),
    ):
        yield storage


def test_read_backup_catalog_unwraps_state_envelopes(tmp_path: Path) -> None:
    """Both the outer mapping and each entry may be ``__state__``-wrapped."""
    root = {
        "backups": {
            "__state__": {
                "data": {
                    "b1": {
                        "__state__": {
                            "data": {
                                "backup_id": "b1",
                                "timestamp": "2026-01-01T00:00:00Z",
                            }
                        }
                    },
                    "b2": {
                        "backup_id": "b2",
                        "timestamp": "2026-02-01T00:00:00Z",
                    },
                }
            }
        }
    }
    srv = _bare_server()
    with _patched_catalog_root(root) as storage:
        result = srv._read_backup_catalog_async(tmp_path / "backup_catalog.dhara")

    assert result == {
        "total_backups": 2,
        "latest_backup_id": "b2",
        "latest_backup_at": "2026-02-01T00:00:00Z",
    }
    storage.close.assert_awaited_once()


def test_read_backup_catalog_ignores_entries_without_timestamps(
    tmp_path: Path,
) -> None:
    root = {"backups": {"b1": {"backup_id": "b1"}}}
    srv = _bare_server()
    with _patched_catalog_root(root):
        result = srv._read_backup_catalog_async(tmp_path / "backup_catalog.dhara")

    assert result == {
        "total_backups": 1,
        "latest_backup_id": None,
        "latest_backup_at": None,
    }


def test_read_backup_catalog_handles_missing_backups_key(tmp_path: Path) -> None:
    srv = _bare_server()
    with _patched_catalog_root({}):
        result = srv._read_backup_catalog_async(tmp_path / "backup_catalog.dhara")

    assert result["total_backups"] == 0
    assert result["latest_backup_id"] is None

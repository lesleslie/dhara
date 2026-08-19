"""Dhara MCP Server using FastMCP framework.

import operator
This module implements the canonical Dhara MCP server using FastMCP patterns
consistent with Mahavishnu, Session-Buddy, and Crackerjack.

Migration Notes:
- Replaces custom tool registration with FastMCP @server.tool() decorators
- Uses DharaSettings as the canonical runtime configuration surface
- Adds canonical bearer-token auth when enabled in Dhara settings
- Adds adapter distribution tools via AdapterRegistry
- Adds ecosystem state tools for service and event persistence
- Adds health check tools via mcp-common
"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, ClassVar, cast

if TYPE_CHECKING:
    import duckdb

# ``Connection`` is re-exported at module scope so legacy test fixtures can
# patch ``dhara.mcp.server_core.Connection`` directly. The runtime code
# paths use ``AsyncConnection`` instead, but the symbol is required by
# the test suite for symbol-level monkeypatching.

from fastmcp.server.auth.authorization import require_scopes
from mcp_common.fastmcp import FastMCP
from mcp_common.health import (
    DependencyConfig,
    register_health_tools,
)
from oneiric.adapters.cache import MemoryCacheSettings, RedisCacheSettings
from oneiric.core.config import load_settings
from oneiric.core.logging import get_logger

from dhara.audit.flusher import OutboxFlusher, periodic_flush_loop
from dhara.audit.outbox import MemoryOutbox
from dhara.audit.subscriber import AuditLogSubscriber
from dhara.core.config import DharaSettings
from dhara.core.connection import Connection
from dhara.mcp.adapter_lookup import resolve_cache_adapter
from dhara.mcp.adapter_tools import (
    AdapterRegistry,
    AsyncAdapterRegistry,
    get_adapter_async_impl,
    get_adapter_health_async_impl,
    list_adapter_versions_async_impl,
    list_adapters_async_impl,
    store_adapter_async_impl,
    validate_adapter_async_impl,
)
from dhara.mcp.ecosystem_state import AsyncEcosystemStateStore, EventRetention
from dhara.mcp.fastmcp_auth import build_token_verifier
from dhara.mcp.kv_timeseries import AsyncKVTimeSeriesStore, TimeSeriesRetention
from dhara.mcp.substrate_routes import register_substrate_routes
from dhara.storage.async_file import AsyncFileStorage

logger = get_logger(__name__)
_DEFAULT_RESOLVE_CACHE_ADAPTER = resolve_cache_adapter
_CACHE_WIRE_LOOP: asyncio.AbstractEventLoop | None = None

# Version is read from installed package metadata so the MCP ``/health``
# version always matches ``pyproject.toml`` (currently 0.15.2). Matches the
# pattern already used in ``dhara/cli.py``.
try:
    _PACKAGE_VERSION = version("dhara")
except PackageNotFoundError:
    _PACKAGE_VERSION = "0.0.0+unknown"


class _BuiltinCacheRegistry:
    """Registry fallback used before the async Dhara stores are initialized.

    ``DharaMCPServer`` has a synchronous constructor while the persistent
    ``AsyncAdapterRegistry`` is created by ``_init_async_stores``.  Cache
    wiring still goes through ``resolve_cache_adapter`` during construction;
    this small registry exposes the canonical Oneiric factory paths until the
    persistent registry is available.
    """

    _FACTORIES: ClassVar[dict[tuple[str, str, str], str]] = {
        ("adapter", "cache", "memory"): (
            "oneiric.adapters.cache.memory:MemoryCacheAdapter"
        ),
        ("adapter", "cache", "redis"): (
            "oneiric.adapters.cache.redis:RedisCacheAdapter"
        ),
    }

    async def get_adapter_async(
        self, domain: str, key: str, provider: str
    ) -> dict[str, str] | None:
        factory_path = self._FACTORIES.get((domain, key, provider))
        return {"factory_path": factory_path} if factory_path else None


async def _wire_cache(config: Any, core_self: Any) -> Any:
    """Resolve and instantiate the cache adapter via the registry helper.

    Settings come from OneiricSettings.adapters.provider_settings (the
    canonical Oneiric path) so Dhara owns no cache-specific config fields.
    """
    cache_backend = getattr(config, "cache_backend", "memory")
    if cache_backend == "redis":
        provider_settings = load_settings(
            project_name="dhara"
        ).adapters.provider_settings.get("cache.redis", {})
        cache_settings = (
            RedisCacheSettings(**provider_settings)
            if provider_settings
            else RedisCacheSettings()
        )
    else:
        cache_settings = MemoryCacheSettings()

    registry = core_self._async_adapter_registry or _BuiltinCacheRegistry()
    resolver = resolve_cache_adapter
    if resolver is _DEFAULT_RESOLVE_CACHE_ADAPTER:
        from dhara.mcp import adapter_lookup

        resolver = adapter_lookup.resolve_cache_adapter
    adapter = await resolver(
        backend=cache_backend,
        settings=cache_settings,
        registry=registry,
    )
    logger_for_core = getattr(core_self, "_logger", logger)
    logger_for_core.info(
        "cache-adapter-resolved",
        backend=cache_backend,
        provider=cache_backend,
        settings_class=type(cache_settings).__name__,
    )
    return adapter


def _run_cache_wire(config: Any, core_self: Any) -> Any:
    """Run cache wiring without closing the process-wide event loop."""
    global _CACHE_WIRE_LOOP
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("cache wiring cannot run inside an active event loop")
    if _CACHE_WIRE_LOOP is None or _CACHE_WIRE_LOOP.is_closed():
        _CACHE_WIRE_LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_CACHE_WIRE_LOOP)
    return _CACHE_WIRE_LOOP.run_until_complete(_wire_cache(config, core_self))


class _SyncConnectionFacade:
    """Sync-compatible facade over an ``AsyncConnection``.

    The post-async-migration DharaMCPServer keeps a single sync
    ``DharaMCPServer.__init__`` while the storage layer is now async-only.
    Most of the MCP-server machinery (AdapterRegistry, substrate routes,
    ``_probe_storage``) reads ``connection.get_root()``,
    ``connection.commit()``, and ``connection.storage`` synchronously.
    This facade drives each call through the persistent ``_CACHE_WIRE_LOOP``
    so those sync call sites keep working without rewriting them.

    Safe under nested-event-loop call sites: when invoked from inside an
    existing loop (FastMCP handlers, ``_probe_storage`` called from
    async endpoints, etc.), we dispatch via
    ``asyncio.run_coroutine_threadsafe`` instead of ``run_until_complete``
    to avoid ``RuntimeError: This loop is already running``.

    Lifecycle: created by ``_run_async_connection_wire`` during ``__init__``.
    After init, async tool handlers should prefer the original
    ``AsyncConnection`` (``facade._async``) when calling async APIs.
    """

    def __init__(
        self,
        async_connection: Any,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._async = async_connection
        self._loop = loop
        self.storage = async_connection.storage

    def _run(self, coro: Any) -> Any:
        # Always bridge to the persistent loop via run_coroutine_threadsafe
        # rather than calling run_until_complete directly: the persistent
        # loop is driven by a daemon thread, so calling run_until_complete
        # from the caller's thread would either raise "This event loop is
        # already running" or block forever waiting for the daemon thread
        # to deliver the result. ``run_coroutine_threadsafe`` is the only
        # cross-thread-safe way to schedule and wait for completion.
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(None)

    def get_root(self) -> Any:
        return self._run(self._async.get_root())

    def commit(self) -> None:
        self._run(self._async.commit())

    def abort(self) -> None:
        self._run(self._async.abort())

    @property
    def cache(self) -> Any:
        return self._async.cache


def _run_async_connection_wire(storage: Any) -> _SyncConnectionFacade:
    """Build ``AsyncConnection.new(storage)`` synchronously and wrap in a facade.

    Mirrors the cache-wiring pattern: reuses the persistent ``_CACHE_WIRE_LOOP``
    so we don't create-and-close a fresh loop on each call (which would
    terminate the process event loop for the rest of the app).

    The ``storage`` arg may be an initialized ``AsyncStorage`` instance or a
    filesystem path (str). When a pre-built ``AsyncFileStorage`` is supplied,
    we explicitly run its ``__aenter__`` because ``AsyncConnection.new`` only
    initializes bare ``str``/``Path`` inputs — passing an un-entered instance
    back into the factory leaves the storage in an un-initialized state and
    any later ``load()`` raises ``RuntimeError("Storage not initialized")``.
    """
    global _CACHE_WIRE_LOOP
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "async-connection wire cannot run inside an active event loop"
        )
    if _CACHE_WIRE_LOOP is None or _CACHE_WIRE_LOOP.is_closed():
        _CACHE_WIRE_LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_CACHE_WIRE_LOOP)

    from dhara.core.connection import AsyncConnection

    # ``AsyncConnection.new`` only enters the storage when given a ``str`` or
    # ``Path``; passing a pre-built ``AsyncFileStorage`` skips that branch and
    # leaves the storage uninitialized. Run ``__aenter__`` ourselves when the
    # storage has not yet acquired its underlying connection (i.e. ``_conn``
    # is still ``None``).
    _conn_attr = getattr(storage, "_conn", "absent")
    if _conn_attr is None:
        _CACHE_WIRE_LOOP.run_until_complete(storage.__aenter__())

    async_conn = _CACHE_WIRE_LOOP.run_until_complete(AsyncConnection.new(storage))

    # Spin up a background thread that runs the persistent loop forever so
    # the sync facade can dispatch subsequent coroutines via
    # ``run_coroutine_threadsafe`` even after ``run_until_complete`` has
    # drained the initial tasks. Without this thread the loop idles once
    # its first batch finishes, ``run_coroutine_threadsafe`` queues work
    # that never runs, and ``future.result()`` deadlocks.
    _ensure_loop_background_thread(_CACHE_WIRE_LOOP)

    return _SyncConnectionFacade(async_conn, _CACHE_WIRE_LOOP)


def _ensure_loop_background_thread(loop: asyncio.AbstractEventLoop) -> None:
    """Run ``loop.run_forever()`` in a daemon thread so the loop stays alive.

    Idempotent: at most one daemon thread per loop, identified by storing
    the thread on the loop itself. ``asyncio`` event loop objects allow
    arbitrary attribute assignment, so this is safe.
    """
    if getattr(loop, "_dhara_wire_thread", None) is not None:
        return
    import threading

    def _runner() -> None:
        asyncio.set_event_loop(loop)
        with suppress(Exception):
            # Daemon thread should never crash the process; log silently.
            loop.run_forever()

    thread = threading.Thread(target=_runner, name="dhara-cache-wire-loop", daemon=True)
    thread.start()
    loop._dhara_wire_thread = thread  # ty: ignore[unresolved-attribute]


class DharaMCPServer:
    """Dhara MCP Server with FastMCP framework.

    Replaces custom MCP implementation with FastMCP for ecosystem alignment.
    The legacy auth module remains available for compatibility and library use,
    while the canonical runtime can enable bearer-token auth through Dhara's
    token store configuration.

    ★ Insight: FastMCP Migration ─────────────────────────────────────
    1. FastMCP replaces custom tool registration with @server.tool() decorators
    2. Automatic JSON schema generation from function signatures
    3. Built-in error handling and response serialization
    4. Consistent with Mahavishnu, Session-Buddy, Crackerjack patterns
    ────────────────────────────────────────────────────────────────────
    """

    def __init__(
        self,
        config: DharaSettings | None = None,
        *,
        storage_conn: duckdb.DuckDBPyConnection | None = None,
        audit_outbox: MemoryOutbox | None = None,
    ) -> None:
        """Initialize Dhara MCP server.

        Args:
            config: Validated Dhara settings. When ``None``, only the D-AUDIT
                substrate is wired (lightweight/test path); the FastMCP server,
                storage backends, adapter registry, and health routes are not
                constructed. Callers using this mode invoke ``_register_tools``
                explicitly to wire the audit subscriber + query tool.
            storage_conn: Optional DuckDB connection forwarded to the
                :class:`AuditLogQueryTool` so audit reads can hit an existing
                connection without rebuilding one.
            audit_outbox: In-memory bounded FIFO used by the audit subscriber.
                Defaults to a fresh :class:`MemoryOutbox` when not supplied.

        Note: The brief for D-AUDIT Task 5 references ``super().__init__(**kwargs)``,
        but ``DharaMCPServer`` is the concrete class with no parent. The kwargs
        signature here preserves that intent (``**kwargs``-like absorption via
        keyword-only parameters) while staying compatible with the existing
        ``config: DharaSettings`` construction path used by production callers.
        """
        # D-AUDIT substrate (Layer 0): always wired, no infrastructure deps.
        self._storage_conn = storage_conn
        self._audit_outbox = audit_outbox or MemoryOutbox()
        self._registered_tools: dict[str, object] = {}
        self._audit_subscriber: AuditLogSubscriber | None = None
        self._audit_flush_task: asyncio.Task[None] | None = None

        if config is None:
            # Lightweight construction mode (audit-only/test path). The
            # FastMCP server, storage, and adapters are not constructed;
            # the caller drives ``_register_tools`` explicitly.
            self.config = None  # type: ignore[assignment]
            self._start_time = time.time()
            self.auth_verifier = None
            self.server = None  # type: ignore[assignment]
            return

        self.config = config
        self._start_time = time.time()
        self.auth_verifier = build_token_verifier(
            enabled=config.authentication.enabled,
            tokens_file=config.authentication.token.tokens_file,
            require_auth=config.authentication.token.require_auth,
            default_role=config.authentication.token.default_role,
            required_scopes=config.authentication.required_scopes,
        )

        # Initialize FastMCP server
        self.server = FastMCP(
            name=config.server_name,
            instructions=(
                "Dhara provides persistent object storage and Oneiric adapter "
                "distribution with ACID transactions and version management."
            ),
            auth=self.auth_verifier,
        )

        # HTTP health endpoint for Claude Code compatibility
        @self.server.custom_route("/health", methods=["GET"])
        async def health_check(request: Any) -> Any:
            """HTTP health check endpoint for Claude Code `mcp list` compatibility."""
            from starlette.responses import JSONResponse

            try:
                runtime = self._runtime_status()
                return JSONResponse(
                    runtime, status_code=200 if runtime["ready"] else 503
                )
            except Exception as exc:  # noqa: BLE001  # runtime-status probe returns typed error data
                # Surface the error so health checks don't silently fail
                return JSONResponse(
                    {"status": "error", "service": "dhara", "error": str(exc)},
                    status_code=503,
                )

        @self.server.custom_route("/healthz", methods=["GET"])
        async def healthz_check(request: Any) -> Any:
            """Kubernetes-style health check endpoint."""
            from starlette.responses import JSONResponse

            return JSONResponse({"status": "ok"})

        @self.server.custom_route("/ready", methods=["GET"])
        async def ready_check(request: Any) -> Any:
            """HTTP readiness endpoint on the main service port."""
            from starlette.responses import JSONResponse

            try:
                runtime = self._runtime_status()
                return JSONResponse(
                    runtime, status_code=200 if runtime["ready"] else 503
                )
            except Exception as exc:  # noqa: BLE001  # runtime-status probe returns typed error data
                return JSONResponse(
                    {"status": "error", "service": "dhara", "error": str(exc)},
                    status_code=503,
                )

        @self.server.custom_route("/readyz", methods=["GET"])
        async def readyz_check(request: Any) -> Any:
            """Kubernetes-style readiness endpoint."""
            from starlette.responses import JSONResponse

            try:
                runtime = self._runtime_status()
                return JSONResponse(
                    runtime, status_code=200 if runtime["ready"] else 503
                )
            except Exception as exc:  # noqa: BLE001  # runtime-status probe returns typed error data
                return JSONResponse(
                    {"status": "error", "service": "dhara", "error": str(exc)},
                    status_code=503,
                )

        @self.server.custom_route("/metrics", methods=["GET"])
        async def metrics_check(request: Any) -> Any:
            """Prometheus metrics endpoint on the main Dhara service port."""
            from starlette.responses import Response

            from dhara.monitoring.metrics import get_server_metrics

            metrics = get_server_metrics()
            if not isinstance(metrics, str):
                import json

                metrics = json.dumps(metrics)
                media_type = "application/json"
            else:
                media_type = "text/plain; version=0.0.4; charset=utf-8"

            return Response(content=metrics, media_type=media_type)

        # NOTE: /tools/call route is registered AFTER storage is initialized
        # so self.kv_store, self.ecosystem_state are available.
        # See tools_call_route below after _register_tools() completes.

        # Initialize storage and connection
        # Expand ~ to home directory
        storage_path = config.storage.path.expanduser()
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        # ── Storage backend selection ─────────────────────────────────────────
        storage_backend = getattr(config, "storage_backend", "sqlite")

        if storage_backend == "postgres":
            from dhara.storage.postgres import PostgresStorageAdapter

            self.storage = PostgresStorageAdapter(
                url=getattr(config, "storage_pg_url", None)
                or "postgresql://localhost/dhara",
            )
        else:
            # Default: AsyncFileStorage (the legacy FileStorage is deleted
            # after sub-task 1i). The mock in test_mcp_server_core.py patches
            # ``AsyncFileStorage`` at this name. AsyncSqliteStorage no longer
            # accepts a ``readonly=`` kwarg post-async-migration; if
            # ``config.storage.read_only`` is set, callers that need
            # read-only enforcement must wrap the storage themselves.
            # ``config.storage.path`` is a pathlib.Path; coerce to str because
            # the shim's ``_path_to_url`` only handles strings.
            self.storage = AsyncFileStorage(str(storage_path))

        # Async stores (initialized lazily on first async tool call).
        # Declared before the cache_backend block so that the wiring step
        # (which uses `self._async_adapter_registry`) can run during the
        # cache block without an AttributeError.
        self._async_kv_store: AsyncKVTimeSeriesStore | None = None
        self._async_ecosystem_state: AsyncEcosystemStateStore | None = None
        self._async_adapter_registry: AsyncAdapterRegistry | None = None

        # ── Cache backend selection ─────────────────────────────────────────
        self.cache = None

        self.cache = _run_cache_wire(config, self)

        # Build the AsyncConnection during sync __init__ via the persistent
        # loop, and wrap it in a sync facade so AdapterRegistry and the
        # substrate routes can keep calling connection.get_root() etc.
        # without rewriting them.
        self.connection = _run_async_connection_wire(self.storage)

        # Initialize adapter registry
        self.adapter_registry = AdapterRegistry(
            cast("Connection", self.connection)
        )  # _SyncConnectionFacade wraps an async Connection; satisfying the Connection protocol is the async-migration follow-up

        # Register tools via the W0 ``_apply_tool_profile`` dispatch.
        # _register_tools() also runs the always-on ``register_health_tools``
        # group as part of ``DHARA_MANDATORY_GROUPS`` — no separate call here.
        self._register_tools()

        logger.info(
            f"Dhara MCP Server initialized: {config.server_name} "
            f"(storage={config.storage.path}, adapters={self.adapter_registry.count()})"
        )

    def _register_tools(self) -> None:
        """Register MCP tools via the W0 ``_apply_tool_profile`` dispatch.

        Tool groups are routed through :mod:`dhara.mcp.tools.profiles`'s
        ``PROFILE_REGISTRATIONS`` + ``REGISTRATION_MAP``. Per-group wrappers
        in :mod:`dhara.mcp.tools.group_registers` carry the inline tool
        definitions; the W0 helper filters by profile + runs mandatory
        groups (health) at every profile tier. The legacy inline
        ``@_tool(GROUP)`` conditional-decorator pattern was removed; the
        W0 path is the single source of truth for which tools get
        registered at each profile.

        Profile tiers:
            MINIMAL:  KV/time-series storage + always-on health/discover
            STANDARD: Adds adapter registry + ecosystem state
            FULL:     Adds sql_proxy
        """

        # D-AUDIT substrate (Layer 0): always wired, no infrastructure deps.
        # Registers the audit subscriber singleton and exposes the read-back
        # query tool under ``audit_record_query`` so callers (incl. lightweight
        # construction) can introspect or invoke the audit pipeline directly.
        subscriber = AuditLogSubscriber(outbox=self._audit_outbox)
        subscriber.register()
        self._audit_subscriber = subscriber

        # The read-back query tool needs a storage handle. Skip it in the
        # fully lightweight path (no storage_conn provided); callers that want
        # query back must pass a DuckDB connection in ``__init__``.
        if self._storage_conn is not None:
            from dhara.audit.query_tool import AuditLogQueryTool

            query_tool = AuditLogQueryTool(conn=self._storage_conn)
            self._registered_tools["audit_record_query"] = query_tool.query

            # Schedule the periodic flush loop so producer ``on_put`` calls
            # actually reach the ``audit_log`` table. G6 contract: any error
            # inside the loop is absorbed by ``periodic_flush_loop`` and
            # logged; the task handle is retained on ``self`` so a future
            # shutdown hook can cancel it cleanly. ``asyncio.create_task``
            # requires a running loop, so we guard against the sync
            # ``__init__`` path (e.g. ``test_mcp_wiring.py``); production
            # callers reach this code from inside FastMCP's running loop.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                self._audit_flush_task = asyncio.create_task(
                    periodic_flush_loop(
                        OutboxFlusher(
                            outbox=self._audit_outbox,
                            conn=self._storage_conn,
                        )
                    )
                )

        if self.server is None:
            # Lightweight/test construction mode: no FastMCP server to decorate.
            return

        # W0 dispatch: profile-gated tool registration + discover_tools +
        # mandatory_groups (health). asyncio.run() drives the async helper
        # from this sync ``__init__`` call site; the helper raises if called
        # from within an active loop, so we explicitly use the async entry.
        asyncio.run(self._apply_w0_profile())

        logger.info("Dhara MCP tools registration complete (via W0 dispatch)")

        # Register REST-style /tools/call endpoint for Akosha client compatibility.
        # Akosha's DharaServiceRegistryClient calls /tools/call (not /mcp) with
        # {"name": "...", "arguments": {...}}. We call underlying store methods directly.
        self._register_tools_call_route()

        # Register substrate CRUD HTTP routes (Workstream C).
        # Persistence uses the AsyncFileStorage-backed Connection.root mapping;
        # Workstream D will swap to SQL-backed tables.
        register_substrate_routes(self.server, self.connection)

        # D-LOCK: distributed lock + audit ledger primitive
        from dhara.lock.routes import register_lock_routes

        sql_backend = getattr(self, "sql_backend", None)
        if sql_backend is not None:
            assert self.server is not None, "FastMCP server required for lock routes"
            register_lock_routes(self.server, sql_backend)

    async def _apply_w0_profile(self) -> None:
        """Call :func:`mcp_common.tools.dispatch._apply_tool_profile` for this server.

        Per-instance ``registration_map`` captures ``self`` so the per-group
        wrappers in :mod:`dhara.mcp.tools.group_registers` can access
        ``self._async_kv_store``, ``self.config``, etc. The W0 helper
        itself is async — ``_register_tools`` drives it via ``asyncio.run``
        from the sync ``__init__`` call site.
        """
        from mcp_common.tools.dispatch import _apply_tool_profile

        from dhara.mcp.tools.group_registers import (
            register_adapter_registry_group,
            register_ecosystem_state_group,
            register_health_tools_group,
            register_kv_timeseries_group,
            register_sql_proxy_group,
        )
        from dhara.mcp.profiles import (
            DHARA_MANDATORY_GROUPS,
            PROFILE_REGISTRATIONS,
        )

        registration_map = {
            "kv_time_series": lambda app: register_kv_timeseries_group(app, self),
            "adapter_registry": lambda app: register_adapter_registry_group(app, self),
            "ecosystem_state": lambda app: register_ecosystem_state_group(app, self),
            "sql_proxy": lambda app: register_sql_proxy_group(app, self),
            "register_health_tools": lambda app: register_health_tools_group(
                app, self
            ),
        }

        await _apply_tool_profile(
            server=self.server,
            profile_env_var="DHARA_TOOL_PROFILE",
            registrations=PROFILE_REGISTRATIONS,
            registration_map=registration_map,
            mandatory_groups=DHARA_MANDATORY_GROUPS,
        )

    def _register_tools_call_route(self) -> None:
        """Register /tools/call REST-style endpoint for Akosha client compatibility."""
        assert self.server is not None, "FastMCP server required for tools/call route"

        import asyncio
        import json

        @self.server.custom_route("/tools/call", methods=["POST"])
        async def tools_call(request: Any) -> Any:
            """REST-style tool call endpoint for Akosha client compatibility.

            Akosha's DharaServiceRegistryClient calls /tools/call with a JSON body
            containing {"name": "...", "arguments": {...}}.
            This route translates REST-style calls into store method invocations.
            """
            from starlette.responses import JSONResponse

            try:
                body = await request.json()
            except Exception:  # noqa: BLE001  # REST body parser → HTTP 400
                return JSONResponse({"error": "Invalid JSON"}, status_code=400)

            tool_name = body.get("name")
            arguments = body.get("arguments", {})

            if not tool_name:
                return JSONResponse({"error": "Missing tool name"}, status_code=400)

            # Map tool names to async store methods
            # These are bound at request time when stores are initialized
            sync_tool_map: dict[str, Any] = {
                "get": self._async_kv_store.get_async if self._async_kv_store else None,
                "put": self._async_kv_store.put_async if self._async_kv_store else None,
                "list_prefix": self._async_kv_store.list_prefix_async
                if self._async_kv_store
                else None,
                "list_services": self._async_ecosystem_state.list_services_async
                if self._async_ecosystem_state
                else None,
                "get_service": self._async_ecosystem_state.get_service_async
                if self._async_ecosystem_state
                else None,
                "record_event": self._async_ecosystem_state.record_event_async
                if self._async_ecosystem_state
                else None,
                "list_events": self._async_ecosystem_state.list_events_async
                if self._async_ecosystem_state
                else None,
            }

            if tool_name in sync_tool_map and sync_tool_map[tool_name] is None:
                return JSONResponse(
                    {"error": f"Store not initialized: {tool_name}"}, status_code=500
                )

            if tool_name not in sync_tool_map:
                return JSONResponse(
                    {"error": f"Unknown tool: {tool_name}"}, status_code=404
                )

            try:
                # Run sync store methods in thread pool to avoid blocking event loop
                result = await asyncio.to_thread(sync_tool_map[tool_name], **arguments)
                # Return in Akosha client format: {"content": [{"type": "text", "text": "..."}]}
                text = json.dumps(result)
                return JSONResponse(
                    {
                        "content": [{"type": "text", "text": text}],
                        "isError": False,
                    }
                )
            except Exception as exc:  # noqa: BLE001  # REST body parser → HTTP 500
                return JSONResponse(
                    {
                        "content": [
                            {"type": "text", "text": json.dumps({"error": str(exc)})}
                        ],
                        "isError": True,
                    },
                    status_code=500,
                )

    def _register_health_tools(self) -> None:
        """Register health check tools using mcp-common.

        Adds standardized health check endpoints for:
        - Liveness probes (is process running)
        - Readiness probes (can accept work)
        - Dependency health checking
        """
        # Default dependencies for Dhara
        dependencies = {
            "session_buddy": DependencyConfig(
                host="localhost",
                port=8678,
                required=False,  # Optional - for session context
                timeout_seconds=10,
            ),
            "mahavishnu": DependencyConfig(
                host="localhost",
                port=8680,
                required=False,  # Optional - for orchestration
                timeout_seconds=10,
            ),
            "akosha": DependencyConfig(
                host="localhost",
                port=8682,
                required=False,  # Optional - for cross-system intelligence
                timeout_seconds=10,
            ),
        }

        register_health_tools(
            mcp=self.server,
            service_name="dhara",
            version=_PACKAGE_VERSION,
            start_time=self._start_time,
            dependencies=dependencies,
        )

        logger.info("Registered health check tools")

    def _probe_storage(self) -> dict[str, Any]:
        """Probe storage accessibility for readiness and health reporting."""
        assert self.config is not None, "config required for storage probe"
        storage_path = self.config.storage.path.expanduser()
        try:
            root = self.connection.get_root()
            return {
                "path": str(storage_path),
                "exists": storage_path.exists(),
                "accessible": True,
                "read_only": self.config.storage.read_only,
                "root_keys": len(list(root.keys())),
            }
        except Exception as exc:  # noqa: BLE001  # health-endpoint probe
            return {
                "path": str(storage_path),
                "exists": storage_path.exists(),
                "accessible": False,
                "read_only": self.config.storage.read_only,
                "error": str(exc),
            }

    def _probe_backups(self) -> dict[str, Any]:
        """Probe backup catalog visibility for recovery awareness."""
        assert self.config is not None, "config required for backup probe"
        backup_dir = self.config.backups.directory.expanduser()
        if not self.config.backups.enabled:
            return {"configured": False}

        catalog_path = backup_dir / "backup_catalog.dhara"
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            latest_backup_id = None
            latest_backup_at = None
            total_backups = 0

            if catalog_path.exists():
                catalog_data = self._read_backup_catalog_async(catalog_path)
                total_backups = catalog_data["total_backups"]
                latest_backup_id = catalog_data["latest_backup_id"]
                latest_backup_at = catalog_data["latest_backup_at"]

            return {
                "configured": True,
                "directory": str(backup_dir),
                "catalog_accessible": True,
                "catalog_exists": catalog_path.exists(),
                "latest_backup_id": latest_backup_id,
                "latest_backup_at": latest_backup_at,
                "total_backups": total_backups,
            }
        except Exception as exc:  # noqa: BLE001  # health-endpoint probe
            return {
                "configured": True,
                "directory": str(backup_dir),
                "catalog_accessible": False,
                "error": str(exc),
            }

    def _read_backup_catalog_async(self, catalog_path: Any) -> dict[str, Any]:
        """Read the backup catalog using async storage.

        The catalog is now backed by ``AsyncFileStorage`` (sqlite under the
        hood). The legacy ``FileStorage`` (Duru SHELF) cannot open the new
        catalog format, so we must use the async API.

        This method is a sync wrapper that runs the async I/O via
        ``asyncio.run``. It is invoked from the sync ``_probe_backups``,
        which is itself called from sync ``_runtime_status`` (test code
        path). The FastMCP ``custom_route`` handler awaits ``_runtime_status``
        results, so the inner event loop is paused while this runs.
        """
        import asyncio

        from dhara.core.connection import AsyncConnection

        async def _read() -> dict[str, Any]:
            storage = AsyncFileStorage(str(catalog_path))
            await storage.init()
            try:
                connection = await AsyncConnection.new(storage)
                root = await connection.get_root()
                backups = root.get("backups", {})
                # Unwrap PersistentDict's ``__state__`` envelope when
                # the on-disk format is the legacy pickle-style state
                # representation rather than a hydrated mapping.
                if (
                    isinstance(backups, dict)
                    and "__state__" in backups
                    and isinstance(backups["__state__"], dict)
                    and "data" in backups["__state__"]
                ):
                    backups = backups["__state__"]["data"]
                total = len(list(backups.keys()))
                latest_payload: dict[str, Any] | None = None
                latest_timestamp: str | None = None
                for payload in backups.values():
                    data = dict(payload)
                    # Each stored entry is itself a PersistentDict that
                    # round-trips through the ``__state__`` envelope.
                    if (
                        isinstance(data, dict)
                        and "__state__" in data
                        and isinstance(data["__state__"], dict)
                        and "data" in data["__state__"]
                    ):
                        data = data["__state__"]["data"]
                    timestamp = data.get("timestamp")
                    if isinstance(timestamp, str) and (
                        latest_timestamp is None or timestamp > latest_timestamp
                    ):
                        latest_timestamp = timestamp
                        latest_payload = data
                return {
                    "total_backups": total,
                    "latest_backup_id": latest_payload.get("backup_id")
                    if latest_payload is not None
                    else None,
                    "latest_backup_at": latest_payload.get("timestamp")
                    if latest_payload is not None
                    else None,
                }
            finally:
                await storage.close()

        return asyncio.run(_read())

    def _runtime_status(self) -> dict[str, Any]:
        """Return canonical runtime health and readiness data."""
        storage = self._probe_storage()
        backups = self._probe_backups()
        ready = bool(storage.get("accessible"))
        return {
            "status": "ok" if ready else "error",
            "service": "dhara",
            "version": _PACKAGE_VERSION,
            "ready": ready,
            "uptime_seconds": time.time() - self._start_time,
            "adapters": self.adapter_registry.count(),
            "authentication": {
                "enabled": self.auth_verifier is not None,
                "mode": "token" if self.auth_verifier is not None else "none",
            },
            "storage": storage,
            "backups": backups,
        }

    def run(self, host: str = "127.0.0.1", port: int = 8683) -> None:
        """Run the MCP server (synchronous - manages its own event loop).

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        assert self.server is not None, "FastMCP server required to run"
        import asyncio

        logger.info(f"Starting Dhara MCP server on {host}:{port}")

        # Initialize async stores before the event loop starts
        asyncio.run(self._init_async_stores())

        # FastMCP 3.x uses run_http_async() for HTTP transport
        asyncio.run(self.server.run_http_async(host=host, port=port))

    async def _init_async_stores(self) -> None:
        """Initialize async stores from AsyncSqliteStorage for async tool dispatch."""
        assert self.config is not None, "config required for async stores"

        from dhara.core.connection import AsyncConnection
        from dhara.storage.sqlite import AsyncSqliteStorage

        # Create and initialize AsyncSqliteStorage (async I/O, WAL mode)
        async_storage = AsyncSqliteStorage()
        await async_storage.init()

        # Create async connection with the initialized AsyncStorage
        async_conn = await AsyncConnection.new(async_storage)
        self._async_kv_store = AsyncKVTimeSeriesStore(
            async_conn,
            retention=TimeSeriesRetention(
                retention_days=self.config.time_series.retention_days
            ),
        )
        self._async_ecosystem_state = AsyncEcosystemStateStore(
            async_conn,
            event_retention=EventRetention(
                retention_days=self.config.ecosystem_state.event_retention_days
            ),
        )
        self._async_adapter_registry = AsyncAdapterRegistry(async_conn)

    def close(self) -> None:
        """Close the server and cleanup resources."""
        if getattr(self, "storage", None) is not None:
            asyncio.run(
                self.storage.close()
            )  # close() runs in the persistent event-loop thread; full async close path is the migration follow-up
        logger.info("Dhara MCP Server closed")


def register_audit_routes(server: DharaMCPServer) -> None:
    """Public registration helper for the D-AUDIT substrate.

    Mirrors the ``register_lock_routes`` pattern from D-LOCK. The audit wire-up
    (subscriber + query tool) is normally performed as part of
    ``DharaMCPServer._register_tools``; this module-level helper exposes that
    capability to callers that construct a ``DharaMCPServer`` in lightweight
    mode (without ``config``) and only need the audit surface.
    """
    server._register_tools()  # mirrors D-LOCK's register_lock_routes pattern

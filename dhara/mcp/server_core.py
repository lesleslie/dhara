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

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from fastmcp.server.auth.authorization import require_scopes
from mcp_common.fastmcp import FastMCP
from mcp_common.health import (
    DependencyConfig,
    register_health_tools,
)
from oneiric.core.logging import get_logger

from dhara.core.config import DharaSettings
from dhara.core.connection import Connection
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

    def __init__(self, config: DharaSettings) -> None:
        """Initialize Dhara MCP server.

        Args:
            config: Validated Dhara settings
        """
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
            except Exception as exc:
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
            except Exception as exc:
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
            except Exception as exc:
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
        storage_backend = getattr(config, "storage_backend", "file")

        if storage_backend == "postgres":
            from dhara.storage.postgres import PostgresStorageAdapter

            self.storage = PostgresStorageAdapter(
                url=getattr(config, "storage_pg_url", None)
                or "postgresql://localhost/dhara",
            )
        else:
            # Default: AsyncFileStorage (the legacy FileStorage is deleted
            # after sub-task 1i). The mock in test_mcp_server_core.py patches
            # ``AsyncFileStorage`` at this name.
            self.storage = AsyncFileStorage(
                storage_path,
                readonly=config.storage.read_only,
            )

        # ── Cache backend selection ─────────────────────────────────────────
        cache_backend = getattr(config, "cache_backend", "memory")
        self.cache = None

        if cache_backend == "redis":
            from dhara.storage.redis_cache import (
                RedisCacheAdapter,
                RedisCacheSettings,
            )

            redis_settings = RedisCacheSettings(
                redis_url=config.cache_redis_url or "redis://localhost:6379",
                redis_token=config.cache_redis_token or None,
                ttl=config.cache_ttl or 3600,
                stampede_jitter_ms=getattr(config, "cache_stampede_jitter_ms", 0),
            )
            self.cache = RedisCacheAdapter(redis_settings)

        self.connection = Connection(self.storage)

        # Initialize adapter registry
        self.adapter_registry = AdapterRegistry(self.connection)

        # Async stores (initialized lazily on first async tool call)
        self._async_kv_store: AsyncKVTimeSeriesStore | None = None
        self._async_ecosystem_state: AsyncEcosystemStateStore | None = None
        self._async_adapter_registry: AsyncAdapterRegistry | None = None

        # Register tools using FastMCP decorators
        self._register_tools()

        # Register health check tools from mcp-common
        self._register_health_tools()

        logger.info(
            f"Dhara MCP Server initialized: {config.server_name} "
            f"(storage={config.storage.path}, adapters={self.adapter_registry.count()})"
        )

    def _register_tools(self) -> None:  # noqa: C901
        """Register MCP tools based on active profile.

        Tools are grouped and gated by the DHARA_TOOL_PROFILE env var.
        Uses a conditional decorator _tool() that only registers tools
        belonging to groups in the active profile.

        Profile tiers:
            MINIMAL:  KV/time-series storage only
            STANDARD: Adds adapter registry and ecosystem state
            FULL:     All tools (same as STANDARD for Dhara)
        """

        def auth(*scopes: str) -> Any:
            """Return a FastMCP authorization callable."""
            if not self.config.authentication.enabled:
                return require_scopes()  # Empty scope check when disabled
            return require_scopes(*scopes)

        from dhara.mcp.profiles import (
            TOOL_GROUP_ADAPTER_REGISTRY,
            TOOL_GROUP_DESCRIPTIONS,
            TOOL_GROUP_ECOSYSTEM_STATE,
            TOOL_GROUP_KV_TIME_SERIES,
            TOOL_GROUP_SQL_PROXY,
            TOOL_GROUP_TOOLS,
            TOOL_GROUPS_BY_PROFILE,
            get_active_profile,
        )
        from dhara.mcp.tools.sql_proxy import (
            dhara_sql_execute as _dhara_sql_execute_impl,
        )
        from dhara.mcp.tools.sql_proxy import (
            dhara_sql_query as _dhara_sql_query_impl,
        )

        profile = get_active_profile()
        active_groups = set(TOOL_GROUPS_BY_PROFILE[profile])

        logger.info(
            "Dhara tool profile=%s groups=%s", profile.value, sorted(active_groups)
        )

        def _tool(group: str, **kwargs: Any) -> Any:
            """Conditional registration — only registers if group is in active profile."""
            if group not in active_groups:
                return lambda fn: fn  # No-op: function defined but not registered
            return self.server.tool(**kwargs)

        # --- Adapter Registry tools (STANDARD+) ---
        @_tool(TOOL_GROUP_ADAPTER_REGISTRY, auth=auth("write"))
        async def store_adapter(
            domain: str,
            key: str,
            provider: str,
            version: str,
            factory_path: str,
            config: dict[str, Any] | None = None,
            dependencies: list[str] | None = None,
            capabilities: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Store a Oneiric adapter in the registry.

            Args:
                domain: Adapter domain (adapter, service, task)
                key: Adapter key (cache, storage, redis)
                provider: Provider name (redis, s3, memory)
                version: Semantic version (e.g., "1.0.0")
                factory_path: Python import path for adapter factory
                config: Adapter configuration dictionary
                dependencies: List of required adapter keys
                capabilities: List of capability strings
                metadata: Additional metadata (category, description, etc.)

            Returns:
                Result dict with adapter_id and version
            """
            assert self._async_adapter_registry is not None, (
                "Async store not initialized"
            )
            return await store_adapter_async_impl(  # type: ignore[no-any-return]
                registry=self._async_adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
                version=version,
                factory_path=factory_path,
                config=config or {},
                dependencies=dependencies or [],
                capabilities=capabilities or [],
                metadata=metadata or {},
            )

        @_tool(TOOL_GROUP_ADAPTER_REGISTRY, auth=auth("read"))
        async def get_contract_info() -> dict[str, Any]:
            """Return the supported Dhara MCP contract summary."""
            auth_mode = "token" if self.auth_verifier is not None else "none"
            return {
                "ok": True,
                "server": {
                    "name": self.config.server_name,
                    "transport": "FastMCP HTTP",
                    "http_endpoints": [
                        "/health",
                        "/healthz",
                        "/ready",
                        "/readyz",
                        "/metrics",
                    ],
                },
                "tool_groups": {
                    "adapter_registry": [
                        "store_adapter",
                        "get_adapter",
                        "list_adapters",
                        "list_adapter_versions",
                        "validate_adapter",
                        "get_adapter_health",
                    ],
                    "kv_time_series": [
                        "put",
                        "get",
                        "record_time_series",
                        "query_time_series",
                        "aggregate_patterns",
                    ],
                    "ecosystem_state": [
                        "upsert_service",
                        "get_service",
                        "list_services",
                        "record_event",
                        "list_events",
                    ],
                    "health": ["mcp-common health tools"],
                },
                "schema_versions": {
                    "adapter_registry": 1,
                    "ecosystem_service": 1,
                    "ecosystem_event": 1,
                },
                "authentication": {
                    "runtime_mode": auth_mode,
                    "canonical_fastmcp_wired": self.auth_verifier is not None,
                    "available_library_surfaces": [
                        "TokenAuth",
                        "HMACAuth",
                        "EnvironmentAuth",
                        "AuthMiddleware",
                    ],
                    "required_scopes": self.config.authentication.required_scopes.copy(),
                    "token_file": (
                        str(self.config.authentication.token.tokens_file.expanduser())
                        if self.config.authentication.token.tokens_file is not None
                        else None
                    ),
                    "notes": (
                        "Canonical FastMCP auth uses bearer tokens backed by the "
                        "Dhara token store when enabled."
                    )
                    if self.auth_verifier is not None
                    else (
                        "The canonical FastMCP server does not currently enforce "
                        "auth in the runtime path."
                    ),
                },
            }

        # --- Ecosystem State tools (STANDARD+) ---
        @_tool(TOOL_GROUP_ECOSYSTEM_STATE, auth=auth("write"))
        async def upsert_service(
            service_id: str,
            service_type: str,
            capabilities: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
            status: str = "unknown",
            lease_expires_at: str | None = None,
            heartbeat_at: str | None = None,
        ) -> dict[str, Any]:
            """Create or update a durable ecosystem service record."""
            assert self._async_ecosystem_state is not None, (
                "Async store not initialized"
            )
            return await self._async_ecosystem_state.upsert_service_async(  # type: ignore[no-any-return]
                service_id=service_id,
                service_type=service_type,
                capabilities=capabilities,
                metadata=metadata,
                status=status,
                lease_expires_at=lease_expires_at,
                heartbeat_at=heartbeat_at,
            )

        @_tool(TOOL_GROUP_ECOSYSTEM_STATE, auth=auth("read"))
        async def get_service(service_id: str) -> dict[str, Any]:
            """Fetch a durable ecosystem service record."""
            assert self._async_ecosystem_state is not None, (
                "Async store not initialized"
            )
            service = await self._async_ecosystem_state.get_service_async(service_id)
            return {"ok": True, "service": service}

        @_tool(TOOL_GROUP_ECOSYSTEM_STATE, auth=auth("list"))
        async def list_services(
            service_type: str | None = None,
            capability: str | None = None,
            status: str | None = None,
        ) -> dict[str, Any]:
            """List durable ecosystem service records."""
            assert self._async_ecosystem_state is not None, (
                "Async store not initialized"
            )
            services = await self._async_ecosystem_state.list_services_async(
                service_type=service_type,
                capability=capability,
                status=status,
            )
            return {"ok": True, "count": len(services), "services": services}

        @_tool(TOOL_GROUP_ECOSYSTEM_STATE, auth=auth("write"))
        async def record_event(
            event_type: str,
            source_service: str,
            payload: dict[str, Any] | None = None,
            related_service: str | None = None,
            timestamp: str | None = None,
        ) -> dict[str, Any]:
            """Append a durable ecosystem event."""
            assert self._async_ecosystem_state is not None, (
                "Async store not initialized"
            )
            return await self._async_ecosystem_state.record_event_async(  # type: ignore[no-any-return]
                event_type=event_type,
                source_service=source_service,
                payload=payload,
                related_service=related_service,
                timestamp=timestamp,
            )

        @_tool(TOOL_GROUP_ECOSYSTEM_STATE, auth=auth("list"))
        async def list_events(
            event_type: str | None = None,
            source_service: str | None = None,
            related_service: str | None = None,
            limit: int | None = 100,
        ) -> dict[str, Any]:
            """List durable ecosystem events."""
            assert self._async_ecosystem_state is not None, (
                "Async store not initialized"
            )
            events = await self._async_ecosystem_state.list_events_async(
                event_type=event_type,
                source_service=source_service,
                related_service=related_service,
                limit=limit,
            )
            return {"ok": True, "count": len(events), "events": events}

        # --- KV/Time Series tools (MINIMAL) ---
        @_tool(TOOL_GROUP_KV_TIME_SERIES, auth=auth("write"))
        async def put(
            key: str,
            value: dict[str, Any] | str | int | float | bool | list[Any] | None,
            ttl: int | None = None,
        ) -> dict[str, Any]:
            """Store a key/value record with optional TTL (seconds)."""
            assert self._async_kv_store is not None, "Async store not initialized"
            return await self._async_kv_store.put_async(key=key, value=value, ttl=ttl)  # type: ignore[no-any-return]

        @_tool(TOOL_GROUP_KV_TIME_SERIES, auth=auth("read"))
        async def get(
            key: str,
        ) -> dict[str, Any]:
            """Get a key/value record."""
            assert self._async_kv_store is not None, "Async store not initialized"
            return await self._async_kv_store.get_async(key=key)  # type: ignore[no-any-return]

        @_tool(TOOL_GROUP_KV_TIME_SERIES, auth=auth("read"))
        async def list_prefix(
            prefix: str,
        ) -> dict[str, Any]:
            """List all key/value records under a key prefix.

            Used by Akosha FitnessAnalyzer to discover component endpoints
            registered under 'component_endpoint/' prefix.
            """
            assert self._async_kv_store is not None, "Async store not initialized"
            results = await self._async_kv_store.list_prefix_async(prefix)
            return {"ok": True, "count": len(results), "items": results}

        @_tool(TOOL_GROUP_KV_TIME_SERIES, auth=auth("write"))
        async def record_time_series(
            metric_type: str,
            entity_id: str,
            record: dict[str, Any],
            timestamp: str | None = None,
        ) -> dict[str, Any]:
            """Append a time-series record."""
            assert self._async_kv_store is not None, "Async store not initialized"
            return await self._async_kv_store.record_time_series_async(  # type: ignore[no-any-return]
                metric_type=metric_type,
                entity_id=entity_id,
                record=record,
                timestamp=timestamp,
            )

        @_tool(TOOL_GROUP_KV_TIME_SERIES, auth=auth("read"))
        async def query_time_series(
            metric_type: str,
            entity_id: str,
            start_date: str | None = None,
            limit: int | None = None,
        ) -> list[dict[str, Any]]:
            """Query time-series records."""
            assert self._async_kv_store is not None, "Async store not initialized"
            return await self._async_kv_store.query_time_series_async(  # type: ignore[no-any-return]
                metric_type=metric_type,
                entity_id=entity_id,
                start_date=start_date,
                limit=limit,
            )

        @_tool(TOOL_GROUP_KV_TIME_SERIES, auth=auth("read"))
        async def aggregate_patterns(
            start_date: str,
            min_occurrences: int = 2,
        ) -> list[dict[str, Any]]:
            """Aggregate patterns across time-series records."""
            assert self._async_kv_store is not None, "Async store not initialized"
            return await self._async_kv_store.aggregate_patterns_async(  # type: ignore[no-any-return]
                start_date=start_date,
                min_occurrences=min_occurrences,
            )

        # --- Remaining Adapter Registry tools (STANDARD+) ---
        @_tool(TOOL_GROUP_ADAPTER_REGISTRY, auth=auth("read"))
        async def get_adapter(
            domain: str,
            key: str,
            provider: str | None = None,
            version: str | None = None,
        ) -> dict[str, Any]:
            """Retrieve an adapter from the registry.

            Args:
                domain: Adapter domain
                key: Adapter key
                provider: Optional provider (defaults to first match)
                version: Optional version (defaults to latest)

            Returns:
                Adapter dict with full configuration
            """
            assert self._async_adapter_registry is not None, (
                "Async store not initialized"
            )
            return await get_adapter_async_impl(  # type: ignore[no-any-return]
                registry=self._async_adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
                version=version,
            )

        @_tool(TOOL_GROUP_ADAPTER_REGISTRY, auth=auth("list"))
        async def list_adapters(
            domain: str | None = None,
            category: str | None = None,
        ) -> dict[str, Any]:
            """List adapters with optional filtering.

            Args:
                domain: Optional filter by domain (adapter, service, task)
                category: Optional filter by category (storage, cache, database)

            Returns:
                Dict with count, filters, and adapters list
            """
            assert self._async_adapter_registry is not None, (
                "Async store not initialized"
            )
            return await list_adapters_async_impl(  # type: ignore[no-any-return]
                registry=self._async_adapter_registry,
                domain=domain,
                category=category,
            )

        @_tool(TOOL_GROUP_ADAPTER_REGISTRY, auth=auth("list"))
        async def list_adapter_versions(
            domain: str,
            key: str,
            provider: str,
        ) -> dict[str, Any]:
            """List all versions of an adapter.

            Shows version history with timestamps and changelogs,
            useful for understanding adapter evolution and rollback options.

            Args:
                domain: Adapter domain
                key: Adapter key
                provider: Provider name

            Returns:
                Dict with version history (timestamp, version, changelog)
            """
            assert self._async_adapter_registry is not None, (
                "Async store not initialized"
            )
            return await list_adapter_versions_async_impl(  # type: ignore[no-any-return]
                registry=self._async_adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
            )

        @_tool(TOOL_GROUP_ADAPTER_REGISTRY, auth=auth("read"))
        async def validate_adapter(
            domain: str,
            key: str,
            provider: str,
            version: str | None = None,
        ) -> dict[str, Any]:
            """Validate an adapter configuration.

            Checks:
            - Factory path is importable
            - Dependencies are available
            - Configuration schema is valid
            - Capabilities are declared

            Args:
                domain: Adapter domain
                key: Adapter key
                provider: Provider name
                version: Optional version to validate

            Returns:
                Validation result with errors/warnings
            """
            assert self._async_adapter_registry is not None, (
                "Async store not initialized"
            )
            return await validate_adapter_async_impl(  # type: ignore[no-any-return]
                registry=self._async_adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
                version=version,
            )

        @_tool(TOOL_GROUP_ADAPTER_REGISTRY, auth=auth("read"))
        async def get_adapter_health(
            domain: str,
            key: str,
            provider: str,
        ) -> dict[str, Any]:
            """Check health status of an adapter.

            Performs health check by attempting to import the adapter's
            factory class. Returns healthy status if import succeeds.

            Args:
                domain: Adapter domain
                key: Adapter key
                provider: Provider name

            Returns:
                Health check result with status and last check timestamp
            """
            assert self._async_adapter_registry is not None, (
                "Async store not initialized"
            )
            return await get_adapter_health_async_impl(  # type: ignore[no-any-return]
                registry=self._async_adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
            )

        # --- SQL Proxy tools (FULL profile only) ---
        @_tool(TOOL_GROUP_SQL_PROXY, auth=auth("write"))
        async def dhara_sql_execute(
            sql: str,
            params: list[Any] | None = None,
        ) -> dict[str, Any]:
            """Execute a DDL/DML statement through the SQL proxy backend.

            Backend is selected via ``DHARA_SQL_BACKEND`` (default
            ``"duckdb"``); DuckDB is used in dev/test and asyncpg in
            production. Returns ``rows_affected``, ``last_row_id`` and
            ``status``. Refuses DROP DATABASE / DROP SCHEMA.
            """
            return await _dhara_sql_execute_impl(sql=sql, params=params)  # type: ignore[no-any-return]

        @_tool(TOOL_GROUP_SQL_PROXY, auth=auth("read"))
        async def dhara_sql_query(
            sql: str,
            params: list[Any] | None = None,
        ) -> list[dict[str, Any]]:
            """Execute a read-only SELECT/WITH query through the SQL proxy.

            Returns a ``list[dict]`` (one entry per row, keyed by SELECT
            projection). Refuses non-SELECT statements.
            """
            return await _dhara_sql_query_impl(sql=sql, params=params)  # type: ignore[no-any-return]

        # --- Discovery meta-tool (always registered) ---
        all_tools: dict[str, str] = {}
        for group_name, tools in TOOL_GROUP_TOOLS.items():
            desc = TOOL_GROUP_DESCRIPTIONS.get(group_name, "")
            for tool_name in tools:
                all_tools[tool_name] = desc

        @self.server.tool()
        async def discover_tools(query: str | None = None) -> dict[str, Any]:
            """Search for available Dhara tools by name or capability."""
            filtered = all_tools
            if query:
                q = query.lower()
                filtered = {
                    n: d
                    for n, d in all_tools.items()
                    if q in n.lower() or q in d.lower()
                }

            profile_group_tools: set[str] = set()
            for gn in TOOL_GROUPS_BY_PROFILE.get(profile, [TOOL_GROUP_KV_TIME_SERIES]):
                profile_group_tools.update(TOOL_GROUP_TOOLS.get(gn, []))

            loaded = sorted(set(filtered.keys()) & profile_group_tools)
            not_loaded = sorted(set(filtered.keys()) - profile_group_tools)

            return {
                "status": "success",
                "profile": profile.value,
                "query": query,
                "loaded_tools": loaded,
                "loaded_count": len(loaded),
                "not_loaded_tools": not_loaded,
                "not_loaded_count": len(not_loaded),
                "hint": "Set DHARA_TOOL_PROFILE=full to enable all tools.",
            }

        logger.info("Dhara MCP tools registration complete (profile=%s)", profile.value)

        # Register REST-style /tools/call endpoint for Akosha client compatibility.
        # Akosha's DharaServiceRegistryClient calls /tools/call (not /mcp) with
        # {"name": "...", "arguments": {...}}. We call underlying store methods directly.
        self._register_tools_call_route()

        # Register substrate CRUD HTTP routes (Workstream C).
        # Persistence uses the AsyncFileStorage-backed Connection.root mapping;
        # Workstream D will swap to SQL-backed tables.
        register_substrate_routes(self.server, self.connection)

    def _register_tools_call_route(self) -> None:
        """Register /tools/call REST-style endpoint for Akosha client compatibility."""

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
            except Exception:
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
            except Exception as exc:
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
            version="0.1.0",
            start_time=self._start_time,
            dependencies=dependencies,
        )

        logger.info("Registered health check tools")

    def _probe_storage(self) -> dict[str, Any]:
        """Probe storage accessibility for readiness and health reporting."""
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
        except Exception as exc:
            return {
                "path": str(storage_path),
                "exists": storage_path.exists(),
                "accessible": False,
                "read_only": self.config.storage.read_only,
                "error": str(exc),
            }

    def _probe_backups(self) -> dict[str, Any]:
        """Probe backup catalog visibility for recovery awareness."""
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
        except Exception as exc:
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
            storage = AsyncFileStorage(str(catalog_path), readonly=True)
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
            "version": "0.1.0",
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
        import asyncio

        logger.info(f"Starting Dhara MCP server on {host}:{port}")

        # Initialize async stores before the event loop starts
        asyncio.run(self._init_async_stores())

        # FastMCP 3.x uses run_http_async() for HTTP transport
        asyncio.run(self.server.run_http_async(host=host, port=port))

    async def _init_async_stores(self) -> None:
        """Initialize async stores from AsyncSqliteStorage for async tool dispatch."""
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
            self.storage.close()
        logger.info("Dhara MCP Server closed")

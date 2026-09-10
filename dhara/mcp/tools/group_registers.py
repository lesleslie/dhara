"""Per-group registration wrappers for the W0 apply_tool_profile helper.

Each wrapper takes a single FastMCP server AND a :class:`DharaMCPServer`
instance (so the wrappers can access ``self._async_kv_store``,
``self.config``, etc.). The ``PROFILE_REGISTRATIONS`` /
``REGISTRATION_MAP`` dispatch in :mod:`dhara.mcp.profiles` routes
per-profile group lists to these wrappers via the W0 mcp-common helper.

The wrappers are pure functions (not methods on ``DharaMCPServer``)
because the W0 helper passes only the FastMCP server to each callable;
the DharaMCPServer instance is captured per-call by the closures built
in ``DharaMCPServer._register_tools_async``. Splitting per-group
registration into free functions keeps the W0 wiring small and
prevents ``DharaMCPServer._register_tools`` from ballooning into a
single 600-line method.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from dhara.mcp.server_core import DharaMCPServer


def _auth_helper(server_self: DharaMCPServer) -> Any:
    """Return the FastMCP authorization callable (or None) for the active config.

    Mirrors the legacy inner ``auth(*scopes)`` helper in
    ``DharaMCPServer._register_tools``:
    - auth disabled → ``require_scopes()`` (empty-scope check)
    - auth enabled → ``require_scopes`` (function; called with *scopes below)
    """
    from fastmcp.server.auth import require_scopes

    assert server_self.config is not None, "config required for auth scopes"
    if not server_self.config.authentication.enabled:
        return require_scopes()
    return require_scopes


def register_kv_timeseries_group(server: FastMCP, instance: DharaMCPServer) -> None:
    """Register KV / time-series storage tools (MINIMAL profile).

    Mirrors the legacy inline definitions inside
    ``DharaMCPServer._register_tools`` for ``put`` / ``get`` /
    ``list_prefix`` / ``record_time_series`` / ``query_time_series`` /
    ``aggregate_patterns``. Uses ``@server.tool()`` directly (the W0
    helper already filters by profile, so no inner conditional needed).
    """
    require_scopes_fn = _auth_helper(instance)

    def auth(*scopes: str) -> Any:
        if not instance.config or not instance.config.authentication.enabled:
            return require_scopes_fn
        return require_scopes_fn(*scopes)

    @server.tool(name="dhara_put", auth=auth("write"))
    async def put(
        key: str,
        value: dict[str, Any] | str | float | bool | list[Any] | None,
        ttl: int | None = None,
    ) -> dict[str, Any]:
        """Store a key/value record with optional TTL (seconds)."""
        assert instance._async_kv_store is not None, "Async store not initialized"
        return await instance._async_kv_store.put_async(key=key, value=value, ttl=ttl)  # type: ignore[no-any-return]

    @server.tool(name="dhara_get", auth=auth("read"))
    async def get(key: str) -> dict[str, Any]:
        """Get a key/value record."""
        assert instance._async_kv_store is not None, "Async store not initialized"
        return await instance._async_kv_store.get_async(key=key)  # type: ignore[no-any-return]

    @server.tool(name="dhara_list_prefix", auth=auth("read"))
    async def list_prefix(prefix: str) -> dict[str, Any]:
        """List all key/value records under a key prefix."""
        assert instance._async_kv_store is not None, "Async store not initialized"
        results = await instance._async_kv_store.list_prefix_async(prefix)
        return {"ok": True, "count": len(results), "items": results}

    @server.tool(name="dhara_record_time_series", auth=auth("write"))
    async def record_time_series(
        metric_type: str,
        entity_id: str,
        record: dict[str, Any],
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Append a time-series record."""
        assert instance._async_kv_store is not None, "Async store not initialized"
        return await instance._async_kv_store.record_time_series_async(  # type: ignore[no-any-return]
            metric_type=metric_type,
            entity_id=entity_id,
            record=record,
            timestamp=timestamp,
        )

    @server.tool(name="dhara_query_time_series", auth=auth("read"))
    async def query_time_series(
        metric_type: str,
        entity_id: str,
        start_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query time-series records."""
        assert instance._async_kv_store is not None, "Async store not initialized"
        return await instance._async_kv_store.query_time_series_async(  # type: ignore[no-any-return]
            metric_type=metric_type,
            entity_id=entity_id,
            start_date=start_date,
            limit=limit,
        )

    @server.tool(name="dhara_aggregate_patterns", auth=auth("read"))
    async def aggregate_patterns(
        start_date: str,
        min_occurrences: int = 2,
    ) -> list[dict[str, Any]]:
        """Aggregate patterns across time-series records."""
        assert instance._async_kv_store is not None, "Async store not initialized"
        return await instance._async_kv_store.aggregate_patterns_async(  # type: ignore[no-any-return]
            start_date=start_date,
            min_occurrences=min_occurrences,
        )


def register_adapter_registry_group(server: FastMCP, instance: DharaMCPServer) -> None:
    """Register adapter-registry tools (STANDARD+ profile)."""
    require_scopes_fn = _auth_helper(instance)

    def auth(*scopes: str) -> Any:
        if not instance.config or not instance.config.authentication.enabled:
            return require_scopes_fn
        return require_scopes_fn(*scopes)

    from dhara.mcp.adapter_tools import (
        get_adapter_async_impl,
        get_adapter_health_async_impl,
        list_adapter_versions_async_impl,
        list_adapters_async_impl,
        store_adapter_async_impl,
        validate_adapter_async_impl,
    )

    @server.tool(name="dhara_store_adapter", auth=auth("write"))
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
        """Store a Oneiric adapter in the registry."""
        assert instance._async_adapter_registry is not None, (
            "Async store not initialized"
        )
        return await store_adapter_async_impl(  # type: ignore[no-any-return]
            registry=instance._async_adapter_registry,
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

    @server.tool(name="dhara_get_contract_info", auth=auth("read"))
    async def get_contract_info() -> dict[str, Any]:
        """Return the supported Dhara MCP contract summary."""
        assert instance.config is not None, "config required for contract info"
        auth_mode = "token" if instance.auth_verifier is not None else "none"
        return {
            "ok": True,
            "server": {
                "name": instance.config.server_name,
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
                "canonical_fastmcp_wired": instance.auth_verifier is not None,
                "available_library_surfaces": [
                    "TokenAuth",
                    "HMACAuth",
                    "EnvironmentAuth",
                    "AuthMiddleware",
                ],
                "required_scopes": instance.config.authentication.required_scopes.copy(),
                "token_file": (
                    str(instance.config.authentication.token.tokens_file.expanduser())
                    if instance.config.authentication.token.tokens_file is not None
                    else None
                ),
                "notes": (
                    "Canonical FastMCP auth uses bearer tokens backed by the "
                    "Dhara token store when enabled."
                )
                if instance.auth_verifier is not None
                else (
                    "The canonical FastMCP server does not currently enforce "
                    "auth in the runtime path."
                ),
            },
        }

    @server.tool(name="dhara_get_adapter", auth=auth("read"))
    async def get_adapter(
        domain: str,
        key: str,
        provider: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve an adapter from the registry."""
        assert instance._async_adapter_registry is not None, (
            "Async store not initialized"
        )
        return await get_adapter_async_impl(  # type: ignore[no-any-return]
            registry=instance._async_adapter_registry,
            domain=domain,
            key=key,
            provider=provider,
            version=version,
        )

    @server.tool(name="dhara_list_adapters", auth=auth("list"))
    async def list_adapters(
        domain: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """List adapters with optional filtering."""
        assert instance._async_adapter_registry is not None, (
            "Async store not initialized"
        )
        return await list_adapters_async_impl(  # type: ignore[no-any-return]
            registry=instance._async_adapter_registry,
            domain=domain,
            category=category,
        )

    @server.tool(name="dhara_list_adapter_versions", auth=auth("list"))
    async def list_adapter_versions(
        domain: str,
        key: str,
        provider: str,
    ) -> dict[str, Any]:
        """List all versions of an adapter."""
        assert instance._async_adapter_registry is not None, (
            "Async store not initialized"
        )
        return await list_adapter_versions_async_impl(  # type: ignore[no-any-return]
            registry=instance._async_adapter_registry,
            domain=domain,
            key=key,
            provider=provider,
        )

    @server.tool(name="dhara_validate_adapter", auth=auth("read"))
    async def validate_adapter(
        domain: str,
        key: str,
        provider: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Validate an adapter configuration."""
        assert instance._async_adapter_registry is not None, (
            "Async store not initialized"
        )
        return await validate_adapter_async_impl(  # type: ignore[no-any-return]
            registry=instance._async_adapter_registry,
            domain=domain,
            key=key,
            provider=provider,
            version=version,
        )

    @server.tool(name="dhara_get_adapter_health", auth=auth("read"))
    async def get_adapter_health(
        domain: str,
        key: str,
        provider: str,
    ) -> dict[str, Any]:
        """Check health status of an adapter."""
        assert instance._async_adapter_registry is not None, (
            "Async store not initialized"
        )
        return await get_adapter_health_async_impl(  # type: ignore[no-any-return]
            registry=instance._async_adapter_registry,
            domain=domain,
            key=key,
            provider=provider,
        )


def register_ecosystem_state_group(server: FastMCP, instance: DharaMCPServer) -> None:
    """Register ecosystem-state tools (STANDARD+ profile)."""
    require_scopes_fn = _auth_helper(instance)

    def auth(*scopes: str) -> Any:
        if not instance.config or not instance.config.authentication.enabled:
            return require_scopes_fn
        return require_scopes_fn(*scopes)

    @server.tool(name="dhara_upsert_service", auth=auth("write"))
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
        assert instance._async_ecosystem_state is not None, (
            "Async store not initialized"
        )
        return await instance._async_ecosystem_state.upsert_service_async(  # type: ignore[no-any-return]
            service_id=service_id,
            service_type=service_type,
            capabilities=capabilities,
            metadata=metadata,
            status=status,
            lease_expires_at=lease_expires_at,
            heartbeat_at=heartbeat_at,
        )

    @server.tool(name="dhara_get_service", auth=auth("read"))
    async def get_service(service_id: str) -> dict[str, Any]:
        """Fetch a durable ecosystem service record."""
        assert instance._async_ecosystem_state is not None, (
            "Async store not initialized"
        )
        service = await instance._async_ecosystem_state.get_service_async(service_id)
        return {"ok": True, "service": service}

    @server.tool(name="dhara_list_services", auth=auth("list"))
    async def list_services(
        service_type: str | None = None,
        capability: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List durable ecosystem service records."""
        assert instance._async_ecosystem_state is not None, (
            "Async store not initialized"
        )
        services = await instance._async_ecosystem_state.list_services_async(
            service_type=service_type,
            capability=capability,
            status=status,
        )
        return {"ok": True, "count": len(services), "services": services}

    @server.tool(name="dhara_record_event", auth=auth("write"))
    async def record_event(
        event_type: str,
        source_service: str,
        payload: dict[str, Any] | None = None,
        related_service: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Append a durable ecosystem event."""
        assert instance._async_ecosystem_state is not None, (
            "Async store not initialized"
        )
        return await instance._async_ecosystem_state.record_event_async(  # type: ignore[no-any-return]
            event_type=event_type,
            source_service=source_service,
            payload=payload,
            related_service=related_service,
            timestamp=timestamp,
        )

    @server.tool(name="dhara_list_events", auth=auth("list"))
    async def list_events(
        event_type: str | None = None,
        source_service: str | None = None,
        related_service: str | None = None,
        limit: int | None = 100,
    ) -> dict[str, Any]:
        """List durable ecosystem events."""
        assert instance._async_ecosystem_state is not None, (
            "Async store not initialized"
        )
        events = await instance._async_ecosystem_state.list_events_async(
            event_type=event_type,
            source_service=source_service,
            related_service=related_service,
            limit=limit,
        )
        return {"ok": True, "count": len(events), "events": events}


def register_sql_proxy_group(server: FastMCP, instance: DharaMCPServer) -> None:
    """Register SQL proxy tools (FULL profile only)."""
    require_scopes_fn = _auth_helper(instance)

    def auth(*scopes: str) -> Any:
        if not instance.config or not instance.config.authentication.enabled:
            return require_scopes_fn
        return require_scopes_fn(*scopes)

    from dhara.mcp.tools.sql_proxy import (
        dhara_sql_execute as _dhara_sql_execute_impl,
    )
    from dhara.mcp.tools.sql_proxy import (
        dhara_sql_query as _dhara_sql_query_impl,
    )

    @server.tool(auth=auth("write"))
    async def dhara_sql_execute(
        sql: str,
        params: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a DDL/DML statement through the SQL proxy backend."""
        return await _dhara_sql_execute_impl(sql=sql, params=params)  # type: ignore[no-any-return]

    @server.tool(auth=auth("read"))
    async def dhara_sql_query(
        sql: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a read-only SELECT/WITH query through the SQL proxy."""
        return await _dhara_sql_query_impl(sql=sql, params=params)  # type: ignore[no-any-return]


def register_health_tools_group(server: FastMCP, instance: DharaMCPServer) -> None:
    """Register health check tools (always-on via DHARA_MANDATORY_GROUPS).

    Delegates to the existing ``DharaMCPServer._register_health_tools``
    method so the W0 path and the legacy path share one implementation
    (no drift between two health-registration bodies).
    """
    instance._register_health_tools()


def register_skills_signer_tools_group(
    server: FastMCP, instance: DharaMCPServer
) -> None:
    """Phase 1.5 — register the skills_signer tools group (per plan §10.3.6).

    Phase 1.5 itself only wires the feed state (the manifest data is
    published via ``DharaMCPServer._runtime_status()``). Phase 1 adds
    the ``list_skills`` / ``get_skill`` MCP tools via the dedicated
    :func:`register_skill_registry_group` (separate registration key
    per plan §6, dhara naming convention) — this wrapper stays a
    no-op so the manifest data ships via ``_runtime_status()`` rather
    than as duplicate tool registrations.

    Args:
        server: the FastMCP server (unused at phase
            1.5; kept for signature parity with the other per-group
            wrappers).
        instance: the :class:`DharaMCPServer` whose
            ``signer_feed_state`` is published in ``/health``.
    """
    # No-op at registration time. Signer init runs in DharaMCPServer.__init__
    # (after the lightweight construction check, before FastMCP server routes
    # are registered). During the config=None lightweight construction path,
    # ``signer_feed_state`` stays as ``None`` and ``_runtime_status()``
    # reports ``ok=False`` with ``error="signer feed state not initialized"``
    # — but the lightweight path does NOT register the /health route, so
    # callers there can't observe the feed at all. Phase 1's
    # ``list_skills`` / ``get_skill`` tools are registered separately via
    # :func:`register_skill_registry_group`.
    return


def register_skill_registry_group(
    server: FastMCP, instance: DharaMCPServer
) -> None:
    """Phase 1 — register the ``list_skills`` / ``get_skill`` MCP tools.

    Delegates to :func:`dhara.mcp.tools.skill_registry.register_skill_registry`
    so the per-group wiring here stays a one-liner. The actual tool
    handlers live in :mod:`dhara.mcp.tools.skill_registry` and pull
    the :class:`SkillsSigner` from the module-level
    :func:`dhara.mcp.signer_feed.get_signer_feed_state` singleton.

    The dhara-specific naming convention (per plan §6) is
    ``skill_registry`` (not ``skill_tools`` like the akosha reference
    impl); this matches the file name
    ``dhara/mcp/tools/skill_registry.py``.

    Args:
        server: the FastMCP server to decorate.
        instance: the :class:`DharaMCPServer` (kept for signature
            parity with the other per-group wrappers — the registry
            tools don't need the instance because they read the signer
            singleton).
    """
    from dhara.mcp.tools.skill_registry import register_skill_registry

    register_skill_registry(server)


__all__ = [
    "register_adapter_registry_group",
    "register_ecosystem_state_group",
    "register_health_tools_group",
    "register_kv_timeseries_group",
    "register_skill_registry_group",
    "register_skills_signer_tools_group",
    "register_sql_proxy_group",
]
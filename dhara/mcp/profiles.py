"""Tool profile registration groups for Dhara MCP server.

Maps ToolProfile levels to tool group names that are registered inline
inside DharaMCPServer._register_tools().

The dispatch surface (PROFILE_REGISTRATIONS + REGISTRATION_MAP +
DHARA_MANDATORY_GROUPS) is consumed by
:func:`mcp_common.tools.dispatch._apply_tool_profile` when called from
:func:`dhara.mcp.server_core.DharaMCPServer._register_tools_async`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_common.tools import ToolProfile

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import FastMCP

TOOL_GROUP_ADAPTER_REGISTRY = "adapter_registry"
TOOL_GROUP_KV_TIME_SERIES = "kv_time_series"
TOOL_GROUP_ECOSYSTEM_STATE = "ecosystem_state"
TOOL_GROUP_SQL_PROXY = "sql_proxy"

TOOL_GROUP_TOOLS: dict[str, list[str]] = {
    TOOL_GROUP_KV_TIME_SERIES: [
        "put",
        "get",
        "list_prefix",
        "record_time_series",
        "query_time_series",
        "aggregate_patterns",
    ],
    TOOL_GROUP_ADAPTER_REGISTRY: [
        "store_adapter",
        "get_contract_info",
        "get_adapter",
        "list_adapters",
        "list_adapter_versions",
        "validate_adapter",
        "get_adapter_health",
    ],
    TOOL_GROUP_ECOSYSTEM_STATE: [
        "upsert_service",
        "get_service",
        "list_services",
        "record_event",
        "list_events",
    ],
    TOOL_GROUP_SQL_PROXY: [
        "dhara_sql_execute",
        "dhara_sql_query",
    ],
}

TOOL_GROUP_DESCRIPTIONS: dict[str, str] = {
    TOOL_GROUP_KV_TIME_SERIES: "Key/value storage with TTL, time-series records, and pattern aggregation",
    TOOL_GROUP_ADAPTER_REGISTRY: "Dhara adapter registry: store, retrieve, validate, and version adapters",
    TOOL_GROUP_ECOSYSTEM_STATE: "Durable ecosystem service and event records",
    TOOL_GROUP_SQL_PROXY: "Generic SQL proxy (execute DDL/DML, query SELECT/WITH) — DuckDB in dev/test, asyncpg in production",
}

HEALTH_TOOLS: list[str] = [
    "get_liveness",
    "get_readiness",
    "health_check_service",
    "health_check_all",
    "wait_for_dependency",
    "wait_for_all_dependencies",
]

MINIMAL_GROUPS = [TOOL_GROUP_KV_TIME_SERIES]
STANDARD_GROUPS = MINIMAL_GROUPS + [
    TOOL_GROUP_ADAPTER_REGISTRY,
    TOOL_GROUP_ECOSYSTEM_STATE,
    TOOL_GROUP_SQL_PROXY,
]
FULL_GROUPS = STANDARD_GROUPS

TOOL_GROUPS_BY_PROFILE: dict[ToolProfile, list[str]] = {
    ToolProfile.MINIMAL: MINIMAL_GROUPS,
    ToolProfile.STANDARD: STANDARD_GROUPS,
    ToolProfile.FULL: FULL_GROUPS,
}


def get_active_profile(env_var: str = "DHARA_TOOL_PROFILE") -> ToolProfile:
    """Read the active tool profile from the environment."""
    return ToolProfile.from_env(env_var)


# ---------------------------------------------------------------------------
# W0 apply_tool_profile dispatch surface.
#
# PROFILE_REGISTRATIONS maps each ToolProfile level to the list of
# registration_map keys active at that profile. REGISTRATION_MAP routes
# each group key to a per-group registration callable. DHARA_MANDATORY_GROUPS
# is a set of registration_map keys whose registrars run AFTER per-profile
# dispatch at every profile (always-on). Set to a subset of
# REGISTRATION_MAP.keys(); the W0 helper raises if a mandatory key is
# missing from the map.
#
# Per-group wrappers live in :mod:`dhara.mcp.tools.group_registers` and
# take ``(server, instance)`` where ``instance`` is the DharaMCPServer
# (for ``self._async_kv_store`` and friends). The W0 helper passes only
# the server, so the per-instance registration_map is built lazily in
# ``DharaMCPServer._register_tools_async`` after async stores are
# initialized.
# ---------------------------------------------------------------------------

PROFILE_REGISTRATIONS: dict[ToolProfile, list[str]] = {
    ToolProfile.MINIMAL: [TOOL_GROUP_KV_TIME_SERIES],
    ToolProfile.STANDARD: [
        TOOL_GROUP_KV_TIME_SERIES,
        TOOL_GROUP_ADAPTER_REGISTRY,
        TOOL_GROUP_ECOSYSTEM_STATE,
        TOOL_GROUP_SQL_PROXY,
    ],
    ToolProfile.FULL: [
        TOOL_GROUP_KV_TIME_SERIES,
        TOOL_GROUP_ADAPTER_REGISTRY,
        TOOL_GROUP_ECOSYSTEM_STATE,
        TOOL_GROUP_SQL_PROXY,
    ],
}

# Registration map keys (also used as PROFILE_REGISTRATIONS entries).
REG_KEY_HEALTH = "register_health_tools"
REG_KEY_KV = TOOL_GROUP_KV_TIME_SERIES
REG_KEY_ADAPTER = TOOL_GROUP_ADAPTER_REGISTRY
REG_KEY_ECOSYSTEM = TOOL_GROUP_ECOSYSTEM_STATE
REG_KEY_SQL = TOOL_GROUP_SQL_PROXY


def _build_registration_map() -> dict[str, Callable[[FastMCP], Awaitable[None] | None]]:
    """Build the {group_key: register_fn(app)} map.

    Local import keeps ``dhara.mcp.tools.profiles`` importable without
    pulling the per-group register modules at module load.
    """
    from dhara.mcp.tools.group_registers import (
        register_adapter_registry_group,
        register_ecosystem_state_group,
        register_health_tools_group,
        register_kv_timeseries_group,
        register_sql_proxy_group,
    )

    return {
        REG_KEY_KV: register_kv_timeseries_group,
        REG_KEY_ADAPTER: register_adapter_registry_group,
        REG_KEY_ECOSYSTEM: register_ecosystem_state_group,
        REG_KEY_SQL: register_sql_proxy_group,
        REG_KEY_HEALTH: register_health_tools_group,
    }


REGISTRATION_MAP: dict[str, Callable[[FastMCP], Awaitable[None] | None]] = (
    _build_registration_map()
)

# Always-on groups: registered at every profile level in addition to the
# per-profile list. Health checks must be reachable from any profile tier
# (load balancers / orchestrators depend on them).
DHARA_MANDATORY_GROUPS: set[str] = {REG_KEY_HEALTH}


__all__ = [
    "DHARA_MANDATORY_GROUPS",
    "FULL_GROUPS",
    "HEALTH_TOOLS",
    "MINIMAL_GROUPS",
    "PROFILE_REGISTRATIONS",
    "REGISTRATION_MAP",
    "STANDARD_GROUPS",
    "TOOL_GROUP_ADAPTER_REGISTRY",
    "TOOL_GROUP_DESCRIPTIONS",
    "TOOL_GROUP_ECOSYSTEM_STATE",
    "TOOL_GROUP_KV_TIME_SERIES",
    "TOOL_GROUP_SQL_PROXY",
    "TOOL_GROUP_TOOLS",
    "get_active_profile",
]

"""Tool profile registration groups for Dhara MCP server.

Maps ToolProfile levels to tool group names that are registered inline
inside DharaMCPServer._register_tools().
"""

from __future__ import annotations

from mcp_common.tools import ToolProfile

TOOL_GROUP_ADAPTER_REGISTRY = "adapter_registry"
TOOL_GROUP_KV_TIME_SERIES = "kv_time_series"
TOOL_GROUP_ECOSYSTEM_STATE = "ecosystem_state"

TOOL_GROUP_TOOLS: dict[str, list[str]] = {
    TOOL_GROUP_KV_TIME_SERIES: [
        "put", "get", "record_time_series", "query_time_series", "aggregate_patterns",
    ],
    TOOL_GROUP_ADAPTER_REGISTRY: [
        "store_adapter", "get_contract_info", "get_adapter", "list_adapters",
        "list_adapter_versions", "validate_adapter", "get_adapter_health",
    ],
    TOOL_GROUP_ECOSYSTEM_STATE: [
        "upsert_service", "get_service", "list_services", "record_event", "list_events",
    ],
}

TOOL_GROUP_DESCRIPTIONS: dict[str, str] = {
    TOOL_GROUP_KV_TIME_SERIES: "Key/value storage with TTL, time-series records, and pattern aggregation",
    TOOL_GROUP_ADAPTER_REGISTRY: "Oneiric adapter registry: store, retrieve, validate, and version adapters",
    TOOL_GROUP_ECOSYSTEM_STATE: "Durable ecosystem service and event records",
}

HEALTH_TOOLS: list[str] = [
    "get_liveness", "get_readiness", "health_check_service",
    "health_check_all", "wait_for_dependency", "wait_for_all_dependencies",
]

MINIMAL_GROUPS = [TOOL_GROUP_KV_TIME_SERIES]
STANDARD_GROUPS = MINIMAL_GROUPS + [TOOL_GROUP_ADAPTER_REGISTRY, TOOL_GROUP_ECOSYSTEM_STATE]
FULL_GROUPS = STANDARD_GROUPS

TOOL_GROUPS_BY_PROFILE: dict[ToolProfile, list[str]] = {
    ToolProfile.MINIMAL: MINIMAL_GROUPS,
    ToolProfile.STANDARD: STANDARD_GROUPS,
    ToolProfile.FULL: FULL_GROUPS,
}


def get_active_profile(env_var: str = "DHARA_TOOL_PROFILE") -> ToolProfile:
    """Read the active tool profile from the environment."""
    return ToolProfile.from_env(env_var)


__all__ = [
    "FULL_GROUPS", "HEALTH_TOOLS", "MINIMAL_GROUPS", "STANDARD_GROUPS",
    "TOOL_GROUP_ADAPTER_REGISTRY", "TOOL_GROUP_DESCRIPTIONS",
    "TOOL_GROUP_ECOSYSTEM_STATE", "TOOL_GROUP_KV_TIME_SERIES",
    "TOOL_GROUP_TOOLS", "TOOL_GROUPS_BY_PROFILE", "get_active_profile",
]

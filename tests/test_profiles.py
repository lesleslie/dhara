"""Tests for dhara/mcp/profiles.py — tool profile registration groups."""

from __future__ import annotations

import os

import pytest

from dhara.mcp.profiles import (
    FULL_GROUPS,
    MINIMAL_GROUPS,
    STANDARD_GROUPS,
    TOOL_GROUP_ADAPTER_REGISTRY,
    TOOL_GROUP_DESCRIPTIONS,
    TOOL_GROUP_ECOSYSTEM_STATE,
    TOOL_GROUP_KV_TIME_SERIES,
    TOOL_GROUP_TOOLS,
    TOOL_GROUPS_BY_PROFILE,
    HEALTH_TOOLS,
    get_active_profile,
)


class TestConstants:
    def test_group_names(self):
        assert TOOL_GROUP_KV_TIME_SERIES == "kv_time_series"
        assert TOOL_GROUP_ADAPTER_REGISTRY == "adapter_registry"
        assert TOOL_GROUP_ECOSYSTEM_STATE == "ecosystem_state"

    def test_kv_tools(self):
        tools = TOOL_GROUP_TOOLS[TOOL_GROUP_KV_TIME_SERIES]
        assert "put" in tools
        assert "get" in tools
        assert "record_time_series" in tools
        assert "query_time_series" in tools
        assert "aggregate_patterns" in tools

    def test_adapter_tools(self):
        tools = TOOL_GROUP_TOOLS[TOOL_GROUP_ADAPTER_REGISTRY]
        assert "store_adapter" in tools
        assert "get_adapter" in tools
        assert "list_adapters" in tools
        assert "validate_adapter" in tools

    def test_ecosystem_tools(self):
        tools = TOOL_GROUP_TOOLS[TOOL_GROUP_ECOSYSTEM_STATE]
        assert "upsert_service" in tools
        assert "get_service" in tools
        assert "record_event" in tools

    def test_descriptions_exist_for_all_groups(self):
        for group in TOOL_GROUP_TOOLS:
            assert group in TOOL_GROUP_DESCRIPTIONS

    def test_health_tools_defined(self):
        assert "get_liveness" in HEALTH_TOOLS
        assert "get_readiness" in HEALTH_TOOLS

    def test_profile_hierarchy(self):
        assert set(MINIMAL_GROUPS) < set(STANDARD_GROUPS)
        assert set(STANDARD_GROUPS) == set(FULL_GROUPS)

    def test_profiles_map(self):
        from mcp_common.tools import ToolProfile
        assert ToolProfile.MINIMAL in TOOL_GROUPS_BY_PROFILE
        assert ToolProfile.STANDARD in TOOL_GROUPS_BY_PROFILE
        assert ToolProfile.FULL in TOOL_GROUPS_BY_PROFILE


class TestGetActiveProfile:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("DHARA_TOOL_PROFILE", raising=False)
        profile = get_active_profile()
        from mcp_common.tools import ToolProfile
        # Default depends on ToolProfile.from_env, just verify it returns a valid profile
        assert isinstance(profile, ToolProfile)

    def test_env_minimal(self, monkeypatch):
        monkeypatch.setenv("DHARA_TOOL_PROFILE", "minimal")
        profile = get_active_profile()
        from mcp_common.tools import ToolProfile
        assert profile == ToolProfile.MINIMAL

    def test_env_full(self, monkeypatch):
        monkeypatch.setenv("DHARA_TOOL_PROFILE", "full")
        profile = get_active_profile()
        from mcp_common.tools import ToolProfile
        assert profile == ToolProfile.FULL

    def test_custom_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_PROFILE", "full")
        profile = get_active_profile(env_var="MY_PROFILE")
        from mcp_common.tools import ToolProfile
        assert profile == ToolProfile.FULL

"""Regression test for tool-group drift in Dhara's MCP server.

Dhara declares MCP tool groups in ``dhara/mcp/profiles.py`` and registers
them through per-group wrappers in
``dhara/mcp/tools/group_registers.py``. Each wrapper carries the inline
tool definitions decorated with ``@server.tool(...)``. The wrappers are
dispatched by the W0 ``apply_tool_profile`` helper from mcp-common at
server construction time, gated by the active ``ToolProfile``.

This test uses ``ast`` to parse ``group_registers.py`` and verify that:

1. Every tool name declared in ``TOOL_GROUP_TOOLS`` is registered inside
   the matching per-group ``register_*_group`` wrapper
   (catches declared-but-unimplemented drift).
2. Every function registered inside the wrappers appears in
   ``TOOL_GROUP_TOOLS[its_group]`` (catches implemented-but-undeclared drift).
3. Profile groups are monotonic: ``MINIMAL_GROUPS ⊆ STANDARD_GROUPS ⊆ FULL_GROUPS``.
4. Every group listed in ``TOOL_GROUPS_BY_PROFILE[profile]`` has at least
   one registered tool (catches dead groups in the profile map).
5. Each group has at least two tools (sanity check against over-fragmentation).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dhara.mcp.profiles import (
    FULL_GROUPS,
    MINIMAL_GROUPS,
    STANDARD_GROUPS,
    TOOL_GROUPS_BY_PROFILE,
    TOOL_GROUP_TOOLS,
)
from mcp_common.tools import ToolProfile


# Resolve group_registers.py relative to this test file so the test does
# not depend on the caller's working directory.
GROUP_REGISTERS_PATH = (
    Path(__file__).resolve().parents[3]
    / "dhara"
    / "mcp"
    / "tools"
    / "group_registers.py"
)

# Per-group wrappers in ``group_registers.py`` are named
# ``register_<group>_group``. Map the registration wrapper to the group key
# in ``TOOL_GROUP_TOOLS`` so the AST walker can attribute each
# ``@server.tool``-decorated function to its group.
_WRAPPER_TO_GROUP: dict[str, str] = {
    "register_kv_timeseries_group": "kv_time_series",
    "register_adapter_registry_group": "adapter_registry",
    "register_ecosystem_state_group": "ecosystem_state",
    "register_sql_proxy_group": "sql_proxy",
    "register_health_tools_group": "health",
}


def _parse_registered_tools(source_path: Path) -> dict[str, str]:
    """Parse ``source_path`` and return ``{function_name: group_name}`` for
    every function decorated with ``@server.tool(...)`` inside a
    ``register_<group>_group`` wrapper.

    Nested ``def auth(*scopes)`` helpers (no decorator) are ignored.
    """
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    registered: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in _WRAPPER_TO_GROUP:
            continue
        group_name = _WRAPPER_TO_GROUP[node.name]
        for child in ast.walk(node):
            if child is node:
                continue
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in child.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                # Match ``@server.tool(...)`` — the FastMCP decorator used
                # in group_registers.py. Ignore the inner ``auth(*scopes)``
                # helper which is captured but undecorated.
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "server"
                    and func.attr == "tool"
                ):
                    registered[child.name] = group_name
                    break
    return registered


@pytest.fixture(scope="module")
def registered_tools() -> dict[str, str]:
    """Tool function names -> group name, parsed from group_registers.py."""
    return _parse_registered_tools(GROUP_REGISTERS_PATH)


def test_all_declared_tools_actually_registered(
    registered_tools: dict[str, str],
) -> None:
    """Every tool name in TOOL_GROUP_TOOLS[GROUP] must be registered inside
    the matching ``register_<group>_group`` wrapper. Catches
    declared-but-unimplemented drift.
    """
    missing: list[tuple[str, str]] = []
    for group_name, tool_names in TOOL_GROUP_TOOLS.items():
        for tool_name in tool_names:
            actual_group = registered_tools.get(tool_name)
            if actual_group is None:
                missing.append((tool_name, group_name))
            elif actual_group != group_name:
                # Wrong-group is a related drift; surface it here too.
                missing.append(
                    (tool_name, f"{group_name} (registered as {actual_group})")
                )

    assert not missing, (
        "Declared in TOOL_GROUP_TOOLS but missing or mis-registered in "
        f"group_registers.py: {missing}"
    )


def test_no_undeclared_tools(registered_tools: dict[str, str]) -> None:
    """Every function registered inside a ``register_<group>_group`` wrapper
    must appear in ``TOOL_GROUP_TOOLS[GROUP]`` (ignoring health tools, which
    live in ``_register_health_tools`` and ``HEALTH_TOOLS``). Catches
    implemented-but-undeclared drift.
    """
    undeclared: list[tuple[str, str]] = []
    for tool_name, group_name in registered_tools.items():
        if group_name == "health":
            # Health tools are tracked separately in ``HEALTH_TOOLS``;
            # they aren't part of ``TOOL_GROUP_TOOLS``.
            continue
        if tool_name in TOOL_GROUP_TOOLS.get(group_name, []):
            continue
        undeclared.append((tool_name, group_name))

    assert not undeclared, (
        "Registered in group_registers.py but not declared in "
        f"TOOL_GROUP_TOOLS[group]: {undeclared}"
    )


def test_profile_group_subset_invariant() -> None:
    """MINIMAL_GROUPS ⊆ STANDARD_GROUPS ⊆ FULL_GROUPS.

    A profile widening must never drop a group that a smaller profile exposes.
    """
    minimal = set(MINIMAL_GROUPS)
    standard = set(STANDARD_GROUPS)
    full = set(FULL_GROUPS)

    assert minimal.issubset(standard), (
        "MINIMAL_GROUPS not a subset of STANDARD_GROUPS: "
        f"only-in-minimal={sorted(minimal - standard)}"
    )
    assert standard.issubset(full), (
        "STANDARD_GROUPS not a subset of FULL_GROUPS: "
        f"only-in-standard={sorted(standard - full)}"
    )


def test_group_membership_matches_profile(
    registered_tools: dict[str, str],
) -> None:
    """Every group in TOOL_GROUPS_BY_PROFILE[profile] must have at least one
    registered tool in group_registers.py. Catches dead groups: declared in
    a profile but never implemented (or removed from group_registers.py).
    """
    groups_with_tools = {g for g in registered_tools.values() if g != "health"}

    for profile in ToolProfile:
        profile_groups = set(TOOL_GROUPS_BY_PROFILE[profile])
        dead_groups = profile_groups - groups_with_tools
        assert not dead_groups, (
            f"Profile {profile.value!r} declares groups with no registered tools "
            f"in group_registers.py: {sorted(dead_groups)}"
        )


def test_tool_count_per_group() -> None:
    """Sanity check: each group must have at least two tools. SQL_PROXY is
    allowed to have exactly two (the proxy/execute + proxy/query pair).
    """
    too_small: list[tuple[str, int]] = []
    for group_name, tool_names in TOOL_GROUP_TOOLS.items():
        if len(tool_names) < 2:
            too_small.append((group_name, len(tool_names)))

    assert not too_small, (
        "Groups with fewer than two declared tools (likely over-fragmented): "
        f"{too_small}"
    )

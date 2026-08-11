"""Regression test for tool-group drift in Dhara's MCP server.

Dhara declares MCP tool groups in ``dhara/mcp/profiles.py`` and applies them
via a custom ``@_tool(group)`` decorator inside ``DharaMCPServer._register_tools``
in ``dhara/mcp/server_core.py``. The decorator returns a no-op (identity) when
the group is not in the active profile, so runtime introspection is unreliable.

This test uses ``ast`` to parse ``server_core.py`` and verify that:

1. Every tool name declared in ``TOOL_GROUP_TOOLS`` is actually decorated with
   ``@_tool(<group>, ...)`` in ``server_core.py`` (catches declared-but-unimplemented).
2. Every function decorated with ``@_tool(...)`` in ``server_core.py`` has its
   name listed in ``TOOL_GROUP_TOOLS[its_group]`` (catches implemented-but-undeclared).
3. Profile groups are monotonic: ``MINIMAL_GROUPS ⊆ STANDARD_GROUPS ⊆ FULL_GROUPS``.
4. Every group listed in ``TOOL_GROUPS_BY_PROFILE[profile]`` has at least one
   decorated tool (catches dead groups in the profile map).
5. Each group has at least two tools (sanity check against over-fragmentation).

The Dhara doc flagged "TOOL_GROUP_TOOLS vs actual @_tool decoration" as a
drift vector; this test pins that contract.
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
    TOOL_GROUP_ADAPTER_REGISTRY,
    TOOL_GROUP_ECOSYSTEM_STATE,
    TOOL_GROUP_KV_TIME_SERIES,
    TOOL_GROUP_SQL_PROXY,
    TOOL_GROUP_TOOLS,
)
from mcp_common.tools import ToolProfile


# Resolve server_core.py relative to this test file so the test does not
# depend on the caller's working directory.
SERVER_CORE_PATH = (
    Path(__file__).resolve().parents[3] / "dhara" / "mcp" / "server_core.py"
)

# Map the public group constant names exported from dhara.mcp.profiles to
# their resolved string values, so the AST walker can turn a Name node like
# ``TOOL_GROUP_ADAPTER_REGISTRY`` into ``"adapter_registry"``.
_GROUP_CONSTANT_VALUES: dict[str, str] = {
    "TOOL_GROUP_ADAPTER_REGISTRY": TOOL_GROUP_ADAPTER_REGISTRY,
    "TOOL_GROUP_KV_TIME_SERIES": TOOL_GROUP_KV_TIME_SERIES,
    "TOOL_GROUP_ECOSYSTEM_STATE": TOOL_GROUP_ECOSYSTEM_STATE,
    "TOOL_GROUP_SQL_PROXY": TOOL_GROUP_SQL_PROXY,
}


def _parse_decorated_tools(source_path: Path) -> dict[str, str]:
    """Parse ``source_path`` and return ``{function_name: group_name}`` for
    every function decorated with ``@_tool(<group>, ...)``.

    The first positional argument to ``_tool`` is the group. It may be either
    a string literal or a Name referring to one of the ``TOOL_GROUP_*``
    constants exported by ``dhara.mcp.profiles``. Only top-level functions
    and async functions are inspected; nested ``def auth(...)`` helpers that
    have no decorator are ignored.
    """
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    decorated: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            # Match ``@_tool(...)`` and ignore ``@self.server.tool()``,
            # which is used for the always-on ``discover_tools`` meta-tool.
            if not (isinstance(func, ast.Name) and func.id == "_tool"):
                continue
            if not decorator.args:
                continue
            first_arg = decorator.args[0]
            group_value: str | None = None
            if isinstance(first_arg, ast.Name):
                group_value = _GROUP_CONSTANT_VALUES.get(first_arg.id)
            elif isinstance(first_arg, ast.Constant) and isinstance(
                first_arg.value, str
            ):
                group_value = first_arg.value
            if group_value is not None:
                decorated[node.name] = group_value
    return decorated


@pytest.fixture(scope="module")
def decorated_tools() -> dict[str, str]:
    """Tool function names -> group name, parsed from server_core.py."""
    return _parse_decorated_tools(SERVER_CORE_PATH)


def test_all_declared_tools_actually_decorated(
    decorated_tools: dict[str, str],
) -> None:
    """Every tool name in TOOL_GROUP_TOOLS[GROUP] must be decorated with
    @_tool(GROUP, ...) in server_core.py. Catches declared-but-unimplemented drift.
    """
    missing: list[tuple[str, str]] = []
    for group_name, tool_names in TOOL_GROUP_TOOLS.items():
        for tool_name in tool_names:
            actual_group = decorated_tools.get(tool_name)
            if actual_group is None:
                missing.append((tool_name, group_name))
            elif actual_group != group_name:
                # Wrong-group is a related drift; surface it here too.
                missing.append(
                    (tool_name, f"{group_name} (decorated as {actual_group})")
                )

    assert not missing, (
        "Declared in TOOL_GROUP_TOOLS but missing or mis-decorated in server_core.py: "
        f"{missing}"
    )


def test_no_undeclared_tools(decorated_tools: dict[str, str]) -> None:
    """Every function decorated with @_tool(GROUP, ...) in server_core.py must
    appear in TOOL_GROUP_TOOLS[GROUP]. Catches implemented-but-undeclared drift.
    """
    undeclared: list[tuple[str, str]] = []
    for tool_name, group_name in decorated_tools.items():
        if tool_name in TOOL_GROUP_TOOLS.get(group_name, []):
            continue
        undeclared.append((tool_name, group_name))

    assert not undeclared, (
        "Decorated with @_tool(<group>) but not declared in TOOL_GROUP_TOOLS[group]: "
        f"{undeclared}"
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
    decorated_tools: dict[str, str],
) -> None:
    """Every group in TOOL_GROUPS_BY_PROFILE[profile] must have at least one
    decorated tool in server_core.py. Catches dead groups: declared in a
    profile but never implemented (or removed from server_core.py).
    """
    groups_with_tools = set(decorated_tools.values())

    for profile in ToolProfile:
        profile_groups = set(TOOL_GROUPS_BY_PROFILE[profile])
        dead_groups = profile_groups - groups_with_tools
        assert not dead_groups, (
            f"Profile {profile.value!r} declares groups with no decorated tools "
            f"in server_core.py: {sorted(dead_groups)}"
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

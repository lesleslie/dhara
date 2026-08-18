"""Capture golden fixture of tool names at each ToolProfile level.

Modeled on W1.3 akosha's capture script. Used BEFORE refactoring to lock
the current behavior of the legacy ``DharaMCPServer._register_tools``
conditional-decorator dispatch loop. Subsequent refactors must produce
identical tool sets at MINIMAL/STANDARD/FULL.

This capture uses Python AST parsing instead of constructing a full
DharaMCPServer because the heavy ``__init__`` path (AsyncConnection
wire, cache backend, etc.) is exercised by integration tests. The AST
analysis is sufficient because the legacy path uses a deterministic
decorator pattern: ``@_tool(GROUP_KEY, ...)`` on each tool function.

Usage:
    cd /Users/les/Projects/dhara
    uv run python scripts/capture_profile_fixtures.py [minimal|standard|full]

Default: capture all three profiles.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SERVER_CORE = ROOT / "dhara" / "mcp" / "server_core.py"


def _parse_tool_decorators() -> dict[str, set[str]]:
    """Return mapping of tool name -> {group_keys} from `_register_tools`.

    Each ``async def`` with a ``@_tool(GROUP_KEY, ...)`` decorator is
    recorded under that group. The ``@self.server.tool()`` decorator
    (without a group arg) is recorded under ``__always_on__``.

    GROUP_KEY may be either a string literal (``"foo"``) or a module-level
    constant (``TOOL_GROUP_ADAPTER_REGISTRY``). Constants are resolved by
    scanning the top-level ``Assign`` nodes across both server_core.py
    and profiles.py for string values.
    """
    module_constants: dict[str, str] = {}
    for path in (SERVER_CORE, ROOT / "dhara" / "mcp" / "profiles.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                    if isinstance(node.value.value, str):
                        module_constants[target.id] = node.value.value

    def _resolve_to_str(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in module_constants:
            return module_constants[node.id]
        return None

    tree = ast.parse(SERVER_CORE.read_text())

    # Locate DharaMCPServer._register_tools
    class_fns: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DharaMCPServer":
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    class_fns[item.name] = item

    register_tools = class_fns["_register_tools"]
    tool_to_groups: dict[str, set[str]] = {}

    for stmt in register_tools.body:
        if not isinstance(stmt, ast.AsyncFunctionDef):
            continue

        for dec in stmt.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            # Bare ``self.server.tool()`` → always on
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "tool"
            ):
                tool_to_groups.setdefault(stmt.name, set()).add("__always_on__")
                continue
            # ``_tool(GROUP_KEY, ...)`` — first arg is the group key
            if isinstance(func, ast.Name) and func.id == "_tool" and dec.args:
                resolved = _resolve_to_str(dec.args[0])
                if resolved is not None:
                    tool_to_groups.setdefault(stmt.name, set()).add(resolved)
    return tool_to_groups


def _groups_for_profile(profile: str, groups_by_profile: dict[str, list[str]]) -> set[str]:
    """Resolve which group keys are active for the given profile."""
    return set(groups_by_profile[profile])


def _capture(profile: str, tool_to_groups: dict[str, set[str]], groups_by_profile: dict[str, list[str]]) -> list[str]:
    """Pick tool names whose group(s) intersect the active profile.

    A tool with any always-on decorator (``__always_on__``) is included
    at every profile. Other tools are included iff at least one of
    their decorator groups is active for the profile.
    """
    active = _groups_for_profile(profile, groups_by_profile)
    always_on = active | {"__always_on__"}
    selected = [
        name
        for name, groups in tool_to_groups.items()
        if groups & always_on
    ]
    return sorted(selected)


def _load_groups_by_profile() -> dict[str, list[str]]:
    """Read the dhara profile → groups map directly from profiles.py."""
    from dhara.mcp.profiles import TOOL_GROUPS_BY_PROFILE, ToolProfile

    return {
        profile.value: list(groups)
        for profile, groups in TOOL_GROUPS_BY_PROFILE.items()
    }


def main(profiles: list[str]) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    tool_to_groups = _parse_tool_decorators()
    groups_by_profile = _load_groups_by_profile()

    for profile in profiles:
        out_dir = FIXTURES / profile
        out_dir.mkdir(parents=True, exist_ok=True)
        names = _capture(profile, tool_to_groups, groups_by_profile)
        (out_dir / "tool_names.json").write_text(json.dumps(names, indent=2) + "\n")
        print(f"{profile}: {len(names)} tools captured -> {out_dir}/tool_names.json")


if __name__ == "__main__":
    requested = sys.argv[1:] or ["minimal", "standard", "full"]
    main(requested)

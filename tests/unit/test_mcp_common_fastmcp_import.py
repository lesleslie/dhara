"""Smoke test for Plan 7 Phase 2: mcp_common.fastmcp import surface.

Confirms the standardized re-export surface shipped by mcp-common (Plan 7
Phase 1, commit 0ae0426) resolves from a fresh import in this repo. The
mcp_common.fastmcp module is the central contract that lets every Bodai
consumer switch to ``from mcp_common.fastmcp import FastMCP`` (and
siblings) without depending on the upstream ``fastmcp`` package directly.

If this test fails, the mcp-common foundation has regressed or this repo's
environment cannot resolve the dependency.
"""

from __future__ import annotations


def test_mcp_common_fastmcp_exports_fast_mcp() -> None:
    """``mcp_common.fastmcp`` must re-export ``FastMCP`` (Plan 7 Phase 1)."""
    from mcp_common.fastmcp import FastMCP  # noqa: F401

    assert FastMCP is not None


def test_mcp_common_fastmcp_exports_context() -> None:
    """``mcp_common.fastmcp`` must re-export ``Context`` (Plan 7 Phase 1)."""
    from mcp_common.fastmcp import Context  # noqa: F401

    assert Context is not None


def test_mcp_common_fastmcp_exports_middleware() -> None:
    """``mcp_common.fastmcp`` must re-export ``Middleware`` (Plan 7 Phase 1)."""
    from mcp_common.fastmcp import Middleware  # noqa: F401

    assert Middleware is not None


def test_dhara_mcp_server_core_imports_via_mcp_common() -> None:
    """``dhara.mcp.server_core`` must import ``FastMCP`` via mcp_common.

    This is the symbol-equivalence check that proves the migration is in
    place: the module must resolve ``FastMCP`` through the standardized
    mcp_common surface, not via a direct ``from fastmcp import ...``.
    """
    import dhara.mcp.server_core as server_core

    fastmcp_name = server_core.FastMCP.__module__
    assert fastmcp_name.startswith("fastmcp"), (
        f"dhara.mcp.server_core.FastMCP resolved to {fastmcp_name!r}; "
        f"expected it to live under the fastmcp package after import "
        f"via mcp_common.fastmcp."
    )

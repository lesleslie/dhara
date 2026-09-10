"""Dhara MCP tool modules.

Each submodule defines plain async functions that act as the canonical
MCP tool implementations. ``DharaMCPServer._register_tools`` wraps these
with the FastMCP ``@server.tool()`` decorator and ``auth=`` scope, so
direct import (e.g. ``from dhara.mcp.tools import sql_proxy``) gives
callers the same async function used by the FastMCP runtime.

The ``register_agent_registry`` function (Phase 3) is also re-exported
so callers can wire the ``list_agents`` / ``get_agent`` MCP tools via
the FastMCP server directly without going through the per-group
wrapper layer.
"""

from __future__ import annotations

from dhara.mcp.tools import sql_proxy
from dhara.mcp.tools.agent_registry import register_agent_registry

__all__ = ["register_agent_registry", "sql_proxy"]
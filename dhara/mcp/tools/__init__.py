"""Dhara MCP tool modules.

Each submodule defines plain async functions that act as the canonical
MCP tool implementations. ``DharaMCPServer._register_tools`` wraps these
with the FastMCP ``@server.tool()`` decorator and ``auth=`` scope, so
direct import (e.g. ``from dhara.mcp.tools import sql_proxy``) gives
callers the same async function used by the FastMCP runtime.
"""

from __future__ import annotations

from dhara.mcp.tools import sql_proxy

__all__ = ["sql_proxy"]

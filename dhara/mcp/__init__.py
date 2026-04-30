"""
Dhara MCP (Model Context Protocol) Server Package

This package provides MCP server implementations for Dhara with integrated
compatibility authentication helpers.

Components:
- auth: Authentication and authorization (delegated to mcp_common.auth)
- server_core: Canonical FastMCP server implementation
- server: Compatibility wrapper for legacy imports
"""

from dhara.mcp.server_core import DharaMCPServer, DruvaMCPServer

__all__ = [
    "DharaMCPServer",
    "DruvaMCPServer",
]

__version__ = "5.0.0"

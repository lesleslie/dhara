"""
Dhara MCP (Model Context Protocol) Server Package

This package provides MCP server implementations for Dhara with integrated
compatibility authentication helpers.

Components:
- auth: Authentication and authorization helper classes
- server_core: Canonical FastMCP server implementation
- server: Compatibility wrapper for legacy imports
- oneiric_server: Legacy custom server path retained for compatibility
"""

from dhara.mcp.auth import (
    AuthContext,
    AuthMiddleware,
    AuthResult,
    EnvironmentAuth,
    HMACAuth,
    Permission,
    TokenAuth,
)
from dhara.mcp.server_core import DharaMCPServer, DruvaMCPServer

__all__ = [
    "DharaMCPServer",
    "DruvaMCPServer",
    "AuthMiddleware",
    "TokenAuth",
    "HMACAuth",
    "EnvironmentAuth",
    "AuthResult",
    "AuthContext",
    "Permission",
]

__version__ = "5.0.0"

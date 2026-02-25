"""
Durus MCP (Model Context Protocol) Server Package

This package provides MCP server implementations for Durus with integrated
authentication and authorization.

Components:
- auth: Authentication and authorization classes
- server: Main Durus MCP server
- oneiric_server: Oneiric-compatible MCP server
"""

from druva.mcp.auth import (
    AuthMiddleware,
    TokenAuth,
    HMACAuth,
    EnvironmentAuth,
    AuthResult,
    AuthContext,
    Permission,
)

__all__ = [
    "AuthMiddleware",
    "TokenAuth",
    "HMACAuth",
    "EnvironmentAuth",
    "AuthResult",
    "AuthContext",
    "Permission",
]

__version__ = "5.0.0"

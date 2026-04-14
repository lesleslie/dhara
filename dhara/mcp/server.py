"""Legacy compatibility wrapper for the canonical Dhara FastMCP server.

`dhara.mcp.server_core` contains the supported implementation. This module
remains only to preserve older import paths while the ecosystem finishes the
rename from Druva/Durus to Dhara.
"""

from __future__ import annotations

from typing import Any
import warnings

from dhara.core.config import DharaSettings
from dhara.mcp.server_core import DharaMCPServer, DruvaMCPServer

warnings.warn(
    "dhara.mcp.server is deprecated; use dhara.mcp.server_core or dhara.mcp instead.",
    DeprecationWarning,
    stacklevel=2,
)


def create_server_from_config(config: dict[str, Any]) -> DharaMCPServer:
    """Create the canonical Dhara MCP server from a config dictionary."""
    settings = DharaSettings.model_validate(config)
    return DharaMCPServer(settings)


__all__ = ["DharaMCPServer", "DruvaMCPServer", "create_server_from_config"]

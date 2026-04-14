#!/usr/bin/env python
"""Dhara MCP Server entry point.

Run with: python -m dhara.mcp
"""

from dhara.core.config import DharaSettings
from dhara.mcp.server_core import DharaMCPServer


def main() -> None:
    """Start the Dhara MCP server."""
    # Load settings from YAML config file (settings/dhara.yaml)
    config = DharaSettings.load()
    server = DharaMCPServer(config)
    server.run()


if __name__ == "__main__":
    main()

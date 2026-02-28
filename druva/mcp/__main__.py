#!/usr/bin/env python
"""Druva MCP Server entry point.

Run with: python -m druva.mcp
"""

from druva.core.config import DruvaSettings
from druva.mcp.server_core import DruvaMCPServer


def main() -> None:
    """Start the Druva MCP server."""
    # Load settings from YAML config file (settings/druva.yaml)
    config = DruvaSettings.load()
    server = DruvaMCPServer(config)
    server.run()


if __name__ == "__main__":
    main()

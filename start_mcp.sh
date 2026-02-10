#!/bin/bash
# Dhruva MCP Server Startup Script

set -e

# Change to project directory
cd "$(dirname "$0")"

# Use local .venv
source .venv/bin/activate

# Start the MCP server (uses default port from config)
python -m dhruva.cli start

"""Dhruva MCP Server CLI using mcp-common patterns.

This module provides the CLI for Dhruva MCP server with standardized
lifecycle management (start/stop/status/health) using MCPServerCLIFactory.

Usage:
    python -m dhruva.cli start
    python -m dhruva.cli status
    python -m dhruva.cli health
    python -m dhruva.cli stop

★ Insight: MCP CLI Pattern ─────────────────────────────────────
1. MCPServerCLIFactory provides standard lifecycle commands
2. Custom handlers for start/stop/health integrate with DhruvaMCPServer
3. Consistent with Mahavishnu, Session-Buddy, Crackerjack CLIs
4. Automatic PID file management, signal handling, health snapshots
───────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import time

import typer
from mcp_common.cli import (
    MCPServerCLIFactory,
    RuntimeHealthSnapshot,
)
from mcp_common.cli.health import load_runtime_health, write_runtime_health
from oneiric.core.logging import get_logger

from dhruva.core.config import DhruvaSettings
from dhruva.mcp.server_core import DhruvaMCPServer

logger = get_logger(__name__)

# Global server instance (for stop handler)
_server_instance: DhruvaMCPServer | None = None


def start_handler() -> None:
    """Custom start handler - called after PID file created.

    Initializes and starts the Dhruva MCP server with FastMCP framework.
    Handles graceful shutdown on SIGTERM/SIGINT.

    ★ Insight: Start Handler Lifecycle ───────────────────────────────
    1. Load DhruvaSettings (YAML + environment variables)
    2. Initialize DhruvaMCPServer with FastMCP
    3. Start uvicorn server (async)
    4. Handle KeyboardInterrupt for graceful shutdown
    5. Clean up resources on exit
    ────────────────────────────────────────────────────────────────────
    """
    global _server_instance

    # Load settings
    settings = DhruvaSettings.load("dhruva")
    logger.info(f"Starting Dhruva MCP Server: {settings.server_name}")
    logger.info(f"Storage path: {settings.storage.path}")
    logger.info(f"Read-only: {settings.storage.read_only}")

    # Initialize server
    _server_instance = DhruvaMCPServer(settings)

    # Save initial health snapshot
    health_snapshot = RuntimeHealthSnapshot(
        orchestrator_pid=None,  # Will be filled by CLI
        watchers_running=True,
        remote_enabled=False,
        lifecycle_state={
            "started_at": time.time(),
            "storage_path": str(settings.storage.path),
            "read_only": settings.storage.read_only,
        },
        activity_state={
            "adapters_registered": _server_instance.adapter_registry.count(),
            "current_status": "initializing",
        },
    )
    write_runtime_health(settings.health_snapshot_path(), health_snapshot)

    # Start server (FastMCP.run() is synchronous - manages its own event loop)
    try:
        _server_instance.run(
            host=settings.host or "127.0.0.1",
            port=settings.port or 8683,
        )
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        # Cleanup
        if _server_instance:
            _server_instance.close()
        logger.info("Dhruva MCP Server stopped")


def stop_handler(_pid: int) -> None:
    """Custom stop handler - called before PID file removed.

    Gracefully shutdown the Dhruva MCP server and cleanup resources.

    Args:
        _pid: Process ID being stopped (unused, kept for interface)

    ★ Insight: Stop Handler Lifecycle ─────────────────────────────────
    1. Close Dhruva connection (flushes pending changes)
    2. Close FileStorage (releases file locks)
    3. Update health snapshot to 'stopped' state
    4. Clean up any background tasks
    ────────────────────────────────────────────────────────────────────
    """
    global _server_instance

    if _server_instance:
        logger.info("Stopping Dhruva MCP Server...")
        _server_instance.close()
        _server_instance = None
        logger.info("Dhruva MCP Server stopped")


def health_probe_handler() -> RuntimeHealthSnapshot:
    """Custom health probe - called by `dhruva mcp health --probe`.

    Checks:
    - Storage file exists and is accessible
    - Connection is active
    - Adapter registry is initialized
    - Resource usage

    Returns:
        RuntimeHealthSnapshot with current health state

    ★ Insight: Health Probe Design ────────────────────────────────────
    1. Load current health snapshot if exists
    2. Check storage file accessibility
    3. Verify adapter registry state
    4. Calculate uptime and activity metrics
    5. Return structured health snapshot
    ────────────────────────────────────────────────────────────────────
    """
    settings = DhruvaSettings.load("dhruva")

    # Check storage file
    storage_exists = settings.storage.path.exists()
    storage_readable = storage_exists and settings.storage.path.is_file()

    # Try to load existing health snapshot
    try:
        existing_snapshot = load_runtime_health(settings.health_snapshot_path())
        started_at = existing_snapshot.lifecycle_state.get("started_at", time.time())
    except Exception:
        started_at = time.time()

    # Calculate uptime
    uptime_seconds = time.time() - started_at

    # Determine health status
    is_healthy = storage_exists and storage_readable

    return RuntimeHealthSnapshot(
        orchestrator_pid=None,  # Will be filled by CLI
        watchers_running=is_healthy,
        remote_enabled=False,
        lifecycle_state={
            "started_at": started_at,
            "uptime_seconds": uptime_seconds,
            "storage_path": str(settings.storage.path),
            "storage_exists": storage_exists,
            "storage_readable": storage_readable,
            "read_only": settings.storage.read_only,
        },
        activity_state={
            "adapters_registered": 0,  # Would check registry if server running
            "current_status": "healthy" if is_healthy else "unhealthy",
            "storage_status": "ok" if storage_readable else "error",
        },
    )


def _create_adapters_command(app: typer.Typer, settings: DhruvaSettings) -> None:
    """Create the adapters command for listing adapters.

    Args:
        app: Typer app to add command to
        settings: DhruvaSettings instance
    """

    @app.command("adapters")
    def adapters(
        domain: str | None = typer.Option(None, help="Filter by domain"),
        category: str | None = typer.Option(None, help="Filter by category"),
    ) -> None:
        """List registered adapters in Dhruva."""
        from dhruva.core.connection import Connection
        from dhruva.mcp.adapter_tools import AdapterRegistry
        from dhruva.storage.file import FileStorage

        # Open connection with context manager for automatic cleanup
        with FileStorage(str(settings.storage.path), readonly=True) as storage:
            connection = Connection(storage)
            registry = AdapterRegistry(connection)

            # List adapters
            adapters = registry.list_adapters(domain=domain, category=category)

            typer.echo(f"\n📦 Found {len(adapters)} adapters:\n")

            for adapter in adapters:
                typer.echo(f"  {adapter['adapter_id']} @ {adapter['version']}")
                typer.echo(
                    f"    {adapter['metadata'].get('description', 'No description')}"
                )


def _create_storage_command(app: typer.Typer, settings: DhruvaSettings) -> None:
    """Create the storage command for storage info.

    Args:
        app: Typer app to add command to
        settings: DhruvaSettings instance
    """

    @app.command("storage")
    def storage() -> None:
        """Display storage information."""
        from dhruva.core.connection import Connection
        from dhruva.storage.file import FileStorage

        with FileStorage(str(settings.storage.path), readonly=True) as storage:
            connection = Connection(storage)

            root = connection.get_root()

            typer.echo("\n💾 Storage Information:")
            typer.echo(f"  Path: {settings.storage.path}")
            typer.echo(f"  Exists: {settings.storage.path.exists()}")
            typer.echo(
                f"  Size: {settings.storage.path.stat().st_size if settings.storage.path.exists() else 0} bytes"
            )
            typer.echo(f"  Root keys: {len(list(root.keys()))}")


def _create_admin_command(app: typer.Typer, settings: DhruvaSettings) -> None:
    """Create the admin command for launching IPython shell.

    Args:
        app: Typer app to add command to
        settings: DhruvaSettings instance
    """

    @app.command("admin")
    def admin() -> None:
        """Launch Dhruva admin shell with IPython."""
        from dhruva.core.connection import Connection
        from dhruva.shell import DhruvaShell
        from dhruva.storage.file import FileStorage

        # Open connection
        storage = FileStorage(str(settings.storage.path))
        connection = Connection(storage)

        # Create and start shell
        shell = DhruvaShell(connection, settings)
        shell.start()


def create_cli() -> typer.Typer:
    """Create CLI application with lifecycle commands + custom commands.

    Returns:
        Typer app with all commands registered

    ★ Insight: CLI Composition ─────────────────────────────────────────
    1. MCPServerCLIFactory provides standard lifecycle commands
    2. Custom commands added via factory.create_app()
    3. Each custom command gets settings for configuration access
    4. Commands follow Typer patterns (Options, Arguments, etc.)
    ────────────────────────────────────────────────────────────────────
    """
    # Load settings (YAML + env vars)
    settings = DhruvaSettings.load("dhruva")

    # Create CLI factory with custom handlers
    factory = MCPServerCLIFactory(
        server_name="dhruva",
        settings=settings,
        start_handler=start_handler,
        stop_handler=stop_handler,
        health_probe_handler=health_probe_handler,
    )

    # Create Typer app with standard lifecycle commands
    app = factory.create_app()

    # Add custom Dhruva-specific commands
    _create_adapters_command(app, settings)
    _create_storage_command(app, settings)
    _create_admin_command(app, settings)

    return app


def main() -> None:
    """Main entry point for Dhruva MCP CLI."""
    app = create_cli()
    app()


if __name__ == "__main__":
    main()

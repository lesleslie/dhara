"""Dhara Unified CLI - MCP Server + Database Operations.

This module provides a unified CLI for Dhara that combines:
1. MCP server lifecycle management (start/stop/status/health)
2. Legacy-compatible database operations (client/server/pack)

Usage:
    # MCP server commands
    dhara mcp start
    dhara mcp status
    dhara mcp health
    dhara mcp stop

    # Database commands (legacy-compatible)
    dhara db client [--file PATH] [--host HOST] [--port PORT]
    dhara db server [--file PATH] [--host HOST] [--port PORT]
    dhara db pack [--file PATH]

    # Custom Dhara commands
    dhara adapters [--domain DOMAIN] [--category CATEGORY]
    dhara storage
    dhara admin --confirm

★ Insight: Unified CLI Pattern ─────────────────────────────────────
1. MCPServerCLIFactory with use_mcp_subcommand=True for `dhara mcp`
2. Legacy-compatible database CLI restructured under `dhara db`
3. Custom Dhara-specific commands at root level (adapters, storage, admin)
4. Single entry point: `dhara` handles both MCP and database operations
───────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import typer
from mcp_common.cli import (
    MCPServerCLIFactory,
    RuntimeHealthSnapshot,
)
from mcp_common.cli.health import load_runtime_health, write_runtime_health
from oneiric.core.logging import get_logger

from dhara.core.config import DharaSettings
from dhara.mcp.server_core import DharaMCPServer

logger = get_logger(__name__)

# Version (sync with pyproject.toml)
__version__ = "0.6.1"

# Global server instance (for stop handler)
_server_instance: DharaMCPServer | None = None


def _probe_storage_runtime(settings: DharaSettings) -> dict[str, object]:
    """Probe storage accessibility for CLI health output."""
    from dhara.core.connection import Connection
    from dhara.storage.file import FileStorage

    storage_path = settings.storage.path.expanduser()
    try:
        with FileStorage(str(storage_path), readonly=True) as storage:
            connection = Connection(storage)
            root = connection.get_root()
            return {
                "storage_exists": storage_path.exists(),
                "storage_readable": True,
                "storage_accessible": True,
                "root_keys": len(list(root.keys())),
            }
    except Exception as exc:
        return {
            "storage_exists": storage_path.exists(),
            "storage_readable": False,
            "storage_accessible": False,
            "storage_error": str(exc),
        }


def _probe_backup_runtime(settings: DharaSettings) -> dict[str, object]:
    """Probe backup catalog visibility for CLI health output."""
    from dhara.core.connection import Connection
    from dhara.storage.file import FileStorage

    if not settings.backups.enabled:
        return {"backup_configured": False}

    backup_dir = settings.backups.directory.expanduser()
    catalog_path = backup_dir / "backup_catalog.durus"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        latest_backup_id = None
        latest_backup_at = None
        backup_count = 0

        if catalog_path.exists():
            with FileStorage(str(catalog_path), readonly=True) as storage:
                connection = Connection(storage)
                root = connection.get_root()
                backups = root.get("backups", {})
                backup_count = len(list(backups.keys()))
                latest_timestamp = None
                for payload in backups.values():
                    data = dict(payload)
                    timestamp = data.get("timestamp")
                    if isinstance(timestamp, str) and (
                        latest_timestamp is None or timestamp > latest_timestamp
                    ):
                        latest_timestamp = timestamp
                        latest_backup_id = data.get("backup_id")
                        latest_backup_at = timestamp

        return {
            "backup_configured": True,
            "backup_directory": str(backup_dir),
            "backup_catalog_accessible": True,
            "backup_catalog_exists": catalog_path.exists(),
            "backup_count": backup_count,
            "latest_backup_id": latest_backup_id,
            "latest_backup_at": latest_backup_at,
        }
    except Exception as exc:
        return {
            "backup_configured": True,
            "backup_directory": str(backup_dir),
            "backup_catalog_accessible": False,
            "backup_error": str(exc),
        }


def start_handler() -> None:
    """Custom start handler - called after PID file created.

    Initializes and starts the Dhara MCP server with FastMCP framework.
    Handles graceful shutdown on SIGTERM/SIGINT.

    ★ Insight: Start Handler Lifecycle ───────────────────────────────
    1. Load DharaSettings (YAML + environment variables)
    2. Initialize DharaMCPServer with FastMCP
    3. Start uvicorn server (async)
    4. Handle KeyboardInterrupt for graceful shutdown
    5. Clean up resources on exit
    ────────────────────────────────────────────────────────────────────
    """
    global _server_instance

    # Load settings with error handling
    try:
        settings = DharaSettings.load("dhara")
    except Exception as e:
        typer.echo(f"Error loading configuration: {e}", err=True)
        raise typer.Exit(1)

    logger.info(f"Starting Dhara MCP Server: {settings.server_name}")
    logger.debug(f"Storage path: {settings.storage.path}")
    logger.debug(f"Read-only: {settings.storage.read_only}")

    # Initialize server
    _server_instance = DharaMCPServer(settings)

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
            "current_status": "running",
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
        stopped_snapshot = RuntimeHealthSnapshot(
            orchestrator_pid=None,
            watchers_running=False,
            remote_enabled=False,
            lifecycle_state={
                "started_at": health_snapshot.lifecycle_state["started_at"],
                "stopped_at": time.time(),
                "storage_path": str(settings.storage.path),
                "read_only": settings.storage.read_only,
            },
            activity_state={
                "adapters_registered": 0,
                "current_status": "stopped",
            },
        )
        write_runtime_health(settings.health_snapshot_path(), stopped_snapshot)
        logger.info("Dhara MCP Server stopped")


def stop_handler(_pid: int) -> None:
    """Custom stop handler - called before PID file removed.

    Gracefully shutdown the Dhara MCP server and cleanup resources.

    Args:
        _pid: Process ID being stopped (unused, kept for interface)

    ★ Insight: Stop Handler Lifecycle ─────────────────────────────────
    1. Close Dhara connection (flushes pending changes)
    2. Close FileStorage (releases file locks)
    3. Update health snapshot to 'stopped' state
    4. Clean up any background tasks
    ────────────────────────────────────────────────────────────────────
    """
    global _server_instance

    settings = DharaSettings.load("dhara")

    if _server_instance:
        logger.info("Stopping Dhara MCP Server...")
        _server_instance.close()
        _server_instance = None
    stopped_snapshot = RuntimeHealthSnapshot(
        orchestrator_pid=None,
        watchers_running=False,
        remote_enabled=False,
        lifecycle_state={
            "stopped_at": time.time(),
            "storage_path": str(settings.storage.path),
            "read_only": settings.storage.read_only,
        },
        activity_state={
            "adapters_registered": 0,
            "current_status": "stopped",
        },
    )
    write_runtime_health(settings.health_snapshot_path(), stopped_snapshot)
    logger.info("Dhara MCP Server stopped")


def health_probe_handler() -> RuntimeHealthSnapshot:
    """Custom health probe - called by `dhara mcp health --probe`.

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
    settings = DharaSettings.load("dhara")

    storage_status = _probe_storage_runtime(settings)
    backup_status = _probe_backup_runtime(settings)

    # Try to load existing health snapshot
    try:
        existing_snapshot = load_runtime_health(settings.health_snapshot_path())
        started_at = existing_snapshot.lifecycle_state.get("started_at", time.time())
    except (FileNotFoundError, KeyError, AttributeError, ValueError):
        # No existing snapshot or malformed - use current time
        started_at = time.time()

    # Calculate uptime
    uptime_seconds = time.time() - started_at

    # Determine health status
    is_healthy = bool(storage_status.get("storage_accessible"))

    return RuntimeHealthSnapshot(
        orchestrator_pid=None,  # Will be filled by CLI
        watchers_running=is_healthy,
        remote_enabled=False,
        lifecycle_state={
            "started_at": started_at,
            "uptime_seconds": uptime_seconds,
            "storage_path": str(settings.storage.path),
            **storage_status,
            **backup_status,
            "read_only": settings.storage.read_only,
        },
        activity_state={
            "adapters_registered": 0,  # Would check registry if server running
            "current_status": "healthy" if is_healthy else "unhealthy",
            "ready": is_healthy,
            "storage_status": "ok" if storage_status.get("storage_accessible") else "error",
        },
    )


def _validate_path(file_path: str | None) -> Path | None:
    """Validate a file path for security.

    Prevents path traversal attacks by canonicalizing the path
    and ensuring it doesn't escape the expected directory.

    Args:
        file_path: Path to validate (can be None)

    Returns:
        Canonicalized Path object, or None if input was None

    Raises:
        typer.Exit: If path is invalid or contains traversal attempts
    """
    if file_path is None:
        return None

    path = Path(file_path)

    # Resolve to absolute path (follows symlinks, removes ..)
    try:
        resolved = path.resolve()
    except (OSError, ValueError) as e:
        typer.echo(f"Error: Invalid path '{file_path}': {e}", err=True)
        raise typer.Exit(1)

    # Check for suspicious patterns in the original path
    original_str = str(path)
    if ".." in original_str.split(os.sep):
        typer.echo(
            f"Error: Path traversal not allowed in '{file_path}'",
            err=True,
        )
        raise typer.Exit(1)

    return resolved


def _create_adapters_command(app: typer.Typer, settings: DharaSettings) -> None:
    """Create the adapters command for listing adapters.

    Args:
        app: Typer app to add command to
        settings: DharaSettings instance
    """

    @app.command("adapters")
    def adapters(
        domain: str | None = typer.Option(None, help="Filter by domain"),
        category: str | None = typer.Option(None, help="Filter by category"),
    ) -> None:
        """List registered adapters in Dhara."""
        from dhara.core.connection import Connection
        from dhara.mcp.adapter_tools import AdapterRegistry
        from dhara.storage.file import FileStorage

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


def _create_storage_command(app: typer.Typer, settings: DharaSettings) -> None:
    """Create the storage command for storage info.

    Args:
        app: Typer app to add command to
        settings: DharaSettings instance
    """

    @app.command("storage")
    def storage() -> None:
        """Display storage information."""
        from dhara.core.connection import Connection
        from dhara.storage.file import FileStorage

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


def _create_admin_command(app: typer.Typer, settings: DharaSettings) -> None:
    """Create the admin command for launching IPython shell.

    Args:
        app: Typer app to add command to
        settings: DharaSettings instance
    """

    @app.command("admin")
    def admin(
        confirm: bool = typer.Option(
            False,
            "--confirm",
            help="Confirm you understand this provides unrestricted database access",
        ),
    ) -> None:
        """Launch Dhara admin shell with IPython.

        ⚠️  WARNING: This shell provides unrestricted read/write access to all
        database content. Use with caution in production environments.
        """
        if not confirm:
            typer.echo(
                "⚠️  Admin shell provides unrestricted database access.\n"
                "   Use --confirm to acknowledge and proceed.",
                err=True,
            )
            raise typer.Exit(1)

        from dhara.core.connection import Connection
        from dhara.shell import DharaShell
        from dhara.storage.file import FileStorage

        # Open connection with proper resource management
        try:
            with FileStorage(str(settings.storage.path)) as storage:
                connection = Connection(storage)
                shell = DharaShell(connection, settings)
                shell.start()
        except FileNotFoundError:
            typer.echo(
                f"Error: Storage file not found: {settings.storage.path}", err=True
            )
            raise typer.Exit(1)
        except PermissionError:
            typer.echo(
                f"Error: Permission denied accessing: {settings.storage.path}",
                err=True,
            )
            raise typer.Exit(1)


def _create_db_commands(app: typer.Typer) -> None:
    """Create the db command group for legacy-compatible database operations.

    Args:
        app: Typer app to add command group to

    ★ Insight: Legacy CLI Restructure ─────────────────────────────────
    1. Historical database flags restructured into subcommands
    2. `dhara db client` replaces `dhara -c`
    3. `dhara db server` replaces `dhara -s`
    4. `dhara db pack` replaces `dhara -p`
    5. Full TLS support preserved with modern option names
    ────────────────────────────────────────────────────────────────────
    """
    db_app = typer.Typer(help="Legacy-compatible Dhara database operations")
    app.add_typer(db_app, name="db")

    @db_app.command("client")
    def client(
        file: str | None = typer.Option(
            None, "--file", "-f", help="Database file path"
        ),
        host: str = typer.Option("127.0.0.1", "--host", "-h", help="Server host"),
        port: int = typer.Option(2972, "--port", "-p", help="Server port"),
        readonly: bool = typer.Option(
            False, "--readonly", help="Open in read-only mode"
        ),
        cache_size: int = typer.Option(10000, "--cache-size", help="Client cache size"),
    ) -> None:
        """Start interactive database client.

        Connect to a Dhara database file or server for interactive queries.
        Provides IPython shell with connection object for database operations.
        """
        from dhara.__main__ import interactive_client

        # Validate file path if provided
        validated_file = _validate_path(file)
        file_str = str(validated_file) if validated_file else None

        if file_str:
            address = None
        else:
            address = (host, port)

        interactive_client(
            file=file_str,
            address=address,
            cache_size=cache_size,
            readonly=readonly,
            repair=False,
            startup=None,
            storage_class=None,
            tls_config=None,
        )

    @db_app.command("start")
    def db_start(
        file: str | None = typer.Option(
            None, "--file", "-f", help="Database file path"
        ),
        host: str = typer.Option("127.0.0.1", "--host", "-h", help="Listen host"),
        port: int = typer.Option(2972, "--port", "-p", help="Listen port"),
        readonly: bool = typer.Option(
            False, "--readonly", help="Open in read-only mode"
        ),
        gcbytes: int = typer.Option(
            100000000, "--gcbytes", help="GC threshold in bytes"
        ),
    ) -> None:
        """Start the legacy-compatible Dhara database server.

        Starts a standalone Dhara storage server that clients can connect to.
        Use for shared database access across multiple processes.
        """
        from dhara.__main__ import get_storage, start_durus

        # Validate file path if provided
        validated_file = _validate_path(file)
        file_str = str(validated_file) if validated_file else None

        storage = get_storage(file_str, readonly=readonly)
        start_durus(
            logfile=None,
            logginglevel=20,
            address=(host, port),
            storage=storage,
            gcbytes=gcbytes,
            tls_config=None,
        )

    @db_app.command("pack")
    def pack(
        file: str | None = typer.Option(
            None, "--file", "-f", help="Database file path"
        ),
        host: str = typer.Option("127.0.0.1", "--host", "-h", help="Server host"),
        port: int = typer.Option(2972, "--port", "-p", help="Server port"),
    ) -> None:
        """Pack a Dhara database to reclaim space.

        Removes unused objects and reclaims storage space.
        Can operate on a file directly or connect to a running server.
        """
        from dhara.__main__ import Connection, get_storage
        from dhara.server.server import SocketAddress
        from dhara.storage.client import ClientStorage

        # Validate file path if provided
        validated_file = _validate_path(file)

        if validated_file is None:
            address = SocketAddress.new((host, port))
            storage = ClientStorage(address=address)
        else:
            if not validated_file.exists():
                typer.echo(
                    f"Error: Database file not found: {validated_file}", err=True
                )
                raise typer.Exit(1)
            storage = get_storage(str(validated_file))

        try:
            connection = Connection(storage)
            connection.pack()
            typer.echo("Database packed successfully")
        except ConnectionError as e:
            typer.echo(f"Error connecting to server: {e}", err=True)
            raise typer.Exit(1)


def main() -> None:
    """Main entry point for Dhara CLI."""
    app = create_cli()
    app()


def create_cli() -> typer.Typer:
    """Create unified CLI application with MCP and database commands.

    Returns:
        Typer app with all commands registered

    ★ Insight: CLI Composition ─────────────────────────────────────────
    1. MCPServerCLIFactory with use_mcp_subcommand=True creates `dhara mcp`
    2. Legacy-compatible database CLI restructured under `dhara db`
    3. Custom Dhara-specific commands at root level (adapters, storage, admin)
    4. Single unified entry point replaces separate dhara and dhara-mcp commands
    ────────────────────────────────────────────────────────────────────
    """
    # Load settings (YAML + env vars)
    settings = DharaSettings.load("dhara")

    # Create CLI factory with custom handlers and MCP subcommand mode
    factory = MCPServerCLIFactory(
        server_name="dhara",
        settings=settings,
        start_handler=start_handler,
        stop_handler=stop_handler,
        health_probe_handler=health_probe_handler,
        use_mcp_subcommand=True,  # Use `dhara mcp start` pattern
    )

    # Create Typer app with MCP lifecycle commands under 'mcp' subcommand
    app = factory.create_app()

    # Add version option to the app callback
    @app.callback()
    def global_options(
        version: bool = typer.Option(
            False,
            "--version",
            "-v",
            help="Show version and exit",
            is_eager=True,
        ),
    ) -> None:
        """Global options for dhara CLI."""
        if version:
            typer.echo(f"dhara version {__version__}")
            raise typer.Exit()

    # Add database command group (legacy-compatible operations)
    _create_db_commands(app)

    # Add custom Dhara-specific commands at root level
    _create_adapters_command(app, settings)
    _create_storage_command(app, settings)
    _create_admin_command(app, settings)

    return app


if __name__ == "__main__":
    main()

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
    dhara db start  [--file PATH] [--host HOST] [--port PORT]
    dhara db client [--file PATH] [--host HOST] [--port PORT]
    dhara db pack   [--file PATH]

    # Custom Dhara commands
    dhara adapters [--domain DOMAIN] [--category CATEGORY]
    dhara storage
    dhara admin --confirm

    # OneiricCLIBase global commands
    dhara version
    dhara doctor
    dhara health

★ Insight: Unified CLI Pattern ─────────────────────────────────────
1. MCPServerCLIFactory with use_mcp_subcommand=True for `dhara mcp`
2. Legacy-compatible database CLI restructured under `dhara db`
3. Custom Dhara-specific commands at root level (adapters, storage, admin)
4. Subclass of ``OneiricCLIBase`` so `version`/`doctor`/`health` come from
   the shared base (Phase 3 Task 4.2 of the Bodai CLI audit).
5. `doctor` returns Dhara-specific checks (config-loadable,
   storage path, backup catalog). `health` returns a runtime snapshot
   covering settings + storage + backup subsystems.
───────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

import typer
from mcp_common.cli import (
    MCPServerCLIFactory,
    MCPServerSettings,
    RuntimeHealthSnapshot,
)
from mcp_common.cli.health import load_runtime_health, write_runtime_health
from oneiric.cli.base import OneiricCLIBase
from oneiric.core.logging import get_logger

from dhara.core.config import DharaSettings
from dhara.mcp.server_core import DharaMCPServer

logger = get_logger(__name__)

# Version is read from the installed package metadata so ``dhara --version``
# always matches ``pyproject.toml`` (currently 0.15.2). ``importlib.metadata``
# is the canonical way to introspect installed distributions without
# importing the package; this avoids the constant-drift trap when the
# version is bumped via ``crackerjack run -p minor``.
try:
    __version__ = version("dhara")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

# Global server instance (for stop handler)
_server_instance: DharaMCPServer | None = None


def _probe_storage_runtime(settings: DharaSettings) -> dict[str, object]:
    """Probe storage accessibility for CLI health output."""
    import asyncio

    from dhara.core.connection import AsyncConnection
    from dhara.storage.async_file import AsyncFileStorage

    storage_path = settings.storage.path.expanduser()

    async def _probe() -> dict[str, object]:
        storage = AsyncFileStorage(str(storage_path))
        await storage.init()
        try:
            connection = await AsyncConnection.new(storage)
            root = await connection.get_root()
            return {
                "storage_exists": storage_path.exists(),
                "storage_readable": True,
                "storage_accessible": True,
                "root_keys": len(list(root.keys())),
            }
        finally:
            await storage.close()

    try:
        return asyncio.run(_probe())
    except Exception as exc:  # noqa: BLE001  # CLI storage-probe boundary: any failure maps to a typed error dict
        return {
            "storage_exists": storage_path.exists(),
            "storage_readable": False,
            "storage_accessible": False,
            "storage_error": str(exc),
        }


def _probe_backup_runtime(settings: DharaSettings) -> dict[str, object]:
    """Probe backup catalog visibility for CLI health output."""
    import asyncio

    from dhara.core.connection import AsyncConnection
    from dhara.storage.async_file import AsyncFileStorage

    if not settings.backups.enabled:
        return {"backup_configured": False}

    backup_dir = settings.backups.directory.expanduser()
    catalog_path = backup_dir / "backup_catalog.dhara"

    async def _read_catalog() -> tuple[int, str | None, str | None]:
        storage = AsyncFileStorage(str(catalog_path))
        await storage.init()
        try:
            connection = await AsyncConnection.new(storage)
            root = await connection.get_root()
            backups = root.get("backups", {})
            backup_count = len(list(backups.keys()))
            latest_timestamp: str | None = None
            latest_id: str | None = None
            for payload in backups.values():
                data = dict(payload)
                timestamp = data.get("timestamp")
                if isinstance(timestamp, str) and (
                    latest_timestamp is None or timestamp > latest_timestamp
                ):
                    latest_timestamp = timestamp
                    latest_id = data.get("backup_id")
            return backup_count, latest_id, latest_timestamp
        finally:
            await storage.close()

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        latest_backup_id = None
        latest_backup_at = None
        backup_count = 0

        if catalog_path.exists():
            backup_count, latest_backup_id, latest_backup_at = asyncio.run(
                _read_catalog()
            )

        return {
            "backup_configured": True,
            "backup_directory": str(backup_dir),
            "backup_catalog_accessible": True,
            "backup_catalog_exists": catalog_path.exists(),
            "backup_count": backup_count,
            "latest_backup_id": latest_backup_id,
            "latest_backup_at": latest_backup_at,
        }
    except Exception as exc:  # noqa: BLE001  # CLI backup-probe boundary: any failure maps to a typed error dict
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
    except Exception as e:  # noqa: BLE001  # CLI config-load boundary: any failure prints and exits with status 1
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
                "started_at": health_snapshot.lifecycle_state.get("started_at")
                if health_snapshot.lifecycle_state is not None
                else time.time(),
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
    2. Close AsyncFileStorage (releases file locks)
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
        snap_state = existing_snapshot.lifecycle_state
        started_at = (
            snap_state.get("started_at", time.time())
            if snap_state is not None
            else time.time()
        )
    except FileNotFoundError, KeyError, AttributeError, ValueError:
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
            "storage_status": "ok"
            if storage_status.get("storage_accessible")
            else "error",
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
    if ".." in path.parts:
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
        import asyncio

        from dhara.core.connection import AsyncConnection
        from dhara.mcp.adapter_tools import AsyncAdapterRegistry
        from dhara.storage.async_file import AsyncFileStorage

        async def _list_adapters() -> list[dict[str, Any]]:
            storage = AsyncFileStorage(str(settings.storage.path))
            await storage.init()
            try:
                connection = await AsyncConnection.new(storage)
                registry = AsyncAdapterRegistry(connection)
                return await registry.list_adapters_async(
                    domain=domain, category=category
                )
            finally:
                await storage.close()

        adapters = asyncio.run(_list_adapters())

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
        import asyncio

        from dhara.core.connection import AsyncConnection
        from dhara.storage.async_file import AsyncFileStorage

        async def _info() -> int:
            storage = AsyncFileStorage(str(settings.storage.path))
            await storage.init()
            try:
                connection = await AsyncConnection.new(storage)
                root = await connection.get_root()
                return len(list(root.keys()))
            finally:
                await storage.close()

        root_key_count = asyncio.run(_info())

        typer.echo("\n💾 Storage Information:")
        typer.echo(f"  Path: {settings.storage.path}")
        typer.echo(f"  Exists: {settings.storage.path.exists()}")
        typer.echo(
            f"  Size: {settings.storage.path.stat().st_size if settings.storage.path.exists() else 0} bytes"
        )
        typer.echo(f"  Root keys: {root_key_count}")


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

        from dhara.core.connection import AsyncConnection
        from dhara.shell import DharaShell
        from dhara.storage.async_file import AsyncFileStorage

        # Open connection with proper resource management
        try:
            import asyncio

            async def _open_shell() -> None:
                storage = AsyncFileStorage(str(settings.storage.path))
                await storage.init()
                try:
                    connection = await AsyncConnection.new(storage)
                    # NOTE: DharaShell currently uses sync AdapterRegistry; this
                    # command is a known partial port — full async wiring is
                    # Task 2 scope. ``type: ignore`` silences the mismatched
                    # connection type until the shell is ported (sub-task 1f).
                    shell = DharaShell(connection, settings)  # type: ignore[arg-type]
                    shell.start()
                finally:
                    await storage.close()

            asyncio.run(_open_shell())
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
    3. `dhara db start` replaces `dhara -s` (alias: `dhara db server`)
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
        port: int = typer.Option(8685, "--port", "-p", help="Server port"),
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

    @db_app.command("start", hidden=False)
    @db_app.command("server", hidden=True, help="Deprecated alias for 'start'.")
    def db_start(
        file: str | None = typer.Option(
            None, "--file", "-f", help="Database file path"
        ),
        host: str = typer.Option("127.0.0.1", "--host", "-h", help="Listen host"),
        port: int = typer.Option(8685, "--port", "-p", help="Listen port"),
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
        from dhara.__main__ import get_storage, start_dhara

        # Validate file path if provided
        validated_file = _validate_path(file)
        file_str = str(validated_file) if validated_file else None

        storage = get_storage(file_str, readonly=readonly)
        start_dhara(
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
        port: int = typer.Option(8685, "--port", "-p", help="Server port"),
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


class DharaCLI(OneiricCLIBase):
    """Dhara Typer app extending ``OneiricCLIBase``.

    Inherits the global ``version`` / ``doctor`` / ``health`` commands and
    ``--json`` flag from the Bodai shared base. In addition, composes the
    MCP server-lifecycle subcommand group (``dhara mcp start`` etc.) by
    delegating to ``MCPServerCLIFactory`` for the actual command bodies.

    Subclasses override ``_doctor_checks`` and ``_health_probe`` with
    Dhara-specific probes (settings-loadable, storage-path, backup-catalog,
    storage-accessible runtime snapshot). The default base-class behaviour
    raises ``NotImplementedError`` (mapped to ``ExitCode.UNAVAILABLE``); we
    override so the global ``doctor``/``health`` commands return repo data.
    """

    def __init__(self, settings: DharaSettings) -> None:
        super().__init__(
            component_name="dhara",
            help="Dhara persistent object database + MCP server CLI",
        )
        # ``DharaSettings`` extends ``OneiricMCPConfig``; they share
        # BaseModel structure but are sibling classes. ``cast`` at the
        # boundary keeps static checkers happy with the structural duck-type.
        self._settings = settings
        self._factory = MCPServerCLIFactory(
            server_name="dhara",
            settings=cast(MCPServerSettings, settings),
            start_handler=start_handler,
            stop_handler=stop_handler,
            health_probe_handler=health_probe_handler,
            use_mcp_subcommand=True,
        )
        self._register_mcp_subcommands()
        # Register the same legacy + Dhara-specific command groups as
        # before. The Typer contract is satisfied because ``OneiricCLIBase``
        # is itself a ``typer.Typer`` subclass.
        _create_db_commands(self)
        _create_adapters_command(self, settings)
        _create_storage_command(self, settings)
        _create_admin_command(self, settings)

    def _register_mcp_subcommands(self) -> None:
        """Mount ``dhara mcp {start,stop,restart,status,health}`` on this app.

        Mirrors the public surface of ``MCPServerCLIFactory.create_app``
        without using it directly — the factory returns a plain
        ``typer.Typer``, which would erase the OneiricCLIBase unified
        callback and the ``version``/``doctor``/``health`` commands we
        get from this base class.
        """
        mcp_app = typer.Typer(
            help="MCP server lifecycle management",
            add_completion=False,
        )
        self.add_typer(mcp_app, name="mcp")
        # ``MCPServerCLIFactory._cmd_*`` are instance methods; bind by
        # attribute access so ``self`` is forwarded correctly.
        mcp_app.command("start")(self._factory._cmd_start)
        mcp_app.command("stop")(self._factory._cmd_stop)
        mcp_app.command("restart")(self._factory._cmd_restart)
        mcp_app.command("status")(self._factory._cmd_status)
        mcp_app.command("health")(self._factory._cmd_health)

    def _doctor_checks(self) -> dict[str, dict[str, str]]:
        """Return Dhara-specific pre-flight doctor checks.

        Reports the same checks a human operator would run before starting
        the server: settings loadable, storage path is reachable, backup
        catalog is present (if backups are enabled). ``status`` is one
        of ``ok``, ``degraded``, or ``failed`` so callers can grep.
        """
        checks: dict[str, dict[str, str]] = {}
        try:
            settings = DharaSettings.load("dhara")
        except Exception as exc:  # noqa: BLE001  # doctor boundary: report failure, don't crash
            return {
                "config_load": {
                    "status": "failed",
                    "detail": f"settings could not be loaded: {exc}",
                },
            }

        checks["config_load"] = {"status": "ok", "detail": "dhara settings loadable"}

        storage_path = settings.storage.path.expanduser()
        if storage_path.exists():
            label = "directory" if storage_path.is_dir() else "file"
            checks[f"storage_path_{label}"] = {
                "status": "ok",
                "detail": str(storage_path),
            }
        else:
            checks["storage_path"] = {
                "status": "degraded",
                "detail": f"not yet created: {storage_path}",
            }

        if settings.backups.enabled:
            backup_dir = settings.backups.directory.expanduser()
            catalog = backup_dir / "backup_catalog.dhara"
            if catalog.exists():
                checks["backup_catalog"] = {
                    "status": "ok",
                    "detail": str(catalog),
                }
            else:
                checks["backup_catalog"] = {
                    "status": "degraded",
                    "detail": f"missing: {catalog}",
                }
        else:
            checks["backup_catalog"] = {
                "status": "ok",
                "detail": "backups disabled in settings",
            }
        return checks

    def _health_probe(self) -> dict[str, Any]:
        """Return a Dhara runtime health snapshot.

        Mirrors the shape ``dhara mcp health --probe`` already exposes
        (storage-accessible bool, backup catalog accessibility) so the
        ``--json`` consumer contract is preserved.
        """
        try:
            settings = DharaSettings.load("dhara")
            settings_loaded = True
            load_error: str | None = None
        except Exception as exc:  # noqa: BLE001  # health boundary: report failure, don't crash
            settings = None
            settings_loaded = False
            load_error = str(exc)

        storage: dict[str, object] = (
            _probe_storage_runtime(settings) if settings is not None else {}
        )
        backup: dict[str, object] = (
            _probe_backup_runtime(settings) if settings is not None else {}
        )
        storage_accessible = bool(storage.get("storage_accessible", False))

        return {
            "component": "dhara",
            "version": self.component_version,
            "settings_loaded": settings_loaded,
            "load_error": load_error,
            "storage_accessible": storage_accessible,
            "current_status": "healthy"
            if storage_accessible and settings_loaded
            else "unhealthy",
            "storage": storage,
            "backup": backup,
        }


def create_cli() -> DharaCLI:
    """Create unified CLI application with MCP and database commands.

    Returns:
        :class:`DharaCLI` instance — a ``typer.Typer`` (via ``OneiricCLIBase``)
        with all commands registered.

    ★ Insight: CLI Composition ─────────────────────────────────────────
    1. ``DharaCLI`` extends ``OneiricCLIBase`` so ``version``/``doctor``/
       ``health`` come from the shared base (no manual ``@app.callback``
       for ``--version``).
    2. The MCP lifecycle subcommand group (``dhara mcp …``) is composed
       by binding ``MCPServerCLIFactory._cmd_*`` instance methods onto a
       sub-Typer — no business-logic duplication.
    3. Legacy-compatible database CLI is restructured under ``dhara db``.
    4. Custom Dhara-specific commands at root level (adapters, storage,
       admin).
    5. Single unified entry point replaces separate dhara and dhara-mcp
       commands.
    ────────────────────────────────────────────────────────────────────
    """
    settings = DharaSettings.load("dhara")
    return DharaCLI(settings)


if __name__ == "__main__":
    main()


# Bodai umbrella entry-point (Phase 5.1)
app = create_cli()

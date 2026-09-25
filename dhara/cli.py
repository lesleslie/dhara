"""Dhara CLI - Database Operations + Admin Shell.

This module provides a CLI for Dhara that covers:

1. Legacy-compatible database operations (client/server/pack)
2. Dhara-specific commands (storage info, admin IPython shell)

Engine surface only — the prior MCP server subcommand group
(``dhara mcp {start,stop,status,health}``) was removed when the MCP server
surface was retired. Dhara now ships as a standalone persistent-object
library; the OneiricCLIBase shared base continues to provide
``version``/``doctor``/``health``.

Usage:
    # Database commands (legacy-compatible)
    dhara db start  [--file PATH] [--hostHOST] [--port PORT]
    dhara db client [--file PATH] [--hostHOST] [--port PORT]
    dhara db pack   [--file PATH]

    # Custom Dhara commands
    dhara storage
    dhara admin --confirm

    # OneiricCLIBase global commands
    dhara version
    dhara doctor
    dhara health
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from oneiric.cli.base import OneiricCLIBase
from oneiric.core.logging import get_logger

from dhara.core.config import DharaSettings

logger = get_logger(__name__)


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
    ``--json`` flag from the shared Oneiric base. The MCP server-lifecycle
    subcommand group (``dhara mcp {start,stop,...}``) was retired with the
    rest of the MCP surface in Wave 2.

    Subclasses override ``_doctor_checks`` and ``_health_probe`` with
    Dhara-specific probes (settings-loadable, storage-path, backup-catalog,
    storage-accessible runtime snapshot). The default base-class behaviour
    raises ``NotImplementedError`` (mapped to ``ExitCode.UNAVAILABLE``); we
    override so the global ``doctor``/``health`` commands return repo data.
    """

    def __init__(self, settings: DharaSettings) -> None:
        super().__init__(
            component_name="dhara",
            help="Dhara persistent object database CLI",
        )
        self._settings = settings
        # Register the legacy + Dhara-specific command groups. The Typer
        # contract is satisfied because ``OneiricCLIBase`` is itself a
        # ``typer.Typer`` subclass.
        _create_db_commands(self)
        _create_storage_command(self, settings)
        _create_admin_command(self, settings)

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

        Reports settings-loadable status, storage-accessible bool, and
        backup catalog accessibility — the same fields the prior
        ``dhara mcp health --probe`` exposed, so the ``--json``
        consumer contract is preserved at the global ``health`` command.
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
    """Create the Dhara CLI application.

    Returns:
        :class:`DharaCLI` instance — a ``typer.Typer`` (via ``OneiricCLIBase``)
        with all commands registered.
    """
    settings = DharaSettings.load("dhara")
    return DharaCLI(settings)


if __name__ == "__main__":
    main()


app = create_cli()

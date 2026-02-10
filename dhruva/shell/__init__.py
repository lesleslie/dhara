"""Dhruva admin shell.

This module provides Dhruva-specific admin shell functionality extending
the Oneiric ecosystem shell pattern with Dhruva-specific features:

- Adapter registry management
- Storage inspection and manipulation
- Version history tracking
- Health monitoring
- Session tracking via Session-Buddy MCP
"""

from __future__ import annotations

import logging
from typing import Any

from oneiric.shell import AdminShell
from oneiric.shell.config import ShellConfig

logger = logging.getLogger(__name__)


class DhruvaShell(AdminShell):
    """Dhruva-specific admin shell.

    Extends the Oneiric AdminShell with Dhruva-specific namespace,
    formatters, helpers, and magic commands for adapter distribution
    and storage management.

    Features:
    - Adapter registry management
    - Storage inspection and manipulation
    - Version history and rollback
    - Health monitoring
    - Session tracking via Session-Buddy MCP

    Example:
        >>> from dhruva.shell import DhruvaShell
        >>> from dhruva.core.config import DhruvaSettings
        >>> from dhruva.core.connection import Connection
        >>> from dhruva.storage.file_storage import FileStorage
        >>> config = DhruvaSettings.load()
        >>> storage = FileStorage(str(config.storage.path))
        >>> connection = Connection(storage)
        >>> shell = DhruvaShell(connection, config)
        >>> shell.start()
    """

    def __init__(
        self,
        connection: Any,
        config: Any,
        shell_config: ShellConfig | None = None,
    ):
        """Initialize Dhruva shell.

        Args:
            connection: Dhruva Connection instance
            config: DhruvaSettings instance
            shell_config: Optional shell configuration
        """
        self.connection = connection

        # Import AdapterRegistry
        from dhruva.mcp.adapter_tools import AdapterRegistry

        # Initialize adapter registry
        self.registry = AdapterRegistry(connection)

        # Pass config to parent as "app"
        super().__init__(config, shell_config)

        # Add Dhruva-specific namespace
        self._add_dhruva_namespace()

        # Override session tracker with Dhruva-specific metadata
        from .session_tracker import DhruvaSessionTracker

        self.session_tracker = DhruvaSessionTracker(
            component_name="dhruva",
        )
        self._session_id: str | None = None

    def _add_dhruva_namespace(self) -> None:
        """Add Dhruva-specific objects to shell namespace."""
        self.namespace.update(
            {
                # Core objects
                "connection": self.connection,
                "registry": self.registry,
                "config": self.app,
                # Convenience aliases
                "adapters": self.registry,
                "storage": self.connection,
                # Adapter management methods
                "store_adapter": self.registry.store_adapter,
                "get_adapter": self.registry.get_adapter,
                "list_adapters": self.registry.list_adapters,
                "list_versions": self.registry.list_adapter_versions,
                "validate_adapter": self.registry.validate_adapter,
                "check_health": self.registry.check_adapter_health,
                "adapter_count": self.registry.count,
                # Storage helpers
                "root": self.connection.get_root(),
                "commit": self.connection.commit,
                "pack": self.connection.pack,
                # Async helpers
                "push_adapters": lambda: self._push_adapters(),
                "show_storage_info": lambda: self._show_storage_info(),
                "show_adapter_summary": lambda: self._show_adapter_summary(),
            }
        )

    def _get_component_name(self) -> str | None:
        """Return Dhruva component name for session tracking.

        Returns:
            Component name "dhruva" for session tracking
        """
        return "dhruva"

    def _get_component_version(self) -> str:
        """Get Dhruva package version.

        Returns:
            Dhruva version string or "unknown" if unavailable
        """
        try:
            import importlib.metadata as importlib_metadata

            return importlib_metadata.version("dhruva")
        except Exception:
            return "unknown"

    def _get_adapters_info(self) -> list[str]:
        """Get Dhruva adapter information.

        Dhruva stores and distributes adapters, but doesn't use
        the orchestration adapter pattern itself.

        Returns:
            Empty list (Dhruva is curator, not orchestrator)
        """
        return []

    def _get_banner(self) -> str:
        """Get Dhruva-specific banner."""
        version = self._get_component_version()
        adapter_count = self.registry.count()

        return f"""
🦀 Dhruva Admin Shell v{version}
{"=" * 60}
Persistent Object Storage & Adapter Distribution

Session Tracking: Enabled
  Shell sessions tracked via Session-Buddy MCP
  Metadata: version, adapter count, storage state

Dhruva is the curator component providing:
  - Persistent object storage (ACID transactions)
  - Adapter versioning and distribution
  - Health monitoring and rollback
  - Built-in adapter push from Oneiric

Storage Info:
  Adapters Registered: {adapter_count}
  Connection: {"Active" if self.connection else "Inactive"}

Convenience Functions:
  push_adapters()        - Push Oneiric adapters to Dhruva
  show_storage_info()    - Display storage statistics
  show_adapter_summary() - Show adapter distribution summary

Adapter Management:
  store_adapter()        - Store an adapter with versioning
  get_adapter()          - Retrieve adapter by ID
  list_adapters()        - List all adapters
  list_versions()        - List adapter version history
  validate_adapter()     - Validate adapter configuration
  check_health()         - Check adapter health
  adapter_count()        - Count total adapters

Storage Operations:
  root                   - Access root persistent object
  commit()               - Commit pending changes
  pack()                 - Pack storage (reclaim space)

Available Objects:
  connection             - Dhruva Connection instance
  registry/adapters      - AdapterRegistry instance
  config                 - Current DhruvaSettings instance

Type 'help()' for Python help or %help_shell for shell commands
{"=" * 60}
"""

    async def _push_adapters(self) -> None:
        """Push Oneiric built-in adapters to Dhruva.

        Helper function available in shell namespace.
        Imports and calls the Oneiric adapter pusher.
        """
        from rich.console import Console
        from rich.table import Table

        console = Console()

        try:
            from oneiric.adapters.dhruva_pusher import push_adapters_on_startup

            console.print("[cyan]Pushing Oneiric adapters to Dhruva...[/cyan]")

            results = push_adapters_on_startup()

            # Display results
            table = Table(title="Adapter Push Results")
            table.add_column("Metric", style="cyan")
            table.add_column("Count", style="green")

            table.add_row("Total", str(results["total"]))
            table.add_row("Success", f"[green]{results['success']}[/green]")
            if results["errors"] > 0:
                table.add_row("Errors", f"[red]{results['errors']}[/red]")
            else:
                table.add_row("Errors", str(results["errors"]))

            console.print(table)

            if results["errors"] > 0:
                console.print("\n[red]Errors:[/red]")
                for detail in results["details"]:
                    if detail["status"] != "success":
                        console.print(
                            f"  • {detail['adapter_id']}: {detail.get('error', 'Unknown')}"
                        )

        except ImportError:
            console.print("[red]✗ Oneiric adapter pusher not found[/red]")
            console.print("  Install oneiric to use this feature")
        except Exception as e:
            console.print(f"[red]✗ Failed to push adapters: {e}[/red]")

    async def _show_storage_info(self) -> None:
        """Display storage statistics.

        Helper function available in shell namespace.
        """
        from rich.console import Console
        from rich.table import Table

        console = Console()
        root = self.connection.get_root()

        table = Table(title="Storage Information")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        # Count objects by type
        from collections import Counter

        type_counts = Counter(type(obj).__name__ for obj in root.values())

        table.add_row("Total Objects", str(len(root)))
        table.add_row("Types", str(len(type_counts)))

        # Show top 5 types
        for type_name, count in type_counts.most_common(5):
            table.add_row(f"  • {type_name}", str(count))

        console.print(table)

    async def _show_adapter_summary(self) -> None:
        """Show adapter distribution summary.

        Helper function available in shell namespace.
        """
        from rich.console import Console
        from rich.table import Table

        console = Console()

        try:
            adapters = self.registry.list_adapters()

            # Group by category
            from collections import Counter

            categories = Counter(
                a["metadata"].get("category", "unknown") for a in adapters
            )

            table = Table(title="Adapter Distribution Summary")
            table.add_column("Category", style="cyan")
            table.add_column("Count", style="green")
            table.add_column("Percentage", style="yellow")

            total = len(adapters)
            for category, count in categories.most_common():
                percentage = (count / total * 100) if total > 0 else 0
                table.add_row(category.capitalize(), str(count), f"{percentage:.1f}%")

            table.add_row("Total", str(total), "100%")

            console.print(table)

        except Exception as e:
            console.print(f"[red]✗ Failed to get adapter summary: {e}[/red]")

    async def _emit_session_start(self) -> None:
        """Emit session start event with Dhruva-specific metadata."""
        try:
            metadata = {
                "version": self._get_component_version(),
                "adapters": self._get_adapters_info(),
                "component_type": "curator",
                "adapter_count": self.registry.count(),
                "storage_path": str(self.app.storage.path)
                if hasattr(self.app, "storage")
                else None,
            }

            self._session_id = await self.session_tracker.emit_session_start(
                shell_type=self.__class__.__name__,
                metadata=metadata,
            )

            if self._session_id:
                logger.info(f"Dhruva shell session started: {self._session_id}")
            else:
                logger.debug(
                    "Session tracking unavailable (Session-Buddy MCP not reachable)"
                )
        except Exception as e:
            logger.debug(f"Failed to emit session start: {e}")

    async def _emit_session_end(self) -> None:
        """Emit session end event."""
        if not self._session_id:
            return

        try:
            await self.session_tracker.emit_session_end(
                session_id=self._session_id,
                metadata={
                    "adapters_at_end": self.registry.count(),
                },
            )
            logger.info(f"Dhruva shell session ended: {self._session_id}")
        except Exception as e:
            logger.debug(f"Failed to emit session end: {e}")
        finally:
            self._session_id = None

    async def close(self) -> None:
        """Close shell and cleanup resources."""
        await self._emit_session_end()
        await self.session_tracker.close()
        self.connection.close()


__all__ = ["DhruvaShell"]

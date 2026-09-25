"""Dhara admin shell.

This module provides Dhara-specific admin shell functionality extending
the Oneiric ecosystem shell pattern with Dhara-specific features:

- Storage inspection and manipulation
- Health monitoring
"""

from __future__ import annotations

import logging
from typing import Any

from oneiric.shell import AdminShell
from oneiric.shell.config import ShellConfig

logger = logging.getLogger(__name__)


class DharaSessionTracker:
    """No-op session tracker for Dhara shell sessions.

    Retained as a no-op stub for backward compatibility with downstream
    code that constructs ``DharaShell`` directly. Methods simply return
    None / do nothing — there is no external session-tracking integration.
    """

    def __init__(self, component_name: str) -> None:
        self.component_name = component_name

    async def emit_session_start(
        self,
        shell_type: str,
        metadata: dict[str, Any],
    ) -> str | None:
        return None

    async def emit_session_end(
        self,
        session_id: str,
        metadata: dict[str, Any],
    ) -> None:
        return None

    async def close(self) -> None:
        return None


class DharaShell(AdminShell):
    """Dhara-specific admin shell.

    Extends the Oneiric AdminShell with Dhara-specific namespace,
    formatters, helpers, and magic commands for storage management.

    Example:
        >>> from dhara.shell import DharaShell
        >>> from dhara.core.config import DharaSettings
        >>> from dhara.core.connection import AsyncConnection
        >>> from dhara.storage.async_file import AsyncFileStorage
        >>> import asyncio
        >>> config = DharaSettings.load()
        >>> connection = asyncio.run(
        ...     AsyncConnection.new(str(config.storage.path))
        ... )
        >>> shell = DharaShell(connection, config)
        >>> shell.start()
    """

    def __init__(
        self,
        connection: Any,
        config: Any,
        shell_config: ShellConfig | None = None,
    ):
        """Initialize Dhara shell.

        Args:
            connection: Dhara Connection instance
            config: DharaSettings instance
            shell_config: Optional shell configuration
        """
        self.connection = connection

        # Pass config to parent as "app"
        super().__init__(config, shell_config)

        # Add Dhara-specific namespace
        self._add_dhara_namespace()

        # Override session tracker with no-op stub (no external integration)
        self.session_tracker = DharaSessionTracker(component_name="dhara")
        self._session_id: str | None = None

    def _add_dhara_namespace(self) -> None:
        """Add Dhara-specific objects to shell namespace."""
        self.namespace.update(
            {
                # Core objects
                "connection": self.connection,
                "config": self.app,
                # Storage helpers
                "root": self.connection.get_root(),
                "commit": self.connection.commit,
                "pack": self.connection.pack,
                # Async helpers
                "show_storage_info": self._show_storage_info,
            }
        )

    def _get_component_name(self) -> str | None:
        """Return Dhara component name for session tracking.

        Returns:
            Component name "dhara" for session tracking
        """
        return "dhara"

    def _get_component_version(self) -> str:
        """Get Dhara package version.

        Returns:
            Dhara version string or "unknown" if unavailable
        """
        try:
            import importlib.metadata as importlib_metadata

            return importlib_metadata.version("dhara")
        except Exception:  # noqa: BLE001  # version probe fallback → "unknown"
            return "unknown"

    def _get_banner(self) -> str:
        """Get Dhara-specific banner."""
        version = self._get_component_version()

        return f"""
🦀 Dhara Admin Shell v{version}
{"=" * 60}
Persistent Object Storage

Storage Info:
  Connection: {"Active" if self.connection else "Inactive"}

Storage Operations:
  root       - Access root persistent object
  commit()   - Commit pending changes
  pack()     - Pack storage (reclaim space)

Available Objects:
  connection - Dhara Connection instance
  config     - Current DharaSettings instance

Type 'help()' for Python help or %help_shell for shell commands
{"=" * 60}
"""

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

    async def _emit_session_start(self) -> None:
        """Emit session start event with Dhara-specific metadata."""
        try:
            metadata = {
                "version": self._get_component_version(),
                "component_type": "curator",
                "storage_path": str(self.app.storage.path)
                if hasattr(self.app, "storage")
                else None,
            }

            self._session_id = await self.session_tracker.emit_session_start(
                shell_type=self.__class__.__name__,
                metadata=metadata,
            )

            if self._session_id:
                logger.info(f"Dhara shell session started: {self._session_id}")
        except Exception as e:  # noqa: BLE001  # session-start tracking fallback
            logger.debug(f"Failed to emit session start: {e}")

    async def _emit_session_end(self) -> None:
        """Emit session end event."""
        if not self._session_id:
            return

        try:
            await self.session_tracker.emit_session_end(
                session_id=self._session_id,
                metadata={},
            )
            logger.info("Dhara shell session ended")
        except Exception as e:  # noqa: BLE001  # session-end tracking fallback
            logger.debug(f"Failed to emit session end: {e}")
        finally:
            self._session_id = None

    async def close(self) -> None:
        """Close shell and cleanup resources."""
        await self._emit_session_end()
        await self.session_tracker.close()
        self.connection.close()


DruvaShell = DharaShell

__all__ = ["DharaShell", "DruvaShell"]

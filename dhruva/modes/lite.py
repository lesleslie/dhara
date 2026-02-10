"""Lite operational mode - Zero-configuration development mode.

This mode provides the simplest possible Dhruva experience:
- No configuration required
- Local filesystem storage
- Sensible defaults
- Ideal for development and testing

★ Insight: Lite Mode Philosophy ───────────────────────────────────
1. Zero configuration required
2. Auto-creation of directories
3. Local-only operation (no cloud dependencies)
4. Fast startup for development iteration
5. Clear separation from production concerns
────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from oneiric.core.logging import get_logger

from dhruva.core.config import StorageConfig
from dhruva.modes.base import ModeValidationError, OperationalMode

logger = get_logger(__name__)


class LiteMode(OperationalMode):
    """Lite mode for development and testing.

    Features:
    - Zero configuration required
    - Local filesystem storage in ~/.local/share/dhruva/
    - Default host: 127.0.0.1 (localhost only)
    - Default port: 8683
    - No cloud storage dependencies
    - Debug logging enabled by default

    Usage:
        # Start in lite mode (zero config)
        dhruva start --mode=lite

        # Or via environment
        export DHRUVA_MODE=lite
        dhruva start

        # Python API
        from dhruva.modes import LiteMode
        mode = LiteMode()
        mode.initialize()
    """

    # Mode constants
    MODE_NAME = "Lite"
    MODE_DESCRIPTION = "Development mode with zero configuration"

    # Default paths
    DEFAULT_STORAGE_PATH = Path.home() / ".local" / "share" / "dhruva" / "lite.dhruva"
    DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "settings" / "lite.yaml"

    # Default server settings
    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8683

    def get_name(self) -> str:
        """Return mode name."""
        return self.MODE_NAME

    def get_description(self) -> str:
        """Return mode description."""
        return self.MODE_DESCRIPTION

    def get_config_path(self) -> Path:
        """Return path to lite mode default configuration."""
        return self.DEFAULT_CONFIG_PATH

    def get_default_storage_path(self) -> Path:
        """Return default storage path for lite mode."""
        return self.DEFAULT_STORAGE_PATH

    def validate_environment(self) -> bool:
        """Validate environment for lite mode.

        Lite mode requires minimal validation:
        - Can create storage directory
        - Have write permissions
        - No network access required (localhost only)

        Returns:
            True if environment is valid

        Raises:
            ModeValidationError: If environment cannot be set up
        """
        logger.debug("Validating lite mode environment")

        try:
            # Ensure storage directory exists
            storage_dir = self.DEFAULT_STORAGE_PATH.parent
            logger.debug(f"Ensuring storage directory exists: {storage_dir}")

            if not storage_dir.exists():
                logger.info(f"Creating storage directory: {storage_dir}")
                storage_dir.mkdir(parents=True, exist_ok=True)

            # Check write permissions
            if not os.access(storage_dir, os.W_OK):
                raise ModeValidationError(
                    f"Cannot write to storage directory: {storage_dir}",
                    mode_name=self.name,
                    details={
                        "storage_dir": str(storage_dir),
                        "fix": "Check directory permissions or run with appropriate user",
                    },
                )

            # Check if port is available (warning only)
            if not self._is_port_available(self.DEFAULT_HOST, self.DEFAULT_PORT):
                logger.warning(
                    f"Port {self.DEFAULT_PORT} may be in use. "
                    f"If startup fails, try: dhruva start --mode=lite --port=8684"
                )

            logger.debug("Lite mode environment validation passed")
            self._validated = True
            return True

        except ModeValidationError:
            raise
        except Exception as e:
            raise ModeValidationError(
                f"Environment validation failed: {e}",
                mode_name=self.name,
                details={"error": str(e)},
            ) from e

    def configure_storage(self, config: StorageConfig) -> StorageConfig:
        """Configure storage for lite mode.

        Lite mode always uses local filesystem storage with
        predictable path in user's home directory.

        Args:
            config: Base storage configuration (will be overridden)

        Returns:
            Lite-mode-configured storage settings
        """
        logger.debug("Configuring storage for lite mode")

        # Force local filesystem storage
        config.backend = "file"
        config.path = self.DEFAULT_STORAGE_PATH
        config.read_only = False

        logger.debug(f"  Storage backend: {config.backend}")
        logger.debug(f"  Storage path: {config.path}")
        logger.debug(f"  Read-only: {config.read_only}")

        return config

    def get_startup_options(self) -> dict[str, Any]:
        """Get default startup options for lite mode.

        Returns:
            Dictionary of default startup options
        """
        return {
            "host": self.DEFAULT_HOST,
            "port": self.DEFAULT_PORT,
            "storage_path": str(self.DEFAULT_STORAGE_PATH),
            "storage_backend": "file",
            "read_only": False,
            "log_level": "DEBUG",
            "log_format": "text",
        }

    def get_banner(self) -> str:
        """Get startup banner for lite mode."""
        return """
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║   🦀 Dhruva Lite Mode - Development & Testing                    ║
║                                                                   ║
║   ✓ Zero configuration required                                  ║
║   ✓ Local storage in ~/.local/share/dhruva/                      ║
║   ✓ Host: 127.0.0.1:8683                                         ║
║   ✓ Ideal for development and testing                            ║
║                                                                   ║
║   Quick start:                                                   ║
║     $ dhruva start --mode=lite                                   ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
"""

    def get_info(self) -> dict[str, Any]:
        """Get comprehensive lite mode information."""
        info = super().get_info()
        info.update(
            {
                "startup_command": "dhruva start --mode=lite",
                "storage_location": str(self.DEFAULT_STORAGE_PATH),
                "access_url": f"http://{self.DEFAULT_HOST}:{self.DEFAULT_PORT}",
                "configuration_required": False,
                "ideal_for": [
                    "Local development",
                    "Quick prototyping",
                    "Testing and experimentation",
                    "Learning Dhruva",
                ],
            }
        )
        return info

    def _is_port_available(self, host: str, port: int) -> bool:
        """Check if port is available.

        Args:
            host: Host address
            port: Port number

        Returns:
            True if port appears to be available
        """
        try:
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            return result != 0  # Connection failed = port available
        except Exception:
            return True  # Assume available if check fails

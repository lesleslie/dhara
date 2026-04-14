"""Base operational mode interface.

This module defines the abstract base class for all operational modes.
Each mode must implement the interface to provide consistent behavior
across different deployment scenarios.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from oneiric.core.logging import get_logger

from dhara.core.config import DharaSettings, StorageConfig

logger = get_logger(__name__)


class OperationalModeError(Exception):
    """Base exception for operational mode errors."""

    def __init__(
        self,
        message: str,
        mode_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.mode_name = mode_name
        self.details = details or {}
        super().__init__(self.message)


class ModeValidationError(OperationalModeError):
    """Raised when mode environment validation fails."""


class ModeConfigurationError(OperationalModeError):
    """Raised when mode configuration is invalid."""


class OperationalMode(ABC):
    """Abstract base class for operational modes.

    Each operational mode (lite, standard) must inherit from this class
    and implement all abstract methods to provide consistent behavior.

    ★ Insight: Mode Lifecycle ───────────────────────────────────────
    1. validate_environment() - Check prerequisites
    2. configure_storage() - Apply mode-specific storage config
    3. get_startup_options() - Get default options
    4. initialize() - Complete mode setup
    ────────────────────────────────────────────────────────────────────
    """

    def __init__(self, settings: DharaSettings | None = None):
        """Initialize operational mode.

        Args:
            settings: Optional DharaSettings instance. If None, will be loaded.
        """
        self.settings = settings
        self._validated = False

    @property
    def name(self) -> str:
        """Get mode name (lowercase)."""
        return self.get_name().lower()

    @abstractmethod
    def get_name(self) -> str:
        """Return human-readable mode name.

        Returns:
            Mode name (e.g., "Lite", "Standard")
        """
        pass

    @abstractmethod
    def get_description(self) -> str:
        """Return mode description.

        Returns:
            Human-readable description of this mode's purpose.
        """
        pass

    @abstractmethod
    def get_config_path(self) -> Path:
        """Return path to mode-specific default configuration.

        Returns:
            Path to default config file (e.g., settings/lite.yaml)
        """
        pass

    @abstractmethod
    def get_default_storage_path(self) -> Path:
        """Return default storage path for this mode.

        Returns:
            Default path for storage file
        """
        pass

    def validate_environment(self) -> bool:
        """Validate environment prerequisites for this mode.

        Checks:
        - Required directories exist or can be created
        - Required environment variables (if any)
        - File system permissions
        - Network access (if applicable)

        Returns:
            True if environment is valid

        Raises:
            ModeValidationError: If environment is invalid
        """
        logger.debug(f"Validating environment for {self.name} mode")

        try:
            # Check storage directory
            storage_path = self.get_default_storage_path()
            storage_dir = storage_path.parent

            if not storage_dir.exists():
                logger.debug(f"Creating storage directory: {storage_dir}")
                storage_dir.mkdir(parents=True, exist_ok=True)

            # Check write permissions
            if not os.access(storage_dir, os.W_OK):
                raise ModeValidationError(
                    f"Cannot write to storage directory: {storage_dir}",
                    mode_name=self.name,
                    details={"storage_dir": str(storage_dir)},
                )

            self._validated = True
            logger.debug(f"Environment validation passed for {self.name} mode")
            return True

        except ModeValidationError:
            raise
        except Exception as e:
            raise ModeValidationError(
                f"Environment validation failed: {e}",
                mode_name=self.name,
                details={"error": str(e)},
            ) from e

    @abstractmethod
    def configure_storage(self, config: StorageConfig) -> StorageConfig:
        """Configure storage backend for this mode.

        Applies mode-specific storage configuration, potentially
        overriding defaults with mode-appropriate values.

        Args:
            config: Base storage configuration

        Returns:
            Mode-configured storage settings
        """
        pass

    @abstractmethod
    def get_startup_options(self) -> dict[str, Any]:
        """Get default startup options for this mode.

        Returns:
            Dictionary of default startup options (host, port, etc.)
        """
        pass

    def get_banner(self) -> str:
        """Get startup banner for this mode.

        Returns:
            ASCII art banner text
        """
        return f"""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   Dhara {self.get_name():<10} Mode                                 ║
║   {self.get_description():<55} ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
"""

    def initialize(self) -> None:
        """Initialize mode (complete setup).

        This is the main entry point for mode initialization:
        1. Validates environment
        2. Applies configuration
        3. Creates directories
        4. Logs ready state

        Raises:
            ModeValidationError: If environment is invalid
            ModeConfigurationError: If configuration is invalid
        """
        logger.info(f"Initializing {self.name} mode")

        # Validate environment
        if not self._validated:
            self.validate_environment()

        # Load settings if not provided
        if self.settings is None:
            logger.debug("Loading DharaSettings")
            self.settings = DharaSettings.load("dhara")

        # Apply mode configuration
        logger.debug(f"Applying {self.name} mode configuration")
        self.settings.storage = self.configure_storage(self.settings.storage)

        # Log ready state
        logger.info(f"{self.name} mode initialized successfully")
        logger.debug(f"  Storage: {self.settings.storage.path}")
        logger.debug(f"  Backend: {self.settings.storage.backend}")
        logger.debug(f"  Read-only: {self.settings.storage.read_only}")

    def get_info(self) -> dict[str, Any]:
        """Get comprehensive mode information.

        Returns:
            Dictionary with mode details
        """
        return {
            "name": self.get_name(),
            "description": self.get_description(),
            "config_path": str(self.get_config_path()),
            "storage_path": str(self.get_default_storage_path()),
            "validated": self._validated,
            "startup_options": self.get_startup_options(),
        }


class LiteMode(OperationalMode):
    """Lite mode stub - will be implemented in lite.py"""

    def get_name(self) -> str:
        return "Lite"

    def get_description(self) -> str:
        return "Development mode with zero configuration"

    def get_config_path(self) -> Path:
        return Path(__file__).parent.parent.parent / "settings" / "lite.yaml"

    def get_default_storage_path(self) -> Path:
        return Path.home() / ".local" / "share" / "dhara" / "lite.dhara"

    def configure_storage(self, config: StorageConfig) -> StorageConfig:
        # Use local filesystem
        config.backend = "file"
        config.path = self.get_default_storage_path()
        config.read_only = False
        return config

    def get_startup_options(self) -> dict[str, Any]:
        return {
            "host": "127.0.0.1",
            "port": 8683,
        }


class StandardMode(OperationalMode):
    """Standard mode stub - will be implemented in standard.py"""

    def get_name(self) -> str:
        return "Standard"

    def get_description(self) -> str:
        return "Production mode with full capabilities"

    def get_config_path(self) -> Path:
        return Path(__file__).parent.parent.parent / "settings" / "standard.yaml"

    def get_default_storage_path(self) -> Path:
        return Path("/data/dhara/production.dhara")

    def configure_storage(self, config: StorageConfig) -> StorageConfig:
        # Use configured backend (file, sqlite, s3, etc.)
        # Keep existing config if set
        if not config.path or config.path == Path("/data/dhara/dhara.dhara"):
            config.path = self.get_default_storage_path()
        return config

    def get_startup_options(self) -> dict[str, Any]:
        return {
            "host": "0.0.0.0",
            "port": 8683,
        }


def create_mode(
    mode_name: str, settings: DharaSettings | None = None
) -> OperationalMode:
    """Create operational mode instance by name.

    Args:
        mode_name: Mode name ("lite" or "standard")
        settings: Optional DharaSettings instance

    Returns:
        OperationalMode instance

    Raises:
        ValueError: If mode_name is invalid

    ★ Insight: Mode Factory ───────────────────────────────────────
    1. Normalize mode name to lowercase
    2. Look up mode class
    3. Instantiate with settings
    4. Return mode instance
    ────────────────────────────────────────────────────────────────────
    """
    mode_name = mode_name.lower().strip()

    mode_classes: dict[str, type[OperationalMode]] = {
        "lite": LiteMode,
        "standard": StandardMode,
    }

    if mode_name not in mode_classes:
        raise ValueError(
            f"Invalid mode: {mode_name}. Valid modes: {', '.join(mode_classes.keys())}"
        )

    mode_class = mode_classes[mode_name]
    return mode_class(settings=settings)


def get_mode(settings: DharaSettings | None = None) -> OperationalMode:
    """Detect operational mode from environment or configuration.

    Detection priority:
    1. DHARA_MODE environment variable
    2. settings.dhara.yaml mode field
    3. Auto-detect based on storage configuration

    Args:
        settings: Optional DharaSettings instance

    Returns:
        Detected OperationalMode instance

    ★ Insight: Mode Detection ───────────────────────────────────────
    1. Check environment variable (highest priority)
    2. Check settings file
    3. Auto-detect based on config
    4. Default to lite mode for safety
    ────────────────────────────────────────────────────────────────────
    """
    # 1. Check environment variable
    env_mode = os.getenv("DHARA_MODE", "").lower().strip()
    if env_mode in ("lite", "standard"):
        logger.debug(f"Detected mode from environment: {env_mode}")
        return create_mode(env_mode, settings=settings)

    # 2. Check settings file
    if settings is None:
        try:
            settings = DharaSettings.load("dhara")
        except Exception:
            logger.debug("Could not load settings, using default detection")
            pass

    # 3. Auto-detect based on storage configuration
    if settings:
        # If storage path is default lite path, assume lite mode
        lite_path = Path.home() / ".local" / "share" / "dhara" / "lite.dhara"
        if settings.storage.path == lite_path:
            logger.debug("Detected lite mode from storage path")
            return create_mode("lite", settings=settings)

        # If storage backend is not file, assume standard mode
        if settings.storage.backend != "file":
            logger.debug(
                f"Detected standard mode from storage backend: {settings.storage.backend}"
            )
            return create_mode("standard", settings=settings)

    # 4. Default to lite mode (safest for new users)
    logger.debug("Defaulting to lite mode")
    return create_mode("lite", settings=settings)


def list_modes() -> list[dict[str, Any]]:
    """List all available operational modes.

    Returns:
        List of mode information dictionaries
    """
    modes = [
        create_mode("lite"),
        create_mode("standard"),
    ]

    return [mode.get_info() for mode in modes]

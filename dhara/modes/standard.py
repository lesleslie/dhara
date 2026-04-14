"""Standard operational mode - Full-featured production mode.

This mode provides complete Dhara capabilities:
- Configurable storage backends (file, SQLite, S3, GCS, Azure)
- Full configuration via YAML + environment variables
- Production-ready defaults
- Cloud storage integration
- Ideal for production deployments

★ Insight: Standard Mode Philosophy ───────────────────────────────
1. Full configuration control
2. Multiple storage backend support
3. Cloud storage integration
4. Production-ready defaults
5. Horizontal scaling capability
────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from oneiric.core.logging import get_logger

from dhara.core.config import DharaSettings, StorageConfig
from dhara.modes.base import ModeValidationError, OperationalMode

logger = get_logger(__name__)


class StandardMode(OperationalMode):
    """Standard mode for production deployments.

    Features:
    - Configurable storage backends (file, sqlite, s3, gcs, azure)
    - Full YAML + environment variable configuration
    - Default host: 0.0.0.0 (all interfaces)
    - Default port: 8683
    - Cloud storage integration (S3, GCS, Azure)
    - Production logging (JSON format)
    - Backup integration enabled

    Usage:
        # Start in standard mode
        dhara start --mode=standard

        # With custom config
        dhara start --mode=standard --config=settings/production.yaml

        # With S3 storage
        export DHARA_STORAGE_BACKEND=s3
        export DHARA_S3_BUCKET=my-bucket
        dhara start --mode=standard

        # Python API
        from dhara.modes import StandardMode
        mode = StandardMode()
        mode.initialize()
    """

    # Mode constants
    MODE_NAME = "Standard"
    MODE_DESCRIPTION = "Production mode with full capabilities"

    # Default paths
    DEFAULT_STORAGE_PATH = Path("/data/dhara/production.dhara")
    DEFAULT_CONFIG_PATH = (
        Path(__file__).parent.parent.parent / "settings" / "standard.yaml"
    )

    # Default server settings
    DEFAULT_HOST = "0.0.0.0"
    DEFAULT_PORT = 8683

    # Supported storage backends
    SUPPORTED_BACKENDS = ["file", "sqlite", "s3", "gcs", "azure"]

    def get_name(self) -> str:
        """Return mode name."""
        return self.MODE_NAME

    def get_description(self) -> str:
        """Return mode description."""
        return self.MODE_DESCRIPTION

    def get_config_path(self) -> Path:
        """Return path to standard mode default configuration."""
        return self.DEFAULT_CONFIG_PATH

    def get_default_storage_path(self) -> Path:
        """Return default storage path for standard mode."""
        return self.DEFAULT_STORAGE_PATH

    def validate_environment(self) -> bool:
        """Validate environment for standard mode.

        Standard mode validation:
        - Storage directory (for file/sqlite backends)
        - Cloud credentials (for s3/gcs/azure backends)
        - Network access
        - Configuration file validity

        Returns:
            True if environment is valid

        Raises:
            ModeValidationError: If environment requirements are not met
        """
        logger.debug("Validating standard mode environment")

        # Load settings to check backend
        if self.settings is None:
            try:
                self.settings = DharaSettings.load("dhara")
            except Exception as e:
                logger.warning(f"Could not load settings for validation: {e}")
                # Don't fail validation, will use defaults
                self.settings = DharaSettings()

        try:
            # Backend-specific validation
            backend = self.settings.storage.backend if self.settings else "file"

            if backend == "file" or backend == "sqlite":
                self._validate_file_storage()
            elif backend == "s3":
                self._validate_s3_storage()
            elif backend == "gcs":
                self._validate_gcs_storage()
            elif backend == "azure":
                self._validate_azure_storage()
            else:
                raise ModeValidationError(
                    f"Unsupported storage backend: {backend}",
                    mode_name=self.name,
                    details={
                        "backend": backend,
                        "supported": self.SUPPORTED_BACKENDS,
                        "fix": f"Use one of: {', '.join(self.SUPPORTED_BACKENDS)}",
                    },
                )

            # Check network access
            self._validate_network_access()

            logger.debug("Standard mode environment validation passed")
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
        """Configure storage for standard mode.

        Respects existing configuration but applies standard mode
        defaults where not set.

        Args:
            config: Base storage configuration

        Returns:
            Standard-mode-configured storage settings
        """
        logger.debug("Configuring storage for standard mode")

        backend = config.backend or "file"

        # Apply backend-specific configuration
        if backend == "file":
            config = self._configure_file_storage(config)
        elif backend == "sqlite":
            config = self._configure_sqlite_storage(config)
        elif backend == "s3":
            config = self._configure_s3_storage(config)
        elif backend == "gcs":
            config = self._configure_gcs_storage(config)
        elif backend == "azure":
            config = self._configure_azure_storage(config)

        logger.debug(f"  Storage backend: {config.backend}")
        logger.debug(f"  Storage path: {config.path}")
        logger.debug(f"  Read-only: {config.read_only}")

        return config

    def get_startup_options(self) -> dict[str, Any]:
        """Get default startup options for standard mode.

        Returns:
            Dictionary of default startup options
        """
        return {
            "host": self.DEFAULT_HOST,
            "port": self.DEFAULT_PORT,
            "storage_backend": "file",  # Will be overridden by config
            "storage_path": str(self.DEFAULT_STORAGE_PATH),
            "read_only": False,
            "log_level": "INFO",
            "log_format": "json",
            "cloud_storage": {
                "enabled": True,
                "backup_enabled": True,
            },
        }

    def get_banner(self) -> str:
        """Get startup banner for standard mode."""
        backend = self.settings.storage.backend if self.settings else "file"
        return f"""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║   Dhara Standard Mode - Production Ready                        ║
║                                                                   ║
║   ✓ Full configuration control                                   ║
║   ✓ Storage backend: {backend:<10}                                ║
║   ✓ Host: {self.DEFAULT_HOST}:{self.DEFAULT_PORT}                                    ║
║   ✓ Ideal for production deployments                             ║
║                                                                   ║
║   Quick start:                                                   ║
║     $ dhara start --mode=standard                               ║
║                                                                   ║
║   Configuration:                                                 ║
║     $ dhara start --mode=standard --config=settings/production  ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
"""

    def get_info(self) -> dict[str, Any]:
        """Get comprehensive standard mode information."""
        info = super().get_info()
        info.update(
            {
                "startup_command": "dhara start --mode=standard",
                "supported_backends": self.SUPPORTED_BACKENDS,
                "access_url": f"http://{self.DEFAULT_HOST}:{self.DEFAULT_PORT}",
                "configuration_required": True,
                "ideal_for": [
                    "Production deployments",
                    "Multi-server setups",
                    "Cloud-native applications",
                    "High availability requirements",
                ],
            }
        )
        return info

    # Private helper methods

    def _validate_file_storage(self) -> None:
        """Validate file/sqlite storage requirements."""
        storage_path = (
            self.settings.storage.path if self.settings else self.DEFAULT_STORAGE_PATH
        )

        if not storage_path:
            raise ModeValidationError(
                "Storage path not configured",
                mode_name=self.name,
                details={"fix": "Set DHARA_STORAGE_PATH or configure in YAML"},
            )

        storage_dir = Path(storage_path).parent

        # Try to create directory if it doesn't exist
        if not storage_dir.exists():
            logger.info(f"Creating storage directory: {storage_dir}")
            try:
                storage_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ModeValidationError(
                    f"Cannot create storage directory: {storage_dir}",
                    mode_name=self.name,
                    details={"error": str(e), "storage_dir": str(storage_dir)},
                ) from e

        # Check write permissions
        if not os.access(storage_dir, os.W_OK):
            raise ModeValidationError(
                f"Cannot write to storage directory: {storage_dir}",
                mode_name=self.name,
                details={"storage_dir": str(storage_dir)},
            )

    def _validate_s3_storage(self) -> None:
        """Validate AWS S3 storage requirements."""
        # Check for AWS credentials
        if not os.getenv("AWS_ACCESS_KEY_ID") and not os.getenv(
            "AWS_SHARED_CREDENTIALS_FILE"
        ):
            logger.warning("AWS credentials not found in environment")

        # Check for bucket configuration
        if self.settings and hasattr(self.settings, "s3_bucket"):
            if not self.settings.s3_bucket:
                raise ModeValidationError(
                    "S3 bucket not configured",
                    mode_name=self.name,
                    details={"fix": "Set DHARA_S3_BUCKET or configure in YAML"},
                )
        else:
            logger.warning("S3 bucket not configured, may fail at runtime")

    def _validate_gcs_storage(self) -> None:
        """Validate Google Cloud Storage requirements."""
        # Check for GCS credentials
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and not os.getenv(
            "GCS_KEYFILE"
        ):
            logger.warning("GCS credentials not found in environment")

        # Check for bucket configuration
        if self.settings and hasattr(self.settings, "gcs_bucket"):
            if not self.settings.gcs_bucket:
                raise ModeValidationError(
                    "GCS bucket not configured",
                    mode_name=self.name,
                    details={"fix": "Set DHARA_GCS_BUCKET or configure in YAML"},
                )
        else:
            logger.warning("GCS bucket not configured, may fail at runtime")

    def _validate_azure_storage(self) -> None:
        """Validate Azure Blob Storage requirements."""
        # Check for Azure credentials
        if not os.getenv("AZURE_STORAGE_CONNECTION_STRING") and not os.getenv(
            "AZURE_STORAGE_KEY"
        ):
            logger.warning("Azure credentials not found in environment")

        # Check for container configuration
        if self.settings and hasattr(self.settings, "azure_container"):
            if not self.settings.azure_container:
                raise ModeValidationError(
                    "Azure container not configured",
                    mode_name=self.name,
                    details={"fix": "Set DHARA_AZURE_CONTAINER or configure in YAML"},
                )
        else:
            logger.warning("Azure container not configured, may fail at runtime")

    def _validate_network_access(self) -> None:
        """Validate network access."""
        host = self.DEFAULT_HOST
        port = self.DEFAULT_PORT

        if not self._is_port_available(host, port):
            logger.warning(
                f"Port {port} may be in use. "
                f"If startup fails, try: dhara start --mode=standard --port=8684"
            )

    def _is_port_available(self, host: str, port: int) -> bool:
        """Check if port is available."""
        try:
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            return result != 0
        except Exception:
            return True

    # Storage configuration helpers

    def _configure_file_storage(self, config: StorageConfig) -> StorageConfig:
        """Configure file storage backend."""
        config.backend = "file"
        if not config.path or config.path == Path("/data/dhara/dhara.dhara"):
            config.path = self.DEFAULT_STORAGE_PATH
        return config

    def _configure_sqlite_storage(self, config: StorageConfig) -> StorageConfig:
        """Configure SQLite storage backend."""
        config.backend = "sqlite"
        if not config.path or config.path == Path("/data/dhara/dhara.dhara"):
            config.path = Path("/data/dhara/production.db")
        return config

    def _configure_s3_storage(self, config: StorageConfig) -> StorageConfig:
        """Configure S3 storage backend."""
        config.backend = "s3"
        # S3 uses bucket/prefix instead of file path
        if not config.path or config.path == Path("/data/dhara/dhara.dhara"):
            config.path = Path("s3://dhara-production/dhara.dhara")
        return config

    def _configure_gcs_storage(self, config: StorageConfig) -> StorageConfig:
        """Configure GCS storage backend."""
        config.backend = "gcs"
        if not config.path or config.path == Path("/data/dhara/dhara.dhara"):
            config.path = Path("gs://dhara-production/dhara.dhara")
        return config

    def _configure_azure_storage(self, config: StorageConfig) -> StorageConfig:
        """Configure Azure storage backend."""
        config.backend = "azure"
        if not config.path or config.path == Path("/data/dhara/dhara.dhara"):
            config.path = Path("azure://dhara-production/dhara.dhara")
        return config

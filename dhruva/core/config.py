"""Dhruva MCP Server configuration using mcp-common patterns.

This module provides type-safe configuration management following
mcp-common patterns with YAML + environment variable configuration.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp_common import MCPServerSettings
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StorageConfig(BaseModel):
    """Dhruva storage configuration."""

    path: Path = Field(default=Path("/data/dhruva.dhruva"))
    read_only: bool = Field(default=False)
    backend: str = Field(default="file")  # file, sqlite, memory, s3, gcs, azure


class AdapterConfig(BaseModel):
    """Adapter distribution configuration."""

    enable_versioning: bool = Field(default=True)
    enable_health_checks: bool = Field(default=True)
    max_versions_per_adapter: int = Field(default=10, ge=1, le=100)
    auto_push_on_startup: bool = Field(default=True)


class CloudStorageConfig(BaseModel):
    """Cloud storage configuration for backups."""

    enabled: bool = Field(default=False)
    provider: str = Field(default="s3")  # s3, gcs, azure
    bucket: str | None = Field(default=None)
    prefix: str = Field(default="")
    schedule: str = Field(default="0 2 * * *")  # Cron format


class DhruvaSettings(MCPServerSettings):
    """Dhruva MCP Server settings extending MCPServerSettings.

    Configuration loading order (later overrides earlier):
    1. Default values (below)
    2. settings/dhruva.yaml (committed) OR settings/{mode}.yaml
    3. settings/local.yaml (gitignored, for development)
    4. Environment variables: DHRUVA_{FIELD}

    Example YAML (settings/dhruva.yaml):
        mode: standard
        storage:
          path: /data/dhruva.dhruva
          read_only: false
        adapters:
          enable_versioning: true
          enable_health_checks: true

    Example env vars:
        export DHRUVA_MODE=lite
        export DHRUVA_STORAGE_PATH=/custom/path
        export DHRUVA_STORAGE_READ_ONLY=false
    """

    # Operational mode (lite, standard)
    mode: str = Field(
        default="lite",
        description="Operational mode: lite (dev) or standard (production)",
    )

    # Cache directory for CLI factory (PID files, health snapshots)
    cache_root: Path = Field(
        default=Path("~/.oneiric_cache"),
        description="Path to .oneiric_cache directory for PID files and snapshots",
    )

    # Dhruva-specific settings
    storage: StorageConfig = Field(default_factory=StorageConfig)
    adapters: AdapterConfig = Field(default_factory=AdapterConfig)
    cloud_storage: CloudStorageConfig = Field(default_factory=CloudStorageConfig)

    # Oneiric integration (optional)
    oneiric_config_path: Path | None = Field(
        default=None,
        description="Path to Oneiric YAML config (optional)",
    )

    # Server host and port
    host: str | None = Field(
        default=None,
        description="Server host (default: 127.0.0.1 for lite, 0.0.0.0 for standard)",
    )
    port: int | None = Field(
        default=None,
        description="Server port (default: 8683)",
    )

    @classmethod
    def load(cls, config_name: str = "dhruva") -> DhruvaSettings:
        """Load settings with mode-aware configuration.

        Detects mode from environment and loads appropriate config file:
        - DHRUVA_MODE=lite → settings/lite.yaml
        - DHRUVA_MODE=standard → settings/standard.yaml
        - No mode set → settings/dhruva.yaml

        Args:
            config_name: Base config name (default: "dhruva")

        Returns:
            Loaded DhruvaSettings instance
        """
        # Detect mode from environment
        mode = os.getenv("DHRUVA_MODE", "").lower().strip()

        # Determine config file to load
        if mode == "lite":
            config_file = "lite"
        elif mode == "standard":
            config_file = "standard"
        else:
            config_file = config_name

        # Load settings using parent class
        try:
            settings = super().load(config_file)
            logger.debug(f"Loaded settings from {config_file}.yaml")
        except Exception as e:
            logger.warning(f"Could not load {config_file}.yaml: {e}, using defaults")
            settings = cls()

        # Override mode from environment if set
        if mode:
            settings.mode = mode
            logger.debug(f"Mode overridden from environment: {mode}")

        return settings

    def get_mode_config_path(self) -> Path:
        """Get path to mode-specific configuration file.

        Returns:
            Path to appropriate config file based on mode
        """
        if self.mode == "lite":
            return Path(__file__).parent.parent.parent / "settings" / "lite.yaml"
        elif self.mode == "standard":
            return Path(__file__).parent.parent.parent / "settings" / "standard.yaml"
        else:
            return Path(__file__).parent.parent.parent / "settings" / "dhruva.yaml"

    def health_snapshot_path(self) -> Path:
        """Get path to health snapshot file for this mode.

        Returns:
            Path to health snapshot file
        """
        snapshot_name = f"{self.mode}_dhruva_health.json"
        return self.cache_root / snapshot_name

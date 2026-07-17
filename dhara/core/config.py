"""Dhara MCP Server configuration using mcp-common patterns.

This module provides type-safe configuration management following
mcp-common patterns with YAML + environment variable configuration.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import ClassVar, Self

from oneiric.core.config import OneiricMCPConfig
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StorageConfig(BaseModel):
    """Dhara storage configuration."""

    path: Path = Field(default=Path("/data/dhara.dhara"))
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


class TimeSeriesConfig(BaseModel):
    """Time-series storage configuration."""

    retention_days: int = Field(default=60, ge=1, le=3650)


class EcosystemStateConfig(BaseModel):
    """Ecosystem registry and event-log configuration."""

    event_retention_days: int = Field(default=30, ge=1, le=3650)


class AuthenticationTokenConfig(BaseModel):
    """Static token auth configuration for the canonical FastMCP runtime."""

    tokens_file: Path | None = Field(default=None)
    require_auth: bool = Field(default=True)
    default_role: str = Field(default="readonly")


class AuthenticationConfig(BaseModel):
    """Canonical MCP authentication settings."""

    enabled: bool = Field(default=False)
    method: str = Field(default="token")
    required_scopes: list[str] = Field(default_factory=list)
    token: AuthenticationTokenConfig = Field(default_factory=AuthenticationTokenConfig)


class BackupRuntimeConfig(BaseModel):
    """Runtime backup/recovery observability settings."""

    enabled: bool = Field(default=False)
    directory: Path = Field(default=Path("./backups"))


def _deep_merge(
    base: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base``. ``override`` wins."""
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _coerce_env_value(value: str) -> Any:
    """Best-effort type coercion for env-var string values."""
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    for caster in (int, float):
        try:
            return caster(value)
        except ValueError:
            continue
    if "," in value:
        return [item.strip() for item in value.split(",")]
    return value


def _env_overrides(prefix: str) -> dict[str, Any]:
    """Build nested dict overrides from ``{prefix}_SECTION__FIELD`` env vars.

    Example: ``DHARA_STORAGE__BACKEND=sqlite`` produces
    ``{"storage": {"backend": "sqlite"}}``.
    """
    env_prefix = f"{prefix}_"
    overrides: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(env_prefix):
            continue
        path = key[len(env_prefix) :].lower().split("__")
        coerced = _coerce_env_value(value)
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = coerced
    return overrides


class DharaSettings(OneiricMCPConfig):
    """Dhara MCP Server settings extending OneiricMCPConfig.

    Configuration loading order (later overrides earlier):
    1. Default values (below)
    2. settings/dhara.yaml (committed) OR settings/{mode}.yaml
    3. settings/local.yaml (gitignored, for development)
    4. Environment variables: DHARA_{FIELD}

    Example YAML (settings/dhara.yaml):
        mode: standard
        storage:
          path: /data/dhara.dhara
          read_only: false
        adapters:
          enable_versioning: true
          enable_health_checks: true

    Example env vars:
        export DHARA_MODE=lite
        export DHARA_STORAGE_PATH=/custom/path
        export DHARA_STORAGE_READ_ONLY=false
    """

    server_name: str = Field(default="dhara")

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

    # Dhara-specific settings
    storage: StorageConfig = Field(default_factory=StorageConfig)
    adapters: AdapterConfig = Field(default_factory=AdapterConfig)
    cloud_storage: CloudStorageConfig = Field(default_factory=CloudStorageConfig)
    time_series: TimeSeriesConfig = Field(default_factory=TimeSeriesConfig)
    ecosystem_state: EcosystemStateConfig = Field(default_factory=EcosystemStateConfig)
    authentication: AuthenticationConfig = Field(default_factory=AuthenticationConfig)
    backups: BackupRuntimeConfig = Field(default_factory=BackupRuntimeConfig)

    # Storage backend config (sqlite or postgres)
    storage_backend: str = Field(default="sqlite", description="sqlite or postgres")
    storage_pg_url: str = Field(
        default="", description="Postgres DSN for serverless mode"
    )

    # Cache backend config (memory or redis).
    # Redis connection details (URL, AUTH, TTL, jitter) now live in
    # OneiricSettings.adapters.provider_settings under the redis adapter
    # entry — see dhara/mcp/adapter_lookup.py for resolution.
    cache_backend: str = Field(default="memory", description="memory or redis")

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

    LEGACY_ENV_PREFIXES: ClassVar[tuple[str, ...]] = ("DRUVA", "DURUS")

    @classmethod
    def _apply_legacy_env_aliases(cls) -> None:
        """Mirror legacy environment variables into the canonical DHARA namespace.

        Legacy prefixes remain supported during the rename transition, but
        canonical `DHARA_*` values win if both are present.
        """
        for legacy_prefix in cls.LEGACY_ENV_PREFIXES:
            prefix = f"{legacy_prefix}_"
            for env_name, value in os.environ.items():
                if not env_name.startswith(prefix):
                    continue
                canonical_name = "DHARA_" + env_name[len(prefix) :]
                os.environ.setdefault(canonical_name, value)

    @classmethod
    def load(cls, config_name: str = "dhara") -> Self:
        """Load settings with mode-aware configuration.

        Detects mode from environment and loads appropriate config file:
        - DHARA_MODE=lite → settings/lite.yaml
        - DHARA_MODE=standard → settings/standard.yaml
        - No mode set → settings/dhara.yaml

        The loader reads ``settings/{config_file}.yaml`` and merges it with
        ``settings/local.yaml`` (if present), then applies DHARA_ env-var
        overrides. Implementation here is self-contained (not delegating to
        Oneiric's parent ``load()``) because ``OneiricMCPConfig`` is a bare
        Pydantic ``BaseModel`` and does not provide a ``load()`` classmethod.

        Args:
            config_name: Base config name (default: "dhara")

        Returns:
            Loaded DharaSettings instance
        """
        import yaml  # local import: avoids hard dep at module load time

        cls._apply_legacy_env_aliases()

        # Detect mode from environment
        mode = os.getenv("DHARA_MODE", "").lower().strip()

        # Determine config file to load
        if mode == "lite":
            config_file = "lite"
        elif mode == "standard":
            config_file = "standard"
        else:
            config_file = config_name

        # Layered YAML merge: settings/{config_file}.yaml + settings/local.yaml
        data: dict[str, Any] = {}
        project_yaml = Path("settings") / f"{config_file}.yaml"
        if project_yaml.exists():
            try:
                data = yaml.safe_load(project_yaml.read_text()) or {}
                logger.debug(f"Loaded settings from {project_yaml}")
            except Exception as e:
                logger.warning(
                    f"Could not load {project_yaml}: {e}, using defaults"
                )
                data = {}

        local_yaml = Path("settings") / "local.yaml"
        if local_yaml.exists():
            try:
                local_data = yaml.safe_load(local_yaml.read_text()) or {}
                data = _deep_merge(data, local_data)
                logger.debug(f"Merged local override from {local_yaml}")
            except Exception as e:
                logger.warning(
                    f"Could not load {local_yaml}: {e}, skipping override"
                )

        # Apply DHARA_ env-var overrides (DHARA_SECTION__FIELD=value syntax).
        env_overrides = _env_overrides("DHARA")
        if env_overrides:
            data = _deep_merge(data, env_overrides)
            logger.debug(f"Applied {len(env_overrides)} env-var override(s)")

        # Validate and instantiate DharaSettings.
        try:
            settings = cls.model_validate(data)
        except Exception as e:
            logger.warning(
                f"Could not validate loaded settings ({e}), using defaults"
            )
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

        return Path(__file__).parent.parent.parent / "settings" / "dhara.yaml"

    def health_snapshot_path(self) -> Path:
        """Get path to health snapshot file for this mode.

        Returns:
            Path to health snapshot file
        """
        snapshot_name = f"{self.mode}_dhara_health.json"
        return self.cache_root.expanduser() / snapshot_name


# Backward-compatible aliases for the in-progress dhara rename.
# DruvaSettings is provided lazily via PEP 562 __getattr__ so that
# downstream `from dhara.core.config import DruvaSettings` keeps working
# without introducing a circular import through dhara._compat.druva.


def __getattr__(name: str):
    if name == "DruvaSettings":
        from dhara._compat.druva import DruvaSettings
        return DruvaSettings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

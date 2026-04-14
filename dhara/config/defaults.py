"""Default configuration for Dhara.

This module provides configuration classes using dataclasses,
following Oneiric patterns for configuration management.
Compatible with legacy Druva/Durus patterns and no external dependencies.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class StorageConfig:
    """Storage backend configuration.

    Attributes:
        backend: Storage backend type ('file', 'sqlite', 'client', 'memory')
        path: Path to storage file (required for file/sqlite backends)
        host: Host address for client storage
        port: Port number for client storage
        read_only: Whether storage is opened in read-only mode
    """

    backend: Literal["file", "sqlite", "client", "memory"] = "memory"
    path: Path | None = None
    host: str = "localhost"
    port: int = 2972
    read_only: bool = False

    def __post_init__(self):
        """Validate storage configuration after initialization."""
        # Validate path for backends that require it
        if self.backend in ["file", "sqlite"] and not self.path:
            raise ValueError(
                f"{self.backend.capitalize()} storage requires 'path' to be specified"
            )

        # Convert path string to Path object if needed
        if self.path and isinstance(self.path, str):
            object.__setattr__(self, "path", Path(self.path))

        # Validate port range
        if not 1 <= self.port <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {self.port}")


@dataclass
class CacheConfig:
    """Cache configuration for Dhara connections.

    Attributes:
        size: Maximum number of objects in the cache
        shrink_threshold: Factor for cache shrinking (default: 2.0)
        enabled: Whether caching is enabled
    """

    size: int = 100000
    shrink_threshold: float = 2.0
    enabled: bool = True

    def __post_init__(self):
        """Validate cache configuration after initialization."""
        if self.size < 0:
            raise ValueError(f"Cache size must be non-negative, got {self.size}")

        if self.shrink_threshold < 1.0:
            raise ValueError(
                f"Shrink threshold must be >= 1.0, got {self.shrink_threshold}"
            )


@dataclass
class ConnectionConfig:
    """Connection configuration settings.

    Attributes:
        timeout: Connection timeout in seconds
        max_retries: Maximum number of connection retries
        retry_delay: Delay between retries in seconds
    """

    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0

    def __post_init__(self):
        """Validate connection configuration after initialization."""
        if self.timeout <= 0:
            raise ValueError(f"Timeout must be positive, got {self.timeout}")

        if self.max_retries < 0:
            raise ValueError(
                f"Max retries must be non-negative, got {self.max_retries}"
            )

        if self.retry_delay < 0:
            raise ValueError(
                f"Retry delay must be non-negative, got {self.retry_delay}"
            )


@dataclass
class DharaConfig:
    """Main Dhara configuration.

    This is the primary configuration class that aggregates all
    Dhara configuration settings. It follows Oneiric patterns for
    centralized configuration management.

    Attributes:
        storage: Storage backend configuration
        cache: Cache configuration
        connection: Connection configuration
        debug_mode: Enable debug mode for additional logging
    """

    storage: StorageConfig = field(default_factory=StorageConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    debug_mode: bool = False

    def __post_init__(self):
        """Validate overall configuration after initialization."""
        # Ensure all nested configs are properly initialized
        if isinstance(self.storage, dict):
            object.__setattr__(self, "storage", StorageConfig(**self.storage))
        if isinstance(self.cache, dict):
            object.__setattr__(self, "cache", CacheConfig(**self.cache))
        if isinstance(self.connection, dict):
            object.__setattr__(self, "connection", ConnectionConfig(**self.connection))

    def to_dict(self) -> dict:
        """Convert configuration to dictionary.

        Returns:
            Dictionary representation of the configuration
        """
        return {
            "storage": {
                "backend": self.storage.backend,
                "path": str(self.storage.path) if self.storage.path else None,
                "host": self.storage.host,
                "port": self.storage.port,
                "read_only": self.storage.read_only,
            },
            "cache": {
                "size": self.cache.size,
                "shrink_threshold": self.cache.shrink_threshold,
                "enabled": self.cache.enabled,
            },
            "connection": {
                "timeout": self.connection.timeout,
                "max_retries": self.connection.max_retries,
                "retry_delay": self.connection.retry_delay,
            },
            "debug_mode": self.debug_mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DharaConfig":
        """Create configuration from dictionary.

        Args:
            data: Dictionary containing configuration values

        Returns:
            DharaConfig instance

        Raises:
            ValueError: If configuration is invalid
        """
        storage_data = data.get("storage", {})
        if "path" in storage_data and isinstance(storage_data["path"], (str, Path)):
            path_val = storage_data["path"]
            storage_data["path"] = (
                Path(path_val) if isinstance(path_val, str) else path_val
            )

        return cls(
            storage=StorageConfig(**storage_data),
            cache=CacheConfig(**data.get("cache", {})),
            connection=ConnectionConfig(**data.get("connection", {})),
            debug_mode=data.get("debug_mode", False),
        )


# Legacy compatibility alias
DruvaConfig = DharaConfig

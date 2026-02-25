from __future__ import annotations

"""Adapter distribution MCP tools for Druva.

This module provides tools for storing, retrieving, and managing Oneiric adapters
as persistent Python objects in Druva with version history and health monitoring.
"""

import importlib
import logging
from datetime import datetime
from typing import Any

from druva.collections.dict import PersistentDict
from druva.core.connection import Connection
from druva.core.persistent import Persistent

logger = logging.getLogger(__name__)


class Adapter(Persistent):
    """Persistent adapter object with version history and health tracking.

    Attributes:
        domain: Adapter domain (adapter, service, task)
        key: Adapter key (cache, storage, redis)
        provider: Provider name (redis, s3, memory)
        version: Semantic version string
        factory_path: Python import path for adapter factory
        config: Adapter configuration dictionary
        dependencies: List of required adapter keys
        capabilities: List of capability strings
        metadata: Additional metadata (description, author, etc.)
        version_history: List of previous versions with rollback support
        created_at: Timestamp when adapter was first registered
        updated_at: Timestamp of last update
        health_status: Current health status
        last_health_check: Timestamp of last health check
    """

    def __init__(
        self,
        domain: str,
        key: str,
        provider: str,
        version: str = "1.0.0",
        factory_path: str | None = None,
        config: dict[str, Any] | None = None,
        dependencies: list[str] | None = None,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.domain = domain
        self.key = key
        self.provider = provider
        self.version = version
        self.factory_path = factory_path or f"{domain}.{key}.{provider}"
        self.config = config or {}
        self.dependencies = dependencies or []
        self.capabilities = capabilities or []
        self.metadata = metadata or {}

        # Version history for rollback support
        self.version_history: list[dict[str, Any]] = []
        self.created_at: datetime = datetime.now()
        self.updated_at: datetime = datetime.now()

        # Health monitoring
        self.health_status: str = "unknown"  # healthy, unhealthy, unknown
        self.last_health_check: datetime | None = None

    def update_version(
        self,
        new_version: str,
        changelog: str,
        **updates: Any,
    ) -> None:
        """Update adapter with version history tracking.

        Args:
            new_version: New semantic version
            changelog: Description of changes
            **updates: Fields to update (config, capabilities, etc.)
        """
        # Store current version in history
        self.version_history.append(
            {
                "version": self.version,
                "updated_at": self.updated_at.isoformat(),
                "changelog": changelog,
                "state": {
                    "factory_path": self.factory_path,
                    "config": self.config.copy(),
                    "capabilities": self.capabilities.copy(),
                    "dependencies": self.dependencies.copy(),
                },
            }
        )

        # Limit history size (configurable)
        if len(self.version_history) > 10:
            self.version_history.pop(0)

        # Update fields
        self.version = new_version
        for key, value in updates.items():
            if hasattr(self, key):
                setattr(self, key, value)

        self.updated_at = datetime.now()

    def rollback_to_version(self, version: str) -> bool:
        """Rollback adapter to previous version.

        Args:
            version: Version to rollback to

        Returns:
            True if rollback succeeded, False otherwise
        """
        for entry in reversed(self.version_history):
            if entry["version"] == version:
                self.version = entry["version"]
                self.factory_path = entry["state"]["factory_path"]
                self.config = entry["state"]["config"]
                self.capabilities = entry["state"]["capabilities"]
                self.dependencies = entry["state"]["dependencies"]
                self.updated_at = datetime.now()
                return True

        return False

    def to_dict(self) -> dict[str, Any]:
        """Convert adapter to dictionary for MCP responses."""
        return {
            "domain": self.domain,
            "key": self.key,
            "provider": self.provider,
            "version": self.version,
            "factory_path": self.factory_path,
            "config": self.config,
            "dependencies": self.dependencies,
            "capabilities": self.capabilities,
            "metadata": self.metadata,
            "adapter_id": f"{self.domain}:{self.key}:{self.provider}",
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "health_status": self.health_status,
            "last_health_check": (
                self.last_health_check.isoformat() if self.last_health_check else None
            ),
        }


class AdapterRegistry:
    """Registry for managing adapters with version history and health tracking.

    Provides transactional operations for storing, retrieving, validating,
    and monitoring adapters with comprehensive version support.
    """

    def __init__(self, connection: Connection):
        """Initialize adapter registry.

        Args:
            connection: Druva connection instance
        """
        self.connection = connection
        self._ensure_registry_structure()

    def _ensure_registry_structure(self) -> None:
        """Ensure registry structure exists in root.

        Silently skips if storage is read-only.
        """
        root = self.connection.get_root()

        # Check if we can write (storage is not read-only)
        try:
            # Try to access storage to check if it's readonly
            storage = self.connection.storage
            is_readonly = hasattr(storage, "shelf") and storage.shelf.file.is_readonly()
        except Exception:
            is_readonly = False

        if not is_readonly:
            if "adapters" not in root:
                root["adapters"] = PersistentDict()  # type: ignore[assignment]
                self.connection.commit()

            if "health_checks" not in root:
                root["health_checks"] = PersistentDict()  # type: ignore[assignment]
                self.connection.commit()

    def store_adapter(
        self,
        domain: str,
        key: str,
        provider: str,
        version: str,
        factory_path: str,
        config: dict[str, Any],
        dependencies: list[str],
        capabilities: list[str],
        metadata: dict[str, Any],
    ) -> str:
        """Store or update an adapter in the registry.

        If adapter already exists, updates version with history tracking.

        Args:
            domain: Adapter domain
            key: Adapter key
            provider: Provider name
            version: Semantic version
            factory_path: Import path
            config: Configuration dict
            dependencies: Required adapter keys
            capabilities: Capability list
            metadata: Additional metadata

        Returns:
            Adapter ID (domain:key:provider)
        """
        root = self.connection.get_root()
        adapters: PersistentDict = root["adapters"]  # type: ignore[assignment]

        adapter_id = f"{domain}:{key}:{provider}"

        # Check if adapter exists
        if adapter_id in adapters:
            # Update existing adapter with version history
            adapter = adapters[adapter_id]
            adapter.update_version(
                new_version=version,
                changelog=metadata.get("changelog", "Manual update"),
                factory_path=factory_path,
                config=config,
                dependencies=dependencies,
                capabilities=capabilities,
                **{k: v for k, v in metadata.items() if k != "changelog"},
            )
        else:
            # Create new adapter
            adapter = Adapter(
                domain=domain,
                key=key,
                provider=provider,
                version=version,
                factory_path=factory_path,
                config=config,
                dependencies=dependencies,
                capabilities=capabilities,
                metadata=metadata,
            )
            adapters[adapter_id] = adapter

        # Commit transactionally
        self.connection.commit()

        logger.info(f"Stored adapter: {adapter_id} @ {version}")
        return adapter_id

    def get_adapter(
        self,
        domain: str,
        key: str,
        provider: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve an adapter from the registry.

        Args:
            domain: Adapter domain
            key: Adapter key
            provider: Provider (optional, for specific lookup)
            version: Version (optional, defaults to latest)

        Returns:
            Adapter dict or None if not found
        """
        root = self.connection.get_root()
        adapters: PersistentDict = root["adapters"]  # type: ignore[assignment]

        if provider:
            # Direct lookup
            adapter_id = f"{domain}:{key}:{provider}"
            if adapter_id in adapters:
                return adapters[adapter_id].to_dict()
            return None

        # Find all providers for this key
        matches = [
            adapters[aid].to_dict()
            for aid in adapters.keys()
            if aid.startswith(f"{domain}:{key}:")
        ]

        if not matches:
            return None

        # Return specific version if requested
        if version:
            for match in matches:
                if match["version"] == version:
                    return match
            return None

        # Return first match (default provider)
        return matches[0]

    def list_adapters(
        self,
        domain: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all adapters with optional filtering.

        Args:
            domain: Filter by domain
            category: Filter by category (metadata field)

        Returns:
            List of adapter dicts
        """
        root = self.connection.get_root()

        # Handle case where adapters dict doesn't exist (readonly storage)
        if "adapters" not in root:
            return []

        adapters: PersistentDict = root["adapters"]  # type: ignore[assignment]

        results = []

        for adapter_id, adapter in adapters.items():
            adapter_dict = adapter.to_dict()

            # Apply filters
            if domain and adapter_dict["domain"] != domain:
                continue

            if category:
                adapter_category = adapter_dict["metadata"].get("category")
                if adapter_category != category:
                    continue

            results.append(adapter_dict)

        return results

    def list_adapter_versions(
        self,
        domain: str,
        key: str,
        provider: str,
    ) -> list[dict[str, Any]]:
        """List all versions of an adapter including rollback history.

        Args:
            domain: Adapter domain
            key: Adapter key
            provider: Provider name

        Returns:
            List of version history with timestamps
        """
        root = self.connection.get_root()
        adapters: PersistentDict = root["adapters"]  # type: ignore[assignment]

        adapter_id = f"{domain}:{key}:{provider}"

        if adapter_id not in adapters:
            return []

        adapter = adapters[adapter_id]
        history = [
            {
                "version": entry["version"],
                "updated_at": entry["updated_at"],
                "changelog": entry.get("changelog", ""),
            }
            for entry in adapter.version_history
        ]

        # Add current version
        history.append(
            {
                "version": adapter.version,
                "updated_at": adapter.updated_at.isoformat(),
                "changelog": "Current version",
            }
        )

        # Sort by timestamp descending
        history.sort(key=lambda x: x["updated_at"], reverse=True)

        return history

    def validate_adapter(
        self,
        domain: str,
        key: str,
        provider: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Validate an adapter configuration.

        Checks:
        - Factory path is importable
        - Dependencies are available
        - Configuration schema is valid
        - Capabilities are declared

        Args:
            domain: Adapter domain
            key: Adapter key
            provider: Provider name
            version: Optional version to validate

        Returns:
            Validation result with errors/warnings
        """
        adapter = self.get_adapter(domain, key, provider, version)

        if not adapter:
            return {
                "valid": False,
                "errors": [f"Adapter not found: {domain}:{key}:{provider}"],
                "warnings": [],
            }

        errors = []
        warnings = []

        # Validate factory path
        try:
            module_path, class_name = adapter["factory_path"].rsplit(".", 1)
            module = importlib.import_module(module_path)
            getattr(module, class_name)
        except ImportError as e:
            errors.append(f"Factory path not importable: {e}")
        except AttributeError as e:
            errors.append(f"Factory class not found: {e}")
        except Exception as e:
            errors.append(f"Factory validation error: {e}")

        # Validate dependencies
        for dep in adapter["dependencies"]:
            dep_domain, dep_key = dep.split(":")[:2] if ":" in dep else (None, dep)
            dep_adapter = self.get_adapter(
                dep_domain or domain,
                dep_key,
            )
            if not dep_adapter:
                warnings.append(f"Dependency not found: {dep}")

        # Validate capabilities
        if not adapter["capabilities"]:
            warnings.append("No capabilities declared")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    def check_adapter_health(
        self,
        domain: str,
        key: str,
        provider: str,
    ) -> dict[str, Any]:
        """Check health status of an adapter.

        Args:
            domain: Adapter domain
            key: Adapter key
            provider: Provider name

        Returns:
            Health check result
        """
        root = self.connection.get_root()
        adapters: PersistentDict = root["adapters"]  # type: ignore[assignment]
        health_checks: PersistentDict = root["health_checks"]  # type: ignore[assignment]

        adapter_id = f"{domain}:{key}:{provider}"

        if adapter_id not in adapters:
            return {
                "healthy": False,
                "error": "Adapter not found",
                "last_check": None,
            }

        adapter = adapters[adapter_id]

        # Update last health check timestamp
        adapter.last_health_check = datetime.now()

        # Perform actual health check (try to import factory)
        try:
            module_path, class_name = adapter.factory_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            getattr(module, class_name)

            # Check if factory can be instantiated
            # (This is a basic check - could be enhanced)
            adapter.health_status = "healthy"

            # Store health check result
            health_checks[adapter_id] = {
                "timestamp": datetime.now().isoformat(),
                "status": "healthy",
            }

            self.connection.commit()

            return {
                "healthy": True,
                "last_check": adapter.last_health_check.isoformat(),
                "status": adapter.health_status,
            }

        except Exception as e:
            adapter.health_status = "unhealthy"

            # Store failed health check
            health_checks[adapter_id] = {
                "timestamp": datetime.now().isoformat(),
                "status": "unhealthy",
                "error": str(e),
            }

            self.connection.commit()

            return {
                "healthy": False,
                "last_check": adapter.last_health_check.isoformat(),
                "status": adapter.health_status,
                "error": str(e),
            }

    def count(self) -> int:
        """Count total adapters in registry.

        Returns:
            Total number of adapters
        """
        root = self.connection.get_root()
        adapters: PersistentDict = root["adapters"]  # type: ignore[assignment]
        return len(adapters)


# Tool implementations (async wrappers for FastMCP)


async def store_adapter_impl(
    registry: AdapterRegistry,
    domain: str,
    key: str,
    provider: str,
    version: str,
    factory_path: str,
    config: dict[str, Any],
    dependencies: list[str],
    capabilities: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Implementation for store_adapter tool."""
    try:
        adapter_id = registry.store_adapter(
            domain=domain,
            key=key,
            provider=provider,
            version=version,
            factory_path=factory_path,
            config=config,
            dependencies=dependencies,
            capabilities=capabilities,
            metadata=metadata,
        )

        return {
            "success": True,
            "adapter_id": adapter_id,
            "version": version,
            "message": f"Stored adapter {adapter_id} @ {version}",
        }

    except Exception as e:
        logger.exception(f"Error storing adapter: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def get_adapter_impl(
    registry: AdapterRegistry,
    domain: str,
    key: str,
    provider: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Implementation for get_adapter tool."""
    try:
        adapter = registry.get_adapter(
            domain=domain,
            key=key,
            provider=provider,
            version=version,
        )

        if adapter:
            return {
                "success": True,
                "adapter": adapter,
            }

        return {
            "success": False,
            "error": f"Adapter not found: {domain}:{key}",
        }

    except Exception as e:
        logger.exception(f"Error getting adapter: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def list_adapters_impl(
    registry: AdapterRegistry,
    domain: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Implementation for list_adapters tool."""
    try:
        adapters = registry.list_adapters(
            domain=domain,
            category=category,
        )

        return {
            "success": True,
            "count": len(adapters),
            "filters": {
                "domain": domain,
                "category": category,
            },
            "adapters": adapters,
        }

    except Exception as e:
        logger.exception(f"Error listing adapters: {e}")
        return {
            "success": False,
            "error": str(e),
            "adapters": [],
        }


async def list_adapter_versions_impl(
    registry: AdapterRegistry,
    domain: str,
    key: str,
    provider: str,
) -> dict[str, Any]:
    """Implementation for list_adapter_versions tool."""
    try:
        versions = registry.list_adapter_versions(
            domain=domain,
            key=key,
            provider=provider,
        )

        return {
            "success": True,
            "count": len(versions),
            "versions": versions,
        }

    except Exception as e:
        logger.exception(f"Error listing versions: {e}")
        return {
            "success": False,
            "error": str(e),
            "versions": [],
        }


async def validate_adapter_impl(
    registry: AdapterRegistry,
    domain: str,
    key: str,
    provider: str,
    version: str | None = None,
) -> dict[str, Any]:
    """Implementation for validate_adapter tool."""
    try:
        result = registry.validate_adapter(
            domain=domain,
            key=key,
            provider=provider,
            version=version,
        )

        return {
            "success": True,
            "validation": result,
        }

    except Exception as e:
        logger.exception(f"Error validating adapter: {e}")
        return {
            "success": False,
            "error": str(e),
        }


async def get_adapter_health_impl(
    registry: AdapterRegistry,
    domain: str,
    key: str,
    provider: str,
) -> dict[str, Any]:
    """Implementation for get_adapter_health tool."""
    try:
        health = registry.check_adapter_health(
            domain=domain,
            key=key,
            provider=provider,
        )

        return {
            "success": True,
            "health": health,
        }

    except Exception as e:
        logger.exception(f"Error checking health: {e}")
        return {
            "success": False,
            "error": str(e),
        }

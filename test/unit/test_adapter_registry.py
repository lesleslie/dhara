"""Unit tests for AdapterRegistry and Adapter persistent objects.

Tests the adapter distribution functionality including:
- Adapter creation and persistence
- Version management and rollback
- Adapter registry operations
- Health checking
- Validation
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from dhara.core import Connection
from dhara.mcp.adapter_tools import (
    Adapter,
    AdapterRegistry,
    get_adapter_health_impl,
    get_adapter_impl,
    list_adapter_versions_impl,
    list_adapters_impl,
    store_adapter_impl,
    validate_adapter_impl,
)
from dhara.storage.file import FileStorage


@pytest.mark.unit
class TestAdapter:
    """Test Adapter persistent object."""

    def test_adapter_creation(self):
        """Test creating an Adapter with all fields."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="oneiric.adapters.cache.RedisAdapter",
            config={"host": "localhost", "port": 6379},
            dependencies=[],
            capabilities=["get", "set", "delete"],
            metadata={"description": "Redis cache adapter"},
        )

        assert adapter.domain == "adapter"
        assert adapter.key == "cache"
        assert adapter.provider == "redis"
        assert adapter.version == "1.0.0"
        assert adapter.factory_path == "oneiric.adapters.cache.RedisAdapter"
        assert adapter.config == {"host": "localhost", "port": 6379}
        assert adapter.capabilities == ["get", "set", "delete"]
        assert adapter.metadata["description"] == "Redis cache adapter"
        assert adapter.health_status == "unknown"
        assert len(adapter.version_history) == 0

    def test_adapter_defaults(self):
        """Test Adapter with default values."""
        adapter = Adapter(
            domain="service",
            key="storage",
            provider="s3",
        )

        assert adapter.version == "1.0.0"
        assert adapter.factory_path == "service.storage.s3"
        assert adapter.config == {}
        assert adapter.dependencies == []
        assert adapter.capabilities == []
        assert adapter.metadata == {}
        assert isinstance(adapter.created_at, datetime)
        assert isinstance(adapter.updated_at, datetime)

    def test_adapter_to_dict(self):
        """Test converting Adapter to dictionary."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="oneiric.adapters.cache.RedisAdapter",
            config={"host": "localhost"},
        )

        result = adapter.to_dict()

        assert result["domain"] == "adapter"
        assert result["key"] == "cache"
        assert result["provider"] == "redis"
        assert result["version"] == "1.0.0"
        assert result["adapter_id"] == "adapter:cache:redis"
        assert "created_at" in result
        assert "updated_at" in result
        assert result["health_status"] == "unknown"

    def test_update_version(self):
        """Test updating adapter version with history tracking."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="old.path.Adapter",
            config={"host": "localhost"},
            capabilities=["get"],
        )

        # Update version
        adapter.update_version(
            new_version="2.0.0",
            changelog="Added support for clustered Redis",
            factory_path="new.path.Adapter",
            config={"host": "localhost", "cluster": True},
            capabilities=["get", "set"],
        )

        assert adapter.version == "2.0.0"
        assert adapter.factory_path == "new.path.Adapter"
        assert adapter.config["cluster"] is True
        assert "set" in adapter.capabilities
        assert len(adapter.version_history) == 1

        # Check history
        history = adapter.version_history[0]
        assert history["version"] == "1.0.0"
        assert history["changelog"] == "Added support for clustered Redis"
        assert history["state"]["factory_path"] == "old.path.Adapter"
        assert history["state"]["config"]["host"] == "localhost"

    def test_version_history_limit(self):
        """Test that version history is limited to 10 entries."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
        )

        # Add 15 versions
        for i in range(15):
            adapter.update_version(
                new_version=f"{i}.0.0",
                changelog=f"Version {i}",
            )

        # Should only keep last 10 + current
        assert len(adapter.version_history) == 10
        assert adapter.version == "14.0.0"

    def test_rollback_to_version(self):
        """Test rolling back adapter to previous version."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="v1.Adapter",
            config={"setting": "v1"},
            capabilities=["v1"],
        )

        # Update to v2
        adapter.update_version(
            new_version="2.0.0",
            changelog="Upgrade to v2",
            factory_path="v2.Adapter",
            config={"setting": "v2"},
            capabilities=["v2"],
        )

        # Update to v3
        adapter.update_version(
            new_version="3.0.0",
            changelog="Upgrade to v3",
            factory_path="v3.Adapter",
            config={"setting": "v3"},
            capabilities=["v3"],
        )

        # Rollback to v2
        success = adapter.rollback_to_version("2.0.0")

        assert success is True
        assert adapter.version == "2.0.0"
        assert adapter.factory_path == "v2.Adapter"
        assert adapter.config["setting"] == "v2"
        assert adapter.capabilities == ["v2"]

    def test_rollback_nonexistent_version(self):
        """Test rolling back to a version that doesn't exist."""
        adapter = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
        )

        success = adapter.rollback_to_version("99.0.0")

        assert success is False
        assert adapter.version == "1.0.0"


@pytest.mark.unit
class TestAdapterRegistry:
    """Test AdapterRegistry operations."""

    @pytest.fixture
    def registry(self, connection: Connection) -> AdapterRegistry:
        """Create AdapterRegistry for testing."""
        return AdapterRegistry(connection)

    @pytest.fixture
    def sample_adapter_dict(self) -> dict:
        """Sample adapter data for testing."""
        return {
            "domain": "adapter",
            "key": "cache",
            "provider": "redis",
            "version": "1.0.0",
            "factory_path": "oneiric.adapters.cache.RedisAdapter",
            "config": {"host": "localhost", "port": 6379},
            "dependencies": [],
            "capabilities": ["get", "set", "delete"],
            "metadata": {"description": "Redis cache adapter"},
        }

    def test_registry_initialization(self, registry: AdapterRegistry):
        """Test registry creates required structure."""
        root = registry.connection.get_root()

        assert "adapters" in root
        assert "health_checks" in root

    def test_store_adapter(self, registry: AdapterRegistry, sample_adapter_dict: dict):
        """Test storing a new adapter."""
        adapter_id = registry.store_adapter(
            domain=sample_adapter_dict["domain"],
            key=sample_adapter_dict["key"],
            provider=sample_adapter_dict["provider"],
            version=sample_adapter_dict["version"],
            factory_path=sample_adapter_dict["factory_path"],
            config=sample_adapter_dict["config"],
            dependencies=sample_adapter_dict["dependencies"],
            capabilities=sample_adapter_dict["capabilities"],
            metadata=sample_adapter_dict["metadata"],
        )

        assert adapter_id == "adapter:cache:redis"

        # Verify it was stored
        root = registry.connection.get_root()
        adapters = root["adapters"]
        assert adapter_id in adapters

        stored = adapters[adapter_id]
        assert stored.version == "1.0.0"
        assert stored.factory_path == "oneiric.adapters.cache.RedisAdapter"

    def test_update_existing_adapter(self, registry: AdapterRegistry, sample_adapter_dict: dict):
        """Test updating an existing adapter creates version history."""
        # Store initial version
        registry.store_adapter(**sample_adapter_dict)

        # Update with new version
        sample_adapter_dict["version"] = "2.0.0"
        sample_adapter_dict["factory_path"] = "new.path.Adapter"
        sample_adapter_dict["metadata"]["changelog"] = "Breaking changes"

        adapter_id = registry.store_adapter(**sample_adapter_dict)

        assert adapter_id == "adapter:cache:redis"

        # Verify version history
        root = registry.connection.get_root()
        adapter = root["adapters"][adapter_id]

        assert adapter.version == "2.0.0"
        assert adapter.factory_path == "new.path.Adapter"
        assert len(adapter.version_history) == 1
        assert adapter.version_history[0]["version"] == "1.0.0"

    def test_get_adapter(self, registry: AdapterRegistry, sample_adapter_dict: dict):
        """Test retrieving an adapter."""
        registry.store_adapter(**sample_adapter_dict)

        adapter = registry.get_adapter(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert adapter is not None
        assert adapter["domain"] == "adapter"
        assert adapter["key"] == "cache"
        assert adapter["provider"] == "redis"
        assert adapter["version"] == "1.0.0"

    def test_get_adapter_not_found(self, registry: AdapterRegistry):
        """Test getting a non-existent adapter."""
        adapter = registry.get_adapter(
            domain="adapter",
            key="nonexistent",
            provider="none",
        )

        assert adapter is None

    def test_list_adapters(self, registry: AdapterRegistry):
        """Test listing all adapters."""
        # Store multiple adapters
        registry.store_adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="cache.RedisAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={"category": "cache"},
        )

        registry.store_adapter(
            domain="adapter",
            key="cache",
            provider="memcached",
            version="1.0.0",
            factory_path="cache.MemcachedAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={"category": "cache"},
        )

        registry.store_adapter(
            domain="service",
            key="storage",
            provider="s3",
            version="1.0.0",
            factory_path="storage.S3Adapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={"category": "storage"},
        )

        # List all
        all_adapters = registry.list_adapters()
        assert len(all_adapters) == 3

        # Filter by domain
        cache_adapters = registry.list_adapters(domain="adapter")
        assert len(cache_adapters) == 2

        # Filter by category
        storage_adapters = registry.list_adapters(category="storage")
        assert len(storage_adapters) == 1
        assert storage_adapters[0]["provider"] == "s3"

    def test_list_adapter_versions(self, registry: AdapterRegistry, sample_adapter_dict: dict):
        """Test listing adapter version history."""
        # Store initial version
        registry.store_adapter(**sample_adapter_dict)

        # Update twice
        for i in range(2, 4):
            sample_adapter_dict["version"] = f"{i}.0.0"
            registry.store_adapter(**sample_adapter_dict)

        # List versions
        versions = registry.list_adapter_versions(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert len(versions) == 3  # 2 historical + current
        assert versions[0]["version"] == "3.0.0"  # Most recent first
        assert versions[1]["version"] == "2.0.0"
        assert versions[2]["version"] == "1.0.0"

    def test_list_versions_nonexistent_adapter(self, registry: AdapterRegistry):
        """Test listing versions for non-existent adapter."""
        versions = registry.list_adapter_versions(
            domain="adapter",
            key="nonexistent",
            provider="none",
        )

        assert versions == []

    def test_validate_adapter_success(self, registry: AdapterRegistry, sample_adapter_dict: dict):
        """Test validating a valid adapter configuration."""
        # Use a real factory path that exists
        sample_adapter_dict["factory_path"] = "druva.core.persistent.PersistentBase"

        registry.store_adapter(**sample_adapter_dict)

        result = registry.validate_adapter(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_adapter_not_found(self, registry: AdapterRegistry):
        """Test validating a non-existent adapter."""
        result = registry.validate_adapter(
            domain="adapter",
            key="nonexistent",
            provider="none",
        )

        assert result["valid"] is False
        assert "not found" in result["errors"][0].lower()

    @patch("druva.mcp.adapter_tools.importlib")
    def test_validate_adapter_import_error(
        self, mock_importlib: Mock, registry: AdapterRegistry, sample_adapter_dict: dict
    ):
        """Test validation with import error."""
        # Mock import to fail
        mock_importlib.import_module.side_effect = ImportError("No module named 'fake'")

        registry.store_adapter(**sample_adapter_dict)

        result = registry.validate_adapter(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert "import" in result["errors"][0].lower()

    def test_check_adapter_health_healthy(self, registry: AdapterRegistry, sample_adapter_dict: dict):
        """Test health check for healthy adapter."""
        # Use a real factory path
        sample_adapter_dict["factory_path"] = "druva.core.persistent.PersistentBase"
        registry.store_adapter(**sample_adapter_dict)

        result = registry.check_adapter_health(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["healthy"] is True
        assert result["status"] == "healthy"
        assert "last_check" in result

    def test_check_adapter_health_unhealthy(
        self, registry: AdapterRegistry, sample_adapter_dict: dict
    ):
        """Test health check for unhealthy adapter."""
        registry.store_adapter(**sample_adapter_dict)

        result = registry.check_adapter_health(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["healthy"] is False
        assert result["status"] == "unhealthy"
        assert "error" in result

    def test_check_adapter_health_not_found(self, registry: AdapterRegistry):
        """Test health check for non-existent adapter."""
        result = registry.check_adapter_health(
            domain="adapter",
            key="nonexistent",
            provider="none",
        )

        assert result["healthy"] is False
        assert result["error"] == "Adapter not found"

    def test_count(self, registry: AdapterRegistry):
        """Test counting adapters in registry."""
        assert registry.count() == 0

        registry.store_adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="cache.RedisAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        assert registry.count() == 1

        registry.store_adapter(
            domain="adapter",
            key="cache",
            provider="memcached",
            version="1.0.0",
            factory_path="cache.MemcachedAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        assert registry.count() == 2


@pytest.mark.unit
@pytest.mark.asyncio
class TestAdapterImpls:
    """Test async implementation functions for MCP tools."""

    @pytest.fixture
    def registry(self, connection: Connection) -> AdapterRegistry:
        """Create AdapterRegistry for testing."""
        return AdapterRegistry(connection)

    async def test_store_adapter_impl(self, registry: AdapterRegistry):
        """Test store_adapter async implementation."""
        result = await store_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="cache.RedisAdapter",
            config={"host": "localhost"},
            dependencies=[],
            capabilities=["get", "set"],
            metadata={"description": "Redis adapter"},
        )

        assert result["success"] is True
        assert result["adapter_id"] == "adapter:cache:redis"
        assert result["version"] == "1.0.0"

    async def test_get_adapter_impl(self, registry: AdapterRegistry):
        """Test get_adapter async implementation."""
        # First store an adapter
        await store_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="cache.RedisAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        # Then retrieve it
        result = await get_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["success"] is True
        assert result["adapter"]["version"] == "1.0.0"

    async def test_list_adapters_impl(self, registry: AdapterRegistry):
        """Test list_adapters async implementation."""
        # Store multiple adapters
        for i in range(3):
            await store_adapter_impl(
                registry=registry,
                domain="adapter",
                key=f"cache{i}",
                provider="redis",
                version="1.0.0",
                factory_path=f"cache.Adapter{i}",
                config={},
                dependencies=[],
                capabilities=[],
                metadata={},
            )

        result = await list_adapters_impl(registry=registry)

        assert result["success"] is True
        assert result["count"] == 3
        assert len(result["adapters"]) == 3

    async def test_list_adapter_versions_impl(self, registry: AdapterRegistry):
        """Test list_adapter_versions async implementation."""
        # Store adapter with multiple versions
        await store_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="cache.RedisAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        await store_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="2.0.0",
            factory_path="cache.RedisAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        result = await list_adapter_versions_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["success"] is True
        assert result["count"] == 2

    async def test_validate_adapter_impl(self, registry: AdapterRegistry):
        """Test validate_adapter async implementation."""
        # First store an adapter
        await store_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="druva.core.persistent.PersistentBase",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        result = await validate_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["success"] is True
        assert "validation" in result

    async def test_get_adapter_health_impl(self, registry: AdapterRegistry):
        """Test get_adapter_health async implementation."""
        # First store an adapter
        await store_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="druva.core.persistent.PersistentBase",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        result = await get_adapter_health_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["success"] is True
        assert "health" in result

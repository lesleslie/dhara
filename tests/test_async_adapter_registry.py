"""Tests for dhara.mcp.adapter_tools.AsyncAdapterRegistry async methods."""

from __future__ import annotations

import pytest

from dhara.mcp.adapter_tools import AsyncAdapterRegistry
from dhara.storage.memory import AsyncMemoryStorage
from dhara.core.connection import AsyncConnection


class TestStoreAdapterAsync:
    @pytest.mark.asyncio
    async def test_store_adapter_async_creates_new(self):
        """store_adapter_async creates a new adapter record."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        adapter_id = await registry.store_adapter_async(
            domain="cache",
            key="redis",
            provider="redis-provider",
            version="1.0.0",
            factory_path="my.cache.RedisFactory",
            config={"host": "localhost", "port": 6379},
            dependencies=[],
            capabilities=["get", "set", "delete"],
            metadata={"category": "storage"},
        )
        assert adapter_id == "cache:redis:redis-provider"

    @pytest.mark.asyncio
    async def test_store_adapter_async_updates_existing(self):
        """store_adapter_async updates an existing adapter with version history."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        await registry.store_adapter_async(
            domain="cache",
            key="redis",
            provider="redis-provider",
            version="1.0.0",
            factory_path="my.cache.RedisFactory",
            config={"host": "localhost"},
            dependencies=[],
            capabilities=["get"],
            metadata={},
        )

        await registry.store_adapter_async(
            domain="cache",
            key="redis",
            provider="redis-provider",
            version="2.0.0",
            factory_path="my.cache.RedisFactory",
            config={"host": "localhost", "port": 6379},
            dependencies=[],
            capabilities=["get", "set"],
            metadata={"changelog": "Added set capability"},
        )

        adapter = await registry.get_adapter_async(
            domain="cache",
            key="redis",
            provider="redis-provider",
        )
        assert adapter is not None
        assert adapter["version"] == "2.0.0"
        # version_history is internal; verify via list_adapter_versions_async
        versions = await registry.list_adapter_versions_async(
            domain="cache",
            key="redis",
            provider="redis-provider",
        )
        assert len(versions) == 2  # v1 in history + v2 current


class TestGetAdapterAsync:
    @pytest.mark.asyncio
    async def test_get_adapter_async_existing(self):
        """get_adapter_async retrieves an existing adapter."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        await registry.store_adapter_async(
            domain="storage",
            key="s3",
            provider="aws",
            version="1.0.0",
            factory_path="my.storage.S3Factory",
            config={"bucket": "my-bucket"},
            dependencies=[],
            capabilities=["upload", "download"],
            metadata={},
        )

        adapter = await registry.get_adapter_async(
            domain="storage",
            key="s3",
            provider="aws",
        )
        assert adapter is not None
        assert adapter["domain"] == "storage"
        assert adapter["key"] == "s3"
        assert adapter["provider"] == "aws"

    @pytest.mark.asyncio
    async def test_get_adapter_async_missing(self):
        """get_adapter_async returns None for missing adapter."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        adapter = await registry.get_adapter_async(
            domain="nonexistent",
            key="missing",
            provider="unknown",
        )
        assert adapter is None


class TestListAdaptersAsync:
    @pytest.mark.asyncio
    async def test_list_adapters_async_all(self):
        """list_adapters_async returns all adapters."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        await registry.store_adapter_async(
            domain="cache", key="redis", provider="redis",
            version="1.0.0", factory_path="f1", config={},
            dependencies=[], capabilities=[], metadata={},
        )
        await registry.store_adapter_async(
            domain="cache", key="memcached", provider="mem",
            version="1.0.0", factory_path="f2", config={},
            dependencies=[], capabilities=[], metadata={},
        )
        await registry.store_adapter_async(
            domain="storage", key="s3", provider="aws",
            version="1.0.0", factory_path="f3", config={},
            dependencies=[], capabilities=[], metadata={},
        )

        adapters = await registry.list_adapters_async()
        assert len(adapters) == 3

    @pytest.mark.asyncio
    async def test_list_adapters_async_filtered_by_domain(self):
        """list_adapters_async filters by domain."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        await registry.store_adapter_async(
            domain="cache", key="redis", provider="redis",
            version="1.0.0", factory_path="f1", config={},
            dependencies=[], capabilities=[], metadata={},
        )
        await registry.store_adapter_async(
            domain="cache", key="memcached", provider="mem",
            version="1.0.0", factory_path="f2", config={},
            dependencies=[], capabilities=[], metadata={},
        )
        await registry.store_adapter_async(
            domain="storage", key="s3", provider="aws",
            version="1.0.0", factory_path="f3", config={},
            dependencies=[], capabilities=[], metadata={},
        )

        cache_adapters = await registry.list_adapters_async(domain="cache")
        assert len(cache_adapters) == 2


class TestListAdapterVersionsAsync:
    @pytest.mark.asyncio
    async def test_list_adapter_versions_async(self):
        """list_adapter_versions_async returns version history."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        await registry.store_adapter_async(
            domain="cache", key="redis", provider="redis",
            version="1.0.0", factory_path="f1", config={},
            dependencies=[], capabilities=[], metadata={},
        )
        await registry.store_adapter_async(
            domain="cache", key="redis", provider="redis",
            version="2.0.0", factory_path="f1", config={},
            dependencies=[], capabilities=[], metadata={"changelog": "v2"},
        )

        versions = await registry.list_adapter_versions_async(
            domain="cache",
            key="redis",
            provider="redis",
        )
        assert len(versions) == 2  # v1 (history) + v2 (current)


class TestValidateAdapterAsync:
    @pytest.mark.asyncio
    async def test_validate_adapter_async_missing(self):
        """validate_adapter_async returns error for missing adapter."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        result = await registry.validate_adapter_async(
            domain="nonexistent",
            key="missing",
            provider="unknown",
        )
        assert result["valid"] is False
        assert "not found" in result["errors"][0]


class TestCheckAdapterHealthAsync:
    @pytest.mark.asyncio
    async def test_check_adapter_health_async_not_found(self):
        """check_adapter_health_async returns unhealthy for missing adapter."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        registry = AsyncAdapterRegistry(conn)

        result = await registry.check_adapter_health_async(
            domain="nonexistent",
            key="missing",
            provider="unknown",
        )
        assert result["healthy"] is False
        assert result["error"] == "Adapter not found"

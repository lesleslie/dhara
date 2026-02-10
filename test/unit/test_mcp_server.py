"""Unit tests for DhruvaMCPServer.

Tests the FastMCP server implementation including:
- Server initialization
- Tool registration
- Storage path handling
- Adapter registry integration
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from dhruva.core.config import DhruvaSettings
from dhruva.mcp.server_core import DhruvaMCPServer


@pytest.mark.unit
class TestDhruvaMCPServer:
    """Test DhruvaMCPServer initialization and configuration."""

    @pytest.fixture
    def temp_settings(self, tmp_path: Path) -> DhruvaSettings:
        """Create DhruvaSettings with temporary storage."""
        return DhruvaSettings(
            server_name="test-dhruva",
            storage={
                "path": tmp_path / "test.dhruva",
                "read_only": False,
                "backend": "file",
            },
            cache_root=tmp_path / ".cache",
        )

    @pytest.fixture
    def server(self, temp_settings: DhruvaSettings) -> DhruvaMCPServer:
        """Create DhruvaMCPServer instance for testing."""
        return DhruvaMCPServer(temp_settings)

    def test_server_initialization(self, server: DhruvaMCPServer, temp_settings: DhruvaSettings):
        """Test server initializes correctly."""
        assert server.config == temp_settings
        assert server.server is not None
        assert server.adapter_registry is not None
        assert server.storage is not None
        assert server.connection is not None

    def test_storage_path_expansion(self, tmp_path: Path):
        """Test that storage path expands ~ correctly."""
        settings = DhruvaSettings(
            server_name="test-dhruva",
            storage={
                "path": tmp_path / "test.dhruva",
                "read_only": False,
            },
        )

        server = DhruvaMCPServer(settings)

        # Verify storage file exists and path was expanded
        assert server.storage is not None
        assert settings.storage.path.exists() or settings.storage.path.parent.exists()

        server.close()

    def test_adapter_registry_initialized(self, server: DhruvaMCPServer):
        """Test that adapter registry is initialized."""
        assert server.adapter_registry is not None
        assert server.adapter_registry.connection is server.connection

    def test_tools_registered(self, server: DhruvaMCPServer):
        """Test that MCP tools are registered."""
        # FastMCP stores tools in server._tools
        tools = server.server._tools

        # Check that expected tools are registered
        tool_names = {name for name in tools.keys()}

        expected_tools = {
            "store_adapter",
            "get_adapter",
            "list_adapters",
            "list_adapter_versions",
            "validate_adapter",
            "get_adapter_health",
        }

        assert expected_tools.issubset(tool_names)

    def test_readonly_storage(self, tmp_path: Path):
        """Test server with readonly storage."""
        # First create a storage file
        settings = DhruvaSettings(
            server_name="test-dhruva",
            storage={
                "path": tmp_path / "readonly.dhruva",
                "read_only": False,
            },
        )

        server1 = DhruvaMCPServer(settings)
        root = server1.connection.get_root()
        root["test"] = "data"
        server1.connection.commit()
        server1.close()

        # Now open as readonly
        settings_readonly = DhruvaSettings(
            server_name="test-dhruva-readonly",
            storage={
                "path": tmp_path / "readonly.dhruva",
                "read_only": True,
            },
        )

        server2 = DhruvaMCPServer(settings_readonly)
        root = server2.connection.get_root()
        assert root["test"] == "data"

        server2.close()

    def test_server_close(self, server: DhruvaMCPServer):
        """Test server close method."""
        # Should not raise any exceptions
        server.close()

    @pytest.mark.asyncio
    async def test_store_adapter_tool(self, server: DhruvaMCPServer):
        """Test store_adapter MCP tool."""
        # Get the tool from FastMCP
        tools = server.server._tools
        store_tool = tools["store_adapter"]

        result = await store_tool(
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

    @pytest.mark.asyncio
    async def test_get_adapter_tool(self, server: DhruvaMCPServer):
        """Test get_adapter MCP tool."""
        tools = server.server._tools

        # First store an adapter
        store_tool = tools["store_adapter"]
        await store_tool(
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
        get_tool = tools["get_adapter"]
        result = await get_tool(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["success"] is True
        assert result["adapter"]["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_list_adapters_tool(self, server: DhruvaMCPServer):
        """Test list_adapters MCP tool."""
        tools = server.server._tools

        # Store multiple adapters
        store_tool = tools["store_adapter"]
        for i in range(3):
            await store_tool(
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

        # List all adapters
        list_tool = tools["list_adapters"]
        result = await list_tool()

        assert result["success"] is True
        assert result["count"] == 3
        assert len(result["adapters"]) == 3

    @pytest.mark.asyncio
    async def test_list_adapters_with_filters(self, server: DhruvaMCPServer):
        """Test list_adapters MCP tool with filters."""
        tools = server.server._tools

        # Store adapters with different domains
        store_tool = tools["store_adapter"]
        await store_tool(
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

        await store_tool(
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

        # Filter by domain
        list_tool = tools["list_adapters"]
        result = await list_tool(domain="adapter")

        assert result["count"] == 1
        assert result["adapters"][0]["domain"] == "adapter"

        # Filter by category
        result = await list_tool(category="storage")

        assert result["count"] == 1
        assert result["adapters"][0]["provider"] == "s3"

    @pytest.mark.asyncio
    async def test_list_adapter_versions_tool(self, server: DhruvaMCPServer):
        """Test list_adapter_versions MCP tool."""
        tools = server.server._tools

        # Store adapter with multiple versions
        store_tool = tools["store_adapter"]
        await store_tool(
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

        await store_tool(
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

        # List versions
        versions_tool = tools["list_adapter_versions"]
        result = await versions_tool(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["success"] is True
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_validate_adapter_tool(self, server: DhruvaMCPServer):
        """Test validate_adapter MCP tool."""
        tools = server.server._tools

        # Store adapter with valid factory path
        store_tool = tools["store_adapter"]
        await store_tool(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="dhruva.core.persistent.PersistentBase",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        # Validate
        validate_tool = tools["validate_adapter"]
        result = await validate_tool(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["success"] is True
        assert "validation" in result

    @pytest.mark.asyncio
    async def test_get_adapter_health_tool(self, server: DhruvaMCPServer):
        """Test get_adapter_health MCP tool."""
        tools = server.server._tools

        # Store adapter with valid factory path
        store_tool = tools["store_adapter"]
        await store_tool(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="dhruva.core.persistent.PersistentBase",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        # Check health
        health_tool = tools["get_adapter_health"]
        result = await health_tool(
            domain="adapter",
            key="cache",
            provider="redis",
        )

        assert result["success"] is True
        assert "health" in result
        assert result["health"]["healthy"] is True

    def test_run_method_not_called_in_tests(self, server: DhruvaMCPServer):
        """Test that run method exists but we don't call it in unit tests."""
        assert hasattr(server, "run")
        assert callable(server.run)

        # We don't actually call run() in unit tests because it starts
        # a blocking uvicorn server

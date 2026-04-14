"""Unit tests for DharaMCPServer.

Tests the FastMCP server implementation including:
- Server initialization
- Tool registration
- Storage path handling
- Adapter registry integration
"""

from __future__ import annotations

from pathlib import Path
import json
from unittest.mock import Mock, patch

import pytest

from dhara.core.config import DharaSettings
from dhara.mcp.server_core import DharaMCPServer


@pytest.mark.unit
class TestDharaMCPServer:
    """Test DharaMCPServer initialization and configuration."""

    @staticmethod
    async def _tool(server: DharaMCPServer, name: str):
        """Fetch a FastMCP tool by name."""
        return await server.server.get_tool(name)

    @pytest.fixture
    def temp_settings(self, tmp_path: Path) -> DharaSettings:
        """Create DharaSettings with temporary storage."""
        return DharaSettings(
            server_name="test-dhara",
            storage={
                "path": tmp_path / "test.dhara",
                "read_only": False,
                "backend": "file",
            },
            cache_root=tmp_path / ".cache",
        )

    @pytest.fixture
    def server(self, temp_settings: DharaSettings) -> DharaMCPServer:
        """Create DharaMCPServer instance for testing."""
        return DharaMCPServer(temp_settings)

    def test_server_initialization(self, server: DharaMCPServer, temp_settings: DharaSettings):
        """Test server initializes correctly."""
        assert server.config == temp_settings
        assert server.server is not None
        assert server.adapter_registry is not None
        assert server.storage is not None
        assert server.connection is not None

    def test_storage_path_expansion(self, tmp_path: Path):
        """Test that storage path expands ~ correctly."""
        settings = DharaSettings(
            server_name="test-dhara",
            storage={
                "path": tmp_path / "test.dhara",
                "read_only": False,
            },
        )

        server = DharaMCPServer(settings)

        # Verify storage file exists and path was expanded
        assert server.storage is not None
        assert settings.storage.path.exists() or settings.storage.path.parent.exists()

        server.close()

    def test_adapter_registry_initialized(self, server: DharaMCPServer):
        """Test that adapter registry is initialized."""
        assert server.adapter_registry is not None
        assert server.adapter_registry.connection is server.connection

    @pytest.mark.asyncio
    async def test_tools_registered(self, server: DharaMCPServer):
        """Test that MCP tools are registered."""
        tools = await server.server.list_tools()

        # Check that expected tools are registered
        tool_names = {tool.name for tool in tools}

        expected_tools = {
            "get_contract_info",
            "store_adapter",
            "get_adapter",
            "list_adapters",
            "list_adapter_versions",
            "validate_adapter",
            "get_adapter_health",
            "upsert_service",
            "get_service",
            "list_services",
            "record_event",
            "list_events",
            "put",
            "get",
            "record_time_series",
            "query_time_series",
            "aggregate_patterns",
        }

        assert expected_tools.issubset(tool_names)

    def test_readonly_storage(self, tmp_path: Path):
        """Test server with readonly storage."""
        # First create a storage file
        settings = DharaSettings(
            server_name="test-dhara",
            storage={
                "path": tmp_path / "readonly.dhara",
                "read_only": False,
            },
        )

        server1 = DharaMCPServer(settings)
        root = server1.connection.get_root()
        root["test"] = "data"
        server1.connection.commit()
        server1.close()

        # Now open as readonly
        settings_readonly = DharaSettings(
            server_name="test-dhara-readonly",
            storage={
                "path": tmp_path / "readonly.dhara",
                "read_only": True,
            },
        )

        server2 = DharaMCPServer(settings_readonly)
        root = server2.connection.get_root()
        assert root["test"] == "data"

        server2.close()

    def test_server_close(self, server: DharaMCPServer):
        """Test server close method."""
        # Should not raise any exceptions
        server.close()

    @pytest.mark.asyncio
    async def test_store_adapter_tool(self, server: DharaMCPServer):
        """Test store_adapter MCP tool."""
        store_tool = await self._tool(server, "store_adapter")
        result = await store_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
                "version": "1.0.0",
                "factory_path": "cache.RedisAdapter",
                "config": {"host": "localhost"},
                "dependencies": [],
                "capabilities": ["get", "set"],
                "metadata": {"description": "Redis adapter"},
            }
        )
        payload = result.structured_content

        assert payload["success"] is True
        assert payload["adapter_id"] == "adapter:cache:redis"

    @pytest.mark.asyncio
    async def test_get_adapter_tool(self, server: DharaMCPServer):
        """Test get_adapter MCP tool."""
        # First store an adapter
        store_tool = await self._tool(server, "store_adapter")
        await store_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
                "version": "1.0.0",
                "factory_path": "cache.RedisAdapter",
                "config": {},
                "dependencies": [],
                "capabilities": [],
                "metadata": {},
            }
        )

        # Then retrieve it
        get_tool = await self._tool(server, "get_adapter")
        result = await get_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
            }
        )
        payload = result.structured_content

        assert payload["success"] is True
        assert payload["adapter"]["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_list_adapters_tool(self, server: DharaMCPServer):
        """Test list_adapters MCP tool."""
        # Store multiple adapters
        store_tool = await self._tool(server, "store_adapter")
        for i in range(3):
            await store_tool.run(
                {
                    "domain": "adapter",
                    "key": f"cache{i}",
                    "provider": "redis",
                    "version": "1.0.0",
                    "factory_path": f"cache.Adapter{i}",
                    "config": {},
                    "dependencies": [],
                    "capabilities": [],
                    "metadata": {},
                }
            )

        # List all adapters
        list_tool = await self._tool(server, "list_adapters")
        result = await list_tool.run({})
        payload = result.structured_content

        assert payload["success"] is True
        assert payload["count"] == 3
        assert len(payload["adapters"]) == 3

    @pytest.mark.asyncio
    async def test_list_adapters_with_filters(self, server: DharaMCPServer):
        """Test list_adapters MCP tool with filters."""
        # Store adapters with different domains
        store_tool = await self._tool(server, "store_adapter")
        await store_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
                "version": "1.0.0",
                "factory_path": "cache.RedisAdapter",
                "config": {},
                "dependencies": [],
                "capabilities": [],
                "metadata": {"category": "cache"},
            }
        )

        await store_tool.run(
            {
                "domain": "service",
                "key": "storage",
                "provider": "s3",
                "version": "1.0.0",
                "factory_path": "storage.S3Adapter",
                "config": {},
                "dependencies": [],
                "capabilities": [],
                "metadata": {"category": "storage"},
            }
        )

        # Filter by domain
        list_tool = await self._tool(server, "list_adapters")
        result = await list_tool.run({"domain": "adapter"})
        payload = result.structured_content

        assert payload["count"] == 1
        assert payload["adapters"][0]["domain"] == "adapter"

        # Filter by category
        result = await list_tool.run({"category": "storage"})
        payload = result.structured_content

        assert payload["count"] == 1
        assert payload["adapters"][0]["provider"] == "s3"

    @pytest.mark.asyncio
    async def test_list_adapter_versions_tool(self, server: DharaMCPServer):
        """Test list_adapter_versions MCP tool."""
        # Store adapter with multiple versions
        store_tool = await self._tool(server, "store_adapter")
        await store_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
                "version": "1.0.0",
                "factory_path": "cache.RedisAdapter",
                "config": {},
                "dependencies": [],
                "capabilities": [],
                "metadata": {},
            }
        )

        await store_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
                "version": "2.0.0",
                "factory_path": "cache.RedisAdapter",
                "config": {},
                "dependencies": [],
                "capabilities": [],
                "metadata": {},
            }
        )

        # List versions
        versions_tool = await self._tool(server, "list_adapter_versions")
        result = await versions_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
            }
        )
        payload = result.structured_content

        assert payload["success"] is True
        assert payload["count"] == 2

    @pytest.mark.asyncio
    async def test_validate_adapter_tool(self, server: DharaMCPServer):
        """Test validate_adapter MCP tool."""
        # Store adapter with valid factory path
        store_tool = await self._tool(server, "store_adapter")
        await store_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
                "version": "1.0.0",
                "factory_path": "dhara.core.persistent.PersistentBase",
                "config": {},
                "dependencies": [],
                "capabilities": [],
                "metadata": {},
            }
        )

        # Validate
        validate_tool = await self._tool(server, "validate_adapter")
        result = await validate_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
            }
        )
        payload = result.structured_content

        assert payload["success"] is True
        assert "validation" in payload

    @pytest.mark.asyncio
    async def test_get_adapter_health_tool(self, server: DharaMCPServer):
        """Test get_adapter_health MCP tool."""
        # Store adapter with valid factory path
        store_tool = await self._tool(server, "store_adapter")
        await store_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
                "version": "1.0.0",
                "factory_path": "dhara.core.persistent.PersistentBase",
                "config": {},
                "dependencies": [],
                "capabilities": [],
                "metadata": {},
            }
        )

        # Check health
        health_tool = await self._tool(server, "get_adapter_health")
        result = await health_tool.run(
            {
                "domain": "adapter",
                "key": "cache",
                "provider": "redis",
            }
        )
        payload = result.structured_content

        assert payload["success"] is True
        assert "health" in payload
        assert payload["health"]["healthy"] is True

    @pytest.mark.asyncio
    async def test_upsert_and_get_service_tools(self, server: DharaMCPServer):
        """Test ecosystem service registration tools."""
        upsert_tool = await self._tool(server, "upsert_service")
        get_tool = await self._tool(server, "get_service")

        await upsert_tool.run(
            {
                "service_id": "mahavishnu",
                "service_type": "orchestrator",
                "capabilities": ["workflow", "routing"],
                "metadata": {"port": 8680},
                "status": "healthy",
            }
        )
        result = await get_tool.run({"service_id": "mahavishnu"})
        payload = result.structured_content

        assert payload["ok"] is True
        assert payload["service"]["schema_version"] == 1
        assert payload["service"]["service_id"] == "mahavishnu"

    @pytest.mark.asyncio
    async def test_record_and_list_events_tools(self, server: DharaMCPServer):
        """Test ecosystem event tools."""
        record_tool = await self._tool(server, "record_event")
        list_tool = await self._tool(server, "list_events")

        await record_tool.run(
            {
                "event_type": "workflow_started",
                "source_service": "mahavishnu",
                "related_service": "session-buddy",
                "payload": {"workflow_id": "wf-123"},
            }
        )
        result = await list_tool.run({"source_service": "mahavishnu"})
        payload = result.structured_content

        assert payload["ok"] is True
        assert payload["count"] == 1
        assert payload["events"][0]["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_put_and_get_tools(self, server: DharaMCPServer):
        """Test KV tools."""
        put_tool = await self._tool(server, "put")
        get_tool = await self._tool(server, "get")

        await put_tool.run({"key": "alpha", "value": {"x": 1}})
        result = await get_tool.run({"key": "alpha"})
        payload = result.structured_content

        assert payload["ok"] is True
        assert payload["value"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_get_contract_info_tool(self, server: DharaMCPServer):
        """Test MCP contract introspection tool."""
        tool = await self._tool(server, "get_contract_info")
        result = await tool.run({})
        payload = result.structured_content

        assert payload["ok"] is True
        assert payload["schema_versions"]["adapter_registry"] == 1
        assert "ecosystem_state" in payload["tool_groups"]
        assert payload["authentication"]["runtime_mode"] == "none"
        assert payload["authentication"]["canonical_fastmcp_wired"] is False
        assert "AuthMiddleware" in payload["authentication"]["available_library_surfaces"]
        assert "dhara.mcp.oneiric_server" in payload["deprecated_surfaces"]["module"]
        assert "/ready" in payload["server"]["http_endpoints"]

    @pytest.mark.asyncio
    async def test_get_contract_info_reports_token_auth_when_enabled(self, tmp_path: Path):
        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text(
            json.dumps(
                {
                    "tokens": {
                        "rw": {
                            "token_hash": "52bfd2de0a2e69dff4517518590ac32a46bd76606ec22a258f99584a6e70aca2",
                            "role": "readwrite",
                            "created_at": "2026-04-03T00:00:00",
                            "expires_at": None,
                            "is_revoked": False,
                            "rate_limit": 1000,
                            "metadata": {},
                        }
                    }
                }
            )
        )
        settings = DharaSettings(
            server_name="test-dhara-auth",
            storage={"path": tmp_path / "auth.dhara", "read_only": False},
            authentication={
                "enabled": True,
                "token": {"tokens_file": tokens_file, "default_role": "readonly"},
            },
        )
        server = DharaMCPServer(settings)
        runtime = server._runtime_status()

        assert server.auth_verifier is not None
        assert server.server.auth is not None
        assert runtime["authentication"]["mode"] == "token"
        server.close()

    def test_runtime_status_reports_backup_probe(self, tmp_path: Path):
        settings = DharaSettings(
            server_name="test-dhara",
            storage={"path": tmp_path / "runtime.dhara", "read_only": False},
            backups={"enabled": True, "directory": tmp_path / "backups"},
        )
        server = DharaMCPServer(settings)

        runtime = server._runtime_status()

        assert runtime["ready"] is True
        assert runtime["storage"]["accessible"] is True
        assert runtime["backups"]["configured"] is True
        assert runtime["backups"]["catalog_accessible"] is True
        server.close()

    def test_run_method_not_called_in_tests(self, server: DharaMCPServer):
        """Test that run method exists but we don't call it in unit tests."""
        assert hasattr(server, "run")
        assert callable(server.run)

        # We don't actually call run() in unit tests because it starts
        # a blocking uvicorn server

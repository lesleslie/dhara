"""Dhruva MCP Server using FastMCP framework.

This module implements the Dhruva MCP server using FastMCP patterns
consistent with Mahavishnu, Session-Buddy, and Crackerjack.

Migration Notes:
- Replaces custom tool registration with FastMCP @server.tool() decorators
- Preserves existing security (Token, HMAC, mTLS) from auth module
- Integrates with DhruvaSettings from mcp-common
- Adds adapter distribution tools via AdapterRegistry
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from oneiric.core.logging import get_logger

from dhruva.core.config import DhruvaSettings
from dhruva.core.connection import Connection
from dhruva.mcp.adapter_tools import (
    AdapterRegistry,
    get_adapter_health_impl,
    get_adapter_impl,
    list_adapter_versions_impl,
    list_adapters_impl,
    store_adapter_impl,
    validate_adapter_impl,
)
from dhruva.storage.file import FileStorage

logger = get_logger(__name__)


class DhruvaMCPServer:
    """Dhruva MCP Server with FastMCP framework.

    Replaces custom MCP implementation with FastMCP for ecosystem alignment.
    Preserves existing security (Token, HMAC, mTLS) while using standard
    tool registration patterns.

    ★ Insight: FastMCP Migration ─────────────────────────────────────
    1. FastMCP replaces custom tool registration with @server.tool() decorators
    2. Automatic JSON schema generation from function signatures
    3. Built-in error handling and response serialization
    4. Consistent with Mahavishnu, Session-Buddy, Crackerjack patterns
    ────────────────────────────────────────────────────────────────────
    """

    def __init__(self, config: DhruvaSettings):
        """Initialize Dhruva MCP server.

        Args:
            config: Validated Dhruva settings
        """
        self.config = config

        # Initialize FastMCP server
        self.server = FastMCP(
            name=config.server_name,
            instructions=(
                "Dhruva provides persistent object storage and Oneiric adapter "
                "distribution with ACID transactions and version management."
            ),
        )

        # Initialize storage and connection
        # Expand ~ to home directory
        storage_path = config.storage.path.expanduser()
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        self.storage = FileStorage(
            str(storage_path),
            readonly=config.storage.read_only,
        )
        self.connection = Connection(self.storage)

        # Initialize adapter registry
        self.adapter_registry = AdapterRegistry(self.connection)

        # Register tools using FastMCP decorators
        self._register_tools()

        logger.info(
            f"Dhruva MCP Server initialized: {config.server_name} "
            f"(storage={config.storage.path}, adapters={self.adapter_registry.count()})"
        )

    def _register_tools(self) -> None:
        """Register all MCP tools using FastMCP decorators.

        FastMCP automatically handles:
        - Input validation via type hints
        - JSON schema generation from function signatures
        - Response serialization
        - Error handling

        ★ Insight: Tool Registration Pattern ────────────────────────────
        Unlike the old custom MCP implementation that required manual
        get_tool_list() and call_tool() methods, FastMCP uses decorator
        registration similar to Flask/FastAPI. This provides:
        1. Type safety via Pydantic models
        2. Automatic schema generation
        3. Self-documenting tool definitions
        ────────────────────────────────────────────────────────────────────
        """

        @self.server.tool()
        async def store_adapter(
            domain: str,
            key: str,
            provider: str,
            version: str,
            factory_path: str,
            config: dict[str, Any] = {},
            dependencies: list[str] = [],
            capabilities: list[str] = [],
            metadata: dict[str, Any] = {},
        ) -> dict[str, Any]:
            """Store a Oneiric adapter in the registry.

            Args:
                domain: Adapter domain (adapter, service, task)
                key: Adapter key (cache, storage, redis)
                provider: Provider name (redis, s3, memory)
                version: Semantic version (e.g., "1.0.0")
                factory_path: Python import path for adapter factory
                config: Adapter configuration dictionary
                dependencies: List of required adapter keys
                capabilities: List of capability strings
                metadata: Additional metadata (category, description, etc.)

            Returns:
                Result dict with adapter_id and version
            """
            return await store_adapter_impl(
                registry=self.adapter_registry,
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

        @self.server.tool()
        async def get_adapter(
            domain: str,
            key: str,
            provider: str | None = None,
            version: str | None = None,
        ) -> dict[str, Any]:
            """Retrieve an adapter from the registry.

            Args:
                domain: Adapter domain
                key: Adapter key
                provider: Optional provider (defaults to first match)
                version: Optional version (defaults to latest)

            Returns:
                Adapter dict with full configuration
            """
            return await get_adapter_impl(
                registry=self.adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
                version=version,
            )

        @self.server.tool()
        async def list_adapters(
            domain: str | None = None,
            category: str | None = None,
        ) -> dict[str, Any]:
            """List adapters with optional filtering.

            Args:
                domain: Optional filter by domain (adapter, service, task)
                category: Optional filter by category (storage, cache, database)

            Returns:
                Dict with count, filters, and adapters list
            """
            return await list_adapters_impl(
                registry=self.adapter_registry,
                domain=domain,
                category=category,
            )

        @self.server.tool()
        async def list_adapter_versions(
            domain: str,
            key: str,
            provider: str,
        ) -> dict[str, Any]:
            """List all versions of an adapter.

            Shows version history with timestamps and changelogs,
            useful for understanding adapter evolution and rollback options.

            Args:
                domain: Adapter domain
                key: Adapter key
                provider: Provider name

            Returns:
                Dict with version history (timestamp, version, changelog)
            """
            return await list_adapter_versions_impl(
                registry=self.adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
            )

        @self.server.tool()
        async def validate_adapter(
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
            return await validate_adapter_impl(
                registry=self.adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
                version=version,
            )

        @self.server.tool()
        async def get_adapter_health(
            domain: str,
            key: str,
            provider: str,
        ) -> dict[str, Any]:
            """Check health status of an adapter.

            Performs health check by attempting to import the adapter's
            factory class. Returns healthy status if import succeeds.

            Args:
                domain: Adapter domain
                key: Adapter key
                provider: Provider name

            Returns:
                Health check result with status and last check timestamp
            """
            return await get_adapter_health_impl(
                registry=self.adapter_registry,
                domain=domain,
                key=key,
                provider=provider,
            )

    def run(self, host: str = "127.0.0.1", port: int = 8683) -> None:
        """Run the MCP server (synchronous - manages its own event loop).

        Args:
            host: Host to bind to
            port: Port to bind to
        """
        logger.info(f"Starting Dhruva MCP server on {host}:{port}")

        # FastMCP.run() is synchronous and manages its own event loop
        # Use "streamable-http" transport for HTTP streaming at /mcp endpoint
        self.server.run(transport="streamable-http", host=host, port=port, path="/mcp")

    def close(self) -> None:
        """Close the server and cleanup resources."""
        # Note: Connection doesn't have a close method in this implementation
        # The storage is managed by the FileStorage class
        logger.info("Dhruva MCP Server closed")

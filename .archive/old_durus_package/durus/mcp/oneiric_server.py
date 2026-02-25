"""
Oneiric-Compatible MCP Server

This module provides a Model Context Protocol (MCP) server for the Oneiric
adapter registry, enabling AI assistants to discover and manage adapters.

The server provides tools for:
- Registering adapters
- Getting adapter information
- Listing available adapters
- Searching adapters by capability

Security:
- Token-based authentication
- Role-based authorization
- Rate limiting per token
- Audit logging
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from druva.mcp.auth import (
    AuthContext,
    AuthMiddleware,
    Permission,
    Role,
    TokenAuth,
)
from druva.mcp.middleware import MCPMiddleware, MCPRequest, MCPResponse

logger = logging.getLogger(__name__)


class AdapterInfo:
    """Information about an adapter"""

    def __init__(
        self,
        name: str,
        adapter_type: str,
        version: str,
        description: str,
        capabilities: List[str],
        author: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.adapter_type = adapter_type
        self.version = version
        self.description = description
        self.capabilities = capabilities
        self.author = author
        self.config = config or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "type": self.adapter_type,
            "version": self.version,
            "description": self.description,
            "capabilities": self.capabilities,
            "author": self.author,
            "config": self.config,
        }


class OneiricMCPServer:
    """
    Oneiric-compatible MCP server with authentication

    This server implements the Model Context Protocol to provide
    AI assistants with access to the Oneiric adapter registry.
    """

    def __init__(
        self,
        auth_middleware: Optional[AuthMiddleware] = None,
        enable_auth: bool = True,
    ):
        """
        Initialize Oneiric MCP server

        Args:
            auth_middleware: Authentication middleware
            enable_auth: Enable authentication
        """
        # Adapter registry
        self.adapters: Dict[str, AdapterInfo] = {}

        # Setup middleware
        self.auth_middleware = auth_middleware
        self.middleware = MCPMiddleware(
            auth_middleware=auth_middleware,
            enable_logging=True,
            enable_metrics=True,
        )

        # Tool registry
        self.tools: Dict[str, callable] = {
            "oneiric_register_adapter": self.register_adapter,
            "oneiric_get_adapter": self.get_adapter,
            "oneiric_list_adapters": self.list_adapters,
            "oneiric_search_adapters": self.search_adapters,
        }

        logger.info(
            f"Oneiric MCP Server initialized (auth={enable_auth})"
        )

    def get_tool_list(self) -> List[Dict[str, Any]]:
        """Get list of available tools"""
        tools = [
            {
                "name": "oneiric_register_adapter",
                "description": "Register a new adapter (requires write permission)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Adapter name",
                        },
                        "type": {
                            "type": "string",
                            "description": "Adapter type (e.g., 'storage', 'serializer')",
                        },
                        "version": {
                            "type": "string",
                            "description": "Adapter version",
                        },
                        "description": {
                            "type": "string",
                            "description": "Adapter description",
                        },
                        "capabilities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of adapter capabilities",
                        },
                        "author": {
                            "type": "string",
                            "description": "Adapter author (optional)",
                        },
                        "config": {
                            "type": "object",
                            "description": "Adapter configuration (optional)",
                        },
                    },
                    "required": ["name", "type", "version", "description", "capabilities"],
                },
            },
            {
                "name": "oneiric_get_adapter",
                "description": "Get information about a specific adapter",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Adapter name",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "oneiric_list_adapters",
                "description": "List all registered adapters",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Filter by adapter type (optional)",
                        },
                    },
                },
            },
            {
                "name": "oneiric_search_adapters",
                "description": "Search for adapters by capability",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "capability": {
                            "type": "string",
                            "description": "Required capability",
                        },
                    },
                    "required": ["capability"],
                },
            },
        ]

        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        auth_context: Optional[AuthContext] = None,
    ) -> Dict[str, Any]:
        """
        Call a tool with authentication and authorization

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            auth_context: Authentication context

        Returns:
            Tool result
        """
        # Create request
        request = MCPRequest(
            method=tool_name,
            params=arguments,
            request_id=f"{tool_name}-{int(asyncio.get_event_loop().time())}",
        )

        # Extract auth info from context
        if auth_context:
            request.auth_token = auth_context.token
            request.auth_hmac = auth_context.hmac_signature
            request.auth_timestamp = auth_context.timestamp
            request.auth_client_id = auth_context.client_id

        # Process request (authenticate, rate limit, etc.)
        processed_request, auth_result = await self.middleware.process_request(
            request
        )

        # Check if authentication succeeded
        if not auth_result or not auth_result.success:
            response = MCPResponse(
                success=False,
                error=auth_result.error_message if auth_result else "Authentication failed",
                request_id=request.request_id,
            )
            return self.middleware.process_response(request, response).__dict__

        # Check tool permission
        if not self.middleware.check_tool_permission(tool_name, auth_result):
            response = MCPResponse(
                success=False,
                error=f"Permission denied for tool '{tool_name}'",
                request_id=request.request_id,
            )
            return self.middleware.process_response(
                request, response, auth_result
            ).__dict__

        # Call the tool
        try:
            if tool_name not in self.tools:
                raise ValueError(f"Unknown tool: {tool_name}")

            tool_func = self.tools[tool_name]

            # Call tool (sync or async)
            if asyncio.iscoroutinefunction(tool_func):
                result = await tool_func(**arguments)
            else:
                result = tool_func(**arguments)

            response = MCPResponse(
                success=True,
                result=result,
                request_id=request.request_id,
            )

        except Exception as e:
            logger.exception(f"Error calling tool {tool_name}: {e}")
            response = MCPResponse(
                success=False,
                error=str(e),
                request_id=request.request_id,
            )

        # Process response
        processed_response = self.middleware.process_response(
            request, response, auth_result
        )

        return processed_response.__dict__

    # Tool implementations

    def register_adapter(
        self,
        name: str,
        adapter_type: str,
        version: str,
        description: str,
        capabilities: List[str],
        author: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Register a new adapter"""
        if name in self.adapters:
            return {
                "success": False,
                "error": f"Adapter '{name}' already registered",
            }

        adapter = AdapterInfo(
            name=name,
            adapter_type=adapter_type,
            version=version,
            description=description,
            capabilities=capabilities,
            author=author,
            config=config,
        )

        self.adapters[name] = adapter

        logger.info(f"Registered adapter '{name}' (type={adapter_type}, version={version})")

        return {
            "success": True,
            "adapter": adapter.to_dict(),
            "message": f"Registered adapter '{name}'",
        }

    def get_adapter(self, name: str) -> Dict[str, Any]:
        """Get information about a specific adapter"""
        if name not in self.adapters:
            return {
                "success": False,
                "error": f"Adapter '{name}' not found",
            }

        adapter = self.adapters[name]

        return {
            "success": True,
            "adapter": adapter.to_dict(),
        }

    def list_adapters(self, adapter_type: Optional[str] = None) -> Dict[str, Any]:
        """List all registered adapters"""
        adapters = list(self.adapters.values())

        if adapter_type:
            adapters = [a for a in adapters if a.adapter_type == adapter_type]

        return {
            "success": True,
            "adapters": [a.to_dict() for a in adapters],
            "count": len(adapters),
        }

    def search_adapters(self, capability: str) -> Dict[str, Any]:
        """Search for adapters by capability"""
        matching_adapters = [
            adapter
            for adapter in self.adapters.values()
            if capability in adapter.capabilities
        ]

        return {
            "success": True,
            "capability": capability,
            "adapters": [a.to_dict() for a in matching_adapters],
            "count": len(matching_adapters),
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Get server metrics"""
        middleware_metrics = self.middleware.get_metrics()

        return {
            "middleware": middleware_metrics,
            "adapter_count": len(self.adapters),
        }


def create_oneiric_server_from_config(config: Dict[str, Any]) -> OneiricMCPServer:
    """
    Create an Oneiric MCP server from configuration

    Args:
        config: Configuration dictionary

    Returns:
        Configured OneiricMCPServer instance
    """
    # Extract auth config
    security_config = config.get("security", {})
    auth_config = security_config.get("authentication", {})
    enable_auth = auth_config.get("enabled", True)

    # Setup authentication if enabled
    auth_middleware = None
    if enable_auth:
        method = auth_config.get("method", "token")

        if method == "token":
            token_config = auth_config.get("token", {})
            tokens_file = token_config.get("tokens_file", "/etc/durus/tokens.json")
            require_auth = token_config.get("require_auth", True)
            default_role_str = token_config.get("default_role", "readonly")

            # Map string to Role
            role_map = {
                "readonly": Role.READONLY,
                "readwrite": Role.READWRITE,
                "admin": Role.ADMIN,
            }
            default_role = role_map.get(default_role_str, Role.READONLY)

            # Create token auth
            token_auth = TokenAuth(
                tokens_file=tokens_file,
                require_auth=require_auth,
                default_role=default_role,
            )

            # Create middleware
            auth_middleware = AuthMiddleware(token_auth=token_auth)

    # Create server
    server = OneiricMCPServer(
        auth_middleware=auth_middleware,
        enable_auth=enable_auth,
    )

    return server


# Example usage
if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create server with token authentication
    token_auth = TokenAuth(require_auth=True)
    token_auth.add_token(
        token_id="admin",
        token="admin_secret_token",
        role=Role.ADMIN,
    )

    auth_middleware = AuthMiddleware(token_auth=token_auth)

    server = OneiricMCPServer(
        auth_middleware=auth_middleware,
        enable_auth=True,
    )

    print("Oneiric MCP Server running")
    print(f"Available tools: {list(server.tools.keys())}")
    print(f"Metrics: {server.get_metrics()}")

    # Register some sample adapters
    server.register_adapter(
        name="file_storage",
        adapter_type="storage",
        version="1.0.0",
        description="File-based storage backend",
        capabilities=["persistent", "transactional", "append_only"],
        author="Durus Team",
    )

    server.register_adapter(
        name="msgspec_serializer",
        adapter_type="serializer",
        version="1.0.0",
        description="Msgspec serialization",
        capabilities=["fast", "secure", "type_safe"],
        author="Durus Team",
    )

    print(f"\nRegistered adapters: {server.list_adapters()}")

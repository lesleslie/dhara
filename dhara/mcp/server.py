"""
Durus MCP Server

This module provides a Model Context Protocol (MCP) server for Durus,
enabling AI assistants to interact with Durus persistent object databases.

The server provides tools for:
- Connecting to Durus storage
- Reading and writing data
- Listing keys and objects
- Creating and restoring checkpoints

Security:
- Token-based authentication
- Role-based authorization
- Rate limiting per token
- Audit logging
"""

import asyncio
import logging
from typing import Any

from dhara.connection import Connection
from dhara.file_storage import FileStorage
from dhara.mcp.auth import (
    AuthContext,
    AuthMiddleware,
    Role,
    TokenAuth,
)
from dhara.mcp.middleware import MCPMiddleware, MCPRequest, MCPResponse

logger = logging.getLogger(__name__)


class DruvaMCPServer:
    """
    Durus MCP Server with authentication and authorization

    This server implements the Model Context Protocol to provide
    AI assistants with access to Durus persistent object databases.
    """

    def __init__(
        self,
        storage_path: str = "/data/durus.durus",
        auth_middleware: AuthMiddleware | None = None,
        enable_auth: bool = True,
        read_only: bool = False,
    ):
        """
        Initialize Durus MCP server

        Args:
            storage_path: Path to Durus storage file
            auth_middleware: Authentication middleware
            enable_auth: Enable authentication
            read_only: Run in read-only mode
        """
        self.storage_path = storage_path
        self.read_only = read_only

        # Initialize storage
        self.storage = FileStorage(storage_path, readonly=read_only)
        self.connection = Connection(self.storage)

        # Setup middleware
        self.auth_middleware = auth_middleware
        self.middleware = MCPMiddleware(
            auth_middleware=auth_middleware,
            enable_logging=True,
            enable_metrics=True,
        )

        # Tool registry
        self.tools: dict[str, callable] = {
            "durus_connect": self.durus_connect,
            "durus_get": self.durus_get,
            "durus_set": self.durus_set,
            "durus_list": self.durus_list,
            "durus_delete": self.durus_delete,
            "durus_checkpoint": self.durus_checkpoint,
            "durus_restore_checkpoint": self.durus_restore_checkpoint,
        }

        logger.info(
            f"Durus MCP Server initialized on {storage_path} "
            f"(read_only={read_only}, auth={enable_auth})"
        )

    def get_tool_list(self) -> list[dict[str, Any]]:
        """Get list of available tools"""
        tools = [
            {
                "name": "durus_connect",
                "description": "Connect to Durus storage",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "storage_path": {
                            "type": "string",
                            "description": "Path to Durus storage file",
                        },
                    },
                    "required": ["storage_path"],
                },
            },
            {
                "name": "durus_get",
                "description": "Get a value from Durus by key",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to retrieve",
                        },
                    },
                    "required": ["key"],
                },
            },
            {
                "name": "durus_set",
                "description": "Set a value in Durus (requires write permission)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to set",
                        },
                        "value": {
                            "type": "string",
                            "description": "Value to set",
                        },
                    },
                    "required": ["key", "value"],
                },
            },
            {
                "name": "durus_list",
                "description": "List all keys in Durus root",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prefix": {
                            "type": "string",
                            "description": "Filter keys by prefix",
                        },
                    },
                },
            },
            {
                "name": "durus_delete",
                "description": "Delete a key from Durus (requires delete permission)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to delete",
                        },
                    },
                    "required": ["key"],
                },
            },
            {
                "name": "durus_checkpoint",
                "description": "Create a checkpoint (requires checkpoint permission)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Checkpoint name",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "durus_restore_checkpoint",
                "description": "Restore from checkpoint (requires restore permission)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Checkpoint name to restore",
                        },
                    },
                    "required": ["name"],
                },
            },
        ]

        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth_context: AuthContext | None = None,
    ) -> dict[str, Any]:
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
        processed_request, auth_result = await self.middleware.process_request(request)

        # Check if authentication succeeded
        if not auth_result or not auth_result.success:
            response = MCPResponse(
                success=False,
                error=auth_result.error_message
                if auth_result
                else "Authentication failed",
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

    def durus_connect(self, storage_path: str) -> dict[str, Any]:
        """Connect to a Durus storage file"""
        if self.read_only:
            return {
                "success": False,
                "error": "Cannot connect in read-only mode",
            }

        # Close existing connection
        if self.connection:
            self.connection.close()

        # Open new connection
        self.storage = FileStorage(storage_path)
        self.connection = Connection(self.storage)
        self.storage_path = storage_path

        return {
            "success": True,
            "storage_path": storage_path,
            "message": f"Connected to {storage_path}",
        }

    def durus_get(self, key: str) -> dict[str, Any]:
        """Get a value from Durus"""
        root = self.connection.get_root()

        if key not in root:
            return {
                "success": False,
                "error": f"Key '{key}' not found",
            }

        value = root[key]
        return {
            "success": True,
            "key": key,
            "value": str(value),  # Convert to string for JSON serialization
        }

    def durus_set(self, key: str, value: Any) -> dict[str, Any]:
        """Set a value in Durus"""
        if self.read_only:
            return {
                "success": False,
                "error": "Cannot write in read-only mode",
            }

        root = self.connection.get_root()
        root[key] = value
        self.connection.commit()

        return {
            "success": True,
            "key": key,
            "message": f"Set key '{key}'",
        }

    def durus_list(self, prefix: str | None = None) -> dict[str, Any]:
        """List keys in Durus root"""
        root = self.connection.get_root()

        keys = list(root.keys())

        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]

        return {
            "success": True,
            "keys": keys,
            "count": len(keys),
        }

    def durus_delete(self, key: str) -> dict[str, Any]:
        """Delete a key from Durus"""
        if self.read_only:
            return {
                "success": False,
                "error": "Cannot delete in read-only mode",
            }

        root = self.connection.get_root()

        if key not in root:
            return {
                "success": False,
                "error": f"Key '{key}' not found",
            }

        del root[key]
        self.connection.commit()

        return {
            "success": True,
            "key": key,
            "message": f"Deleted key '{key}'",
        }

    def durus_checkpoint(self, name: str) -> dict[str, Any]:
        """Create a checkpoint"""
        if self.read_only:
            return {
                "success": False,
                "error": "Cannot create checkpoint in read-only mode",
            }

        # Import checkpoint functionality
        from dhara.backup.checkpoint import create_checkpoint

        checkpoint_path = create_checkpoint(self.storage, name)

        return {
            "success": True,
            "name": name,
            "checkpoint_path": checkpoint_path,
            "message": f"Created checkpoint '{name}'",
        }

    def durus_restore_checkpoint(self, name: str) -> dict[str, Any]:
        """Restore from a checkpoint"""
        if self.read_only:
            return {
                "success": False,
                "error": "Cannot restore checkpoint in read-only mode",
            }

        # Import checkpoint functionality
        from dhara.backup.checkpoint import restore_checkpoint

        restore_checkpoint(self.storage, name)

        # Reopen connection
        self.connection.close()
        self.connection = Connection(self.storage)

        return {
            "success": True,
            "name": name,
            "message": f"Restored checkpoint '{name}'",
        }

    def get_metrics(self) -> dict[str, Any]:
        """Get server metrics"""
        middleware_metrics = self.middleware.get_metrics()

        return {
            "middleware": middleware_metrics,
            "storage_path": self.storage_path,
            "read_only": self.read_only,
        }

    def close(self):
        """Close the server"""
        if self.connection:
            self.connection.close()
        logger.info("Durus MCP Server closed")


def create_server_from_config(config: dict[str, Any]) -> DruvaMCPServer:
    """
    Create a Durus MCP server from configuration

    Args:
        config: Configuration dictionary

    Returns:
        Configured DruvaMCPServer instance
    """
    # Extract storage config
    storage_config = config.get("storage", {})
    storage_path = storage_config.get("path", "/data/durus.durus")
    read_only = storage_config.get("read_only", False)

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
    server = DruvaMCPServer(
        storage_path=storage_path,
        auth_middleware=auth_middleware,
        enable_auth=enable_auth,
        read_only=read_only,
    )

    return server


# Example usage
if __name__ == "__main__":
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

    server = DruvaMCPServer(
        storage_path="/tmp/test.durus",
        auth_middleware=auth_middleware,
        enable_auth=True,
        read_only=False,
    )

    print("Durus MCP Server running")
    print(f"Available tools: {list(server.tools.keys())}")
    print(f"Metrics: {server.get_metrics()}")

    server.close()

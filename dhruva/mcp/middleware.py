"""
MCP Server Middleware

This module provides middleware for MCP servers including authentication,
logging, error handling, and request validation.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dhruva.mcp.auth import (
    AuthContext,
    AuthMiddleware,
    AuthResult,
    Permission,
)

logger = logging.getLogger(__name__)


@dataclass
class MCPRequest:
    """MCP request context"""

    method: str
    params: dict[str, Any]
    request_id: str | None = None
    timestamp: float = field(default_factory=time.time)

    # Authentication context
    auth_token: str | None = None
    auth_hmac: str | None = None
    auth_timestamp: str | None = None
    auth_client_id: str | None = None


@dataclass
class MCPResponse:
    """MCP response"""

    success: bool
    result: Any | None = None
    error: str | None = None
    request_id: str | None = None
    duration_ms: float = 0.0


class MCPMiddleware:
    """
    Base middleware for MCP servers

    Handles request preprocessing, authentication, authorization,
    logging, and response postprocessing.
    """

    def __init__(
        self,
        auth_middleware: AuthMiddleware | None = None,
        enable_logging: bool = True,
        enable_metrics: bool = True,
        log_level: int = logging.INFO,
    ):
        """
        Initialize MCP middleware

        Args:
            auth_middleware: Authentication middleware
            enable_logging: Enable request/response logging
            enable_metrics: Enable metrics collection
            log_level: Logging level
        """
        self.auth_middleware = auth_middleware
        self.enable_logging = enable_logging
        self.enable_metrics = enable_metrics
        self.log_level = log_level

        # Metrics
        self._request_count = 0
        self._error_count = 0
        self._auth_failure_count = 0
        self._request_durations: list[float] = []

        # Permission mapping for MCP tools
        self._tool_permissions: dict[str, Permission] = {
            # Durus MCP tools
            "durus_get": Permission.READ,
            "durus_set": Permission.WRITE,
            "durus_list": Permission.LIST,
            "durus_delete": Permission.DELETE,
            "durus_checkpoint": Permission.CHECKPOINT,
            "durus_restore_checkpoint": Permission.RESTORE,
            "durus_connect": Permission.READ,
            # Oneiric MCP tools
            "oneiric_register_adapter": Permission.WRITE,
            "oneiric_get_adapter": Permission.READ,
            "oneiric_list_adapters": Permission.LIST,
            "oneiric_search_adapters": Permission.READ,
        }

    def get_required_permission(self, tool_name: str) -> Permission | None:
        """Get required permission for a tool"""
        return self._tool_permissions.get(tool_name)

    def set_tool_permission(self, tool_name: str, permission: Permission) -> None:
        """Set required permission for a tool"""
        self._tool_permissions[tool_name] = permission

    async def process_request(
        self,
        request: MCPRequest,
    ) -> tuple[MCPRequest, AuthResult | None]:
        """
        Process incoming request

        Args:
            request: MCP request

        Returns:
            Tuple of (processed_request, auth_result)
        """
        time.time()

        # Extract authentication context
        auth_context = AuthContext(
            token=request.auth_token,
            hmac_signature=request.auth_hmac,
            timestamp=request.auth_timestamp,
            client_id=request.auth_client_id,
        )

        # Authenticate if middleware configured
        auth_result = None
        if self.auth_middleware:
            auth_result = self.auth_middleware.authenticate(auth_context)

            if not auth_result.success:
                self._auth_failure_count += 1
                logger.warning(
                    f"Authentication failed for request {request.request_id}: "
                    f"{auth_result.error_message}"
                )
                return request, auth_result

            # Check rate limiting
            if auth_result.token_id:
                can_proceed = await self.auth_middleware.token_auth.check_rate_limit(
                    auth_result.token_id
                )
                if not can_proceed:
                    logger.warning(
                        f"Rate limit exceeded for token '{auth_result.token_id}'"
                    )
                    # Create auth result indicating rate limit
                    auth_result.success = False
                    auth_result.error_message = "Rate limit exceeded"
                    return request, auth_result

        # Log request
        if self.enable_logging:
            self._log_request(request, auth_result)

        self._request_count += 1

        return request, auth_result

    def process_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        auth_result: AuthResult | None = None,
    ) -> MCPResponse:
        """
        Process outgoing response

        Args:
            request: Original request
            response: Response to process
            auth_result: Authentication result

        Returns:
            Processed response
        """
        # Add duration if not set
        if response.duration_ms == 0.0:
            response.duration_ms = (time.time() - request.timestamp) * 1000

        # Track metrics
        if self.enable_metrics:
            self._request_durations.append(response.duration_ms)
            if not response.success:
                self._error_count += 1

        # Log response
        if self.enable_logging:
            self._log_response(request, response, auth_result)

        return response

    def _log_request(
        self,
        request: MCPRequest,
        auth_result: AuthResult | None = None,
    ) -> None:
        """Log incoming request"""
        log_data = {
            "request_id": request.request_id,
            "method": request.method,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if auth_result:
            log_data["token_id"] = auth_result.token_id
            log_data["role"] = auth_result.role.value if auth_result.role else None

        logger.log(self.log_level, f"MCP Request: {json.dumps(log_data)}")

    def _log_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        auth_result: AuthResult | None = None,
    ) -> None:
        """Log outgoing response"""
        log_data = {
            "request_id": request.request_id,
            "method": request.method,
            "success": response.success,
            "duration_ms": response.duration_ms,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if not response.success and response.error:
            log_data["error"] = response.error

        if auth_result:
            log_data["token_id"] = auth_result.token_id

        if response.success:
            logger.log(self.log_level, f"MCP Response: {json.dumps(log_data)}")
        else:
            logger.error(f"MCP Error: {json.dumps(log_data)}")

    def check_tool_permission(
        self,
        tool_name: str,
        auth_result: AuthResult,
    ) -> bool:
        """
        Check if auth result has permission for a tool

        Args:
            tool_name: Tool name
            auth_result: Authentication result

        Returns:
            True if has permission
        """
        required_permission = self.get_required_permission(tool_name)

        if not required_permission:
            # No permission required
            return True

        if not auth_result.success:
            return False

        if not self.auth_middleware:
            return True

        return self.auth_middleware.check_permission(auth_result, required_permission)

    def get_metrics(self) -> dict[str, Any]:
        """Get middleware metrics"""
        avg_duration = (
            sum(self._request_durations) / len(self._request_durations)
            if self._request_durations
            else 0.0
        )

        return {
            "request_count": self._request_count,
            "error_count": self._error_count,
            "auth_failure_count": self._auth_failure_count,
            "avg_duration_ms": avg_duration,
            "error_rate": (
                self._error_count / self._request_count if self._request_count else 0.0
            ),
        }

    def reset_metrics(self) -> None:
        """Reset metrics"""
        self._request_count = 0
        self._error_count = 0
        self._auth_failure_count = 0
        self._request_durations = []


class RateLimiter:
    """
    Rate limiter for API requests

    Implements token bucket algorithm for rate limiting.
    """

    def __init__(
        self,
        requests_per_second: float = 10.0,
        burst_size: int = 100,
    ):
        """
        Initialize rate limiter

        Args:
            requests_per_second: Rate limit
            burst_size: Maximum burst size
        """
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size

        # Token buckets: key -> (tokens, last_update)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, tokens: int = 1) -> bool:
        """
        Acquire tokens from bucket

        Args:
            key: Bucket identifier (e.g., token_id)
            tokens: Number of tokens to acquire

        Returns:
            True if tokens acquired, False otherwise
        """
        async with self._lock:
            now = time.time()

            # Get or create bucket
            if key not in self._buckets:
                self._buckets[key] = (self.burst_size, now)
                return True

            bucket_tokens, last_update = self._buckets[key]

            # Add tokens based on time elapsed
            elapsed = now - last_update
            new_tokens = elapsed * self.requests_per_second
            bucket_tokens = min(self.burst_size, bucket_tokens + new_tokens)

            # Check if enough tokens
            if bucket_tokens >= tokens:
                # Consume tokens
                bucket_tokens -= tokens
                self._buckets[key] = (bucket_tokens, now)
                return True
            else:
                # Not enough tokens
                self._buckets[key] = (bucket_tokens, now)
                return False

    def get_available_tokens(self, key: str) -> float:
        """Get available tokens for a key"""
        if key not in self._buckets:
            return self.burst_size

        bucket_tokens, last_update = self._buckets[key]

        # Calculate tokens based on time elapsed
        now = time.time()
        elapsed = now - last_update
        new_tokens = elapsed * self.requests_per_second

        return min(self.burst_size, bucket_tokens + new_tokens)


class RequestContext:
    """
    Context for MCP request processing

    Tracks request state, authentication, and metadata.
    """

    def __init__(
        self,
        request_id: str,
        method: str,
        params: dict[str, Any],
    ):
        self.request_id = request_id
        self.method = method
        self.params = params
        self.start_time = time.time()

        # Authentication
        self.auth_result: AuthResult | None = None

        # Metadata
        self.metadata: dict[str, Any] = {}

    @property
    def duration(self) -> float:
        """Get request duration in seconds"""
        return time.time() - self.start_time

    @property
    def duration_ms(self) -> float:
        """Get request duration in milliseconds"""
        return self.duration * 1000


def create_auth_context_from_request(request: MCPRequest) -> AuthContext:
    """Create AuthContext from MCPRequest"""
    return AuthContext(
        token=request.auth_token,
        hmac_signature=request.auth_hmac,
        timestamp=request.auth_timestamp,
        client_id=request.auth_client_id,
    )

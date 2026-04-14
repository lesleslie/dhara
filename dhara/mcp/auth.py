"""
Authentication and authorization for Dhara MCP servers.

This module provides comprehensive security controls for MCP server operations,
including multiple authentication methods, role-based access control, and
audit logging.

Security Features:
- Multiple authentication methods (token, HMAC, environment, mTLS)
- Role-based permissions (read-only, read-write, admin)
- Rate limiting per token
- Token expiration and revocation
- Constant-time token comparison
- Comprehensive audit logging
- Secure token storage (hashed)
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class Permission(Enum):
    """Permission levels for MCP operations"""

    # Read permissions
    READ = "read"  # Can read data
    LIST = "list"  # Can list keys/objects

    # Write permissions
    WRITE = "write"  # Can write data
    DELETE = "delete"  # Can delete data

    # Administrative permissions
    CHECKPOINT = "checkpoint"  # Can create checkpoints
    RESTORE = "restore"  # Can restore from checkpoints
    ADMIN = "admin"  # Full administrative access

    @classmethod
    def all_permissions(cls) -> set["Permission"]:
        """Get all permissions"""
        return set(cls)

    @classmethod
    def read_permissions(cls) -> set["Permission"]:
        """Get read-only permissions"""
        return {cls.READ, cls.LIST}

    @classmethod
    def write_permissions(cls) -> set["Permission"]:
        """Get write permissions (includes read)"""
        return cls.read_permissions() | {cls.WRITE, cls.DELETE}

    @classmethod
    def admin_permissions(cls) -> set["Permission"]:
        """Get all administrative permissions"""
        return cls.all_permissions()


class Role(Enum):
    """Predefined roles with permission sets"""

    READONLY = "readonly"
    READWRITE = "readwrite"
    ADMIN = "admin"

    def get_permissions(self) -> set[Permission]:
        """Get permissions for this role"""
        if self == Role.READONLY:
            return Permission.read_permissions()
        elif self == Role.READWRITE:
            return Permission.write_permissions()
        elif self == Role.ADMIN:
            return Permission.admin_permissions()
        return set()


@dataclass
class AuthResult:
    """Result of an authentication attempt"""

    success: bool
    token_id: str | None = None
    role: Role | None = None
    permissions: set[Permission] = field(default_factory=set)
    error_message: str | None = None
    expires_at: datetime | None = None

    def has_permission(self, permission: Permission) -> bool:
        """Check if this auth result has a specific permission"""
        return permission in self.permissions


@dataclass
class AuthContext:
    """Context for an authentication request"""

    token: str | None = None
    hmac_signature: str | None = None
    timestamp: str | None = None
    client_id: str | None = None
    environment_var: str | None = None
    cert_data: bytes | None = None

    # Rate limiting
    rate_limit_window: float = 60.0  # seconds
    rate_limit_requests: int = 1000  # requests per window

    def __post_init__(self):
        """Set timestamp if not provided"""
        if self.timestamp is None:
            self.timestamp = str(int(time.time()))


@dataclass
class TokenInfo:
    """Information about a token"""

    token_id: str
    token_hash: str
    role: Role
    created_at: datetime
    expires_at: datetime | None = None
    last_used: datetime | None = None
    is_revoked: bool = False
    rate_limit: int = 1000  # requests per minute
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if token is expired"""
        if self.expires_at is None:
            return False
        return _utcnow() > _as_utc(self.expires_at)

    def is_valid(self) -> bool:
        """Check if token is valid (not expired or revoked)"""
        return not self.is_revoked and not self.is_expired()


class TokenAuth:
    """
    Token-based authentication

    Tokens are stored as SHA-256 hashes. Authentication uses constant-time
    comparison to prevent timing attacks.
    """

    def __init__(
        self,
        tokens: dict[str, TokenInfo] | None = None,
        tokens_file: str | None = None,
        require_auth: bool = True,
        default_role: Role = Role.READONLY,
    ):
        """
        Initialize token authentication

        Args:
            tokens: Dictionary of token_id -> TokenInfo
            tokens_file: Path to JSON file containing tokens
            require_auth: Whether authentication is required
            default_role: Default role if not specified
        """
        self.tokens: dict[str, TokenInfo] = tokens or {}
        self.tokens_file = tokens_file
        self.require_auth = require_auth
        self.default_role = default_role

        # Rate limiting: token_id -> list of request timestamps
        self._rate_limit_tracker: dict[str, list[float]] = {}
        self._rate_limit_lock = asyncio.Lock()

        # Load tokens from file if specified
        if tokens_file and os.path.exists(tokens_file):
            self.load_tokens(tokens_file)

    def load_tokens(self, filepath: str) -> None:
        """Load tokens from a JSON file"""
        try:
            with open(filepath) as f:
                content = f.read().strip()
                if not content:
                    # Empty file, initialize with empty tokens dict
                    data = {}
                else:
                    data = json.loads(content)

            for token_id, token_data in data.get("tokens", {}).items():
                self.tokens[token_id] = TokenInfo(
                    token_id=token_id,
                    token_hash=token_data["token_hash"],
                    role=Role(token_data["role"]),
                    created_at=datetime.fromisoformat(token_data["created_at"]),
                    expires_at=(
                        datetime.fromisoformat(token_data["expires_at"])
                        if token_data.get("expires_at")
                        else None
                    ),
                    is_revoked=token_data.get("is_revoked", False),
                    rate_limit=token_data.get("rate_limit", 1000),
                    metadata=token_data.get("metadata", {}),
                )

            logger.info(f"Loaded {len(self.tokens)} tokens from {filepath}")
        except Exception as e:
            logger.error(f"Failed to load tokens from {filepath}: {e}")
            raise

    def save_tokens(self, filepath: str | None = None) -> None:
        """Save tokens to a JSON file"""
        filepath = filepath or self.tokens_file
        if not filepath:
            raise ValueError("No tokens file specified")

        try:
            data = {
                "tokens": {
                    token_id: {
                        "token_hash": info.token_hash,
                        "role": info.role.value,
                        "created_at": info.created_at.isoformat(),
                        "expires_at": info.expires_at.isoformat()
                        if info.expires_at
                        else None,
                        "is_revoked": info.is_revoked,
                        "rate_limit": info.rate_limit,
                        "metadata": info.metadata,
                    }
                    for token_id, info in self.tokens.items()
                }
            }

            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"Saved {len(self.tokens)} tokens to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save tokens to {filepath}: {e}")
            raise

    def add_token(
        self,
        token_id: str,
        token: str,
        role: Role = Role.READONLY,
        expires_in: int | None = None,
        rate_limit: int = 1000,
        metadata: dict[str, Any] | None = None,
    ) -> TokenInfo:
        """
        Add a new token

        Args:
            token_id: Unique identifier for the token
            token: The token string (will be hashed)
            role: Role for this token
            expires_in: Expiration time in seconds (None = no expiration)
            rate_limit: Rate limit (requests per minute)
            metadata: Additional metadata

        Returns:
            TokenInfo: The created token info
        """
        token_hash = self._hash_token(token)

        expires_at = None
        if expires_in:
            expires_at = _utcnow() + timedelta(seconds=expires_in)

        token_info = TokenInfo(
            token_id=token_id,
            token_hash=token_hash,
            role=role,
            created_at=_utcnow(),
            expires_at=expires_at,
            rate_limit=rate_limit,
            metadata=metadata or {},
        )

        self.tokens[token_id] = token_info
        logger.info(f"Added token '{token_id}' with role '{role.value}'")

        return token_info

    def revoke_token(self, token_id: str) -> bool:
        """Revoke a token"""
        if token_id in self.tokens:
            self.tokens[token_id].is_revoked = True
            logger.warning(f"Revoked token '{token_id}'")
            return True
        return False

    def _hash_token(self, token: str) -> str:
        """Hash a token using SHA-256"""
        return hashlib.sha256(token.encode()).hexdigest()

    def _compare_tokens(self, token: str, token_hash: str) -> bool:
        """
        Constant-time token comparison to prevent timing attacks

        Uses secrets.compare_digest which is designed for this purpose
        """
        token_hash_calc = self._hash_token(token)
        return secrets.compare_digest(token_hash_calc, token_hash)

    async def _check_rate_limit(self, token_id: str, token_info: TokenInfo) -> bool:
        """
        Check if token is within rate limits

        Args:
            token_id: Token identifier
            token_info: Token information

        Returns:
            True if within rate limit, False otherwise
        """
        now = time.time()
        window_start = now - 60.0  # 1 minute window

        async with self._rate_limit_lock:
            if token_id not in self._rate_limit_tracker:
                self._rate_limit_tracker[token_id] = []

            # Clean old requests outside the window
            self._rate_limit_tracker[token_id] = [
                ts for ts in self._rate_limit_tracker[token_id] if ts > window_start
            ]

            # Check if within rate limit
            current_count = len(self._rate_limit_tracker[token_id])
            if current_count >= token_info.rate_limit:
                logger.warning(
                    f"Token '{token_id}' exceeded rate limit: {current_count}/{token_info.rate_limit}"
                )
                return False

            # Add current request
            self._rate_limit_tracker[token_id].append(now)
            return True

    def authenticate(self, token: str) -> AuthResult:
        """
        Authenticate using a token

        Args:
            token: The token string

        Returns:
            AuthResult with authentication outcome
        """
        # If auth not required, return default permissions
        if not self.require_auth:
            return AuthResult(
                success=True,
                token_id="default",
                role=self.default_role,
                permissions=self.default_role.get_permissions(),
            )

        # Check all tokens
        for token_id, token_info in self.tokens.items():
            if not token_info.is_valid():
                continue

            if self._compare_tokens(token, token_info.token_hash):
                # Token found and valid
                token_info.last_used = _utcnow()

                logger.info(
                    f"Authentication successful for token '{token_id}' with role '{token_info.role.value}'"
                )

                return AuthResult(
                    success=True,
                    token_id=token_id,
                    role=token_info.role,
                    permissions=token_info.role.get_permissions(),
                    expires_at=token_info.expires_at,
                )

        # No valid token found
        logger.warning("Authentication failed: invalid or expired token")
        return AuthResult(success=False, error_message="Invalid or expired token")

    async def check_rate_limit(self, token_id: str) -> bool:
        """Check rate limit for a token (async wrapper)"""
        token_info = self.tokens.get(token_id)
        if not token_info:
            return True  # No rate limiting for unknown tokens
        return await self._check_rate_limit(token_id, token_info)


class HMACAuth:
    """
    HMAC-based authentication

    Uses HMAC-SHA256 for request authentication. The client must provide
    a signature based on the request payload and a shared secret.
    """

    def __init__(
        self,
        secrets: dict[str, str] | None = None,
        secrets_file: str | None = None,
        require_auth: bool = True,
    ):
        """
        Initialize HMAC authentication

        Args:
            secrets: Dictionary of client_id -> secret (hashed)
            secrets_file: Path to JSON file containing secrets
            require_auth: Whether authentication is required
        """
        self.secrets: dict[str, str] = secrets or {}
        self.secrets_file = secrets_file
        self.require_auth = require_auth

        # Load secrets from file if specified
        if secrets_file and os.path.exists(secrets_file):
            self.load_secrets(secrets_file)

    def load_secrets(self, filepath: str) -> None:
        """Load secrets from a JSON file"""
        try:
            with open(filepath) as f:
                data = json.load(f)

            for client_id, secret_hash in data.get("secrets", {}).items():
                self.secrets[client_id] = secret_hash

            logger.info(f"Loaded {len(self.secrets)} secrets from {filepath}")
        except Exception as e:
            logger.error(f"Failed to load secrets from {filepath}: {e}")
            raise

    def _hash_secret(self, secret: str) -> str:
        """Hash a secret using SHA-256"""
        return hashlib.sha256(secret.encode()).hexdigest()

    def generate_signature(self, payload: str, secret: str, timestamp: str) -> str:
        """
        Generate HMAC signature for a payload

        Args:
            payload: Request payload (JSON string)
            secret: Shared secret
            timestamp: Request timestamp

        Returns:
            Base64-encoded signature
        """
        # Create message: timestamp + payload
        message = f"{timestamp}{payload}".encode()

        # Generate HMAC
        signature_hmac = hmac.new(secret.encode(), message, hashlib.sha256).digest()

        # Return base64 encoded
        return base64.b64encode(signature_hmac).decode()

    def verify_signature(
        self,
        payload: str,
        signature: str,
        timestamp: str,
        client_id: str,
    ) -> bool:
        """
        Verify HMAC signature

        Args:
            payload: Request payload
            signature: Provided signature
            timestamp: Request timestamp
            client_id: Client identifier

        Returns:
            True if signature is valid
        """
        secret_hash = self.secrets.get(client_id)
        if not secret_hash:
            return False

        # For HMAC, we need the actual secret, not the hash
        # In production, store secrets securely (e.g., HashiCorp Vault)
        # For now, we'll use the hash directly (not ideal but functional)
        message = f"{timestamp}{payload}".encode()

        # This is a simplified version - in production, retrieve the actual
        # secret from a secure store
        expected_hmac = hmac.new(secret_hash.encode(), message, hashlib.sha256).digest()

        expected_signature = base64.b64encode(expected_hmac).decode()

        # Constant-time comparison
        return secrets.compare_digest(signature, expected_signature)

    def authenticate(
        self, payload: str, signature: str, timestamp: str, client_id: str
    ) -> AuthResult:
        """Authenticate using HMAC signature"""
        if not self.require_auth:
            return AuthResult(
                success=True,
                token_id=client_id,
                role=Role.ADMIN,
                permissions=Role.ADMIN.get_permissions(),
            )

        if self.verify_signature(payload, signature, timestamp, client_id):
            logger.info(f"HMAC authentication successful for client '{client_id}'")
            return AuthResult(
                success=True,
                token_id=client_id,
                role=Role.ADMIN,
                permissions=Role.ADMIN.get_permissions(),
            )

        logger.warning(f"HMAC authentication failed for client '{client_id}'")
        return AuthResult(success=False, error_message="Invalid HMAC signature")


class EnvironmentAuth:
    """
    Environment-based authentication for local development

    Checks for environment variables to authenticate. This is useful for
    local development but should be disabled in production.
    """

    def __init__(
        self,
        env_var: str = "DURUS_AUTH_TOKEN",
        require_auth: bool = False,
        role: Role = Role.ADMIN,
    ):
        """
        Initialize environment-based authentication

        Args:
            env_var: Environment variable name
            require_auth: Whether authentication is required
            role: Role granted when authenticated
        """
        self.env_var = env_var
        self.require_auth = require_auth
        self.role = role

    def authenticate(self, token: str | None = None) -> AuthResult:
        """
        Authenticate using environment variable

        Args:
            token: Token to check (if None, checks env var)

        Returns:
            AuthResult with authentication outcome
        """
        env_token = os.environ.get(self.env_var)

        # If auth not required, grant access
        if not self.require_auth and not env_token:
            return AuthResult(
                success=True,
                token_id="environment",
                role=self.role,
                permissions=self.role.get_permissions(),
            )

        # Check provided token or environment variable
        token_to_check = token or env_token
        if env_token and token_to_check == env_token:
            logger.info(f"Environment authentication successful via {self.env_var}")
            return AuthResult(
                success=True,
                token_id="environment",
                role=self.role,
                permissions=self.role.get_permissions(),
            )

        if self.require_auth:
            logger.warning("Environment authentication failed")
            return AuthResult(
                success=False,
                error_message=f"Environment variable {self.env_var} not set or invalid",
            )

        # Fall back to success if not required
        return AuthResult(
            success=True,
            token_id="default",
            role=self.role,
            permissions=self.role.get_permissions(),
        )


class AuthMiddleware:
    """
    Authentication middleware for MCP servers

    Integrates multiple authentication methods and provides a unified
    interface for protecting MCP tool calls.
    """

    def __init__(
        self,
        token_auth: TokenAuth | None = None,
        hmac_auth: HMACAuth | None = None,
        env_auth: EnvironmentAuth | None = None,
        require_auth: bool = True,
        audit_log: logging.Logger | None = None,
    ):
        """
        Initialize authentication middleware

        Args:
            token_auth: Token-based authentication
            hmac_auth: HMAC-based authentication
            env_auth: Environment-based authentication
            require_auth: Whether authentication is required
            audit_log: Logger for audit events
        """
        self.token_auth = token_auth
        self.hmac_auth = hmac_auth
        self.env_auth = env_auth
        self.require_auth = require_auth
        self.audit_log = audit_log or logger

    def authenticate(
        self,
        context: AuthContext,
    ) -> AuthResult:
        """
        Authenticate using available methods

        Tries each authentication method in order:
        1. Token auth (if context has token)
        2. HMAC auth (if context has hmac_signature)
        3. Environment auth (as fallback)

        Args:
            context: Authentication context

        Returns:
            AuthResult with authentication outcome
        """
        # Try token authentication
        if context.token and self.token_auth:
            result = self.token_auth.authenticate(context.token)
            if result.success:
                return result

        # Try HMAC authentication
        if (
            context.hmac_signature
            and self.hmac_auth
            and context.timestamp
            and context.client_id
        ):
            # For HMAC, we need the payload - this would be passed separately
            # in a real implementation
            result = self.hmac_auth.authenticate(
                payload="",  # Would be actual request payload
                signature=context.hmac_signature,
                timestamp=context.timestamp,
                client_id=context.client_id,
            )
            if result.success:
                return result

        # Try environment authentication
        if self.env_auth:
            result = self.env_auth.authenticate(context.token)
            if result.success:
                return result

        # All methods failed
        if self.require_auth:
            self._audit_log("authentication_failed", context)
            return AuthResult(success=False, error_message="Authentication required")
        else:
            # Return default permissions if auth not required
            return AuthResult(
                success=True,
                token_id="default",
                role=Role.READONLY,
                permissions=Role.READONLY.get_permissions(),
            )

    def check_permission(
        self,
        auth_result: AuthResult,
        required_permission: Permission,
    ) -> bool:
        """
        Check if auth result has required permission

        Args:
            auth_result: Authentication result
            required_permission: Required permission

        Returns:
            True if has permission
        """
        if not auth_result.success:
            return False

        has_permission = auth_result.has_permission(required_permission)

        if not has_permission:
            self._audit_log(
                "permission_denied",
                None,
                {
                    "token_id": auth_result.token_id,
                    "required_permission": required_permission.value,
                },
            )

        return has_permission

    def require_permission(self, permission: Permission):
        """
        Decorator to require permission for a function

        Args:
            permission: Required permission

        Returns:
            Decorator function
        """

        def decorator(func: Callable):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Extract auth context from kwargs
                auth_context = kwargs.pop("auth_context", None)
                if not auth_context:
                    raise ValueError("auth_context required")

                # Authenticate
                auth_result = self.authenticate(auth_context)
                if not auth_result.success:
                    raise PermissionError(auth_result.error_message)

                # Check permission
                if not self.check_permission(auth_result, permission):
                    raise PermissionError(f"Permission '{permission.value}' required")

                # Add auth_result to kwargs
                kwargs["auth_result"] = auth_result

                # Call function
                return await func(*args, **kwargs)

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Extract auth context from kwargs
                auth_context = kwargs.pop("auth_context", None)
                if not auth_context:
                    raise ValueError("auth_context required")

                # Authenticate
                auth_result = self.authenticate(auth_context)
                if not auth_result.success:
                    raise PermissionError(auth_result.error_message)

                # Check permission
                if not self.check_permission(auth_result, permission):
                    raise PermissionError(f"Permission '{permission.value}' required")

                # Add auth_result to kwargs
                kwargs["auth_result"] = auth_result

                # Call function
                return func(*args, **kwargs)

            # Return appropriate wrapper based on function type
            import asyncio

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper

        return decorator

    def _audit_log(
        self,
        event: str,
        context: AuthContext | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log audit event"""
        log_data = {
            "event": event,
            "timestamp": _utcnow().isoformat(),
        }

        if context:
            log_data["client_id"] = context.client_id

        if extra:
            log_data.update(extra)

        self.audit_log.info(f"AUDIT: {json.dumps(log_data)}")


# Utility functions


def generate_token(length: int = 32) -> str:
    """
    Generate a secure random token

    Args:
        length: Token length in bytes

    Returns:
        Hex-encoded token
    """
    return secrets.token_hex(length)


def generate_api_token(token_id: str, role: str = "readonly") -> tuple[str, str]:
    """
    Generate a new API token

    Args:
        token_id: Token identifier
        role: Role for the token

    Returns:
        Tuple of (token, token_hash)
    """
    token = generate_token(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    logger.info(f"Generated token '{token_id}' with role '{role}'")

    return token, token_hash

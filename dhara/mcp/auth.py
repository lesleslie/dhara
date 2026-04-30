"""
Dhara MCP authentication — delegated to mcp_common.auth with Dhara-specific extensions.

This module provides a thin delegation to mcp_common.auth for new code, while
maintaining backward-compatible exports for legacy code that depends on the old
custom implementation.

New Code: Use DharaPermission and require_dhara_auth
Legacy Code: TokenAuth, Role, AuthResult, AuthContext remain available
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from functools import wraps
from typing import Any

from mcp_common.auth.audit import AuditLogger, AuthAuditEvent
from mcp_common.auth.config import AuthConfig
from mcp_common.auth.core import verify_token as _verify_token
from mcp_common.auth.exceptions import AuthError
from mcp_common.auth.permissions import Permission

logger = logging.getLogger(__name__)

_config: AuthConfig | None = None
_audit = AuditLogger()


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _get_config() -> AuthConfig:
    global _config
    if _config is None:
        _config = AuthConfig(service_name="dhara", secret_env_var="DHARA_AUTH_SECRET")
    return _config


def _reset_config() -> None:
    global _config
    _config = None


class DharaPermission(Enum):
    """Dhara-specific permissions extending the base Permission model."""
    CHECKPOINT = "checkpoint"
    RESTORE = "restore"


def require_dhara_auth(
    permission: Permission | DharaPermission | None = None,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cfg = _get_config()
            if not cfg.enabled:
                return await func(*args, **kwargs)

            token_str = kwargs.pop("__auth_token__", None)
            if not token_str:
                return {"error": "Authentication required", "error_code": "AUTH_REQUIRED"}

            try:
                payload = _verify_token(token_str, secret=cfg.secret, expected_audience="dhara")
            except AuthError as exc:
                return {"error": str(exc), "error_code": "AUTH_FAILED"}

            perm = permission if isinstance(permission, Permission) else Permission.READ
            _audit.emit(AuthAuditEvent(
                timestamp=datetime.now(UTC),
                service="dhara",
                caller_service=payload.issuer,
                caller_id=payload.subject,
                action=func.__name__,
                permission=perm,
                result="allowed",
                reason=None,
                source_ip=None,
                token_id=payload.jti,
            ))
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# ============================================================================
# Legacy Backward Compatibility Exports
# ============================================================================
# For backward compatibility with code that depends on the old custom
# implementation (fastmcp_auth, middleware, legacy tests).
# These are minimal stubs that delegate to mcp_common.auth where possible.

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import timedelta


class Role(Enum):
    """Legacy Role enum - maintained for backward compatibility."""
    READONLY = "readonly"
    READWRITE = "readwrite"
    ADMIN = "admin"

    def get_permissions(self) -> set[Permission]:
        """Get permissions for this role."""
        if self == Role.READONLY:
            return {Permission.READ}
        elif self == Role.READWRITE:
            return {Permission.READ, Permission.WRITE, Permission.DELETE}
        elif self == Role.ADMIN:
            return {Permission.READ, Permission.WRITE, Permission.DELETE, Permission.ADMIN}
        return set()


@dataclass
class AuthResult:
    """Legacy AuthResult - maintained for backward compatibility."""
    success: bool
    token_id: str | None = None
    role: Role | None = None
    permissions: set[Permission] = field(default_factory=set)
    error_message: str | None = None
    expires_at: datetime | None = None

    def has_permission(self, permission: Permission) -> bool:
        """Check if this auth result has a specific permission."""
        return permission in self.permissions


@dataclass
class AuthContext:
    """Legacy AuthContext - maintained for backward compatibility."""
    token: str | None = None
    hmac_signature: str | None = None
    timestamp: str | None = None
    client_id: str | None = None
    environment_var: str | None = None
    cert_data: bytes | None = None
    rate_limit_window: float = 60.0
    rate_limit_requests: int = 1000

    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = str(int(time.time()))


@dataclass
class TokenInfo:
    """Legacy TokenInfo - maintained for backward compatibility."""
    token_id: str
    token_hash: str
    role: Role
    created_at: datetime
    expires_at: datetime | None = None
    last_used: datetime | None = None
    is_revoked: bool = False
    rate_limit: int = 1000
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if token is expired."""
        if self.expires_at is None:
            return False
        now = datetime.now(UTC)
        exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        return now > exp

    def is_valid(self) -> bool:
        """Check if token is valid (not expired or revoked)."""
        return not self.is_revoked and not self.is_expired()


class TokenAuth:
    """Legacy TokenAuth - maintained for backward compatibility."""

    def __init__(
        self,
        tokens: dict[str, TokenInfo] | None = None,
        tokens_file: str | None = None,
        require_auth: bool = True,
        default_role: Role = Role.READONLY,
    ):
        """Initialize token authentication."""
        self.tokens: dict[str, TokenInfo] = tokens or {}
        self.tokens_file = tokens_file
        self.require_auth = require_auth
        self.default_role = default_role
        self._rate_limit_tracker: dict[str, list[float]] = {}
        self._rate_limit_lock = asyncio.Lock()

        if tokens_file and os.path.exists(tokens_file):
            self.load_tokens(tokens_file)

    def load_tokens(self, filepath: str) -> None:
        """Load tokens from a JSON file."""
        try:
            with open(filepath) as f:
                content = f.read().strip()
                data = json.loads(content) if content else {}

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
        """Save tokens to a JSON file."""
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
                        "expires_at": info.expires_at.isoformat() if info.expires_at else None,
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
        """Add a new token."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = None
        if expires_in:
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        token_info = TokenInfo(
            token_id=token_id,
            token_hash=token_hash,
            role=role,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
            rate_limit=rate_limit,
            metadata=metadata or {},
        )

        self.tokens[token_id] = token_info
        logger.info(f"Added token '{token_id}' with role '{role.value}'")
        return token_info

    def revoke_token(self, token_id: str) -> bool:
        """Revoke a token."""
        if token_id in self.tokens:
            self.tokens[token_id].is_revoked = True
            logger.warning(f"Revoked token '{token_id}'")
            return True
        return False

    def _hash_token(self, token: str) -> str:
        """Hash a token using SHA-256."""
        return hashlib.sha256(token.encode()).hexdigest()

    def _compare_tokens(self, token: str, token_hash: str) -> bool:
        """Constant-time token comparison."""
        token_hash_calc = self._hash_token(token)
        return secrets.compare_digest(token_hash_calc, token_hash)

    async def _check_rate_limit(self, token_id: str, token_info: TokenInfo) -> bool:
        """Check if token is within rate limits."""
        now = time.time()
        window_start = now - 60.0

        async with self._rate_limit_lock:
            if token_id not in self._rate_limit_tracker:
                self._rate_limit_tracker[token_id] = []

            self._rate_limit_tracker[token_id] = [
                ts for ts in self._rate_limit_tracker[token_id] if ts > window_start
            ]

            current_count = len(self._rate_limit_tracker[token_id])
            if current_count >= token_info.rate_limit:
                logger.warning(
                    f"Token '{token_id}' exceeded rate limit: {current_count}/{token_info.rate_limit}"
                )
                return False

            self._rate_limit_tracker[token_id].append(now)
            return True

    def authenticate(self, token: str) -> AuthResult:
        """Authenticate using a token."""
        if not self.require_auth:
            return AuthResult(
                success=True,
                token_id="default",
                role=self.default_role,
                permissions=self.default_role.get_permissions(),
            )

        for token_id, token_info in self.tokens.items():
            if not token_info.is_valid():
                continue

            if self._compare_tokens(token, token_info.token_hash):
                token_info.last_used = datetime.now(UTC)
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

        logger.warning("Authentication failed: invalid or expired token")
        return AuthResult(success=False, error_message="Invalid or expired token")

    async def check_rate_limit(self, token_id: str) -> bool:
        """Check rate limit for a token (async wrapper)."""
        token_info = self.tokens.get(token_id)
        if not token_info:
            return True
        return await self._check_rate_limit(token_id, token_info)


class HMACAuth:
    """Legacy HMACAuth - maintained for backward compatibility."""

    def __init__(
        self,
        secrets: dict[str, str] | None = None,
        secrets_file: str | None = None,
        require_auth: bool = True,
    ):
        """Initialize HMAC authentication."""
        self.secrets: dict[str, str] = secrets or {}
        self.secrets_file = secrets_file
        self.require_auth = require_auth

        if secrets_file and os.path.exists(secrets_file):
            self.load_secrets(secrets_file)

    def load_secrets(self, filepath: str) -> None:
        """Load secrets from a JSON file."""
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
        """Hash a secret using SHA-256."""
        return hashlib.sha256(secret.encode()).hexdigest()

    def generate_signature(self, payload: str, secret: str, timestamp: str) -> str:
        """Generate HMAC signature for a payload."""
        message = f"{timestamp}{payload}".encode()
        signature_hmac = hmac.new(secret.encode(), message, hashlib.sha256).digest()
        return base64.b64encode(signature_hmac).decode()

    def verify_signature(
        self,
        payload: str,
        signature: str,
        timestamp: str,
        client_id: str,
    ) -> bool:
        """Verify HMAC signature."""
        secret_hash = self.secrets.get(client_id)
        if not secret_hash:
            return False

        message = f"{timestamp}{payload}".encode()
        expected_hmac = hmac.new(secret_hash.encode(), message, hashlib.sha256).digest()
        expected_signature = base64.b64encode(expected_hmac).decode()
        return secrets.compare_digest(signature, expected_signature)

    def authenticate(
        self, payload: str, signature: str, timestamp: str, client_id: str
    ) -> AuthResult:
        """Authenticate using HMAC signature."""
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
    """Legacy EnvironmentAuth - maintained for backward compatibility."""

    def __init__(
        self,
        env_var: str = "DURUS_AUTH_TOKEN",
        require_auth: bool = False,
        role: Role = Role.ADMIN,
    ):
        """Initialize environment-based authentication."""
        self.env_var = env_var
        self.require_auth = require_auth
        self.role = role

    def authenticate(self, token: str | None = None) -> AuthResult:
        """Authenticate using environment variable."""
        env_token = os.environ.get(self.env_var)

        if not self.require_auth and not env_token:
            return AuthResult(
                success=True,
                token_id="environment",
                role=self.role,
                permissions=self.role.get_permissions(),
            )

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

        return AuthResult(
            success=True,
            token_id="default",
            role=self.role,
            permissions=self.role.get_permissions(),
        )


class AuthMiddleware:
    """Legacy AuthMiddleware - maintained for backward compatibility."""

    def __init__(
        self,
        token_auth: TokenAuth | None = None,
        hmac_auth: HMACAuth | None = None,
        env_auth: EnvironmentAuth | None = None,
        require_auth: bool = True,
        audit_log: logging.Logger | None = None,
    ):
        """Initialize authentication middleware."""
        self.token_auth = token_auth
        self.hmac_auth = hmac_auth
        self.env_auth = env_auth
        self.require_auth = require_auth
        self.audit_log = audit_log or logger

    def authenticate(self, context: AuthContext) -> AuthResult:
        """Authenticate using available methods."""
        if context.token and self.token_auth:
            result = self.token_auth.authenticate(context.token)
            if result.success:
                return result

        if (
            context.hmac_signature
            and self.hmac_auth
            and context.timestamp
            and context.client_id
        ):
            result = self.hmac_auth.authenticate(
                payload="",
                signature=context.hmac_signature,
                timestamp=context.timestamp,
                client_id=context.client_id,
            )
            if result.success:
                return result

        if self.env_auth:
            result = self.env_auth.authenticate(context.token)
            if result.success:
                return result

        if self.require_auth:
            return AuthResult(success=False, error_message="Authentication required")
        else:
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
        """Check if auth result has required permission."""
        return auth_result.success and auth_result.has_permission(required_permission)

    def require_permission(self, permission: Permission):
        """Decorator to require permission for a function."""

        def decorator(func: Callable):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any):
                auth_context = kwargs.pop("auth_context", None)
                if not auth_context:
                    raise ValueError("auth_context required")

                auth_result = self.authenticate(auth_context)
                if not auth_result.success:
                    raise PermissionError(auth_result.error_message)

                if not self.check_permission(auth_result, permission):
                    raise PermissionError(f"Permission '{permission.value}' required")

                kwargs["auth_result"] = auth_result
                return await func(*args, **kwargs)

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any):
                auth_context = kwargs.pop("auth_context", None)
                if not auth_context:
                    raise ValueError("auth_context required")

                auth_result = self.authenticate(auth_context)
                if not auth_result.success:
                    raise PermissionError(auth_result.error_message)

                if not self.check_permission(auth_result, permission):
                    raise PermissionError(f"Permission '{permission.value}' required")

                kwargs["auth_result"] = auth_result
                return func(*args, **kwargs)

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
        """Log audit event."""
        log_data = {
            "event": event,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if context:
            log_data["client_id"] = context.client_id

        if extra:
            log_data.update(extra)

        self.audit_log.info(f"AUDIT: {json.dumps(log_data)}")


def generate_token(length: int = 32) -> str:
    """Generate a secure random token."""
    return secrets.token_hex(length)


def generate_api_token(token_id: str, role: str = "readonly") -> tuple[str, str]:
    """Generate a new API token."""
    token = generate_token(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    logger.info(f"Generated token '{token_id}' with role '{role}'")
    return token, token_hash


__all__ = [
    # New API
    "DharaPermission",
    "require_dhara_auth",
    # Legacy utility functions
    "_utcnow",
    "_as_utc",
    # Legacy API (backward compatibility)
    "AuthContext",
    "AuthResult",
    "Role",
    "Permission",
    "TokenAuth",
    "HMACAuth",
    "EnvironmentAuth",
    "AuthMiddleware",
    "TokenInfo",
    "generate_token",
    "generate_api_token",
]

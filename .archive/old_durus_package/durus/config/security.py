"""
Security Configuration Module

This module provides centralized security configuration for Durus applications,
integrating with Oneiric secrets management for HMAC signing keys.
"""

import os
import sys
import threading
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, field
import logging
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta

# Import Oneiric secrets module with error handling
ONEIRIC_AVAILABLE = False
OneiricSecretsAdapter = None
create_hmac_signature = None
verify_hmac_signature = None
initialize_secrets = None

try:
    from druva.security.oneiric_secrets import (
        OneiricSecretsAdapter,
        create_hmac_signature,
        verify_hmac_signature,
        initialize_secrets
    )
    ONEIRIC_AVAILABLE = True
except ImportError:
    # Oneiric not available, will use fallback mode
    pass


@dataclass
class SecurityConfig:
    """
    Centralized security configuration for Durus applications.

    Handles HMAC key management, security policies, and validation.
    """

    # Secret management configuration
    secret_prefix: str = "durus/hmac"
    rotation_interval_days: int = 90
    key_length_minimum_bytes: int = 32

    # Security policies
    allowed_algorithms: List[str] = field(default_factory=lambda: ["sha256", "sha384", "sha512"])
    allow_fallback_keys: bool = True
    require_key_validation: bool = True
    enable_auto_rotation: bool = True

    # Security validation
    enable_strict_mode: bool = False
    log_security_events: bool = True

    # Fallback configuration (for development/testing only)
    fallback_signing_key: Optional[bytes] = None
    fallback_enabled: bool = False

    # Internal state
    _adapter: Optional[Any] = None
    _initialized: bool = False
    _logger: Optional[logging.Logger] = None
    _fallback_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        """Initialize logging and validate configuration."""
        self._logger = logging.getLogger(__name__)

        if self.rotation_interval_days < 1:
            raise ValueError("Rotation interval must be at least 1 day")

        if self.key_length_minimum_bytes < 32:
            raise ValueError("Minimum key length must be at least 32 bytes (256 bits)")

        # Validate allowed algorithms
        self.allowed_algorithms = [
            algo for algo in self.allowed_algorithms
            if algo in hashlib.algorithms_available
        ]

    def initialize(self) -> None:
        """
        Initialize the security configuration and load secrets from Oneiric.

        Raises:
            RuntimeError: If Oneiric is not available or initialization fails
        """
        if self._initialized:
            return

        try:
            # Check if Oneiric is available
            if not ONEIRIC_AVAILABLE:
                if not self.fallback_enabled:
                    raise RuntimeError(
                        "Oneiric secrets library is not available and fallback is disabled. "
                        "Please install the Oneiric SDK or enable fallback mode."
                    )
                else:
                    self._logger.warning(
                        "Oneiric not available, using fallback mode. "
                        "This is less secure than production setup."
                    )
                    self._initialize_fallback()
                    return

            # Initialize Oneiric secrets
            self._adapter = initialize_secrets(
                self.secret_prefix,
                self.rotation_interval_days
            )

            # Perform validation only for Oneiric mode
            if self.require_key_validation:
                self._validate_security_setup()

            self._initialized = True
            self._log_security_event("Security configuration initialized successfully")

        except Exception as e:
            error_msg = f"Failed to initialize security configuration: {str(e)}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _initialize_fallback(self) -> None:
        """Initialize with fallback configuration for development/testing."""
        with self._fallback_lock:
            if self._initialized:
                return

            if self.fallback_signing_key is None:
                # Generate a random fallback key
                self.fallback_signing_key = secrets.token_bytes(32)
                self._logger.warning("Generated temporary fallback signing key")

            self._initialized = True
            self._log_security_event("Security configuration initialized in fallback mode")

    def _validate_security_setup(self) -> None:
        """Validate the security setup meets requirements."""
        # Skip validation in fallback mode
        if not ONEIRIC_AVAILABLE:
            return

        try:
            # Get key status
            status = self._adapter.get_key_status()

            # Validate key requirements
            if "signing_key" not in status:
                raise RuntimeError("No signing key available")

            signing_key = status["signing_key"]
            if signing_key["key_length"] < self.key_length_minimum_bytes:
                raise ValueError(
                    f"Signing key too short: {signing_key['key_length']} bytes "
                    f"(minimum: {self.key_length_minimum_bytes})"
                )

            if signing_key["is_expired"]:
                raise ValueError(f"Signing key has expired: {signing_key['expires_at']}")

            # Check rotation interval
            if status["rotation_interval_days"] != self.rotation_interval_days:
                self._logger.warning(
                    f"Rotation interval mismatch: configured={self.rotation_interval_days}, "
                    f"actual={status['rotation_interval_days']}"
                )

        except Exception as e:
            self._logger.error(f"Security validation failed: {str(e)}")
            raise

    def create_signature(self, message: bytes, algorithm: str = "sha256") -> bytes:
        """
        Create an HMAC signature for the given message.

        Args:
            message: Message to sign
            algorithm: Hash algorithm to use

        Returns:
            HMAC signature bytes

        Raises:
            ValueError: If algorithm is not allowed or message is invalid
            RuntimeError: If security configuration is not initialized
        """
        if not self._initialized:
            raise RuntimeError("Security configuration not initialized")

        # Validate algorithm
        if algorithm not in self.allowed_algorithms:
            raise ValueError(f"Algorithm '{algorithm}' not in allowed algorithms: {self.allowed_algorithms}")

        # Validate message
        if not isinstance(message, bytes):
            raise ValueError("Message must be bytes")

        try:
            if not ONEIRIC_AVAILABLE:
                if not self.fallback_enabled:
                    raise RuntimeError("Oneiric not available and fallback disabled")
                return self._create_fallback_signature(message, algorithm)

            return create_hmac_signature(message, algorithm)

        except Exception as e:
            error_msg = f"Failed to create signature: {str(e)}"
            if self.log_security_events:
                self._logger.error(error_msg)
            raise ValueError(error_msg)

    def verify_signature(self, message: bytes, signature: bytes, algorithm: str = "sha256") -> bool:
        """
        Verify an HMAC signature.

        Args:
            message: Original message
            signature: Signature to verify
            algorithm: Hash algorithm used

        Returns:
            True if signature is valid, False otherwise
        """
        if not self._initialized:
            raise RuntimeError("Security configuration not initialized")

        # Validate algorithm
        if algorithm not in self.allowed_algorithms:
            return False

        # Validate message
        if not isinstance(message, bytes):
            return False

        try:
            if not ONEIRIC_AVAILABLE:
                if not self.fallback_enabled:
                    return False
                return self._verify_fallback_signature(message, signature, algorithm)

            return verify_hmac_signature(message, signature, algorithm)

        except Exception as e:
            if self.log_security_events:
                self._logger.warning(f"Signature verification failed: {str(e)}")
            return False

    def _create_fallback_signature(self, message: bytes, algorithm: str) -> bytes:
        """Create signature using fallback key."""
        if self.fallback_signing_key is None:
            raise RuntimeError("No fallback signing key available")

        h = hmac.new(self.fallback_signing_key, message, getattr(hashlib, algorithm))
        return h.digest()

    def _verify_fallback_signature(self, message: bytes, signature: bytes, algorithm: str) -> bool:
        """Verify signature using fallback key."""
        try:
            expected_signature = self._create_fallback_signature(message, algorithm)
            return secrets.compare_digest(expected_signature, signature)
        except Exception:
            return False

    def rotate_keys(self) -> Dict[str, str]:
        """
        Manually rotate all security keys.

        Returns:
            Dict mapping key names to their new IDs

        Raises:
            RuntimeError: If Oneiric is not available or operation fails
        """
        if not self._initialized:
            raise RuntimeError("Security configuration not initialized")

        if not ONEIRIC_AVAILABLE:
            raise RuntimeError("Cannot rotate keys without Oneiric")

        try:
            result = self._adapter.rotate_all_keys()
            self._log_security_event("Manual key rotation completed")
            return result
        except Exception as e:
            error_msg = f"Failed to rotate keys: {str(e)}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_security_status(self) -> Dict[str, Any]:
        """
        Get comprehensive security status information.

        Returns:
            Dict containing security status information
        """
        if not self._initialized:
            return {"initialized": False, "error": "Not initialized"}

        status = {
            "initialized": True,
            "oneiric_available": ONEIRIC_AVAILABLE,
            "fallback_mode": not ONEIRIC_AVAILABLE and self.fallback_enabled,
            "secret_prefix": self.secret_prefix,
            "rotation_interval_days": self.rotation_interval_days,
            "key_length_minimum_bytes": self.key_length_minimum_bytes,
            "allowed_algorithms": self.allowed_algorithms,
            "auto_rotation_enabled": self.enable_auto_rotation,
            "strict_mode_enabled": self.enable_strict_mode,
            "log_security_events": self.log_security_events
        }

        if ONEIRIC_AVAILABLE and self._adapter:
            try:
                key_status = self._adapter.get_key_status()
                status["key_status"] = key_status

                # Add rotation schedule info
                if key_status.get("signing_key"):
                    signing_key = key_status["signing_key"]
                    status["days_until_rotation"] = (
                        (signing_key["expires_at"] or "").split("T")[0]
                        if signing_key.get("expires_at") else "N/A"
                    )

            except Exception as e:
                status["key_status"] = {"error": str(e)}

        return status

    def cleanup_expired_keys(self) -> int:
        """
        Clean up expired keys and return the count of keys removed.

        Returns:
            Number of keys cleaned up
        """
        if not self._initialized:
            raise RuntimeError("Security configuration not initialized")

        if not ONEIRIC_AVAILABLE:
            return 0

        try:
            cleaned_count = self._adapter.cleanup_expired_keys()
            self._log_security_event(f"Cleaned up {cleaned_count} expired keys")
            return cleaned_count
        except Exception as e:
            error_msg = f"Failed to cleanup expired keys: {str(e)}"
            self._logger.error(error_msg)
            return 0

    def create_backup_key(self) -> str:
        """
        Create a new backup key and return its ID.

        Returns:
            The ID of the newly created backup key

        Raises:
            RuntimeError: If Oneiric is not available or operation fails
        """
        if not self._initialized:
            raise RuntimeError("Security configuration not initialized")

        if not ONEIRIC_AVAILABLE:
            raise RuntimeError("Cannot create backup keys without Oneiric")

        try:
            key_id = self._adapter.create_backup_key()
            self._log_security_event(f"Created backup key: {key_id}")
            return key_id
        except Exception as e:
            error_msg = f"Failed to create backup key: {str(e)}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _log_security_event(self, message: str) -> None:
        """Log security events if enabled."""
        if self.log_security_events and self._logger:
            self._logger.info(f"[Security] {message}")

    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # Clean up resources if needed
        pass


# Global security configuration instance
_global_config: Optional[SecurityConfig] = None


def get_security_config() -> SecurityConfig:
    """
    Get the global security configuration instance.

    Returns:
        The SecurityConfig instance

    Raises:
        RuntimeError: If no global configuration has been set
    """
    global _global_config

    if _global_config is None:
        raise RuntimeError("No global security configuration has been set")

    return _global_config


def initialize_security(
    secret_prefix: str = "durus/hmac",
    rotation_interval_days: int = 90,
    fallback_enabled: bool = False,
    **kwargs
) -> SecurityConfig:
    """
    Initialize the global security configuration.

    Args:
        secret_prefix: Prefix for secret names in Oneiric
        rotation_interval_days: Key rotation interval in days
        fallback_enabled: Enable fallback mode for development/testing
        **kwargs: Additional configuration options for SecurityConfig

    Returns:
        The initialized SecurityConfig instance
    """
    global _global_config

    _global_config = SecurityConfig(
        secret_prefix=secret_prefix,
        rotation_interval_days=rotation_interval_days,
        fallback_enabled=fallback_enabled,
        **kwargs
    )

    return _global_config

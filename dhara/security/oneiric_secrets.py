"""
Oneiric Secrets Adapter for HMAC Signing Keys

This module provides a secure secrets management interface using Oneiric secrets adapters.
It handles automatic key rotation, validation, and thread-safe access for HMAC signing operations.
"""

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional

try:
    from oneiric import secrets

    ONEIRIC_AVAILABLE = True
except ImportError:
    ONEIRIC_AVAILABLE = False
    secrets = None


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass
class SecretKey:
    """Represents a cryptographic key with metadata."""

    key_id: str
    key_material: bytes
    created_at: datetime
    expires_at: datetime | None = None
    is_active: bool = True
    rotation_interval: timedelta = timedelta(days=90)
    fallback_key: Optional["SecretKey"] = None

    @property
    def is_expired(self) -> bool:
        """Check if the key has expired."""
        if self.expires_at is None:
            return False
        return _utcnow() > _as_utc(self.expires_at)

    @property
    def age(self) -> timedelta:
        """Get the age of the key."""
        return _utcnow() - _as_utc(self.created_at)

    def rotate(self) -> "SecretKey":
        """Create a new rotated version of this key."""
        new_key = SecretKey(
            key_id=f"{self.key_id}_rotated_{int(time.time())}",
            key_material=secrets.token_bytes(32),  # 256-bit key
            created_at=_utcnow(),
            expires_at=_utcnow() + self.rotation_interval,
            rotation_interval=self.rotation_interval,
        )
        return new_key


class OneiricSecretsAdapter:
    """Oneiric secrets adapter with automatic key rotation and validation."""

    def __init__(self, secret_prefix: str = "durus/hmac", rotation_interval: int = 90):
        """
        Initialize the Oneiric secrets adapter.

        Args:
            secret_prefix: Prefix for secret names in Oneiric
            rotation_interval: Key rotation interval in days (default: 90)
        """
        if not ONEIRIC_AVAILABLE:
            raise RuntimeError(
                "Oneiric secrets library is not available. "
                "Please install the Oneiric SDK or check your environment."
            )

        self.secret_prefix = secret_prefix.rstrip("/")
        self.rotation_interval = timedelta(days=rotation_interval)
        self._keys: dict[str, SecretKey] = {}
        self._active_keys: dict[str, SecretKey] = {}
        self._lock = threading.RLock()
        self._initialized = False

        # Thread-safe key loading and rotation
        self._load_secrets()
        self._start_rotation_timer()

    def _load_secrets(self) -> None:
        """Load secrets from Oneiric storage."""
        if not self._initialized:
            with self._lock:
                if self._initialized:
                    return

                try:
                    # Load primary signing key
                    primary_key = self._get_or_create_key("signing_key")
                    self._active_keys["signing"] = primary_key

                    # Load backup/rotated keys if they exist
                    backup_keys = self._get_backup_keys()
                    for key in backup_keys:
                        self._keys[key.key_id] = key

                    self._initialized = True
                    self._validate_keys()

                except Exception as e:
                    raise RuntimeError(f"Failed to load secrets from Oneiric: {str(e)}")

    def _get_or_create_key(self, key_name: str) -> SecretKey:
        """Get an existing key or create a new one."""
        full_secret_name = f"{self.secret_prefix}/{key_name}"
        key_id = f"{self.secret_prefix}_{key_name}"

        try:
            # Try to load existing key
            key_material = secrets.get(full_secret_name)
            created_at_str = secrets.get(f"{full_secret_name}_created", "")
            expires_at_str = secrets.get(f"{full_secret_name}_expires", "")

            key = SecretKey(
                key_id=key_id,
                key_material=key_material,
                created_at=datetime.fromisoformat(created_at_str)
                if created_at_str
                else _utcnow(),
                expires_at=datetime.fromisoformat(expires_at_str)
                if expires_at_str
                else _utcnow() + self.rotation_interval,
                rotation_interval=self.rotation_interval,
            )

            # Check if key needs rotation
            if key.is_expired or key.age > key.rotation_interval:
                key = self._rotate_key(key, full_secret_name)

        except secrets.SecretNotFoundError:
            # Create new key
            key = SecretKey(
                key_id=key_id,
                key_material=secrets.token_bytes(32),  # 256-bit minimum
                created_at=_utcnow(),
                expires_at=_utcnow() + self.rotation_interval,
                rotation_interval=self.rotation_interval,
            )

            # Store in Oneiric
            secrets.set(full_secret_name, key.key_material)
            secrets.set(f"{full_secret_name}_created", key.created_at.isoformat())
            secrets.set(f"{full_secret_name}_expires", key.expires_at.isoformat())

        except Exception as e:
            raise RuntimeError(f"Failed to handle key {key_name}: {str(e)}")

        return key

    def _rotate_key(self, key: SecretKey, secret_name: str) -> SecretKey:
        """Rotate an existing key."""
        new_key = key.rotate()

        # Store new key
        secrets.set(secret_name, new_key.key_material)
        secrets.set(f"{secret_name}_created", new_key.created_at.isoformat())
        secrets.set(f"{secret_name}_expires", new_key.expires_at.isoformat())

        # Mark old key as inactive
        key.is_active = False

        return new_key

    def _get_backup_keys(self) -> list[SecretKey]:
        """Get backup/rotated keys."""
        backup_keys = []

        # Look for rotated keys
        try:
            secret_names = secrets.list(prefix=f"{self.secret_prefix}/")

            for secret_name in secret_names:
                if "signing_key_rotated" in secret_name:
                    key_name = secret_name.split("/")[-1]
                    key = self._get_or_create_key(key_name)
                    backup_keys.append(key)

        except Exception:
            # If listing fails, ignore and continue
            pass

        return backup_keys

    def _validate_keys(self) -> None:
        """Validate all loaded keys meet security requirements."""
        with self._lock:
            for key in self._active_keys.values():
                if len(key.key_material) < 32:  # 256-bit minimum
                    raise ValueError(
                        f"Key {key.key_id} is too short: {len(key.key_material)} bytes"
                    )

                if key.is_expired:
                    raise ValueError(f"Key {key.key_id} has expired")

            # Ensure we have at least one active signing key
            if "signing" not in self._active_keys:
                raise RuntimeError("No active signing key available")

    def _start_rotation_timer(self) -> None:
        """Start the automatic rotation timer."""

        def rotation_task():
            while True:
                try:
                    self._auto_rotate_keys()
                    time.sleep(24 * 3600)  # Check every 24 hours
                except Exception:
                    # Log error but continue
                    time.sleep(3600)  # Wait 1 hour before retry

        # Start rotation in a daemon thread
        thread = threading.Thread(target=rotation_task, daemon=True)
        thread.start()

    def _auto_rotate_keys(self) -> None:
        """Automatically rotate keys that need it."""
        with self._lock:
            if not self._initialized:
                return

            # Rotate signing key if needed
            if "signing" in self._active_keys:
                key = self._active_keys["signing"]
                if key.age > key.rotation_interval:
                    # Create new key while maintaining fallback
                    new_key = key.rotate()
                    self._active_keys["signing"] = new_key

                    # Store in keys collection as backup
                    self._keys[key.key_id] = key
                    self._keys[new_key.key_id] = new_key

    def get_signing_key(self, algorithm: str = "sha256") -> tuple[bytes, str]:
        """
        Get the current signing key for HMAC operations.

        Args:
            algorithm: Hash algorithm to use (sha256, sha384, sha512)

        Returns:
            Tuple of (key_material, key_id)

        Raises:
            ValueError: If key is invalid or algorithm is unsupported
        """
        with self._lock:
            if "signing" not in self._active_keys:
                raise ValueError("No active signing key available")

            key = self._active_keys["signing"]

            # Validate algorithm
            if algorithm not in hashlib.algorithms_available:
                raise ValueError(f"Unsupported algorithm: {algorithm}")

            return key.key_material, key.key_id

    def create_backup_key(self) -> str:
        """
        Create a new backup key and return its ID.

        Returns:
            The ID of the newly created backup key
        """
        with self._lock:
            backup_key = self._get_or_create_key("backup_signing_key")

            # Set as fallback to primary signing key
            primary_key = self._active_keys["signing"]
            backup_key.fallback_key = primary_key

            return backup_key.key_id

    def rotate_all_keys(self) -> dict[str, str]:
        """
        Manually rotate all keys.

        Returns:
            Dict mapping key names to their new IDs
        """
        with self._lock:
            results = {}

            # Rotate primary signing key
            if "signing" in self._active_keys:
                old_key = self._active_keys["signing"]
                new_key = old_key.rotate()
                self._active_keys["signing"] = new_key

                # Store old key as backup
                self._keys[old_key.key_id] = old_key
                results["signing"] = new_key.key_id

            return results

    def cleanup_expired_keys(self) -> int:
        """
        Clean up expired keys.

        Returns:
            Number of keys cleaned up
        """
        with self._lock:
            cleaned_count = 0

            # Remove expired keys from collection
            expired_keys = [k for k in self._keys.values() if k.is_expired]
            for key in expired_keys:
                if key.key_id in self._keys:
                    del self._keys[key.key_id]
                    cleaned_count += 1

            return cleaned_count

    def get_key_status(self) -> dict[str, str | int | bool]:
        """
        Get status information about all keys.

        Returns:
            Dict with key status information
        """
        with self._lock:
            status = {
                "total_keys": len(self._keys) + len(self._active_keys),
                "active_keys": len(self._active_keys),
                "backup_keys": len(self._keys),
                "rotation_interval_days": self.rotation_interval.days,
                "initialized": self._initialized,
                "secret_prefix": self.secret_prefix,
            }

            # Add details for active keys
            if "signing" in self._active_keys:
                key = self._active_keys["signing"]
                status["signing_key"] = {
                    "key_id": key.key_id,
                    "created_at": key.created_at.isoformat(),
                    "expires_at": key.expires_at.isoformat()
                    if key.expires_at
                    else None,
                    "age_days": key.age.days,
                    "is_expired": key.is_expired,
                    "is_active": key.is_active,
                    "key_length": len(key.key_material),
                }

            return status


# Global adapter instance
_adapter: OneiricSecretsAdapter | None = None
_adapter_lock = threading.Lock()


def get_secrets_adapter(
    secret_prefix: str = "durus/hmac", rotation_interval: int = 90
) -> OneiricSecretsAdapter:
    """
    Get the global secrets adapter instance.

    Args:
        secret_prefix: Prefix for secret names in Oneiric
        rotation_interval: Key rotation interval in days

    Returns:
        The OneiricSecretsAdapter instance
    """
    global _adapter

    if _adapter is None:
        with _adapter_lock:
            if _adapter is None:
                _adapter = OneiricSecretsAdapter(secret_prefix, rotation_interval)

    return _adapter


def create_hmac_signature(message: bytes, algorithm: str = "sha256") -> bytes:
    """
    Create an HMAC signature using the current signing key.

    Args:
        message: Message to sign
        algorithm: Hash algorithm to use

    Returns:
        HMAC signature bytes

    Raises:
        ValueError: If algorithm is unsupported or message is invalid
    """
    if not isinstance(message, bytes):
        raise ValueError("Message must be bytes")

    adapter = get_secrets_adapter()
    key_material, key_id = adapter.get_signing_key(algorithm)

    try:
        h = hmac.new(key_material, message, getattr(hashlib, algorithm))
        return h.digest()
    except Exception as e:
        raise ValueError(f"Failed to create HMAC signature: {str(e)}")


def verify_hmac_signature(
    message: bytes, signature: bytes, algorithm: str = "sha256"
) -> bool:
    """
    Verify an HMAC signature.

    Args:
        message: Original message
        signature: Signature to verify
        algorithm: Hash algorithm used

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        expected_signature = create_hmac_signature(message, algorithm)
        return secrets.compare_digest(expected_signature, signature)
    except Exception:
        return False


def initialize_secrets(
    secret_prefix: str = "durus/hmac", rotation_interval: int = 90
) -> None:
    """
    Initialize the global secrets adapter.

    Args:
        secret_prefix: Prefix for secret names in Oneiric
        rotation_interval: Key rotation interval in days
    """
    global _adapter
    _adapter = OneiricSecretsAdapter(secret_prefix, rotation_interval)

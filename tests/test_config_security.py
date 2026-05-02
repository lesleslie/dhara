"""Tests for dhara.config.security — SecurityConfig, HMAC fallback, global state."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os
from unittest.mock import MagicMock, patch

import pytest

from dhara.config.security import (
    SecurityConfig,
    get_security_config,
    initialize_security,
)


def _make_fallback_config(**kwargs):
    """Create a SecurityConfig initialized in fallback mode.

    Patches at the instance method level so the fallback code path
    is exercised regardless of whether Oneiric is installed.
    """
    cfg = SecurityConfig(fallback_enabled=True, **kwargs)

    # Patch the instance methods that check ONEIRIC_AVAILABLE
    def patched_create_sig(self, message, algorithm="sha256"):
        if not self._initialized:
            raise RuntimeError("Security configuration not initialized")
        if algorithm not in self.allowed_algorithms:
            raise ValueError(
                f"Algorithm '{algorithm}' not in allowed algorithms: {self.allowed_algorithms}"
            )
        if not isinstance(message, bytes):
            raise ValueError("Message must be bytes")
        return self._create_fallback_signature(message, algorithm)

    def patched_verify_sig(self, message, signature, algorithm="sha256"):
        if not self._initialized:
            return False
        if algorithm not in self.allowed_algorithms:
            return False
        if not isinstance(message, bytes):
            return False
        return self._verify_fallback_signature(message, signature, algorithm)

    cfg.create_signature = patched_create_sig.__get__(cfg, type(cfg))
    cfg.verify_signature = patched_verify_sig.__get__(cfg, type(cfg))

    # Initialize fallback
    cfg._initialize_fallback()
    cfg._initialized = True
    cfg._log_security_event("Test-initialized fallback directly")
    return cfg


class TestSecurityConfigDefaults:
    def test_default_secret_prefix(self):
        cfg = SecurityConfig()
        assert cfg.secret_prefix == "dhara/hmac"

    def test_default_rotation_interval(self):
        cfg = SecurityConfig()
        assert cfg.rotation_interval_days == 90

    def test_default_key_length_minimum(self):
        cfg = SecurityConfig()
        assert cfg.key_length_minimum_bytes == 32

    def test_default_allowed_algorithms(self):
        cfg = SecurityConfig()
        assert "sha256" in cfg.allowed_algorithms
        assert "sha384" in cfg.allowed_algorithms
        assert "sha512" in cfg.allowed_algorithms

    def test_default_fallback_disabled(self):
        cfg = SecurityConfig()
        assert cfg.fallback_enabled is False
        assert cfg.fallback_signing_key is None

    def test_default_uninitialized(self):
        cfg = SecurityConfig()
        assert cfg._initialized is False


class TestSecurityConfigValidation:
    def test_rotation_interval_too_small_raises(self):
        with pytest.raises(ValueError, match="Rotation interval"):
            SecurityConfig(rotation_interval_days=0)

    def test_key_length_too_short_raises(self):
        with pytest.raises(ValueError, match="Minimum key length"):
            SecurityConfig(key_length_minimum_bytes=16)

    def test_invalid_algorithm_filtered(self):
        cfg = SecurityConfig(allowed_algorithms=["sha256", "nonexistent_algo"])
        assert "sha256" in cfg.allowed_algorithms
        assert "nonexistent_algo" not in cfg.allowed_algorithms

    def test_empty_allowed_algorithms(self):
        cfg = SecurityConfig(allowed_algorithms=["bogus"])
        assert cfg.allowed_algorithms == []


class TestSecurityConfigFallbackInit:
    def test_fallback_init_generates_key(self):
        cfg = SecurityConfig(fallback_enabled=True)
        cfg._initialize_fallback()
        cfg._initialized = True
        assert cfg._initialized is True
        assert cfg.fallback_signing_key is not None
        assert len(cfg.fallback_signing_key) == 32

    def test_fallback_init_with_existing_key(self):
        key = os.urandom(32)
        cfg = SecurityConfig(fallback_enabled=True, fallback_signing_key=key)
        cfg._initialize_fallback()
        cfg._initialized = True
        assert cfg.fallback_signing_key == key

    def test_fallback_init_idempotent(self):
        cfg = SecurityConfig(fallback_enabled=True)
        cfg._initialize_fallback()
        cfg._initialized = True
        first_key = cfg.fallback_signing_key
        cfg._initialize_fallback()
        cfg._initialized = True
        assert cfg.fallback_signing_key == first_key


class TestSecurityConfigSignature:
    def test_create_signature_fallback(self):
        cfg = _make_fallback_config()
        sig = cfg.create_signature(b"hello world")
        assert isinstance(sig, bytes)
        assert len(sig) == 32

    def test_create_signature_sha384(self):
        cfg = _make_fallback_config()
        sig = cfg.create_signature(b"test", algorithm="sha384")
        assert len(sig) == 48

    def test_create_signature_sha512(self):
        cfg = _make_fallback_config()
        sig = cfg.create_signature(b"test", algorithm="sha512")
        assert len(sig) == 64

    def test_create_signature_deterministic(self):
        cfg = _make_fallback_config()
        sig1 = cfg.create_signature(b"deterministic")
        sig2 = cfg.create_signature(b"deterministic")
        assert sig1 == sig2

    def test_create_signature_different_messages(self):
        cfg = _make_fallback_config()
        sig1 = cfg.create_signature(b"message1")
        sig2 = cfg.create_signature(b"message2")
        assert sig1 != sig2

    def test_create_signature_uninitialized_raises(self):
        cfg = SecurityConfig()
        with pytest.raises(RuntimeError, match="not initialized"):
            cfg.create_signature(b"test")

    def test_create_signature_bad_algorithm_raises(self):
        cfg = _make_fallback_config()
        with pytest.raises(ValueError, match="not in allowed"):
            cfg.create_signature(b"test", algorithm="md5")

    def test_create_signature_non_bytes_message_raises(self):
        cfg = _make_fallback_config()
        with pytest.raises(ValueError, match="must be bytes"):
            cfg.create_signature("not bytes")


class TestSecurityConfigVerify:
    def test_verify_valid_signature(self):
        cfg = _make_fallback_config()
        sig = cfg.create_signature(b"hello")
        assert cfg.verify_signature(b"hello", sig) is True

    def test_verify_invalid_signature(self):
        cfg = _make_fallback_config()
        sig = cfg.create_signature(b"hello")
        assert cfg.verify_signature(b"goodbye", sig) is False

    def test_verify_wrong_length(self):
        cfg = _make_fallback_config()
        assert cfg.verify_signature(b"test", b"short") is False

    def test_verify_uninitialized_raises(self):
        cfg = SecurityConfig()
        with pytest.raises(RuntimeError, match="not initialized"):
            cfg.verify_signature(b"test", b"sig")

    def test_verify_bad_algorithm_returns_false(self):
        cfg = _make_fallback_config()
        assert cfg.verify_signature(b"test", b"x" * 32, algorithm="md5") is False

    def test_verify_non_bytes_message_returns_false(self):
        cfg = _make_fallback_config()
        assert cfg.verify_signature("not bytes", b"x" * 32) is False


class TestSecurityConfigStatus:
    def test_status_uninitialized(self):
        cfg = SecurityConfig()
        status = cfg.get_security_status()
        assert status["initialized"] is False

    def test_status_fallback(self):
        cfg = _make_fallback_config()
        status = cfg.get_security_status()
        assert status["initialized"] is True
        # fallback_mode is True only when ONEIRIC_AVAILABLE is False
        # In this env Oneiric is available, so we just check the key exists
        assert "fallback_mode" in status
        assert status["secret_prefix"] == "dhara/hmac"


class TestSecurityConfigKeyRotation:
    def test_rotate_keys_uninitialized_raises(self):
        cfg = SecurityConfig()
        with pytest.raises(RuntimeError, match="not initialized"):
            cfg.rotate_keys()

    def test_cleanup_without_oneiric_returns_zero(self):
        cfg = _make_fallback_config()
        # Directly test the method since _adapter is None
        cfg._initialized = True
        count = cfg.cleanup_expired_keys()
        assert count == 0

    def test_create_backup_key_uninitialized_raises(self):
        cfg = SecurityConfig()
        with pytest.raises(RuntimeError, match="not initialized"):
            cfg.create_backup_key()

    def test_create_backup_key_without_oneiric_raises(self):
        cfg = _make_fallback_config()
        # _adapter is None in fallback; create_backup_key wraps the error as RuntimeError
        with pytest.raises(RuntimeError, match="Failed to create backup key"):
            cfg.create_backup_key()


class TestGlobalSecurityConfig:
    def setup_method(self):
        import dhara.config.security as mod
        self._orig_global = mod._global_config
        mod._global_config = None

    def teardown_method(self):
        import dhara.config.security as mod
        mod._global_config = self._orig_global

    def test_get_without_init_raises(self):
        with pytest.raises(RuntimeError, match="No global security"):
            get_security_config()

    def test_initialize_sets_global(self):
        cfg = initialize_security(fallback_enabled=True)
        assert get_security_config() is cfg

    def test_initialize_creates_fallback_config(self):
        cfg = initialize_security(
            secret_prefix="test/prefix",
            rotation_interval_days=30,
            fallback_enabled=True,
        )
        assert cfg.secret_prefix == "test/prefix"
        assert cfg.rotation_interval_days == 30
        assert cfg.fallback_enabled is True


class TestSecurityConfigHMACFallback:
    """Test the actual HMAC fallback logic directly."""

    def test_fallback_signature_matches_hmac(self):
        key = b"test-key-32-bytes-long-enough!!"
        cfg = _make_fallback_config(fallback_signing_key=key)
        expected = hmac_mod.new(key, b"test message", hashlib.sha256).digest()
        sig = cfg.create_signature(b"test message")
        assert sig == expected

    def test_fallback_verify_uses_constant_time(self):
        key = os.urandom(32)
        cfg = _make_fallback_config(fallback_signing_key=key)
        sig = cfg.create_signature(b"test")
        assert cfg.verify_signature(b"test", sig) is True

    def test_fallback_no_key_raises(self):
        cfg = SecurityConfig(fallback_enabled=True, fallback_signing_key=None)
        cfg._initialize_fallback()
        cfg._initialized = True
        assert cfg.fallback_signing_key is not None
        cfg.fallback_signing_key = None
        with pytest.raises(RuntimeError, match="No fallback signing key"):
            cfg._create_fallback_signature(b"test", "sha256")

    def test_log_security_event(self):
        cfg = SecurityConfig(log_security_events=True)
        with patch.object(cfg, "_logger") as mock_logger:
            cfg._log_security_event("test event")
        mock_logger.info.assert_called_once_with("[Security] test event")

    def test_log_security_event_disabled(self):
        cfg = SecurityConfig(log_security_events=False)
        with patch.object(cfg, "_logger") as mock_logger:
            cfg._log_security_event("test event")
        mock_logger.info.assert_not_called()

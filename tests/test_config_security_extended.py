"""Extended tests for dhara.config.security — covering Oneiric paths and edge cases.

These tests complement the existing test_config_security.py by exercising:
- The Oneiric-available code paths (initialize, create/verify signature, rotate, cleanup, backup)
- _validate_security_setup and its various failure modes
- get_security_status with adapter details
- Context manager protocol
- Edge cases and error handling in the Oneiric branches
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from dhara.config.security import (
    ONEIRIC_AVAILABLE,
    SecurityConfig,
    get_security_config,
    initialize_security,
)


# ---------------------------------------------------------------------------
# Helper: build a SecurityConfig that thinks ONEIRIC_AVAILABLE is True
# and has a fully mocked _adapter.
# ---------------------------------------------------------------------------


def _make_oneiric_config(**kwargs):
    """Create a SecurityConfig with a mocked Oneiric adapter.

    Patches at the module level so that ONEIRIC_AVAILABLE reads True, and
    the _adapter is a MagicMock.  This exercises the Oneiric code paths
    without requiring a real Oneiric installation.
    """
    mock_adapter = MagicMock()
    mock_adapter.get_key_status.return_value = {
        "signing_key": {
            "key_id": "test_signing_key",
            "key_length": 64,
            "is_expired": False,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=60)).isoformat(),
            "is_active": True,
            "created_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        },
        "rotation_interval_days": 90,
    }
    mock_adapter.rotate_all_keys.return_value = {"signing": "new_key_id"}
    mock_adapter.cleanup_expired_keys.return_value = 3
    mock_adapter.create_backup_key.return_value = "backup_key_001"

    cfg = SecurityConfig(**kwargs)

    # Inject the mock adapter and mark initialized
    cfg._adapter = mock_adapter
    cfg._initialized = True

    return cfg, mock_adapter


def _make_oneiric_config_uninitialized(**kwargs):
    """Like _make_oneiric_config but _initialized is False (for testing initialize)."""
    mock_adapter = MagicMock()
    mock_adapter.get_key_status.return_value = {
        "signing_key": {
            "key_id": "test_signing_key",
            "key_length": 64,
            "is_expired": False,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=60)).isoformat(),
            "is_active": True,
            "created_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        },
        "rotation_interval_days": 90,
    }
    cfg = SecurityConfig(**kwargs)
    cfg._adapter = mock_adapter
    return cfg, mock_adapter


# =========================================================================
# Tests for initialize() with Oneiric available
# =========================================================================


class TestInitializeOneiricPath:
    """Test SecurityConfig.initialize() when ONEIRIC_AVAILABLE is True."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.initialize_secrets")
    @patch("dhara.config.security.create_hmac_signature", side_effect=RuntimeError("mock"))
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("mock"))
    def test_initialize_with_oneiric_sets_adapter(self, _mock_verify, _mock_create, mock_init_secrets):
        """When Oneiric is available, initialize() calls initialize_secrets."""
        mock_adapter = MagicMock()
        mock_adapter.get_key_status.return_value = {
            "signing_key": {
                "key_id": "test_key",
                "key_length": 64,
                "is_expired": False,
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            "rotation_interval_days": 30,
        }
        mock_init_secrets.return_value = mock_adapter
        cfg = SecurityConfig(secret_prefix="test/hmac", rotation_interval_days=30)
        cfg.initialize()
        mock_init_secrets.assert_called_once_with("test/hmac", 30)
        assert cfg._initialized is True
        assert cfg._adapter is not None

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.initialize_secrets")
    @patch("dhara.config.security.create_hmac_signature", side_effect=RuntimeError("mock"))
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("mock"))
    def test_initialize_idempotent(self, _mock_verify, _mock_create, mock_init_secrets):
        """Calling initialize() twice does not re-initialize."""
        mock_adapter = MagicMock()
        mock_adapter.get_key_status.return_value = {
            "signing_key": {
                "key_id": "test_key",
                "key_length": 64,
                "is_expired": False,
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            "rotation_interval_days": 90,
        }
        mock_init_secrets.return_value = mock_adapter
        cfg = SecurityConfig()
        cfg.initialize()
        cfg.initialize()
        mock_init_secrets.assert_called_once()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.initialize_secrets", side_effect=RuntimeError("adapter error"))
    @patch("dhara.config.security.create_hmac_signature", side_effect=RuntimeError("mock"))
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("mock"))
    def test_initialize_oneiric_error_raises(self, _mock_verify, _mock_create, mock_init_secrets):
        """If initialize_secrets raises, initialize() wraps in RuntimeError."""
        cfg = SecurityConfig()
        with pytest.raises(RuntimeError, match="Failed to initialize security configuration"):
            cfg.initialize()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    @patch("dhara.config.security.create_hmac_signature", side_effect=RuntimeError("mock"))
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("mock"))
    def test_initialize_no_oneiric_no_fallback_raises(self, _mock_verify, _mock_create):
        """When Oneiric is unavailable and fallback is disabled, initialize() raises."""
        cfg = SecurityConfig(fallback_enabled=False)
        with pytest.raises(RuntimeError, match="Oneiric secrets library is not available"):
            cfg.initialize()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.initialize_secrets")
    @patch("dhara.config.security.create_hmac_signature", side_effect=RuntimeError("mock"))
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("mock"))
    def test_initialize_with_key_validation_enabled(self, _mock_verify, _mock_create, mock_init_secrets):
        """When require_key_validation is True, _validate_security_setup is called."""
        mock_adapter = MagicMock()
        mock_adapter.get_key_status.return_value = {
            "signing_key": {
                "key_id": "key1",
                "key_length": 64,
                "is_expired": False,
                "expires_at": "2099-01-01T00:00:00+00:00",
                "is_active": True,
                "created_at": "2025-01-01T00:00:00+00:00",
            },
            "rotation_interval_days": 90,
        }
        mock_init_secrets.return_value = mock_adapter
        cfg = SecurityConfig(require_key_validation=True, rotation_interval_days=90)
        cfg.initialize()
        mock_adapter.get_key_status.assert_called_once()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.initialize_secrets")
    @patch("dhara.config.security.create_hmac_signature", side_effect=RuntimeError("mock"))
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("mock"))
    def test_initialize_with_key_validation_disabled(self, _mock_verify, _mock_create, mock_init_secrets):
        """When require_key_validation is False, _validate_security_setup is skipped."""
        mock_adapter = MagicMock()
        mock_init_secrets.return_value = mock_adapter
        cfg = SecurityConfig(require_key_validation=False)
        cfg.initialize()
        mock_adapter.get_key_status.assert_not_called()


# =========================================================================
# Tests for _validate_security_setup
# =========================================================================


class TestValidateSecuritySetup:
    """Test _validate_security_setup in Oneiric mode."""

    def test_validate_no_signing_key_raises(self):
        """Raises RuntimeError when signing_key is missing from status."""
        cfg, mock_adapter = _make_oneiric_config_uninitialized()
        mock_adapter.get_key_status.return_value = {}
        cfg._initialized = False

        # Directly call _validate_security_setup (it's the Oneiric path)
        with patch("dhara.config.security.ONEIRIC_AVAILABLE", True):
            with pytest.raises(RuntimeError, match="No signing key available"):
                cfg._validate_security_setup()

    def test_validate_key_too_short_raises(self):
        """Raises ValueError when signing key is shorter than minimum."""
        cfg, mock_adapter = _make_oneiric_config_uninitialized(
            key_length_minimum_bytes=64
        )
        mock_adapter.get_key_status.return_value = {
            "signing_key": {
                "key_length": 32,  # less than 64
                "is_expired": False,
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            "rotation_interval_days": 90,
        }

        with patch("dhara.config.security.ONEIRIC_AVAILABLE", True):
            with pytest.raises(ValueError, match="Signing key too short"):
                cfg._validate_security_setup()

    def test_validate_expired_key_raises(self):
        """Raises ValueError when signing key has expired."""
        cfg, mock_adapter = _make_oneiric_config_uninitialized()
        mock_adapter.get_key_status.return_value = {
            "signing_key": {
                "key_length": 64,
                "is_expired": True,
                "expires_at": "2020-01-01T00:00:00+00:00",
            },
            "rotation_interval_days": 90,
        }

        with patch("dhara.config.security.ONEIRIC_AVAILABLE", True):
            with pytest.raises(ValueError, match="Signing key has expired"):
                cfg._validate_security_setup()

    def test_validate_rotation_interval_mismatch_warns(self):
        """Logs a warning when rotation interval doesn't match."""
        cfg, mock_adapter = _make_oneiric_config_uninitialized(
            rotation_interval_days=30
        )
        mock_adapter.get_key_status.return_value = {
            "signing_key": {
                "key_length": 64,
                "is_expired": False,
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            "rotation_interval_days": 90,  # mismatch with config's 30
        }

        with patch("dhara.config.security.ONEIRIC_AVAILABLE", True):
            with patch.object(cfg, "_logger") as mock_logger:
                cfg._validate_security_setup()
                # Should warn about mismatch but not raise
                mock_logger.warning.assert_called_once()
                assert "Rotation interval mismatch" in mock_logger.warning.call_args[0][0]

    def test_validate_adapter_exception_propagates(self):
        """Exception from adapter.get_key_status propagates up."""
        cfg, mock_adapter = _make_oneiric_config_uninitialized()
        mock_adapter.get_key_status.side_effect = RuntimeError("adapter boom")

        with patch("dhara.config.security.ONEIRIC_AVAILABLE", True):
            with pytest.raises(RuntimeError, match="adapter boom"):
                cfg._validate_security_setup()

    def test_validate_skipped_when_oneiric_unavailable(self):
        """Validation is a no-op when ONEIRIC_AVAILABLE is False."""
        cfg = SecurityConfig()
        with patch("dhara.config.security.ONEIRIC_AVAILABLE", False):
            # Should not raise even with no adapter
            cfg._validate_security_setup()


# =========================================================================
# Tests for create_signature with Oneiric available
# =========================================================================


class TestCreateSignatureOneiricPath:
    """Test create_signature() when ONEIRIC_AVAILABLE is True."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.create_hmac_signature")
    def test_create_signature_delegates_to_oneiric(self, mock_create):
        mock_create.return_value = b"oneiric_sig_32_bytes_padding!"
        cfg, _ = _make_oneiric_config()
        sig = cfg.create_signature(b"test message")
        mock_create.assert_called_once_with(b"test message", "sha256")
        assert sig == b"oneiric_sig_32_bytes_padding!"

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.create_hmac_signature")
    def test_create_signature_custom_algorithm(self, mock_create):
        mock_create.return_value = b"x" * 48
        cfg, _ = _make_oneiric_config()
        sig = cfg.create_signature(b"test", algorithm="sha384")
        mock_create.assert_called_once_with(b"test", "sha384")
        assert sig == b"x" * 48

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.create_hmac_signature", side_effect=ValueError("sig error"))
    def test_create_signature_oneiric_error_wraps(self, mock_create):
        """When create_hmac_signature raises, it's wrapped in ValueError."""
        cfg, _ = _make_oneiric_config(log_security_events=True)
        with pytest.raises(ValueError, match="Failed to create signature"):
            cfg.create_signature(b"test")

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.create_hmac_signature", side_effect=RuntimeError("sig error"))
    def test_create_signature_oneiric_error_logs_when_enabled(self, mock_create):
        """Error is logged when log_security_events is True."""
        cfg, _ = _make_oneiric_config(log_security_events=True)
        with patch.object(cfg, "_logger") as mock_logger:
            with pytest.raises(ValueError, match="Failed to create signature"):
                cfg.create_signature(b"test")
            mock_logger.error.assert_called_once()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.create_hmac_signature", side_effect=RuntimeError("sig error"))
    def test_create_signature_oneiric_error_no_log_when_disabled(self, mock_create):
        """Error is NOT logged when log_security_events is False."""
        cfg, _ = _make_oneiric_config(log_security_events=False)
        with patch.object(cfg, "_logger") as mock_logger:
            with pytest.raises(ValueError, match="Failed to create signature"):
                cfg.create_signature(b"test")
            mock_logger.error.assert_not_called()


# =========================================================================
# Tests for verify_signature with Oneiric available
# =========================================================================


class TestVerifySignatureOneiricPath:
    """Test verify_signature() when ONEIRIC_AVAILABLE is True."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.verify_hmac_signature")
    def test_verify_signature_delegates_to_oneiric(self, mock_verify):
        mock_verify.return_value = True
        cfg, _ = _make_oneiric_config()
        result = cfg.verify_signature(b"test message", b"signature")
        mock_verify.assert_called_once_with(b"test message", b"signature", "sha256")
        assert result is True

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.verify_hmac_signature", return_value=False)
    def test_verify_signature_invalid_returns_false(self, mock_verify):
        cfg, _ = _make_oneiric_config()
        assert cfg.verify_signature(b"test", b"bad_sig") is False

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.verify_hmac_signature")
    def test_verify_signature_custom_algorithm(self, mock_verify):
        mock_verify.return_value = True
        cfg, _ = _make_oneiric_config()
        result = cfg.verify_signature(b"test", b"sig", algorithm="sha512")
        mock_verify.assert_called_once_with(b"test", b"sig", "sha512")
        assert result is True

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("verify boom"))
    def test_verify_signature_oneiric_error_returns_false(self, mock_verify):
        """When verify_hmac_signature raises, returns False."""
        cfg, _ = _make_oneiric_config(log_security_events=True)
        result = cfg.verify_signature(b"test", b"sig")
        assert result is False

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("verify boom"))
    def test_verify_signature_oneiric_error_logs_warning(self, mock_verify):
        """Warning is logged when verification fails due to exception."""
        cfg, _ = _make_oneiric_config(log_security_events=True)
        with patch.object(cfg, "_logger") as mock_logger:
            cfg.verify_signature(b"test", b"sig")
            mock_logger.warning.assert_called_once()
            assert "Signature verification failed" in mock_logger.warning.call_args[0][0]

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    @patch("dhara.config.security.verify_hmac_signature", side_effect=RuntimeError("verify boom"))
    def test_verify_signature_oneiric_error_no_log_when_disabled(self, mock_verify):
        """Warning is NOT logged when log_security_events is False."""
        cfg, _ = _make_oneiric_config(log_security_events=False)
        with patch.object(cfg, "_logger") as mock_logger:
            cfg.verify_signature(b"test", b"sig")
            mock_logger.warning.assert_not_called()


# =========================================================================
# Tests for rotate_keys with Oneiric available
# =========================================================================


class TestRotateKeysOneiricPath:
    """Test rotate_keys() when ONEIRIC_AVAILABLE is True."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_rotate_keys_delegates_to_adapter(self):
        cfg, mock_adapter = _make_oneiric_config()
        result = cfg.rotate_keys()
        mock_adapter.rotate_all_keys.assert_called_once()
        assert result == {"signing": "new_key_id"}

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_rotate_keys_uninitialized_raises(self):
        cfg = SecurityConfig()
        with pytest.raises(RuntimeError, match="not initialized"):
            cfg.rotate_keys()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_rotate_keys_adapter_error_wrapped(self):
        cfg, mock_adapter = _make_oneiric_config()
        mock_adapter.rotate_all_keys.side_effect = RuntimeError("rotation failed")
        with pytest.raises(RuntimeError, match="Failed to rotate keys"):
            cfg.rotate_keys()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_rotate_keys_logs_security_event(self):
        cfg, mock_adapter = _make_oneiric_config()
        with patch.object(cfg, "_logger") as mock_logger:
            cfg.rotate_keys()
            mock_logger.info.assert_called_once_with(
                "[Security] Manual key rotation completed"
            )

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_rotate_keys_without_oneiric_raises(self):
        """When ONEIRIC_AVAILABLE is False, rotate_keys raises RuntimeError."""
        cfg = _make_oneiric_config()[0]  # _initialized=True from helper
        cfg._adapter = None
        with pytest.raises(RuntimeError, match="Cannot rotate keys without Oneiric"):
            cfg.rotate_keys()


# =========================================================================
# Tests for cleanup_expired_keys with Oneiric available
# =========================================================================


class TestCleanupExpiredKeysOneiricPath:
    """Test cleanup_expired_keys() when ONEIRIC_AVAILABLE is True."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_cleanup_delegates_to_adapter(self):
        cfg, mock_adapter = _make_oneiric_config()
        count = cfg.cleanup_expired_keys()
        mock_adapter.cleanup_expired_keys.assert_called_once()
        assert count == 3

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_cleanup_returns_zero_when_no_keys(self):
        cfg, mock_adapter = _make_oneiric_config()
        mock_adapter.cleanup_expired_keys.return_value = 0
        count = cfg.cleanup_expired_keys()
        assert count == 0

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_cleanup_uninitialized_raises(self):
        cfg = SecurityConfig()
        with pytest.raises(RuntimeError, match="not initialized"):
            cfg.cleanup_expired_keys()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_cleanup_adapter_error_returns_zero(self):
        cfg, mock_adapter = _make_oneiric_config()
        mock_adapter.cleanup_expired_keys.side_effect = RuntimeError("cleanup failed")
        count = cfg.cleanup_expired_keys()
        assert count == 0

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_cleanup_logs_security_event(self):
        cfg, mock_adapter = _make_oneiric_config()
        with patch.object(cfg, "_logger") as mock_logger:
            cfg.cleanup_expired_keys()
            mock_logger.info.assert_called_once_with(
                "[Security] Cleaned up 3 expired keys"
            )

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_cleanup_without_oneiric_returns_zero(self):
        cfg = SecurityConfig()
        cfg._initialized = True
        assert cfg.cleanup_expired_keys() == 0


# =========================================================================
# Tests for create_backup_key with Oneiric available
# =========================================================================


class TestCreateBackupKeyOneiricPath:
    """Test create_backup_key() when ONEIRIC_AVAILABLE is True."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_create_backup_key_delegates_to_adapter(self):
        cfg, mock_adapter = _make_oneiric_config()
        key_id = cfg.create_backup_key()
        mock_adapter.create_backup_key.assert_called_once()
        assert key_id == "backup_key_001"

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_create_backup_key_uninitialized_raises(self):
        cfg = SecurityConfig()
        with pytest.raises(RuntimeError, match="not initialized"):
            cfg.create_backup_key()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_create_backup_key_adapter_error_wrapped(self):
        cfg, mock_adapter = _make_oneiric_config()
        mock_adapter.create_backup_key.side_effect = RuntimeError("backup failed")
        with pytest.raises(RuntimeError, match="Failed to create backup key"):
            cfg.create_backup_key()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_create_backup_key_logs_security_event(self):
        cfg, mock_adapter = _make_oneiric_config()
        with patch.object(cfg, "_logger") as mock_logger:
            cfg.create_backup_key()
            mock_logger.info.assert_called_once_with(
                "[Security] Created backup key: backup_key_001"
            )

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_create_backup_key_without_oneiric_raises(self):
        """When ONEIRIC_AVAILABLE is False, create_backup_key raises RuntimeError."""
        cfg = SecurityConfig()
        cfg._initialized = True
        cfg._adapter = None
        with pytest.raises(RuntimeError, match="Cannot create backup keys without Oneiric"):
            cfg.create_backup_key()


# =========================================================================
# Tests for get_security_status with Oneiric adapter details
# =========================================================================


class TestSecurityStatusOneiricPath:
    """Test get_security_status() when Oneiric adapter is present."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_status_includes_key_status(self):
        cfg, mock_adapter = _make_oneiric_config()
        status = cfg.get_security_status()
        assert status["initialized"] is True
        assert status["oneiric_available"] is True
        assert "key_status" in status
        assert status["key_status"]["signing_key"]["key_id"] == "test_signing_key"

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_status_includes_days_until_rotation(self):
        cfg, mock_adapter = _make_oneiric_config()
        status = cfg.get_security_status()
        assert "days_until_rotation" in status
        # Should be a date string from the ISO expires_at
        assert status["days_until_rotation"] != "N/A"

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_status_days_until_rotation_na_when_no_expires(self):
        """days_until_rotation is 'N/A' when expires_at is None."""
        cfg, mock_adapter = _make_oneiric_config()
        mock_adapter.get_key_status.return_value = {
            "signing_key": {
                "key_id": "key1",
                "key_length": 64,
                "is_expired": False,
                "expires_at": None,
            },
            "rotation_interval_days": 90,
        }
        status = cfg.get_security_status()
        assert status["days_until_rotation"] == "N/A"

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_status_no_signing_key_no_days_until_rotation(self):
        """days_until_rotation is not set when signing_key is absent."""
        cfg, mock_adapter = _make_oneiric_config()
        mock_adapter.get_key_status.return_value = {}
        status = cfg.get_security_status()
        assert "days_until_rotation" not in status

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_status_adapter_error_returns_error_in_key_status(self):
        cfg, mock_adapter = _make_oneiric_config()
        mock_adapter.get_key_status.side_effect = RuntimeError("status error")
        status = cfg.get_security_status()
        assert status["key_status"]["error"] == "status error"

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_status_includes_config_flags(self):
        cfg, _ = _make_oneiric_config(
            enable_auto_rotation=True,
            enable_strict_mode=True,
            log_security_events=False,
            allow_fallback_keys=False,
            require_key_validation=False,
        )
        status = cfg.get_security_status()
        assert status["auto_rotation_enabled"] is True
        assert status["strict_mode_enabled"] is True
        assert status["log_security_events"] is False
        assert status["allowed_algorithms"] == ["sha256", "sha384", "sha512"]

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", True)
    def test_status_uninitialized(self):
        cfg = SecurityConfig()
        status = cfg.get_security_status()
        assert status["initialized"] is False
        assert status["error"] == "Not initialized"


# =========================================================================
# Tests for _log_security_event edge cases
# =========================================================================


class TestLogSecurityEvent:
    """Test _log_security_event in various scenarios."""

    def test_log_when_logger_is_none(self):
        """No crash when _logger is None."""
        cfg = SecurityConfig(log_security_events=True)
        cfg._logger = None
        # Should not raise
        cfg._log_security_event("test with no logger")

    def test_log_long_message(self):
        cfg = SecurityConfig(log_security_events=True)
        with patch.object(cfg, "_logger") as mock_logger:
            cfg._log_security_event("a" * 500)
            mock_logger.info.assert_called_once()
            assert "[Security]" in mock_logger.info.call_args[0][0]


# =========================================================================
# Tests for context manager protocol
# =========================================================================


class TestContextManager:
    """Test __enter__ and __exit__."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_enter_initializes_fallback(self):
        cfg = SecurityConfig(fallback_enabled=True)
        with cfg as ctx:
            assert ctx is cfg
            assert cfg._initialized is True

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_exit_completes_without_error(self):
        cfg = SecurityConfig(fallback_enabled=True)
        with cfg:
            pass
        # __exit__ should complete without error

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_exit_with_exception(self):
        cfg = SecurityConfig(fallback_enabled=True)
        with pytest.raises(ValueError):
            with cfg:
                raise ValueError("test exception")
        # __exit__ should not suppress the exception

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_enter_already_initialized(self):
        """Context manager on already-initialized config is a no-op."""
        cfg = SecurityConfig(fallback_enabled=True)
        cfg._initialize_fallback()
        first_key = cfg.fallback_signing_key
        with cfg as ctx:
            assert ctx._initialized is True
            # Key should NOT change
            assert ctx.fallback_signing_key == first_key


# =========================================================================
# Tests for config options: allow_fallback_keys, require_key_validation, etc.
# =========================================================================


class TestConfigOptions:
    """Test that configuration options are stored and accessible."""

    def test_allow_fallback_keys_true(self):
        cfg = SecurityConfig(allow_fallback_keys=True)
        assert cfg.allow_fallback_keys is True

    def test_allow_fallback_keys_false(self):
        cfg = SecurityConfig(allow_fallback_keys=False)
        assert cfg.allow_fallback_keys is False

    def test_require_key_validation_true(self):
        cfg = SecurityConfig(require_key_validation=True)
        assert cfg.require_key_validation is True

    def test_require_key_validation_false(self):
        cfg = SecurityConfig(require_key_validation=False)
        assert cfg.require_key_validation is False

    def test_enable_strict_mode_true(self):
        cfg = SecurityConfig(enable_strict_mode=True)
        assert cfg.enable_strict_mode is True

    def test_enable_auto_rotation_true(self):
        cfg = SecurityConfig(enable_auto_rotation=True)
        assert cfg.enable_auto_rotation is True

    def test_enable_auto_rotation_false(self):
        cfg = SecurityConfig(enable_auto_rotation=False)
        assert cfg.enable_auto_rotation is False


# =========================================================================
# Tests for create_signature / verify_signature when ONEIRIC_AVAILABLE=False
# and fallback_enabled=False (unreachable through normal initialize() flow)
# =========================================================================


class TestSignatureOneiricUnavailableFallbackDisabled:
    """Exercise the error branches when Oneiric is off AND fallback is off.

    These paths are normally unreachable because initialize() raises before
    _initialized can be set.  We set _initialized manually to test them.
    """

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_create_signature_raises_without_fallback(self):
        cfg = SecurityConfig(fallback_enabled=False)
        cfg._initialized = True
        with pytest.raises(ValueError, match="Failed to create signature"):
            cfg.create_signature(b"test")

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_create_signature_logs_error_without_fallback(self):
        cfg = SecurityConfig(fallback_enabled=False, log_security_events=True)
        cfg._initialized = True
        with patch.object(cfg, "_logger") as mock_logger:
            with pytest.raises(ValueError):
                cfg.create_signature(b"test")
            mock_logger.error.assert_called_once()

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_verify_signature_returns_false_without_fallback(self):
        cfg = SecurityConfig(fallback_enabled=False)
        cfg._initialized = True
        assert cfg.verify_signature(b"test", b"x" * 32) is False


# =========================================================================
# Tests for _verify_fallback_signature exception path
# =========================================================================


class TestVerifyFallbackSignatureException:
    """Test the exception handler in _verify_fallback_signature."""

    def test_verify_fallback_catches_exception(self):
        """If _create_fallback_signature raises, returns False."""
        cfg = SecurityConfig(fallback_enabled=True, fallback_signing_key=os.urandom(32))
        cfg._initialize_fallback()
        cfg._initialized = True

        # Force _create_fallback_signature to raise
        original = cfg._create_fallback_signature

        def raise_error(msg, algo):
            raise RuntimeError("forced error")

        cfg._create_fallback_signature = raise_error
        result = cfg._verify_fallback_signature(b"test", b"sig", "sha256")
        assert result is False

        # Restore for cleanup
        cfg._create_fallback_signature = original


# =========================================================================
# Tests for initialize_security with Oneiric
# =========================================================================


class TestInitializeSecurityExtended:
    """Extended tests for the initialize_security global function."""

    def setup_method(self):
        import dhara.config.security as mod
        self._orig_global = mod._global_config
        mod._global_config = None

    def teardown_method(self):
        import dhara.config.security as mod
        mod._global_config = self._orig_global

    def test_initialize_with_custom_config_options(self):
        cfg = initialize_security(
            secret_prefix="custom/prefix",
            rotation_interval_days=45,
            allow_fallback_keys=False,
            enable_strict_mode=True,
            enable_auto_rotation=False,
            fallback_enabled=True,
        )
        assert cfg.secret_prefix == "custom/prefix"
        assert cfg.rotation_interval_days == 45
        assert cfg.allow_fallback_keys is False
        assert cfg.enable_strict_mode is True
        assert cfg.enable_auto_rotation is False

    def test_get_after_initialize_returns_same_instance(self):
        cfg1 = initialize_security(fallback_enabled=True)
        cfg2 = get_security_config()
        assert cfg1 is cfg2

    def test_multiple_initialize_calls_replace_global(self):
        cfg1 = initialize_security(fallback_enabled=True)
        cfg2 = initialize_security(
            secret_prefix="new/prefix", fallback_enabled=True
        )
        assert get_security_config() is cfg2
        assert get_security_config() is not cfg1


# =========================================================================
# Tests for get_security_status with fallback mode
# =========================================================================


class TestSecurityStatusFallbackMode:
    """Test get_security_status() in fallback mode."""

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_status_fallback_mode_fields(self):
        cfg = SecurityConfig(fallback_enabled=True)
        cfg._initialize_fallback()
        cfg._initialized = True
        status = cfg.get_security_status()
        assert status["initialized"] is True
        assert status["oneiric_available"] is False
        assert status["fallback_mode"] is True
        assert status["secret_prefix"] == "dhara/hmac"
        assert status["rotation_interval_days"] == 90
        assert status["key_length_minimum_bytes"] == 32

    @patch("dhara.config.security.ONEIRIC_AVAILABLE", False)
    def test_status_uninitialized_in_fallback(self):
        cfg = SecurityConfig(fallback_enabled=True)
        status = cfg.get_security_status()
        assert status["initialized"] is False
        assert status["error"] == "Not initialized"

"""Tests for dhara.security.oneiric_secrets.

Covers helper functions, SecretKey dataclass, OneiricSecretsAdapter class,
and module-level functions (singleton, HMAC creation/verification, init).

The module does ``from oneiric import secrets`` at import time.  When oneiric
is installed but ``oneiric.secrets`` is missing (as in this environment),
the module-level ``secrets`` ends up as ``None`` and ``ONEIRIC_AVAILABLE`` is
``False``.  To exercise the full adapter code path we install a fake
``oneiric.secrets`` into ``sys.modules`` *before* the first import of the
module under test, then remove it afterwards to avoid polluting other tests.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import importlib
import secrets as stdlib_secrets
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Custom exception matching oneiric.secrets.SecretNotFoundError shape
# ---------------------------------------------------------------------------

_SecretNotFoundError = type("SecretNotFoundError", (Exception,), {})


# ---------------------------------------------------------------------------
# Mock Oneiric secrets backend
# ---------------------------------------------------------------------------


def _make_mock_oneiric_secrets(
    *,
    existing_keys: dict[str, bytes] | None = None,
    existing_meta: dict[str, str] | None = None,
    list_prefix_result: list[str] | None = None,
) -> MagicMock:
    """Return a MagicMock that behaves like ``oneiric.secrets``."""
    store: dict[str, bytes] = dict(existing_keys or {})
    meta: dict[str, str] = dict(existing_meta or {})

    mock = MagicMock()

    def _get(name: str, default: str = "") -> bytes | str:
        if name in store:
            return store[name]
        if name in meta:
            return meta[name]
        if default:
            return default
        raise _SecretNotFoundError(f"Secret not found: {name}")

    mock.get = MagicMock(side_effect=_get)
    mock.set = MagicMock(side_effect=lambda k, v: store.update({k: v}))
    mock.SecretNotFoundError = _SecretNotFoundError
    mock.list = MagicMock(return_value=list_prefix_result or [])
    # token_bytes delegates to stdlib (used by SecretKey.rotate)
    mock.token_bytes = stdlib_secrets.token_bytes
    # compare_digest delegates to stdlib (used by verify_hmac_signature)
    mock.compare_digest = stdlib_secrets.compare_digest
    return mock


# ---------------------------------------------------------------------------
# Module import helper -- installs fake oneiric.secrets into sys.modules
# ---------------------------------------------------------------------------


def _install_fake_oneiric_secrets(
    mock_secrets: MagicMock | None = None,
) -> MagicMock:
    """Install a fake ``oneiric.secrets`` into sys.modules and return it.

    Call ``_uninstall_fake_oneiric_secrets()`` in a finally-block to clean up.
    """
    if mock_secrets is None:
        mock_secrets = _make_mock_oneiric_secrets()

    # Use a real types.ModuleType as the fake oneiric package so that
    # ``from oneiric import secrets`` correctly retrieves the attribute.
    import types

    fake_oneiric = types.ModuleType("oneiric")
    fake_oneiric.__path__ = []  # pretend it is a package
    fake_oneiric.secrets = mock_secrets

    # Save originals so we can restore
    _orig = sys.modules.get("oneiric")
    _orig_sub = sys.modules.get("oneiric.secrets")

    sys.modules["oneiric"] = fake_oneiric
    sys.modules["oneiric.secrets"] = mock_secrets

    # Remove cached dhara.security.oneiric_secrets so the next import
    # re-executes the module-level try/except and picks up the mock.
    for key in list(sys.modules):
        if key == "dhara.security.oneiric_secrets" or key.startswith(
            "dhara.security.oneiric_secrets."
        ):
            del sys.modules[key]

    mock_secrets._saved_orig = _orig
    mock_secrets._saved_orig_sub = _orig_sub
    return mock_secrets


def _uninstall_fake_oneiric_secrets(mock_secrets: MagicMock) -> None:
    """Restore sys.modules to its original state."""
    _orig = getattr(mock_secrets, "_saved_orig", None)
    _orig_sub = getattr(mock_secrets, "_saved_orig_sub", None)

    if _orig is not None:
        sys.modules["oneiric"] = _orig
    elif "oneiric" in sys.modules:
        del sys.modules["oneiric"]

    if _orig_sub is not None:
        sys.modules["oneiric.secrets"] = _orig_sub
    elif "oneiric.secrets" in sys.modules:
        del sys.modules["oneiric.secrets"]

    # Remove cached module so the next test gets a fresh import
    for key in list(sys.modules):
        if key == "dhara.security.oneiric_secrets" or key.startswith(
            "dhara.security.oneiric_secrets."
        ):
            del sys.modules[key]


def _import_mod():
    """Import the module (assumes fake oneiric.secrets is installed)."""
    import dhara.security.oneiric_secrets as mod

    return mod


def _fresh_adapter(
    *,
    secret_prefix: str = "test/hmac",
    rotation_interval: int = 90,
    mock_secrets: MagicMock | None = None,
) -> tuple:
    """Build a OneiricSecretsAdapter with mocked Oneiric secrets.

    Returns ``(module, adapter, mock_secrets)``.

    The caller is responsible for calling
    ``_uninstall_fake_oneiric_secrets(mock_secrets)`` when done.
    """
    mock_secrets = _install_fake_oneiric_secrets(mock_secrets)
    mod = _import_mod()
    assert mod.ONEIRIC_AVAILABLE is True
    adapter = mod.OneiricSecretsAdapter(
        secret_prefix=secret_prefix, rotation_interval=rotation_interval
    )
    return mod, adapter, mock_secrets


# ===========================================================================
# 1. TestHelperFunctions
# ===========================================================================


class TestHelperFunctions:
    """Tests for the module-level _utcnow() and _as_utc() helpers."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_utcnow_returns_timezone_aware_datetime(self):
        result = self.mod._utcnow()
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_utcnow_is_approximately_now(self):
        before = datetime.now(UTC)
        result = self.mod._utcnow()
        after = datetime.now(UTC)
        assert before <= result <= after

    def test_as_utc_with_naive_datetime(self):
        naive = datetime(2025, 6, 15, 12, 0, 0)
        result = self.mod._as_utc(naive)
        assert result.tzinfo is not None
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15

    def test_as_utc_with_aware_datetime(self):
        from datetime import timezone, timedelta as td

        aware = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone(td(hours=5)))
        result = self.mod._as_utc(aware)
        assert result.tzinfo is not None
        assert result.hour == 7  # 12:00 +05:00 -> 07:00 UTC

    def test_as_utc_already_utc_unchanged(self):
        utc_dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        result = self.mod._as_utc(utc_dt)
        assert result == utc_dt


# ===========================================================================
# 2. TestSecretKey
# ===========================================================================


class TestSecretKey:
    """Tests for the SecretKey dataclass."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def _make_key(self, **overrides) -> "SecretKey":
        defaults = dict(
            key_id="test_key",
            key_material=b"x" * 32,
            created_at=datetime.now(UTC) - timedelta(days=10),
            expires_at=datetime.now(UTC) + timedelta(days=80),
            is_active=True,
            rotation_interval=timedelta(days=90),
        )
        defaults.update(overrides)
        return self.mod.SecretKey(**defaults)

    def test_basic_construction(self):
        key = self._make_key()
        assert key.key_id == "test_key"
        assert key.key_material == b"x" * 32
        assert key.is_active is True
        assert key.rotation_interval == timedelta(days=90)

    def test_is_expired_false_when_no_expires_at(self):
        key = self._make_key(expires_at=None)
        assert key.is_expired is False

    def test_is_expired_false_when_in_future(self):
        key = self._make_key(expires_at=datetime.now(UTC) + timedelta(days=80))
        assert key.is_expired is False

    def test_is_expired_true_when_in_past(self):
        key = self._make_key(expires_at=datetime.now(UTC) - timedelta(days=1))
        assert key.is_expired is True

    def test_age_returns_timedelta(self):
        key = self._make_key(created_at=datetime.now(UTC) - timedelta(days=5))
        age = key.age
        assert isinstance(age, timedelta)
        assert abs(age.days - 5) <= 1

    def test_age_with_naive_created_at(self):
        key = self._make_key(created_at=datetime(2025, 1, 1))
        age = key.age
        assert isinstance(age, timedelta)

    def test_rotate_creates_new_key(self):
        key = self._make_key()
        new_key = key.rotate()
        assert new_key.key_id.startswith("test_key_rotated_")
        assert new_key.key_material != key.key_material
        assert len(new_key.key_material) == 32
        assert new_key.created_at > key.created_at
        assert new_key.is_active is True

    def test_rotate_sets_expires_at(self):
        key = self._make_key()
        new_key = key.rotate()
        assert new_key.expires_at is not None
        assert new_key.expires_at > new_key.created_at

    def test_rotate_preserves_rotation_interval(self):
        key = self._make_key(rotation_interval=timedelta(days=60))
        new_key = key.rotate()
        assert new_key.rotation_interval == timedelta(days=60)

    def test_fallback_key_default_none(self):
        key = self._make_key()
        assert key.fallback_key is None

    def test_fallback_key_can_be_set(self):
        key1 = self._make_key(key_id="primary")
        key2 = self._make_key(key_id="backup")
        key2.fallback_key = key1
        assert key2.fallback_key is key1
        assert key2.fallback_key.key_id == "primary"


# ===========================================================================
# 3. TestOneiricSecretsAdapterInit
# ===========================================================================


class TestOneiricSecretsAdapterInit:
    """Tests for OneiricSecretsAdapter initialization."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def _build(self, **kw) -> tuple:
        adapter = self.mod.OneiricSecretsAdapter(**kw)
        return adapter, self.mock

    def test_init_creates_adapter_successfully(self):
        adapter, _ = self._build()
        assert adapter.secret_prefix == "durus/hmac"
        assert adapter.rotation_interval == timedelta(days=90)
        assert adapter._initialized is True

    def test_init_strips_trailing_slash_from_prefix(self):
        adapter, _ = self._build(secret_prefix="test/hmac/")
        assert adapter.secret_prefix == "test/hmac"

    def test_init_creates_primary_signing_key(self):
        adapter, _ = self._build(secret_prefix="test/hmac")
        assert "signing" in adapter._active_keys
        key = adapter._active_keys["signing"]
        assert len(key.key_material) == 32

    def test_init_calls_secrets_get_for_existing_key(self):
        mock = _make_mock_oneiric_secrets(
            existing_keys={"test/hmac/signing_key": b"y" * 32},
            existing_meta={
                "test/hmac/signing_key_created": "2025-01-01T00:00:00+00:00",
                "test/hmac/signing_key_expires": "2025-06-01T00:00:00+00:00",
            },
        )
        _uninstall_fake_oneiric_secrets(self.mock)
        self.mock = _install_fake_oneiric_secrets(mock)
        # Need to reimport after changing sys.modules
        for key in list(sys.modules):
            if key == "dhara.security.oneiric_secrets" or key.startswith(
                "dhara.security.oneiric_secrets."
            ):
                del sys.modules[key]
        self.mod = _import_mod()
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        mock.get.assert_called()

    def test_init_creates_new_key_when_not_found(self):
        adapter, mock = self._build(secret_prefix="test/hmac")
        assert mock.set.called

    def test_init_stores_key_metadata(self):
        adapter, mock = self._build(secret_prefix="test/hmac")
        set_calls = {call[0][0] for call in mock.set.call_args_list}
        assert any("signing_key_created" in s for s in set_calls)
        assert any("signing_key_expires" in s for s in set_calls)

    def test_init_raises_when_oneiric_not_available(self):
        with patch.object(self.mod, "ONEIRIC_AVAILABLE", False):
            with pytest.raises(RuntimeError, match="Oneiric secrets library"):
                self.mod.OneiricSecretsAdapter()

    def test_init_rotates_expired_key(self):
        expired_time = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        mock = _make_mock_oneiric_secrets(
            existing_keys={"test/hmac/signing_key": b"w" * 32},
            existing_meta={
                "test/hmac/signing_key_created": "2024-01-01T00:00:00+00:00",
                "test/hmac/signing_key_expires": expired_time,
            },
        )
        _uninstall_fake_oneiric_secrets(self.mock)
        self.mock = _install_fake_oneiric_secrets(mock)
        for key in list(sys.modules):
            if key == "dhara.security.oneiric_secrets" or key.startswith(
                "dhara.security.oneiric_secrets."
            ):
                del sys.modules[key]
        self.mod = _import_mod()
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        assert mock.set.called

    def test_rotation_interval_custom_value(self):
        adapter, _ = self._build(rotation_interval=30)
        assert adapter.rotation_interval == timedelta(days=30)


# ===========================================================================
# 4. TestOneiricSecretsAdapterGetSigningKey
# ===========================================================================


class TestOneiricSecretsAdapterGetSigningKey:
    """Tests for OneiricSecretsAdapter.get_signing_key()."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_get_signing_key_returns_tuple(self):
        result = self.adapter.get_signing_key()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_get_signing_key_returns_bytes_and_string(self):
        key_material, key_id = self.adapter.get_signing_key()
        assert isinstance(key_material, bytes)
        assert isinstance(key_id, str)

    def test_get_signing_key_returns_correct_length(self):
        key_material, _ = self.adapter.get_signing_key()
        assert len(key_material) == 32

    def test_get_signing_key_sha256(self):
        key_material, _ = self.adapter.get_signing_key("sha256")
        assert isinstance(key_material, bytes)

    def test_get_signing_key_sha384(self):
        key_material, _ = self.adapter.get_signing_key("sha384")
        assert isinstance(key_material, bytes)

    def test_get_signing_key_sha512(self):
        key_material, _ = self.adapter.get_signing_key("sha512")
        assert isinstance(key_material, bytes)

    def test_get_signing_key_unsupported_algorithm_raises(self):
        with pytest.raises(ValueError, match="Unsupported algorithm"):
            self.adapter.get_signing_key("nonexistent_algo")

    def test_get_signing_key_default_algorithm(self):
        key_material, key_id = self.adapter.get_signing_key()
        assert key_id == "test/hmac_signing_key"


# ===========================================================================
# 5. TestOneiricSecretsAdapterCreateBackupKey
# ===========================================================================


class TestOneiricSecretsAdapterCreateBackupKey:
    """Tests for OneiricSecretsAdapter.create_backup_key()."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_create_backup_key_returns_key_id(self):
        key_id = self.adapter.create_backup_key()
        assert isinstance(key_id, str)

    def test_create_backup_key_has_expected_prefix(self):
        key_id = self.adapter.create_backup_key()
        assert "backup_signing_key" in key_id

    def test_create_backup_key_calls_secrets_set(self):
        initial_call_count = self.mock.set.call_count
        self.adapter.create_backup_key()
        assert self.mock.set.call_count > initial_call_count


# ===========================================================================
# 6. TestOneiricSecretsAdapterRotateAllKeys
# ===========================================================================


class TestOneiricSecretsAdapterRotateAllKeys:
    """Tests for OneiricSecretsAdapter.rotate_all_keys()."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_rotate_all_keys_returns_dict(self):
        result = self.adapter.rotate_all_keys()
        assert isinstance(result, dict)

    def test_rotate_all_keys_contains_signing(self):
        result = self.adapter.rotate_all_keys()
        assert "signing" in result

    def test_rotate_all_keys_new_id_differs(self):
        old_id = self.adapter._active_keys["signing"].key_id
        result = self.adapter.rotate_all_keys()
        assert result["signing"] != old_id

    def test_rotate_all_keys_old_key_moved_to_backup(self):
        old_id = self.adapter._active_keys["signing"].key_id
        self.adapter.rotate_all_keys()
        assert old_id in self.adapter._keys

    def test_rotate_all_keys_new_key_is_active(self):
        self.adapter.rotate_all_keys()
        new_key = self.adapter._active_keys["signing"]
        assert new_key.is_active is True


# ===========================================================================
# 7. TestOneiricSecretsAdapterCleanupExpiredKeys
# ===========================================================================


class TestOneiricSecretsAdapterCleanupExpiredKeys:
    """Tests for OneiricSecretsAdapter.cleanup_expired_keys()."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_cleanup_returns_int(self):
        count = self.adapter.cleanup_expired_keys()
        assert isinstance(count, int)

    def test_cleanup_removes_expired_keys(self):
        expired_key = self.mod.SecretKey(
            key_id="expired_test_key",
            key_material=b"e" * 32,
            created_at=datetime.now(UTC) - timedelta(days=200),
            expires_at=datetime.now(UTC) - timedelta(days=10),
            is_active=False,
        )
        self.adapter._keys[expired_key.key_id] = expired_key
        count = self.adapter.cleanup_expired_keys()
        assert count == 1
        assert "expired_test_key" not in self.adapter._keys

    def test_cleanup_preserves_non_expired_keys(self):
        valid_key = self.mod.SecretKey(
            key_id="valid_test_key",
            key_material=b"v" * 32,
            created_at=datetime.now(UTC) - timedelta(days=10),
            expires_at=datetime.now(UTC) + timedelta(days=80),
            is_active=False,
        )
        self.adapter._keys[valid_key.key_id] = valid_key
        count = self.adapter.cleanup_expired_keys()
        assert count == 0
        assert "valid_test_key" in self.adapter._keys

    def test_cleanup_no_expired_returns_zero(self):
        count = self.adapter.cleanup_expired_keys()
        assert count == 0

    def test_cleanup_multiple_expired_keys(self):
        for i in range(3):
            expired_key = self.mod.SecretKey(
                key_id=f"expired_key_{i}",
                key_material=b"e" * 32,
                created_at=datetime.now(UTC) - timedelta(days=200),
                expires_at=datetime.now(UTC) - timedelta(days=1),
                is_active=False,
            )
            self.adapter._keys[expired_key.key_id] = expired_key
        count = self.adapter.cleanup_expired_keys()
        assert count == 3

    def test_cleanup_key_with_no_expires_at_not_removed(self):
        key_no_expiry = self.mod.SecretKey(
            key_id="no_expiry_key",
            key_material=b"n" * 32,
            created_at=datetime.now(UTC) - timedelta(days=200),
            expires_at=None,
            is_active=False,
        )
        self.adapter._keys[key_no_expiry.key_id] = key_no_expiry
        count = self.adapter.cleanup_expired_keys()
        assert count == 0
        assert "no_expiry_key" in self.adapter._keys


# ===========================================================================
# 8. TestOneiricSecretsAdapterGetKeyStatus
# ===========================================================================


class TestOneiricSecretsAdapterGetKeyStatus:
    """Tests for OneiricSecretsAdapter.get_key_status()."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_get_key_status_returns_dict(self):
        status = self.adapter.get_key_status()
        assert isinstance(status, dict)

    def test_get_key_status_has_expected_keys(self):
        status = self.adapter.get_key_status()
        expected_keys = {
            "total_keys",
            "active_keys",
            "backup_keys",
            "rotation_interval_days",
            "initialized",
            "secret_prefix",
        }
        assert expected_keys.issubset(set(status.keys()))

    def test_get_key_status_total_keys(self):
        status = self.adapter.get_key_status()
        expected = len(self.adapter._keys) + len(self.adapter._active_keys)
        assert status["total_keys"] == expected

    def test_get_key_status_active_keys(self):
        status = self.adapter.get_key_status()
        assert status["active_keys"] == len(self.adapter._active_keys)

    def test_get_key_status_rotation_interval(self):
        adapter = self.mod.OneiricSecretsAdapter(
            secret_prefix="test/hmac", rotation_interval=45
        )
        status = adapter.get_key_status()
        assert status["rotation_interval_days"] == 45

    def test_get_key_status_initialized_true(self):
        status = self.adapter.get_key_status()
        assert status["initialized"] is True

    def test_get_key_status_secret_prefix(self):
        status = self.adapter.get_key_status()
        assert status["secret_prefix"] == "test/hmac"

    def test_get_key_status_includes_signing_key_details(self):
        status = self.adapter.get_key_status()
        assert "signing_key" in status
        signing = status["signing_key"]
        for field in (
            "key_id",
            "created_at",
            "expires_at",
            "age_days",
            "is_expired",
            "is_active",
            "key_length",
        ):
            assert field in signing

    def test_get_key_status_signing_key_length(self):
        status = self.adapter.get_key_status()
        assert status["signing_key"]["key_length"] == 32


# ===========================================================================
# 9. TestOneiricSecretsAdapterValidateKeys
# ===========================================================================


class TestOneiricSecretsAdapterValidateKeys:
    """Tests for OneiricSecretsAdapter._validate_keys()."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_validate_keys_passes_for_valid_keys(self):
        self.adapter._validate_keys()

    def test_validate_keys_raises_for_short_key(self):
        self.adapter._active_keys["signing"].key_material = b"short"
        with pytest.raises(ValueError, match="too short"):
            self.adapter._validate_keys()

    def test_validate_keys_raises_for_expired_key(self):
        self.adapter._active_keys["signing"].expires_at = datetime.now(
            UTC
        ) - timedelta(days=1)
        with pytest.raises(ValueError, match="has expired"):
            self.adapter._validate_keys()

    def test_validate_keys_raises_when_no_signing_key(self):
        self.adapter._active_keys.clear()
        with pytest.raises(RuntimeError, match="No active signing key"):
            self.adapter._validate_keys()

    def test_validate_keys_32_bytes_minimum_boundary(self):
        """31 bytes should fail, 32 bytes should pass."""
        self.adapter._active_keys["signing"].key_material = b"x" * 31
        with pytest.raises(ValueError, match="too short"):
            self.adapter._validate_keys()

        self.adapter._active_keys["signing"].key_material = b"x" * 32
        self.adapter._active_keys["signing"].expires_at = datetime.now(
            UTC
        ) + timedelta(days=90)
        self.adapter._validate_keys()


# ===========================================================================
# 10. TestCreateHmacSignature
# ===========================================================================


class TestCreateHmacSignature:
    """Tests for the module-level create_hmac_signature() function."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        # Make the global adapter available
        self.mod._adapter = self.adapter

    def teardown_method(self):
        self.mod._adapter = None
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_create_hmac_returns_bytes(self):
        sig = self.mod.create_hmac_signature(b"test message")
        assert isinstance(sig, bytes)

    def test_create_hmac_sha256_length(self):
        sig = self.mod.create_hmac_signature(b"test message", "sha256")
        assert len(sig) == 32

    def test_create_hmac_sha384_length(self):
        sig = self.mod.create_hmac_signature(b"test message", "sha384")
        assert len(sig) == 48

    def test_create_hmac_sha512_length(self):
        sig = self.mod.create_hmac_signature(b"test message", "sha512")
        assert len(sig) == 64

    def test_create_hmac_deterministic(self):
        sig1 = self.mod.create_hmac_signature(b"hello world")
        sig2 = self.mod.create_hmac_signature(b"hello world")
        assert sig1 == sig2

    def test_create_hmac_different_messages_differ(self):
        sig1 = self.mod.create_hmac_signature(b"message one")
        sig2 = self.mod.create_hmac_signature(b"message two")
        assert sig1 != sig2

    def test_create_hmac_raises_on_non_bytes_message(self):
        with pytest.raises(ValueError, match="Message must be bytes"):
            self.mod.create_hmac_signature("not bytes")

    def test_create_hmac_empty_message(self):
        sig = self.mod.create_hmac_signature(b"")
        assert isinstance(sig, bytes)
        assert len(sig) == 32

    def test_create_hmac_matches_stdlib_hmac(self):
        message = b"verify against stdlib"
        sig = self.mod.create_hmac_signature(message, "sha256")
        key_material, _ = self.adapter.get_signing_key("sha256")
        expected = hmac_mod.new(key_material, message, hashlib.sha256).digest()
        assert sig == expected


# ===========================================================================
# 11. TestVerifyHmacSignature
# ===========================================================================


class TestVerifyHmacSignature:
    """Tests for the module-level verify_hmac_signature() function."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        self.mod._adapter = self.adapter

    def teardown_method(self):
        self.mod._adapter = None
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_verify_valid_signature(self):
        sig = self.mod.create_hmac_signature(b"test message")
        result = self.mod.verify_hmac_signature(b"test message", sig)
        assert result is True

    def test_verify_invalid_signature(self):
        sig = self.mod.create_hmac_signature(b"test message")
        result = self.mod.verify_hmac_signature(b"wrong message", sig)
        assert result is False

    def test_verify_tampered_signature(self):
        sig = bytearray(self.mod.create_hmac_signature(b"test message"))
        sig[0] = (sig[0] + 1) % 256
        result = self.mod.verify_hmac_signature(b"test message", bytes(sig))
        assert result is False

    def test_verify_wrong_length_signature(self):
        result = self.mod.verify_hmac_signature(b"test message", b"tooshort")
        assert result is False

    def test_verify_empty_signature(self):
        result = self.mod.verify_hmac_signature(b"test message", b"")
        assert result is False

    def test_verify_different_algorithm(self):
        sig = self.mod.create_hmac_signature(b"test", "sha512")
        result = self.mod.verify_hmac_signature(b"test", sig, "sha512")
        assert result is True

    def test_verify_returns_false_on_exception(self):
        with patch.object(
            self.mod,
            "create_hmac_signature",
            side_effect=RuntimeError("boom"),
        ):
            result = self.mod.verify_hmac_signature(b"msg", b"sig")
        assert result is False


# ===========================================================================
# 12. TestGetSecretsAdapter (singleton)
# ===========================================================================


class TestGetSecretsAdapter:
    """Tests for the module-level get_secrets_adapter() singleton."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.orig_adapter = self.mod._adapter

    def teardown_method(self):
        self.mod._adapter = self.orig_adapter
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_get_secrets_adapter_returns_adapter(self):
        self.mod._adapter = None
        adapter = self.mod.get_secrets_adapter()
        assert isinstance(adapter, self.mod.OneiricSecretsAdapter)

    def test_get_secrets_adapter_is_singleton(self):
        self.mod._adapter = None
        adapter1 = self.mod.get_secrets_adapter()
        adapter2 = self.mod.get_secrets_adapter()
        assert adapter1 is adapter2

    def test_get_secrets_adapter_custom_params(self):
        self.mod._adapter = None
        adapter = self.mod.get_secrets_adapter(
            secret_prefix="custom/prefix", rotation_interval=30
        )
        assert adapter.secret_prefix == "custom/prefix"
        assert adapter.rotation_interval == timedelta(days=30)

    def test_get_secrets_adapter_default_params(self):
        self.mod._adapter = None
        adapter = self.mod.get_secrets_adapter()
        assert adapter.secret_prefix == "durus/hmac"
        assert adapter.rotation_interval == timedelta(days=90)


# ===========================================================================
# 13. TestInitializeSecrets
# ===========================================================================


class TestInitializeSecrets:
    """Tests for the module-level initialize_secrets() function."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.orig_adapter = self.mod._adapter

    def teardown_method(self):
        self.mod._adapter = self.orig_adapter
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_initialize_secrets_sets_global_adapter(self):
        self.mod.initialize_secrets(secret_prefix="test/hmac")
        assert self.mod._adapter is not None

    def test_initialize_secrets_returns_none(self):
        result = self.mod.initialize_secrets(secret_prefix="test/hmac")
        assert result is None

    def test_initialize_secrets_custom_params(self):
        self.mod.initialize_secrets(
            secret_prefix="init/test", rotation_interval=60
        )
        assert self.mod._adapter.secret_prefix == "init/test"
        assert self.mod._adapter.rotation_interval == timedelta(days=60)

    def test_initialize_secrets_overwrites_previous(self):
        self.mod.initialize_secrets(secret_prefix="first")
        first_adapter = self.mod._adapter
        self.mod.initialize_secrets(secret_prefix="second")
        second_adapter = self.mod._adapter
        assert first_adapter is not second_adapter
        assert second_adapter.secret_prefix == "second"


# ===========================================================================
# 14. TestOneiricSecretsAdapterAutoRotate
# ===========================================================================


class TestOneiricSecretsAdapterAutoRotate:
    """Tests for auto-rotation logic."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_auto_rotate_skips_when_not_initialized(self):
        self.adapter._initialized = False
        self.adapter._auto_rotate_keys()
        assert "signing" in self.adapter._active_keys

    def test_auto_rotate_old_key(self):
        old_key = self.adapter._active_keys["signing"]
        old_key.created_at = datetime.now(UTC) - timedelta(days=200)
        self.adapter._auto_rotate_keys()
        new_key = self.adapter._active_keys["signing"]
        assert new_key.key_id != old_key.key_id

    def test_auto_rotate_preserves_recent_key(self):
        old_key = self.adapter._active_keys["signing"]
        old_key.created_at = datetime.now(UTC) - timedelta(days=1)
        self.adapter._auto_rotate_keys()
        assert self.adapter._active_keys["signing"].key_id == old_key.key_id


# ===========================================================================
# 15. TestOneiricSecretsAdapterGetOrCreateKey
# ===========================================================================


class TestOneiricSecretsAdapterGetOrCreateKey:
    """Tests for the _get_or_create_key internal method."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def _reinstall_with_get_side_effect(self, side_effect_fn):
        """Replace the mock's get side_effect and reinstall."""
        self.mock.get.side_effect = side_effect_fn
        # Force module reimport so it picks up the modified mock
        for key in list(sys.modules):
            if key == "dhara.security.oneiric_secrets" or key.startswith(
                "dhara.security.oneiric_secrets."
            ):
                del sys.modules[key]
        self.mod = _import_mod()

    def test_get_or_create_existing_key(self):
        """When a key already exists in Oneiric, it should be loaded."""
        existing_material = b"existing_key_material_32_bytes_ok"
        # Use a recent created_at so the key is NOT rotated
        recent_created = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        recent_expires = (datetime.now(UTC) + timedelta(days=80)).isoformat()

        def _get_with_existing(name, default=""):
            if name == "test/hmac/signing_key":
                return b"z" * 32
            elif name == "test/hmac/signing_key_created":
                return recent_created
            elif name == "test/hmac/signing_key_expires":
                return recent_expires
            elif name == "test/hmac/custom_key":
                return existing_material
            elif name == "test/hmac/custom_key_created":
                return recent_created
            elif name == "test/hmac/custom_key_expires":
                return recent_expires
            elif default:
                return default
            raise _SecretNotFoundError(f"Not found: {name}")

        self._reinstall_with_get_side_effect(_get_with_existing)
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        key = adapter._get_or_create_key("custom_key")
        assert key.key_material == existing_material
        assert key.key_id == "test/hmac_custom_key"

    def test_get_or_create_new_key(self):
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        key = adapter._get_or_create_key("brand_new_key")
        assert key.key_id == "test/hmac_brand_new_key"
        assert len(key.key_material) == 32
        # Should have stored in Oneiric
        set_calls = {call[0][0] for call in self.mock.set.call_args_list}
        assert "test/hmac/brand_new_key" in set_calls

    def test_get_or_create_key_without_metadata(self):
        """Key exists but no _created/_expires metadata uses defaults."""
        recent_created = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        recent_expires = (datetime.now(UTC) + timedelta(days=80)).isoformat()

        def _get_no_meta(name, default=""):
            if name == "test/hmac/signing_key":
                return b"z" * 32
            elif name == "test/hmac/signing_key_created":
                return recent_created
            elif name == "test/hmac/signing_key_expires":
                return recent_expires
            elif name == "test/hmac/no_meta_key":
                return b"x" * 32
            elif name in (
                "test/hmac/no_meta_key_created",
                "test/hmac/no_meta_key_expires",
            ):
                # Return empty string for missing metadata (default arg is "")
                return ""
            elif default is not None:
                return default
            raise _SecretNotFoundError(f"Not found: {name}")

        self._reinstall_with_get_side_effect(_get_no_meta)
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        key = adapter._get_or_create_key("no_meta_key")
        assert key.key_material == b"x" * 32
        assert key.expires_at is not None


# ===========================================================================
# 16. TestOneiricSecretsAdapterRotateKey
# ===========================================================================


class TestOneiricSecretsAdapterRotateKey:
    """Tests for the _rotate_key internal method."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()
        self.adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_rotate_key_creates_new_key(self):
        old_key = self.mod.SecretKey(
            key_id="old_key",
            key_material=b"o" * 32,
            created_at=datetime.now(UTC) - timedelta(days=50),
            expires_at=datetime.now(UTC) + timedelta(days=40),
            rotation_interval=timedelta(days=90),
        )
        new_key = self.adapter._rotate_key(old_key, "test/hmac/old_key")
        assert new_key.key_id.startswith("old_key_rotated_")
        assert new_key.key_material != old_key.key_material
        assert old_key.is_active is False

    def test_rotate_key_stores_in_oneiric(self):
        old_key = self.mod.SecretKey(
            key_id="store_test",
            key_material=b"s" * 32,
            created_at=datetime.now(UTC) - timedelta(days=50),
            expires_at=datetime.now(UTC) + timedelta(days=40),
            rotation_interval=timedelta(days=90),
        )
        self.adapter._rotate_key(old_key, "test/hmac/store_test")
        set_calls = {call[0][0] for call in self.mock.set.call_args_list}
        assert "test/hmac/store_test" in set_calls
        assert "test/hmac/store_test_created" in set_calls
        assert "test/hmac/store_test_expires" in set_calls


# ===========================================================================
# 17. TestOneiricSecretsAdapterGetBackupKeys
# ===========================================================================


class TestOneiricSecretsAdapterGetBackupKeys:
    """Tests for the _get_backup_keys internal method."""

    def _build_with_backup(
        self, *, existing_keys=None, existing_meta=None, list_result=None
    ):
        mock = _make_mock_oneiric_secrets(
            existing_keys=existing_keys,
            existing_meta=existing_meta,
            list_prefix_result=list_result,
        )
        _uninstall_fake_oneiric_secrets(self.mock)
        self.mock = _install_fake_oneiric_secrets(mock)
        for key in list(sys.modules):
            if key == "dhara.security.oneiric_secrets" or key.startswith(
                "dhara.security.oneiric_secrets."
            ):
                del sys.modules[key]
        self.mod = _import_mod()
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        return adapter, mock

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_get_backup_keys_empty_list(self):
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        backups = adapter._get_backup_keys()
        assert backups == []

    def test_get_backup_keys_filters_non_rotated(self):
        adapter, mock = self._build_with_backup(
            existing_keys={
                "test/hmac/signing_key": b"x" * 32,
                "test/hmac/some_other_key": b"y" * 32,
            },
            existing_meta={
                "test/hmac/signing_key_created": "2025-01-01T00:00:00+00:00",
                "test/hmac/signing_key_expires": "2025-06-01T00:00:00+00:00",
            },
            list_result=[
                "test/hmac/signing_key",
                "test/hmac/some_other_key",
            ],
        )
        backups = adapter._get_backup_keys()
        assert len(backups) == 0

    def test_get_backup_keys_returns_rotated_keys(self):
        adapter, mock = self._build_with_backup(
            existing_keys={
                "test/hmac/signing_key": b"x" * 32,
                "test/hmac/signing_key_rotated_123": b"r" * 32,
            },
            existing_meta={
                "test/hmac/signing_key_created": "2025-01-01T00:00:00+00:00",
                "test/hmac/signing_key_expires": "2025-06-01T00:00:00+00:00",
                "test/hmac/signing_key_rotated_123_created": "2025-02-01T00:00:00+00:00",
                "test/hmac/signing_key_rotated_123_expires": "2025-07-01T00:00:00+00:00",
            },
            list_result=[
                "test/hmac/signing_key",
                "test/hmac/signing_key_rotated_123",
            ],
        )
        backups = adapter._get_backup_keys()
        assert len(backups) >= 1

    def test_get_backup_keys_handles_list_exception(self):
        mock = _make_mock_oneiric_secrets()
        mock.list.side_effect = RuntimeError("connection failed")
        adapter, _ = self._build_with_backup(list_result=[])
        # Replace the list side_effect on the live mock
        self.mock.list.side_effect = RuntimeError("connection failed")
        backups = adapter._get_backup_keys()
        assert backups == []


# ===========================================================================
# 18. Additional edge-case tests for remaining coverage
# ===========================================================================


class TestEdgeCases:
    """Additional tests covering remaining code paths."""

    def setup_method(self):
        self.mock = _install_fake_oneiric_secrets()
        self.mod = _import_mod()

    def teardown_method(self):
        _uninstall_fake_oneiric_secrets(self.mock)

    def test_get_signing_key_raises_when_no_active_key(self):
        """Covers line 271: no active signing key in get_signing_key."""
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        adapter._active_keys.clear()
        with pytest.raises(ValueError, match="No active signing key"):
            adapter.get_signing_key()

    def test_rotate_all_keys_with_no_active_keys(self):
        """Covers lines 308-317: rotate_all_keys when no active keys."""
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        adapter._active_keys.clear()
        result = adapter.rotate_all_keys()
        assert result == {}

    def test_get_key_status_without_signing_key(self):
        """Covers lines 356-370: status when no signing key."""
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        adapter._active_keys.clear()
        status = adapter.get_key_status()
        assert "signing_key" not in status
        assert status["active_keys"] == 0

    def test_create_hmac_raises_on_hmac_error(self):
        """Covers lines 424-425: exception handler in create_hmac_signature."""
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        self.mod._adapter = adapter
        # Pass an invalid algorithm that exists in hashlib but produces error
        # by patching hashlib internally
        with patch("hashlib.sha256", side_effect=ValueError("hash error")):
            with pytest.raises(ValueError, match="Failed to create HMAC"):
                self.mod.create_hmac_signature(b"test")
        self.mod._adapter = None

    def test_load_secrets_generic_exception(self):
        """Covers lines 122-123: RuntimeError from _load_secrets."""
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        adapter._initialized = False
        # Make _get_or_create_key raise a generic exception
        with patch.object(
            adapter,
            "_get_or_create_key",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="Failed to load secrets"):
                adapter._load_secrets()

    def test_get_or_create_key_generic_exception(self):
        """Covers lines 167-168: RuntimeError from _get_or_create_key."""
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        # Make secrets.get raise something that is NOT SecretNotFoundError
        original_get = self.mock.get.side_effect

        def _raising_get(name, default=""):
            if "signing_key" == name.split("/")[-1]:
                raise RuntimeError("connection refused")
            return original_get(name, default)

        self.mock.get.side_effect = _raising_get
        # Clear adapter so _get_or_create_key is called fresh
        adapter._initialized = False
        with pytest.raises(RuntimeError, match="Failed to handle key"):
            adapter._get_or_create_key("signing_key")

    def test_init_loads_with_double_checked_locking(self):
        """Covers lines 104, 107: double-checked locking in _load_secrets."""
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        # Already initialized; calling again should be a no-op
        adapter._load_secrets()
        assert adapter._initialized is True

    def test_singleton_double_check(self):
        """Covers lines 395-398: double-checked locking in get_secrets_adapter."""
        self.mod._adapter = None
        adapter1 = self.mod.get_secrets_adapter()
        # Second call hits the outer check (no lock needed)
        adapter2 = self.mod.get_secrets_adapter()
        assert adapter1 is adapter2

    def test_verify_hmac_signature_length_mismatch(self):
        """Verify returns False for wrong-length signature."""
        adapter = self.mod.OneiricSecretsAdapter(secret_prefix="test/hmac")
        self.mod._adapter = adapter
        # 32-byte message, but provide 16-byte signature
        result = self.mod.verify_hmac_signature(
            b"test message", b"\x00" * 16
        )
        assert result is False
        self.mod._adapter = None

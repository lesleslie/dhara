"""Comprehensive tests for the Dhara operational modes system.

Covers:
- base.py: OperationalModeError, ModeValidationError, OperationalMode ABC,
  LiteMode/StandardMode stubs, create_mode(), get_mode(), list_modes()
- standard.py: Full StandardMode implementation
- lite.py: Full LiteMode implementation
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dhara.core.config import DharaSettings, StorageConfig
from dhara.modes.base import (
    LiteMode as BaseLiteMode,
    ModeConfigurationError,
    ModeValidationError,
    OperationalMode,
    OperationalModeError,
    StandardMode as BaseStandardMode,
    create_mode,
    get_mode,
    list_modes,
)
from dhara.modes.lite import LiteMode
from dhara.modes.standard import StandardMode


# ---------------------------------------------------------------------------
# Exception tests
# ---------------------------------------------------------------------------


class TestOperationalModeError:
    """Tests for OperationalModeError exception."""

    def test_default_message(self):
        err = OperationalModeError("something went wrong")
        assert err.message == "something went wrong"
        assert err.mode_name is None
        assert err.details == {}
        assert str(err) == "something went wrong"

    def test_with_mode_name(self):
        err = OperationalModeError("bad config", mode_name="Lite")
        assert err.mode_name == "Lite"

    def test_with_details(self):
        details = {"key": "value", "fix": "do X"}
        err = OperationalModeError("bad config", mode_name="Standard", details=details)
        assert err.details == details

    def test_is_exception(self):
        assert issubclass(OperationalModeError, Exception)


class TestModeValidationError:
    """Tests for ModeValidationError exception."""

    def test_inherits_from_operational_mode_error(self):
        assert issubclass(ModeValidationError, OperationalModeError)

    def test_default_construction(self):
        err = ModeValidationError("env invalid", mode_name="lite")
        assert err.message == "env invalid"
        assert err.mode_name == "lite"

    def test_with_details_dict(self):
        err = ModeValidationError(
            "cannot write",
            mode_name="lite",
            details={"storage_dir": "/tmp/x", "fix": "chmod"},
        )
        assert err.details["storage_dir"] == "/tmp/x"


class TestModeConfigurationError:
    """Tests for ModeConfigurationError exception."""

    def test_inherits_from_operational_mode_error(self):
        assert issubclass(ModeConfigurationError, OperationalModeError)

    def test_default_construction(self):
        err = ModeConfigurationError("bad yaml")
        assert err.message == "bad yaml"


# ---------------------------------------------------------------------------
# OperationalMode ABC tests (using base stubs)
# ---------------------------------------------------------------------------


class TestOperationalModeABC:
    """Tests for the OperationalMode abstract base class using stub implementations."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            OperationalMode()

    def test_abstract_methods_exist(self):
        abstracts = OperationalMode.__abstractmethods__
        assert "get_name" in abstracts
        assert "get_description" in abstracts
        assert "get_config_path" in abstracts
        assert "get_default_storage_path" in abstracts
        assert "configure_storage" in abstracts
        assert "get_startup_options" in abstracts

    # -- name property (uses get_name) --

    def test_name_property_lowercases(self):
        mode = BaseLiteMode()
        assert mode.name == "lite"

    def test_name_property_standard(self):
        mode = BaseStandardMode()
        assert mode.name == "standard"

    # -- validate_environment (base implementation) --

    def test_validate_environment_creates_dir(self, tmp_path):
        """validate_environment should create missing storage directory."""
        storage_path = tmp_path / "subdir" / "data.dhara"
        mode = BaseLiteMode()
        # Override to use tmp_path
        with patch.object(mode, "get_default_storage_path", return_value=storage_path):
            result = mode.validate_environment()
        assert result is True
        assert storage_path.parent.exists()
        assert mode._validated is True

    def test_validate_environment_writable_dir(self, tmp_path):
        """validate_environment succeeds with writable directory."""
        storage_path = tmp_path / "data.dhara"
        storage_path.parent.mkdir(exist_ok=True)
        mode = BaseLiteMode()
        with patch.object(mode, "get_default_storage_path", return_value=storage_path):
            result = mode.validate_environment()
        assert result is True

    def test_validate_environment_non_writable_dir(self, tmp_path):
        """validate_environment raises on non-writable directory."""
        storage_path = tmp_path / "data.dhara"
        storage_path.parent.mkdir(exist_ok=True)
        mode = BaseLiteMode()
        with patch.object(mode, "get_default_storage_path", return_value=storage_path):
            with patch("os.access", return_value=False):
                with pytest.raises(ModeValidationError, match="Cannot write"):
                    mode.validate_environment()

    def test_validate_environment_handles_generic_error(self, tmp_path):
        """validate_environment wraps unexpected errors in ModeValidationError."""
        storage_path = tmp_path / "data.dhara"
        mode = BaseLiteMode()
        with patch.object(mode, "get_default_storage_path", return_value=storage_path):
            with patch.object(mode, "get_default_storage_path", return_value=storage_path):
                with patch("os.access", side_effect=OSError("boom")):
                    with pytest.raises(ModeValidationError, match="Environment validation failed"):
                        mode.validate_environment()

    # -- get_banner --

    def test_get_banner_contains_name(self):
        mode = BaseLiteMode()
        banner = mode.get_banner()
        assert "Lite" in banner
        assert "Dhara" in banner

    def test_get_banner_contains_description(self):
        mode = BaseLiteMode()
        banner = mode.get_banner()
        assert "zero configuration" in banner.lower()

    # -- get_info --

    def test_get_info_structure(self):
        mode = BaseLiteMode()
        info = mode.get_info()
        assert "name" in info
        assert "description" in info
        assert "config_path" in info
        assert "storage_path" in info
        assert "validated" in info
        assert "startup_options" in info

    def test_get_info_values(self):
        mode = BaseLiteMode()
        info = mode.get_info()
        assert info["name"] == "Lite"
        assert info["validated"] is False
        assert "host" in info["startup_options"]
        assert "port" in info["startup_options"]

    # -- initialize --

    def test_initialize_calls_validate_environment(self, tmp_path):
        """initialize() calls validate_environment when not yet validated."""
        storage_path = tmp_path / "data.dhara"
        mode = BaseLiteMode()
        with patch.object(mode, "get_default_storage_path", return_value=storage_path):
            with patch.object(mode, "configure_storage", return_value=StorageConfig()) as mock_cfg:
                with patch.object(DharaSettings, "load", return_value=DharaSettings()):
                    mode.initialize()
        assert mode._validated is True
        mock_cfg.assert_called_once()

    def test_initialize_skips_validation_if_already_validated(self, tmp_path):
        """initialize() skips validate_environment when already validated."""
        storage_path = tmp_path / "data.dhara"
        mode = BaseLiteMode()
        mode._validated = True
        mode.settings = DharaSettings()
        with patch.object(mode, "validate_environment") as mock_val:
            with patch.object(mode, "configure_storage", return_value=StorageConfig()):
                mode.initialize()
        mock_val.assert_not_called()

    def test_initialize_raises_on_validation_failure(self, tmp_path):
        """initialize() propagates ModeValidationError."""
        storage_path = tmp_path / "data.dhara"
        mode = BaseLiteMode()
        with patch.object(mode, "get_default_storage_path", return_value=storage_path):
            with patch("os.access", return_value=False):
                with pytest.raises(ModeValidationError):
                    mode.initialize()


# ---------------------------------------------------------------------------
# Base stub LiteMode and StandardMode tests
# ---------------------------------------------------------------------------


class TestBaseLiteModeStub:
    """Tests for the LiteMode stub in base.py."""

    def test_get_name(self):
        mode = BaseLiteMode()
        assert mode.get_name() == "Lite"

    def test_get_description(self):
        mode = BaseLiteMode()
        assert "zero configuration" in mode.get_description().lower()

    def test_get_config_path(self):
        mode = BaseLiteMode()
        path = mode.get_config_path()
        assert path.name == "lite.yaml"
        assert "settings" in str(path)

    def test_get_default_storage_path(self):
        mode = BaseLiteMode()
        path = mode.get_default_storage_path()
        assert str(path).endswith(".local/share/dhara/lite.dhara")

    def test_configure_storage(self):
        mode = BaseLiteMode()
        config = StorageConfig(backend="sqlite", path=Path("/tmp/other.db"))
        result = mode.configure_storage(config)
        assert result.backend == "file"
        assert result.path == mode.get_default_storage_path()
        assert result.read_only is False

    def test_get_startup_options(self):
        mode = BaseLiteMode()
        opts = mode.get_startup_options()
        assert opts["host"] == "127.0.0.1"
        assert opts["port"] == 8683


class TestBaseStandardModeStub:
    """Tests for the StandardMode stub in base.py."""

    def test_get_name(self):
        mode = BaseStandardMode()
        assert mode.get_name() == "Standard"

    def test_get_description(self):
        mode = BaseStandardMode()
        assert "full capabilities" in mode.get_description().lower()

    def test_get_config_path(self):
        mode = BaseStandardMode()
        path = mode.get_config_path()
        assert path.name == "standard.yaml"
        assert "settings" in str(path)

    def test_get_default_storage_path(self):
        mode = BaseStandardMode()
        path = mode.get_default_storage_path()
        assert str(path) == "/data/dhara/production.dhara"

    def test_configure_storage_keeps_existing_path(self):
        mode = BaseStandardMode()
        config = StorageConfig(path=Path("/custom/path.dhara"))
        result = mode.configure_storage(config)
        assert result.path == Path("/custom/path.dhara")

    def test_configure_storage_overrides_default_path(self):
        mode = BaseStandardMode()
        config = StorageConfig(path=Path("/data/dhara/dhara.dhara"))
        result = mode.configure_storage(config)
        assert result.path == Path("/data/dhara/production.dhara")

    def test_configure_storage_default_path_when_default_dhara_path(self):
        """Stub configure_storage overrides the default dhara path."""
        mode = BaseStandardMode()
        config = StorageConfig(path=Path("/data/dhara/dhara.dhara"))
        result = mode.configure_storage(config)
        assert result.path == Path("/data/dhara/production.dhara")

    def test_get_startup_options(self):
        mode = BaseStandardMode()
        opts = mode.get_startup_options()
        assert opts["host"] == "0.0.0.0"
        assert opts["port"] == 8683


# ---------------------------------------------------------------------------
# create_mode() factory function
# ---------------------------------------------------------------------------


class TestCreateMode:
    """Tests for the create_mode() factory function."""

    def test_create_lite_mode(self):
        mode = create_mode("lite")
        assert isinstance(mode, BaseLiteMode)
        assert mode.get_name() == "Lite"

    def test_create_standard_mode(self):
        mode = create_mode("standard")
        assert isinstance(mode, BaseStandardMode)
        assert mode.get_name() == "Standard"

    def test_create_mode_case_insensitive(self):
        mode = create_mode("LITE")
        assert mode.name == "lite"

    def test_create_mode_strips_whitespace(self):
        mode = create_mode("  lite  ")
        assert mode.name == "lite"

    def test_create_mode_with_settings(self):
        settings = DharaSettings()
        mode = create_mode("lite", settings=settings)
        assert mode.settings is settings

    def test_create_mode_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid mode: production"):
            create_mode("production")

    def test_create_mode_empty_raises(self):
        with pytest.raises(ValueError, match="Invalid mode"):
            create_mode("")


# ---------------------------------------------------------------------------
# get_mode() detection function
# ---------------------------------------------------------------------------


class TestGetMode:
    """Tests for the get_mode() auto-detection function."""

    def test_env_var_lite(self, monkeypatch):
        monkeypatch.setenv("DHARA_MODE", "lite")
        mode = get_mode()
        assert mode.name == "lite"

    def test_env_var_standard(self, monkeypatch):
        monkeypatch.setenv("DHARA_MODE", "standard")
        mode = get_mode()
        assert mode.name == "standard"

    def test_env_var_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("DHARA_MODE", "STANDARD")
        mode = get_mode()
        assert mode.name == "standard"

    def test_settings_detection_lite_path(self, monkeypatch):
        """Auto-detects lite mode when storage path matches lite default."""
        monkeypatch.delenv("DHARA_MODE", raising=False)
        settings = DharaSettings()
        lite_path = Path.home() / ".local" / "share" / "dhara" / "lite.dhara"
        settings.storage = StorageConfig(path=lite_path)
        mode = get_mode(settings=settings)
        assert mode.name == "lite"

    def test_settings_detection_standard_backend(self, monkeypatch):
        """Auto-detects standard mode when backend is not 'file'."""
        monkeypatch.delenv("DHARA_MODE", raising=False)
        settings = DharaSettings()
        settings.storage = StorageConfig(backend="s3")
        mode = get_mode(settings=settings)
        assert mode.name == "standard"

    def test_settings_detection_sqlite_backend(self, monkeypatch):
        """SQLite backend triggers standard mode."""
        monkeypatch.delenv("DHARA_MODE", raising=False)
        settings = DharaSettings()
        settings.storage = StorageConfig(backend="sqlite")
        mode = get_mode(settings=settings)
        assert mode.name == "standard"

    def test_default_to_lite(self, monkeypatch):
        """Defaults to lite mode when no env var and no settings."""
        monkeypatch.delenv("DHARA_MODE", raising=False)
        with patch.object(DharaSettings, "load", side_effect=Exception("no config")):
            mode = get_mode()
        assert mode.name == "lite"

    def test_env_var_takes_priority_over_settings(self, monkeypatch):
        """Environment variable overrides settings-based detection."""
        monkeypatch.setenv("DHARA_MODE", "lite")
        settings = DharaSettings()
        settings.storage = StorageConfig(backend="s3")
        mode = get_mode(settings=settings)
        assert mode.name == "lite"

    def test_invalid_env_var_falls_through(self, monkeypatch):
        """Invalid DHARA_MODE value falls through to settings detection."""
        monkeypatch.setenv("DHARA_MODE", "production")
        with patch.object(DharaSettings, "load", side_effect=Exception("no config")):
            mode = get_mode()
        assert mode.name == "lite"


# ---------------------------------------------------------------------------
# list_modes() function
# ---------------------------------------------------------------------------


class TestListModes:
    """Tests for the list_modes() function."""

    def test_returns_list(self):
        modes = list_modes()
        assert isinstance(modes, list)

    def test_returns_two_modes(self):
        modes = list_modes()
        assert len(modes) == 2

    def test_contains_lite_and_standard(self):
        modes = list_modes()
        names = [m["name"] for m in modes]
        assert "Lite" in names
        assert "Standard" in names

    def test_each_mode_has_info_keys(self):
        modes = list_modes()
        for mode_info in modes:
            assert "name" in mode_info
            assert "description" in mode_info
            assert "config_path" in mode_info
            assert "storage_path" in mode_info
            assert "validated" in mode_info
            assert "startup_options" in mode_info


# ===========================================================================
# Full LiteMode tests (from lite.py)
# ===========================================================================


class TestLiteMode:
    """Tests for the full LiteMode implementation from modes/lite.py."""

    def test_get_name(self):
        mode = LiteMode()
        assert mode.get_name() == "Lite"

    def test_mode_name_constant(self):
        assert LiteMode.MODE_NAME == "Lite"

    def test_get_description(self):
        mode = LiteMode()
        assert "zero configuration" in mode.get_description().lower()

    def test_mode_description_constant(self):
        assert "zero configuration" in LiteMode.MODE_DESCRIPTION.lower()

    def test_get_config_path(self):
        mode = LiteMode()
        path = mode.get_config_path()
        assert path.name == "lite.yaml"
        assert "settings" in str(path)

    def test_get_default_storage_path(self):
        mode = LiteMode()
        path = mode.get_default_storage_path()
        assert str(path).endswith(".local/share/dhara/lite.dhara")

    def test_name_property(self):
        mode = LiteMode()
        assert mode.name == "lite"

    def test_default_host(self):
        assert LiteMode.DEFAULT_HOST == "127.0.0.1"

    def test_default_port(self):
        assert LiteMode.DEFAULT_PORT == 8683

    # -- validate_environment --

    def test_validate_environment_existing_dir(self, tmp_path):
        """Validation succeeds when storage dir already exists and is writable."""
        storage_path = tmp_path / "data" / "lite.dhara"
        storage_path.parent.mkdir(parents=True)
        mode = LiteMode()
        with patch.object(mode, "DEFAULT_STORAGE_PATH", storage_path):
            result = mode.validate_environment()
        assert result is True
        assert mode._validated is True

    def test_validate_environment_creates_missing_dir(self, tmp_path):
        """Validation creates missing storage directory."""
        storage_path = tmp_path / "newdir" / "subdir" / "lite.dhara"
        mode = LiteMode()
        with patch.object(mode, "DEFAULT_STORAGE_PATH", storage_path):
            result = mode.validate_environment()
        assert result is True
        assert storage_path.parent.exists()

    def test_validate_environment_permission_error(self, tmp_path):
        """Validation raises ModeValidationError on permission failure."""
        storage_path = tmp_path / "data" / "lite.dhara"
        storage_path.parent.mkdir(parents=True)
        mode = LiteMode()
        with patch.object(mode, "DEFAULT_STORAGE_PATH", storage_path):
            with patch("os.access", return_value=False):
                with pytest.raises(ModeValidationError, match="Cannot write"):
                    mode.validate_environment()

    def test_validate_environment_generic_error(self, tmp_path):
        """Validation wraps unexpected errors."""
        storage_path = tmp_path / "data" / "lite.dhara"
        mode = LiteMode()
        with patch.object(mode, "DEFAULT_STORAGE_PATH", storage_path):
            with patch.object(Path, "mkdir", side_effect=OSError("disk full")):
                with pytest.raises(ModeValidationError, match="Environment validation failed"):
                    mode.validate_environment()

    # -- configure_storage --

    def test_configure_storage_forces_file_backend(self):
        """Lite mode always forces 'file' backend regardless of input."""
        mode = LiteMode()
        config = StorageConfig(backend="s3", path=Path("s3://bucket/data"))
        result = mode.configure_storage(config)
        assert result.backend == "file"
        assert result.path == mode.DEFAULT_STORAGE_PATH
        assert result.read_only is False

    def test_configure_storage_overrides_existing_config(self):
        """Lite mode overrides all storage settings."""
        mode = LiteMode()
        config = StorageConfig(
            backend="sqlite",
            path=Path("/tmp/other.db"),
            read_only=True,
        )
        result = mode.configure_storage(config)
        assert result.backend == "file"
        assert result.read_only is False

    # -- get_startup_options --

    def test_get_startup_options(self):
        mode = LiteMode()
        opts = mode.get_startup_options()
        assert opts["host"] == "127.0.0.1"
        assert opts["port"] == 8683
        assert opts["storage_path"] == str(mode.DEFAULT_STORAGE_PATH)
        assert opts["storage_backend"] == "file"
        assert opts["read_only"] is False
        assert opts["log_level"] == "DEBUG"
        assert opts["log_format"] == "text"

    # -- get_banner --

    def test_get_banner_content(self):
        mode = LiteMode()
        banner = mode.get_banner()
        assert "Lite Mode" in banner
        assert "Zero configuration" in banner
        assert "127.0.0.1:8683" in banner
        assert "dhara start --mode=lite" in banner

    # -- get_info --

    def test_get_info_extended(self):
        mode = LiteMode()
        info = mode.get_info()
        assert info["name"] == "Lite"
        assert info["startup_command"] == "dhara start --mode=lite"
        assert info["access_url"] == "http://127.0.0.1:8683"
        assert info["configuration_required"] is False
        assert "ideal_for" in info
        assert "Local development" in info["ideal_for"]

    # -- _is_port_available --

    def test_is_port_available_unreachable(self):
        """Port that nothing is listening on should be 'available'."""
        mode = LiteMode()
        # Use a port that is almost certainly not in use
        result = mode._is_port_available("127.0.0.1", 59999)
        assert result is True

    def test_is_port_available_listening(self):
        """Port with a server listening should be 'not available'."""
        mode = LiteMode()
        # Bind a socket to a port, then check
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            result = mode._is_port_available("127.0.0.1", port)
            assert result is False
        finally:
            sock.close()

    def test_is_port_available_exception_returns_true(self):
        """If socket check fails, assume port is available."""
        mode = LiteMode()
        with patch("socket.socket", side_effect=OSError("network down")):
            result = mode._is_port_available("127.0.0.1", 8683)
            assert result is True

    # -- initialization with settings --

    def test_init_with_settings(self):
        settings = DharaSettings()
        mode = LiteMode(settings=settings)
        assert mode.settings is settings

    def test_init_without_settings(self):
        mode = LiteMode()
        assert mode.settings is None


# ===========================================================================
# Full StandardMode tests (from standard.py)
# ===========================================================================


class TestStandardMode:
    """Tests for the full StandardMode implementation from modes/standard.py."""

    def test_get_name(self):
        mode = StandardMode()
        assert mode.get_name() == "Standard"

    def test_mode_name_constant(self):
        assert StandardMode.MODE_NAME == "Standard"

    def test_get_description(self):
        mode = StandardMode()
        assert "full capabilities" in mode.get_description().lower()

    def test_get_config_path(self):
        mode = StandardMode()
        path = mode.get_config_path()
        assert path.name == "standard.yaml"
        assert "settings" in str(path)

    def test_get_default_storage_path(self):
        mode = StandardMode()
        assert str(mode.get_default_storage_path()) == "/data/dhara/production.dhara"

    def test_name_property(self):
        mode = StandardMode()
        assert mode.name == "standard"

    def test_default_host(self):
        assert StandardMode.DEFAULT_HOST == "0.0.0.0"

    def test_default_port(self):
        assert StandardMode.DEFAULT_PORT == 8683

    def test_supported_backends(self):
        assert "file" in StandardMode.SUPPORTED_BACKENDS
        assert "sqlite" in StandardMode.SUPPORTED_BACKENDS
        assert "s3" in StandardMode.SUPPORTED_BACKENDS
        assert "gcs" in StandardMode.SUPPORTED_BACKENDS
        assert "azure" in StandardMode.SUPPORTED_BACKENDS

    # -- validate_environment --

    def test_validate_file_backend(self, tmp_path):
        """File backend validation creates directory and checks permissions."""
        storage_path = tmp_path / "data" / "production.dhara"
        settings = DharaSettings()
        settings.storage = StorageConfig(backend="file", path=storage_path)
        mode = StandardMode(settings=settings)
        result = mode.validate_environment()
        assert result is True
        assert mode._validated is True
        assert storage_path.parent.exists()

    def test_validate_sqlite_backend(self, tmp_path):
        """SQLite backend validation uses same file storage validation."""
        storage_path = tmp_path / "data" / "production.db"
        settings = DharaSettings()
        settings.storage = StorageConfig(backend="sqlite", path=storage_path)
        mode = StandardMode(settings=settings)
        result = mode.validate_environment()
        assert result is True

    def test_validate_file_backend_empty_path(self):
        """File backend with empty-ish path (via MagicMock) raises ModeValidationError."""
        settings = MagicMock(spec=DharaSettings)
        settings.storage = MagicMock(spec=StorageConfig)
        settings.storage.backend = "file"
        settings.storage.path = None  # Simulate empty path
        mode = StandardMode(settings=settings)
        with pytest.raises(ModeValidationError, match="Storage path not configured"):
            mode.validate_environment()

    def test_validate_file_backend_cannot_create_dir(self, tmp_path):
        """File backend raises when directory cannot be created."""
        storage_path = tmp_path / "data" / "production.dhara"
        settings = DharaSettings()
        settings.storage = StorageConfig(backend="file", path=storage_path)
        mode = StandardMode(settings=settings)
        with patch.object(Path, "mkdir", side_effect=OSError("permission denied")):
            with pytest.raises(ModeValidationError, match="Cannot create storage directory"):
                mode.validate_environment()

    def test_validate_file_backend_no_write_permission(self, tmp_path):
        """File backend raises when directory is not writable."""
        storage_path = tmp_path / "data" / "production.dhara"
        storage_path.parent.mkdir(parents=True)
        settings = DharaSettings()
        settings.storage = StorageConfig(backend="file", path=storage_path)
        mode = StandardMode(settings=settings)
        with patch("os.access", return_value=False):
            with pytest.raises(ModeValidationError, match="Cannot write to storage directory"):
                mode.validate_environment()

    def test_validate_unsupported_backend(self):
        """Unsupported backend raises ModeValidationError."""
        settings = DharaSettings()
        settings.storage = StorageConfig(backend="mongodb")
        mode = StandardMode(settings=settings)
        with pytest.raises(ModeValidationError, match="Unsupported storage backend"):
            mode.validate_environment()

    def test_validate_s3_backend_no_credentials(self, monkeypatch):
        """S3 backend with missing credentials logs warning but does not raise."""
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.storage = MagicMock(spec=StorageConfig)
        settings.storage.backend = "s3"
        # Give it a bucket so bucket check passes
        settings.s3_bucket = "my-bucket"
        mode = StandardMode(settings=settings)
        # Should not raise, just warn
        result = mode.validate_environment()
        assert result is True

    def test_validate_s3_backend_no_bucket(self, monkeypatch):
        """S3 backend with no bucket configured raises ModeValidationError."""
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.storage = MagicMock(spec=StorageConfig)
        settings.storage.backend = "s3"
        settings.s3_bucket = ""
        mode = StandardMode(settings=settings)
        with pytest.raises(ModeValidationError, match="S3 bucket not configured"):
            mode.validate_environment()

    def test_validate_gcs_backend_no_credentials(self, monkeypatch):
        """GCS backend with missing credentials logs warning but does not raise."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        monkeypatch.delenv("GCS_KEYFILE", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.storage = MagicMock(spec=StorageConfig)
        settings.storage.backend = "gcs"
        settings.gcs_bucket = "my-bucket"
        mode = StandardMode(settings=settings)
        result = mode.validate_environment()
        assert result is True

    def test_validate_gcs_backend_no_bucket(self, monkeypatch):
        """GCS backend with no bucket configured raises ModeValidationError."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        monkeypatch.delenv("GCS_KEYFILE", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.storage = MagicMock(spec=StorageConfig)
        settings.storage.backend = "gcs"
        settings.gcs_bucket = ""
        mode = StandardMode(settings=settings)
        with pytest.raises(ModeValidationError, match="GCS bucket not configured"):
            mode.validate_environment()

    def test_validate_azure_backend_no_credentials(self, monkeypatch):
        """Azure backend with missing credentials logs warning but does not raise."""
        monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.delenv("AZURE_STORAGE_KEY", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.storage = MagicMock(spec=StorageConfig)
        settings.storage.backend = "azure"
        settings.azure_container = "my-container"
        mode = StandardMode(settings=settings)
        result = mode.validate_environment()
        assert result is True

    def test_validate_azure_backend_no_container(self, monkeypatch):
        """Azure backend with no container configured raises ModeValidationError."""
        monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.delenv("AZURE_STORAGE_KEY", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.storage = MagicMock(spec=StorageConfig)
        settings.storage.backend = "azure"
        settings.azure_container = ""
        mode = StandardMode(settings=settings)
        with pytest.raises(ModeValidationError, match="Azure container not configured"):
            mode.validate_environment()

    def test_validate_network_access_port_in_use(self):
        """Network validation warns if port is in use (does not raise)."""
        settings = MagicMock(spec=DharaSettings)
        settings.storage = MagicMock(spec=StorageConfig)
        settings.storage.backend = "file"
        mode = StandardMode(settings=settings)
        # Bind a socket to port 0 to get a free port, then check
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        with patch.object(mode, "DEFAULT_PORT", port):
            with patch.object(mode, "_validate_file_storage"):
                # Should not raise, just warn
                result = mode.validate_environment()
        assert result is True
        sock.close()

    def test_validate_no_settings_loads_default(self):
        """When settings is None, validate_environment loads defaults."""
        mode = StandardMode(settings=None)
        with patch.object(DharaSettings, "load", return_value=DharaSettings()):
            with patch.object(mode, "_validate_file_storage"):
                with patch.object(mode, "_validate_network_access"):
                    result = mode.validate_environment()
        assert result is True

    def test_validate_settings_load_fails_gracefully(self):
        """When settings load fails, validate_environment uses defaults."""
        mode = StandardMode(settings=None)
        with patch.object(DharaSettings, "load", side_effect=Exception("bad yaml")):
            with patch.object(mode, "_validate_file_storage"):
                with patch.object(mode, "_validate_network_access"):
                    result = mode.validate_environment()
        assert result is True

    # -- configure_storage --

    def test_configure_file_storage(self):
        mode = StandardMode()
        config = StorageConfig(backend="file")
        result = mode.configure_storage(config)
        assert result.backend == "file"
        # Default path is /data/dhara.dhara, which does NOT match the
        # override condition /data/dhara/dhara.dhara, so it stays as-is
        assert result.path == Path("/data/dhara.dhara")

    def test_configure_file_storage_with_default_dhara_path(self):
        """File storage overrides the path when it matches /data/dhara/dhara.dhara."""
        mode = StandardMode()
        config = StorageConfig(backend="file", path=Path("/data/dhara/dhara.dhara"))
        result = mode.configure_storage(config)
        assert result.backend == "file"
        assert result.path == StandardMode.DEFAULT_STORAGE_PATH

    def test_configure_file_storage_preserves_custom_path(self):
        mode = StandardMode()
        config = StorageConfig(backend="file", path=Path("/custom/data.dhara"))
        result = mode.configure_storage(config)
        assert result.backend == "file"
        assert result.path == Path("/custom/data.dhara")

    def test_configure_sqlite_storage(self):
        mode = StandardMode()
        config = StorageConfig(backend="sqlite")
        result = mode.configure_storage(config)
        assert result.backend == "sqlite"
        # Default path /data/dhara.dhara does NOT match /data/dhara/dhara.dhara
        assert result.path == Path("/data/dhara.dhara")

    def test_configure_sqlite_storage_with_default_dhara_path(self):
        mode = StandardMode()
        config = StorageConfig(backend="sqlite", path=Path("/data/dhara/dhara.dhara"))
        result = mode.configure_storage(config)
        assert result.backend == "sqlite"
        assert result.path == Path("/data/dhara/production.db")

    def test_configure_s3_storage(self):
        mode = StandardMode()
        config = StorageConfig(backend="s3")
        result = mode.configure_storage(config)
        assert result.backend == "s3"
        # Default path does not match /data/dhara/dhara.dhara
        assert result.path == Path("/data/dhara.dhara")

    def test_configure_s3_storage_with_default_dhara_path(self):
        mode = StandardMode()
        config = StorageConfig(backend="s3", path=Path("/data/dhara/dhara.dhara"))
        result = mode.configure_storage(config)
        assert result.backend == "s3"
        # Path normalizes s3:// to s3:/
        assert "s3:/dhara-production/dhara.dhara" in str(result.path)

    def test_configure_gcs_storage(self):
        mode = StandardMode()
        config = StorageConfig(backend="gcs")
        result = mode.configure_storage(config)
        assert result.backend == "gcs"
        assert result.path == Path("/data/dhara.dhara")

    def test_configure_gcs_storage_with_default_dhara_path(self):
        mode = StandardMode()
        config = StorageConfig(backend="gcs", path=Path("/data/dhara/dhara.dhara"))
        result = mode.configure_storage(config)
        assert result.backend == "gcs"
        # Path normalizes gs:// to gs:/
        assert "gs:/dhara-production/dhara.dhara" in str(result.path)

    def test_configure_azure_storage(self):
        mode = StandardMode()
        config = StorageConfig(backend="azure")
        result = mode.configure_storage(config)
        assert result.backend == "azure"
        assert result.path == Path("/data/dhara.dhara")

    def test_configure_azure_storage_with_default_dhara_path(self):
        mode = StandardMode()
        config = StorageConfig(backend="azure", path=Path("/data/dhara/dhara.dhara"))
        result = mode.configure_storage(config)
        assert result.backend == "azure"
        # Path normalizes azure:// to azure:/
        assert "azure:/dhara-production/dhara.dhara" in str(result.path)

    def test_configure_storage_empty_backend_defaults_to_file(self):
        """When backend is empty string, defaults to 'file'."""
        mode = StandardMode()
        config = StorageConfig(backend="")
        result = mode.configure_storage(config)
        assert result.backend == "file"

    # -- get_startup_options --

    def test_get_startup_options(self):
        mode = StandardMode()
        opts = mode.get_startup_options()
        assert opts["host"] == "0.0.0.0"
        assert opts["port"] == 8683
        assert opts["storage_backend"] == "file"
        assert opts["read_only"] is False
        assert opts["log_level"] == "INFO"
        assert opts["log_format"] == "json"
        assert opts["cloud_storage"]["enabled"] is True
        assert opts["cloud_storage"]["backup_enabled"] is True

    # -- get_banner --

    def test_get_banner_content(self):
        mode = StandardMode()
        banner = mode.get_banner()
        assert "Standard Mode" in banner
        assert "Production Ready" in banner
        assert "0.0.0.0:8683" in banner
        assert "dhara start --mode=standard" in banner

    def test_get_banner_shows_backend(self):
        mode = StandardMode()
        mode.settings = DharaSettings()
        mode.settings.storage = StorageConfig(backend="s3")
        banner = mode.get_banner()
        assert "s3" in banner

    def test_get_banner_default_backend(self):
        mode = StandardMode()
        banner = mode.get_banner()
        assert "file" in banner

    # -- get_info --

    def test_get_info_extended(self):
        mode = StandardMode()
        info = mode.get_info()
        assert info["name"] == "Standard"
        assert info["startup_command"] == "dhara start --mode=standard"
        assert info["supported_backends"] == StandardMode.SUPPORTED_BACKENDS
        assert info["access_url"] == "http://0.0.0.0:8683"
        assert info["configuration_required"] is True
        assert "ideal_for" in info
        assert "Production deployments" in info["ideal_for"]

    def test_get_info_includes_base_keys(self):
        mode = StandardMode()
        info = mode.get_info()
        assert "description" in info
        assert "config_path" in info
        assert "storage_path" in info
        assert "validated" in info
        assert "startup_options" in info

    # -- _is_port_available --

    def test_is_port_available_unreachable(self):
        mode = StandardMode()
        result = mode._is_port_available("0.0.0.0", 59998)
        assert result is True

    def test_is_port_available_listening(self):
        mode = StandardMode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            result = mode._is_port_available("0.0.0.0", port)
            assert result is False
        finally:
            sock.close()

    def test_is_port_available_exception_returns_true(self):
        mode = StandardMode()
        with patch("socket.socket", side_effect=OSError("network error")):
            result = mode._is_port_available("0.0.0.0", 8683)
            assert result is True

    # -- _validate_s3_storage / _validate_gcs_storage / _validate_azure_storage --

    def test_validate_s3_with_credentials(self, monkeypatch):
        """S3 validation with credentials does not raise."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
        settings = MagicMock(spec=DharaSettings)
        settings.s3_bucket = "test-bucket"
        mode = StandardMode(settings=settings)
        # Should not raise
        mode._validate_s3_storage()

    def test_validate_s3_without_credentials_no_bucket(self, monkeypatch):
        """S3 validation without credentials and no bucket raises."""
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.s3_bucket = ""
        mode = StandardMode(settings=settings)
        with pytest.raises(ModeValidationError, match="S3 bucket not configured"):
            mode._validate_s3_storage()

    def test_validate_gcs_with_credentials(self, monkeypatch):
        """GCS validation with credentials does not raise."""
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/path/to/creds.json")
        settings = MagicMock(spec=DharaSettings)
        settings.gcs_bucket = "test-bucket"
        mode = StandardMode(settings=settings)
        mode._validate_gcs_storage()

    def test_validate_gcs_without_credentials_no_bucket(self, monkeypatch):
        """GCS validation without credentials and no bucket raises."""
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        monkeypatch.delenv("GCS_KEYFILE", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.gcs_bucket = ""
        mode = StandardMode(settings=settings)
        with pytest.raises(ModeValidationError, match="GCS bucket not configured"):
            mode._validate_gcs_storage()

    def test_validate_azure_with_credentials(self, monkeypatch):
        """Azure validation with credentials does not raise."""
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "conn-string")
        settings = MagicMock(spec=DharaSettings)
        settings.azure_container = "test-container"
        mode = StandardMode(settings=settings)
        mode._validate_azure_storage()

    def test_validate_azure_without_credentials_no_container(self, monkeypatch):
        """Azure validation without credentials and no container raises."""
        monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
        monkeypatch.delenv("AZURE_STORAGE_KEY", raising=False)
        settings = MagicMock(spec=DharaSettings)
        settings.azure_container = ""
        mode = StandardMode(settings=settings)
        with pytest.raises(ModeValidationError, match="Azure container not configured"):
            mode._validate_azure_storage()

    # -- initialization --

    def test_init_with_settings(self):
        settings = DharaSettings()
        mode = StandardMode(settings=settings)
        assert mode.settings is settings

    def test_init_without_settings(self):
        mode = StandardMode()
        assert mode.settings is None


# ===========================================================================
# Cross-mode integration tests
# ===========================================================================


class TestModeIntegration:
    """Integration tests spanning multiple mode classes."""

    def test_different_names(self):
        lite = LiteMode()
        std = StandardMode()
        assert lite.get_name() != std.get_name()
        assert lite.name != std.name

    def test_different_hosts(self):
        lite = LiteMode()
        std = StandardMode()
        assert lite.get_startup_options()["host"] != std.get_startup_options()["host"]

    def test_different_descriptions(self):
        lite = LiteMode()
        std = StandardMode()
        assert lite.get_description() != std.get_description()

    def test_different_config_paths(self):
        lite = LiteMode()
        std = StandardMode()
        assert lite.get_config_path() != std.get_config_path()

    def test_different_storage_paths(self):
        lite = LiteMode()
        std = StandardMode()
        assert lite.get_default_storage_path() != std.get_default_storage_path()

    def test_different_log_levels(self):
        lite = LiteMode()
        std = StandardMode()
        assert lite.get_startup_options()["log_level"] == "DEBUG"
        assert std.get_startup_options()["log_level"] == "INFO"

    def test_different_log_formats(self):
        lite = LiteMode()
        std = StandardMode()
        assert lite.get_startup_options()["log_format"] == "text"
        assert std.get_startup_options()["log_format"] == "json"

    def test_list_modes_includes_both(self):
        modes = list_modes()
        names = {m["name"] for m in modes}
        assert names == {"Lite", "Standard"}

    def test_create_mode_and_get_mode_consistency(self, monkeypatch):
        """create_mode and get_mode return instances with same name."""
        monkeypatch.delenv("DHARA_MODE", raising=False)
        with patch.object(DharaSettings, "load", side_effect=Exception("no config")):
            detected = get_mode()
        created = create_mode("lite")
        assert detected.name == created.name

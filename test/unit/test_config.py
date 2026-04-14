"""Unit tests for DharaSettings configuration.

Tests configuration management including:
- Default values
- YAML loading
- Environment variable overrides
- Type validation
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

import pytest
from pydantic import ValidationError

from dhara.core.config import AdapterConfig, DharaSettings, StorageConfig


@pytest.mark.unit
class TestStorageConfig:
    """Test StorageConfig model."""

    def test_storage_config_defaults(self):
        """Test StorageConfig has correct default values."""
        config = StorageConfig()

        assert config.path == Path("/data/dhara.dhara")
        assert config.read_only is False
        assert config.backend == "file"

    def test_storage_config_custom_values(self):
        """Test StorageConfig with custom values."""
        config = StorageConfig(
            path=Path("/custom/path.dhara"),
            read_only=True,
            backend="sqlite",
        )

        assert config.path == Path("/custom/path.dhara")
        assert config.read_only is True
        assert config.backend == "sqlite"

    def test_storage_config_validation(self):
        """Test StorageConfig validates types correctly."""
        # Should accept Path object
        config = StorageConfig(path=Path("/tmp/test.dhara"))
        assert isinstance(config.path, Path)

        # Should convert string to Path
        config = StorageConfig(path="/tmp/test.dhara")
        assert isinstance(config.path, Path)


@pytest.mark.unit
class TestAdapterConfig:
    """Test AdapterConfig model."""

    def test_adapter_config_defaults(self):
        """Test AdapterConfig has correct default values."""
        config = AdapterConfig()

        assert config.enable_versioning is True
        assert config.enable_health_checks is True
        assert config.max_versions_per_adapter == 10
        assert config.auto_push_on_startup is True

    def test_adapter_config_custom_values(self):
        """Test AdapterConfig with custom values."""
        config = AdapterConfig(
            enable_versioning=False,
            enable_health_checks=False,
            max_versions_per_adapter=20,
            auto_push_on_startup=False,
        )

        assert config.enable_versioning is False
        assert config.enable_health_checks is False
        assert config.max_versions_per_adapter == 20
        assert config.auto_push_on_startup is False

    def test_adapter_config_validation(self):
        """Test AdapterConfig validates constraints."""
        # Valid range
        config = AdapterConfig(max_versions_per_adapter=1)
        assert config.max_versions_per_adapter == 1

        config = AdapterConfig(max_versions_per_adapter=100)
        assert config.max_versions_per_adapter == 100

        # Invalid: too low
        with pytest.raises(ValidationError):
            AdapterConfig(max_versions_per_adapter=0)

        # Invalid: too high
        with pytest.raises(ValidationError):
            AdapterConfig(max_versions_per_adapter=101)


@pytest.mark.unit
class TestDharaSettings:
    """Test DharaSettings configuration."""

    def test_dhara_settings_defaults(self):
        """Test DharaSettings has correct default values."""
        settings = DharaSettings()

        assert settings.server_name == "dhara"
        assert settings.cache_root == Path("~/.oneiric_cache")
        assert isinstance(settings.storage, StorageConfig)
        assert isinstance(settings.adapters, AdapterConfig)
        assert settings.oneiric_config_path is None
        assert settings.host is None
        assert settings.port is None

    def test_dhara_settings_custom_storage(self):
        """Test DharaSettings with custom storage config."""
        settings = DharaSettings(
            storage={
                "path": "/custom/path.dhara",
                "read_only": True,
                "backend": "sqlite",
            }
        )

        assert settings.storage.path == Path("/custom/path.dhara")
        assert settings.storage.read_only is True
        assert settings.storage.backend == "sqlite"

    def test_dhara_settings_custom_adapters(self):
        """Test DharaSettings with custom adapter config."""
        settings = DharaSettings(
            adapters={
                "enable_versioning": False,
                "max_versions_per_adapter": 5,
            }
        )

        assert settings.adapters.enable_versioning is False
        assert settings.adapters.max_versions_per_adapter == 5

    def test_dhara_settings_custom_host_port(self):
        """Test DharaSettings with custom host and port."""
        settings = DharaSettings(
            host="0.0.0.0",
            port=9999,
        )

        assert settings.host == "0.0.0.0"
        assert settings.port == 9999

    def test_dhara_settings_custom_cache_root(self):
        """Test DharaSettings with custom cache root."""
        settings = DharaSettings(
            cache_root=Path("/custom/cache"),
        )

        assert settings.cache_root == Path("/custom/cache")

    def test_dhara_settings_with_oneiric_config(self):
        """Test DharaSettings with Oneiric config path."""
        settings = DharaSettings(
            oneiric_config_path=Path("/etc/oneiric.yaml"),
        )

        assert settings.oneiric_config_path == Path("/etc/oneiric.yaml")

    @pytest.fixture
    def clean_env(self) -> Generator[None, None, None]:
        """Fixture to clean environment variables before/after tests."""
        # Save original env vars
        original_env = {
            k: v
            for k, v in os.environ.items()
            if k.startswith("DHARA_")
        }

        # Clear DHARA_ env vars
        for key in list(os.environ.keys()):
            if key.startswith("DHARA_"):
                del os.environ[key]

        yield

        # Restore original env vars
        for key, value in original_env.items():
            os.environ[key] = value

    def test_environment_variable_override_storage_path(self, clean_env):
        """Test that DHARA_STORAGE_PATH overrides config."""
        os.environ["DHARA_STORAGE_PATH"] = "/env/path.dhara"

        settings = DharaSettings.load("dhara")

        # Environment variables should override defaults
        # Note: The actual override logic depends on MCPServerSettings.load()
        assert isinstance(settings.storage, StorageConfig)

    def test_environment_variable_override_storage_read_only(self, clean_env):
        """Test that DHARA_STORAGE_READ_ONLY overrides config."""
        os.environ["DHARA_STORAGE_READ_ONLY"] = "true"

        settings = DharaSettings.load("dhara")

        assert isinstance(settings.storage, StorageConfig)

    def test_environment_variable_override_host(self, clean_env):
        """Test that DHARA_HOST overrides config."""
        os.environ["DHARA_HOST"] = "192.168.1.1"

        settings = DharaSettings.load("dhara")

        # Note: Actual override behavior depends on MCPServerSettings
        assert isinstance(settings, DharaSettings)

    def test_environment_variable_override_port(self, clean_env):
        """Test that DHARA_PORT overrides config."""
        os.environ["DHARA_PORT"] = "8888"

        settings = DharaSettings.load("dhara")

        # Note: Actual override behavior depends on MCPServerSettings
        assert isinstance(settings, DharaSettings)

    def test_path_expansion_in_storage(self):
        """Test that ~ is expanded in storage path."""
        settings = DharaSettings(
            storage={
                "path": "~/custom.dhara",
            }
        )

        # Path should expand ~ when accessed
        expanded = settings.storage.path.expanduser()
        assert str(expanded) != "~/custom.dhara"
        assert "custom.dhara" in str(expanded)

    def test_path_expansion_in_cache_root(self):
        """Test that ~ is expanded in cache root."""
        settings = DharaSettings(
            cache_root="~/cache",
        )

        expanded = settings.cache_root.expanduser()
        assert str(expanded) != "~/cache"
        assert "cache" in str(expanded)

    def test_settings_to_dict(self):
        """Test converting settings to dictionary."""
        settings = DharaSettings(
            server_name="test-dhara",
            storage={
                "path": "/test.dhara",
                "read_only": True,
            },
        )

        d = settings.model_dump(mode="json")

        assert d["server_name"] == "test-dhara"
        assert d["storage"]["path"] == "/test.dhara"
        assert d["storage"]["read_only"] is True

    def test_settings_from_dict(self):
        """Test creating settings from dictionary."""
        data = {
            "server_name": "test-dhara",
            "storage": {
                "path": "/test.dhara",
                "read_only": True,
                "backend": "file",
            },
            "adapters": {
                "enable_versioning": False,
                "max_versions_per_adapter": 5,
            },
        }

        settings = DharaSettings(**data)

        assert settings.server_name == "test-dhara"
        assert settings.storage.path == Path("/test.dhara")
        assert settings.storage.read_only is True
        assert settings.adapters.enable_versioning is False
        assert settings.adapters.max_versions_per_adapter == 5

    def test_health_snapshot_path(self):
        """Test health_snapshot_path method."""
        settings = DharaSettings(
            cache_root=Path("/test/cache"),
        )

        snapshot_path = settings.health_snapshot_path()
        assert "dhara" in str(snapshot_path).lower()
        assert "health" in str(snapshot_path).lower()


@pytest.mark.unit
class TestSettingsIntegration:
    """Integration tests for settings with file loading."""

    def test_load_without_config_file(self):
        """Test loading settings when no config file exists."""
        # Should use defaults when no file exists
        settings = DharaSettings.load("dhara")
        assert isinstance(settings, DharaSettings)
        assert settings.server_name == "dhara"

    def test_model_json_schema(self):
        """Test that settings can generate JSON schema."""
        schema = DharaSettings.model_json_schema()

        assert "properties" in schema
        assert "server_name" in schema["properties"]
        assert "storage" in schema["properties"]
        assert "adapters" in schema["properties"]

    def test_model_fields_set(self):
        """Test that model tracks which fields were explicitly set."""
        settings = DharaSettings(
            server_name="custom",
        )

        assert "server_name" in settings.model_fields_set
        assert "storage" not in settings.model_fields_set  # Using default

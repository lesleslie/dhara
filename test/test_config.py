"""Tests for Druva configuration management."""

import pytest
from pathlib import Path
from tempfile import mktemp
import yaml

from dhara.config import (
    DruvaConfig,
    StorageConfig,
    CacheConfig,
    ConnectionConfig,
    load_config,
    load_config_from_env,
    save_config,
    merge_configs,
)

# Backward compatibility alias
DurusConfig = DruvaConfig


class TestStorageConfig:
    """Tests for StorageConfig."""

    def test_default_storage_config(self):
        """Test default storage configuration."""
        config = StorageConfig()
        assert config.backend == "memory"
        assert config.host == "localhost"
        assert config.port == 2972
        assert config.read_only is False

    def test_file_backend_requires_path(self):
        """Test that file backend requires path."""
        with pytest.raises(ValueError, match="File storage requires 'path'"):
            StorageConfig(backend="file")

    def test_file_backend_with_path(self):
        """Test file backend with path."""
        config = StorageConfig(backend="file", path="/tmp/test.durus")
        assert config.backend == "file"
        assert config.path == Path("/tmp/test.durus")

    def test_path_string_conversion(self):
        """Test that path strings are converted to Path objects."""
        config = StorageConfig(backend="file", path="/tmp/test.durus")
        assert isinstance(config.path, Path)
        assert str(config.path) == "/tmp/test.durus"

    def test_memory_backend_no_path_required(self):
        """Test that memory backend doesn't require path."""
        config = StorageConfig(backend="memory")
        assert config.backend == "memory"
        assert config.path is None

    def test_client_backend_configuration(self):
        """Test client backend configuration."""
        config = StorageConfig(
            backend="client", host="example.com", port=8080
        )
        assert config.backend == "client"
        assert config.host == "example.com"
        assert config.port == 8080

    def test_invalid_port_raises_error(self):
        """Test that invalid port raises error."""
        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            StorageConfig(port=0)

        with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
            StorageConfig(port=70000)

    def test_sqlite_backend_requires_path(self):
        """Test that sqlite backend requires path."""
        with pytest.raises(ValueError, match="Sqlite storage requires 'path'"):
            StorageConfig(backend="sqlite")


class TestCacheConfig:
    """Tests for CacheConfig."""

    def test_default_cache_config(self):
        """Test default cache configuration."""
        config = CacheConfig()
        assert config.size == 100000
        assert config.shrink_threshold == 2.0
        assert config.enabled is True

    def test_custom_cache_config(self):
        """Test custom cache configuration."""
        config = CacheConfig(size=50000, shrink_threshold=1.5)
        assert config.size == 50000
        assert config.shrink_threshold == 1.5

    def test_negative_size_raises_error(self):
        """Test that negative size raises error."""
        with pytest.raises(ValueError, match="Cache size must be non-negative"):
            CacheConfig(size=-1)

    def test_invalid_shrink_threshold_raises_error(self):
        """Test that invalid shrink threshold raises error."""
        with pytest.raises(
            ValueError, match="Shrink threshold must be >= 1.0"
        ):
            CacheConfig(shrink_threshold=0.5)


class TestConnectionConfig:
    """Tests for ConnectionConfig."""

    def test_default_connection_config(self):
        """Test default connection configuration."""
        config = ConnectionConfig()
        assert config.timeout == 30.0
        assert config.max_retries == 3
        assert config.retry_delay == 1.0

    def test_custom_connection_config(self):
        """Test custom connection configuration."""
        config = ConnectionConfig(timeout=60.0, max_retries=5)
        assert config.timeout == 60.0
        assert config.max_retries == 5

    def test_invalid_timeout_raises_error(self):
        """Test that invalid timeout raises error."""
        with pytest.raises(ValueError, match="Timeout must be positive"):
            ConnectionConfig(timeout=0)

    def test_negative_retries_raises_error(self):
        """Test that negative retries raises error."""
        with pytest.raises(ValueError, match="Max retries must be non-negative"):
            ConnectionConfig(max_retries=-1)


class TestDruvaConfig:
    """Tests for DruvaConfig."""

    def test_default_druva_config(self):
        """Test default Druva configuration."""
        config = DruvaConfig()
        assert config.storage.backend == "memory"
        assert config.cache.size == 100000
        assert config.connection.timeout == 30.0
        assert config.debug_mode is False

    def test_custom_druva_config(self):
        """Test custom Druva configuration."""
        storage = StorageConfig(backend="memory")
        cache = CacheConfig(size=50000)
        config = DruvaConfig(storage=storage, cache=cache, debug_mode=True)

        assert config.storage.backend == "memory"
        assert config.cache.size == 50000
        assert config.debug_mode is True

    # Backward compatibility - test old name still works
    def test_durus_config_alias(self):
        """Test that DurusConfig alias works for backward compatibility."""
        config = DurusConfig()
        assert isinstance(config, DruvaConfig)
        assert config.storage.backend == "memory"

    def test_to_dict(self):
        """Test converting configuration to dictionary."""
        config = DruvaConfig(
            storage=StorageConfig(backend="memory"),
            cache=CacheConfig(size=50000),
        )
        data = config.to_dict()

        assert data["storage"]["backend"] == "memory"
        assert data["cache"]["size"] == 50000
        assert data["connection"]["timeout"] == 30.0

    def test_from_dict(self):
        """Test creating configuration from dictionary."""
        data = {
            "storage": {"backend": "memory", "path": None},
            "cache": {"size": 75000, "shrink_threshold": 2.0, "enabled": True},
            "connection": {"timeout": 30.0, "max_retries": 3, "retry_delay": 1.0},
            "debug_mode": False,
        }
        config = DruvaConfig.from_dict(data)

        assert config.storage.backend == "memory"
        assert config.cache.size == 75000

    def test_from_dict_with_path_string(self):
        """Test creating configuration from dictionary with path string."""
        data = {
            "storage": {"backend": "file", "path": "/tmp/test.dhara"},
        }
        config = DruvaConfig.from_dict(data)

        assert isinstance(config.storage.path, Path)
        assert str(config.storage.path) == "/tmp/test.dhara"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_from_dict(self):
        """Test loading configuration from dictionary."""
        data = {"storage": {"backend": "memory"}}
        config = load_config(data)
        assert config.storage.backend == "memory"

    def test_load_config_from_yaml_file(self):
        """Test loading configuration from YAML file."""
        # Create temporary YAML config file
        config_data = {
            "storage": {
                "backend": "file",
                "path": "/tmp/test.durus",
            },
            "cache": {
                "size": 50000,
            },
        }

        config_file = mktemp(suffix=".yaml")
        try:
            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            config = load_config(config_file)
            assert config.storage.backend == "file"
            assert config.cache.size == 50000
        finally:
            Path(config_file).unlink(missing_ok=True)

    def test_load_config_auto_detect_yaml(self):
        """Test auto-detection of YAML format."""
        config_data = {"storage": {"backend": "memory"}}
        config_file = mktemp(suffix=".yml")

        try:
            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            config = load_config(config_file)
            assert config.storage.backend == "memory"
        finally:
            Path(config_file).unlink(missing_ok=True)

    def test_load_config_nonexistent_file(self):
        """Test loading from non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_load_config_invalid_yaml(self):
        """Test loading invalid YAML raises error."""
        config_file = mktemp(suffix=".yaml")
        try:
            with open(config_file, "w") as f:
                f.write("invalid: yaml: content: [")

            with pytest.raises(yaml.YAMLError):
                load_config(config_file)
        finally:
            Path(config_file).unlink(missing_ok=True)

    def test_load_config_unknown_format(self):
        """Test loading config with unknown extension."""
        config_file = mktemp(suffix=".unknown")
        Path(config_file).write_text("{}")

        with pytest.raises(ValueError, match="Cannot detect format"):
            load_config(config_file)

        Path(config_file).unlink(missing_ok=True)


class TestLoadConfigFromEnv:
    """Tests for load_config_from_env function."""

    def test_load_config_from_env_no_env_var(self):
        """Test when no environment variable is set."""
        import os

        # Ensure env var is not set
        if "DURUS_CONFIG" in os.environ:
            del os.environ["DURUS_CONFIG"]

        config = load_config_from_env()
        assert config is None

    def test_load_config_from_env_with_file(self):
        """Test loading from environment variable."""
        import os

        # Create temporary config file
        config_data = {"storage": {"backend": "memory"}}
        config_file = mktemp(suffix=".yaml")

        try:
            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            # Set environment variable
            os.environ["DURUS_CONFIG"] = config_file

            config = load_config_from_env()
            assert config is not None
            assert config.storage.backend == "memory"
        finally:
            if "DURUS_CONFIG" in os.environ:
                del os.environ["DURUS_CONFIG"]
            Path(config_file).unlink(missing_ok=True)

    def test_load_config_from_env_with_overrides(self):
        """Test environment variable overrides."""
        import os

        # Create temporary config file
        config_data = {"storage": {"backend": "memory"}}
        config_file = mktemp(suffix=".yaml")

        try:
            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            os.environ["DURUS_CONFIG"] = config_file
            os.environ["DURUS_CACHE_SIZE"] = "75000"
            os.environ["DURUS_DEBUG"] = "1"

            config = load_config_from_env()
            assert config is not None
            assert config.cache.size == 75000
            assert config.debug_mode is True
        finally:
            for key in ["DURUS_CONFIG", "DURUS_CACHE_SIZE", "DURUS_DEBUG"]:
                if key in os.environ:
                    del os.environ[key]
            Path(config_file).unlink(missing_ok=True)


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config_yaml(self):
        """Test saving configuration to YAML file."""
        config = DruvaConfig(
            storage=StorageConfig(backend="memory"),
            cache=CacheConfig(size=50000),
        )
        config_file = mktemp(suffix=".yaml")

        try:
            save_config(config, config_file, format="yaml")
            assert Path(config_file).exists()

            # Verify content
            loaded = load_config(config_file)
            assert loaded.storage.backend == "memory"
            assert loaded.cache.size == 50000
        finally:
            Path(config_file).unlink(missing_ok=True)

    def test_save_config_creates_directory(self):
        """Test that save_config creates parent directories."""
        import tempfile
        import shutil

        # Create a temp directory for our test
        temp_dir = tempfile.mkdtemp()
        config_file = Path(temp_dir) / "subdir" / "config.yaml"

        try:
            config = DruvaConfig()
            save_config(config, config_file)
            assert config_file.exists()
        finally:
            # Clean up
            shutil.rmtree(temp_dir)


class TestMergeConfigs:
    """Tests for merge_configs function."""

    def test_merge_empty_configs(self):
        """Test merging no configs returns default."""
        config = merge_configs()
        assert isinstance(config, DruvaConfig)
        assert config.storage.backend == "memory"

    def test_merge_single_config(self):
        """Test merging single config."""
        config1 = DruvaConfig(storage=StorageConfig(backend="memory"))
        result = merge_configs(config1)
        assert result.storage.backend == "memory"

    def test_merge_multiple_configs(self):
        """Test merging multiple configs."""
        config1 = DruvaConfig(
            storage=StorageConfig(backend="file", path="/tmp/test.dhara"),
            cache=CacheConfig(size=100000),
        )
        config2 = DruvaConfig(
            storage=StorageConfig(backend="client"),
            cache=CacheConfig(size=50000),
        )

        result = merge_configs(config1, config2)
        assert result.storage.backend == "client"  # Overridden by config2
        assert result.cache.size == 50000  # Overridden by config2

    def test_merge_partial_override(self):
        """Test merging with partial overrides."""
        config1 = DruvaConfig(
            storage=StorageConfig(backend="file", path="/tmp/test.dhara"),
            cache=CacheConfig(size=100000),
        )
        config2 = DruvaConfig(
            cache=CacheConfig(size=50000),
        )

        result = merge_configs(config1, config2)
        assert result.storage.backend == "file"  # Not overridden
        assert result.cache.size == 50000  # Overridden

    def test_merge_debug_mode(self):
        """Test merging debug mode."""
        config1 = DruvaConfig(debug_mode=False)
        config2 = DruvaConfig(debug_mode=True)

        result = merge_configs(config1, config2)
        assert result.debug_mode is True

    def test_merge_preserves_original(self):
        """Test that merge doesn't modify original configs."""
        config1 = DruvaConfig(cache=CacheConfig(size=100000))
        config2 = DruvaConfig(cache=CacheConfig(size=50000))

        result = merge_configs(config1, config2)

        # Original configs should be unchanged
        assert config1.cache.size == 100000
        assert config2.cache.size == 50000
        assert result.cache.size == 50000

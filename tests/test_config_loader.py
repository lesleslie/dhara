"""Tests for configuration loader.

Tests load_config, load_config_from_env, save_config, and merge_configs
from dhara.config.loader. Covers YAML/JSON loading, env overrides,
path traversal protection, and size limits.
"""

import json
import os
from pathlib import Path

import pytest
import yaml

from dhara.config.defaults import (
    CacheConfig,
    ConnectionConfig,
    DharaConfig,
    StorageConfig,
)
from dhara.config.loader import (
    MAX_CACHE_SIZE,
    MAX_CONFIG_SIZE,
    MIN_PORT,
    MAX_PORT,
    VALID_STORAGE_BACKENDS,
    _env_prefix_candidates,
    _get_env_value,
    load_config,
    load_config_from_env,
    merge_configs,
    save_config,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def yaml_config_file(tmp_path):
    """Create a valid YAML config file."""
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump({
            "storage": {"backend": "memory"},
            "cache": {"size": 5000},
            "debug_mode": True,
        })
    )
    return path


@pytest.fixture
def json_config_file(tmp_path):
    """Create a valid JSON config file."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "storage": {"backend": "memory"},
        "cache": {"size": 3000},
    }))
    return path


# ============================================================================
# _env_prefix_candidates / _get_env_value
# ============================================================================


class TestEnvHelpers:
    """Tests for internal env helper functions."""

    def test_dhara_prefix_includes_legacy(self):
        result = _env_prefix_candidates("DHARA")
        assert result == ("DHARA", "DRUVA", "DURUS")

    def test_other_prefix_no_legacy(self):
        result = _env_prefix_candidates("CUSTOM")
        assert result == ("CUSTOM",)

    def test_get_env_value_dhara_preferred(self, monkeypatch):
        monkeypatch.setenv("DHARA_MODE", "lite")
        monkeypatch.setenv("DRUVA_MODE", "standard")
        assert _get_env_value(("DHARA", "DRUVA"), "MODE") == "lite"

    def test_get_env_value_falls_to_druva(self, monkeypatch):
        monkeypatch.delenv("DHARA_MODE", raising=False)
        monkeypatch.setenv("DRUVA_MODE", "standard")
        assert _get_env_value(("DHARA", "DRUVA"), "MODE") == "standard"

    def test_get_env_value_none_when_missing(self, monkeypatch):
        monkeypatch.delenv("DHARA_MODE", raising=False)
        monkeypatch.delenv("DRUVA_MODE", raising=False)
        assert _get_env_value(("DHARA", "DRUVA"), "MODE") is None


# ============================================================================
# load_config
# ============================================================================


class TestLoadConfig:
    """Tests for load_config function."""

    def test_from_dict(self):
        cfg = load_config({"storage": {"backend": "memory"}})
        assert isinstance(cfg, DharaConfig)
        assert cfg.storage.backend == "memory"

    def test_from_dict_empty(self):
        cfg = load_config({})
        assert cfg.storage.backend == "memory"

    def test_from_yaml_file(self, yaml_config_file):
        cfg = load_config(yaml_config_file)
        assert cfg.storage.backend == "memory"
        assert cfg.cache.size == 5000
        assert cfg.debug_mode is True

    def test_from_json_file(self, json_config_file):
        cfg = load_config(json_config_file)
        assert cfg.storage.backend == "memory"
        assert cfg.cache.size == 3000

    def test_auto_detect_yaml_extension(self, yaml_config_file):
        cfg = load_config(yaml_config_file, format="auto")
        assert cfg.storage.backend == "memory"

    def test_auto_detect_yml_extension(self, tmp_path):
        path = tmp_path / "config.yml"
        path.write_text(yaml.dump({"storage": {"backend": "memory"}}))
        cfg = load_config(path)
        assert cfg.storage.backend == "memory"

    def test_auto_detect_json_extension(self, json_config_file):
        cfg = load_config(json_config_file, format="auto")
        assert cfg.storage.backend == "memory"

    def test_explicit_yaml_format(self, yaml_config_file):
        cfg = load_config(yaml_config_file, format="yaml")
        assert isinstance(cfg, DharaConfig)

    def test_explicit_json_format(self, json_config_file):
        cfg = load_config(json_config_file, format="json")
        assert isinstance(cfg, DharaConfig)

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_config("/nonexistent/config.yaml")

    def test_oversized_file_raises(self, tmp_path):
        path = tmp_path / "big.yaml"
        path.write_text("x" * (MAX_CONFIG_SIZE + 1))
        with pytest.raises(ValueError, match="too large"):
            load_config(path, max_size=100)

    def test_unknown_extension_raises(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("mode = lite")
        with pytest.raises(ValueError, match="Cannot detect format"):
            load_config(path)

    def test_unsupported_format_raises(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("mode: lite")
        with pytest.raises(ValueError, match="Unsupported format"):
            load_config(path, format="toml")

    def test_invalid_yaml_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(":\n  - invalid\n: yaml")
        with pytest.raises(yaml.YAMLError):
            load_config(path)

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json}")
        with pytest.raises(ValueError, match="Failed to parse JSON"):
            load_config(path)

    def test_yaml_with_non_dict_raises(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text(yaml.dump(["item1", "item2"]))
        with pytest.raises(ValueError, match="must contain a dictionary"):
            load_config(path)

    def test_json_with_non_dict_raises(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text(json.dumps(["item1", "item2"]))
        with pytest.raises(ValueError, match="must contain a dictionary"):
            load_config(path)


# ============================================================================
# load_config_from_env
# ============================================================================


class TestLoadConfigFromEnv:
    """Tests for load_config_from_env function."""

    def test_returns_none_when_no_config_var(self, monkeypatch):
        monkeypatch.delenv("DHARA_CONFIG", raising=False)
        monkeypatch.delenv("DRUVA_CONFIG", raising=False)
        assert load_config_from_env() is None

    def test_loads_from_dhara_config_env(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        cfg = load_config_from_env()
        assert cfg is not None
        assert cfg.storage.backend == "memory"

    def test_loads_from_druva_config_env(self, yaml_config_file, monkeypatch):
        monkeypatch.delenv("DHARA_CONFIG", raising=False)
        monkeypatch.setenv("DRUVA_CONFIG", str(yaml_config_file))
        cfg = load_config_from_env()
        assert cfg is not None

    def test_dhara_preferred_over_druva(self, yaml_config_file, json_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DRUVA_CONFIG", str(json_config_file))
        cfg = load_config_from_env()
        assert cfg.cache.size == 5000  # YAML has 5000, JSON has 3000

    def test_env_overrides_backend(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_STORAGE_BACKEND", "file")
        monkeypatch.setenv("DHARA_STORAGE_PATH", "/tmp/test.dhara")
        cfg = load_config_from_env()
        assert cfg.storage.backend == "file"

    def test_invalid_backend_raises(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_STORAGE_BACKEND", "invalid")
        with pytest.raises(ValueError, match="Invalid.*STORAGE_BACKEND"):
            load_config_from_env()

    def test_path_traversal_rejected(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_STORAGE_PATH", "/etc/../../etc/passwd")
        with pytest.raises(ValueError, match="Path traversal"):
            load_config_from_env()

    def test_tilde_path_rejected(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_STORAGE_PATH", "~/secret")
        with pytest.raises(ValueError, match="Home directory"):
            load_config_from_env()

    def test_port_override(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_STORAGE_PORT", "8080")
        cfg = load_config_from_env()
        assert cfg.storage.port == 8080

    def test_invalid_port_type_raises(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_STORAGE_PORT", "abc")
        with pytest.raises(TypeError, match="must be an integer"):
            load_config_from_env()

    def test_port_out_of_range_raises(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_STORAGE_PORT", "99999")
        with pytest.raises(ValueError, match="Must be between"):
            load_config_from_env()

    def test_cache_size_override(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_CACHE_SIZE", "1000")
        cfg = load_config_from_env()
        assert cfg.cache.size == 1000

    def test_negative_cache_size_raises(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_CACHE_SIZE", "-1")
        with pytest.raises(ValueError, match="non-negative"):
            load_config_from_env()

    def test_too_large_cache_size_raises(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_CACHE_SIZE", str(MAX_CACHE_SIZE + 1))
        with pytest.raises(ValueError, match="too large"):
            load_config_from_env()

    def test_debug_true_values(self, yaml_config_file, monkeypatch):
        for val in ["1", "true", "yes", "on", "enabled"]:
            monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
            monkeypatch.setenv("DHARA_DEBUG", val)
            cfg = load_config_from_env()
            assert cfg.debug_mode is True

    def test_debug_false_values(self, yaml_config_file, monkeypatch):
        for val in ["0", "false", "no", "off", "disabled"]:
            monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
            monkeypatch.setenv("DHARA_DEBUG", val)
            cfg = load_config_from_env()
            assert cfg.debug_mode is False

    def test_debug_invalid_value_raises(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_DEBUG", "maybe")
        with pytest.raises(ValueError, match="Invalid.*DEBUG"):
            load_config_from_env()

    def test_empty_host_raises(self, yaml_config_file, monkeypatch):
        monkeypatch.setenv("DHARA_CONFIG", str(yaml_config_file))
        monkeypatch.setenv("DHARA_STORAGE_HOST", "  ")
        with pytest.raises(ValueError, match="cannot be empty"):
            load_config_from_env()


# ============================================================================
# save_config
# ============================================================================


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_yaml(self, tmp_path):
        cfg = DharaConfig()
        path = tmp_path / "saved" / "config.yaml"
        save_config(cfg, path)
        assert path.exists()
        data = yaml.safe_load(path.read_text())
        assert data["debug_mode"] is False

    def test_save_json(self, tmp_path):
        cfg = DharaConfig()
        path = tmp_path / "saved" / "config.json"
        save_config(cfg, path, format="json")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["debug_mode"] is False

    def test_save_creates_parent_dirs(self, tmp_path):
        cfg = DharaConfig()
        path = tmp_path / "deeply" / "nested" / "config.yaml"
        save_config(cfg, path)
        assert path.exists()

    def test_unsupported_format_raises(self, tmp_path):
        cfg = DharaConfig()
        with pytest.raises(ValueError, match="Unsupported format"):
            save_config(cfg, tmp_path / "config.toml", format="toml")


# ============================================================================
# merge_configs
# ============================================================================


class TestMergeConfigs:
    """Tests for merge_configs function."""

    def test_empty_returns_default(self):
        cfg = merge_configs()
        assert cfg.storage.backend == "memory"

    def test_single_config_returns_copy(self):
        original = DharaConfig()
        merged = merge_configs(original)
        assert merged.storage.backend == "memory"
        # Verify it's a copy
        assert merged is not original

    def test_later_config_overrides_earlier(self, tmp_path):
        base = DharaConfig()
        override = DharaConfig(
            storage=StorageConfig(backend="file", path=tmp_path / "test.dhara"),
        )
        merged = merge_configs(base, override)
        assert merged.storage.backend == "file"

    def test_three_way_merge(self, tmp_path):
        cfg1 = DharaConfig(
            storage=StorageConfig(backend="file", path=tmp_path / "test.dhara"),
        )
        cfg2 = DharaConfig(cache=CacheConfig(size=2000))
        cfg3 = DharaConfig(debug_mode=True)
        merged = merge_configs(cfg1, cfg2, cfg3)
        assert merged.storage.backend == "file"
        assert merged.cache.size == 2000
        assert merged.debug_mode is True

    def test_original_not_mutated(self, tmp_path):
        original = DharaConfig()
        override = DharaConfig(debug_mode=True)
        merge_configs(original, override)
        assert original.debug_mode is False

    def test_connection_override(self):
        cfg1 = DharaConfig()
        cfg2 = DharaConfig(connection=ConnectionConfig(timeout=99.0))
        merged = merge_configs(cfg1, cfg2)
        assert merged.connection.timeout == 99.0

    def test_read_only_override(self):
        cfg1 = DharaConfig()
        cfg2 = DharaConfig(storage=StorageConfig(read_only=True))
        merged = merge_configs(cfg1, cfg2)
        assert merged.storage.read_only is True

    def test_cache_disabled_override(self):
        cfg1 = DharaConfig()
        cfg2 = DharaConfig(cache=CacheConfig(enabled=False))
        merged = merge_configs(cfg1, cfg2)
        assert merged.cache.enabled is False


# ============================================================================
# Module constants
# ============================================================================


class TestModuleConstants:
    """Tests for loader module-level constants."""

    def test_max_config_size_is_10mb(self):
        assert MAX_CONFIG_SIZE == 10 * 1024 * 1024

    def test_valid_storage_backends(self):
        assert "file" in VALID_STORAGE_BACKENDS
        assert "sqlite" in VALID_STORAGE_BACKENDS
        assert "memory" in VALID_STORAGE_BACKENDS

    def test_port_range(self):
        assert MIN_PORT == 1
        assert MAX_PORT == 65535

    def test_max_cache_size(self):
        assert MAX_CACHE_SIZE == 1_000_000_000

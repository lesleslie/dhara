"""Tests for Dhara configuration defaults (dataclass-based).

Tests the StorageConfig, CacheConfig, ConnectionConfig, and DharaConfig
dataclasses from dhara.config.defaults, covering defaults, validation,
serialization, and backward compatibility.
"""

from pathlib import Path

import pytest

from dhara.config.defaults import (
    CacheConfig,
    ConnectionConfig,
    DharaConfig,
    StorageConfig,
)


# ============================================================================
# StorageConfig
# ============================================================================


class TestStorageConfig:
    """Tests for StorageConfig dataclass."""

    def test_default_backend_is_memory(self):
        cfg = StorageConfig()
        assert cfg.backend == "memory"

    def test_default_host(self):
        cfg = StorageConfig()
        assert cfg.host == "localhost"

    def test_default_port(self):
        cfg = StorageConfig()
        assert cfg.port == 2972

    def test_default_read_only(self):
        cfg = StorageConfig()
        assert cfg.read_only is False

    def test_default_path_is_none(self):
        cfg = StorageConfig()
        assert cfg.path is None

    @pytest.mark.parametrize("backend", ["file", "sqlite", "client", "memory"])
    def test_valid_backends(self, backend):
        if backend == "memory":
            cfg = StorageConfig(backend=backend)
        else:
            cfg = StorageConfig(backend=backend, path="/tmp/test")
        assert cfg.backend == backend

    def test_file_backend_requires_path(self):
        with pytest.raises(ValueError, match="requires 'path'"):
            StorageConfig(backend="file")

    def test_sqlite_backend_requires_path(self):
        with pytest.raises(ValueError, match="requires 'path'"):
            StorageConfig(backend="sqlite")

    def test_client_backend_requires_no_path(self):
        cfg = StorageConfig(backend="client")
        assert cfg.backend == "client"

    def test_string_path_converted_to_pathlib(self, tmp_path):
        cfg = StorageConfig(backend="file", path=str(tmp_path / "test.dhara"))
        assert isinstance(cfg.path, Path)

    def test_pathlib_path_accepted(self, tmp_path):
        path = tmp_path / "test.dhara"
        cfg = StorageConfig(backend="file", path=path)
        assert cfg.path == path

    @pytest.mark.parametrize("port", [0, -1, 65536, 100000])
    def test_invalid_port_raises(self, port):
        with pytest.raises(ValueError, match="Port must be between"):
            StorageConfig(backend="memory", port=port)

    def test_port_boundaries_accepted(self):
        cfg = StorageConfig(backend="memory", port=1)
        assert cfg.port == 1
        cfg2 = StorageConfig(backend="memory", port=65535)
        assert cfg2.port == 65535


# ============================================================================
# CacheConfig
# ============================================================================


class TestCacheConfig:
    """Tests for CacheConfig dataclass."""

    def test_default_size(self):
        cfg = CacheConfig()
        assert cfg.size == 100000

    def test_default_shrink_threshold(self):
        cfg = CacheConfig()
        assert cfg.shrink_threshold == 2.0

    def test_default_enabled(self):
        cfg = CacheConfig()
        assert cfg.enabled is True

    def test_negative_size_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            CacheConfig(size=-1)

    def test_zero_size_allowed(self):
        cfg = CacheConfig(size=0)
        assert cfg.size == 0

    def test_shrink_threshold_below_one_raises(self):
        with pytest.raises(ValueError, match=">= 1.0"):
            CacheConfig(shrink_threshold=0.9)

    def test_shrink_threshold_one_allowed(self):
        cfg = CacheConfig(shrink_threshold=1.0)
        assert cfg.shrink_threshold == 1.0

    def test_custom_values(self):
        cfg = CacheConfig(size=50000, shrink_threshold=1.5, enabled=False)
        assert cfg.size == 50000
        assert cfg.shrink_threshold == 1.5
        assert cfg.enabled is False


# ============================================================================
# ConnectionConfig
# ============================================================================


class TestConnectionConfig:
    """Tests for ConnectionConfig dataclass."""

    def test_default_timeout(self):
        cfg = ConnectionConfig()
        assert cfg.timeout == 30.0

    def test_default_max_retries(self):
        cfg = ConnectionConfig()
        assert cfg.max_retries == 3

    def test_default_retry_delay(self):
        cfg = ConnectionConfig()
        assert cfg.retry_delay == 1.0

    def test_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="positive"):
            ConnectionConfig(timeout=0)

    def test_negative_timeout_raises(self):
        with pytest.raises(ValueError, match="positive"):
            ConnectionConfig(timeout=-1)

    def test_negative_retries_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            ConnectionConfig(max_retries=-1)

    def test_zero_retries_allowed(self):
        cfg = ConnectionConfig(max_retries=0)
        assert cfg.max_retries == 0

    def test_negative_retry_delay_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            ConnectionConfig(retry_delay=-0.1)

    def test_zero_retry_delay_allowed(self):
        cfg = ConnectionConfig(retry_delay=0)
        assert cfg.retry_delay == 0

    def test_custom_values(self):
        cfg = ConnectionConfig(timeout=60.0, max_retries=5, retry_delay=2.5)
        assert cfg.timeout == 60.0
        assert cfg.max_retries == 5
        assert cfg.retry_delay == 2.5


# ============================================================================
# DharaConfig
# ============================================================================


class TestDharaConfig:
    """Tests for DharaConfig dataclass."""

    def test_defaults(self):
        cfg = DharaConfig()
        assert cfg.storage.backend == "memory"
        assert cfg.cache.size == 100000
        assert cfg.connection.timeout == 30.0
        assert cfg.debug_mode is False

    def test_custom_subconfigs(self, tmp_path):
        storage = StorageConfig(backend="file", path=tmp_path / "test.dhara")
        cache = CacheConfig(size=5000)
        conn = ConnectionConfig(timeout=10.0)
        cfg = DharaConfig(
            storage=storage, cache=cache, connection=conn, debug_mode=True,
        )
        assert cfg.storage.backend == "file"
        assert cfg.cache.size == 5000
        assert cfg.connection.timeout == 10.0
        assert cfg.debug_mode is True

    def test_to_dict(self, tmp_path):
        storage = StorageConfig(backend="file", path=tmp_path / "test.dhara")
        cfg = DharaConfig(storage=storage)
        d = cfg.to_dict()
        assert d["storage"]["backend"] == "file"
        assert d["cache"]["size"] == 100000
        assert d["connection"]["timeout"] == 30.0
        assert d["debug_mode"] is False

    def test_to_dict_path_as_string(self, tmp_path):
        path = tmp_path / "test.dhara"
        cfg = DharaConfig(storage=StorageConfig(backend="file", path=path))
        d = cfg.to_dict()
        assert isinstance(d["storage"]["path"], str)

    def test_from_dict(self, tmp_path):
        data = {
            "storage": {"backend": "file", "path": str(tmp_path / "test.dhara")},
            "cache": {"size": 2000},
            "connection": {"timeout": 60.0},
            "debug_mode": True,
        }
        cfg = DharaConfig.from_dict(data)
        assert cfg.storage.backend == "file"
        assert cfg.cache.size == 2000
        assert cfg.connection.timeout == 60.0
        assert cfg.debug_mode is True

    def test_from_dict_defaults_for_missing_keys(self, tmp_path):
        data = {"storage": {"backend": "file", "path": str(tmp_path / "test.dhara")}}
        cfg = DharaConfig.from_dict(data)
        assert cfg.cache.size == 100000
        assert cfg.connection.timeout == 30.0
        assert cfg.debug_mode is False

    def test_from_dict_accepts_empty_dict(self):
        cfg = DharaConfig.from_dict({})
        assert cfg.storage.backend == "memory"
        assert cfg.debug_mode is False

    def test_dict_init_with_dict_subconfigs(self, tmp_path):
        cfg = DharaConfig(
            storage={"backend": "file", "path": str(tmp_path / "test.dhara")},
            cache={"size": 500},
        )
        assert cfg.storage.backend == "file"
        assert cfg.cache.size == 500

    def test_legacy_alias(self):
        from dhara.config.defaults import DruvaConfig

        assert DruvaConfig is DharaConfig

    def test_roundtrip_to_dict_from_dict(self, tmp_path):
        original = DharaConfig(
            storage=StorageConfig(backend="file", path=tmp_path / "test.dhara"),
            cache=CacheConfig(size=42),
        )
        d = original.to_dict()
        restored = DharaConfig.from_dict(d)
        assert restored.storage.backend == original.storage.backend
        assert restored.cache.size == original.cache.size
        assert restored.connection.timeout == original.connection.timeout

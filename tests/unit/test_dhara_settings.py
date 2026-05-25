"""Tests for DharaSettings storage and cache backend configuration."""

from __future__ import annotations

import pytest
from dhara.core.config import DharaSettings


class TestDharaSettingsBackendConfig:
    def test_storage_backend_defaults_to_file(self):
        settings = DharaSettings()
        assert settings.storage_backend == "file"

    def test_cache_backend_defaults_to_memory(self):
        settings = DharaSettings()
        assert settings.cache_backend == "memory"

    def test_pg_url_empty_by_default(self):
        settings = DharaSettings()
        assert settings.storage_pg_url == ""

    def test_redis_url_empty_by_default(self):
        settings = DharaSettings()
        assert settings.cache_redis_url == ""

    def test_cache_ttl_defaults_to_3600(self):
        settings = DharaSettings()
        assert settings.cache_ttl == 3600

    def test_stampede_jitter_defaults_to_0(self):
        settings = DharaSettings()
        assert settings.cache_stampede_jitter_ms == 0

    def test_env_overrides_storage_backend(self, monkeypatch):
        monkeypatch.setenv("DHARA_STORAGE_BACKEND", "postgres")
        settings = DharaSettings.load()
        assert settings.storage_backend == "postgres"

    def test_env_overrides_pg_url(self, monkeypatch):
        monkeypatch.setenv("DHARA_STORAGE_PG_URL", "postgresql://user:pass@localhost:5432/dhara")
        settings = DharaSettings.load()
        assert settings.storage_pg_url == "postgresql://user:pass@localhost:5432/dhara"

    def test_env_overrides_cache_backend(self, monkeypatch):
        monkeypatch.setenv("DHARA_CACHE_BACKEND", "redis")
        settings = DharaSettings.load()
        assert settings.cache_backend == "redis"
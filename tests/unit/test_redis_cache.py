# tests/unit/test_redis_cache.py
from __future__ import annotations

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from dhara.storage.redis_cache import RedisCacheAdapter, RedisCacheSettings


class TestRedisCacheAdapterClear:
    @pytest.mark.asyncio
    async def test_clear_deletes_all_prefixed_keys(self):
        settings = RedisCacheSettings(key_prefix="dhara:cache:")
        adapter = RedisCacheAdapter(settings)
        mock_client = AsyncMock()

        # Create an async generator for scan_iter results
        async def mock_scan_iter(match):
            for key in ["dhara:cache:1", "dhara:cache:2"]:
                yield key

        mock_client.scan_iter = mock_scan_iter
        adapter._client = mock_client

        await adapter.clear()
        mock_client.delete.assert_any_call("dhara:cache:1")
        mock_client.delete.assert_any_call("dhara:cache:2")


class TestRedisCacheAdapterStampedeJitter:
    @pytest.mark.asyncio
    async def test_get_with_stampede_jitter_sleeps_before_returning_none(self):
        settings = RedisCacheSettings(stampede_jitter_ms=100)
        adapter = RedisCacheAdapter(settings)
        mock_client = AsyncMock()
        mock_client.get.return_value = None
        adapter._client = mock_client

        start = time.monotonic()
        result = await adapter.get("nonexistent_oid")
        elapsed_ms = (time.monotonic() - start) * 1000
        assert result is None
        assert elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_get_with_zero_stampede_jitter_does_not_sleep(self):
        settings = RedisCacheSettings(stampede_jitter_ms=0)
        adapter = RedisCacheAdapter(settings)
        mock_client = AsyncMock()
        mock_client.get.return_value = None
        adapter._client = mock_client

        start = time.monotonic()
        result = await adapter.get("nonexistent_oid")
        elapsed_ms = (time.monotonic() - start) * 1000
        assert result is None
        assert elapsed_ms < 50


class TestRedisCacheAdapterInit:
    def test_settings_default_ttl_is_3600(self):
        settings = RedisCacheSettings()
        assert settings.ttl == 3600

    def test_settings_requires_redis_url(self):
        settings = RedisCacheSettings()
        assert settings.redis_url == "redis://localhost:6379"

    def test_adapter_init_without_url_defaults(self):
        adapter = RedisCacheAdapter(RedisCacheSettings())
        assert adapter._in_transaction is False

    @pytest.mark.asyncio
    async def test_health_returns_true_when_redis_responds(self):
        settings = RedisCacheSettings()
        adapter = RedisCacheAdapter(settings)
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        adapter._client = mock_redis
        result = await adapter.health()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_returns_false_when_redis_down(self):
        settings = RedisCacheSettings()
        adapter = RedisCacheAdapter(settings)
        mock_redis = AsyncMock()
        mock_redis.ping.side_effect = OSError("connection refused")
        adapter._client = mock_redis
        result = await adapter.health()
        assert result is False
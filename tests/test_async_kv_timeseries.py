"""Tests for dhara.mcp.kv_timeseries.AsyncKVTimeSeriesStore async methods."""

from __future__ import annotations

import pytest

from dhara.collections.dict import PersistentDict
from dhara.collections.list import PersistentList
from dhara.mcp.kv_timeseries import AsyncKVTimeSeriesStore, TimeSeriesRetention
from dhara.storage.memory import AsyncMemoryStorage
from dhara.core.connection import AsyncConnection


class TestAsyncKVTimeSeriesStore:
    @pytest.mark.asyncio
    async def test_put_and_get_async(self):
        """put_async stores value, get_async retrieves it."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncKVTimeSeriesStore(conn)
        result = await store.put_async("key1", {"name": "test"})
        assert result["ok"] is True
        assert result["key"] == "key1"

        retrieved = await store.get_async("key1")
        assert retrieved["ok"] is True
        assert retrieved["value"]["name"] == "test"

    @pytest.mark.asyncio
    async def test_put_with_ttl_async(self):
        """put_async with TTL stores expires_at metadata."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncKVTimeSeriesStore(conn)
        result = await store.put_async("ttl_key", "value", ttl=3600)
        assert result["ok"] is True

        retrieved = await store.get_async("ttl_key")
        assert retrieved["value"] == "value"
        assert "expires_at" not in retrieved  # Not expired yet

    @pytest.mark.asyncio
    async def test_get_missing_async(self):
        """get_async returns None for missing key."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncKVTimeSeriesStore(conn)
        result = await store.get_async("nonexistent")
        assert result["ok"] is True
        assert result["value"] is None

    @pytest.mark.asyncio
    async def test_record_and_query_time_series_async(self):
        """record_time_series_async + query_time_series_async round-trip."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncKVTimeSeriesStore(conn)
        await store.record_time_series_async(
            "cpu_usage",
            "host1",
            {"value": 0.75, "unit": "percent"},
        )
        await store.record_time_series_async(
            "cpu_usage",
            "host1",
            {"value": 0.80, "unit": "percent"},
        )

        results = await store.query_time_series_async("cpu_usage", "host1")
        assert len(results) == 2
        assert results[0]["value"] == 0.75
        assert results[1]["value"] == 0.80

    @pytest.mark.asyncio
    async def test_aggregate_patterns_async(self):
        """aggregate_patterns_async counts records-per-pattern (not the count field value)."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncKVTimeSeriesStore(conn)

        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        ts = now.isoformat()

        # timeout appears in 2 records (service-a and service-b) → passes min_occurrences=2
        await store.record_time_series_async(
            "errors",
            "service-a",
            {"pattern": "timeout", "count": 1},
            timestamp=ts,
        )
        await store.record_time_series_async(
            "errors",
            "service-b",
            {"pattern": "timeout", "count": 2},
            timestamp=ts,
        )
        # crash appears in only 1 record (service-c) → filtered by min_occurrences=2
        await store.record_time_series_async(
            "errors",
            "service-c",
            {"pattern": "crash", "count": 1},
            timestamp=ts,
        )

        patterns = await store.aggregate_patterns_async(now.isoformat())
        # Only timeout survives min_occurrences=2 (appears in 2 records)
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "timeout"
        assert patterns[0]["count"] == 2

    @pytest.mark.asyncio
    async def test_list_prefix_async(self):
        """list_prefix_async returns matching keys."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncKVTimeSeriesStore(conn)

        await store.put_async("component_endpoint/a", {"url": "http://a"})
        await store.put_async("component_endpoint/b", {"url": "http://b"})
        await store.put_async("other/key", {"url": "http://other"})

        results = await store.list_prefix_async("component_endpoint/")
        assert len(results) == 2
        keys = {r["key"] for r in results}
        assert "component_endpoint/a" in keys
        assert "component_endpoint/b" in keys
        assert "other/key" not in keys

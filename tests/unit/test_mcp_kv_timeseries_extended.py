"""Extended tests for dhara/mcp/kv_timeseries.py — closes the gap from 89% to >=95%.

The existing coverage of `dhara/mcp/kv_timeseries.py` (89%) misses several
branches in the async store (``AsyncKVTimeSeriesStore``) and the sync
``list_prefix`` method. This file exercises every uncovered branch with
inline ``connection`` / ``async_connection`` fixtures (no project-wide
conftest dependency, so the file is self-contained under ``tests/unit/``).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from dhara.core.connection import AsyncConnection, Connection
from dhara.mcp.kv_timeseries import (
    AsyncKVTimeSeriesStore,
    KVTimeSeriesStore,
    TimeSeriesRetention,
    _parse_iso,
    _utcnow,
)
from dhara.storage.memory import AsyncMemoryStorage
from dhara.storage.base import MemoryStorage


# ---------------------------------------------------------------------------
# Inline fixtures (no tests/conftest.py dependency)
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_storage() -> MemoryStorage:
    """Fresh in-memory storage for each test."""
    return MemoryStorage()


@pytest.fixture
def connection(memory_storage: MemoryStorage) -> Connection:
    return Connection(memory_storage)


@pytest_asyncio.fixture
async def async_memory_storage() -> AsyncMemoryStorage:
    storage = AsyncMemoryStorage()
    await storage.init()
    return storage


@pytest_asyncio.fixture
async def async_connection(
    async_memory_storage: AsyncMemoryStorage,
) -> AsyncConnection:
    return await AsyncConnection.new(async_memory_storage)


def _ts(hours_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


# ---------------------------------------------------------------------------
# AsyncKVTimeSeriesStore - _ensure_root_async branch coverage
# ---------------------------------------------------------------------------


class TestAsyncEnsureRootBranches:
    @pytest.mark.asyncio
    async def test_ensure_root_creates_all_subdicts(
        self, async_connection: AsyncConnection
    ) -> None:
        """Lines 78->81 / 81->84 / 84->88: empty root -> all three subdicts created."""
        store = AsyncKVTimeSeriesStore(async_connection)
        # _ensure_root_async runs implicitly on first operation
        await store.put_async("k", "v")
        root = await async_connection.get_root()
        assert "kv" in root
        assert "kv_ttl" in root
        assert "time_series" in root

    @pytest.mark.asyncio
    async def test_ensure_root_idempotent_after_first_init(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 88->90: when no changes are needed the second init does not commit."""
        store = AsyncKVTimeSeriesStore(async_connection)
        await store.put_async("first", "v")
        # Second call must hit the early-return guard
        await store.put_async("second", "v")
        results = await store.get_async("first")
        assert results["value"] == "v"
        results2 = await store.get_async("second")
        assert results2["value"] == "v"

    @pytest.mark.asyncio
    async def test_ensure_root_second_instance_exercises_all_false_branches(
        self, async_connection: AsyncConnection
    ) -> None:
        """Lines 78->81 / 81->84 / 84->88 / 88->90: a fresh store against an
        already-populated root hits the False branch of every 'not in root'
        check and skips the commit."""
        store1 = AsyncKVTimeSeriesStore(async_connection)
        await store1.put_async("warmup", "v")  # populates kv / kv_ttl / time_series
        # Brand-new store instance — _initialized is False but root is populated
        store2 = AsyncKVTimeSeriesStore(async_connection)
        await store2.put_async("after", "v")
        assert (await store2.get_async("after"))["value"] == "v"
        assert (await store2.get_async("warmup"))["value"] == "v"

    @pytest.mark.asyncio
    async def test_async_store_accepts_custom_retention(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=7)
        )
        assert store.retention.retention_days == 7
        # Ensure it still works
        result = await store.put_async("k", "v")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# AsyncKVTimeSeriesStore.put_async - TTL clearing branch
# ---------------------------------------------------------------------------


class TestAsyncPutBranches:
    @pytest.mark.asyncio
    async def test_put_async_clears_existing_ttl(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 111: putting without TTL when key already has TTL clears it."""
        store = AsyncKVTimeSeriesStore(async_connection)
        await store.put_async("k", "v1", ttl=3600)
        result = await store.get_async("k")
        assert result["value"] == "v1"
        # Overwrite without TTL -> ttl_map entry removed
        await store.put_async("k", "v2")
        result2 = await store.get_async("k")
        assert result2["value"] == "v2"
        assert "expired" not in result2

    @pytest.mark.asyncio
    async def test_put_async_returns_dict(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(async_connection)
        result = await store.put_async("mykey", 42)
        assert isinstance(result, dict)
        assert result["ok"] is True
        assert result["key"] == "mykey"


# ---------------------------------------------------------------------------
# AsyncKVTimeSeriesStore.get_async - expired entry branch
# ---------------------------------------------------------------------------


class TestAsyncGetExpired:
    @pytest.mark.asyncio
    async def test_get_async_expired_lazy_deletion(
        self, async_connection: AsyncConnection
    ) -> None:
        """Lines 126-129: expired key -> delete + return expired=True."""
        store = AsyncKVTimeSeriesStore(async_connection)
        await store.put_async("ephemeral", "data", ttl=1)
        time.sleep(1.1)
        result = await store.get_async("ephemeral")
        assert result["ok"] is True
        assert result["value"] is None
        assert result["expired"] is True
        # Key removed by lazy deletion
        result2 = await store.get_async("ephemeral")
        assert result2["value"] is None
        assert "expired" not in result2

    @pytest.mark.asyncio
    async def test_get_async_missing_returns_none(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(async_connection)
        result = await store.get_async("nope")
        assert result["ok"] is True
        assert result["value"] is None


# ---------------------------------------------------------------------------
# AsyncKVTimeSeriesStore.list_prefix_async - TTL expiry branch
# ---------------------------------------------------------------------------


class TestAsyncListPrefix:
    @pytest.mark.asyncio
    async def test_list_prefix_skips_expired(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 144: expired TTL keys are excluded from prefix scan."""
        store = AsyncKVTimeSeriesStore(async_connection)
        await store.put_async("component_endpoint/a", {"url": "http://a"})
        await store.put_async("component_endpoint/b", {"url": "http://b"}, ttl=1)
        time.sleep(1.1)
        results = await store.list_prefix_async("component_endpoint/")
        keys = {r["key"] for r in results}
        assert "component_endpoint/a" in keys
        assert "component_endpoint/b" not in keys

    @pytest.mark.asyncio
    async def test_list_prefix_no_matches(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(async_connection)
        await store.put_async("other/key", 1)
        results = await store.list_prefix_async("nothing/")
        assert results == []


# ---------------------------------------------------------------------------
# AsyncKVTimeSeriesStore.record_time_series_async - record-with-data branch
# ---------------------------------------------------------------------------


class TestAsyncRecordTimeSeries:
    @pytest.mark.asyncio
    async def test_record_with_record_payload(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 172->174: payload.update(record) merges user-supplied dict."""
        store = AsyncKVTimeSeriesStore(async_connection)
        result = await store.record_time_series_async(
            "cpu",
            "host1",
            {"value": 0.85, "unit": "percent"},
        )
        assert result["ok"] is True
        assert result["metric_type"] == "cpu"
        assert result["entity_id"] == "host1"
        records = await store.query_time_series_async("cpu", "host1")
        assert len(records) == 1
        assert records[0]["value"] == 0.85
        assert records[0]["unit"] == "percent"

    @pytest.mark.asyncio
    async def test_record_without_record_payload(
        self, async_connection: AsyncConnection
    ) -> None:
        """When record is None, payload only contains 'ts'."""
        store = AsyncKVTimeSeriesStore(async_connection)
        await store.record_time_series_async("m", "e")
        records = await store.query_time_series_async("m", "e")
        assert len(records) == 1
        assert set(records[0].keys()) == {"ts"}


# ---------------------------------------------------------------------------
# AsyncKVTimeSeriesStore.query_time_series_async - filters and limits
# ---------------------------------------------------------------------------


class TestAsyncQueryTimeSeries:
    @pytest.mark.asyncio
    async def test_query_with_start_date_filter(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 197 / 199: retention and start_date filters together."""
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async(
            "m", "e", {"v": "old"}, timestamp=_ts(72)
        )
        await store.record_time_series_async(
            "m", "e", {"v": "new"}, timestamp=_ts(1)
        )
        results = await store.query_time_series_async("m", "e", start_date=_ts(48))
        assert len(results) == 1
        assert results[0]["v"] == "new"

    @pytest.mark.asyncio
    async def test_query_with_limit(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 203: limit slicing keeps only the trailing N items."""
        store = AsyncKVTimeSeriesStore(async_connection)
        for i in range(5):
            await store.record_time_series_async("m", "e", {"i": i})
        results = await store.query_time_series_async("m", "e", limit=2)
        assert len(results) == 2
        assert results[-1]["i"] == 4

    @pytest.mark.asyncio
    async def test_query_filters_by_retention(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=1)
        )
        await store.record_time_series_async(
            "m", "e", {"v": "old"}, timestamp=_ts(48)
        )
        await store.record_time_series_async(
            "m", "e", {"v": "new"}, timestamp=_ts(1)
        )
        results = await store.query_time_series_async("m", "e")
        assert len(results) == 1
        assert results[0]["v"] == "new"

    @pytest.mark.asyncio
    async def test_query_with_invalid_start_date(
        self, async_connection: AsyncConnection
    ) -> None:
        """When _parse_iso returns None, the start_date filter is skipped."""
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async(
            "m", "e", {"v": 1}, timestamp=_ts(1)
        )
        results = await store.query_time_series_async(
            "m", "e", start_date="not-a-date"
        )
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_query_skips_items_older_than_retention(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 197: manually inject old data; retention filter skips it in query.

        We bypass the record_time_series purge by directly mutating the
        PersistentList so we exercise the in-query retention-filter branch.
        """
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=1)
        )
        ts_list = await store._get_ts_list("m", "e")
        ts_list.append({"ts": _ts(48), "v": "old"})
        ts_list.append({"ts": _ts(1), "v": "new"})
        await async_connection.commit()

        results = await store.query_time_series_async("m", "e")
        assert len(results) == 1
        assert results[0]["v"] == "new"


# ---------------------------------------------------------------------------
# AsyncKVTimeSeriesStore.aggregate_patterns_async - branch coverage
# ---------------------------------------------------------------------------


class TestAsyncAggregatePatterns:
    @pytest.mark.asyncio
    async def test_aggregate_filters_retention(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 224: items older than retention are skipped."""
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=1)
        )
        await store.record_time_series_async(
            "m", "e", {"pattern": "old"}, timestamp=_ts(48)
        )
        await store.record_time_series_async(
            "m", "e", {"pattern": "new"}, timestamp=_ts(1)
        )
        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "new"

    @pytest.mark.asyncio
    async def test_aggregate_filters_start_date(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 226: items before start_dt are skipped."""
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async(
            "m", "e", {"pattern": "old"}, timestamp=_ts(48)
        )
        await store.record_time_series_async(
            "m", "e", {"pattern": "new"}, timestamp=_ts(1)
        )
        results = await store.aggregate_patterns_async(_ts(24), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "new"

    @pytest.mark.asyncio
    async def test_aggregate_skips_items_without_pattern(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 235: items lacking pattern/issue_type/event/category are skipped."""
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async("m", "e", {"value": 42})
        await store.record_time_series_async("m", "e", {"other": "data"})
        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=1)
        assert results == []

    @pytest.mark.asyncio
    async def test_aggregate_recognizes_event_field(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async("logs", "s1", {"event": "deploy"})
        await store.record_time_series_async("logs", "s2", {"event": "deploy"})
        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=2)
        assert len(results) == 1
        assert results[0]["pattern"] == "deploy"
        assert results[0]["count"] == 2

    @pytest.mark.asyncio
    async def test_aggregate_recognizes_category_field(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async("err", "r1", {"category": "net"})
        await store.record_time_series_async("err", "r2", {"category": "net"})
        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=2)
        assert results[0]["pattern"] == "net"

    @pytest.mark.asyncio
    async def test_aggregate_issue_type_fallback(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async("m", "e", {"issue_type": "crash"})
        await store.record_time_series_async("m", "e", {"issue_type": "crash"})
        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=2)
        assert results[0]["pattern"] == "crash"

    @pytest.mark.asyncio
    async def test_aggregate_sorted_by_count_desc(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async("m", "e", {"pattern": "low"})
        await store.record_time_series_async("m", "e", {"pattern": "mid"})
        await store.record_time_series_async("m", "e", {"pattern": "mid"})
        await store.record_time_series_async("m", "e", {"pattern": "high"})
        await store.record_time_series_async("m", "e", {"pattern": "high"})
        await store.record_time_series_async("m", "e", {"pattern": "high"})
        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=1)
        assert [r["count"] for r in results] == [3, 2, 1]
        assert [r["pattern"] for r in results] == ["high", "mid", "low"]

    @pytest.mark.asyncio
    async def test_aggregate_min_occurrences_filter(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async("m", "e", {"pattern": "rare"})
        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=2)
        assert results == []

    @pytest.mark.asyncio
    async def test_aggregate_with_invalid_start_date(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=365)
        )
        await store.record_time_series_async("m", "e", {"pattern": "p"})
        results = await store.aggregate_patterns_async("not-a-date", min_occurrences=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_aggregate_empty(
        self, async_connection: AsyncConnection
    ) -> None:
        store = AsyncKVTimeSeriesStore(async_connection)
        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=1)
        assert results == []

    @pytest.mark.asyncio
    async def test_aggregate_skips_retention_cutoff(
        self, async_connection: AsyncConnection
    ) -> None:
        """Line 224: items past the retention cutoff are skipped during aggregation.

        We manually inject a stale entry so the in-loop retention filter
        (independent of record-time purge) is exercised.
        """
        store = AsyncKVTimeSeriesStore(
            async_connection, retention=TimeSeriesRetention(retention_days=1)
        )
        ts_list = await store._get_ts_list("m", "e")
        ts_list.append({"ts": _ts(48), "pattern": "stale"})
        ts_list.append({"ts": _ts(1), "pattern": "fresh"})
        await async_connection.commit()

        results = await store.aggregate_patterns_async(_ts(365), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "fresh"


# ---------------------------------------------------------------------------
# Sync KVTimeSeriesStore.list_prefix - lines 330-340
# ---------------------------------------------------------------------------


class TestSyncListPrefix:
    def test_list_prefix_returns_matching_keys(
        self, connection: Connection
    ) -> None:
        """Lines 330-340: sync list_prefix method basic flow."""
        store = KVTimeSeriesStore(connection)
        store.put("component_endpoint/a", {"url": "http://a"})
        store.put("component_endpoint/b", {"url": "http://b"})
        store.put("other/key", "ignored")
        results = store.list_prefix("component_endpoint/")
        keys = {r["key"] for r in results}
        assert keys == {"component_endpoint/a", "component_endpoint/b"}

    def test_list_prefix_no_matches(self, connection: Connection) -> None:
        store = KVTimeSeriesStore(connection)
        store.put("alpha/1", "x")
        results = store.list_prefix("beta/")
        assert results == []

    def test_list_prefix_skips_expired(
        self, connection: Connection
    ) -> None:
        store = KVTimeSeriesStore(connection)
        store.put("p/a", "x")
        store.put("p/b", "y", ttl=1)
        time.sleep(1.1)
        results = store.list_prefix("p/")
        keys = {r["key"] for r in results}
        assert keys == {"p/a"}

    def test_list_prefix_empty_kv(self, connection: Connection) -> None:
        store = KVTimeSeriesStore(connection)
        results = store.list_prefix("any/")
        assert results == []


# ---------------------------------------------------------------------------
# Sync get: TTL=0 expires immediately (small additional branch coverage)
# ---------------------------------------------------------------------------


class TestSyncGetZeroTtl:
    def test_get_zero_ttl_expires(
        self, connection: Connection
    ) -> None:
        """A TTL of 0 expires on the next read."""
        store = KVTimeSeriesStore(connection)
        store.put("k", "v", ttl=0)
        time.sleep(0.05)
        result = store.get("k")
        assert result["value"] is None
        assert result.get("expired") is True

"""Tests for dhara/mcp/kv_timeseries.py — KV and time-series storage."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from dhara.mcp.kv_timeseries import (
    KVTimeSeriesStore,
    TimeSeriesRetention,
    _parse_iso,
    _utcnow,
)


# ── Helpers ──────────────────────────────────────────────────────


def _ts(hours_ago: int = 0) -> str:
    """Return an ISO timestamp *hours_ago* hours from now."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


# ── Pure-function tests ──────────────────────────────────────────


class TestParseIso:
    def test_valid_iso(self):
        result = _parse_iso("2025-01-01T00:00:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_z_suffix(self):
        result = _parse_iso("2025-01-01T00:00:00Z")
        assert result is not None

    def test_naive_becomes_utc(self):
        result = _parse_iso("2025-01-01T00:00:00")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_garbage_returns_none(self):
        assert _parse_iso("not-a-date") is None
        assert _parse_iso("") is None


class TestTimeSeriesRetention:
    def test_cutoff(self):
        r = TimeSeriesRetention(retention_days=7)
        cutoff = r.cutoff()
        now = datetime.now(timezone.utc)
        assert (now - cutoff).days >= 6

    def test_default_retention(self):
        assert TimeSeriesRetention().retention_days == 60


# ── KV tests ─────────────────────────────────────────────────────


class TestKVTimeSeriesStoreKV:
    def test_put_and_get(self, connection):
        store = KVTimeSeriesStore(connection)
        store.put("key1", "value1")
        result = store.get("key1")
        assert result["ok"] is True
        assert result["value"] == "value1"

    def test_get_missing_key(self, connection):
        store = KVTimeSeriesStore(connection)
        result = store.get("nope")
        assert result["ok"] is True
        assert result["value"] is None

    def test_put_overwrites(self, connection):
        store = KVTimeSeriesStore(connection)
        store.put("k", 1)
        store.put("k", 2)
        assert store.get("k")["value"] == 2

    def test_ttl_expiry(self, connection):
        store = KVTimeSeriesStore(connection)
        store.put("ttl_key", "data", ttl=1)
        assert store.get("ttl_key")["value"] == "data"
        time.sleep(1.1)
        result = store.get("ttl_key")
        assert result["value"] is None
        assert result.get("expired") is True

    def test_ttl_cleared_on_overwrite_without_ttl(self, connection):
        store = KVTimeSeriesStore(connection)
        store.put("k", "v1", ttl=3600)
        store.put("k", "v2")
        result = store.get("k")
        assert result["value"] == "v2"
        assert "expired" not in result

    def test_various_value_types(self, connection):
        store = KVTimeSeriesStore(connection)
        for val in [42, 3.14, True, None, [1, 2], {"a": "b"}]:
            store.put("k", val)
            assert store.get("k")["value"] == val


# ── Time-series tests ─────────────────────────────────────────────


class TestKVTimeSeriesStoreTS:
    def test_record_and_query(self, connection):
        store = KVTimeSeriesStore(connection)
        store.record_time_series("cpu", "host1", {"value": 80})
        results = store.query_time_series("cpu", "host1")
        assert len(results) == 1
        assert results[0]["value"] == 80

    def test_custom_timestamp(self, connection):
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        ts = _ts(hours_ago=1)
        store.record_time_series("cpu", "h1", {"v": 50}, timestamp=ts)
        results = store.query_time_series("cpu", "h1", start_date=_ts(hours_ago=24))
        assert len(results) == 1
        assert results[0]["ts"] == ts

    def test_query_with_limit(self, connection):
        store = KVTimeSeriesStore(connection)
        for i in range(10):
            store.record_time_series("m", "e", {"i": i})
        results = store.query_time_series("m", "e", limit=3)
        assert len(results) == 3
        assert results[-1]["i"] == 9

    def test_query_filters_by_start_date(self, connection):
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"v": 1}, timestamp=_ts(48))
        store.record_time_series("m", "e", {"v": 2}, timestamp=_ts(1))
        results = store.query_time_series("m", "e", start_date=_ts(24))
        assert len(results) == 1
        assert results[0]["v"] == 2

    def test_purge_old_records(self, connection):
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        store.record_time_series("m", "e", {"v": "old"}, timestamp=_ts(48))
        store.record_time_series("m", "e", {"v": "new"}, timestamp=_ts(1))
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert results[0]["v"] == "new"


# ── Aggregate patterns tests ──────────────────────────────────────


class TestAggregatePatterns:
    def test_aggregates_pattern_field(self, connection):
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("issues", "r1", {"pattern": "timeout"})
        store.record_time_series("issues", "r2", {"pattern": "timeout"})
        store.record_time_series("issues", "r3", {"pattern": "oom"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=2)
        assert len(results) == 1
        assert results[0]["pattern"] == "timeout"
        assert results[0]["count"] == 2

    def test_aggregates_issue_type_field(self, connection):
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("bugs", "r1", {"issue_type": "crash"})
        store.record_time_series("bugs", "r2", {"issue_type": "crash"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=2)
        assert len(results) == 1
        assert results[0]["pattern"] == "crash"

    def test_min_occurrences_filters(self, connection):
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"pattern": "rare"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=2)
        assert len(results) == 0

    def test_sorted_by_count_desc(self, connection):
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"pattern": "a"})
        store.record_time_series("m", "e", {"pattern": "b"})
        store.record_time_series("m", "e", {"pattern": "b"})
        store.record_time_series("m", "e", {"pattern": "b"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert results[0]["pattern"] == "b"
        assert results[0]["count"] == 3

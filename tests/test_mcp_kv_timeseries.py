"""Comprehensive tests for dhara/mcp/kv_timeseries.py — targeting all uncovered lines.

This file supplements tests/test_kv_timeseries.py by covering branches and edge
cases that the original suite does not exercise.  Together the two files should
bring line coverage of kv_timeseries.py to 100 %.

The conftest.py in tests/ provides a ``connection`` fixture backed by
MemoryStorage, which is ideal for unit tests because it requires no file
cleanup.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest

from dhara.mcp.kv_timeseries import (
    KVTimeSeriesStore,
    TimeSeriesRetention,
    _parse_iso,
    _utcnow,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(hours_ago: int = 0) -> str:
    """Return an ISO timestamp *hours_ago* hours from now."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


# ---------------------------------------------------------------------------
# _utcnow
# ---------------------------------------------------------------------------


class TestUtcnow:
    def test_returns_aware_datetime(self) -> None:
        result = _utcnow()
        assert result.tzinfo == timezone.utc

    @patch("dhara.mcp.kv_timeseries._utcnow", wraps=_utcnow)
    def test_called_by_record_when_no_timestamp(self, mock_now: Any, connection: Any) -> None:
        """record_time_series falls back to _utcnow when timestamp is None."""
        store = KVTimeSeriesStore(connection)
        fake_ts = "2099-01-01T00:00:00+00:00"
        mock_now.return_value = datetime.fromisoformat(fake_ts)
        store.record_time_series("m", "e", {"v": 1})
        results = store.query_time_series("m", "e")
        assert results[0]["ts"] == fake_ts


# ---------------------------------------------------------------------------
# _parse_iso -- branches not covered by the original suite
# ---------------------------------------------------------------------------


class TestParseIsoExtended:
    def test_naive_datetime_becomes_utc(self) -> None:
        """Line 30: dt.tzinfo is None -> replace with UTC."""
        result = _parse_iso("2025-06-15T12:00:00")
        assert result is not None
        assert result.tzinfo == timezone.utc
        assert result.year == 2025
        assert result.month == 6

    def test_non_utc_tzinfo_converted_to_utc(self) -> None:
        """Line 31: dt.tzinfo is not None and not UTC -> astimezone(UTC)."""
        # +05:30 offset
        result = _parse_iso("2025-06-15T12:00:00+05:30")
        assert result is not None
        assert result.tzinfo == timezone.utc
        # 12:00 +05:30 -> 06:30 UTC
        assert result.hour == 6
        assert result.minute == 30

    def test_negative_offset_converted_to_utc(self) -> None:
        result = _parse_iso("2025-06-15T12:00:00-08:00")
        assert result is not None
        assert result.tzinfo == timezone.utc
        # 12:00 -08:00 -> 20:00 UTC
        assert result.hour == 20

    def test_already_utc_preserved(self) -> None:
        result = _parse_iso("2025-06-15T12:00:00+00:00")
        assert result is not None
        assert result.tzinfo == timezone.utc
        assert result.hour == 12

    def test_microseconds_preserved(self) -> None:
        result = _parse_iso("2025-06-15T12:00:00.123456+00:00")
        assert result is not None
        assert result.microsecond == 123456

    def test_empty_string_returns_none(self) -> None:
        assert _parse_iso("") is None

    def test_non_string_input(self) -> None:
        assert _parse_iso(None) is None  # type: ignore[arg-type]

    def test_date_only_returns_datetime(self) -> None:
        """Python 3.11+ supports date-only strings in fromisoformat."""
        result = _parse_iso("2025-06-15")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_z_suffix_parsed(self) -> None:
        """Verify Z suffix is replaced before fromisoformat."""
        result = _parse_iso("2025-06-15T12:00:00Z")
        assert result is not None
        assert result.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# TimeSeriesRetention -- additional edge cases
# ---------------------------------------------------------------------------


class TestTimeSeriesRetentionExtended:
    def test_zero_retention(self) -> None:
        r = TimeSeriesRetention(retention_days=0)
        cutoff = r.cutoff()
        now = datetime.now(timezone.utc)
        # cutoff should be very close to now
        assert abs((now - cutoff).total_seconds()) < 5

    def test_large_retention(self) -> None:
        r = TimeSeriesRetention(retention_days=3650)
        cutoff = r.cutoff()
        now = datetime.now(timezone.utc)
        assert (now - cutoff).days >= 3650 - 1


# ---------------------------------------------------------------------------
# KVTimeSeriesStore -- _ensure_root edge cases
# ---------------------------------------------------------------------------


class TestEnsureRoot:
    def test_root_already_initialized(self, connection: Any) -> None:
        """When root already has kv, kv_ttl, time_series, no extra commit."""
        store = KVTimeSeriesStore(connection)
        # Creating a second store against the same connection should not fail
        store2 = KVTimeSeriesStore(connection)
        store2.put("k", "v")
        assert store2.get("k")["value"] == "v"

    def test_each_subdict_created_once(self, connection: Any) -> None:
        """Verify that _ensure_root creates all three root keys."""
        store = KVTimeSeriesStore(connection)
        root = connection.get_root()
        assert "kv" in root
        assert "kv_ttl" in root
        assert "time_series" in root


# ---------------------------------------------------------------------------
# KVTimeSeriesStore.put -- additional branches
# ---------------------------------------------------------------------------


class TestPutExtended:
    def test_put_with_float_ttl(self, connection: Any) -> None:
        """Line 83: ttl is float; int() conversion applied."""
        store = KVTimeSeriesStore(connection)
        store.put("k", "v", ttl=2.7)
        result = store.get("k")
        assert result["value"] == "v"

    def test_put_with_zero_ttl_expires_immediately(self, connection: Any) -> None:
        """A TTL of 0 means the key expires on the next read."""
        store = KVTimeSeriesStore(connection)
        store.put("k", "v", ttl=0)
        time.sleep(0.05)
        result = store.get("k")
        assert result["value"] is None
        assert result.get("expired") is True

    def test_put_overwrites_ttl_key(self, connection: Any) -> None:
        """Overwriting a TTL key with a new TTL updates the expiry."""
        store = KVTimeSeriesStore(connection)
        store.put("k", "v1", ttl=1)
        store.put("k", "v2", ttl=3600)
        result = store.get("k")
        assert result["value"] == "v2"
        assert "expired" not in result

    def test_put_returns_dict(self, connection: Any) -> None:
        store = KVTimeSeriesStore(connection)
        result = store.put("mykey", 42)
        assert isinstance(result, dict)
        assert result["ok"] is True
        assert result["key"] == "mykey"


# ---------------------------------------------------------------------------
# KVTimeSeriesStore.get -- additional branches
# ---------------------------------------------------------------------------


class TestGetExtended:
    def test_get_expired_lazy_deletion(self, connection: Any) -> None:
        """Line 100-103: expired key is deleted from both kv and kv_ttl."""
        store = KVTimeSeriesStore(connection)
        store.put("k", "v", ttl=1)
        time.sleep(1.1)
        result = store.get("k")
        assert result["value"] is None
        assert result["expired"] is True
        # After lazy deletion, a second get should still return None
        # but without the expired flag (key no longer exists).
        result2 = store.get("k")
        assert result2["value"] is None
        assert "expired" not in result2

    def test_get_nonexistent_returns_none(self, connection: Any) -> None:
        store = KVTimeSeriesStore(connection)
        result = store.get("does_not_exist")
        assert result["value"] is None
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# _ts_key
# ---------------------------------------------------------------------------


class TestTsKey:
    def test_ts_key_format(self, connection: Any) -> None:
        store = KVTimeSeriesStore(connection)
        key = store._ts_key("cpu", "host1")
        assert key == "cpu:host1"

    def test_ts_key_with_special_characters(self, connection: Any) -> None:
        store = KVTimeSeriesStore(connection)
        key = store._ts_key("metric/type", "entity:id")
        assert key == "metric/type:entity:id"


# ---------------------------------------------------------------------------
# _get_ts_list
# ---------------------------------------------------------------------------


class TestGetTsList:
    def test_creates_new_list_on_first_access(self, connection: Any) -> None:
        store = KVTimeSeriesStore(connection)
        ts_list = store._get_ts_list("new_metric", "new_entity")
        assert len(ts_list) == 0

    def test_returns_existing_list(self, connection: Any) -> None:
        store = KVTimeSeriesStore(connection)
        store.record_time_series("m", "e", {"v": 1})
        ts_list = store._get_ts_list("m", "e")
        assert len(ts_list) == 1


# ---------------------------------------------------------------------------
# record_time_series -- additional branches
# ---------------------------------------------------------------------------


class TestRecordTimeSeriesExtended:
    def test_record_with_empty_dict(self, connection: Any) -> None:
        """Line 132: record is empty dict -> payload.update({}) is a no-op."""
        store = KVTimeSeriesStore(connection)
        store.record_time_series("m", "e", {})
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert "ts" in results[0]
        # Only "ts" key should be present
        assert set(results[0].keys()) == {"ts"}

    def test_record_with_none_record(self, connection: Any) -> None:
        """Line 132: record is None -> record or {} evaluates to {}."""
        store = KVTimeSeriesStore(connection)
        store.record_time_series("m", "e", None)  # type: ignore[arg-type]
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert set(results[0].keys()) == {"ts"}

    def test_record_with_explicit_timestamp(self, connection: Any) -> None:
        """Line 129: timestamp provided, _utcnow() not called."""
        store = KVTimeSeriesStore(
            connection, retention=TimeSeriesRetention(retention_days=730),
        )
        ts = "2025-01-01T00:00:00+00:00"
        store.record_time_series("m", "e", {"v": 42}, timestamp=ts)
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert results[0]["ts"] == ts

    def test_record_return_value(self, connection: Any) -> None:
        store = KVTimeSeriesStore(connection)
        result = store.record_time_series("cpu", "host1", {"value": 80})
        assert result["ok"] is True
        assert result["metric_type"] == "cpu"
        assert result["entity_id"] == "host1"

    def test_record_multiple_entities(self, connection: Any) -> None:
        """Different entity_ids produce independent time series."""
        store = KVTimeSeriesStore(connection)
        store.record_time_series("cpu", "host1", {"v": 10})
        store.record_time_series("cpu", "host2", {"v": 20})
        assert len(store.query_time_series("cpu", "host1")) == 1
        assert len(store.query_time_series("cpu", "host2")) == 1
        assert store.query_time_series("cpu", "host1")[0]["v"] == 10
        assert store.query_time_series("cpu", "host2")[0]["v"] == 20

    def test_record_multiple_metrics(self, connection: Any) -> None:
        """Different metric_types produce independent time series."""
        store = KVTimeSeriesStore(connection)
        store.record_time_series("cpu", "host1", {"v": 10})
        store.record_time_series("memory", "host1", {"v": 50})
        assert len(store.query_time_series("cpu", "host1")) == 1
        assert len(store.query_time_series("memory", "host1")) == 1


# ---------------------------------------------------------------------------
# query_time_series -- additional branches
# ---------------------------------------------------------------------------


class TestQueryTimeSeriesExtended:
    def test_query_no_start_date(self, connection: Any) -> None:
        """Line 148: start_date is None -> start_dt is None -> no date filter."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"v": 1}, timestamp=_ts(48))
        store.record_time_series("m", "e", {"v": 2}, timestamp=_ts(1))
        results = store.query_time_series("m", "e")
        assert len(results) == 2

    def test_query_with_limit_zero(self, connection: Any) -> None:
        """Line 161: limit=0 -> results[-0:] = results[0:] returns all results."""
        store = KVTimeSeriesStore(connection)
        store.record_time_series("m", "e", {"v": 1})
        store.record_time_series("m", "e", {"v": 2})
        results = store.query_time_series("m", "e", limit=0)
        # -0 == 0, so results[0:] returns everything
        assert len(results) == 2

    def test_query_limit_exceeds_list_length(self, connection: Any) -> None:
        """Limit larger than the number of records returns all records."""
        store = KVTimeSeriesStore(connection)
        store.record_time_series("m", "e", {"v": 1})
        store.record_time_series("m", "e", {"v": 2})
        results = store.query_time_series("m", "e", limit=100)
        assert len(results) == 2

    def test_query_limit_one_returns_last(self, connection: Any) -> None:
        """Limit=1 returns only the most recent record (last in list)."""
        store = KVTimeSeriesStore(connection)
        store.record_time_series("m", "e", {"v": 1})
        store.record_time_series("m", "e", {"v": 2})
        results = store.query_time_series("m", "e", limit=1)
        assert len(results) == 1
        assert results[0]["v"] == 2

    def test_query_with_negative_limit(self, connection: Any) -> None:
        """Line 161: int(limit) with negative value -> slicing from end."""
        store = KVTimeSeriesStore(connection)
        for i in range(5):
            store.record_time_series("m", "e", {"v": i})
        # limit=-3 -> results[-(-3):] = results[3:] -> last 2 items
        results = store.query_time_series("m", "e", limit=-3)
        assert len(results) == 2

    def test_query_filters_out_expired_by_retention(self, connection: Any) -> None:
        """Line 154-155: items older than retention cutoff are skipped."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        store.record_time_series("m", "e", {"v": "old"}, timestamp=_ts(48))
        store.record_time_series("m", "e", {"v": "recent"}, timestamp=_ts(1))
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert results[0]["v"] == "recent"

    def test_query_filters_by_start_date(self, connection: Any) -> None:
        """Line 156-157: items before start_dt are skipped."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"v": 1}, timestamp=_ts(72))
        store.record_time_series("m", "e", {"v": 2}, timestamp=_ts(36))
        store.record_time_series("m", "e", {"v": 3}, timestamp=_ts(1))
        results = store.query_time_series("m", "e", start_date=_ts(48))
        assert len(results) == 2
        assert results[0]["v"] == 2
        assert results[1]["v"] == 3

    def test_query_empty_series(self, connection: Any) -> None:
        store = KVTimeSeriesStore(connection)
        results = store.query_time_series("m", "e")
        assert results == []

    def test_query_invalid_start_date(self, connection: Any) -> None:
        """Line 148: _parse_iso returns None for invalid start_date."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"v": 1}, timestamp=_ts(1))
        # Invalid start_date -> start_dt is None -> no date filter applied
        results = store.query_time_series("m", "e", start_date="not-a-date")
        assert len(results) == 1

    def test_query_with_float_limit(self, connection: Any) -> None:
        """Line 161: limit is float -> int(limit) conversion."""
        store = KVTimeSeriesStore(connection)
        for i in range(10):
            store.record_time_series("m", "e", {"v": i})
        results = store.query_time_series("m", "e", limit=3.7)
        assert len(results) == 3

    def test_query_items_without_ts_key(self, connection: Any) -> None:
        """Line 153: item has no 'ts' key -> ts_raw is None -> ts_dt is None.

        When ts_dt is None, both retention and start_date checks are skipped,
        so the item is included.
        """
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        # Manually insert an item without a ts key via the underlying list
        ts_list = store._get_ts_list("m", "e")
        ts_list.append({"v": "no_ts"})
        connection.commit()
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert results[0]["v"] == "no_ts"

    def test_query_items_with_non_string_ts(self, connection: Any) -> None:
        """Line 153: ts_raw is not a string -> isinstance check is False."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        ts_list = store._get_ts_list("m", "e")
        ts_list.append({"ts": 12345, "v": "int_ts"})
        connection.commit()
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert results[0]["v"] == "int_ts"

    def test_query_retention_cuts_off_old_with_start_date(self, connection: Any) -> None:
        """Both retention cutoff and start_date filter are applied together."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=2),
        )
        store.record_time_series("m", "e", {"v": "very_old"}, timestamp=_ts(72))
        store.record_time_series("m", "e", {"v": "old"}, timestamp=_ts(36))
        store.record_time_series("m", "e", {"v": "new"}, timestamp=_ts(1))
        # start_date filters out "old" (36h ago) but "very_old" is also filtered
        # by retention (72h ago > 2 day retention)
        results = store.query_time_series("m", "e", start_date=_ts(24))
        assert len(results) == 1
        assert results[0]["v"] == "new"


# ---------------------------------------------------------------------------
# aggregate_patterns -- additional branches
# ---------------------------------------------------------------------------


class TestAggregatePatternsExtended:
    def test_event_field_recognized(self, connection: Any) -> None:
        """Line 188: item.get('event') is used as pattern."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("logs", "svc1", {"event": "deploy"})
        store.record_time_series("logs", "svc2", {"event": "deploy"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=2)
        assert len(results) == 1
        assert results[0]["pattern"] == "deploy"
        assert results[0]["count"] == 2

    def test_category_field_recognized(self, connection: Any) -> None:
        """Line 189: item.get('category') is used as pattern."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("errors", "r1", {"category": "network"})
        store.record_time_series("errors", "r2", {"category": "network"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=2)
        assert len(results) == 1
        assert results[0]["pattern"] == "network"

    def test_pattern_takes_precedence_over_issue_type(self, connection: Any) -> None:
        """Line 186-187: pattern is checked first; issue_type is a fallback."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"pattern": "p", "issue_type": "i"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "p"

    def test_issue_type_precedence_over_event(self, connection: Any) -> None:
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"issue_type": "bug", "event": "crash"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "bug"

    def test_event_precedence_over_category(self, connection: Any) -> None:
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"event": "restart", "category": "ops"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "restart"

    def test_items_without_pattern_fields_skipped(self, connection: Any) -> None:
        """Line 191-192: items with no pattern/issue_type/event/category are skipped."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"value": 42})
        store.record_time_series("m", "e", {"other": "data"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert len(results) == 0

    def test_items_with_non_string_ts_skipped_correctly(self, connection: Any) -> None:
        """Line 179: ts_raw is not a string -> ts_dt is None -> skip retention/start checks.

        Since ts_dt is None, the retention check on line 180-181 is skipped
        (ts_dt is falsy), and the start_date check on line 182-183 is also
        skipped. The item is then processed for pattern extraction.
        """
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        ts_list = store._get_ts_list("m", "e")
        ts_list.append({"ts": 12345, "pattern": "from_int_ts"})
        connection.commit()
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "from_int_ts"

    def test_items_without_ts_key(self, connection: Any) -> None:
        """Items with no 'ts' key have ts_raw=None -> ts_dt=None."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        ts_list = store._get_ts_list("m", "e")
        ts_list.append({"pattern": "no_ts_key"})
        connection.commit()
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "no_ts_key"

    def test_retention_filters_old_patterns(self, connection: Any) -> None:
        """Patterns from records older than retention are excluded."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        store.record_time_series("m", "e", {"pattern": "old"}, timestamp=_ts(48))
        store.record_time_series("m", "e", {"pattern": "new"}, timestamp=_ts(1))
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "new"

    def test_start_date_filters_patterns(self, connection: Any) -> None:
        """Patterns from records before start_date are excluded."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"pattern": "old"}, timestamp=_ts(48))
        store.record_time_series("m", "e", {"pattern": "new"}, timestamp=_ts(1))
        results = store.aggregate_patterns(_ts(24), min_occurrences=1)
        assert len(results) == 1
        assert results[0]["pattern"] == "new"

    def test_invalid_start_date_in_aggregate(self, connection: Any) -> None:
        """Line 171: _parse_iso returns None for invalid start_date."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"pattern": "p"}, timestamp=_ts(1))
        # Invalid start_date -> start_dt is None -> no date filter
        results = store.aggregate_patterns("not-a-date", min_occurrences=1)
        assert len(results) == 1

    def test_patterns_across_multiple_series_keys(self, connection: Any) -> None:
        """Patterns are aggregated across all metric_type:entity_id combinations."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("issues", "r1", {"pattern": "timeout"})
        store.record_time_series("issues", "r2", {"pattern": "timeout"})
        store.record_time_series("bugs", "r3", {"pattern": "timeout"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=3)
        assert len(results) == 1
        assert results[0]["pattern"] == "timeout"
        assert results[0]["count"] == 3

    def test_empty_time_series_map(self, connection: Any) -> None:
        """No time series data at all."""
        store = KVTimeSeriesStore(connection)
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert results == []

    def test_sorted_by_count_descending(self, connection: Any) -> None:
        """Line 200-201: results are sorted by count descending."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"pattern": "low"})
        store.record_time_series("m", "e", {"pattern": "mid"})
        store.record_time_series("m", "e", {"pattern": "mid"})
        store.record_time_series("m", "e", {"pattern": "high"})
        store.record_time_series("m", "e", {"pattern": "high"})
        store.record_time_series("m", "e", {"pattern": "high"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=1)
        assert [r["count"] for r in results] == [3, 2, 1]
        assert [r["pattern"] for r in results] == ["high", "mid", "low"]

    def test_pattern_counted_across_items(self, connection: Any) -> None:
        """Multiple items with the same pattern are counted correctly."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        for _ in range(5):
            store.record_time_series("m", "e", {"pattern": "repeated"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=5)
        assert len(results) == 1
        assert results[0]["count"] == 5

    def test_pattern_value_is_stringified(self, connection: Any) -> None:
        """Line 193: str(pattern) is used as the key."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"pattern": 123})
        store.record_time_series("m", "e", {"pattern": "123"})
        results = store.aggregate_patterns(_ts(365), min_occurrences=2)
        assert len(results) == 1
        assert results[0]["pattern"] == "123"
        assert results[0]["count"] == 2


# ---------------------------------------------------------------------------
# _purge_time_series -- additional branches
# ---------------------------------------------------------------------------


class TestPurgeTimeSeries:
    def test_purge_empty_list(self, connection: Any) -> None:
        """Line 205-206: empty list -> early return."""
        store = KVTimeSeriesStore(connection)
        ts_list = store._get_ts_list("m", "e")
        store._purge_time_series(ts_list)
        assert len(ts_list) == 0

    def test_purge_removes_expired(self, connection: Any) -> None:
        """Line 215-216: expired items are removed from the list."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        store.record_time_series("m", "e", {"v": "old"}, timestamp=_ts(48))
        store.record_time_series("m", "e", {"v": "new"}, timestamp=_ts(1))
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert results[0]["v"] == "new"

    def test_purge_keeps_items_without_parseable_ts(self, connection: Any) -> None:
        """Line 212: ts_dt is None -> item is kept (not purged)."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        ts_list = store._get_ts_list("m", "e")
        ts_list.append({"v": "no_ts"})
        ts_list.append({"ts": "not-a-date", "v": "bad_ts"})
        connection.commit()
        store._purge_time_series(ts_list)
        assert len(ts_list) == 2

    def test_purge_keeps_items_with_non_string_ts(self, connection: Any) -> None:
        """Line 211: ts_raw is not a string -> ts_dt is None -> kept."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        ts_list = store._get_ts_list("m", "e")
        ts_list.append({"ts": 12345, "v": "int_ts"})
        connection.commit()
        store._purge_time_series(ts_list)
        assert len(ts_list) == 1
        assert ts_list[0]["v"] == "int_ts"

    def test_purge_no_change_when_all_within_retention(self, connection: Any) -> None:
        """Line 215: len(kept) == len(ts_list) -> no mutation."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=365),
        )
        store.record_time_series("m", "e", {"v": 1}, timestamp=_ts(1))
        store.record_time_series("m", "e", {"v": 2}, timestamp=_ts(2))
        ts_list = store._get_ts_list("m", "e")
        original_len = len(ts_list)
        store._purge_time_series(ts_list)
        assert len(ts_list) == original_len

    def test_purge_all_expired(self, connection: Any) -> None:
        """All items are older than retention -> list is cleared."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        store.record_time_series("m", "e", {"v": 1}, timestamp=_ts(48))
        store.record_time_series("m", "e", {"v": 2}, timestamp=_ts(72))
        results = store.query_time_series("m", "e")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Integration: record -> purge -> query cycle
# ---------------------------------------------------------------------------


class TestRecordPurgeQueryCycle:
    def test_purge_happens_on_record(self, connection: Any) -> None:
        """_purge_time_series is called during record_time_series."""
        store = KVTimeSeriesStore(
            connection,
            retention=TimeSeriesRetention(retention_days=1),
        )
        # Record old entries
        store.record_time_series("m", "e", {"v": 1}, timestamp=_ts(48))
        # Record a new entry; this triggers _purge_time_series
        store.record_time_series("m", "e", {"v": 2}, timestamp=_ts(1))
        results = store.query_time_series("m", "e")
        assert len(results) == 1
        assert results[0]["v"] == 2

    def test_multiple_commits_preserve_data(self, connection: Any) -> None:
        """Multiple put/get/record cycles over the same connection."""
        store = KVTimeSeriesStore(connection)
        store.put("k1", "v1")
        store.record_time_series("m", "e", {"v": 1})
        store.put("k2", "v2")
        store.record_time_series("m", "e", {"v": 2})

        assert store.get("k1")["value"] == "v1"
        assert store.get("k2")["value"] == "v2"
        results = store.query_time_series("m", "e")
        assert len(results) == 2

    def test_store_with_custom_retention(self, connection: Any) -> None:
        """Store accepts a custom TimeSeriesRetention instance."""
        retention = TimeSeriesRetention(retention_days=30)
        store = KVTimeSeriesStore(connection, retention=retention)
        assert store.retention is retention
        assert store.retention.retention_days == 30

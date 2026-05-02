"""Tests for Prometheus metrics collection.

Tests MetricsCollector, OperationTimer, get_metrics_collector,
and get_server_metrics from dhara.monitoring.metrics.

Note: get_stats() and get_cache_hit_rate() use Counter._value.get()
which depends on prometheus_client internals. We mock _value when needed.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from dhara.monitoring.metrics import (
    PROMETHEUS_AVAILABLE,
    MetricsCollector,
    OperationTimer,
    get_metrics_collector,
    get_server_metrics,
)


def _requires_prometheus():
    if not PROMETHEUS_AVAILABLE:
        pytest.skip("prometheus_client not installed")


def _mock_counter_value(value=0):
    """Create a mock _value object with .get() returning the given value."""
    mock_val = MagicMock()
    mock_val.get.return_value = value
    return mock_val


# ============================================================================
# Module constant
# ============================================================================


class TestPrometheusAvailability:
    """Tests for PROMETHEUS_AVAILABLE flag."""

    def test_flag_is_bool(self):
        assert isinstance(PROMETHEUS_AVAILABLE, bool)


# ============================================================================
# MetricsCollector
# ============================================================================


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_init_when_prometheus_available(self):
        _requires_prometheus()
        collector = MetricsCollector()
        assert collector.is_enabled() is True

    def test_disabled_collector(self, monkeypatch):
        monkeypatch.setattr("dhara.monitoring.metrics.PROMETHEUS_AVAILABLE", False)
        monkeypatch.setattr("dhara.monitoring.metrics.CollectorRegistry", None)
        collector = MetricsCollector()
        assert collector.is_enabled() is False

    def test_record_operation_success(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_operation("load", success=True)
        stats = collector.get_stats()
        assert stats["storage_operations"] > 0

    def test_record_operation_error(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_operation("store", success=False)
        stats = collector.get_stats()
        assert stats["storage_operations"] > 0

    def test_record_operation_with_duration(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_operation("load", success=True, duration=0.001)
        stats = collector.get_stats()
        assert stats["storage_operations"] > 0

    def test_record_cache_hit(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_cache_hit()
        stats = collector.get_stats()
        assert stats["cache_hits"] == 1

    def test_record_cache_miss(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_cache_miss()
        stats = collector.get_stats()
        assert stats["cache_misses"] == 1

    def test_cache_hit_rate(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_cache_hit()
        collector.record_cache_miss()
        rate = collector.get_cache_hit_rate()
        assert rate == 0.5

    def test_cache_hit_rate_none_when_empty(self):
        _requires_prometheus()
        collector = MetricsCollector()
        assert collector.get_cache_hit_rate() is None

    def test_update_cache_size(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.update_cache_size(42)
        stats = collector.get_stats()
        assert stats["cache_size"] == 42

    def test_record_transaction_commit(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_transaction_commit()
        stats = collector.get_stats()
        assert stats["transactions_committed"] == 1

    def test_record_transaction_abort(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_transaction_abort()
        stats = collector.get_stats()
        assert stats["transactions_aborted"] == 1

    def test_record_transaction_conflict(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.record_transaction_conflict()
        stats = collector.get_stats()
        assert stats["transaction_conflicts"] == 1

    def test_increment_connections(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.increment_connections()
        stats = collector.get_stats()
        assert stats["active_connections"] == 1
        assert stats["total_connections"] == 1

    def test_decrement_connections(self):
        _requires_prometheus()
        collector = MetricsCollector()
        collector.increment_connections()
        collector.decrement_connections()
        stats = collector.get_stats()
        assert stats["active_connections"] == 0
        assert stats["total_connections"] == 1

    def test_get_metrics_returns_string(self):
        _requires_prometheus()
        collector = MetricsCollector()
        metrics = collector.get_metrics()
        assert isinstance(metrics, str)
        assert "dhara" in metrics

    def test_get_metrics_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr("dhara.monitoring.metrics.PROMETHEUS_AVAILABLE", False)
        monkeypatch.setattr("dhara.monitoring.metrics.CollectorRegistry", None)
        collector = MetricsCollector()
        assert collector.get_metrics() is None

    def test_get_stats_disabled(self, monkeypatch):
        monkeypatch.setattr("dhara.monitoring.metrics.PROMETHEUS_AVAILABLE", False)
        monkeypatch.setattr("dhara.monitoring.metrics.CollectorRegistry", None)
        collector = MetricsCollector()
        assert collector.get_stats() == {"enabled": False}

    def test_get_stats_enabled(self):
        _requires_prometheus()
        collector = MetricsCollector()
        stats = collector.get_stats()
        assert stats["enabled"] is True
        assert "storage_operations" in stats
        assert "cache_size" in stats
        assert "cache_hits" in stats
        assert "cache_misses" in stats
        assert "transactions_committed" in stats
        assert "active_connections" in stats
        assert "total_connections" in stats

    def test_operations_accumulate(self):
        _requires_prometheus()
        collector = MetricsCollector()
        for _ in range(5):
            collector.record_operation("load", success=True)
        stats = collector.get_stats()
        assert stats["storage_operations"] == 5

    def test_disabled_ops_are_noops(self, monkeypatch):
        monkeypatch.setattr("dhara.monitoring.metrics.PROMETHEUS_AVAILABLE", False)
        monkeypatch.setattr("dhara.monitoring.metrics.CollectorRegistry", None)
        collector = MetricsCollector()
        collector.record_operation("load", True)
        collector.record_cache_hit()
        collector.record_cache_miss()
        collector.update_cache_size(10)
        collector.record_transaction_commit()
        collector.record_transaction_abort()
        collector.record_transaction_conflict()
        collector.increment_connections()
        collector.decrement_connections()
        assert collector.get_cache_hit_rate() is None
        assert collector.get_stats() == {"enabled": False}


# ============================================================================
# OperationTimer
# ============================================================================


class TestOperationTimer:
    """Tests for OperationTimer context manager."""

    def test_records_successful_operation(self):
        _requires_prometheus()
        collector = MetricsCollector()
        with OperationTimer("load", collector):
            time.sleep(0.001)
        stats = collector.get_stats()
        assert stats["storage_operations"] >= 1

    def test_records_failed_operation(self):
        _requires_prometheus()
        collector = MetricsCollector()
        try:
            with OperationTimer("store", collector):
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        stats = collector.get_stats()
        assert stats["storage_operations"] >= 1

    def test_success_flag_set_on_success(self):
        _requires_prometheus()
        collector = MetricsCollector()
        timer = OperationTimer("load", collector)
        with timer:
            pass
        assert timer.success is True

    def test_success_flag_false_on_error(self):
        _requires_prometheus()
        collector = MetricsCollector()
        try:
            with OperationTimer("load", collector) as timer:
                raise ValueError("err")
        except ValueError:
            pass
        assert timer.success is False

    def test_uses_global_collector_by_default(self):
        _requires_prometheus()
        with OperationTimer("load"):
            pass
        collector = get_metrics_collector()
        stats = collector.get_stats()
        assert stats["storage_operations"] >= 1

    def test_records_duration(self):
        _requires_prometheus()
        collector = MetricsCollector()
        with OperationTimer("load", collector):
            time.sleep(0.01)
        stats = collector.get_stats()
        assert stats["storage_operations"] >= 1

    def test_noop_when_start_time_is_none(self):
        """When __enter__ is never called, __exit__ does nothing."""
        _requires_prometheus()
        collector = MetricsCollector()
        timer = OperationTimer("load", collector)
        timer.start_time = None
        timer.__exit__(None, None, None)
        assert timer.start_time is None


# ============================================================================
# Global functions
# ============================================================================


class TestGlobalFunctions:
    """Tests for get_metrics_collector and get_server_metrics."""

    def test_get_metrics_collector_returns_same_instance(self):
        c1 = get_metrics_collector()
        c2 = get_metrics_collector()
        assert c1 is c2

    def test_get_server_metrics_returns_string(self):
        metrics = get_server_metrics()
        assert isinstance(metrics, str)
        assert "dhara" in metrics

    def test_get_server_metrics_has_help_lines(self):
        metrics = get_server_metrics()
        lines = metrics.strip().split("\n")
        assert any("# HELP" in line for line in lines)

    def test_get_server_metrics_disabled_fallback(self, monkeypatch):
        """When prometheus is disabled, get_server_metrics returns minimal health payload."""
        monkeypatch.setattr("dhara.monitoring.metrics.PROMETHEUS_AVAILABLE", False)
        monkeypatch.setattr("dhara.monitoring.metrics.CollectorRegistry", None)
        # Reset the global collector so a new (disabled) one is created
        import dhara.monitoring.metrics as mod
        mod._global_collector = None
        try:
            metrics = get_server_metrics()
            assert "dhara_metrics_enabled 0" in metrics
        finally:
            mod._global_collector = None

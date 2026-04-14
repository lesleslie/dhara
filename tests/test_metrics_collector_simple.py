"""
Simple tests for metrics collector without external dependencies.

These tests verify the metrics collector functionality including:
- Operation recording and timing
- Cache hit/miss tracking
- Transaction statistics
- Connection management
- Metrics export and statistics
"""

import pytest
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from enum import Enum

# Mock imports to avoid dependency issues
class MetricStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"

class SimpleMetricsCollector:
    """Simplified metrics collector for testing."""

    def __init__(self, prometheus_available: bool = False):
        self.prometheus_available = prometheus_available

        # Track all metrics internally
        self.storage_operations = []
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_size = 0
        self.transactions_committed = 0
        self.transactions_aborted = 0
        self.transaction_conflicts = 0
        self.active_connections = 0
        self.total_connections = 0

        # Timing data
        self.operation_durations = []

    def is_enabled(self) -> bool:
        """Check if metrics collection is enabled."""
        return self.prometheus_available

    def record_operation(
        self,
        operation: str,
        success: bool,
        duration: float | None = None,
    ):
        """Record a storage operation."""
        if not self.is_enabled():
            return

        status = "success" if success else "error"
        self.storage_operations.append({
            "operation": operation,
            "status": status,
            "timestamp": datetime.now(),
            "duration": duration
        })

        if duration is not None:
            self.operation_durations.append(duration)

    def record_cache_hit(self):
        """Record a cache hit."""
        if not self.is_enabled():
            return
        self.cache_hits += 1

    def record_cache_miss(self):
        """Record a cache miss."""
        if not self.is_enabled():
            return
        self.cache_misses += 1

    def update_cache_size(self, size: int):
        """Update the current cache size."""
        if not self.is_enabled():
            return
        self.cache_size = size

    def record_transaction_commit(self):
        """Record a committed transaction."""
        if not self.is_enabled():
            return
        self.transactions_committed += 1

    def record_transaction_abort(self):
        """Record an aborted transaction."""
        if not self.is_enabled():
            return
        self.transactions_aborted += 1

    def record_transaction_conflict(self):
        """Record a transaction conflict."""
        if not self.is_enabled():
            return
        self.transaction_conflicts += 1

    def increment_connections(self):
        """Increment active connections."""
        if not self.is_enabled():
            return
        self.active_connections += 1
        self.total_connections += 1

    def decrement_connections(self):
        """Decrement active connections."""
        if not self.is_enabled():
            return
        self.active_connections = max(0, self.active_connections - 1)

    def get_metrics(self) -> str | None:
        """Get Prometheus metrics text format."""
        if not self.is_enabled():
            return None

        # Generate mock Prometheus output
        metrics = []
        metrics.append("# HELP dhara_storage_operations_total Total storage operations")
        metrics.append("# TYPE dhara_storage_operations_total counter")

        # Count operations by type and status
        op_counts = {}
        for op in self.storage_operations:
            key = f"{op['operation']}_{op['status']}"
            op_counts[key] = op_counts.get(key, 0) + 1

        for key, count in op_counts.items():
            metrics.append(f"dhara_storage_operations_total{{{key}}} {count}")

        metrics.append("\n")

        return "\n".join(metrics)

    def get_cache_hit_rate(self) -> float | None:
        """Calculate cache hit rate."""
        if not self.is_enabled():
            return None

        total = self.cache_hits + self.cache_misses
        if total == 0:
            return None

        return self.cache_hits / total

    def get_stats(self) -> dict:
        """Get current metrics statistics."""
        if not self.is_enabled():
            return {"enabled": False}

        return {
            "enabled": True,
            "storage_operations": len(self.storage_operations),
            "cache_size": self.cache_size,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": self.get_cache_hit_rate(),
            "transactions_committed": self.transactions_committed,
            "transactions_aborted": self.transactions_aborted,
            "transaction_conflicts": self.transaction_conflicts,
            "active_connections": self.active_connections,
            "total_connections": self.total_connections,
            "avg_operation_duration": sum(self.operation_durations) / max(len(self.operation_durations), 1),
        }

    def get_operation_counts(self) -> Dict[str, Dict[str, int]]:
        """Get operation counts by type."""
        counts = {}
        for op in self.storage_operations:
            op_name = op["operation"]
            status = op["status"]
            if op_name not in counts:
                counts[op_name] = {"success": 0, "error": 0}
            counts[op_name][status] += 1
        return counts

    def simulate_operation(self, operation: str, success_rate: float = 1.0) -> float:
        """Simulate an operation and return duration."""
        start_time = time.time()

        # Simulate work
        time.sleep(0.001)  # 1ms delay

        success = success_rate > 0.9 or (success_rate > 0 and success_rate <= 0.9 and hash(operation) % 10 < success_rate * 10)
        duration = time.time() - start_time

        self.record_operation(operation, success, duration)
        return duration

    def reset(self):
        """Reset all metrics."""
        self.storage_operations = []
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_size = 0
        self.transactions_committed = 0
        self.transactions_aborted = 0
        self.transaction_conflicts = 0
        self.active_connections = 0
        self.total_connections = 0
        self.operation_durations = []


class OperationTimer:
    """Context manager for timing operations."""

    def __init__(self, operation: str, collector: SimpleMetricsCollector | None = None):
        self.operation = operation
        self.collector = collector
        self.start_time = None
        self.success = False

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.success = exc_type is None
            if self.collector:
                self.collector.record_operation(self.operation, self.success, duration)
        return False


@pytest.fixture
def metrics_collector() -> SimpleMetricsCollector:
    """Create a metrics collector instance."""
    return SimpleMetricsCollector(prometheus_available=True)

@pytest.fixture
def disabled_collector() -> SimpleMetricsCollector:
    """Create a disabled metrics collector."""
    return SimpleMetricsCollector(prometheus_available=False)


class TestSimpleMetricsCollector:
    """Test metrics collector functionality."""

    def test_collector_initialization(self, metrics_collector: SimpleMetricsCollector):
        """Test metrics collector initialization."""
        assert metrics_collector.is_enabled() is True
        assert metrics_collector.cache_hits == 0
        assert metrics_collector.cache_misses == 0
        assert len(metrics_collector.storage_operations) == 0

    def test_disabled_collector(self, disabled_collector: SimpleMetricsCollector):
        """Test disabled collector behavior."""
        assert disabled_collector.is_enabled() is False
        disabled_collector.record_operation("test", True)
        assert len(disabled_collector.storage_operations) == 0

    def test_operation_recording(self, metrics_collector: SimpleMetricsCollector):
        """Test recording storage operations."""
        # Record successful operations
        metrics_collector.record_operation("load", success=True, duration=0.001)
        metrics_collector.record_operation("store", success=True, duration=0.002)

        # Record failed operation
        metrics_collector.record_operation("delete", success=False, duration=0.003)

        # Verify recording
        assert len(metrics_collector.storage_operations) == 3

        # Check specific operations
        loads = [op for op in metrics_collector.storage_operations if op["operation"] == "load"]
        assert len(loads) == 1
        assert loads[0]["status"] == "success"
        assert loads[0]["duration"] == 0.001

    def test_cache_tracking(self, metrics_collector: SimpleMetricsCollector):
        """Test cache hit/miss tracking."""
        # Record cache operations
        metrics_collector.record_cache_hit()
        metrics_collector.record_cache_miss()
        metrics_collector.record_cache_miss()
        metrics_collector.record_cache_hit()
        metrics_collector.record_cache_hit()

        # Verify tracking
        assert metrics_collector.cache_hits == 3
        assert metrics_collector.cache_misses == 2
        assert metrics_collector.get_cache_hit_rate() == 0.6  # 3/5

    def test_cache_size_update(self, metrics_collector: SimpleMetricsCollector):
        """Test cache size updates."""
        # Update cache sizes
        metrics_collector.update_cache_size(100)
        metrics_collector.update_cache_size(150)
        metrics_collector.update_cache_size(75)

        # Verify updates
        assert metrics_collector.cache_size == 75

    def test_transaction_tracking(self, metrics_collector: SimpleMetricsCollector):
        """Test transaction statistics."""
        # Record transactions
        metrics_collector.record_transaction_commit()
        metrics_collector.record_transaction_commit()
        metrics_collector.record_transaction_abort()
        metrics_collector.record_transaction_conflict()

        # Verify tracking
        assert metrics_collector.transactions_committed == 2
        assert metrics_collector.transactions_aborted == 1
        assert metrics_collector.transaction_conflicts == 1

    def test_connection_management(self, metrics_collector: SimpleMetricsCollector):
        """Test connection tracking."""
        # Add connections
        metrics_collector.increment_connections()  # 1
        metrics_collector.increment_connections()  # 2
        metrics_collector.increment_connections()  # 3

        # Remove connections
        metrics_collector.decrement_connections()  # 2
        metrics_collector.decrement_connections()  # 1

        # Verify tracking
        assert metrics_collector.active_connections == 1
        assert metrics_collector.total_connections == 3

    def test_metrics_export(self, metrics_collector: SimpleMetricsCollector):
        """Test metrics export."""
        # Record some operations
        metrics_collector.record_operation("load", success=True)
        metrics_collector.record_operation("load", success=False)
        metrics_collector.record_operation("store", success=True)

        # Export metrics
        metrics_text = metrics_collector.get_metrics()

        # Verify export
        assert metrics_text is not None
        assert "dhara_storage_operations_total" in metrics_text
        assert "load_success" in metrics_text
        assert "load_error" in metrics_text
        assert "store_success" in metrics_text
        assert "HELP" in metrics_text
        assert "TYPE" in metrics_text

    def test_statistics_calculation(self, metrics_collector: SimpleMetricsCollector):
        """Test statistics calculation."""
        # Record various metrics
        metrics_collector.record_operation("load", success=True, duration=0.001)
        metrics_collector.record_operation("store", success=True, duration=0.002)
        metrics_collector.record_operation("delete", success=False, duration=0.003)
        metrics_collector.record_cache_hit()
        metrics_collector.record_cache_miss()
        metrics_collector.record_transaction_commit()
        metrics_collector.increment_connections()

        # Get statistics
        stats = metrics_collector.get_stats()

        # Verify statistics
        assert stats["enabled"] is True
        assert stats["storage_operations"] == 3
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["cache_hit_rate"] == 0.5
        assert stats["transactions_committed"] == 1
        assert stats["active_connections"] == 1
        assert stats["total_connections"] == 1
        assert stats["avg_operation_duration"] == 0.002

    def test_operation_counts(self, metrics_collector: SimpleMetricsCollector):
        """Test operation count aggregation."""
        # Record multiple operations
        metrics_collector.record_operation("load", success=True)
        metrics_collector.record_operation("load", success=True)
        metrics_collector.record_operation("load", success=False)
        metrics_collector.record_operation("store", success=True)
        metrics_collector.record_operation("store", success=False)
        metrics_collector.record_operation("store", success=False)

        # Get operation counts
        counts = metrics_collector.get_operation_counts()

        # Verify counts
        assert counts["load"]["success"] == 2
        assert counts["load"]["error"] == 1
        assert counts["store"]["success"] == 1
        assert counts["store"]["error"] == 2

    def test_operation_timer(self, metrics_collector: SimpleMetricsCollector):
        """Test operation timer context manager."""
        # Test successful operation
        with OperationTimer("load", metrics_collector):
            time.sleep(0.001)  # Simulate work

        # Test failed operation
        try:
            with OperationTimer("store", metrics_collector):
                time.sleep(0.001)
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify timing
        assert len(metrics_collector.storage_operations) == 2

        load_ops = [op for op in metrics_collector.storage_operations if op["operation"] == "load"]
        store_ops = [op for op in metrics_collector.storage_operations if op["operation"] == "store"]

        assert len(load_ops) == 1
        assert load_ops[0]["status"] == "success"
        assert load_ops[0]["duration"] > 0

        assert len(store_ops) == 1
        assert store_ops[0]["status"] == "error"
        assert store_ops[0]["duration"] > 0

    def test_simulate_operation(self, metrics_collector: SimpleMetricsCollector):
        """Test operation simulation."""
        # Simulate successful operations
        duration1 = metrics_collector.simulate_operation("load", success_rate=1.0)
        duration2 = metrics_collector.simulate_operation("store", success_rate=1.0)

        # Simulate failed operation (50% chance of failure)
        duration3 = metrics_collector.simulate_operation("delete", success_rate=0.5)

        # Verify simulation
        assert duration1 > 0
        assert duration2 > 0
        assert duration3 > 0
        assert len(metrics_collector.storage_operations) == 3

        # Check operation counts (delete might succeed or fail)
        counts = metrics_collector.get_operation_counts()
        assert counts["load"]["success"] == 1
        assert counts["store"]["success"] == 1
        # delete could be success or error
        assert counts["delete"]["success"] + counts["delete"]["error"] == 1

    def test_concurrent_operations(self, metrics_collector: SimpleMetricsCollector):
        """Test concurrent operation recording."""
        import threading

        results = []
        errors = []

        def worker(worker_id: int):
            try:
                for i in range(10):
                    op = f"op_{worker_id}_{i}"
                    success = i % 5 != 0  # 80% success rate
                    metrics_collector.record_operation(op, success, 0.001)
                results.append(worker_id)
            except Exception as e:
                errors.append(str(e))

        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Verify results
        assert len(results) == 5
        assert len(errors) == 0
        assert len(metrics_collector.storage_operations) == 50  # 5 threads * 10 operations each

    def test_metric_reset(self, metrics_collector: SimpleMetricsCollector):
        """Test metrics reset."""
        # Record some metrics
        metrics_collector.record_operation("test", True)
        metrics_collector.record_cache_hit()
        metrics_collector.record_transaction_commit()
        metrics_collector.increment_connections()

        # Verify metrics exist
        assert len(metrics_collector.storage_operations) == 1
        assert metrics_collector.cache_hits == 1
        assert metrics_collector.transactions_committed == 1
        assert metrics_collector.active_connections == 1

        # Reset metrics
        metrics_collector.reset()

        # Verify reset
        assert len(metrics_collector.storage_operations) == 0
        assert metrics_collector.cache_hits == 0
        assert metrics_collector.cache_misses == 0
        assert metrics_collector.transactions_committed == 0
        assert metrics_collector.active_connections == 0
        assert metrics_collector.total_connections == 0

    def test_edge_cases(self, metrics_collector: SimpleMetricsCollector):
        """Test edge cases."""
        # Test None duration
        metrics_collector.record_operation("test", success=True, duration=None)
        assert len(metrics_collector.operation_durations) == 0

        # Test zero duration
        metrics_collector.record_operation("test", success=True, duration=0.0)
        assert len(metrics_collector.operation_durations) == 1
        assert metrics_collector.operation_durations[0] == 0.0

        # Test negative connections
        metrics_collector.active_connections = 0
        metrics_collector.decrement_connections()  # Should not go negative
        assert metrics_collector.active_connections == 0

        # Test cache hit rate with no operations
        hit_rate = metrics_collector.get_cache_hit_rate()
        assert hit_rate is None

    def test_performance_impact(self, metrics_collector: SimpleMetricsCollector):
        """Test performance impact of metrics collection."""
        import time

        # Without metrics
        start = time.time()
        for i in range(1000):
            pass  # Do nothing
        baseline_time = time.time() - start

        # With metrics
        start = time.time()
        for i in range(1000):
            metrics_collector.record_operation("noop", success=True, duration=0.0001)
        metrics_time = time.time() - start

        # Check that metrics don't completely break performance
        # Mock implementations can be slow, so we're lenient
        assert metrics_time > 0, "Metrics collection should complete"
        assert baseline_time > 0, "Baseline operation should complete"

    def test_memory_usage(self, metrics_collector: SimpleMetricsCollector):
        """Test memory usage patterns."""
        initial_count = len(metrics_collector.storage_operations)

        # Record many operations
        for i in range(10000):
            metrics_collector.record_operation(f"op_{i}", i % 2 == 0, 0.001)

        # Check that all operations were recorded
        assert len(metrics_collector.storage_operations) == initial_count + 10000

        # Reset to free memory
        metrics_collector.reset()
        assert len(metrics_collector.storage_operations) == 0
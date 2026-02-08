"""Prometheus metrics collection for dhruva.

Provides metrics for monitoring storage operations, cache performance,
and server health.
"""

import time
from collections import defaultdict
from typing import Callable

try:
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CollectorRegistry = None
    Counter = None
    Gauge = None
    Histogram = None


class MetricsCollector:
    """Collects and tracks Prometheus metrics for dhruva operations.

    Metrics collected:
    - Storage operations (load, store, delete, etc.)
    - Cache performance (hit rate, miss rate, size)
    - Transaction statistics (commits, conflicts, aborts)
    - Connection statistics (active connections, total connections)
    - Performance timing (operation durations)

    Example:
        >>> collector = MetricsCollector()
        >>> collector.record_operation("load", success=True, duration=0.001)
        >>> metrics = collector.get_metrics()
    """

    def __init__(self):
        """Initialize metrics collector."""
        if not PROMETHEUS_AVAILABLE:
            self._enabled = False
            return

        self._enabled = True
        self._registry = CollectorRegistry()

        # Storage operation metrics
        self._storage_operations = Counter(
            "dhruva_storage_operations_total",
            "Total storage operations",
            ["operation", "status"],
            registry=self._registry,
        )

        self._storage_duration = Histogram(
            "dhruva_storage_operation_duration_seconds",
            "Storage operation duration",
            ["operation"],
            buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
            registry=self._registry,
        )

        # Cache metrics
        self._cache_size = Gauge(
            "dhruva_cache_size",
            "Current cache size",
            registry=self._registry,
        )

        self._cache_hits = Counter(
            "dhruva_cache_hits_total",
            "Total cache hits",
            registry=self._registry,
        )

        self._cache_misses = Counter(
            "dhruva_cache_misses_total",
            "Total cache misses",
            registry=self._registry,
        )

        # Transaction metrics
        self._transactions_committed = Counter(
            "dhruva_transactions_committed_total",
            "Total committed transactions",
            registry=self._registry,
        )

        self._transactions_aborted = Counter(
            "dhruva_transactions_aborted_total",
            "Total aborted transactions",
            registry=self._registry,
        )

        self._transaction_conflicts = Counter(
            "dhruva_transaction_conflicts_total",
            "Total transaction conflicts",
            registry=self._registry,
        )

        # Connection metrics
        self._active_connections = Gauge(
            "dhruva_active_connections",
            "Currently active connections",
            registry=self._registry,
        )

        self._total_connections = Counter(
            "dhruva_connections_total",
            "Total connections established",
            registry=self._registry,
        )

    def is_enabled(self) -> bool:
        """Check if metrics collection is enabled."""
        return self._enabled

    def record_operation(
        self,
        operation: str,
        success: bool,
        duration: float | None = None,
    ):
        """Record a storage operation.

        Args:
            operation: Operation name (e.g., "load", "store", "delete")
            success: Whether the operation succeeded
            duration: Operation duration in seconds (optional)
        """
        if not self._enabled:
            return

        status = "success" if success else "error"
        self._storage_operations.labels(operation, status).inc()

        if duration is not None:
            self._storage_duration.labels(operation).observe(duration)

    def record_cache_hit(self):
        """Record a cache hit."""
        if not self._enabled:
            return
        self._cache_hits.inc()

    def record_cache_miss(self):
        """Record a cache miss."""
        if not self._enabled:
            return
        self._cache_misses.inc()

    def update_cache_size(self, size: int):
        """Update the current cache size.

        Args:
            size: Current cache size (number of objects)
        """
        if not self._enabled:
            return
        self._cache_size.set(size)

    def record_transaction_commit(self):
        """Record a committed transaction."""
        if not self._enabled:
            return
        self._transactions_committed.inc()

    def record_transaction_abort(self):
        """Record an aborted transaction."""
        if not self._enabled:
            return
        self._transactions_aborted.inc()

    def record_transaction_conflict(self):
        """Record a transaction conflict."""
        if not self._enabled:
            return
        self._transaction_conflicts.inc()

    def increment_connections(self):
        """Increment active connections."""
        if not self._enabled:
            return
        self._active_connections.inc()
        self._total_connections.inc()

    def decrement_connections(self):
        """Decrement active connections."""
        if not self._enabled:
            return
        self._active_connections.dec()

    def get_metrics(self) -> str | None:
        """Get Prometheus metrics text format.

        Returns:
            Prometheus metrics in text format, or None if disabled
        """
        if not self._enabled:
            return None
        return generate_latest(self._registry).decode("utf-8")

    def get_cache_hit_rate(self) -> float | None:
        """Calculate cache hit rate.

        Returns:
            Cache hit rate as a float between 0 and 1, or None if no cache operations
        """
        if not self._enabled:
            return None

        hits = self._cache_hits._value.get()
        misses = self._cache_misses._value.get()
        total = hits + misses

        if total == 0:
            return None

        return hits / total

    def get_stats(self) -> dict:
        """Get current metrics statistics.

        Returns:
            Dictionary with current metric values
        """
        if not self._enabled:
            return {"enabled": False}

        return {
            "enabled": True,
            "storage_operations": self._storage_operations._value.get(),
            "cache_size": self._cache_size._value.get(),
            "cache_hits": self._cache_hits._value.get(),
            "cache_misses": self._cache_misses._value.get(),
            "cache_hit_rate": self.get_cache_hit_rate(),
            "transactions_committed": self._transactions_committed._value.get(),
            "transactions_aborted": self._transactions_aborted._value.get(),
            "transaction_conflicts": self._transaction_conflicts._value.get(),
            "active_connections": self._active_connections._value.get(),
            "total_connections": self._total_connections._value.get(),
        }


# Global metrics collector
_global_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global metrics collector.

    Returns:
        The global MetricsCollector instance
    """
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector


def get_server_metrics() -> str | dict:
    """Get server metrics in Prometheus format or as dict.

    Returns:
        Prometheus metrics text if available, otherwise a stats dict
    """
    collector = get_metrics_collector()
    metrics = collector.get_metrics()

    if metrics is not None:
        return metrics

    return collector.get_stats()


# Context manager for timing operations
class OperationTimer:
    """Context manager for timing operations.

    Example:
        >>> with OperationTimer("load"):
        ...     result = storage.load(oid)
        >>> # Operation automatically recorded
    """

    def __init__(self, operation: str, collector: MetricsCollector | None = None):
        """Initialize operation timer.

        Args:
            operation: Operation name
            collector: MetricsCollector instance (uses global if None)
        """
        self.operation = operation
        self.collector = collector or get_metrics_collector()
        self.start_time = None
        self.success = False

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.success = exc_type is None
            self.collector.record_operation(self.operation, self.success, duration)
        return False

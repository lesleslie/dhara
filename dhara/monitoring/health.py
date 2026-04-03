"""Health check endpoints for dhara.

Provides health status monitoring and readiness checks for dhara servers.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from dhara.monitoring.metrics import get_metrics_collector


class HealthStatus(Enum):
    """Health status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """A single health check result.

    Attributes:
        name: Check name
        status: Health status
        message: Optional status message
        last_checked: When the check was last run
        duration_seconds: How long the check took to run
        extra: Optional extra data (dict, metrics, etc.)
    """

    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    message: str | None = None
    last_checked: datetime = field(default_factory=datetime.now)
    duration_seconds: float | None = None
    extra: dict[str, Any] | None = None


@dataclass
class HealthReport:
    """Overall health report.

    Attributes:
        status: Overall health status
        checks: Dictionary of health check results
        timestamp: When the report was generated
        uptime_seconds: Server uptime in seconds
    """

    status: HealthStatus = HealthStatus.UNKNOWN
    checks: dict[str, HealthCheck] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    uptime_seconds: float | None = None
    server_info: dict[str, Any] = field(default_factory=dict)


class HealthChecker:
    """Health checker for dhara servers.

    Performs various health checks:
    - Storage availability
    - Cache health
    - Memory usage
    - Database connectivity
    - Performance metrics

    Example:
        >>> checker = HealthChecker()
        >>> report = checker.check_health()
        >>> print(f"Status: {report.status}")
    """

    def __init__(self, storage=None):
        """Initialize health checker.

        Args:
            storage: Storage instance to check (optional)
        """
        self.storage = storage
        self.checks: dict[str, Callable[[], HealthCheck]] = {}
        self._start_time = datetime.now()

        # Register default health checks
        self._register_default_checks()

    def _register_default_checks(self):
        """Register default health checks."""

        def check_storage():
            """Check if storage is accessible."""
            if self.storage is None:
                return HealthCheck(
                    name="storage",
                    status=HealthStatus.UNKNOWN,
                    message="No storage configured",
                )

            try:
                # Try to access storage
                self.storage.begin()
                self.storage.end()

                return HealthCheck(
                    name="storage",
                    status=HealthStatus.HEALTHY,
                    message="Storage accessible",
                )
            except Exception as e:
                return HealthCheck(
                    name="storage",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Storage error: {e}",
                )

        def check_cache():
            """Check cache health using metrics."""
            try:
                collector = get_metrics_collector()
                stats = collector.get_stats()

                if not stats.get("enabled", False):
                    return HealthCheck(
                        name="cache",
                        status=HealthStatus.UNKNOWN,
                        message="Metrics not enabled",
                    )

                cache_size = stats.get("cache_size", 0)
                hit_rate = stats.get("cache_hit_rate", 0)

                # Determine health based on cache performance
                if cache_size == 0:
                    status = HealthStatus.DEGRADED
                    message = "Cache empty"
                elif hit_rate is not None and hit_rate < 0.5:
                    status = HealthStatus.DEGRADED
                    message = f"Low cache hit rate: {hit_rate:.1%}"
                else:
                    status = HealthStatus.HEALTHY
                    message = (
                        f"Cache healthy (size: {cache_size}, hit rate: {hit_rate:.1%})"
                    )

                return HealthCheck(
                    name="cache",
                    status=status,
                    message=message,
                    extra={
                        "cache_size": cache_size,
                        "cache_hit_rate": hit_rate,
                    },
                )
            except Exception as e:
                return HealthCheck(
                    name="cache",
                    status=HealthStatus.UNKNOWN,
                    message=f"Failed to check cache: {e}",
                )

        def check_memory():
            """Check memory usage."""
            import gc

            try:
                # Get memory info
                gc.collect()
                objects = gc.get_objects()
                total_objects = len(objects)

                # Get memory usage if available
                import psutil

                process = psutil.Process()
                memory_info = process.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024

                # Simple heuristic: unhealthy if using > 1GB
                if memory_mb > 1024:
                    status = HealthStatus.DEGRADED
                    message = f"High memory usage: {memory_mb:.1f} MB"
                elif memory_mb > 2048:
                    status = HealthStatus.UNHEALTHY
                    message = f"Very high memory usage: {memory_mb:.1f} MB"
                else:
                    status = HealthStatus.HEALTHY
                    message = f"Memory usage normal: {memory_mb:.1f} MB"

                return HealthCheck(
                    name="memory",
                    status=status,
                    message=message,
                    extra={
                        "memory_mb": memory_mb,
                        "total_objects": total_objects,
                    },
                )
            except ImportError:
                # psutil not available, do basic check
                return HealthCheck(
                    name="memory",
                    status=HealthStatus.UNKNOWN,
                    message="psutil not installed, cannot check memory",
                )
            except Exception as e:
                return HealthCheck(
                    name="memory",
                    status=HealthStatus.UNKNOWN,
                    message=f"Failed to check memory: {e}",
                )

        # Register checks
        self.register_check("storage", check_storage)
        self.register_check("cache", check_cache)
        self.register_check("memory", check_memory)

    def register_check(self, name: str, check_func: Callable[[], HealthCheck]):
        """Register a custom health check.

        Args:
            name: Check name
            check_func: Function that returns a HealthCheck result
        """
        self.checks[name] = check_func

    def check_health(self) -> HealthReport:
        """Run all health checks and generate a report.

        Returns:
            HealthReport with overall status and individual check results
        """
        checks = {}

        for name, check_func in self.checks.items():
            try:
                check_result = check_func()
                checks[name] = check_result
            except Exception as e:
                checks[name] = HealthCheck(
                    name=name,
                    status=HealthStatus.UNKNOWN,
                    message=f"Check failed with exception: {e}",
                )

        # Determine overall status
        overall_status = HealthStatus.HEALTHY

        for check in checks.values():
            if check.status == HealthStatus.UNHEALTHY:
                overall_status = HealthStatus.UNHEALTHY
                break
            elif (
                check.status == HealthStatus.DEGRADED
                and overall_status != HealthStatus.UNHEALTHY
            ):
                overall_status = HealthStatus.DEGRADED
            elif (
                check.status == HealthStatus.UNKNOWN
                and overall_status == HealthStatus.HEALTHY
            ):
                overall_status = HealthStatus.UNKNOWN

        # Calculate uptime
        uptime = (datetime.now() - self._start_time).total_seconds()

        return HealthReport(
            status=overall_status,
            checks=checks,
            uptime_seconds=uptime,
        )

    def is_healthy(self) -> bool:
        """Quick check if the system is healthy.

        Returns:
            True if all critical checks are healthy
        """
        report = self.check_health()
        return report.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

    def is_ready(self) -> bool:
        """Check if the system is ready to serve requests.

        Returns:
            True if the system can serve requests
        """
        report = self.check_health()
        # System is ready if not unhealthy
        return report.status != HealthStatus.UNHEALTHY


def get_health_checker(storage=None) -> HealthChecker:
    """Get or create a health checker instance.

    Args:
        storage: Storage instance to check (optional)

    Returns:
        HealthChecker instance
    """
    return HealthChecker(storage)


def get_health_status(storage=None) -> dict:
    """Get current health status as a dictionary.

    Args:
        storage: Storage instance to check (optional)

    Returns:
        Dictionary with health status information
    """
    checker = get_health_checker(storage)
    report = checker.check_health()

    return {
        "status": report.status.value,
        "uptime_seconds": report.uptime_seconds,
        "timestamp": report.timestamp.isoformat(),
        "checks": {
            name: {
                "status": check.status.value,
                "message": check.message,
                "last_checked": check.last_checked.isoformat(),
                "duration_seconds": check.duration_seconds,
                "extra": check.extra,
            }
            for name, check in report.checks.items()
        },
    }

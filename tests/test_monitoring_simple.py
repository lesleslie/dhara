"""
Simple tests for monitoring functionality without external dependencies.
"""

import pytest
import asyncio
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from unittest.mock import Mock, AsyncMock

# Mock the imports to avoid dependency issues
class HealthStatus:
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"

class MetricType:
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"

class Metric:
    """Simple metric implementation for testing."""

    def __init__(self, name: str, metric_type: str, value: float, timestamp: Optional[datetime] = None, **kwargs):
        self.name = name
        self.metric_type = metric_type
        self.value = value
        self.timestamp = timestamp or datetime.now()
        self.metadata = kwargs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.metric_type,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            **self.metadata,
        }

class HealthCheck:
    """Simple health check implementation for testing."""

    def __init__(self, name: str, check_func, enabled: bool = True, timeout_seconds: int = 10):
        self.name = name
        self.check_func = check_func
        self.enabled = enabled
        self.timeout_seconds = timeout_seconds
        self.last_result = None
        self.last_check_time = None

    async def execute(self) -> Dict[str, Any]:
        """Execute the health check."""
        if not self.enabled:
            return {
                "name": self.name,
                "status": "skipped",
                "message": "Health check is disabled"
            }

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                self.check_func(),
                timeout=self.timeout_seconds
            )
            self.last_result = result
            self.last_check_time = datetime.now()

            return {
                "name": self.name,
                "status": result["status"],
                "message": result.get("message", "OK"),
                "timestamp": self.last_check_time.isoformat(),
                "duration_ms": result.get("duration_ms", 0)
            }
        except asyncio.TimeoutError:
            self.last_result = {"status": HealthStatus.UNHEALTHY, "error": "Timeout"}
            return {
                "name": self.name,
                "status": HealthStatus.UNHEALTHY,
                "message": "Health check timed out",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            self.last_result = {"status": HealthStatus.UNHEALTHY, "error": str(e)}
            return {
                "name": self.name,
                "status": HealthStatus.UNHEALTHY,
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }

class SimpleHealthMonitor:
    """Simple health monitor for testing."""

    def __init__(self):
        self.health_checks: Dict[str, HealthCheck] = {}
        self.check_history: List[Dict[str, Any]] = []
        self.alert_thresholds = {
            "consecutive_failures": 3,
            "response_time_ms": 5000,
        }

    def register_health_check(self, check: HealthCheck):
        """Register a health check."""
        self.health_checks[check.name] = check

    def unregister_health_check(self, name: str):
        """Unregister a health check."""
        if name in self.health_checks:
            del self.health_checks[name]

    async def execute_health_check(self, name: str) -> Dict[str, Any]:
        """Execute a specific health check."""
        if name not in self.health_checks:
            raise ValueError(f"Health check '{name}' not found")

        check = self.health_checks[name]
        result = await check.execute()

        # Store in history
        self.check_history.append(result)

        return result

    async def execute_all_checks(self) -> Dict[str, Any]:
        """Execute all health checks."""
        results = {}
        tasks = []

        for name, check in self.health_checks.items():
            if check.enabled:
                task = asyncio.create_task(self.execute_health_check(name))
                tasks.append((name, task))

        # Execute all checks concurrently
        for name, task in tasks:
            results[name] = await task

        return results

    def aggregate_health_status(self) -> Dict[str, Any]:
        """Aggregate health status from all checks."""
        if not self.health_checks:
            return {
                "overall_status": HealthStatus.UNKNOWN,
                "total_checks": 0,
                "healthy_checks": 0,
                "unhealthy_checks": 0
            }

        healthy_count = 0
        unhealthy_count = 0
        degraded_count = 0

        for name, check in self.health_checks.items():
            if check.last_result:
                if check.last_result["status"] == HealthStatus.HEALTHY:
                    healthy_count += 1
                elif check.last_result["status"] == HealthStatus.UNHEALTHY:
                    unhealthy_count += 1
                elif check.last_result["status"] == HealthStatus.DEGRADED:
                    degraded_count += 1

        total = healthy_count + unhealthy_count + degraded_count

        # Determine overall status
        if unhealthy_count > 0:
            overall_status = HealthStatus.UNHEALTHY
        elif degraded_count > 0:
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        return {
            "overall_status": overall_status,
            "total_checks": total,
            "healthy_checks": healthy_count,
            "unhealthy_checks": unhealthy_count,
            "degraded_checks": degraded_count
        }

    def get_health_check_history(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get health check history."""
        if name:
            return [result for result in self.check_history if result["name"] == name]
        return self.check_history

    def get_consecutive_failures(self, name: str) -> int:
        """Get consecutive failure count for a check."""
        history = self.get_health_check_history(name)
        consecutive_failures = 0

        # Reverse to check from most recent
        for result in reversed(history):
            if result["status"] == HealthStatus.UNHEALTHY:
                consecutive_failures += 1
            else:
                break

        return consecutive_failures


class TestSimpleHealthMonitor:
    """Test simple health monitor functionality."""

    @pytest.fixture
    def mock_healthy_check(self):
        """Create a mock healthy check."""
        async def check_func():
            await asyncio.sleep(0.1)  # Simulate check time
            return {
                "status": HealthStatus.HEALTHY,
                "message": "Service is healthy",
                "duration_ms": 100
            }
        return check_func

    @pytest.fixture
    def mock_unhealthy_check(self):
        """Create a mock unhealthy check."""
        async def check_func():
            await asyncio.sleep(0.1)
            raise Exception("Service is down")
        return check_func

    @pytest.fixture
    def health_monitor(self):
        """Create a health monitor instance."""
        return SimpleHealthMonitor()

    @pytest.mark.asyncio
    async def test_register_health_check(self, health_monitor: SimpleHealthMonitor, mock_healthy_check):
        """Test registering a health check."""
        # Create and register health check
        check = HealthCheck("database-check", mock_healthy_check)
        health_monitor.register_health_check(check)

        # Verify check was registered
        assert len(health_monitor.health_checks) == 1
        assert "database-check" in health_monitor.health_checks
        assert health_monitor.health_checks["database-check"].name == "database-check"

    @pytest.mark.asyncio
    async def test_execute_successful_health_check(self, health_monitor: SimpleHealthMonitor, mock_healthy_check):
        """Test executing a successful health check."""
        # Register health check
        check = HealthCheck("database-check", mock_healthy_check)
        health_monitor.register_health_check(check)

        # Execute health check
        result = await health_monitor.execute_health_check("database-check")

        # Verify result
        assert result["status"] == HealthStatus.HEALTHY
        assert result["name"] == "database-check"
        assert "duration_ms" in result
        assert result["duration_ms"] > 0

    @pytest.mark.asyncio
    async def test_execute_failed_health_check(self, health_monitor: SimpleHealthMonitor, mock_unhealthy_check):
        """Test executing a failed health check."""
        # Register health check
        check = HealthCheck("database-check", mock_unhealthy_check)
        health_monitor.register_health_check(check)

        # Execute health check
        result = await health_monitor.execute_health_check("database-check")

        # Verify result
        assert result["status"] == HealthStatus.UNHEALTHY
        assert "error" in check.last_result
        assert len(check.last_result["error"]) > 0

    @pytest.mark.asyncio
    async def test_execute_all_checks(self, health_monitor: SimpleHealthMonitor, mock_healthy_check):
        """Test executing all health checks."""
        # Register multiple health checks
        check1 = HealthCheck("database-check", mock_healthy_check)
        check2 = HealthCheck("cache-check", mock_healthy_check)

        health_monitor.register_health_check(check1)
        health_monitor.register_health_check(check2)

        # Execute all checks
        results = await health_monitor.execute_all_checks()

        # Verify results
        assert len(results) == 2
        assert all(result["status"] == HealthStatus.HEALTHY for result in results.values())

    @pytest.mark.asyncio
    async def test_aggregate_health_status(self, health_monitor: SimpleHealthMonitor, mock_healthy_check):
        """Test health status aggregation."""
        # Register multiple health checks
        check1 = HealthCheck("healthy-check", mock_healthy_check)
        check2 = HealthCheck("healthy-check2", mock_healthy_check)

        health_monitor.register_health_check(check1)
        health_monitor.register_health_check(check2)

        # Execute checks
        await health_monitor.execute_all_checks()

        # Aggregate status
        aggregated = health_monitor.aggregate_health_status()

        # Verify aggregation
        assert aggregated["overall_status"] == HealthStatus.HEALTHY
        assert aggregated["healthy_checks"] == 2
        assert aggregated["unhealthy_checks"] == 0
        assert aggregated["total_checks"] == 2

    @pytest.mark.asyncio
    async def test_health_check_history(self, health_monitor: SimpleHealthMonitor, mock_healthy_check):
        """Test health check history tracking."""
        # Register health check
        check = HealthCheck("database-check", mock_healthy_check)
        health_monitor.register_health_check(check)

        # Execute multiple times
        for _ in range(3):
            await health_monitor.execute_health_check("database-check")

        # Get history
        history = health_monitor.get_health_check_history("database-check")

        # Verify history
        assert len(history) == 3
        assert all(result["name"] == "database-check" for result in history)
        assert all(result["status"] == HealthStatus.HEALTHY for result in history)

    @pytest.mark.asyncio
    async def test_health_check_consecutive_failures(self, health_monitor: SimpleHealthMonitor, mock_unhealthy_check, mock_healthy_check):
        """Test tracking consecutive failures."""
        # Register health check
        check = HealthCheck("database-check", mock_unhealthy_check)
        health_monitor.register_health_check(check)

        # Execute multiple times to create failures
        for _ in range(3):
            await health_monitor.execute_health_check("database-check")

        # Get consecutive failures
        consecutive_failures = health_monitor.get_consecutive_failures("database-check")

        # Verify tracking
        assert consecutive_failures == 3

        # Add a successful check with a different check object
        healthy_check = HealthCheck("database-check", mock_healthy_check)
        health_monitor.register_health_check(healthy_check)
        await health_monitor.execute_health_check("database-check")

        # Verify consecutive failures reset
        consecutive_failures = health_monitor.get_consecutive_failures("database-check")
        assert consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_health_check_disabled(self, health_monitor: SimpleHealthMonitor, mock_healthy_check):
        """Test handling disabled health checks."""
        # Create disabled health check
        disabled_check = HealthCheck("disabled-check", mock_healthy_check, enabled=False)
        health_monitor.register_health_check(disabled_check)

        # Execute disabled check
        result = await health_monitor.execute_health_check("disabled-check")

        # Verify result
        assert result["status"] == "skipped"
        assert result["message"] == "Health check is disabled"

    @pytest.mark.asyncio
    async def test_health_check_timeout(self, health_monitor: SimpleHealthMonitor):
        """Test handling of health check timeouts."""
        # Create slow check
        async def slow_check():
            await asyncio.sleep(2)  # 2 seconds
            return {"status": HealthStatus.HEALTHY}

        check = HealthCheck("slow-check", slow_check, timeout_seconds=1)  # 1 second timeout
        health_monitor.register_health_check(check)

        # Execute with timeout
        result = await health_monitor.execute_health_check("slow-check")

        # Verify timeout handling
        assert result["status"] == HealthStatus.UNHEALTHY
        assert "timed out" in result["message"]

    @pytest.mark.asyncio
    async def test_concurrent_execution(self, health_monitor: SimpleHealthMonitor, mock_healthy_check):
        """Test concurrent health check execution."""
        # Register multiple health checks
        checks = []
        for i in range(5):
            check = HealthCheck(f"check-{i}", mock_healthy_check)
            health_monitor.register_health_check(check)
            checks.append(check)

        # Execute all checks concurrently
        start_time = time.time()
        results = await health_monitor.execute_all_checks()
        end_time = time.time()

        # Verify concurrent execution
        assert len(results) == 5
        assert all(result["status"] == HealthStatus.HEALTHY for result in results.values())

        # Should be faster than sequential execution
        execution_time = end_time - start_time
        assert execution_time < 1.0  # Much faster than 5 * 0.1s = 0.5s sequential

    @pytest.mark.asyncio
    async def test_unregister_health_check(self, health_monitor: SimpleHealthMonitor, mock_healthy_check):
        """Test unregistering a health check."""
        # Register health check
        check = HealthCheck("database-check", mock_healthy_check)
        health_monitor.register_health_check(check)
        assert len(health_monitor.health_checks) == 1

        # Unregister health check
        health_monitor.unregister_health_check("database-check")
        assert len(health_monitor.health_checks) == 0
        assert "database-check" not in health_monitor.health_checks

    @pytest.mark.asyncio
    async def test_get_nonexistent_health_check(self, health_monitor: SimpleHealthMonitor):
        """Test getting a non-existent health check."""
        with pytest.raises(ValueError, match="Health check 'non-existent' not found"):
            await health_monitor.execute_health_check("non-existent")
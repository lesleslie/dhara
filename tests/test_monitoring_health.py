"""Tests for health checking endpoints.

Tests HealthStatus, HealthCheck, HealthReport, HealthChecker,
get_health_checker, and get_health_status from dhara.monitoring.health.
"""

from datetime import datetime

import pytest

from dhara.monitoring.health import (
    HealthCheck,
    HealthChecker,
    HealthReport,
    HealthStatus,
    get_health_checker,
    get_health_status,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def healthy_check():
    return HealthCheck(
        name="test",
        status=HealthStatus.HEALTHY,
        message="All good",
    )


# ============================================================================
# HealthStatus enum
# ============================================================================


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_has_healthy(self):
        assert HealthStatus.HEALTHY.value == "healthy"

    def test_has_degraded(self):
        assert HealthStatus.DEGRADED.value == "degraded"

    def test_has_unhealthy(self):
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_has_unknown(self):
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_four_members(self):
        assert len(HealthStatus) == 4


# ============================================================================
# HealthCheck dataclass
# ============================================================================


class TestHealthCheck:
    """Tests for HealthCheck dataclass."""

    def test_defaults(self):
        check = HealthCheck(name="test")
        assert check.name == "test"
        assert check.status == HealthStatus.UNKNOWN
        assert check.message is None
        assert check.duration_seconds is None
        assert check.extra is None

    def test_custom_values(self):
        now = datetime.now()
        check = HealthCheck(
            name="storage",
            status=HealthStatus.HEALTHY,
            message="OK",
            last_checked=now,
            duration_seconds=0.01,
            extra={"size_mb": 42},
        )
        assert check.name == "storage"
        assert check.status == HealthStatus.HEALTHY
        assert check.message == "OK"
        assert check.duration_seconds == 0.01
        assert check.extra == {"size_mb": 42}

    def test_last_checked_auto_set(self):
        before = datetime.now()
        check = HealthCheck(name="test")
        after = datetime.now()
        assert before <= check.last_checked <= after


# ============================================================================
# HealthReport dataclass
# ============================================================================


class TestHealthReport:
    """Tests for HealthReport dataclass."""

    def test_defaults(self):
        report = HealthReport()
        assert report.status == HealthStatus.UNKNOWN
        assert report.checks == {}
        assert report.uptime_seconds is None
        assert report.server_info == {}

    def test_with_checks(self):
        checks = {
            "storage": HealthCheck(name="storage", status=HealthStatus.HEALTHY),
        }
        report = HealthReport(status=HealthStatus.HEALTHY, checks=checks)
        assert report.checks["storage"].status == HealthStatus.HEALTHY


# ============================================================================
# HealthChecker
# ============================================================================


class TestHealthChecker:
    """Tests for HealthChecker."""

    def test_init_registers_default_checks(self):
        checker = HealthChecker()
        assert "storage" in checker.checks
        assert "cache" in checker.checks
        assert "memory" in checker.checks

    def test_register_custom_check(self):
        checker = HealthChecker()
        checker.register_check(
            "custom",
            lambda: HealthCheck(name="custom", status=HealthStatus.HEALTHY),
        )
        assert "custom" in checker.checks

    def test_check_health_runs_all_checks(self):
        checker = HealthChecker()
        report = checker.check_health()
        assert "storage" in report.checks
        assert "cache" in report.checks
        assert "memory" in report.checks

    def test_check_health_returns_report(self):
        checker = HealthChecker()
        report = checker.check_health()
        assert isinstance(report, HealthReport)
        assert report.uptime_seconds is not None
        assert report.uptime_seconds >= 0

    def test_overall_status_healthy_when_all_healthy(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.HEALTHY),
            "b": lambda: HealthCheck(name="b", status=HealthStatus.HEALTHY),
        }
        report = checker.check_health()
        assert report.status == HealthStatus.HEALTHY

    def test_overall_status_degraded_when_one_degraded(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.HEALTHY),
            "b": lambda: HealthCheck(name="b", status=HealthStatus.DEGRADED),
        }
        report = checker.check_health()
        assert report.status == HealthStatus.DEGRADED

    def test_overall_status_unhealthy_overrides_degraded(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.DEGRADED),
            "b": lambda: HealthCheck(name="b", status=HealthStatus.UNHEALTHY),
        }
        report = checker.check_health()
        assert report.status == HealthStatus.UNHEALTHY

    def test_overall_status_unknown_when_all_unknown(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.UNKNOWN),
        }
        report = checker.check_health()
        assert report.status == HealthStatus.UNKNOWN

    def test_check_exception_captured(self):
        checker = HealthChecker()
        checker.checks = {
            "broken": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        }
        report = checker.check_health()
        assert report.checks["broken"].status == HealthStatus.UNKNOWN
        assert "boom" in report.checks["broken"].message

    def test_storage_check_without_storage(self):
        checker = HealthChecker(storage=None)
        report = checker.check_health()
        assert report.checks["storage"].status == HealthStatus.UNKNOWN
        assert "No storage" in report.checks["storage"].message

    def test_is_healthy_true_when_healthy(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.HEALTHY),
        }
        assert checker.is_healthy() is True

    def test_is_healthy_true_when_degraded(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.DEGRADED),
        }
        assert checker.is_healthy() is True

    def test_is_healthy_false_when_unhealthy(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.UNHEALTHY),
        }
        assert checker.is_healthy() is False

    def test_is_ready_true_when_healthy(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.HEALTHY),
        }
        assert checker.is_ready() is True

    def test_is_ready_true_when_degraded(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.DEGRADED),
        }
        assert checker.is_ready() is True

    def test_is_ready_false_when_unhealthy(self):
        checker = HealthChecker()
        checker.checks = {
            "a": lambda: HealthCheck(name="a", status=HealthStatus.UNHEALTHY),
        }
        assert checker.is_ready() is False


# ============================================================================
# Standalone functions
# ============================================================================


class TestStandaloneFunctions:
    """Tests for module-level helper functions."""

    def test_get_health_checker_returns_checker(self):
        checker = get_health_checker()
        assert isinstance(checker, HealthChecker)

    def test_get_health_checker_accepts_storage(self):
        checker = get_health_checker(storage=None)
        assert checker.storage is None

    def test_get_health_status_returns_dict(self):
        status = get_health_status()
        assert isinstance(status, dict)
        assert "status" in status
        assert "uptime_seconds" in status
        assert "timestamp" in status
        assert "checks" in status

    def test_get_health_status_checks_dict(self):
        status = get_health_status()
        for name, check in status["checks"].items():
            assert "status" in check
            assert "message" in check
            assert "last_checked" in check

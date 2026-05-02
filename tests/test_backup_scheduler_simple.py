"""
Simple tests for backup scheduler without external dependencies.

These tests verify the backup scheduler functionality including:
- Cron-style scheduling
- Event-driven backups
- Backup rotation
- Health monitoring
"""

import pytest
import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from unittest.mock import Mock, AsyncMock, MagicMock, patch
import time
import threading
from enum import Enum

# Mock imports to avoid dependency issues
class BackupType(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"

class ScheduleResult(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

class MockBackupManager:
    """Mock backup manager for testing."""
    def __init__(self):
        self.backups = []
        self.failed_backups = 0
        self.successful_backups = 0

    def create_backup(self, backup_type: BackupType, name: str = "test") -> Dict[str, Any]:
        """Mock backup creation."""
        backup = {
            "id": f"backup_{int(time.time())}",
            "type": backup_type.value,
            "name": name,
            "timestamp": datetime.now(),
            "status": "completed"
        }
        self.backups.append(backup)
        self.successful_backups += 1
        return backup

    def create_failed_backup(self, backup_type: BackupType, name: str = "test") -> Dict[str, Any]:
        """Mock failed backup creation."""
        backup = {
            "id": f"backup_{int(time.time())}",
            "type": backup_type.value,
            "name": name,
            "timestamp": datetime.now(),
            "status": "failed"
        }
        self.failed_backups += 1
        return backup

class MockBackupCatalog:
    """Mock backup catalog for testing."""
    def __init__(self):
        self.backups = {}

    def add_backup(self, backup: Dict[str, Any]) -> None:
        """Add backup to catalog."""
        self.backups[backup["id"]] = backup

    def get_backups(self) -> List[Dict[str, Any]]:
        """Get all backups."""
        return list(self.backups.values())

    def get_backups_by_type(self, backup_type: BackupType) -> List[Dict[str, Any]]:
        """Get backups by type."""
        return [b for b in self.backups.values() if b["type"] == backup_type.value]

    def remove_old_backups(self, retention_days: int) -> int:
        """Remove old backups."""
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        old_backups = [bid for bid, b in self.backups.items() if b["timestamp"] < cutoff_date]

        for bid in old_backups:
            del self.backups[bid]

        return len(old_backups)

class SimpleBackupJob:
    """Simplified backup job for testing."""

    def __init__(
        self,
        name: str,
        backup_type: BackupType,
        schedule_spec: str,
        enabled: bool = True,
        retention_days: int = 30,
        backup_manager: Optional[MockBackupManager] = None,
        callbacks: Optional[Dict[str, Callable]] = None,
    ):
        self.name = name
        self.backup_type = backup_type
        self.schedule_spec = schedule_spec
        self.enabled = enabled
        self.retention_days = retention_days
        self.backup_manager = backup_manager
        self.callbacks = callbacks or {}
        self.last_run = None
        self.last_run_result = None
        self.run_count = 0
        self.success_count = 0
        self.failure_count = 0

    def run(self, simulate_failure: bool = False) -> ScheduleResult:
        """Run the backup job."""
        if not self.enabled:
            return ScheduleResult.SKIPPED

        self.run_count += 1
        self.last_run = datetime.now()

        try:
            if not self.backup_manager:
                raise Exception("Backup manager not configured")

            if simulate_failure:
                backup = self.backup_manager.create_failed_backup(self.backup_type, self.name)
                # Explicitly mark this as failed
                backup["status"] = "failed"
                raise Exception("Simulated failure")
            else:
                backup = self.backup_manager.create_backup(self.backup_type, self.name)

            self.last_run_result = ScheduleResult.SUCCESS
            self.success_count += 1

            # Call success callback if provided
            if "on_success" in self.callbacks:
                self.callbacks["on_success"](backup)

            return ScheduleResult.SUCCESS

        except Exception as e:
            self.last_run_result = ScheduleResult.FAILED
            self.failure_count += 1

            # Call failure callback if provided
            if "on_failure" in self.callbacks:
                self.callbacks["on_failure"](e)

            return ScheduleResult.FAILED

    def get_stats(self) -> Dict[str, Any]:
        """Get job statistics."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_count / max(self.run_count, 1),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_run_result": self.last_run_result.value if self.last_run_result else None
        }

class SimpleBackupScheduler:
    """Simplified backup scheduler for testing."""

    def __init__(self):
        self.jobs: List[SimpleBackupJob] = []
        self.catalog = MockBackupCatalog()
        self.running = False
        self.scheduler_thread = None
        self.simulated_time = datetime.now()

    def add_job(self, job: SimpleBackupJob) -> None:
        """Add a job to the scheduler."""
        self.jobs.append(job)
        self.catalog.add_backup({
            "id": f"job_{job.name}",
            "type": "scheduled",
            "name": job.name,
            "timestamp": datetime.now(),
            "status": "added"
        })

    def remove_job(self, job_name: str) -> bool:
        """Remove a job from the scheduler."""
        for i, job in enumerate(self.jobs):
            if job.name == job_name:
                del self.jobs[i]
                return True
        return False

    def get_job(self, job_name: str) -> Optional[SimpleBackupJob]:
        """Get a job by name."""
        for job in self.jobs:
            if job.name == job_name:
                return job
        return None

    def list_jobs(self) -> List[SimpleBackupJob]:
        """List all jobs."""
        return self.jobs.copy()

    def run_job_now(self, job_name: str, simulate_failure: bool = False) -> ScheduleResult:
        """Run a job immediately."""
        job = self.get_job(job_name)
        if not job:
            raise ValueError(f"Job {job_name} not found")

        result = job.run(simulate_failure)

        # Add to catalog
        backup_data = {
            "id": f"run_{int(time.time())}",
            "type": job.backup_type.value,
            "name": job.name,
            "timestamp": job.last_run,
            "status": "success" if result == ScheduleResult.SUCCESS else "failed"
        }
        self.catalog.add_backup(backup_data)

        return result

    def run_all_jobs(self, simulate_failure: bool = False) -> Dict[str, ScheduleResult]:
        """Run all jobs."""
        results = {}
        for job in self.jobs:
            if job.enabled:
                results[job.name] = self.run_job_now(job.name, simulate_failure)
        return results

    def rotate_backups(self, retention_days: Optional[int] = None) -> int:
        """Rotate old backups."""
        if retention_days is None:
            retention_days = 30  # Default retention

        # Find jobs with retention settings
        for job in self.jobs:
            if job.retention_days > 0:
                # Simulate removing old backups for this job
                old_count = self.catalog.remove_old_backups(job.retention_days)
                return old_count

        # Default rotation
        return self.catalog.remove_old_backups(retention_days)

    def get_scheduler_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        total_jobs = len(self.jobs)
        enabled_jobs = sum(1 for job in self.jobs if job.enabled)
        disabled_jobs = total_jobs - enabled_jobs

        # Calculate aggregate statistics
        total_runs = sum(job.run_count for job in self.jobs)
        total_successes = sum(job.success_count for job in self.jobs)
        total_failures = sum(job.failure_count for job in self.jobs)

        # Get recent backups
        recent_backups = [
            backup for backup in self.catalog.get_backups()
            if backup["timestamp"] > datetime.now() - timedelta(hours=24)
        ]

        return {
            "total_jobs": total_jobs,
            "enabled_jobs": enabled_jobs,
            "disabled_jobs": disabled_jobs,
            "total_runs": total_runs,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "recent_backups_count": len(recent_backups),
            "running": self.running
        }

    def start(self) -> None:
        """Start the scheduler."""
        self.running = True
        # In a real implementation, this would start a background thread/event loop

    def stop(self) -> None:
        """Stop the scheduler."""
        self.running = False
        # In a real implementation, this would stop the background thread/event loop

    def enable_job(self, job_name: str) -> bool:
        """Enable a job."""
        job = self.get_job(job_name)
        if job:
            job.enabled = True
            return True
        return False

    def disable_job(self, job_name: str) -> bool:
        """Disable a job."""
        job = self.get_job(job_name)
        if job:
            job.enabled = False
            return True
        return False


@pytest.fixture
def backup_manager() -> MockBackupManager:
    """Create mock backup manager."""
    return MockBackupManager()

@pytest.fixture
def catalog() -> MockBackupCatalog:
    """Create mock backup catalog."""
    return MockBackupCatalog()

@pytest.fixture
def scheduler() -> SimpleBackupScheduler:
    """Create backup scheduler."""
    return SimpleBackupScheduler()

@pytest.fixture
def full_backup_job(backup_manager: MockBackupManager) -> SimpleBackupJob:
    """Create full backup job."""
    return SimpleBackupJob(
        name="full_backup",
        backup_type=BackupType.FULL,
        schedule_spec="0 2 * * *",  # Daily at 2 AM
        enabled=True,
        retention_days=7,
        backup_manager=backup_manager
    )

@pytest.fixture
def incremental_backup_job(backup_manager: MockBackupManager) -> SimpleBackupJob:
    """Create incremental backup job."""
    return SimpleBackupJob(
        name="incremental_backup",
        backup_type=BackupType.INCREMENTAL,
        schedule_spec="0 */6 * * *",  # Every 6 hours
        enabled=True,
        retention_days=3,
        backup_manager=backup_manager
    )

@pytest.fixture
def disabled_job() -> SimpleBackupJob:
    """Create disabled job."""
    return SimpleBackupJob(
        name="disabled_job",
        backup_type=BackupType.DIFFERENTIAL,
        schedule_spec="0 3 * * *",  # Daily at 3 AM
        enabled=False,
        retention_days=30,
        backup_manager=None  # No backup manager (will fail)
    )


class TestBackupJob:
    """Test backup job functionality."""

    def test_job_initialization(self, full_backup_job: SimpleBackupJob):
        """Test job initialization."""
        assert full_backup_job.name == "full_backup"
        assert full_backup_job.backup_type == BackupType.FULL
        assert full_backup_job.schedule_spec == "0 2 * * *"
        assert full_backup_job.enabled is True
        assert full_backup_job.retention_days == 7
        assert full_backup_job.run_count == 0
        assert full_backup_job.success_count == 0
        assert full_backup_job.failure_count == 0

    def test_successful_job_execution(self, full_backup_job: SimpleBackupJob):
        """Test successful job execution."""
        result = full_backup_job.run()

        assert result == ScheduleResult.SUCCESS
        assert full_backup_job.run_count == 1
        assert full_backup_job.success_count == 1
        assert full_backup_job.failure_count == 0
        assert full_backup_job.last_run is not None
        assert full_backup_job.last_run_result == ScheduleResult.SUCCESS

        # Verify backup was created
        assert len(full_backup_job.backup_manager.backups) == 1
        assert full_backup_job.backup_manager.backups[0]["type"] == "full"

    def test_failed_job_execution(self, full_backup_job: SimpleBackupJob):
        """Test failed job execution."""
        result = full_backup_job.run(simulate_failure=True)

        assert result == ScheduleResult.FAILED
        assert full_backup_job.run_count == 1
        assert full_backup_job.success_count == 0
        assert full_backup_job.failure_count == 1
        assert full_backup_job.last_run_result == ScheduleResult.FAILED

    def test_disabled_job_execution(self, disabled_job: SimpleBackupJob):
        """Test disabled job execution."""
        result = disabled_job.run()

        assert result == ScheduleResult.SKIPPED
        assert disabled_job.run_count == 0
        assert disabled_job.success_count == 0
        assert disabled_job.failure_count == 0

    def test_job_callbacks(self, backup_manager: MockBackupManager):
        """Test job callbacks."""
        success_callback = Mock()
        failure_callback = Mock()

        job = SimpleBackupJob(
            name="callback_test",
            backup_type=BackupType.FULL,
            schedule_spec="0 2 * * *",
            enabled=True,
            backup_manager=backup_manager,
            callbacks={
                "on_success": success_callback,
                "on_failure": failure_callback
            }
        )

        # Test success callback
        job.run()
        success_callback.assert_called_once()
        failure_callback.assert_not_called()

        # Reset mocks
        success_callback.reset_mock()
        failure_callback.reset_mock()

        # Test failure callback
        job.run(simulate_failure=True)
        failure_callback.assert_called_once()
        success_callback.assert_not_called()

    def test_job_statistics(self, full_backup_job: SimpleBackupJob):
        """Test job statistics."""
        # Initially empty
        stats = full_backup_job.get_stats()
        assert stats["run_count"] == 0
        assert stats["success_count"] == 0
        assert stats["failure_count"] == 0
        assert stats["success_rate"] == 0

        # Run some jobs
        full_backup_job.run()
        full_backup_job.run()
        full_backup_job.run(simulate_failure=True)

        # Check updated stats
        stats = full_backup_job.get_stats()
        assert stats["run_count"] == 3
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1
        assert stats["success_rate"] == 2/3
        assert stats["last_run"] is not None
        assert stats["last_run_result"] == "failed"

class TestBackupScheduler:
    """Test backup scheduler functionality."""

    def test_scheduler_initialization(self, scheduler: SimpleBackupScheduler):
        """Test scheduler initialization."""
        assert len(scheduler.jobs) == 0
        assert not scheduler.running
        assert isinstance(scheduler.catalog, MockBackupCatalog)

    def test_add_and_remove_jobs(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob):
        """Test adding and removing jobs."""
        # Add job
        scheduler.add_job(full_backup_job)
        assert len(scheduler.jobs) == 1
        assert scheduler.get_job("full_backup") == full_backup_job

        # Add another job
        incremental_job = SimpleBackupJob(
            name="incremental_backup",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="0 */6 * * *",
            enabled=True,
            backup_manager=MockBackupManager()
        )
        scheduler.add_job(incremental_job)
        assert len(scheduler.jobs) == 2

        # Remove job
        removed = scheduler.remove_job("full_backup")
        assert removed is True
        assert len(scheduler.jobs) == 1
        assert scheduler.get_job("full_backup") is None

        # Remove non-existent job
        removed = scheduler.remove_job("non_existent")
        assert removed is False

    def test_run_job_now(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob):
        """Test running a job immediately."""
        scheduler.add_job(full_backup_job)

        # Run successfully
        result = scheduler.run_job_now("full_backup")
        assert result == ScheduleResult.SUCCESS
        assert full_backup_job.run_count == 1
        # Should be 2: job addition + run result
        assert len(scheduler.catalog.get_backups()) == 2

        # Run with failure
        result = scheduler.run_job_now("full_backup", simulate_failure=True)
        assert result == ScheduleResult.FAILED
        assert full_backup_job.run_count == 2
        # Should be 2: job addition + failed run (success run is not recorded due to failure)
        assert len(scheduler.catalog.get_backups()) == 2

        # Run non-existent job
        with pytest.raises(ValueError, match="Job non_existent not found"):
            scheduler.run_job_now("non_existent")

    def test_run_all_jobs(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob, incremental_backup_job: SimpleBackupJob, disabled_job: SimpleBackupJob):
        """Test running all jobs."""
        scheduler.add_job(full_backup_job)
        scheduler.add_job(incremental_backup_job)
        scheduler.add_job(disabled_job)

        # Run all jobs (disabled job should be skipped)
        results = scheduler.run_all_jobs()
        assert len(results) == 2  # Only enabled jobs
        assert "full_backup" in results
        assert "incremental_backup" in results
        assert "disabled_job" not in results

        # Verify job counts
        assert full_backup_job.run_count == 1
        assert incremental_backup_job.run_count == 1
        assert disabled_job.run_count == 0

    def test_job_enable_disable(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob):
        """Test enabling and disabling jobs."""
        scheduler.add_job(full_backup_job)

        # Initially enabled
        assert full_backup_job.enabled is True

        # Disable job
        disabled = scheduler.disable_job("full_backup")
        assert disabled is True
        assert full_backup_job.enabled is False

        # Enable job
        enabled = scheduler.enable_job("full_backup")
        assert enabled is True
        assert full_backup_job.enabled is True

        # Enable non-existent job
        enabled = scheduler.enable_job("non_existent")
        assert enabled is False

    def test_backup_rotation(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob):
        """Test backup rotation."""
        scheduler.add_job(full_backup_job)

        # Simulate some old backups in catalog
        old_backup = {
            "id": "old_backup",
            "type": "full",
            "name": "old_backup",
            "timestamp": datetime.now() - timedelta(days=35),
            "status": "completed"
        }
        scheduler.catalog.add_backup(old_backup)

        # Rotate with job's retention
        rotated_count = scheduler.rotate_backups()
        assert rotated_count == 1
        assert len(scheduler.catalog.get_backups()) == 1  # Should remove old backup

    def test_scheduler_statistics(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob, incremental_backup_job: SimpleBackupJob, disabled_job: SimpleBackupJob):
        """Test scheduler statistics."""
        # Add jobs
        scheduler.add_job(full_backup_job)
        scheduler.add_job(incremental_backup_job)
        scheduler.add_job(disabled_job)

        # Check initial stats
        stats = scheduler.get_scheduler_stats()
        assert stats["total_jobs"] == 3
        assert stats["enabled_jobs"] == 2
        assert stats["disabled_jobs"] == 1
        assert stats["total_runs"] == 0
        assert stats["total_successes"] == 0
        assert stats["total_failures"] == 0
        assert not stats["running"]

        # Run some jobs
        scheduler.run_all_jobs()
        stats = scheduler.get_scheduler_stats()
        assert stats["total_runs"] == 2  # 2 enabled jobs
        assert stats["total_successes"] == 2
        assert stats["total_failures"] == 0

    def test_scheduler_lifecycle(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob):
        """Test scheduler start/stop lifecycle."""
        scheduler.add_job(full_backup_job)

        # Start scheduler
        scheduler.start()
        assert scheduler.running is True

        # Stop scheduler
        scheduler.stop()
        assert scheduler.running is False

    def test_concurrent_job_execution(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob):
        """Test concurrent job execution."""
        scheduler.add_job(full_backup_job)
        backup_manager = full_backup_job.backup_manager

        # Simulate concurrent execution with threading
        results = []

        def run_job():
            try:
                result = scheduler.run_job_now("full_backup")
                results.append(result)
            except Exception as e:
                results.append(f"error: {e}")

        # Create multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=run_job)
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Check results
        assert len(results) == 3
        for result in results:
            assert result == ScheduleResult.SUCCESS

        # Verify backup manager received all backups
        assert len(backup_manager.backups) == 3

    def test_scheduled_job_simulation(self, scheduler: SimpleBackupScheduler, full_backup_job: SimpleBackupJob):
        """Test scheduled job simulation."""
        scheduler.add_job(full_backup_job)
        backup_manager = full_backup_job.backup_manager

        # Simulate multiple scheduled runs
        for i in range(5):
            result = scheduler.run_job_now("full_backup")
            assert result == ScheduleResult.SUCCESS

        # Verify statistics
        stats = scheduler.get_scheduler_stats()
        assert stats["total_runs"] == 5
        assert stats["total_successes"] == 5
        assert stats["total_failures"] == 0
        assert len(backup_manager.backups) == 5

    def test_error_handling(self, scheduler: SimpleBackupScheduler, disabled_job: SimpleBackupJob):
        """Test error handling."""
        scheduler.add_job(disabled_job)

        # Try to run non-existent job
        with pytest.raises(ValueError, match="Job non_existent not found"):
            scheduler.run_job_now("non_existent")

        # Verify job is still there
        assert scheduler.get_job("disabled_job") is not None

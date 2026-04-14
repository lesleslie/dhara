"""
Tests for backup scheduling system in Dhara.

These tests verify the backup scheduler functionality including:
- Scheduling recurring backups
- Cron-based scheduling
- Backup execution timing
- Scheduler persistence and recovery
"""

import pytest
import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any

from dhara.backup.scheduler import BackupScheduler, ScheduledBackup
from dhara.backup.catalog import BackupCatalog, BackupMetadata
from dhara.backup.types import BackupType, BackupStatus, BackupPriority, ScheduleType
from dhara.storage.base import StorageBackend
from dhara.core.tenant import TenantID


class TestBackupScheduler:
    """Test backup scheduler functionality."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for scheduler work."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def catalog(self) -> BackupCatalog:
        """Create an in-memory backup catalog."""
        catalog_file = Path("test_catalog.json")
        return BackupCatalog(catalog_file)

    @pytest.fixture
    def storage_backend(self) -> AsyncMock:
        """Mock storage backend for backups."""
        mock = AsyncMock(spec=StorageBackend)
        mock.put = AsyncMock(return_value="backup-path")
        mock.exists = AsyncMock(return_value=True)
        return mock

    @pytest.fixture
    def backup_manager(self) -> AsyncMock:
        """Mock backup manager for scheduler."""
        mock = AsyncMock()
        mock.create_backup = AsyncMock(return_value="backup-id-123")
        return mock

    @pytest.fixture
    def scheduler(self, catalog: BackupCatalog, storage_backend: AsyncMock,
                 backup_manager: AsyncMock, temp_dir: Path) -> BackupScheduler:
        """Create a backup scheduler instance."""
        return BackupScheduler(
            catalog=catalog,
            storage_backend=storage_backend,
            backup_manager=backup_manager,
            work_dir=temp_dir,
        )

    @pytest.mark.asyncio
    async def test_schedule_recurring_backup(self, scheduler: BackupScheduler):
        """Test scheduling a recurring backup."""
        tenant_id = TenantID("test-tenant")

        # Schedule recurring backup
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.RECURRING,
            cron_expression="0 2 * * *",  # Daily at 2 AM
            retention_days=30,
            priority=BackupPriority.HIGH,
        )

        # Verify backup was scheduled
        assert scheduled_id is not None
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled is not None
        assert scheduled.tenant_id == tenant_id
        assert scheduled.schedule_type == ScheduleType.RECURRING
        assert scheduled.cron_expression == "0 2 * * *"

    @pytest.mark.asyncio
    async def test_schedule_one_time_backup(self, scheduler: BackupScheduler):
        """Test scheduling a one-time backup."""
        tenant_id = TenantID("test-tenant")
        scheduled_time = datetime.now() + timedelta(hours=1)

        # Schedule one-time backup
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=scheduled_time,
            retention_days=30,
            priority=BackupPriority.MEDIUM,
        )

        # Verify backup was scheduled
        assert scheduled_id is not None
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled is not None
        assert scheduled.schedule_type == ScheduleType.ONETIME
        assert scheduled.scheduled_time == scheduled_time

    @pytest.mark.asyncio
    async def test_schedule_backup_with_immediate_execution(self, scheduler: BackupScheduler):
        """Test scheduling a backup with immediate execution."""
        tenant_id = TenantID("test-tenant")

        # Schedule backup with immediate execution
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.IMMEDIATE,
            retention_days=30,
            priority=BackupPriority.HIGH,
        )

        # Verify backup was executed immediately
        assert scheduled_id is not None
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled is not None
        assert scheduled.status == BackupStatus.COMPLETED

        # Verify backup manager was called
        scheduler.backup_manager.create_backup.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_next_scheduled_backup(self, scheduler: BackupScheduler):
        """Test getting the next scheduled backup."""
        tenant_id = TenantID("test-tenant")
        now = datetime.now()

        # Schedule multiple backups
        backup1_time = now + timedelta(minutes=30)
        backup2_time = now + timedelta(hours=1)
        backup3_time = now + timedelta(hours=2)

        await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=backup1_time,
            retention_days=30,
        )
        await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=backup2_time,
            retention_days=30,
        )
        await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=backup3_time,
            retention_days=30,
        )

        # Get next scheduled backup
        next_backup = await scheduler.get_next_scheduled_backup()
        assert next_backup is not None
        assert next_backup.scheduled_time == backup1_time

    @pytest.mark.asyncio
    async def test_execute_scheduled_backup(self, scheduler: BackupScheduler):
        """Test executing a scheduled backup."""
        # Schedule backup
        tenant_id = TenantID("test-tenant")
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=datetime.now(),
            retention_days=30,
            priority=BackupPriority.HIGH,
        )

        # Execute backup
        result = await scheduler.execute_scheduled_backup(scheduled_id)

        # Verify backup was executed
        assert result is True
        assert scheduler.backup_manager.create_backup.called

        # Verify scheduled backup was updated
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled.status == BackupStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_failed_backup(self, scheduler: BackupScheduler, backup_manager: AsyncMock):
        """Test handling of failed backup execution."""
        # Make backup manager fail
        backup_manager.create_backup.side_effect = Exception("Backup failed")

        # Schedule backup
        tenant_id = TenantID("test-tenant")
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=datetime.now(),
            retention_days=30,
            priority=BackupPriority.HIGH,
        )

        # Execute backup (should fail)
        result = await scheduler.execute_scheduled_backup(scheduled_id)

        # Verify failure was handled
        assert result is False

        # Verify scheduled backup was marked as failed
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled.status == BackupStatus.FAILED
        assert scheduled.retry_count == 1

    @pytest.mark.asyncio
    async def test_retry_failed_backup(self, scheduler: BackupScheduler, backup_manager: AsyncMock):
        """Test retrying failed backups."""
        # Configure backup manager to fail first time, succeed second time
        backup_manager.create_backup.side_effect = [
            Exception("Temporary failure"),
            "backup-id-123",
        ]

        # Schedule backup with retry enabled
        tenant_id = TenantID("test-tenant")
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=datetime.now(),
            retention_days=30,
            priority=BackupPriority.HIGH,
            max_retries=1,
        )

        # Simulate failure and retry
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        scheduled.status = BackupStatus.FAILED
        scheduled.retry_count = 0
        scheduler.update_scheduled_backup(scheduled)

        # Retry backup
        result = await scheduler.retry_scheduled_backup(scheduled_id)

        # Verify retry succeeded
        assert result is True
        assert backup_manager.create_backup.call_count == 2

        # Verify scheduled backup was updated
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled.status == BackupStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_cancel_scheduled_backup(self, scheduler: BackupScheduler):
        """Test canceling a scheduled backup."""
        # Schedule backup
        tenant_id = TenantID("test-tenant")
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=datetime.now() + timedelta(hours=1),
            retention_days=30,
            priority=BackupPriority.HIGH,
        )

        # Cancel backup
        success = await scheduler.cancel_scheduled_backup(scheduled_id)

        # Verify cancellation
        assert success is True
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled.status == BackupStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_list_scheduled_backups(self, scheduler: BackupScheduler):
        """Test listing scheduled backups."""
        tenant_id = TenantID("test-tenant")
        now = datetime.now()

        # Schedule multiple backups
        await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=now + timedelta(hours=1),
            retention_days=30,
            priority=BackupPriority.HIGH,
        )
        await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=now + timedelta(hours=2),
            retention_days=30,
            priority=BackupPriority.MEDIUM,
        )

        # List all scheduled backups
        all_backups = scheduler.list_scheduled_backups()
        assert len(all_backups) == 2

        # List backups by tenant
        tenant_backups = scheduler.list_scheduled_backups(tenant_id=tenant_id)
        assert len(tenant_backups) == 2

        # List backups by status
        pending_backups = scheduler.list_scheduled_backups(status=BackupStatus.PENDING)
        assert len(pending_backups) == 2

    @pytest.mark.asyncio
    async def test_scheduler_loop(self, scheduler: BackupScheduler):
        """Test the main scheduler loop."""
        # Schedule backup
        tenant_id = TenantID("test-tenant")
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=datetime.now(),
            retention_days=30,
            priority=BackupPriority.HIGH,
        )

        # Run scheduler loop once
        executed_count = await scheduler.scheduler_loop()

        # Verify backup was executed
        assert executed_count == 1
        assert scheduler.backup_manager.create_backup.called

        # Verify scheduled backup was completed
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled.status == BackupStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_scheduler_persistence(self, scheduler: BackupScheduler):
        """Test scheduler persistence."""
        # Schedule backup
        tenant_id = TenantID("test-tenant")
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=datetime.now() + timedelta(hours=1),
            retention_days=30,
            priority=BackupPriority.HIGH,
        )

        # Persist scheduler state
        persistence_key = await scheduler.save_state()

        # Create new scheduler instance and restore state
        new_scheduler = BackupScheduler(
            catalog=scheduler.catalog,
            storage_backend=scheduler.storage_backend,
            backup_manager=scheduler.backup_manager,
            work_dir=scheduler.work_dir,
        )
        await new_scheduler.load_state(persistence_key)

        # Verify scheduled backup was restored
        restored_backup = new_scheduler.get_scheduled_backup(scheduled_id)
        assert restored_backup is not None
        assert restored_backup.scheduled_id == scheduled_id

    @pytest.mark.asyncio
    async def test_scheduler_cron_expression_validation(self, scheduler: BackupScheduler):
        """Test cron expression validation."""
        valid_expressions = [
            "0 2 * * *",    # Daily at 2 AM
            "0 * * * *",    # Hourly
            "*/15 * * * *", # Every 15 minutes
            "0 9 * * 1-5",  # Weekdays at 9 AM
        ]

        invalid_expressions = [
            "invalid cron",
            "60 * * * *",   # Invalid minute
            "* * * *",      # Missing field
        ]

        # Test valid expressions
        for expr in valid_expressions:
            is_valid = scheduler.validate_cron_expression(expr)
            assert is_valid is True, f"Valid expression rejected: {expr}"

        # Test invalid expressions
        for expr in invalid_expressions:
            is_valid = scheduler.validate_cron_expression(expr)
            assert is_valid is False, f"Invalid expression accepted: {expr}"

    @pytest.mark.asyncio
    async def test_scheduler_concurrent_execution(self, scheduler: BackupScheduler):
        """Test concurrent backup execution."""
        tenant_id = TenantID("test-tenant")

        # Schedule multiple backups for execution at the same time
        scheduled_ids = []
        for i in range(5):
            scheduled_id = await scheduler.schedule_backup(
                tenant_id=tenant_id,
                backup_type=BackupType.FULL,
                schedule_type=ScheduleType.ONETIME,
                scheduled_time=datetime.now(),
                retention_days=30,
                priority=BackupPriority.HIGH,
            )
            scheduled_ids.append(scheduled_id)

        # Execute all scheduled backups
        results = []
        for scheduled_id in scheduled_ids:
            result = await scheduler.execute_scheduled_backup(scheduled_id)
            results.append(result)

        # Verify all backups were executed
        assert all(results)
        assert scheduler.backup_manager.create_backup.call_count == 5

        # Verify all scheduled backups were completed
        for scheduled_id in scheduled_ids:
            scheduled = scheduler.get_scheduled_backup(scheduled_id)
            assert scheduled.status == BackupStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_scheduler_timeout_handling(self, scheduler: BackupScheduler, backup_manager: AsyncMock):
        """Test timeout handling for backup execution."""
        # Make backup manager take longer than timeout
        backup_manager.create_backup.side_effect = asyncio.sleep(2)

        # Schedule backup with short timeout
        tenant_id = TenantID("test-tenant")
        scheduled_id = await scheduler.schedule_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            schedule_type=ScheduleType.ONETIME,
            scheduled_time=datetime.now(),
            retention_days=30,
            priority=BackupPriority.HIGH,
            timeout_seconds=1,  # 1 second timeout
        )

        # Execute backup (should timeout)
        with pytest.raises(asyncio.TimeoutError):
            await scheduler.execute_scheduled_backup(scheduled_id)

        # Verify backup was marked as timed out
        scheduled = scheduler.get_scheduled_backup(scheduled_id)
        assert scheduled.status == BackupStatus.FAILED
        assert "timeout" in scheduled.metadata.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_scheduler_metrics_collection(self, scheduler: BackupScheduler):
        """Test metrics collection by the scheduler."""
        tenant_id = TenantID("test-tenant")

        # Schedule and execute multiple backups
        for i in range(3):
            scheduled_id = await scheduler.schedule_backup(
                tenant_id=tenant_id,
                backup_type=BackupType.FULL,
                schedule_type=ScheduleType.ONETIME,
                scheduled_time=datetime.now(),
                retention_days=30,
                priority=BackupPriority.HIGH,
            )
            await scheduler.execute_scheduled_backup(scheduled_id)

        # Get scheduler metrics
        metrics = scheduler.get_metrics()

        # Verify metrics
        assert metrics["total_scheduled"] >= 3
        assert metrics["total_executed"] >= 3
        assert metrics["success_rate"] == 1.0  # 100% success rate
        assert "average_execution_time" in metrics
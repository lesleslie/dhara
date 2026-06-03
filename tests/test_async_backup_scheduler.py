"""Tests for dhara.backup.scheduler.AsyncBackupScheduler."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import shutil

from dhara.backup.scheduler import AsyncBackupScheduler, BackupJob, BackupScheduler
from dhara.backup.manager import BackupMetadata, BackupType
from dhara.storage.memory import AsyncMemoryStorage
from dhara.core.connection import AsyncConnection


def _meta(
    backup_id: str,
    backup_type: BackupType,
    source_path: str,
    size_bytes: int,
    days_ago: int = 0,
) -> BackupMetadata:
    ts = datetime.now() - timedelta(days=days_ago)
    return BackupMetadata(
        backup_id=backup_id,
        backup_type=backup_type,
        source_path=source_path,
        size_bytes=size_bytes,
        timestamp=ts,
        retention_days=30,
        checksum="deadbeef",
    )


class TestAsyncBackupScheduler:
    @pytest.fixture
    def temp_dir(self) -> Path:
        path = Path(tempfile.mkdtemp())
        yield path
        shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    async def scheduler_with_conn(self, temp_dir: Path) -> AsyncBackupScheduler:
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        scheduler = AsyncBackupScheduler(
            backup_dir=str(temp_dir),
            connection=conn,
        )
        yield scheduler
        scheduler.close()

    @pytest.mark.asyncio
    async def test_add_job_async(self, temp_dir: Path) -> None:
        """add_job_async creates a BackupJob and schedules it."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        job = await scheduler.add_job_async(
            name="test-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            enabled=True,
            retention_days=30,
        )
        assert job.name == "test-job"
        assert job.backup_type == BackupType.FULL
        assert job.enabled is True
        assert "test-job" in scheduler.jobs
        scheduler.close()

    @pytest.mark.asyncio
    async def test_get_job_status_async(self, temp_dir: Path) -> None:
        """get_job_status_async returns correct job status."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        await scheduler.add_job_async(
            name="status-job",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="hourly",
        )
        status = await scheduler.get_job_status_async("status-job")
        assert status is not None
        assert status["name"] == "status-job"
        assert status["backup_type"] == "incremental"
        assert status["schedule"] == "hourly"
        assert status["enabled"] is True
        scheduler.close()

    @pytest.mark.asyncio
    async def test_get_job_status_async_missing(self, temp_dir: Path) -> None:
        """get_job_status_async returns None for unknown job."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        result = await scheduler.get_job_status_async("nonexistent")
        assert result is None
        scheduler.close()

    @pytest.mark.asyncio
    async def test_get_all_jobs_status_async(self, temp_dir: Path) -> None:
        """get_all_jobs_status_async returns all job statuses."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        await scheduler.add_job_async(
            name="job-a", backup_type=BackupType.FULL, schedule_spec="daily"
        )
        await scheduler.add_job_async(
            name="job-b", backup_type=BackupType.INCREMENTAL, schedule_spec="hourly"
        )
        statuses = await scheduler.get_all_jobs_status_async()
        assert len(statuses) == 2
        assert "job-a" in statuses
        assert "job-b" in statuses
        scheduler.close()

    @pytest.mark.asyncio
    async def test_get_scheduler_statistics_async(
        self, scheduler_with_conn: AsyncBackupScheduler
    ) -> None:
        """get_scheduler_statistics_async returns catalog statistics."""
        await scheduler_with_conn.add_job_async(
            name="stats-job", backup_type=BackupType.FULL, schedule_spec="daily"
        )
        stats = await scheduler_with_conn.get_scheduler_statistics_async()
        assert stats["total_jobs"] == 1
        assert stats["enabled_jobs"] == 1
        assert "total_backups" in stats
        assert "by_type" in stats

    @pytest.mark.asyncio
    async def test_run_job_async_no_manager(self, temp_dir: Path) -> None:
        """run_job_async with no backup manager returns skipped status."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        await scheduler.add_job_async(
            name="skipped-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            enabled=True,
        )
        result = await scheduler.run_job_async("skipped-job")
        assert result is not None
        assert result["status"] == "skipped"
        scheduler.close()

    @pytest.mark.asyncio
    async def test_close(self, temp_dir: Path) -> None:
        """close cleans up resources without error."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        await scheduler.add_job_async(
            name="close-job", backup_type=BackupType.FULL, schedule_spec="daily"
        )
        scheduler.close()  # Should not raise
        assert scheduler._verification_engine is None

    @pytest.mark.asyncio
    async def test_context_manager(self, temp_dir: Path) -> None:
        """AsyncBackupScheduler supports async context manager."""
        async with AsyncBackupScheduler(backup_dir=str(temp_dir)) as scheduler:
            await scheduler.add_job_async(
                name="ctx-job", backup_type=BackupType.FULL, schedule_spec="daily"
            )
            assert "ctx-job" in scheduler.jobs
        # After exiting context, verification engine should be closed

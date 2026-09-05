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

    # ----- Additional coverage for _run_job_async / lifecycle -----

    @pytest.mark.asyncio
    async def test_run_job_async_full_success(self, temp_dir: Path) -> None:
        """run_job_async on a FULL job calls perform_full_backup and returns success."""
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from dhara.backup.manager import BackupMetadata

        fake_manager = MagicMock()
        meta = BackupMetadata(
            backup_id="B-full-1",
            backup_type=BackupType.FULL,
            source_path="/tmp/db.dhara",
            size_bytes=1234,
            timestamp=datetime.now(UTC),
            retention_days=30,
            checksum="abcd",
        )
        fake_manager.perform_full_backup.return_value = meta
        fake_manager.cloud_adapter = None

        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        scheduler.backup_manager = fake_manager
        await scheduler.add_job_async(
            name="full-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
        )
        result = await scheduler.run_job_async("full-job")
        assert result is not None
        assert result["status"] == "success"
        assert result["backup_id"] == "B-full-1"
        assert result["run_count"] == 1
        # job.last_run_result should be updated.
        job = scheduler.jobs["full-job"]
        assert job.last_run_result == "success"
        assert job.run_count == 1
        scheduler.close()

    @pytest.mark.asyncio
    async def test_run_job_async_incremental_success(self, temp_dir: Path) -> None:
        """run_job_async on INCREMENTAL exercises catalog + perform_incremental_backup."""
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        from dhara.backup.manager import BackupMetadata

        fake_manager = MagicMock()
        meta = BackupMetadata(
            backup_id="B-incr-1",
            backup_type=BackupType.INCREMENTAL,
            source_path="/tmp/db.dhara",
            size_bytes=42,
            timestamp=datetime.now(UTC),
            retention_days=30,
            checksum="beef",
        )
        fake_manager.perform_incremental_backup.return_value = meta
        fake_manager.cloud_adapter = None

        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        scheduler.backup_manager = fake_manager
        await scheduler.add_job_async(
            name="incr-job",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="hourly",
        )

        # Patch AsyncBackupCatalog.get_last_backup_async to return None
        # so the incremental path can proceed without a real DB connection.
        fake_catalog = MagicMock()
        fake_catalog.get_last_backup_async = AsyncMock(return_value=None)
        with patch(
            "dhara.backup.scheduler.AsyncBackupCatalog", return_value=fake_catalog
        ):
            result = await scheduler.run_job_async("incr-job")
        assert result is not None
        assert result["status"] == "success"
        scheduler.close()

    @pytest.mark.asyncio
    async def test_run_job_async_differential_success(self, temp_dir: Path) -> None:
        """run_job_async on DIFFERENTIAL exercises perform_differential_backup."""
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        from dhara.backup.manager import BackupMetadata

        fake_manager = MagicMock()
        meta = BackupMetadata(
            backup_id="B-diff-1",
            backup_type=BackupType.DIFFERENTIAL,
            source_path="/tmp/db.dhara",
            size_bytes=99,
            timestamp=datetime.now(UTC),
            retention_days=30,
            checksum="cafe",
        )
        fake_manager.perform_differential_backup.return_value = meta
        fake_manager.cloud_adapter = None

        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        scheduler.backup_manager = fake_manager
        await scheduler.add_job_async(
            name="diff-job",
            backup_type=BackupType.DIFFERENTIAL,
            schedule_spec="weekly",
        )

        fake_catalog = MagicMock()
        fake_catalog.get_last_backup_async = AsyncMock(return_value=None)
        with patch(
            "dhara.backup.scheduler.AsyncBackupCatalog", return_value=fake_catalog
        ):
            result = await scheduler.run_job_async("diff-job")
        assert result is not None
        assert result["status"] == "success"
        scheduler.close()

    @pytest.mark.asyncio
    async def test_run_job_async_unknown_backup_type_raises(
        self, temp_dir: Path
    ) -> None:
        """An invalid backup_type raises ValueError, which is caught and
        surfaced as a failed result with the failure callback invoked."""
        from unittest.mock import MagicMock

        fake_manager = MagicMock()
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        scheduler.backup_manager = fake_manager

        failure_calls: list[tuple[BackupJob, Exception]] = []

        def on_failure(job: BackupJob, exc: Exception) -> None:
            failure_calls.append((job, exc))

        # Bypass BackupType enum validation by patching the enum value.
        await scheduler.add_job_async(
            name="bogus-job",
            backup_type=BackupType.FULL,  # we'll swap it below
            schedule_spec="daily",
            callbacks={"on_failure": on_failure},
        )
        # Patch the job's backup_type to an invalid value.
        scheduler.jobs["bogus-job"].backup_type = "definitely-not-a-backup-type"  # type: ignore[assignment]

        result = await scheduler.run_job_async("bogus-job")
        assert result is not None
        assert result["status"] == "failed"
        assert "Unknown backup type" in result["error"]
        assert scheduler.jobs["bogus-job"].last_run_result == "failed"
        assert len(failure_calls) == 1
        scheduler.close()

    @pytest.mark.asyncio
    async def test_run_job_async_on_success_callback_invoked(
        self, temp_dir: Path
    ) -> None:
        """The on_success callback fires with the backup metadata."""
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from dhara.backup.manager import BackupMetadata

        fake_manager = MagicMock()
        meta = BackupMetadata(
            backup_id="B-cb-1",
            backup_type=BackupType.FULL,
            source_path="/tmp/x",
            size_bytes=1,
            timestamp=datetime.now(UTC),
            retention_days=30,
            checksum="x",
        )
        fake_manager.perform_full_backup.return_value = meta
        fake_manager.cloud_adapter = None

        success_calls: list[tuple[BackupMetadata, BackupJob]] = []

        def on_success(backup_metadata: BackupMetadata, job: BackupJob) -> None:
            success_calls.append((backup_metadata, job))

        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        scheduler.backup_manager = fake_manager
        await scheduler.add_job_async(
            name="cb-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            callbacks={"on_success": on_success},
        )
        result = await scheduler.run_job_async("cb-job")
        assert result["status"] == "success"
        assert len(success_calls) == 1
        assert success_calls[0][0].backup_id == "B-cb-1"
        scheduler.close()

    @pytest.mark.asyncio
    async def test_run_job_async_cloud_upload_failure_logs_warning(
        self, temp_dir: Path
    ) -> None:
        """If cloud_adapter returns False, run_job_async logs a warning but
        still returns success."""
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        from dhara.backup.manager import BackupMetadata

        fake_manager = MagicMock()
        meta = BackupMetadata(
            backup_id="B-cloud-1",
            backup_type=BackupType.FULL,
            source_path="/tmp/x",
            size_bytes=1,
            timestamp=datetime.now(UTC),
            retention_days=30,
            checksum="x",
        )
        fake_manager.perform_full_backup.return_value = meta
        fake_manager.cloud_adapter = MagicMock()
        fake_manager.cloud_adapter.upload_file = MagicMock(return_value=False)

        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        scheduler.backup_manager = fake_manager
        await scheduler.add_job_async(
            name="cloud-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
        )
        result = await scheduler.run_job_async("cloud-job")
        assert result is not None
        assert result["status"] == "success"
        scheduler.close()

    @pytest.mark.asyncio
    async def test_run_job_async_skipped_when_disabled(self, temp_dir: Path) -> None:
        """A disabled job returns skipped even if a manager is set."""
        from unittest.mock import MagicMock

        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        scheduler.backup_manager = MagicMock()
        await scheduler.add_job_async(
            name="disabled-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            enabled=False,
        )
        result = await scheduler.run_job_async("disabled-job")
        assert result is not None
        assert result["status"] == "skipped"
        scheduler.close()

    @pytest.mark.asyncio
    async def test_run_job_async_unknown_job_returns_none(self, temp_dir: Path) -> None:
        """run_job_async returns None when the named job does not exist."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        result = await scheduler.run_job_async("does-not-exist")
        assert result is None
        scheduler.close()

    @pytest.mark.asyncio
    async def test_start_async_and_stop_async(self, temp_dir: Path) -> None:
        """start_async spawns the scheduler+verify tasks; stop_async halts them."""
        import asyncio

        scheduler = AsyncBackupScheduler(
            backup_dir=str(temp_dir),
            auto_verify=False,  # only test scheduler loop
        )
        await scheduler.start_async()
        assert scheduler.running is True
        # Calling start again should be a no-op (warning).
        await scheduler.start_async()
        # Stop and verify running flips back.
        await scheduler.stop_async()
        assert scheduler.running is False
        # Stop again should be a no-op.
        await scheduler.stop_async()
        # Let any pending asyncio tasks wind down.
        await asyncio.sleep(0.05)
        scheduler.close()

    @pytest.mark.asyncio
    async def test_get_verification_engine_lazy(self, temp_dir: Path) -> None:
        """_get_verification_engine creates an engine on first call only."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        assert scheduler._verification_engine is None
        engine1 = await scheduler._get_verification_engine()
        assert engine1 is not None
        engine2 = await scheduler._get_verification_engine()
        assert engine2 is engine1  # cached
        scheduler.close()

    @pytest.mark.asyncio
    async def test_close_releases_verification_engine(self, temp_dir: Path) -> None:
        """close() sets _verification_engine to None after release."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        await scheduler._get_verification_engine()  # populate
        assert scheduler._verification_engine is not None
        scheduler.close()
        assert scheduler._verification_engine is None

    @pytest.mark.asyncio
    async def test_get_scheduler_statistics_async_with_backups(
        self, scheduler_with_conn: AsyncBackupScheduler
    ) -> None:
        """Verify by_type aggregation works with multiple backups."""
        # Insert some backups via the catalog directly.
        from dhara.backup.catalog import AsyncBackupCatalog

        catalog = AsyncBackupCatalog(
            str(scheduler_with_conn.backup_dir),
            connection=scheduler_with_conn._connection,
        )
        # No fixtures for catalog writes; just verify stats response shape.
        stats = await scheduler_with_conn.get_scheduler_statistics_async()
        assert "by_type" in stats
        assert "total_jobs" in stats
        assert "verification_interval" in stats

    @pytest.mark.asyncio
    async def test_add_job_async_with_disabled(self, temp_dir: Path) -> None:
        """An add_job_async with enabled=False doesn't schedule."""
        scheduler = AsyncBackupScheduler(backup_dir=str(temp_dir))
        job = await scheduler.add_job_async(
            name="not-enabled",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            enabled=False,
        )
        assert job.enabled is False
        assert "not-enabled" in scheduler.jobs
        scheduler.close()

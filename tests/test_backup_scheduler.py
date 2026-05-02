"""
Tests for backup scheduler (dhara.backup.scheduler).

Covers BackupJob and BackupScheduler including:
- Job creation, scheduling, enable/disable, and removal
- Job execution for FULL, INCREMENTAL, and DIFFERENTIAL backup types
- Callback invocation on success and failure
- Cloud upload and old-backup cleanup during job runs
- Default job configuration
- Scheduler statistics, start/stop lifecycle, and async loops
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dhara.backup.manager import BackupMetadata, BackupType
from dhara.backup.scheduler import BackupJob, BackupScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metadata(
    backup_id: str = "b1",
    backup_type: BackupType = BackupType.FULL,
    source_path: str = "/tmp/backup.bak",
    parent_backup_id: str | None = None,
    timestamp: datetime | None = None,
) -> BackupMetadata:
    """Create a BackupMetadata instance for testing."""
    return BackupMetadata(
        backup_id=backup_id,
        backup_type=backup_type,
        timestamp=timestamp or datetime.now(),
        source_path=source_path,
        size_bytes=1024,
        checksum="abc123",
        compression_ratio=0.8,
        encryption_enabled=False,
        parent_backup_id=parent_backup_id,
        retention_days=30,
    )


def _make_manager() -> MagicMock:
    """Create a mock BackupManager with sensible defaults."""
    mgr = MagicMock()
    mgr.backup_dir = "/tmp/backups"
    mgr.cloud_adapter = None
    mgr.perform_full_backup.return_value = _make_metadata("full-1", BackupType.FULL)
    mgr.perform_incremental_backup.return_value = _make_metadata(
        "inc-1", BackupType.INCREMENTAL, parent_backup_id="full-1"
    )
    mgr.perform_differential_backup.return_value = _make_metadata(
        "diff-1", BackupType.DIFFERENTIAL, parent_backup_id="full-1"
    )
    mgr.upload_to_cloud.return_value = True
    mgr.cleanup_old_backups.return_value = 0
    return mgr


# ===========================================================================
# BackupJob tests
# ===========================================================================


class TestBackupJobInit:
    """Test BackupJob initialisation."""

    def test_default_attributes(self):
        job = BackupJob(
            name="test-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
        )
        assert job.name == "test-job"
        assert job.backup_type is BackupType.FULL
        assert job.schedule_spec == "daily"
        assert job.enabled is True
        assert job.retention_days == 30
        assert job.backup_manager is None
        assert job.callbacks == {}
        assert job.last_run is None
        assert job.last_run_result is None
        assert job.run_count == 0

    def test_custom_attributes(self):
        callbacks = {"on_success": lambda m, j: None}
        mgr = _make_manager()
        job = BackupJob(
            name="custom",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="hourly",
            enabled=False,
            retention_days=7,
            backup_manager=mgr,
            callbacks=callbacks,
        )
        assert job.enabled is False
        assert job.retention_days == 7
        assert job.backup_manager is mgr
        assert job.callbacks is callbacks


class TestBackupJobStr:
    """Test BackupJob string representation."""

    def test_str_representation(self):
        job = BackupJob(
            name="my-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
        )
        text = str(job)
        assert "my-job" in text
        assert "full" in text
        assert "daily" in text


class TestBackupJobSchedule:
    """Test BackupJob.schedule() with various schedule specs."""

    @patch("dhara.backup.scheduler.schedule")
    def test_daily_spec(self, mock_schedule_mod):
        job = BackupJob(name="j", backup_type=BackupType.FULL, schedule_spec="daily")
        job.schedule()
        mock_schedule_mod.every.return_value.day.do.assert_called_once_with(job.run)

    @patch("dhara.backup.scheduler.schedule")
    def test_hourly_spec(self, mock_schedule_mod):
        job = BackupJob(name="j", backup_type=BackupType.FULL, schedule_spec="hourly")
        job.schedule()
        mock_schedule_mod.every.return_value.hour.do.assert_called_once_with(job.run)

    @patch("dhara.backup.scheduler.schedule")
    def test_weekly_spec(self, mock_schedule_mod):
        job = BackupJob(name="j", backup_type=BackupType.FULL, schedule_spec="weekly")
        job.schedule()
        mock_schedule_mod.every.return_value.week.do.assert_called_once_with(job.run)

    @patch("dhara.backup.scheduler.schedule")
    def test_monthly_spec(self, mock_schedule_mod):
        job = BackupJob(name="j", backup_type=BackupType.FULL, schedule_spec="monthly")
        job.schedule()
        mock_schedule_mod.every.return_value.month.do.assert_called_once_with(job.run)

    @patch("dhara.backup.scheduler.schedule")
    def test_cron_five_part_spec(self, mock_schedule_mod):
        job = BackupJob(
            name="j", backup_type=BackupType.FULL, schedule_spec="30 2 * * *"
        )
        job.schedule()
        # The code splits into parts and calls .day.at("2:30")
        mock_schedule_mod.every.return_value.day.at.assert_called_once_with("2:30")
        mock_schedule_mod.every.return_value.day.at.return_value.do.assert_called_once_with(job.run)

    @patch("dhara.backup.scheduler.schedule")
    def test_invalid_spec_logs_error(self, mock_schedule_mod, caplog):
        """An unrecognised schedule spec should log an error but not raise."""
        job = BackupJob(name="j", backup_type=BackupType.FULL, schedule_spec="bogus")
        with caplog.at_level("ERROR"):
            job.schedule()
        assert "Invalid schedule spec" in caplog.text


class TestBackupJobRun:
    """Test BackupJob.run() execution paths."""

    def test_run_skipped_when_disabled(self):
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            enabled=False,
        )
        result = job.run()
        assert result["status"] == "skipped"
        assert "disabled" in result["reason"]

    def test_run_skipped_when_no_manager(self):
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
        )
        result = job.run()
        assert result["status"] == "skipped"
        assert "no backup manager" in result["reason"]

    def test_run_full_backup_success(self):
        mgr = _make_manager()
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            backup_manager=mgr,
        )
        result = job.run()
        assert result["status"] == "success"
        assert result["backup_id"] == "full-1"
        assert result["backup_type"] == "full"
        assert result["run_count"] == 1
        assert job.last_run is not None
        assert job.last_run_result == "success"
        assert job.run_count == 1
        mgr.perform_full_backup.assert_called_once()
        mgr.cleanup_old_backups.assert_called_once()

    def test_run_full_backup_increments_count(self):
        mgr = _make_manager()
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            backup_manager=mgr,
        )
        job.run()
        job.run()
        assert job.run_count == 2
        assert job.last_run_result == "success"

    @patch("dhara.backup.scheduler.BackupCatalog")
    def test_run_incremental_backup_with_last(self, MockCatalog):
        mgr = _make_manager()
        last = _make_metadata("full-prev", BackupType.FULL)
        mock_catalog = MockCatalog.return_value
        mock_catalog.get_last_backup.return_value = last

        job = BackupJob(
            name="j",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="hourly",
            backup_manager=mgr,
        )
        result = job.run()
        assert result["status"] == "success"
        mgr.perform_incremental_backup.assert_called_once_with("full-prev")

    @patch("dhara.backup.scheduler.BackupCatalog")
    def test_run_incremental_backup_no_last(self, MockCatalog):
        mgr = _make_manager()
        mock_catalog = MockCatalog.return_value
        mock_catalog.get_last_backup.return_value = None

        job = BackupJob(
            name="j",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="hourly",
            backup_manager=mgr,
        )
        result = job.run()
        assert result["status"] == "success"
        mgr.perform_incremental_backup.assert_called_once_with(None)

    @patch("dhara.backup.scheduler.BackupCatalog")
    def test_run_differential_backup_with_last_full(self, MockCatalog):
        mgr = _make_manager()
        last_full = _make_metadata("full-prev", BackupType.FULL)
        mock_catalog = MockCatalog.return_value
        mock_catalog.get_last_backup_of_type.return_value = last_full

        job = BackupJob(
            name="j",
            backup_type=BackupType.DIFFERENTIAL,
            schedule_spec="daily",
            backup_manager=mgr,
        )
        result = job.run()
        assert result["status"] == "success"
        mgr.perform_differential_backup.assert_called_once_with("full-prev")

    @patch("dhara.backup.scheduler.BackupCatalog")
    def test_run_differential_backup_no_last_full(self, MockCatalog):
        mgr = _make_manager()
        mock_catalog = MockCatalog.return_value
        mock_catalog.get_last_backup_of_type.return_value = None

        job = BackupJob(
            name="j",
            backup_type=BackupType.DIFFERENTIAL,
            schedule_spec="daily",
            backup_manager=mgr,
        )
        result = job.run()
        assert result["status"] == "success"
        mgr.perform_differential_backup.assert_called_once_with(None)

    def test_run_calls_success_callback(self):
        mgr = _make_manager()
        callback = MagicMock()
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            backup_manager=mgr,
            callbacks={"on_success": callback},
        )
        result = job.run()
        assert result["status"] == "success"
        callback.assert_called_once()
        args = callback.call_args[0]
        # First arg is backup_metadata, second is the job itself
        assert args[1] is job

    def test_run_calls_failure_callback_on_exception(self):
        mgr = _make_manager()
        mgr.perform_full_backup.side_effect = RuntimeError("disk full")
        callback = MagicMock()
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            backup_manager=mgr,
            callbacks={"on_failure": callback},
        )
        result = job.run()
        assert result["status"] == "failed"
        assert "disk full" in result["error"]
        assert job.last_run_result == "failed"
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] is job
        assert isinstance(args[1], RuntimeError)

    def test_run_exception_without_failure_callback(self):
        mgr = _make_manager()
        mgr.perform_full_backup.side_effect = RuntimeError("oops")
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            backup_manager=mgr,
        )
        result = job.run()
        assert result["status"] == "failed"
        assert job.last_run_result == "failed"

    def test_run_with_cloud_upload_success(self):
        mgr = _make_manager()
        mgr.cloud_adapter = MagicMock()
        mgr.upload_to_cloud.return_value = True
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            backup_manager=mgr,
        )
        result = job.run()
        assert result["status"] == "success"
        mgr.upload_to_cloud.assert_called_once()

    def test_run_with_cloud_upload_failure_still_succeeds(self, caplog):
        mgr = _make_manager()
        mgr.cloud_adapter = MagicMock()
        mgr.upload_to_cloud.return_value = False
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            backup_manager=mgr,
        )
        with caplog.at_level("WARNING"):
            result = job.run()
        assert result["status"] == "success"
        assert "Cloud upload failed" in caplog.text

    def test_run_no_cloud_adapter_skips_upload(self):
        mgr = _make_manager()
        # cloud_adapter is None by default from _make_manager
        job = BackupJob(
            name="j",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            backup_manager=mgr,
        )
        result = job.run()
        assert result["status"] == "success"
        mgr.upload_to_cloud.assert_not_called()


# ===========================================================================
# BackupScheduler tests
# ===========================================================================


class TestBackupSchedulerInit:
    """Test BackupScheduler initialisation."""

    def test_default_init(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        assert scheduler.backup_dir == tmp_path
        assert scheduler.backup_manager is None
        assert scheduler.auto_verify is True
        assert scheduler.verify_interval == 3600
        assert scheduler.jobs == {}
        assert scheduler.running is False
        assert scheduler.last_verification is None

    def test_init_with_manager(self, tmp_path):
        mgr = _make_manager()
        scheduler = BackupScheduler(backup_dir=str(tmp_path), backup_manager=mgr)
        assert scheduler.backup_manager is mgr

    def test_init_creates_verification_engine(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        assert scheduler.verification_engine is not None

    def test_init_empty_dir_no_verification_engine(self):
        scheduler = BackupScheduler(backup_dir="")
        assert scheduler.verification_engine is None


class TestBackupSchedulerAddJob:
    """Test BackupScheduler.add_job()."""

    def test_add_enabled_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        job = scheduler.add_job(
            name="daily-full",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
        )
        assert "daily-full" in scheduler.jobs
        assert job.name == "daily-full"
        assert job.backup_type is BackupType.FULL
        assert job.enabled is True
        assert job.backup_manager is None

    def test_add_disabled_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        job = scheduler.add_job(
            name="paused-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            enabled=False,
        )
        assert "paused-job" in scheduler.jobs
        assert job.enabled is False

    def test_add_job_with_manager(self, tmp_path):
        mgr = _make_manager()
        scheduler = BackupScheduler(backup_dir=str(tmp_path), backup_manager=mgr)
        job = scheduler.add_job(
            name="with-mgr",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
        )
        assert job.backup_manager is mgr

    def test_add_job_with_callbacks(self, tmp_path):
        cb = {"on_success": lambda m, j: None}
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        job = scheduler.add_job(
            name="cb-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            callbacks=cb,
        )
        assert job.callbacks is cb

    def test_add_job_overwrites_existing(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.add_job(name="dup", backup_type=BackupType.FULL, schedule_spec="daily")
        job2 = scheduler.add_job(
            name="dup", backup_type=BackupType.INCREMENTAL, schedule_spec="hourly"
        )
        assert len(scheduler.jobs) == 1
        assert scheduler.jobs["dup"] is job2
        assert scheduler.jobs["dup"].backup_type is BackupType.INCREMENTAL


class TestBackupSchedulerRemoveJob:
    """Test BackupScheduler.remove_job()."""

    def test_remove_existing_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.add_job(name="rm-me", backup_type=BackupType.FULL, schedule_spec="daily")
        result = scheduler.remove_job("rm-me")
        assert result is True
        assert "rm-me" not in scheduler.jobs

    def test_remove_nonexistent_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        result = scheduler.remove_job("nope")
        assert result is False


class TestBackupSchedulerEnableDisable:
    """Test enable_job / disable_job."""

    def test_enable_existing_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.add_job(
            name="j", backup_type=BackupType.FULL, schedule_spec="daily", enabled=False
        )
        assert scheduler.jobs["j"].enabled is False
        result = scheduler.enable_job("j")
        assert result is True
        assert scheduler.jobs["j"].enabled is True

    def test_enable_nonexistent_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        result = scheduler.enable_job("ghost")
        assert result is False

    def test_disable_existing_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.add_job(name="j", backup_type=BackupType.FULL, schedule_spec="daily")
        result = scheduler.disable_job("j")
        assert result is True
        assert scheduler.jobs["j"].enabled is False

    def test_disable_nonexistent_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        result = scheduler.disable_job("ghost")
        assert result is False


class TestBackupSchedulerRunJob:
    """Test BackupScheduler.run_job()."""

    def test_run_existing_job(self, tmp_path):
        mgr = _make_manager()
        scheduler = BackupScheduler(backup_dir=str(tmp_path), backup_manager=mgr)
        scheduler.add_job(
            name="run-me", backup_type=BackupType.FULL, schedule_spec="daily"
        )
        result = scheduler.run_job("run-me")
        assert result is not None
        assert result["status"] == "success"

    def test_run_nonexistent_job(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        result = scheduler.run_job("ghost")
        assert result is None


class TestBackupSchedulerGetStatus:
    """Test get_job_status / get_all_jobs_status."""

    def test_get_job_status_existing(self, tmp_path):
        mgr = _make_manager()
        scheduler = BackupScheduler(backup_dir=str(tmp_path), backup_manager=mgr)
        scheduler.add_job(
            name="status-me",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            retention_days=14,
        )
        status = scheduler.get_job_status("status-me")
        assert status is not None
        assert status["name"] == "status-me"
        assert status["backup_type"] == "full"
        assert status["schedule"] == "daily"
        assert status["enabled"] is True
        assert status["retention_days"] == 14
        assert status["last_run"] is None
        assert status["last_run_result"] is None
        assert status["run_count"] == 0

    def test_get_job_status_after_run(self, tmp_path):
        mgr = _make_manager()
        scheduler = BackupScheduler(backup_dir=str(tmp_path), backup_manager=mgr)
        scheduler.add_job(
            name="ran", backup_type=BackupType.FULL, schedule_spec="daily"
        )
        scheduler.run_job("ran")
        status = scheduler.get_job_status("ran")
        assert status["last_run"] is not None
        assert status["last_run_result"] == "success"
        assert status["run_count"] == 1

    def test_get_job_status_nonexistent(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        assert scheduler.get_job_status("ghost") is None

    def test_get_all_jobs_status(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.add_job(name="a", backup_type=BackupType.FULL, schedule_spec="daily")
        scheduler.add_job(name="b", backup_type=BackupType.INCREMENTAL, schedule_spec="hourly")
        all_status = scheduler.get_all_jobs_status()
        assert len(all_status) == 2
        assert "a" in all_status
        assert "b" in all_status

    def test_get_all_jobs_status_empty(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        assert scheduler.get_all_jobs_status() == {}


class TestBackupSchedulerStartStop:
    """Test start / stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path), auto_verify=False)
        scheduler.start()
        assert scheduler.running is True
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_start_when_already_running_logs_warning(self, tmp_path, caplog):
        scheduler = BackupScheduler(backup_dir=str(tmp_path), auto_verify=False)
        scheduler.running = True
        with caplog.at_level("WARNING"):
            scheduler.start()
        assert "already running" in caplog.text

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.running = True
        scheduler.stop()
        assert scheduler.running is False

    def test_stop_when_not_running_logs_warning(self, tmp_path, caplog):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        with caplog.at_level("WARNING"):
            scheduler.stop()
        assert "not running" in caplog.text


class TestBackupSchedulerAsyncLoops:
    """Test async scheduler and verification loops."""

    @pytest.mark.asyncio
    async def test_scheduler_loop_runs_schedule_pending(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.running = True

        with patch("dhara.backup.scheduler.schedule") as mock_schedule:
            # Let the loop run once then stop
            iterations = 0
            original_sleep = asyncio.sleep

            async def fake_sleep(seconds):
                nonlocal iterations
                iterations += 1
                if iterations >= 2:
                    scheduler.running = False
                await original_sleep(0)

            with patch("dhara.backup.scheduler.asyncio.sleep", side_effect=fake_sleep):
                await scheduler._scheduler_loop()

            mock_schedule.run_pending.assert_called()

    @pytest.mark.asyncio
    async def test_scheduler_loop_handles_exception(self, tmp_path, caplog):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.running = True
        iterations = 0
        original_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            nonlocal iterations
            iterations += 1
            if iterations >= 2:
                scheduler.running = False
            await original_sleep(0)

        with patch(
            "dhara.backup.scheduler.schedule.run_pending",
            side_effect=RuntimeError("boom"),
        ):
            with patch("dhara.backup.scheduler.asyncio.sleep", side_effect=fake_sleep):
                with caplog.at_level("ERROR"):
                    await scheduler._scheduler_loop()

        assert "Scheduler loop error" in caplog.text

    @pytest.mark.asyncio
    async def test_verification_loop_runs_checks(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.running = True
        scheduler.verification_engine = MagicMock()
        scheduler.verification_engine.run_all_checks.return_value = {
            "check1": {"status": "passed"},
            "check2": {"status": "failed", "error": "bad"},
        }
        iterations = 0
        original_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            nonlocal iterations
            iterations += 1
            if iterations >= 2:
                scheduler.running = False
            await original_sleep(0)

        with patch("dhara.backup.scheduler.asyncio.sleep", side_effect=fake_sleep):
            await scheduler._verification_loop()

        scheduler.verification_engine.run_all_checks.assert_called()
        assert scheduler.last_verification is not None

    @pytest.mark.asyncio
    async def test_verification_loop_handles_exception(self, tmp_path, caplog):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.running = True
        scheduler.verification_engine = MagicMock()
        scheduler.verification_engine.run_all_checks.side_effect = RuntimeError(
            "verify-err"
        )
        iterations = 0
        original_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            nonlocal iterations
            iterations += 1
            if iterations >= 2:
                scheduler.running = False
            await original_sleep(0)

        with patch("dhara.backup.scheduler.asyncio.sleep", side_effect=fake_sleep):
            with caplog.at_level("ERROR"):
                await scheduler._verification_loop()

        assert "Verification loop error" in caplog.text

    @pytest.mark.asyncio
    async def test_start_creates_scheduler_task(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path), auto_verify=False)
        with patch("dhara.backup.scheduler.asyncio.create_task") as mock_create:
            scheduler.start()
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_creates_verification_task_when_enabled(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path), auto_verify=True)
        with patch("dhara.backup.scheduler.asyncio.create_task") as mock_create:
            scheduler.start()
            assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_start_does_not_create_verification_task_when_disabled(self, tmp_path):
        scheduler = BackupScheduler(backup_dir=str(tmp_path), auto_verify=False)
        with patch("dhara.backup.scheduler.asyncio.create_task") as mock_create:
            scheduler.start()
            assert mock_create.call_count == 1


class TestBackupSchedulerDefaultJobs:
    """Test configure_default_jobs()."""

    def test_configure_default_jobs_without_manager(self, tmp_path, caplog):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        with caplog.at_level("WARNING"):
            scheduler.configure_default_jobs()
        assert "No backup manager" in caplog.text
        assert len(scheduler.jobs) == 0

    def test_configure_default_jobs_creates_three_jobs(self, tmp_path):
        mgr = _make_manager()
        scheduler = BackupScheduler(backup_dir=str(tmp_path), backup_manager=mgr)
        scheduler.configure_default_jobs()
        assert len(scheduler.jobs) == 3
        assert "daily_full" in scheduler.jobs
        assert "hourly_incremental" in scheduler.jobs
        assert "daily_differential" in scheduler.jobs

    def test_default_jobs_have_correct_types(self, tmp_path):
        mgr = _make_manager()
        scheduler = BackupScheduler(backup_dir=str(tmp_path), backup_manager=mgr)
        scheduler.configure_default_jobs()
        assert scheduler.jobs["daily_full"].backup_type is BackupType.FULL
        assert scheduler.jobs["hourly_incremental"].backup_type is BackupType.INCREMENTAL
        assert scheduler.jobs["daily_differential"].backup_type is BackupType.DIFFERENTIAL

    def test_default_jobs_have_callbacks(self, tmp_path):
        mgr = _make_manager()
        scheduler = BackupScheduler(backup_dir=str(tmp_path), backup_manager=mgr)
        scheduler.configure_default_jobs()
        for job in scheduler.jobs.values():
            assert "on_success" in job.callbacks
            assert "on_failure" in job.callbacks


class TestBackupSchedulerCallbacks:
    """Test _on_backup_success / _on_backup_failure callbacks."""

    def test_on_backup_success(self, tmp_path, caplog):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        metadata = _make_metadata("cb-test")
        job = BackupJob(
            name="j", backup_type=BackupType.FULL, schedule_spec="daily"
        )
        with caplog.at_level("INFO"):
            scheduler._on_backup_success(metadata, job)
        assert "cb-test" in caplog.text

    def test_on_backup_failure(self, tmp_path, caplog):
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        job = BackupJob(
            name="failing-job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
        )
        with caplog.at_level("ERROR"):
            scheduler._on_backup_failure(job, RuntimeError("oops"))
        assert "failing-job" in caplog.text


class TestBackupSchedulerStatistics:
    """Test get_scheduler_statistics()."""

    @patch("dhara.backup.scheduler.BackupCatalog")
    def test_statistics_empty(self, MockCatalog, tmp_path):
        mock_catalog = MockCatalog.return_value
        mock_catalog.get_backup_statistics.return_value = {
            "total_backups": 0,
            "total_size": 0,
            "by_type": {},
            "avg_size": 0,
        }
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        stats = scheduler.get_scheduler_statistics()
        assert stats["running"] is False
        assert stats["total_jobs"] == 0
        assert stats["enabled_jobs"] == 0
        assert stats["backup_statistics"]["total_backups"] == 0
        assert stats["last_verification"] is None
        assert stats["verification_interval"] == 3600

    @patch("dhara.backup.scheduler.BackupCatalog")
    def test_statistics_with_jobs(self, MockCatalog, tmp_path):
        mock_catalog = MockCatalog.return_value
        mock_catalog.get_backup_statistics.return_value = {
            "total_backups": 5,
            "total_size": 5000,
        }
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.add_job(name="a", backup_type=BackupType.FULL, schedule_spec="daily")
        scheduler.add_job(
            name="b",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="hourly",
            enabled=False,
        )
        stats = scheduler.get_scheduler_statistics()
        assert stats["total_jobs"] == 2
        assert stats["enabled_jobs"] == 1

    @patch("dhara.backup.scheduler.BackupCatalog")
    def test_statistics_with_verification_time(self, MockCatalog, tmp_path):
        mock_catalog = MockCatalog.return_value
        mock_catalog.get_backup_statistics.return_value = {}
        scheduler = BackupScheduler(backup_dir=str(tmp_path))
        scheduler.last_verification = datetime.now()
        stats = scheduler.get_scheduler_statistics()
        assert stats["last_verification"] is not None
        # ISO format string should parse back
        datetime.fromisoformat(stats["last_verification"])

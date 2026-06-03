"""
from __future__ import annotations
Backup scheduler for automated backup management.

This module provides:
- Cron-style scheduling
- Event-driven backups
- Backup rotation
- Health monitoring
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import schedule

from dhara.core.connection import AsyncConnection

from .catalog import AsyncBackupCatalog, BackupCatalog
from .manager import BackupManager, BackupType
from .verification import AsyncBackupVerification, BackupVerification

logger = logging.getLogger(__name__)


class BackupJob:
    """Represents a scheduled backup job."""

    def __init__(
        self,
        name: str,
        backup_type: BackupType,
        schedule_spec: str,
        enabled: bool = True,
        retention_days: int = 30,
        backup_manager: BackupManager | None = None,
        callbacks: dict[str, Callable[..., Any]] | None = None,
    ):
        self.name = name
        self.backup_type = backup_type
        self.schedule_spec = schedule_spec
        self.enabled = enabled
        self.retention_days = retention_days
        self.backup_manager = backup_manager
        self.callbacks = callbacks or {}
        self.last_run: datetime | None = None
        self.last_run_result: str | None = None
        self.run_count: int = 0

    def __str__(self) -> str:
        return f"BackupJob(name={self.name}, type={self.backup_type.value}, schedule={self.schedule_spec})"

    def schedule(self) -> None:
        """Schedule the job based on schedule_spec."""
        # Parse schedule_spec (simplified cron format)
        parts = self.schedule_spec.split()
        if len(parts) == 5:  # minute hour day month weekday
            minute, hour, _, _, _ = parts
            schedule.every().day.at(f"{hour}:{minute}").do(self.run)  # type: ignore[arg-type]
        elif self.schedule_spec == "daily":
            schedule.every().day.do(self.run)  # type: ignore[arg-type]
        elif self.schedule_spec == "hourly":
            schedule.every().hour.do(self.run)  # type: ignore[arg-type]
        elif self.schedule_spec == "weekly":
            schedule.every().week.do(self.run)  # type: ignore[arg-type]
        elif self.schedule_spec == "monthly":
            schedule.every().month.do(self.run)  # type: ignore[attr-defined]
        else:
            logger.error(f"Invalid schedule spec: {self.schedule_spec}")

    def run(self) -> dict[str, Any]:  # noqa: C901
        """Run the backup job."""
        if not self.enabled or not self.backup_manager:
            return {"status": "skipped", "reason": "job disabled or no backup manager"}

        try:
            logger.info(f"Running backup job: {self.name}")

            # Perform backup based on type
            if self.backup_type == BackupType.FULL:
                backup_metadata = self.backup_manager.perform_full_backup()
            elif self.backup_type == BackupType.INCREMENTAL:
                # Get last backup for incremental
                catalog = BackupCatalog(self.backup_manager.backup_dir)
                last_backup = catalog.get_last_backup()
                backup_metadata = self.backup_manager.perform_incremental_backup(
                    last_backup.backup_id if last_backup else None
                )
            elif self.backup_type == BackupType.DIFFERENTIAL:
                catalog = BackupCatalog(self.backup_manager.backup_dir)
                last_full = catalog.get_last_backup_of_type(BackupType.FULL)
                backup_metadata = self.backup_manager.perform_differential_backup(
                    last_full.backup_id if last_full else None
                )
            else:
                raise ValueError(f"Unknown backup type: {self.backup_type}")

            # Update job status
            self.last_run = datetime.now()
            self.last_run_result = "success"
            self.run_count += 1

            # Call success callback
            if "on_success" in self.callbacks:
                self.callbacks["on_success"](backup_metadata, self)

            # Upload to cloud if configured
            if self.backup_manager.cloud_adapter:
                cloud_success = self.backup_manager.upload_to_cloud(backup_metadata)
                if not cloud_success:
                    logger.warning(
                        f"Cloud upload failed for backup: {backup_metadata.backup_id}"
                    )

            # Clean up old backups
            self.backup_manager.cleanup_old_backups()

            return {
                "status": "success",
                "backup_id": backup_metadata.backup_id,
                "backup_type": backup_metadata.backup_type.value,
                "timestamp": backup_metadata.timestamp.isoformat(),
                "run_count": self.run_count,
            }

        except Exception as e:
            self.last_run = datetime.now()
            self.last_run_result = "failed"
            logger.error(f"Backup job {self.name} failed: {e}")

            # Call failure callback
            if "on_failure" in self.callbacks:
                self.callbacks["on_failure"](self, e)

            return {"status": "failed", "error": str(e), "run_count": self.run_count}


class BackupScheduler:
    """Main scheduler for automated backups."""

    def __init__(
        self,
        backup_dir: str = "./backups",
        backup_manager: BackupManager | None = None,
        auto_verify: bool = True,
        verify_interval: int = 3600,  # 1 hour
    ):
        self.backup_dir = Path(backup_dir)
        self.backup_manager = backup_manager
        self.auto_verify = auto_verify
        self.verify_interval = verify_interval
        self.jobs: dict[str, BackupJob] = {}
        self.running: bool = False
        self.last_verification: datetime | None = None
        self.verification_engine = (
            BackupVerification(
                str(self.backup_dir),
                str(self.backup_dir / "test_restores"),
            )
            if backup_dir
            else None
        )

    def add_job(
        self,
        name: str,
        backup_type: BackupType,
        schedule_spec: str,
        enabled: bool = True,
        retention_days: int = 30,
        callbacks: dict[str, Callable[..., Any]] | None = None,
    ) -> BackupJob:
        """Add a backup job to the scheduler."""
        job = BackupJob(
            name=name,
            backup_type=backup_type,
            schedule_spec=schedule_spec,
            enabled=enabled,
            retention_days=retention_days,
            backup_manager=self.backup_manager,
            callbacks=callbacks,
        )

        self.jobs[name] = job
        if enabled:
            job.schedule()

        logger.info(f"Added backup job: {job}")
        return job

    def remove_job(self, name: str) -> bool:
        """Remove a backup job from the scheduler."""
        if name in self.jobs:
            del self.jobs[name]
            logger.info(f"Removed backup job: {name}")
            return True
        return False

    def enable_job(self, name: str) -> bool:
        """Enable a backup job."""
        if name in self.jobs:
            self.jobs[name].enabled = True
            self.jobs[name].schedule()
            logger.info(f"Enabled backup job: {name}")
            return True
        return False

    def disable_job(self, name: str) -> bool:
        """Disable a backup job."""
        if name in self.jobs:
            self.jobs[name].enabled = False
            logger.info(f"Disabled backup job: {name}")
            return True
        return False

    def run_job(self, name: str) -> dict[str, Any] | None:
        """Run a specific backup job immediately."""
        if name in self.jobs:
            return self.jobs[name].run()
        return None

    def get_job_status(self, name: str) -> dict[str, Any] | None:
        """Get status of a specific job."""
        if name in self.jobs:
            job = self.jobs[name]
            return {
                "name": job.name,
                "backup_type": job.backup_type.value,
                "schedule": job.schedule_spec,
                "enabled": job.enabled,
                "retention_days": job.retention_days,
                "last_run": job.last_run.isoformat() if job.last_run else None,
                "last_run_result": job.last_run_result,
                "run_count": job.run_count,
            }
        return None

    def get_all_jobs_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all jobs."""
        return {name: self.get_job_status(name) or {} for name in self.jobs}

    def start(self) -> None:
        """Start the scheduler."""
        if self.running:
            logger.warning("Scheduler is already running")
            return

        self.running = True
        logger.info("Starting backup scheduler")

        # Start background tasks
        asyncio.create_task(self._scheduler_loop())
        if self.auto_verify:
            asyncio.create_task(self._verification_loop())

    def stop(self) -> None:
        """Stop the scheduler."""
        if not self.running:
            logger.warning("Scheduler is not running")
            return

        self.running = False
        logger.info("Stopped backup scheduler")

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        while self.running:
            try:
                # Run scheduled jobs
                schedule.run_pending()

                # Sleep for a short interval
                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(60)

    async def _verification_loop(self) -> None:
        """Verification loop for automated backup testing."""
        while self.running:
            try:
                # Check if it's time for verification
                now = datetime.now()
                if (
                    self.last_verification is None
                    or (now - self.last_verification).seconds >= self.verify_interval
                ):
                    logger.info("Starting automated backup verification")

                    # Run verification
                    results = self.verification_engine.run_all_checks()  # type: ignore

                    # Log results
                    for check_name, result in results.items():
                        check_result = result if isinstance(result, dict) else {}
                        if check_result.get("status") == "failed":
                            logger.error(
                                f"Verification failed: {check_name} - {check_result.get('error', 'Unknown error')}"
                            )
                        else:
                            logger.info(f"Verification passed: {check_name}")

                    self.last_verification = now  # type: ignore

                # Wait before next check
                await asyncio.sleep(self.verify_interval)

            except Exception as e:
                logger.error(f"Verification loop error: {e}")
                await asyncio.sleep(60)

    def configure_default_jobs(self) -> None:
        """Configure default backup jobs."""
        if not self.backup_manager:
            logger.warning("No backup manager configured for default jobs")
            return

        # Daily full backup at 2 AM
        self.add_job(
            name="daily_full",
            backup_type=BackupType.FULL,
            schedule_spec="02:00",
            retention_days=30,
            callbacks={
                "on_success": self._on_backup_success,
                "on_failure": self._on_backup_failure,
            },
        )

        # Hourly incremental backup
        self.add_job(
            name="hourly_incremental",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="hourly",
            retention_days=7,
            callbacks={
                "on_success": self._on_backup_success,
                "on_failure": self._on_backup_failure,
            },
        )

        # Daily differential backup at 10 PM
        self.add_job(
            name="daily_differential",
            backup_type=BackupType.DIFFERENTIAL,
            schedule_spec="22:00",
            retention_days=14,
            callbacks={
                "on_success": self._on_backup_success,
                "on_failure": self._on_backup_failure,
            },
        )

    def _on_backup_success(self, backup_metadata: Any, job: BackupJob) -> None:
        """Callback for successful backup."""
        logger.info(f"Backup completed successfully: {backup_metadata.backup_id}")
        # Here you could add notifications, logging, etc.

    def _on_backup_failure(self, job: BackupJob, error: Exception) -> None:
        """Callback for failed backup."""
        logger.error(f"Backup failed: {job.name} - {error}")
        # Here you could add alerts, notifications, etc.

    def get_scheduler_statistics(self) -> dict[str, Any]:
        """Get scheduler statistics."""
        backup_stats = BackupCatalog(str(self.backup_dir)).get_backup_statistics()

        return {
            "running": self.running,
            "total_jobs": len(self.jobs),
            "enabled_jobs": sum(1 for j in self.jobs.values() if j.enabled),
            "backup_statistics": backup_stats,
            "last_verification": self.last_verification.isoformat()  # type: ignore[attr-defined]
            if self.last_verification
            else None,
            "verification_interval": self.verify_interval,
        }


class AsyncBackupScheduler:
    """Async Dhara-backed backup scheduler using AsyncConnection.

    Uses AsyncBackupCatalog and AsyncBackupVerification for async
    catalog access. Runs blocking operations in a thread pool.
    """

    def __init__(
        self,
        backup_dir: str = "./backups",
        backup_manager: BackupManager | None = None,
        auto_verify: bool = True,
        verify_interval: int = 3600,
        connection: AsyncConnection | None = None,
    ) -> None:
        self.backup_dir = Path(backup_dir)
        self.backup_manager = backup_manager
        self.auto_verify = auto_verify
        self.verify_interval = verify_interval
        self.jobs: dict[str, BackupJob] = {}
        self.running = False
        self.last_verification: datetime | None = None
        self._verification_engine: AsyncBackupVerification | None = None
        self._connection = connection
        self.logger = logging.getLogger(__name__)

    async def _get_verification_engine(self) -> AsyncBackupVerification:
        if self._verification_engine is None:
            self._verification_engine = AsyncBackupVerification(
                str(self.backup_dir),
                str(self.backup_dir / "test_restores"),
            )
        return self._verification_engine

    async def _run_job_async(self, job: BackupJob) -> dict[str, Any]:
        """Run a backup job asynchronously."""
        if not job.enabled or not job.backup_manager:
            return {"status": "skipped", "reason": "job disabled or no backup manager"}

        try:
            self.logger.info(f"Running async backup job: {job.name}")

            if job.backup_type == BackupType.FULL:
                backup_metadata = await asyncio.to_thread(
                    job.backup_manager.perform_full_backup
                )
            elif job.backup_type == BackupType.INCREMENTAL:
                catalog = AsyncBackupCatalog(job.backup_manager.backup_dir)
                last_backup = await catalog.get_last_backup_async()
                backup_metadata = await asyncio.to_thread(
                    job.backup_manager.perform_incremental_backup,
                    last_backup.backup_id if last_backup else None,
                )
            elif job.backup_type == BackupType.DIFFERENTIAL:
                catalog = AsyncBackupCatalog(job.backup_manager.backup_dir)
                last_full = await catalog.get_last_backup_async()
                backup_metadata = await asyncio.to_thread(
                    job.backup_manager.perform_differential_backup,
                    last_full.backup_id if last_full else None,
                )
            else:
                raise ValueError(f"Unknown backup type: {job.backup_type}")

            job.last_run = datetime.now()
            job.last_run_result = "success"
            job.run_count += 1

            if "on_success" in job.callbacks:
                job.callbacks["on_success"](backup_metadata, job)

            if job.backup_manager.cloud_adapter:
                cloud_success = await asyncio.to_thread(
                    job.backup_manager.upload_to_cloud, backup_metadata
                )
                if not cloud_success:
                    self.logger.warning(
                        f"Cloud upload failed for backup: {backup_metadata.backup_id}"
                    )

            await asyncio.to_thread(job.backup_manager.cleanup_old_backups)

            return {
                "status": "success",
                "backup_id": backup_metadata.backup_id,
                "backup_type": backup_metadata.backup_type.value,
                "timestamp": backup_metadata.timestamp.isoformat(),
                "run_count": job.run_count,
            }

        except Exception as e:
            job.last_run = datetime.now()
            job.last_run_result = "failed"
            self.logger.error(f"Async backup job {job.name} failed: {e}")

            if "on_failure" in job.callbacks:
                job.callbacks["on_failure"](job, e)

            return {"status": "failed", "error": str(e), "run_count": job.run_count}

    async def add_job_async(
        self,
        name: str,
        backup_type: BackupType,
        schedule_spec: str,
        enabled: bool = True,
        retention_days: int = 30,
        callbacks: dict[str, Callable[..., Any]] | None = None,
    ) -> BackupJob:
        """Add a backup job to the scheduler (async)."""
        job = BackupJob(
            name=name,
            backup_type=backup_type,
            schedule_spec=schedule_spec,
            enabled=enabled,
            retention_days=retention_days,
            backup_manager=self.backup_manager,
            callbacks=callbacks,
        )

        self.jobs[name] = job
        if enabled:
            job.schedule()

        self.logger.info(f"Added async backup job: {job}")
        return job

    async def run_job_async(self, name: str) -> dict[str, Any] | None:
        """Run a specific backup job immediately (async)."""
        if name in self.jobs:
            return await self._run_job_async(self.jobs[name])
        return None

    async def get_job_status_async(self, name: str) -> dict[str, Any] | None:
        """Get status of a specific job (async)."""
        if name in self.jobs:
            job = self.jobs[name]
            return {
                "name": job.name,
                "backup_type": job.backup_type.value,
                "schedule": job.schedule_spec,
                "enabled": job.enabled,
                "retention_days": job.retention_days,
                "last_run": job.last_run.isoformat() if job.last_run else None,
                "last_run_result": job.last_run_result,
                "run_count": job.run_count,
            }
        return None

    async def get_all_jobs_status_async(self) -> dict[str, dict[str, Any]]:
        """Get status of all jobs (async)."""
        results: dict[str, dict[str, Any]] = {}
        for name in self.jobs:
            status = await self.get_job_status_async(name)
            if status is not None:
                results[name] = status
        return results

    async def start_async(self) -> None:
        """Start the async scheduler."""
        if self.running:
            self.logger.warning("Async scheduler is already running")
            return

        self.running = True
        self.logger.info("Starting async backup scheduler")

        asyncio.create_task(self._scheduler_loop_async())
        if self.auto_verify:
            asyncio.create_task(self._verification_loop_async())

    async def stop_async(self) -> None:
        """Stop the async scheduler."""
        if not self.running:
            self.logger.warning("Async scheduler is not running")
            return

        self.running = False
        self.logger.info("Stopped async backup scheduler")

    async def _scheduler_loop_async(self) -> None:
        """Main async scheduler loop."""
        while self.running:
            try:
                schedule.run_pending()
                await asyncio.sleep(60)
            except Exception as e:
                self.logger.error(f"Async scheduler loop error: {e}")
                await asyncio.sleep(60)

    async def _verification_loop_async(self) -> None:
        """Async verification loop for automated backup testing."""
        while self.running:
            try:
                now = datetime.now()
                if (
                    self.last_verification is None
                    or (now - self.last_verification).seconds >= self.verify_interval
                ):
                    self.logger.info("Starting async automated backup verification")

                    engine = await self._get_verification_engine()
                    results = await engine.run_all_checks_async()

                    for check_name, result in results.items():
                        check_dict = result if isinstance(result, dict) else {}
                        if check_dict.get("status") == "failed":
                            self.logger.error(
                                f"Async verification failed: {check_name} - "
                                f"{check_dict.get('error', 'Unknown error')}"
                            )
                        else:
                            self.logger.info(f"Async verification passed: {check_name}")

                    self.last_verification = now

                await asyncio.sleep(self.verify_interval)

            except Exception as e:
                self.logger.error(f"Async verification loop error: {e}")
                await asyncio.sleep(60)

    async def get_scheduler_statistics_async(self) -> dict[str, Any]:
        """Get scheduler statistics (async)."""
        catalog = AsyncBackupCatalog(str(self.backup_dir), connection=self._connection)
        backups = await catalog.get_all_backups_async()

        total_size = sum(b.size_bytes for b in backups)
        by_type: dict[str, int] = {}
        for b in backups:
            btype = b.backup_type.value
            by_type[btype] = by_type.get(btype, 0) + 1

        return {
            "running": self.running,
            "total_jobs": len(self.jobs),
            "enabled_jobs": sum(1 for j in self.jobs.values() if j.enabled),
            "total_backups": len(backups),
            "total_size_bytes": total_size,
            "by_type": by_type,
            "last_verification": self.last_verification.isoformat()
            if self.last_verification
            else None,
            "verification_interval": self.verify_interval,
        }

    def close(self) -> None:
        """Close async resources."""
        if self._verification_engine is not None:
            self._verification_engine.close()
            self._verification_engine = None

    def __enter__(self) -> "AsyncBackupScheduler":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def __aenter__(self) -> "AsyncBackupScheduler":
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.close()

"""
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

from .catalog import BackupCatalog
from .manager import BackupManager, BackupType
from .verification import BackupVerification

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
        callbacks: dict[str, Callable] | None = None,
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

    def __str__(self):
        return f"BackupJob(name={self.name}, type={self.backup_type.value}, schedule={self.schedule_spec})"

    def schedule(self) -> None:
        """Schedule the job based on schedule_spec."""
        # Parse schedule_spec (simplified cron format)
        parts = self.schedule_spec.split()
        if len(parts) == 5:  # minute hour day month weekday
            minute, hour, day, month, weekday = parts
            schedule.every().day.at(f"{hour}:{minute}").do(self.run)
        elif self.schedule_spec == "daily":
            schedule.every().day.do(self.run)
        elif self.schedule_spec == "hourly":
            schedule.every().hour.do(self.run)
        elif self.schedule_spec == "weekly":
            schedule.every().week.do(self.run)
        elif self.schedule_spec == "monthly":
            schedule.every().month.do(self.run)
        else:
            logger.error(f"Invalid schedule spec: {self.schedule_spec}")

    def run(self) -> dict[str, Any]:
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
                return {"status": "failed", "reason": "unsupported backup type"}

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
        self.running = False
        self.last_verification = None
        self.verification_engine = (
            BackupVerification(backup_dir) if backup_dir else None
        )

    def add_job(
        self,
        name: str,
        backup_type: BackupType,
        schedule_spec: str,
        enabled: bool = True,
        retention_days: int = 30,
        callbacks: dict[str, Callable] | None = None,
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
        return {name: self.get_job_status(name) for name in self.jobs}

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
                    results = self.verification_engine.run_all_checks()

                    # Log results
                    for check_name, result in results.items():
                        if result["status"] == "failed":
                            logger.error(
                                f"Verification failed: {check_name} - {result.get('error', 'Unknown error')}"
                            )
                        else:
                            logger.info(f"Verification passed: {check_name}")

                    self.last_verification = now

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
        catalog = BackupCatalog(str(self.backup_dir))
        backup_stats = catalog.get_backup_statistics()

        return {
            "running": self.running,
            "total_jobs": len(self.jobs),
            "enabled_jobs": sum(1 for j in self.jobs.values() if j.enabled),
            "backup_statistics": backup_stats,
            "last_verification": self.last_verification.isoformat()
            if self.last_verification
            else None,
            "verification_interval": self.verify_interval,
        }

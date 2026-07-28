from __future__ import annotations

"""
from __future__ import annotations
Backup verification system for Durus backups.

This module provides:
- Backup file integrity verification
- Test restores
- Performance testing
- Automated validation
- AsyncBackupVerification for async tool dispatch
"""

import asyncio
import hashlib
import logging
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self, cast

from .catalog import AsyncBackupCatalog, BackupCatalog
from .manager import BackupMetadata, BackupType
from .restore import AsyncRestoreManager, RestoreManager

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of *path* (sync; offload via ``asyncio.to_thread``)."""
    sha256_hash = hashlib.sha256()
    with path.open("rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


class CheckResult:
    """Result of a verification check."""

    def __init__(
        self,
        check_name: str,
        status: str,
        message: str = "",
        details: dict[str, Any] | None = None,
        duration_seconds: float = 0.0,
    ):
        self.check_name = check_name
        self.status = status  # "passed", "failed", "warning"
        self.message = message
        self.details = details or {}
        self.duration_seconds = duration_seconds

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "check_name": self.check_name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "duration_seconds": self.duration_seconds,
        }


class BackupVerification:
    """Handles backup verification and testing."""

    def __init__(
        self,
        backup_dir: str = "./backups",
        test_restore_dir: str = "./test_restores",
        timeout_seconds: int = 300,
        max_test_size_mb: int = 100,
    ):
        self.backup_dir = Path(backup_dir)
        self.test_restore_dir = Path(test_restore_dir)
        self.timeout_seconds = timeout_seconds
        self.max_test_size_mb = max_test_size_mb

        # Ensure test restore directory exists
        self.test_restore_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Backup verification initialized")

    def check_backup_integrity(self, backup_metadata: BackupMetadata) -> CheckResult:
        """Check backup file integrity."""
        start_time = time.time()

        try:
            backup_path = Path(backup_metadata.source_path)
            if not backup_path.exists():
                return CheckResult(
                    "integrity_check", "failed", f"Backup file not found: {backup_path}"
                )

            # Check file size
            actual_size = backup_path.stat().st_size
            if actual_size != backup_metadata.size_bytes:
                return CheckResult(
                    "integrity_check",
                    "failed",
                    f"File size mismatch: expected {backup_metadata.size_bytes}, got {actual_size}",
                    {
                        "expected_size": backup_metadata.size_bytes,
                        "actual_size": actual_size,
                    },
                )

            # Calculate checksum (sync helper; safe in non-async context).
            actual_checksum = _sha256_file(backup_path)
            if actual_checksum != backup_metadata.checksum:
                return CheckResult(
                    "integrity_check",
                    "failed",
                    f"Checksum mismatch: expected {backup_metadata.checksum}, got {actual_checksum}",
                    {
                        "expected_checksum": backup_metadata.checksum,
                        "actual_checksum": actual_checksum,
                    },
                )

            duration = time.time() - start_time
            return CheckResult(
                "integrity_check",
                "passed",
                "Backup integrity verified successfully",
                {
                    "duration_seconds": duration,
                    "file_size_mb": actual_size / (1024 * 1024),
                },
            )

        except Exception as e:  # noqa: BLE001  # integrity-check boundary: any failure maps to a CheckResult("failed")
            duration = time.time() - start_time
            return CheckResult(
                "integrity_check",
                "failed",
                f"Integrity check failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    def check_compression_ratio(self, backup_metadata: BackupMetadata) -> CheckResult:
        """Check if compression ratio is acceptable."""
        start_time = time.time()

        try:
            # Compression ratio should be reasonable (not too high or too low)
            compression_ratio = backup_metadata.compression_ratio

            if compression_ratio < 0.1:  # Very poor compression
                status = "warning"
                message = f"Poor compression ratio: {compression_ratio:.2%}"
            elif compression_ratio > 0.95:  # Almost no compression
                status = "warning"
                message = f"Minimal compression ratio: {compression_ratio:.2%}"
            else:
                status = "passed"
                message = f"Compression ratio acceptable: {compression_ratio:.2%}"

            duration = time.time() - start_time
            return CheckResult(
                "compression_check",
                status,
                message,
                {"compression_ratio": compression_ratio, "duration_seconds": duration},
            )

        except Exception as e:  # noqa: BLE001  # compression-check boundary: any failure maps to a CheckResult("failed")
            duration = time.time() - start_time
            return CheckResult(
                "compression_check",
                "failed",
                f"Compression check failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    def perform_test_restore(self, backup_metadata: BackupMetadata) -> CheckResult:
        """Perform a test restore to verify backup is valid."""
        start_time = time.time()

        try:
            backup_path = Path(backup_metadata.source_path)
            if not backup_path.exists():
                return CheckResult(
                    "test_restore", "failed", f"Backup file not found: {backup_path}"
                )

            # Check file size limit
            if backup_path.stat().st_size > self.max_test_size_mb * 1024 * 1024:
                return CheckResult(
                    "test_restore",
                    "warning",
                    f"Backup file too large for testing ({backup_path.stat().st_size / (1024 * 1024):.1f}MB > {self.max_test_size_mb}MB)",
                )

            # Create temporary restore location
            restore_path = (
                self.test_restore_dir / f"test_restore_{backup_metadata.backup_id}"
            )
            restore_path.mkdir(parents=True, exist_ok=True)

            # Create restore manager
            restore_manager = RestoreManager(
                target_path=str(restore_path / "test_db.dhara"),
                backup_dir=str(self.backup_dir),
            )

            # Perform restore
            restore_manager._restore_from_backup(backup_metadata)  # type: ignore[reportPrivateUsage]

            # Verify restore
            if restore_manager.verify_restore(backup_metadata):
                # Cleanup
                shutil.rmtree(restore_path)
                duration = time.time() - start_time
                return CheckResult(
                    "test_restore",
                    "passed",
                    "Test restore completed successfully",
                    {
                        "duration_seconds": duration,
                        "backup_size_mb": backup_path.stat().st_size / (1024 * 1024),
                    },
                )
            else:
                # Cleanup
                shutil.rmtree(restore_path)
                duration = time.time() - start_time
                return CheckResult(
                    "test_restore",
                    "failed",
                    "Test restore verification failed",
                    {"duration_seconds": duration},
                )

        except Exception as e:  # noqa: BLE001  # test-restore boundary: any failure cleans up and maps to CheckResult("failed")
            # Cleanup on error
            restore_path = (
                self.test_restore_dir / f"test_restore_{backup_metadata.backup_id}"
            )
            if restore_path.exists():
                shutil.rmtree(restore_path)

            duration = time.time() - start_time
            return CheckResult(
                "test_restore",
                "failed",
                f"Test restore failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    def check_retention_policy(self, backup_metadata: BackupMetadata) -> CheckResult:
        """Check if backup complies with retention policy."""
        start_time = time.time()

        try:
            current_time = datetime.now(UTC)
            ts = (
                backup_metadata.timestamp
                if backup_metadata.timestamp.tzinfo is not None
                else backup_metadata.timestamp.replace(tzinfo=UTC)
            )
            retention_date = ts + timedelta(days=backup_metadata.retention_days)

            if current_time > retention_date:
                status = "warning"
                days_overdue = (current_time - retention_date).days
                message = f"Backup expired {days_overdue} days ago"
            else:
                days_remaining = (retention_date - current_time).days
                status = "passed"
                message = f"Backup has {days_remaining} days remaining"

            duration = time.time() - start_time
            return CheckResult(
                "retention_check",
                status,
                message,
                {
                    "retention_date": retention_date.isoformat(),
                    "days_remaining": (retention_date - current_time).days,
                    "duration_seconds": duration,
                },
            )

        except Exception as e:  # noqa: BLE001  # retention-check boundary: any failure maps to CheckResult("failed")
            duration = time.time() - start_time
            return CheckResult(
                "retention_check",
                "failed",
                f"Retention check failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    def check_backup_chain(self, backup_metadata: BackupMetadata) -> CheckResult:
        """Check if backup chain is intact for incremental backups."""
        start_time = time.time()

        try:
            if backup_metadata.backup_type == BackupType.INCREMENTAL:
                catalog = BackupCatalog(str(self.backup_dir))

                # Check parent backup exists
                if not backup_metadata.parent_backup_id:
                    return CheckResult(
                        "chain_check",
                        "failed",
                        "Incremental backup missing parent backup ID",
                    )

                parent_backup = catalog.get_backup(backup_metadata.parent_backup_id)
                if not parent_backup:
                    return CheckResult(
                        "chain_check",
                        "failed",
                        f"Parent backup not found: {backup_metadata.parent_backup_id}",
                    )

                # Check if parent is full backup
                if parent_backup.backup_type != BackupType.FULL:
                    return CheckResult(
                        "chain_check",
                        "failed",
                        f"Parent backup is not a full backup: {parent_backup.backup_type}",
                    )

                # Check parent is newer than current backup (should be older)
                if parent_backup.timestamp > backup_metadata.timestamp:
                    return CheckResult(
                        "chain_check",
                        "warning",
                        "Parent backup timestamp is newer than current backup",
                    )

            duration = time.time() - start_time
            return CheckResult(
                "chain_check",
                "passed",
                "Backup chain integrity verified",
                {"duration_seconds": duration},
            )

        except Exception as e:  # noqa: BLE001  # chain-check boundary: any failure maps to CheckResult("failed")
            duration = time.time() - start_time
            return CheckResult(
                "chain_check",
                "failed",
                f"Chain check failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    def run_all_checks(
        self, backup_metadata: BackupMetadata | None = None
    ) -> dict[str, CheckResult] | dict[str, dict[str, CheckResult]]:
        """Run all verification checks on a backup."""
        if backup_metadata is None:
            # Run checks on all backups
            catalog = BackupCatalog(str(self.backup_dir))
            all_results: dict[str, dict[str, CheckResult]] = {}

            for backup in catalog.get_all_backups():
                backup_results_single = self.run_all_checks(backup)
                all_results[backup.backup_id] = cast(
                    "dict[str, CheckResult]", backup_results_single
                )

            return all_results

        # Run checks on specific backup
        backup_results: dict[str, CheckResult] = {}

        # 1. Integrity check
        backup_results["integrity"] = self.check_backup_integrity(backup_metadata)

        # 2. Compression check
        backup_results["compression"] = self.check_compression_ratio(backup_metadata)

        # 3. Test restore
        backup_results["test_restore"] = self.perform_test_restore(backup_metadata)

        # 4. Retention policy
        backup_results["retention"] = self.check_retention_policy(backup_metadata)

        # 5. Chain check (for incremental backups)
        if backup_metadata.backup_type in (
            BackupType.INCREMENTAL,
            BackupType.DIFFERENTIAL,
        ):
            backup_results["chain"] = self.check_backup_chain(backup_metadata)

        return backup_results

    def generate_verification_report(
        self, backup_metadata: BackupMetadata | None = None
    ) -> dict[str, Any]:
        """Generate a comprehensive verification report."""
        results = self.run_all_checks(backup_metadata)

        if backup_metadata is not None:
            # Single backup report
            overall_status = "passed"
            results_dict: dict[str, CheckResult] = cast(
                "dict[str, CheckResult]", results
            )
            for result in results_dict.values():
                if result.status == "failed":
                    overall_status = "failed"
                    break
                elif result.status == "warning":
                    overall_status = "warning"

            return {
                "backup_id": backup_metadata.backup_id,
                "overall_status": overall_status,
                "checks": results,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        else:
            # Multi-backup report
            overall_stats = {"passed": 0, "failed": 0, "warning": 0}
            backup_reports = {}

            for backup_id, backup_results in results.items():
                status: str = "passed"
                backup_results_dict: dict[str, CheckResult] = cast(
                    "dict[str, CheckResult]", backup_results
                )
                for result in backup_results_dict.values():
                    if result.status == "failed":
                        status = "failed"
                        break
                    elif result.status == "warning":
                        status = "warning"

                overall_stats[status] += 1
                backup_reports[backup_id] = {
                    "overall_status": status,
                    "checks": backup_results,
                }

            return {
                "overall_stats": overall_stats,
                "total_backups": sum(overall_stats.values()),
                "backup_reports": backup_reports,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def cleanup_test_restores(self) -> int:
        """Clean up old test restore directories."""
        removed_count = 0

        for item in self.test_restore_dir.iterdir():
            # Combined check: is a "test_restore_*" directory older than 24 hours.
            if (
                item.is_dir()
                and item.name.startswith("test_restore_")
                and time.time() - item.stat().st_mtime > 86400
            ):
                shutil.rmtree(item)
                removed_count += 1

        return removed_count


class AsyncBackupVerification:
    """Async Dhara-backed backup verification using AsyncConnection.

    Provides async versions of verification methods using AsyncBackupCatalog
    and AsyncRestoreManager for async tool dispatch.
    """

    def __init__(
        self,
        backup_dir: str = "./backups",
        test_restore_dir: str = "./test_restores",
        timeout_seconds: int = 300,
        max_test_size_mb: int = 100,
    ) -> None:
        self.backup_dir = Path(backup_dir)
        self.test_restore_dir = Path(test_restore_dir)
        self.timeout_seconds = timeout_seconds
        self.max_test_size_mb = max_test_size_mb
        self._catalog: AsyncBackupCatalog | None = None
        self.test_restore_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Async backup verification initialized")

    async def _get_catalog(self) -> AsyncBackupCatalog:
        if self._catalog is None:
            self._catalog = AsyncBackupCatalog(self.backup_dir)
        return self._catalog

    async def check_backup_integrity_async(
        self, backup_metadata: BackupMetadata
    ) -> CheckResult:
        """Check backup file integrity (async)."""
        start_time = time.time()

        try:
            backup_path = Path(backup_metadata.source_path)
            if not backup_path.exists():
                return CheckResult(
                    "integrity_check", "failed", f"Backup file not found: {backup_path}"
                )

            actual_size = backup_path.stat().st_size
            if actual_size != backup_metadata.size_bytes:
                return CheckResult(
                    "integrity_check",
                    "failed",
                    f"File size mismatch: expected {backup_metadata.size_bytes}, got {actual_size}",
                    {
                        "expected_size": backup_metadata.size_bytes,
                        "actual_size": actual_size,
                    },
                )

            # Offload blocking file I/O + SHA-256 loop to a worker thread
            # so the event loop is not blocked on large backups.
            actual_checksum = await asyncio.to_thread(_sha256_file, backup_path)
            if actual_checksum != backup_metadata.checksum:
                return CheckResult(
                    "integrity_check",
                    "failed",
                    f"Checksum mismatch: expected {backup_metadata.checksum}, got {actual_checksum}",
                    {
                        "expected_checksum": backup_metadata.checksum,
                        "actual_checksum": actual_checksum,
                    },
                )

            duration = time.time() - start_time
            return CheckResult(
                "integrity_check",
                "passed",
                "Backup integrity verified successfully",
                {
                    "duration_seconds": duration,
                    "file_size_mb": actual_size / (1024 * 1024),
                },
            )

        except Exception as e:  # noqa: BLE001  # integrity-check boundary: any failure maps to a CheckResult("failed")
            duration = time.time() - start_time
            return CheckResult(
                "integrity_check",
                "failed",
                f"Integrity check failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    async def check_backup_chain_async(
        self, backup_metadata: BackupMetadata
    ) -> CheckResult:
        """Check if backup chain is intact (async)."""
        start_time = time.time()

        try:
            if backup_metadata.backup_type == BackupType.INCREMENTAL:
                catalog = await self._get_catalog()

                if not backup_metadata.parent_backup_id:
                    return CheckResult(
                        "chain_check",
                        "failed",
                        "Incremental backup missing parent backup ID",
                    )

                parent_backup = await catalog.get_backup_async(
                    backup_metadata.parent_backup_id
                )
                if not parent_backup:
                    return CheckResult(
                        "chain_check",
                        "failed",
                        f"Parent backup not found: {backup_metadata.parent_backup_id}",
                    )

                if parent_backup.backup_type != BackupType.FULL:
                    return CheckResult(
                        "chain_check",
                        "failed",
                        f"Parent backup is not a full backup: {parent_backup.backup_type}",
                    )

                if parent_backup.timestamp > backup_metadata.timestamp:
                    return CheckResult(
                        "chain_check",
                        "warning",
                        "Parent backup timestamp is newer than current backup",
                    )

            duration = time.time() - start_time
            return CheckResult(
                "chain_check",
                "passed",
                "Backup chain integrity verified",
                {"duration_seconds": duration},
            )

        except Exception as e:  # noqa: BLE001  # chain-check boundary: any failure maps to CheckResult("failed")
            duration = time.time() - start_time
            return CheckResult(
                "chain_check",
                "failed",
                f"Chain check failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    async def perform_test_restore_async(
        self, backup_metadata: BackupMetadata
    ) -> CheckResult:
        """Perform a test restore to verify backup is valid (async)."""
        start_time = time.time()

        try:
            backup_path = Path(backup_metadata.source_path)
            if not backup_path.exists():
                return CheckResult(
                    "test_restore", "failed", f"Backup file not found: {backup_path}"
                )

            if backup_path.stat().st_size > self.max_test_size_mb * 1024 * 1024:
                return CheckResult(
                    "test_restore",
                    "warning",
                    f"Backup file too large for testing ({backup_path.stat().st_size / (1024 * 1024):.1f}MB > {self.max_test_size_mb}MB)",
                )

            restore_path = (
                self.test_restore_dir / f"test_restore_{backup_metadata.backup_id}"
            )
            restore_path.mkdir(parents=True, exist_ok=True)

            async with AsyncRestoreManager(
                target_path=str(restore_path / "test_db.dhara"),
                backup_dir=str(self.backup_dir),
            ) as restore_manager:
                await restore_manager.restore_emergency_async(backup_metadata.backup_id)
                verified = await restore_manager.verify_restore_async(backup_metadata)

            if verified:
                shutil.rmtree(restore_path)
                duration = time.time() - start_time
                return CheckResult(
                    "test_restore",
                    "passed",
                    "Test restore completed successfully",
                    {
                        "duration_seconds": duration,
                        "backup_size_mb": backup_path.stat().st_size / (1024 * 1024),
                    },
                )
            else:
                shutil.rmtree(restore_path)
                duration = time.time() - start_time
                return CheckResult(
                    "test_restore",
                    "failed",
                    "Test restore verification failed",
                    {"duration_seconds": duration},
                )

        except Exception as e:  # noqa: BLE001  # async-test-restore boundary: cleans up and maps to CheckResult("failed")
            restore_path = (
                self.test_restore_dir / f"test_restore_{backup_metadata.backup_id}"
            )
            if restore_path.exists():
                shutil.rmtree(restore_path)

            duration = time.time() - start_time
            return CheckResult(
                "test_restore",
                "failed",
                f"Test restore failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    async def run_all_checks_async(
        self, backup_metadata: BackupMetadata | None = None
    ) -> dict[str, CheckResult] | dict[str, dict[str, CheckResult]]:
        """Run all verification checks on a backup (async)."""
        if backup_metadata is None:
            catalog = await self._get_catalog()
            all_backups = await catalog.get_all_backups_async()
            all_results: dict[str, dict[str, CheckResult]] = {}

            for backup in all_backups:
                r = await self.run_all_checks_async(backup)
                all_results[backup.backup_id] = cast("dict[str, CheckResult]", r)

            return all_results

        single_backup_results: dict[str, CheckResult] = {}
        single_backup_results["integrity"] = await self.check_backup_integrity_async(
            backup_metadata
        )
        single_backup_results["test_restore"] = await self.perform_test_restore_async(
            backup_metadata
        )
        single_backup_results["retention"] = self.check_retention_policy(
            backup_metadata
        )

        if backup_metadata.backup_type in (
            BackupType.INCREMENTAL,
            BackupType.DIFFERENTIAL,
        ):
            single_backup_results["chain"] = await self.check_backup_chain_async(
                backup_metadata
            )

        return single_backup_results

    def check_retention_policy(self, backup_metadata: BackupMetadata) -> CheckResult:
        """Check if backup complies with retention policy."""
        start_time = time.time()
        try:
            current_time = datetime.now(UTC)
            ts = (
                backup_metadata.timestamp
                if backup_metadata.timestamp.tzinfo is not None
                else backup_metadata.timestamp.replace(tzinfo=UTC)
            )
            retention_date = ts + timedelta(days=backup_metadata.retention_days)
            if current_time > retention_date:
                status = "warning"
                days_overdue = (current_time - retention_date).days
                message = f"Backup expired {days_overdue} days ago"
                days_remaining = 0
            else:
                days_remaining = (retention_date - current_time).days
                status = "passed"
                message = f"Backup has {days_remaining} days remaining"

            duration = time.time() - start_time
            return CheckResult(
                "retention_check",
                status,
                message,
                {
                    "retention_date": retention_date.isoformat(),
                    "days_remaining": days_remaining,
                    "duration_seconds": duration,
                },
            )
        except Exception as e:  # noqa: BLE001  # retention-check boundary: any failure maps to CheckResult("failed")
            duration = time.time() - start_time
            return CheckResult(
                "retention_check",
                "failed",
                f"Retention check failed: {e}",
                {"error": str(e)},
                duration_seconds=duration,
            )

    def close(self) -> None:
        """Close the catalog connection."""
        if self._catalog is not None:
            self._catalog.close()
            self._catalog = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        self.close()

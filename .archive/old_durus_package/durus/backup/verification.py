"""
Backup verification system for Durus backups.

This module provides:
- Backup file integrity verification
- Test restores
- Performance testing
- Automated validation
"""

import hashlib
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from dhruva.file_storage import FileStorage

from .manager import BackupMetadata, BackupType, CompressionEngine, EncryptionEngine
from .catalog import BackupCatalog
from .restore import RestoreManager

logger = logging.getLogger(__name__)


class CheckResult:
    """Result of a verification check."""

    def __init__(
        self,
        check_name: str,
        status: str,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
        duration_seconds: float = 0.0
    ):
        self.check_name = check_name
        self.status = status  # "passed", "failed", "warning"
        self.message = message
        self.details = details or {}
        self.duration_seconds = duration_seconds

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "check_name": self.check_name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "duration_seconds": self.duration_seconds
        }


class BackupVerification:
    """Handles backup verification and testing."""

    def __init__(
        self,
        backup_dir: str = "./backups",
        test_restore_dir: str = "./test_restores",
        timeout_seconds: int = 300,
        max_test_size_mb: int = 100
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
                    "integrity_check",
                    "failed",
                    f"Backup file not found: {backup_path}"
                )

            # Check file size
            actual_size = os.path.getsize(backup_path)
            if actual_size != backup_metadata.size_bytes:
                return CheckResult(
                    "integrity_check",
                    "failed",
                    f"File size mismatch: expected {backup_metadata.size_bytes}, got {actual_size}",
                    {"expected_size": backup_metadata.size_bytes, "actual_size": actual_size}
                )

            # Calculate checksum
            sha256_hash = hashlib.sha256()
            with open(backup_path, 'rb') as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)

            actual_checksum = sha256_hash.hexdigest()
            if actual_checksum != backup_metadata.checksum:
                return CheckResult(
                    "integrity_check",
                    "failed",
                    f"Checksum mismatch: expected {backup_metadata.checksum}, got {actual_checksum}",
                    {"expected_checksum": backup_metadata.checksum, "actual_checksum": actual_checksum}
                )

            duration = time.time() - start_time
            return CheckResult(
                "integrity_check",
                "passed",
                "Backup integrity verified successfully",
                {"duration_seconds": duration, "file_size_mb": actual_size / (1024 * 1024)}
            )

        except Exception as e:
            duration = time.time() - start_time
            return CheckResult(
                "integrity_check",
                "failed",
                f"Integrity check failed: {str(e)}",
                {"error": str(e)},
                duration_seconds=duration
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
                {"compression_ratio": compression_ratio, "duration_seconds": duration}
            )

        except Exception as e:
            duration = time.time() - start_time
            return CheckResult(
                "compression_check",
                "failed",
                f"Compression check failed: {str(e)}",
                {"error": str(e)},
                duration_seconds=duration
            )

    def perform_test_restore(self, backup_metadata: BackupMetadata) -> CheckResult:
        """Perform a test restore to verify backup is valid."""
        start_time = time.time()

        try:
            backup_path = Path(backup_metadata.source_path)
            if not backup_path.exists():
                return CheckResult(
                    "test_restore",
                    "failed",
                    f"Backup file not found: {backup_path}"
                )

            # Check file size limit
            if backup_path.stat().st_size > self.max_test_size_mb * 1024 * 1024:
                return CheckResult(
                    "test_restore",
                    "warning",
                    f"Backup file too large for testing ({backup_path.stat().st_size / (1024*1024):.1f}MB > {self.max_test_size_mb}MB)"
                )

            # Create temporary restore location
            restore_path = self.test_restore_dir / f"test_restore_{backup_metadata.backup_id}"
            restore_path.mkdir(parents=True, exist_ok=True)

            # Create restore manager
            restore_manager = RestoreManager(
                target_path=str(restore_path / "test_db.durus"),
                backup_dir=str(self.backup_dir)
            )

            # Perform restore
            restore_manager._restore_from_backup(backup_metadata)

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
                        "backup_size_mb": backup_path.stat().st_size / (1024 * 1024)
                    }
                )
            else:
                # Cleanup
                shutil.rmtree(restore_path)
                duration = time.time() - start_time
                return CheckResult(
                    "test_restore",
                    "failed",
                    "Test restore verification failed",
                    {"duration_seconds": duration}
                )

        except Exception as e:
            # Cleanup on error
            restore_path = self.test_restore_dir / f"test_restore_{backup_metadata.backup_id}"
            if restore_path.exists():
                shutil.rmtree(restore_path)

            duration = time.time() - start_time
            return CheckResult(
                "test_restore",
                "failed",
                f"Test restore failed: {str(e)}",
                {"error": str(e)},
                duration_seconds=duration
            )

    def check_retention_policy(self, backup_metadata: BackupMetadata) -> CheckResult:
        """Check if backup complies with retention policy."""
        start_time = time.time()

        try:
            current_time = datetime.now()
            retention_date = backup_metadata.timestamp + timedelta(days=backup_metadata.retention_days)

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
                    "duration_seconds": duration
                }
            )

        except Exception as e:
            duration = time.time() - start_time
            return CheckResult(
                "retention_check",
                "failed",
                f"Retention check failed: {str(e)}",
                {"error": str(e)},
                duration_seconds=duration
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
                        "Incremental backup missing parent backup ID"
                    )

                parent_backup = catalog.get_backup(backup_metadata.parent_backup_id)
                if not parent_backup:
                    return CheckResult(
                        "chain_check",
                        "failed",
                        f"Parent backup not found: {backup_metadata.parent_backup_id}"
                    )

                # Check if parent is full backup
                if parent_backup.backup_type != BackupType.FULL:
                    return CheckResult(
                        "chain_check",
                        "failed",
                        f"Parent backup is not a full backup: {parent_backup.backup_type}"
                    )

                # Check parent is newer than current backup (should be older)
                if parent_backup.timestamp > backup_metadata.timestamp:
                    return CheckResult(
                        "chain_check",
                        "warning",
                        f"Parent backup timestamp is newer than current backup"
                    )

            duration = time.time() - start_time
            return CheckResult(
                "chain_check",
                "passed",
                "Backup chain integrity verified",
                {"duration_seconds": duration}
            )

        except Exception as e:
            duration = time.time() - start_time
            return CheckResult(
                "chain_check",
                "failed",
                f"Chain check failed: {str(e)}",
                {"error": str(e)},
                duration_seconds=duration
            )

    def run_all_checks(self, backup_metadata: Optional[BackupMetadata] = None) -> Dict[str, CheckResult]:
        """Run all verification checks on a backup."""
        if backup_metadata is None:
            # Run checks on all backups
            catalog = BackupCatalog(str(self.backup_dir))
            all_results = {}

            for backup in catalog.get_all_backups():
                results = self.run_all_checks(backup)
                all_results[backup.backup_id] = results

            return all_results

        # Run checks on specific backup
        results = {}

        # 1. Integrity check
        results["integrity"] = self.check_backup_integrity(backup_metadata)

        # 2. Compression check
        results["compression"] = self.check_compression_ratio(backup_metadata)

        # 3. Test restore
        results["test_restore"] = self.perform_test_restore(backup_metadata)

        # 4. Retention policy
        results["retention"] = self.check_retention_policy(backup_metadata)

        # 5. Chain check (for incremental backups)
        if backup_metadata.backup_type in [BackupType.INCREMENTAL, BackupType.DIFFERENTIAL]:
            results["chain"] = self.check_backup_chain(backup_metadata)

        return results

    def generate_verification_report(
        self,
        backup_metadata: Optional[BackupMetadata] = None
    ) -> Dict[str, Any]:
        """Generate a comprehensive verification report."""
        results = self.run_all_checks(backup_metadata)

        if backup_metadata is not None:
            # Single backup report
            overall_status = "passed"
            for result in results.values():
                if result.status == "failed":
                    overall_status = "failed"
                    break
                elif result.status == "warning":
                    overall_status = "warning"

            return {
                "backup_id": backup_metadata.backup_id,
                "overall_status": overall_status,
                "checks": results,
                "timestamp": datetime.now().isoformat()
            }
        else:
            # Multi-backup report
            overall_stats = {"passed": 0, "failed": 0, "warning": 0}
            backup_reports = {}

            for backup_id, backup_results in results.items():
                status = "passed"
                for result in backup_results.values():
                    if result.status == "failed":
                        status = "failed"
                        break
                    elif result.status == "warning":
                        status = "warning"

                overall_stats[status] += 1
                backup_reports[backup_id] = {
                    "overall_status": status,
                    "checks": backup_results
                }

            return {
                "overall_stats": overall_stats,
                "total_backups": sum(overall_stats.values()),
                "backup_reports": backup_reports,
                "timestamp": datetime.now().isoformat()
            }

    def cleanup_test_restores(self) -> int:
        """Clean up old test restore directories."""
        removed_count = 0

        for item in self.test_restore_dir.iterdir():
            if item.is_dir() and item.name.startswith("test_restore_"):
                # Check if directory is older than 24 hours
                if time.time() - item.stat().st_mtime > 86400:
                    shutil.rmtree(item)
                    removed_count += 1

        return removed_count

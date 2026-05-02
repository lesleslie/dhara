"""
Comprehensive tests for dhara.backup.verification module.

Covers:
- CheckResult class (construction, to_dict)
- BackupVerification class (all methods)
"""

import hashlib
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dhara.backup.catalog import BackupCatalog
from dhara.backup.manager import BackupMetadata, BackupType
from dhara.backup.restore import RestoreManager
from dhara.backup.verification import BackupVerification, CheckResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metadata(
    backup_id: str = "backup-001",
    backup_type: BackupType = BackupType.FULL,
    source_path: str = "/tmp/nonexistent_backup.durus",
    size_bytes: int = 1024,
    checksum: str = "abc123",
    compression_ratio: float = 0.5,
    retention_days: int = 30,
    parent_backup_id: str | None = None,
    timestamp: datetime | None = None,
) -> BackupMetadata:
    """Create a BackupMetadata instance with sensible defaults."""
    return BackupMetadata(
        backup_id=backup_id,
        backup_type=backup_type,
        timestamp=timestamp or datetime.now(),
        source_path=source_path,
        size_bytes=size_bytes,
        checksum=checksum,
        compression_ratio=compression_ratio,
        retention_days=retention_days,
        parent_backup_id=parent_backup_id,
    )


def _write_test_file(path: str | Path, content: bytes = b"hello world backup") -> str:
    """Write content to a file and return its SHA-256 checksum."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


# ===========================================================================
# CheckResult tests
# ===========================================================================


class TestCheckResult:
    """Tests for the CheckResult data class."""

    def test_init_defaults(self):
        result = CheckResult(check_name="test", status="passed")
        assert result.check_name == "test"
        assert result.status == "passed"
        assert result.message == ""
        assert result.details == {}
        assert result.duration_seconds == 0.0

    def test_init_all_params(self):
        result = CheckResult(
            check_name="integrity_check",
            status="failed",
            message="something went wrong",
            details={"key": "value"},
            duration_seconds=1.5,
        )
        assert result.check_name == "integrity_check"
        assert result.status == "failed"
        assert result.message == "something went wrong"
        assert result.details == {"key": "value"}
        assert result.duration_seconds == 1.5

    def test_init_details_none_becomes_empty_dict(self):
        result = CheckResult(check_name="x", status="passed", details=None)
        assert result.details == {}

    def test_to_dict(self):
        result = CheckResult(
            check_name="compression_check",
            status="warning",
            message="ratio high",
            details={"ratio": 0.96},
            duration_seconds=2.0,
        )
        d = result.to_dict()
        assert d == {
            "check_name": "compression_check",
            "status": "warning",
            "message": "ratio high",
            "details": {"ratio": 0.96},
            "duration_seconds": 2.0,
        }

    def test_to_dict_empty_details(self):
        result = CheckResult(check_name="x", status="passed")
        d = result.to_dict()
        assert d["details"] == {}


# ===========================================================================
# BackupVerification.__init__
# ===========================================================================


class TestBackupVerificationInit:
    """Tests for BackupVerification constructor."""

    def test_default_params(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path / "backups"))
        assert bv.backup_dir == tmp_path / "backups"
        assert bv.test_restore_dir == Path("./test_restores")
        assert bv.timeout_seconds == 300
        assert bv.max_test_size_mb == 100

    def test_custom_params(self, tmp_path):
        test_dir = tmp_path / "test_restores"
        bv = BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(test_dir),
            timeout_seconds=600,
            max_test_size_mb=50,
        )
        assert bv.test_restore_dir == test_dir
        assert bv.timeout_seconds == 600
        assert bv.max_test_size_mb == 50

    def test_creates_test_restore_dir(self, tmp_path):
        test_dir = tmp_path / "subdir" / "test_restores"
        BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(test_dir),
        )
        assert test_dir.exists()
        assert test_dir.is_dir()

    def test_creates_test_restore_dir_already_exists(self, tmp_path):
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()
        BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(test_dir),
        )
        assert test_dir.exists()


# ===========================================================================
# check_backup_integrity
# ===========================================================================


class TestCheckBackupIntegrity:
    """Tests for BackupVerification.check_backup_integrity."""

    def test_file_not_found(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = _make_metadata(source_path="/no/such/file.durus")
        result = bv.check_backup_integrity(meta)
        assert result.check_name == "integrity_check"
        assert result.status == "failed"
        assert "not found" in result.message

    def test_file_size_mismatch(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        content = b"small content"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        meta = _make_metadata(
            source_path=str(path),
            size_bytes=999999,
            checksum=hashlib.sha256(content).hexdigest(),
        )
        result = bv.check_backup_integrity(meta)
        assert result.status == "failed"
        assert "size mismatch" in result.message
        assert result.details["expected_size"] == 999999
        assert result.details["actual_size"] == len(content)

    def test_checksum_mismatch(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        content = b"hello world"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        meta = _make_metadata(
            source_path=str(path),
            size_bytes=len(content),
            checksum="deadbeef",
        )
        result = bv.check_backup_integrity(meta)
        assert result.status == "failed"
        assert "checksum mismatch" in result.message.lower()
        assert result.details["expected_checksum"] == "deadbeef"
        assert result.details["actual_checksum"] == hashlib.sha256(content).hexdigest()

    def test_valid_file(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        content = b"valid backup data here"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        meta = _make_metadata(
            source_path=str(path),
            size_bytes=len(content),
            checksum=checksum,
        )
        result = bv.check_backup_integrity(meta)
        assert result.status == "passed"
        assert "verified successfully" in result.message
        assert "duration_seconds" in result.details
        assert "file_size_mb" in result.details

    def test_exception_handling(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = MagicMock()
        meta.source_path = "/some/path"
        # Make Path() raise an unexpected error
        with patch("dhara.backup.verification.Path", side_effect=RuntimeError("boom")):
            result = bv.check_backup_integrity(meta)
        assert result.status == "failed"
        assert "boom" in result.message
        assert result.details["error"] == "boom"


# ===========================================================================
# check_compression_ratio
# ===========================================================================


class TestCheckCompressionRatio:
    """Tests for BackupVerification.check_compression_ratio."""

    def test_poor_compression_ratio(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(compression_ratio=0.05)
        result = bv.check_compression_ratio(meta)
        assert result.check_name == "compression_check"
        assert result.status == "warning"
        assert "Poor compression" in result.message

    def test_minimal_compression_ratio(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(compression_ratio=0.96)
        result = bv.check_compression_ratio(meta)
        assert result.status == "warning"
        assert "Minimal compression" in result.message

    def test_boundary_low(self):
        """Ratio exactly 0.1 should be passed (not < 0.1)."""
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(compression_ratio=0.1)
        result = bv.check_compression_ratio(meta)
        assert result.status == "passed"

    def test_boundary_high(self):
        """Ratio exactly 0.95 should be passed (not > 0.95)."""
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(compression_ratio=0.95)
        result = bv.check_compression_ratio(meta)
        assert result.status == "passed"

    def test_good_compression_ratio(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(compression_ratio=0.5)
        result = bv.check_compression_ratio(meta)
        assert result.status == "passed"
        assert "acceptable" in result.message
        assert result.details["compression_ratio"] == 0.5

    def test_exception_handling(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = MagicMock()
        meta.compression_ratio = property(lambda self: (_ for _ in ()).throw(RuntimeError("err")))
        result = bv.check_compression_ratio(meta)
        assert result.status == "failed"
        assert "Compression check failed" in result.message


# ===========================================================================
# perform_test_restore
# ===========================================================================


class TestPerformTestRestore:
    """Tests for BackupVerification.perform_test_restore."""

    def test_file_not_found(self, tmp_path):
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        meta = _make_metadata(source_path="/no/such/file.durus", backup_id="missing")
        result = bv.perform_test_restore(meta)
        assert result.check_name == "test_restore"
        assert result.status == "failed"
        assert "not found" in result.message

    def test_file_too_large(self, tmp_path):
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(tmp_path / "test_restores"),
            max_test_size_mb=1,
        )
        # Create a file larger than 1 MB
        big_content = b"x" * (2 * 1024 * 1024)
        path = tmp_path / "big_backup.durus"
        path.write_bytes(big_content)
        meta = _make_metadata(source_path=str(path), backup_id="big", size_bytes=len(big_content))
        result = bv.perform_test_restore(meta)
        assert result.status == "warning"
        assert "too large" in result.message

    def test_successful_restore(self, tmp_path):
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        content = b"valid backup"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        meta = _make_metadata(source_path=str(path), backup_id="good")

        with patch("dhara.backup.verification.RestoreManager") as MockRM:
            mock_instance = MagicMock()
            MockRM.return_value = mock_instance
            mock_instance.verify_restore.return_value = True
            mock_instance._restore_from_backup.return_value = str(
                tmp_path / "test_restores" / "test_restore_good" / "test_db.durus"
            )

            result = bv.perform_test_restore(meta)

        assert result.status == "passed"
        assert "successfully" in result.message
        assert "duration_seconds" in result.details
        assert "backup_size_mb" in result.details
        # Restore directory should be cleaned up
        assert not (tmp_path / "test_restores" / "test_restore_good").exists()

    def test_failed_verify(self, tmp_path):
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        content = b"bad backup"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        meta = _make_metadata(source_path=str(path), backup_id="bad")

        with patch("dhara.backup.verification.RestoreManager") as MockRM:
            mock_instance = MagicMock()
            MockRM.return_value = mock_instance
            mock_instance.verify_restore.return_value = False
            mock_instance._restore_from_backup.return_value = str(
                tmp_path / "test_restores" / "test_restore_bad" / "test_db.durus"
            )

            result = bv.perform_test_restore(meta)

        assert result.status == "failed"
        assert "verification failed" in result.message
        # Restore directory should be cleaned up
        assert not (tmp_path / "test_restores" / "test_restore_bad").exists()

    def test_exception_cleanup(self, tmp_path):
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        content = b"error backup"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        meta = _make_metadata(source_path=str(path), backup_id="err")

        with patch("dhara.backup.verification.RestoreManager") as MockRM:
            MockRM.side_effect = RuntimeError("restore exploded")

            result = bv.perform_test_restore(meta)

        assert result.status == "failed"
        assert "restore exploded" in result.message
        assert result.details["error"] == "restore exploded"
        # Directory should be cleaned up after exception
        assert not (tmp_path / "test_restores" / "test_restore_err").exists()


# ===========================================================================
# check_retention_policy
# ===========================================================================


class TestCheckRetentionPolicy:
    """Tests for BackupVerification.check_retention_policy."""

    def test_backup_expired(self):
        bv = BackupVerification(backup_dir="/tmp")
        old_time = datetime.now() - timedelta(days=60)
        meta = _make_metadata(timestamp=old_time, retention_days=30)
        result = bv.check_retention_policy(meta)
        assert result.check_name == "retention_check"
        assert result.status == "warning"
        assert "expired" in result.message
        # days_overdue should be in details indirectly via retention_date
        assert "retention_date" in result.details
        assert "days_remaining" in result.details

    def test_backup_expired_with_days_overdue(self):
        bv = BackupVerification(backup_dir="/tmp")
        old_time = datetime.now() - timedelta(days=45)
        meta = _make_metadata(timestamp=old_time, retention_days=30)
        result = bv.check_retention_policy(meta)
        assert result.status == "warning"
        # 45 - 30 = 15 days overdue
        assert "15 days ago" in result.message

    def test_backup_not_expired(self):
        bv = BackupVerification(backup_dir="/tmp")
        recent_time = datetime.now() - timedelta(days=5)
        meta = _make_metadata(timestamp=recent_time, retention_days=30)
        result = bv.check_retention_policy(meta)
        assert result.status == "passed"
        assert "remaining" in result.message
        assert result.details["days_remaining"] >= 24  # at least ~25 days remaining

    def test_backup_not_expired_exact_days(self):
        bv = BackupVerification(backup_dir="/tmp")
        recent_time = datetime.now() - timedelta(days=1)
        meta = _make_metadata(timestamp=recent_time, retention_days=30)
        result = bv.check_retention_policy(meta)
        assert result.status == "passed"
        assert "28 days remaining" in result.message

    def test_exception_handling(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = MagicMock()
        meta.timestamp = "not a datetime"
        meta.retention_days = 30
        result = bv.check_retention_policy(meta)
        assert result.status == "failed"
        assert "Retention check failed" in result.message


# ===========================================================================
# check_backup_chain
# ===========================================================================


class TestCheckBackupChain:
    """Tests for BackupVerification.check_backup_chain."""

    def test_incremental_missing_parent_id(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = _make_metadata(
            backup_type=BackupType.INCREMENTAL,
            parent_backup_id=None,
        )
        result = bv.check_backup_chain(meta)
        assert result.check_name == "chain_check"
        assert result.status == "failed"
        assert "missing parent" in result.message

    def test_incremental_parent_not_found(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = _make_metadata(
            backup_type=BackupType.INCREMENTAL,
            parent_backup_id="nonexistent-parent",
        )
        with patch("dhara.backup.verification.BackupCatalog") as MockCatalog:
            mock_instance = MagicMock()
            MockCatalog.return_value = mock_instance
            mock_instance.get_backup.return_value = None

            result = bv.check_backup_chain(meta)

        assert result.status == "failed"
        assert "not found" in result.message

    def test_incremental_parent_not_full(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = _make_metadata(
            backup_type=BackupType.INCREMENTAL,
            parent_backup_id="parent-001",
        )
        parent_meta = _make_metadata(
            backup_id="parent-001",
            backup_type=BackupType.INCREMENTAL,
        )
        with patch("dhara.backup.verification.BackupCatalog") as MockCatalog:
            mock_instance = MagicMock()
            MockCatalog.return_value = mock_instance
            mock_instance.get_backup.return_value = parent_meta

            result = bv.check_backup_chain(meta)

        assert result.status == "failed"
        assert "not a full backup" in result.message

    def test_incremental_parent_is_differential(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = _make_metadata(
            backup_type=BackupType.INCREMENTAL,
            parent_backup_id="parent-diff",
        )
        parent_meta = _make_metadata(
            backup_id="parent-diff",
            backup_type=BackupType.DIFFERENTIAL,
        )
        with patch("dhara.backup.verification.BackupCatalog") as MockCatalog:
            mock_instance = MagicMock()
            MockCatalog.return_value = mock_instance
            mock_instance.get_backup.return_value = parent_meta

            result = bv.check_backup_chain(meta)

        assert result.status == "failed"
        assert "not a full backup" in result.message

    def test_incremental_parent_timestamp_newer(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        old_time = datetime.now() - timedelta(days=5)
        new_time = datetime.now() - timedelta(days=1)
        meta = _make_metadata(
            backup_type=BackupType.INCREMENTAL,
            parent_backup_id="parent-newer",
            timestamp=old_time,
        )
        parent_meta = _make_metadata(
            backup_id="parent-newer",
            backup_type=BackupType.FULL,
            timestamp=new_time,
        )
        with patch("dhara.backup.verification.BackupCatalog") as MockCatalog:
            mock_instance = MagicMock()
            MockCatalog.return_value = mock_instance
            mock_instance.get_backup.return_value = parent_meta

            result = bv.check_backup_chain(meta)

        assert result.status == "warning"
        assert "newer than current" in result.message

    def test_incremental_valid_chain(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        parent_time = datetime.now() - timedelta(days=5)
        child_time = datetime.now() - timedelta(days=1)
        meta = _make_metadata(
            backup_type=BackupType.INCREMENTAL,
            parent_backup_id="parent-valid",
            timestamp=child_time,
        )
        parent_meta = _make_metadata(
            backup_id="parent-valid",
            backup_type=BackupType.FULL,
            timestamp=parent_time,
        )
        with patch("dhara.backup.verification.BackupCatalog") as MockCatalog:
            mock_instance = MagicMock()
            MockCatalog.return_value = mock_instance
            mock_instance.get_backup.return_value = parent_meta

            result = bv.check_backup_chain(meta)

        assert result.status == "passed"
        assert "chain integrity verified" in result.message

    def test_full_backup_returns_passed(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = _make_metadata(backup_type=BackupType.FULL)
        result = bv.check_backup_chain(meta)
        assert result.status == "passed"
        assert "chain integrity verified" in result.message

    def test_differential_backup_returns_passed(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = _make_metadata(backup_type=BackupType.DIFFERENTIAL)
        result = bv.check_backup_chain(meta)
        assert result.status == "passed"
        assert "chain integrity verified" in result.message

    def test_exception_handling(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta = _make_metadata(backup_type=BackupType.INCREMENTAL, parent_backup_id="x")
        with patch("dhara.backup.verification.BackupCatalog", side_effect=RuntimeError("catalog error")):
            result = bv.check_backup_chain(meta)
        assert result.status == "failed"
        assert "catalog error" in result.message


# ===========================================================================
# run_all_checks
# ===========================================================================


class TestRunAllChecks:
    """Tests for BackupVerification.run_all_checks."""

    def test_specific_backup_runs_all_five_checks(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        content = b"backup data for full test"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        meta = _make_metadata(
            source_path=str(path),
            backup_type=BackupType.INCREMENTAL,
            parent_backup_id="parent-1",
            size_bytes=len(content),
            checksum=checksum,
        )

        with patch("dhara.backup.verification.RestoreManager") as MockRM, \
             patch("dhara.backup.verification.BackupCatalog") as MockCatalog:
            mock_rm = MagicMock()
            MockRM.return_value = mock_rm
            mock_rm.verify_restore.return_value = True
            mock_rm._restore_from_backup.return_value = "test_db.durus"

            mock_cat = MagicMock()
            MockCatalog.return_value = mock_cat
            parent_meta = _make_metadata(
                backup_id="parent-1",
                backup_type=BackupType.FULL,
                timestamp=datetime.now() - timedelta(days=1),
            )
            mock_cat.get_backup.return_value = parent_meta

            results = bv.run_all_checks(meta)

        # Should have integrity, compression, test_restore, retention, chain
        assert "integrity" in results
        assert "compression" in results
        assert "test_restore" in results
        assert "retention" in results
        assert "chain" in results
        assert len(results) == 5

    def test_non_incremental_runs_four_checks(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        content = b"full backup data"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        meta = _make_metadata(
            source_path=str(path),
            backup_type=BackupType.FULL,
            size_bytes=len(content),
            checksum=checksum,
        )

        with patch("dhara.backup.verification.RestoreManager") as MockRM:
            mock_rm = MagicMock()
            MockRM.return_value = mock_rm
            mock_rm.verify_restore.return_value = True
            mock_rm._restore_from_backup.return_value = "test_db.durus"

            results = bv.run_all_checks(meta)

        assert "integrity" in results
        assert "compression" in results
        assert "test_restore" in results
        assert "retention" in results
        assert "chain" not in results
        assert len(results) == 4

    def test_differential_runs_chain_check(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        content = b"differential backup data"
        path = tmp_path / "backup.durus"
        path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        meta = _make_metadata(
            source_path=str(path),
            backup_type=BackupType.DIFFERENTIAL,
            parent_backup_id="parent-1",
            size_bytes=len(content),
            checksum=checksum,
        )

        with patch("dhara.backup.verification.RestoreManager") as MockRM, \
             patch("dhara.backup.verification.BackupCatalog") as MockCatalog:
            mock_rm = MagicMock()
            MockRM.return_value = mock_rm
            mock_rm.verify_restore.return_value = True
            mock_rm._restore_from_backup.return_value = "test_db.durus"

            mock_cat = MagicMock()
            MockCatalog.return_value = mock_cat
            parent_meta = _make_metadata(
                backup_id="parent-1",
                backup_type=BackupType.FULL,
            )
            mock_cat.get_backup.return_value = parent_meta

            results = bv.run_all_checks(meta)

        assert "chain" in results
        assert len(results) == 5

    def test_none_runs_on_all_backups(self, tmp_path):
        bv = BackupVerification(backup_dir=str(tmp_path))
        meta1 = _make_metadata(backup_id="b1")
        meta2 = _make_metadata(backup_id="b2")

        with patch("dhara.backup.verification.BackupCatalog") as MockCatalog:
            mock_cat = MagicMock()
            MockCatalog.return_value = mock_cat
            mock_cat.get_all_backups.return_value = [meta1, meta2]

            # Patch the individual check methods to avoid file I/O
            with patch.object(bv, "check_backup_integrity", return_value=CheckResult("integrity", "passed")), \
                 patch.object(bv, "check_compression_ratio", return_value=CheckResult("compression", "passed")), \
                 patch.object(bv, "perform_test_restore", return_value=CheckResult("test_restore", "passed")), \
                 patch.object(bv, "check_retention_policy", return_value=CheckResult("retention", "passed")):

                results = bv.run_all_checks(None)

        assert "b1" in results
        assert "b2" in results
        assert len(results) == 2


# ===========================================================================
# generate_verification_report
# ===========================================================================


class TestGenerateVerificationReport:
    """Tests for BackupVerification.generate_verification_report."""

    def test_single_backup_report_overall_passed(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(backup_id="b1")

        results = {
            "integrity": CheckResult("integrity", "passed"),
            "compression": CheckResult("compression", "passed"),
            "test_restore": CheckResult("test_restore", "passed"),
            "retention": CheckResult("retention", "passed"),
        }
        with patch.object(bv, "run_all_checks", return_value=results):
            report = bv.generate_verification_report(meta)

        assert report["backup_id"] == "b1"
        assert report["overall_status"] == "passed"
        assert "checks" in report
        assert "timestamp" in report

    def test_single_backup_report_overall_failed(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(backup_id="b2")

        results = {
            "integrity": CheckResult("integrity", "passed"),
            "compression": CheckResult("compression", "failed", "bad"),
            "test_restore": CheckResult("test_restore", "passed"),
            "retention": CheckResult("retention", "passed"),
        }
        with patch.object(bv, "run_all_checks", return_value=results):
            report = bv.generate_verification_report(meta)

        assert report["overall_status"] == "failed"

    def test_single_backup_report_overall_warning(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(backup_id="b3")

        results = {
            "integrity": CheckResult("integrity", "passed"),
            "compression": CheckResult("compression", "warning"),
            "test_restore": CheckResult("test_restore", "passed"),
            "retention": CheckResult("retention", "passed"),
        }
        with patch.object(bv, "run_all_checks", return_value=results):
            report = bv.generate_verification_report(meta)

        assert report["overall_status"] == "warning"

    def test_single_backup_report_failed_overrides_warning(self):
        bv = BackupVerification(backup_dir="/tmp")
        meta = _make_metadata(backup_id="b4")

        results = {
            "integrity": CheckResult("integrity", "warning"),
            "compression": CheckResult("compression", "failed"),
            "test_restore": CheckResult("test_restore", "warning"),
            "retention": CheckResult("retention", "passed"),
        }
        with patch.object(bv, "run_all_checks", return_value=results):
            report = bv.generate_verification_report(meta)

        assert report["overall_status"] == "failed"

    def test_multi_backup_report_with_overall_stats(self):
        bv = BackupVerification(backup_dir="/tmp")

        all_results = {
            "b1": {
                "integrity": CheckResult("integrity", "passed"),
                "compression": CheckResult("compression", "passed"),
                "test_restore": CheckResult("test_restore", "passed"),
                "retention": CheckResult("retention", "passed"),
            },
            "b2": {
                "integrity": CheckResult("integrity", "failed"),
                "compression": CheckResult("compression", "passed"),
                "test_restore": CheckResult("test_restore", "passed"),
                "retention": CheckResult("retention", "warning"),
            },
        }
        with patch.object(bv, "run_all_checks", return_value=all_results):
            report = bv.generate_verification_report(None)

        assert "overall_stats" in report
        assert report["overall_stats"]["passed"] == 1
        assert report["overall_stats"]["failed"] == 1
        assert report["overall_stats"]["warning"] == 0
        assert report["total_backups"] == 2
        assert "backup_reports" in report
        assert "timestamp" in report
        assert report["backup_reports"]["b1"]["overall_status"] == "passed"
        assert report["backup_reports"]["b2"]["overall_status"] == "failed"

    def test_multi_backup_report_all_passed(self):
        bv = BackupVerification(backup_dir="/tmp")

        all_results = {
            "b1": {"integrity": CheckResult("integrity", "passed")},
            "b2": {"integrity": CheckResult("integrity", "passed")},
        }
        with patch.object(bv, "run_all_checks", return_value=all_results):
            report = bv.generate_verification_report(None)

        assert report["overall_stats"]["passed"] == 2
        assert report["overall_stats"]["failed"] == 0
        assert report["overall_stats"]["warning"] == 0
        assert report["total_backups"] == 2


# ===========================================================================
# cleanup_test_restores
# ===========================================================================


class TestCleanupTestRestores:
    """Tests for BackupVerification.cleanup_test_restores."""

    def test_removes_old_directories(self, tmp_path):
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(test_dir),
        )

        # Create old directories (older than 24 hours)
        old_dir = test_dir / "test_restore_old"
        old_dir.mkdir()
        # Set mtime to 25 hours ago
        old_time = time.time() - (25 * 3600)
        os.utime(str(old_dir), (old_time, old_time))

        # Create a recent directory (should not be removed)
        recent_dir = test_dir / "test_restore_recent"
        recent_dir.mkdir()

        # Create a non-test_restore directory (should not be removed)
        other_dir = test_dir / "other_dir"
        other_dir.mkdir()

        count = bv.cleanup_test_restores()

        assert count == 1
        assert not old_dir.exists()
        assert recent_dir.exists()
        assert other_dir.exists()

    def test_no_old_directories(self, tmp_path):
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(test_dir),
        )

        # Create a recent directory
        recent_dir = test_dir / "test_restore_recent"
        recent_dir.mkdir()

        count = bv.cleanup_test_restores()
        assert count == 0
        assert recent_dir.exists()

    def test_empty_test_restore_dir(self, tmp_path):
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(test_dir),
        )

        count = bv.cleanup_test_restores()
        assert count == 0

    def test_multiple_old_directories(self, tmp_path):
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(test_dir),
        )

        old_time = time.time() - (48 * 3600)
        for i in range(3):
            d = test_dir / f"test_restore_{i}"
            d.mkdir()
            os.utime(str(d), (old_time, old_time))

        count = bv.cleanup_test_restores()
        assert count == 3

    def test_boundary_under_24_hours_not_removed(self, tmp_path):
        """Directory just under 24 hours old should NOT be removed."""
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(test_dir),
        )

        boundary_dir = test_dir / "test_restore_boundary"
        boundary_dir.mkdir()
        # Set mtime to 23 hours ago (82800 seconds) -- safely under 86400
        boundary_time = time.time() - 82800
        os.utime(str(boundary_dir), (boundary_time, boundary_time))

        count = bv.cleanup_test_restores()
        assert count == 0
        assert boundary_dir.exists()

    def test_just_over_24_hours(self, tmp_path):
        """Directory 1 second over 24 hours should be removed."""
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()
        bv = BackupVerification(
            backup_dir=str(tmp_path),
            test_restore_dir=str(test_dir),
        )

        over_dir = test_dir / "test_restore_over"
        over_dir.mkdir()
        over_time = time.time() - 86401
        os.utime(str(over_dir), (over_time, over_time))

        count = bv.cleanup_test_restores()
        assert count == 1
        assert not over_dir.exists()

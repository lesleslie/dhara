"""Tests for dhara.backup.verification.AsyncBackupVerification.

The existing tests/test_backup_verification.py covers the sync
``BackupVerification`` class. AsyncBackupVerification mirrors most of
that surface but uses ``AsyncBackupCatalog`` and ``AsyncRestoreManager``.
This file pushes AsyncBackupVerification coverage to ~85%.

Strategy: real-file fixtures with sha256/tarball checks where helpful,
otherwise ``BackupCatalog`` and ``RestoreManager`` are mocked at the
boundary. The catalog/restore internals are covered by their own tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dhara.backup.manager import BackupMetadata, BackupType
from dhara.backup.verification import (
    AsyncBackupVerification,
    BackupVerification,
    CheckResult,
)


def _meta(
    backup_id: str,
    backup_type: BackupType,
    source_path: str,
    size_bytes: int | None = None,
    *,
    checksum: str = "deadbeef",
    retention_days: int = 30,
    days_old: int = 0,
    parent_backup_id: str | None = None,
    compression_ratio: float = 0.5,
) -> BackupMetadata:
    """Build a BackupMetadata with sensible defaults."""
    return BackupMetadata(
        backup_id=backup_id,
        backup_type=backup_type,
        source_path=source_path,
        size_bytes=size_bytes if size_bytes is not None else 0,
        timestamp=datetime.now(UTC) - timedelta(days=days_old),
        retention_days=retention_days,
        checksum=checksum,
        compression_ratio=compression_ratio,
        parent_backup_id=parent_backup_id,
    )


def _write_file(path: Path, content: bytes = b"backup contents") -> str:
    """Write content to *path* and return its sha256 hex."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


# --------------------------- AsyncBackupVerification: init ---------------------------


class TestAsyncBackupVerificationInit:
    def test_default_params(self, tmp_path: Path) -> None:
        """Defaults: backup_dir=./backups, test_restore_dir=./test_restores."""
        # Run in tmp_path to keep test isolated.
        original_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            verifier = AsyncBackupVerification()
            assert verifier.backup_dir == Path("./backups")
            assert verifier.test_restore_dir == Path("./test_restores")
            assert verifier.timeout_seconds == 300
            assert verifier.max_test_size_mb == 100
            # test_restore_dir was created.
            assert verifier.test_restore_dir.exists()
            # Catalog not yet instantiated (lazy).
            assert verifier._catalog is None
        finally:
            os.chdir(original_cwd)

    def test_custom_params(self, tmp_path: Path) -> None:
        backup_dir = tmp_path / "backups"
        test_dir = tmp_path / "test_restores"
        verifier = AsyncBackupVerification(
            backup_dir=str(backup_dir),
            test_restore_dir=str(test_dir),
            timeout_seconds=60,
            max_test_size_mb=10,
        )
        assert verifier.backup_dir == backup_dir
        assert verifier.test_restore_dir == test_dir
        assert verifier.timeout_seconds == 60
        assert verifier.max_test_size_mb == 10
        assert test_dir.exists()

    def test_existing_test_restore_dir_kept(self, tmp_path: Path) -> None:
        """Pre-existing test_restore_dir is preserved (not deleted)."""
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()
        marker = test_dir / "preserved.txt"
        marker.write_text("don't delete me")

        AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(test_dir),
        )

        assert marker.exists()
        assert marker.read_text() == "don't delete me"


# --------------------------- _get_catalog ---------------------------


class TestGetCatalog:
    def test_catalog_lazy_init(self, tmp_path: Path) -> None:
        """Catalog is None until first access."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups")
        )
        assert verifier._catalog is None

    def test_catalog_cached_on_subsequent_calls(self, tmp_path: Path) -> None:
        """After first access, the same catalog is returned."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups")
        )
        catalog1 = asyncio.run(verifier._get_catalog())
        catalog2 = asyncio.run(verifier._get_catalog())
        assert catalog1 is catalog2
        # Stored on the instance.
        assert verifier._catalog is catalog1


# --------------------------- check_backup_integrity_async ---------------------------


class TestCheckBackupIntegrityAsync:
    def test_file_not_found(self, tmp_path: Path) -> None:
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        meta = _meta("B1", BackupType.FULL, str(tmp_path / "missing.dhara"))

        result = asyncio.run(verifier.check_backup_integrity_async(meta))

        assert result.status == "failed"
        assert "Backup file not found" in result.message

    def test_file_size_mismatch(self, tmp_path: Path) -> None:
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        backup.write_bytes(b"actual content")
        meta = _meta("B1", BackupType.FULL, str(backup), size_bytes=999_999)

        result = asyncio.run(verifier.check_backup_integrity_async(meta))

        assert result.status == "failed"
        assert "size mismatch" in result.message.lower()
        assert result.details["expected_size"] == 999_999

    def test_checksum_mismatch(self, tmp_path: Path) -> None:
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        checksum = _write_file(backup, b"data")
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
            checksum="wrong-checksum",
        )

        result = asyncio.run(verifier.check_backup_integrity_async(meta))

        assert result.status == "failed"
        assert "checksum" in result.message.lower()
        assert result.details["expected_checksum"] == "wrong-checksum"
        assert result.details["actual_checksum"] == checksum

    async def test_valid_file(self, tmp_path: Path) -> None:
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        checksum = _write_file(backup, b"real backup bytes here")
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
            checksum=checksum,
        )

        result = await verifier.check_backup_integrity_async(meta)

        assert result.status == "passed"
        assert "successfully" in result.message
        assert "duration_seconds" in result.details
        assert "file_size_mb" in result.details

    def test_exception_handling(self, tmp_path: Path) -> None:
        """An unexpected error during the check is mapped to a failed result."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        # The file exists but stat() raises — drive the except branch.
        backup = tmp_path / "backup.dhara"
        backup.write_bytes(b"data")
        meta = _meta("B1", BackupType.FULL, str(backup))

        with patch.object(Path, "stat", side_effect=OSError("stat blew up")):
            result = asyncio.run(verifier.check_backup_integrity_async(meta))

        assert result.status == "failed"
        assert "Integrity check failed" in result.message


# --------------------------- check_backup_chain_async ---------------------------


class TestCheckBackupChainAsync:
    def _make_verifier(self, tmp_path: Path) -> AsyncBackupVerification:
        return AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )

    def test_non_incremental_skips_chain_check(self, tmp_path: Path) -> None:
        """FULL backups skip the catalog entirely."""
        verifier = self._make_verifier(tmp_path)
        meta = _meta("B1", BackupType.FULL, str(tmp_path / "b.dhara"))

        result = asyncio.run(verifier.check_backup_chain_async(meta))

        assert result.status == "passed"
        # No catalog was created.
        assert verifier._catalog is None

    def test_incremental_missing_parent_id(self, tmp_path: Path) -> None:
        """An INCREMENTAL with no parent_backup_id is a chain failure."""
        verifier = self._make_verifier(tmp_path)
        meta = _meta(
            "B2",
            BackupType.INCREMENTAL,
            str(tmp_path / "b.dhara"),
            parent_backup_id=None,
        )

        result = asyncio.run(verifier.check_backup_chain_async(meta))

        assert result.status == "failed"
        assert "parent backup ID" in result.message

    def test_incremental_parent_not_found(self, tmp_path: Path) -> None:
        """When parent ID is set but parent is missing from the catalog."""
        verifier = self._make_verifier(tmp_path)
        meta = _meta(
            "B2",
            BackupType.INCREMENTAL,
            str(tmp_path / "b.dhara"),
            parent_backup_id="missing-parent",
        )

        # Patch the catalog returned by _get_catalog to return None.
        with patch.object(
            verifier, "_get_catalog"
        ) as mock_get_catalog:
            mock_catalog = MagicMock()
            mock_catalog.get_backup_async = AsyncMock(return_value=None)
            mock_get_catalog.return_value = mock_catalog
            result = asyncio.run(verifier.check_backup_chain_async(meta))

        assert result.status == "failed"
        assert "Parent backup not found" in result.message

    def test_incremental_parent_not_full(self, tmp_path: Path) -> None:
        """Parent exists but isn't a FULL backup."""
        verifier = self._make_verifier(tmp_path)
        meta = _meta(
            "B2",
            BackupType.INCREMENTAL,
            str(tmp_path / "b.dhara"),
            parent_backup_id="P1",
            days_old=5,
        )

        with patch.object(
            verifier, "_get_catalog"
        ) as mock_get_catalog:
            mock_catalog = MagicMock()
            mock_catalog.get_backup_async = AsyncMock(
                return_value=_meta(
                    "P1",
                    BackupType.INCREMENTAL,
                    str(tmp_path / "p.dhara"),
                    days_old=10,
                )
            )
            mock_get_catalog.return_value = mock_catalog
            result = asyncio.run(verifier.check_backup_chain_async(meta))

        assert result.status == "failed"
        assert "is not a full backup" in result.message

    def test_incremental_parent_newer_than_current_warning(self, tmp_path: Path) -> None:
        """Parent backup timestamp is newer than current → warning."""
        verifier = self._make_verifier(tmp_path)
        meta = _meta(
            "B2",
            BackupType.INCREMENTAL,
            str(tmp_path / "b.dhara"),
            parent_backup_id="P1",
            days_old=10,
        )

        with patch.object(
            verifier, "_get_catalog"
        ) as mock_get_catalog:
            mock_catalog = MagicMock()
            # Parent is "newer" (less old) than current.
            mock_catalog.get_backup_async = AsyncMock(
                return_value=_meta(
                    "P1",
                    BackupType.FULL,
                    str(tmp_path / "p.dhara"),
                    days_old=1,
                )
            )
            mock_get_catalog.return_value = mock_catalog
            result = asyncio.run(verifier.check_backup_chain_async(meta))

        assert result.status == "warning"
        assert "newer than current backup" in result.message

    def test_incremental_chain_valid(self, tmp_path: Path) -> None:
        """Happy path: parent is FULL and older → chain passes."""
        verifier = self._make_verifier(tmp_path)
        meta = _meta(
            "B2",
            BackupType.INCREMENTAL,
            str(tmp_path / "b.dhara"),
            parent_backup_id="P1",
            days_old=5,
        )

        with patch.object(
            verifier, "_get_catalog"
        ) as mock_get_catalog:
            mock_catalog = MagicMock()
            mock_catalog.get_backup_async = AsyncMock(
                return_value=_meta(
                    "P1",
                    BackupType.FULL,
                    str(tmp_path / "p.dhara"),
                    days_old=10,
                )
            )
            mock_get_catalog.return_value = mock_catalog
            result = asyncio.run(verifier.check_backup_chain_async(meta))

        assert result.status == "passed"


# --------------------------- perform_test_restore_async ---------------------------


class TestPerformTestRestoreAsync:
    def test_file_not_found(self, tmp_path: Path) -> None:
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        meta = _meta("B1", BackupType.FULL, str(tmp_path / "missing.dhara"))

        result = asyncio.run(verifier.perform_test_restore_async(meta))

        assert result.status == "failed"
        assert "Backup file not found" in result.message

    def test_file_too_large_warning(self, tmp_path: Path) -> None:
        """Backup file size exceeds max_test_size_mb → warning, no restore."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
            max_test_size_mb=1,
        )
        backup = tmp_path / "big.dhara"
        # 2 MB file
        backup.write_bytes(b"\x00" * (2 * 1024 * 1024))
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
        )

        result = asyncio.run(verifier.perform_test_restore_async(meta))

        assert result.status == "warning"
        assert "too large" in result.message

    async def test_restore_succeeds(self, tmp_path: Path) -> None:
        """A successful test restore returns 'passed'."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        backup.write_bytes(b"small backup")
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
        )

        # Patch AsyncRestoreManager context manager to verify=True.
        with patch("dhara.backup.verification.AsyncRestoreManager") as MockMgr:
            mock_mgr = AsyncMock()
            mock_mgr.restore_emergency_async = AsyncMock()
            mock_mgr.verify_restore_async = AsyncMock(return_value=True)
            mock_mgr.__aenter__ = AsyncMock(return_value=mock_mgr)
            mock_mgr.__aexit__ = AsyncMock(return_value=None)
            MockMgr.return_value = mock_mgr

            result = await verifier.perform_test_restore_async(meta)

        assert result.status == "passed"
        assert "successfully" in result.message

    async def test_restore_verify_fails(self, tmp_path: Path) -> None:
        """verify_restore_async returns False → 'failed' result."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        backup.write_bytes(b"another backup")
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
        )

        with patch("dhara.backup.verification.AsyncRestoreManager") as MockMgr:
            mock_mgr = AsyncMock()
            mock_mgr.restore_emergency_async = AsyncMock()
            mock_mgr.verify_restore_async = AsyncMock(return_value=False)
            mock_mgr.__aenter__ = AsyncMock(return_value=mock_mgr)
            mock_mgr.__aexit__ = AsyncMock(return_value=None)
            MockMgr.return_value = mock_mgr

            result = await verifier.perform_test_restore_async(meta)

        assert result.status == "failed"
        assert "verification failed" in result.message

    async def test_restore_exception_cleanup(self, tmp_path: Path) -> None:
        """When restore raises, the test restore dir is cleaned up."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        backup.write_bytes(b"backup data")
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
        )

        with patch("dhara.backup.verification.AsyncRestoreManager") as MockMgr:
            mock_mgr = AsyncMock()
            mock_mgr.restore_emergency_async = AsyncMock(
                side_effect=RuntimeError("boom")
            )
            mock_mgr.__aenter__ = AsyncMock(return_value=mock_mgr)
            mock_mgr.__aexit__ = AsyncMock(return_value=None)
            MockMgr.return_value = mock_mgr

            result = await verifier.perform_test_restore_async(meta)

        assert result.status == "failed"
        assert "boom" in result.message
        # Cleanup ran.
        expected_restore_path = (
            verifier.test_restore_dir / f"test_restore_{meta.backup_id}"
        )
        assert not expected_restore_path.exists()


# --------------------------- check_retention_policy (sync on async class) ---------------------------


class TestCheckRetentionPolicyAsyncClass:
    def test_expired_backup_warning(self, tmp_path: Path) -> None:
        """Backup past its retention date → 'warning'."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        # Retention of 30 days, but backup is 100 days old.
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(tmp_path / "b.dhara"),
            retention_days=30,
            days_old=100,
        )

        result = verifier.check_retention_policy(meta)

        assert result.status == "warning"
        assert "expired" in result.message.lower()

    def test_active_backup_passes(self, tmp_path: Path) -> None:
        """Backup within retention → 'passed' with days_remaining."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(tmp_path / "b.dhara"),
            retention_days=30,
            days_old=5,
        )

        result = verifier.check_retention_policy(meta)

        assert result.status == "passed"
        assert "remaining" in result.message.lower()
        assert "retention_date" in result.details
        assert result.details["days_remaining"] >= 24

    def test_naive_timestamp_gets_utc_attached(self, tmp_path: Path) -> None:
        """A naive timestamp is treated as UTC."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        meta = BackupMetadata(
            backup_id="B1",
            backup_type=BackupType.FULL,
            source_path=str(tmp_path / "b.dhara"),
            size_bytes=100,
            timestamp=datetime.now() - timedelta(days=5),  # naive
            retention_days=30,
            checksum="x",
        )

        result = verifier.check_retention_policy(meta)

        # Should not raise; naive timestamp is auto-localized to UTC.
        assert result.status in {"passed", "warning"}


# --------------------------- run_all_checks_async ---------------------------


class TestRunAllChecksAsync:
    async def test_single_backup_full_runs_all_checks(self, tmp_path: Path) -> None:
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        checksum = _write_file(backup)
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
            checksum=checksum,
        )

        with patch(
            "dhara.backup.verification.AsyncRestoreManager"
        ) as MockMgr:
            mock_mgr = AsyncMock()
            mock_mgr.restore_emergency_async = AsyncMock()
            mock_mgr.verify_restore_async = AsyncMock(return_value=True)
            mock_mgr.__aenter__ = AsyncMock(return_value=mock_mgr)
            mock_mgr.__aexit__ = AsyncMock(return_value=None)
            MockMgr.return_value = mock_mgr

            results = await verifier.run_all_checks_async(meta)

        assert "integrity" in results
        assert "test_restore" in results
        assert "retention" in results
        # FULL backup has no chain check.
        assert "chain" not in results

    async def test_single_backup_incremental_includes_chain(self, tmp_path: Path) -> None:
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        checksum = _write_file(backup)
        meta = _meta(
            "B2",
            BackupType.INCREMENTAL,
            str(backup),
            size_bytes=os.path.getsize(backup),
            checksum=checksum,
            parent_backup_id="P1",
            days_old=5,
        )

        with patch(
            "dhara.backup.verification.AsyncRestoreManager"
        ) as MockMgr, patch.object(verifier, "_get_catalog") as mock_get:
            mock_mgr = AsyncMock()
            mock_mgr.restore_emergency_async = AsyncMock()
            mock_mgr.verify_restore_async = AsyncMock(return_value=True)
            mock_mgr.__aenter__ = AsyncMock(return_value=mock_mgr)
            mock_mgr.__aexit__ = AsyncMock(return_value=None)
            MockMgr.return_value = mock_mgr

            mock_catalog = MagicMock()
            mock_catalog.get_backup_async = AsyncMock(
                return_value=_meta(
                    "P1",
                    BackupType.FULL,
                    str(tmp_path / "p.dhara"),
                    days_old=10,
                )
            )
            mock_get.return_value = mock_catalog

            results = await verifier.run_all_checks_async(meta)

        assert "chain" in results
        assert results["chain"].status == "passed"

    async def test_all_backups_iterates_catalog(self, tmp_path: Path) -> None:
        """When backup_metadata is None, run_all_checks_async iterates the catalog."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )

        # Create two backups.
        b1 = tmp_path / "b1.dhara"
        b2 = tmp_path / "b2.dhara"
        cs1 = _write_file(b1)
        cs2 = _write_file(b2)
        metas = [
            _meta(
                "B1",
                BackupType.FULL,
                str(b1),
                size_bytes=os.path.getsize(b1),
                checksum=cs1,
            ),
            _meta(
                "B2",
                BackupType.FULL,
                str(b2),
                size_bytes=os.path.getsize(b2),
                checksum=cs2,
            ),
        ]

        with patch(
            "dhara.backup.verification.AsyncRestoreManager"
        ) as MockMgr, patch.object(verifier, "_get_catalog") as mock_get:
            mock_mgr = AsyncMock()
            mock_mgr.restore_emergency_async = AsyncMock()
            mock_mgr.verify_restore_async = AsyncMock(return_value=True)
            mock_mgr.__aenter__ = AsyncMock(return_value=mock_mgr)
            mock_mgr.__aexit__ = AsyncMock(return_value=None)
            MockMgr.return_value = mock_mgr

            mock_catalog = MagicMock()
            mock_catalog.get_all_backups_async = AsyncMock(return_value=metas)
            mock_get.return_value = mock_catalog

            results = await verifier.run_all_checks_async(None)

        assert "B1" in results
        assert "B2" in results


# --------------------------- close() / __aenter__ / __aexit__ ---------------------------


class TestCloseAndContextManager:
    def test_close_releases_catalog(self, tmp_path: Path) -> None:
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        # Lazy-init the catalog.
        catalog = asyncio.run(verifier._get_catalog())
        verifier.close()
        assert verifier._catalog is None
        # Calling close again is a no-op.
        verifier.close()
        assert verifier._catalog is None

    def test_close_without_catalog_is_noop(self, tmp_path: Path) -> None:
        """close() before _get_catalog() is harmless."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        verifier.close()
        assert verifier._catalog is None

    async def test_async_context_manager(self, tmp_path: Path) -> None:
        """AsyncBackupVerification is an async context manager."""
        verifier = AsyncBackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        async with verifier as ctx:
            assert ctx is verifier
            # Catalog was lazy-initialized.
            catalog1 = await verifier._get_catalog()
            assert catalog1 is verifier._catalog
        # On exit, the catalog was closed.
        assert verifier._catalog is None


# --------------------------- coverage of generate_verification_report ---------------------------


class TestGenerateVerificationReport:
    def test_single_backup_report_passed(self, tmp_path: Path) -> None:
        """generate_verification_report with one passing backup."""
        verifier = BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        checksum = _write_file(backup)
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
            checksum=checksum,
        )
        # Patch perform_test_restore to skip real restore I/O.
        verifier.perform_test_restore = MagicMock(  # type: ignore[method-assign]
            return_value=CheckResult("test_restore", "passed", "ok")
        )

        report = verifier.generate_verification_report(meta)

        assert report["backup_id"] == "B1"
        assert report["overall_status"] == "passed"
        assert "checks" in report
        assert "timestamp" in report

    def test_single_backup_report_failed_propagates(self, tmp_path: Path) -> None:
        """A failing check marks the whole report as failed."""
        verifier = BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=0,
            checksum="wrong",
        )
        # Force integrity to fail.
        report = verifier.generate_verification_report(meta)
        assert report["overall_status"] == "failed"

    def test_single_backup_report_warning_propagates(self, tmp_path: Path) -> None:
        """A warning check marks the whole report as warning (no failures)."""
        verifier = BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        backup = tmp_path / "backup.dhara"
        checksum = _write_file(backup)
        meta = _meta(
            "B1",
            BackupType.FULL,
            str(backup),
            size_bytes=os.path.getsize(backup),
            checksum=checksum,
            retention_days=30,
            days_old=100,  # expired → warning
        )
        # Skip test restore by patching.
        verifier.perform_test_restore = MagicMock(  # type: ignore[method-assign]
            return_value=CheckResult("test_restore", "passed", "ok")
        )

        report = verifier.generate_verification_report(meta)
        assert report["overall_status"] == "warning"

    def test_multi_backup_report(self, tmp_path: Path) -> None:
        """When backup_metadata is None, the report aggregates all backups."""
        verifier = BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(tmp_path / "test_restores"),
        )
        b1 = tmp_path / "b1.dhara"
        b2 = tmp_path / "b2.dhara"
        cs1 = _write_file(b1)
        cs2 = _write_file(b2)

        metas = [
            _meta(
                "B1",
                BackupType.FULL,
                str(b1),
                size_bytes=os.path.getsize(b1),
                checksum=cs1,
            ),
            _meta(
                "B2",
                BackupType.FULL,
                str(b2),
                size_bytes=os.path.getsize(b2),
                checksum=cs2,
            ),
        ]

        with patch.object(verifier, "run_all_checks") as mock_rac:
            mock_rac.return_value = {
                "B1": {
                    "integrity": CheckResult("integrity", "passed", "ok"),
                    "test_restore": CheckResult("test_restore", "passed", "ok"),
                    "retention": CheckResult("retention", "passed", "ok"),
                },
                "B2": {
                    "integrity": CheckResult("integrity", "failed", "bad"),
                    "test_restore": CheckResult("test_restore", "passed", "ok"),
                    "retention": CheckResult("retention", "passed", "ok"),
                },
            }

            report = verifier.generate_verification_report(None)

        assert report["total_backups"] == 2
        assert report["overall_stats"]["passed"] == 1
        assert report["overall_stats"]["failed"] == 1
        assert "B1" in report["backup_reports"]
        assert "B2" in report["backup_reports"]
        assert report["backup_reports"]["B2"]["overall_status"] == "failed"


# --------------------------- cleanup_test_restores ---------------------------


class TestCleanupTestRestores:
    def test_removes_old_test_restore_dirs(self, tmp_path: Path) -> None:
        """Directories older than 24 hours are removed; others are kept."""
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()

        old_dir = test_dir / "test_restore_old"
        old_dir.mkdir()
        # Set mtime to 25 hours ago.
        old_time = time.time() - (25 * 3600)
        os.utime(old_dir, (old_time, old_time))

        new_dir = test_dir / "test_restore_new"
        new_dir.mkdir()
        # mtime is now (default).

        verifier = BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(test_dir),
        )

        removed = verifier.cleanup_test_restores()

        assert removed == 1
        assert not old_dir.exists()
        assert new_dir.exists()

    def test_ignores_non_test_restore_dirs(self, tmp_path: Path) -> None:
        """Directories not starting with ``test_restore_`` are left alone."""
        test_dir = tmp_path / "test_restores"
        test_dir.mkdir()

        # Old but unrelated directory.
        unrelated = test_dir / "preserved_dir"
        unrelated.mkdir()
        old_time = time.time() - (25 * 3600)
        os.utime(unrelated, (old_time, old_time))

        # Even older test_restore_X dir.
        old_test = test_dir / "test_restore_X"
        old_test.mkdir()
        os.utime(old_test, (old_time, old_time))

        verifier = BackupVerification(
            backup_dir=str(tmp_path / "backups"),
            test_restore_dir=str(test_dir),
        )

        removed = verifier.cleanup_test_restores()

        # Only the test_restore_X is removed.
        assert removed == 1
        assert unrelated.exists()
        assert not old_test.exists()

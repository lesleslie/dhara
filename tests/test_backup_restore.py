"""
Comprehensive tests for dhara.backup.restore module.

Tests cover:
- RestorePoint class
- RestoreManager class (init, directory management, restore from backup,
  cloud download, find restore points, point-in-time restore, incremental
  chain restore, emergency restore, verify_restore, checksum, summary)
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from dhara.backup.manager import BackupMetadata, BackupType, CompressionEngine, EncryptionEngine
from dhara.backup.restore import RestoreManager, RestorePoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_backup_metadata(
    backup_id="backup-001",
    backup_type=BackupType.FULL,
    timestamp=None,
    source_path="/tmp/backup-001.durus",
    size_bytes=1024,
    checksum="abc123",
    encryption_enabled=False,
    parent_backup_id=None,
):
    """Create a BackupMetadata instance with sensible defaults."""
    if timestamp is None:
        timestamp = datetime(2026, 4, 25, 12, 0, 0)
    return BackupMetadata(
        backup_id=backup_id,
        backup_type=backup_type,
        timestamp=timestamp,
        source_path=source_path,
        size_bytes=size_bytes,
        checksum=checksum,
        encryption_enabled=encryption_enabled,
        parent_backup_id=parent_backup_id,
    )


# ===========================================================================
# RestorePoint tests
# ===========================================================================

class TestRestorePoint:
    """Tests for the RestorePoint data class."""

    def test_init_stores_all_params(self):
        ts = datetime(2026, 4, 25, 12, 0, 0)
        meta = {"size_bytes": 2048}
        rp = RestorePoint(
            backup_id="bp-001",
            timestamp=ts,
            restore_type="full",
            backup_path="/tmp/bp-001.durus",
            metadata=meta,
        )
        assert rp.backup_id == "bp-001"
        assert rp.timestamp == ts
        assert rp.restore_type == "full"
        assert rp.backup_path == "/tmp/bp-001.durus"
        assert rp.metadata == meta

    def test_str_representation(self):
        ts = datetime(2026, 4, 25, 12, 0, 0)
        rp = RestorePoint(
            backup_id="bp-001",
            timestamp=ts,
            restore_type="full",
            backup_path="/tmp/bp-001.durus",
            metadata={},
        )
        expected = f"RestorePoint(id=bp-001, type=full, time={ts})"
        assert str(rp) == expected

    def test_str_with_different_types(self):
        ts = datetime(2026, 1, 1, 0, 0, 0)
        rp = RestorePoint(
            backup_id="inc-042",
            timestamp=ts,
            restore_type="incremental",
            backup_path="/tmp/inc-042.durus",
            metadata={"parent": "base-001"},
        )
        assert "type=incremental" in str(rp)
        assert "id=inc-042" in str(rp)


# ===========================================================================
# RestoreManager.__init__ tests
# ===========================================================================

class TestRestoreManagerInit:
    """Tests for RestoreManager constructor."""

    def test_init_with_defaults(self, tmp_path):
        target = tmp_path / "restore.durus"
        rm = RestoreManager(target_path=str(target))
        assert rm.target_path == target
        assert rm.backup_dir == Path("./backups")
        assert rm.storage_type == "file"
        assert rm.encryption is None
        assert rm.cloud_adapter is None

    def test_init_with_custom_backup_dir(self, tmp_path):
        target = tmp_path / "restore.durus"
        backup_dir = tmp_path / "my_backups"
        rm = RestoreManager(target_path=str(target), backup_dir=str(backup_dir))
        assert rm.backup_dir == backup_dir

    def test_init_with_storage_type(self, tmp_path):
        target = tmp_path / "restore.durus"
        rm = RestoreManager(target_path=str(target), storage_type="s3")
        assert rm.storage_type == "s3"

    def test_init_with_encryption_key(self, tmp_path):
        target = tmp_path / "restore.durus"
        key = b"x" * 32
        with patch("dhara.backup.restore.EncryptionEngine") as mock_enc_cls:
            rm = RestoreManager(target_path=str(target), encryption_key=key)
            mock_enc_cls.assert_called_once_with(key=key)
            assert rm.encryption is not None

    def test_init_without_encryption_key_no_engine(self, tmp_path):
        target = tmp_path / "restore.durus"
        rm = RestoreManager(target_path=str(target), encryption_key=None)
        assert rm.encryption is None

    def test_init_with_cloud_adapter(self, tmp_path):
        target = tmp_path / "restore.durus"
        adapter = MagicMock()
        rm = RestoreManager(target_path=str(target), cloud_adapter=adapter)
        assert rm.cloud_adapter is adapter


# ===========================================================================
# RestoreManager._ensure_target_directory tests
# ===========================================================================

class TestEnsureTargetDirectory:
    """Tests for the _ensure_target_directory helper."""

    def test_creates_parent_directory(self, tmp_path):
        target = tmp_path / "deeply" / "nested" / "restore.durus"
        rm = RestoreManager(target_path=str(target))
        rm._ensure_target_directory()
        assert target.parent.exists()

    def test_removes_existing_directory(self, tmp_path):
        target = tmp_path / "restore.durus"
        target.mkdir()
        (target / "old_file.txt").write_text("data")
        rm = RestoreManager(target_path=str(target))
        rm._ensure_target_directory()
        assert not target.exists()

    def test_removes_existing_file(self, tmp_path):
        target = tmp_path / "restore.durus"
        target.write_text("old data")
        rm = RestoreManager(target_path=str(target))
        rm._ensure_target_directory()
        assert not target.exists()

    def test_no_op_when_path_does_not_exist(self, tmp_path):
        target = tmp_path / "nonexistent" / "restore.durus"
        rm = RestoreManager(target_path=str(target))
        rm._ensure_target_directory()
        assert target.parent.exists()
        assert not target.exists()


# ===========================================================================
# RestoreManager._restore_from_backup tests
# ===========================================================================

class TestRestoreFromBackup:
    """Tests for the _restore_from_backup method."""

    def test_file_exists_restores_successfully(self, tmp_path):
        """When the backup file exists on disk, restore from it."""
        backup_dir = tmp_path / "backups"
        backup_file = tmp_path / "backup-001.durus"
        backup_file.write_text("backup-data-here")
        target = tmp_path / "restore.durus"

        rm = RestoreManager(
            target_path=str(target),
            backup_dir=str(backup_dir),
        )

        metadata = _make_backup_metadata(source_path=str(backup_file))
        result = rm._restore_from_backup(metadata)

        assert result == str(target)
        assert target.exists()
        assert target.read_text() == "backup-data-here"

    def test_file_not_found_no_cloud_raises(self, tmp_path):
        """Without a cloud adapter, a missing file raises FileNotFoundError."""
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"

        rm = RestoreManager(
            target_path=str(target),
            backup_dir=str(backup_dir),
        )

        metadata = _make_backup_metadata(source_path="/nonexistent/backup.durus")
        with pytest.raises(FileNotFoundError, match="Backup file not found"):
            rm._restore_from_backup(metadata)

    def test_file_not_found_with_cloud_downloads(self, tmp_path):
        """With a cloud adapter, a missing file triggers a cloud download."""
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"

        cloud_adapter = MagicMock()
        rm = RestoreManager(
            target_path=str(target),
            backup_dir=str(backup_dir),
            cloud_adapter=cloud_adapter,
        )

        metadata = _make_backup_metadata(source_path="/nonexistent/backup.durus")

        # Create the file that the cloud download will "produce"
        downloaded_file = tmp_path / "downloaded.durus"
        downloaded_file.write_text("cloud-data")

        with patch.object(
            rm,
            "_download_backup_from_cloud",
            return_value=downloaded_file,
        ) as mock_download:
            result = rm._restore_from_backup(metadata)

        mock_download.assert_called_once_with(metadata)
        assert result == str(target)
        assert target.read_text() == "cloud-data"

    def test_compressed_zst_file(self, tmp_path):
        """A .zst backup is decompressed before restoring."""
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"

        # Create a compressed backup file using real zstd
        import zstandard as zstd
        compressed_file = tmp_path / "backup-001.durus.zst"
        original_data = b"decompressed-database-content"
        compressor = zstd.ZstdCompressor()
        compressed_data = compressor.compress(original_data)
        compressed_file.write_bytes(compressed_data)

        rm = RestoreManager(
            target_path=str(target),
            backup_dir=str(backup_dir),
        )

        metadata = _make_backup_metadata(source_path=str(compressed_file))

        # Mock _ensure_target_directory so we don't need to deal with the
        # side-effect of removing the target during the inner call.
        with patch.object(rm, "_ensure_target_directory"):
            result = rm._restore_from_backup(metadata)

        assert result == str(target)
        assert target.read_bytes() == original_data

    def test_encrypted_file(self, tmp_path):
        """An encrypted backup is decrypted before restoring."""
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"

        # Create an encrypted backup
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        cipher = Fernet(key)
        plaintext = b"secret-database-content"
        encrypted_data = cipher.encrypt(plaintext)
        encrypted_file = tmp_path / "backup-001.durus.zst"
        encrypted_file.write_bytes(encrypted_data)

        # Create a RestoreManager with encryption key
        mock_encryption = MagicMock()
        rm = RestoreManager(
            target_path=str(target),
            backup_dir=str(backup_dir),
            encryption_key=key,
        )
        rm.encryption = mock_encryption

        metadata = _make_backup_metadata(
            source_path=str(encrypted_file),
            encryption_enabled=True,
        )

        # Mock decrypt_file to write the decrypted data
        def fake_decrypt(src, dst):
            Path(dst).write_bytes(plaintext + b".zst")  # append .zst to match suffix check

        mock_encryption.decrypt_file.side_effect = fake_decrypt

        # Mock CompressionEngine since the decrypted file still has .zst suffix
        with patch.object(rm, "_ensure_target_directory"):
            with patch("dhara.backup.restore.CompressionEngine") as mock_comp_cls:
                mock_comp = MagicMock()
                mock_comp_cls.return_value = mock_comp

                def fake_decompress(src, dst):
                    Path(dst).write_bytes(plaintext)

                mock_comp.decompress_file.side_effect = fake_decompress

                result = rm._restore_from_backup(metadata)

        mock_encryption.decrypt_file.assert_called_once()
        mock_comp.decompress_file.assert_called_once()
        assert result == str(target)


# ===========================================================================
# RestoreManager._download_backup_from_cloud tests
# ===========================================================================

class TestDownloadBackupFromCloud:
    """Tests for the _download_backup_from_cloud method."""

    def test_normal_download(self, tmp_path):
        cloud_adapter = MagicMock()
        rm = RestoreManager(
            target_path=str(tmp_path / "restore.durus"),
            cloud_adapter=cloud_adapter,
        )

        metadata = _make_backup_metadata(source_path="/remote/backups/backup-001.durus")

        with patch("dhara.backup.restore.tempfile.mkdtemp", return_value=str(tmp_path / "cloud_tmp")):
            result = rm._download_backup_from_cloud(metadata)

        cloud_adapter.download_file.assert_called_once()
        call_args = cloud_adapter.download_file.call_args[0]
        assert call_args[0] == "durus_backups/backup-001/backup-001.durus"
        assert call_args[1].endswith("backup-001.durus")
        assert isinstance(result, Path)

    def test_no_cloud_adapter_raises_value_error(self, tmp_path):
        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        metadata = _make_backup_metadata()

        with pytest.raises(ValueError, match="No cloud adapter configured"):
            rm._download_backup_from_cloud(metadata)

    def test_download_failure_raises(self, tmp_path):
        cloud_adapter = MagicMock()
        cloud_adapter.download_file.side_effect = RuntimeError("Connection refused")
        rm = RestoreManager(
            target_path=str(tmp_path / "restore.durus"),
            cloud_adapter=cloud_adapter,
        )

        metadata = _make_backup_metadata(source_path="/remote/backup-001.durus")

        with patch("dhara.backup.restore.tempfile.mkdtemp", return_value=str(tmp_path / "cloud_tmp")):
            with pytest.raises(RuntimeError, match="Connection refused"):
                rm._download_backup_from_cloud(metadata)


# ===========================================================================
# RestoreManager.find_restore_points tests
# ===========================================================================

class TestFindRestorePoints:
    """Tests for the find_restore_points method."""

    def _make_mock_catalog(self, backups):
        """Create a mock BackupCatalog that returns the given list of BackupMetadata."""
        catalog = MagicMock()
        catalog.get_all_backups.return_value = backups
        return catalog

    def test_no_filters_returns_all(self, tmp_path):
        ts1 = datetime(2026, 4, 25, 12, 0, 0)
        ts2 = datetime(2026, 4, 24, 12, 0, 0)
        b1 = _make_backup_metadata(backup_id="b1", timestamp=ts1)
        b2 = _make_backup_metadata(backup_id="b2", timestamp=ts2)

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        with patch("dhara.backup.restore.BackupCatalog", return_value=self._make_mock_catalog([b1, b2])):
            points = rm.find_restore_points()

        assert len(points) == 2
        ids = {p.backup_id for p in points}
        assert ids == {"b1", "b2"}

    def test_start_time_filter(self, tmp_path):
        ts_early = datetime(2026, 4, 20, 12, 0, 0)
        ts_late = datetime(2026, 4, 25, 12, 0, 0)
        b1 = _make_backup_metadata(backup_id="early", timestamp=ts_early)
        b2 = _make_backup_metadata(backup_id="late", timestamp=ts_late)

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        cutoff = datetime(2026, 4, 22, 0, 0, 0)
        with patch("dhara.backup.restore.BackupCatalog", return_value=self._make_mock_catalog([b1, b2])):
            points = rm.find_restore_points(start_time=cutoff)

        assert len(points) == 1
        assert points[0].backup_id == "late"

    def test_end_time_filter(self, tmp_path):
        ts_early = datetime(2026, 4, 20, 12, 0, 0)
        ts_late = datetime(2026, 4, 25, 12, 0, 0)
        b1 = _make_backup_metadata(backup_id="early", timestamp=ts_early)
        b2 = _make_backup_metadata(backup_id="late", timestamp=ts_late)

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        cutoff = datetime(2026, 4, 22, 0, 0, 0)
        with patch("dhara.backup.restore.BackupCatalog", return_value=self._make_mock_catalog([b1, b2])):
            points = rm.find_restore_points(end_time=cutoff)

        assert len(points) == 1
        assert points[0].backup_id == "early"

    def test_backup_type_filter(self, tmp_path):
        ts1 = datetime(2026, 4, 25, 12, 0, 0)
        ts2 = datetime(2026, 4, 24, 12, 0, 0)
        b_full = _make_backup_metadata(backup_id="full-1", backup_type=BackupType.FULL, timestamp=ts1)
        b_inc = _make_backup_metadata(backup_id="inc-1", backup_type=BackupType.INCREMENTAL, timestamp=ts2)

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        with patch("dhara.backup.restore.BackupCatalog", return_value=self._make_mock_catalog([b_full, b_inc])):
            points = rm.find_restore_points(backup_type=BackupType.INCREMENTAL)

        assert len(points) == 1
        assert points[0].backup_id == "inc-1"

    def test_combined_filters(self, tmp_path):
        ts1 = datetime(2026, 4, 20, 6, 0, 0)
        ts2 = datetime(2026, 4, 22, 6, 0, 0)
        ts3 = datetime(2026, 4, 24, 6, 0, 0)
        b1 = _make_backup_metadata(backup_id="old-full", backup_type=BackupType.FULL, timestamp=ts1)
        b2 = _make_backup_metadata(backup_id="new-inc", backup_type=BackupType.INCREMENTAL, timestamp=ts2)
        b3 = _make_backup_metadata(backup_id="new-full", backup_type=BackupType.FULL, timestamp=ts3)

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        start = datetime(2026, 4, 21, 0, 0, 0)
        end = datetime(2026, 4, 23, 0, 0, 0)
        with patch("dhara.backup.restore.BackupCatalog", return_value=self._make_mock_catalog([b1, b2, b3])):
            points = rm.find_restore_points(start_time=start, end_time=end, backup_type=BackupType.INCREMENTAL)

        assert len(points) == 1
        assert points[0].backup_id == "new-inc"

    def test_empty_catalog_returns_empty_list(self, tmp_path):
        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        with patch("dhara.backup.restore.BackupCatalog", return_value=self._make_mock_catalog([])):
            points = rm.find_restore_points()

        assert points == []

    def test_sorted_newest_first(self, tmp_path):
        ts1 = datetime(2026, 4, 20, 12, 0, 0)
        ts2 = datetime(2026, 4, 25, 12, 0, 0)
        ts3 = datetime(2026, 4, 23, 12, 0, 0)
        b1 = _make_backup_metadata(backup_id="oldest", timestamp=ts1)
        b2 = _make_backup_metadata(backup_id="newest", timestamp=ts2)
        b3 = _make_backup_metadata(backup_id="middle", timestamp=ts3)

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        with patch("dhara.backup.restore.BackupCatalog", return_value=self._make_mock_catalog([b1, b2, b3])):
            points = rm.find_restore_points()

        assert [p.backup_id for p in points] == ["newest", "middle", "oldest"]


# ===========================================================================
# RestoreManager.restore_point_in_time tests
# ===========================================================================

class TestRestorePointInTime:
    """Tests for the restore_point_in_time method."""

    def test_normal_restore(self, tmp_path):
        ts = datetime(2026, 4, 25, 12, 0, 0)
        target = tmp_path / "restore.durus"
        backup_dir = tmp_path / "backups"
        backup_file = tmp_path / "backup-001.durus"
        backup_file.write_text("data")

        rm = RestoreManager(target_path=str(target), backup_dir=str(backup_dir))

        metadata = _make_backup_metadata(
            backup_id="backup-001",
            timestamp=ts,
            source_path=str(backup_file),
        )

        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = metadata

        # Mock find_restore_points to return the backup we created
        rp = RestorePoint(
            backup_id="backup-001",
            timestamp=ts,
            restore_type="full",
            backup_path=str(backup_file),
            metadata={},
        )

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            with patch.object(rm, "find_restore_points", return_value=[rp]):
                result = rm.restore_point_in_time(ts)

        mock_catalog.get_backup.assert_called_once_with("backup-001")
        assert result == str(target)
        assert target.exists()

    def test_use_incremental_true_with_available_incremental(self, tmp_path):
        """When use_incremental=True and an incremental backup is available, it is preferred."""
        ts_inc = datetime(2026, 4, 24, 12, 0, 0)
        target_time = datetime(2026, 4, 25, 0, 0, 0)
        target = tmp_path / "restore.durus"
        backup_dir = tmp_path / "backups"

        backup_file = tmp_path / "inc-001.durus"
        backup_file.write_text("inc-data")

        inc_metadata = _make_backup_metadata(
            backup_id="inc-001",
            backup_type=BackupType.INCREMENTAL,
            timestamp=ts_inc,
            source_path=str(backup_file),
        )

        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = inc_metadata

        rm = RestoreManager(target_path=str(target), backup_dir=str(backup_dir))

        # Mock find_restore_points to return both a full and an incremental backup
        rp_full = RestorePoint(
            backup_id="full-001",
            timestamp=datetime(2026, 4, 20, 12, 0, 0),
            restore_type="full",
            backup_path=str(tmp_path / "full-001.durus"),
            metadata={},
        )
        rp_inc = RestorePoint(
            backup_id="inc-001",
            timestamp=ts_inc,
            restore_type="incremental",
            backup_path=str(backup_file),
            metadata={},
        )

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            with patch.object(rm, "find_restore_points", return_value=[rp_inc, rp_full]):
                result = rm.restore_point_in_time(target_time, use_incremental=True)

        # The catalog.get_backup should have been called with the incremental backup id
        mock_catalog.get_backup.assert_called_once_with("inc-001")
        assert result == str(target)

    def test_use_incremental_true_without_incrementals_falls_back(self, tmp_path):
        """When use_incremental=True but no incremental backup exists, falls back to latest."""
        ts_full = datetime(2026, 4, 24, 12, 0, 0)
        target_time = datetime(2026, 4, 25, 0, 0, 0)
        target = tmp_path / "restore.durus"
        backup_dir = tmp_path / "backups"

        backup_file = tmp_path / "full-001.durus"
        backup_file.write_text("full-data")

        full_metadata = _make_backup_metadata(
            backup_id="full-001",
            backup_type=BackupType.FULL,
            timestamp=ts_full,
            source_path=str(backup_file),
        )

        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = full_metadata

        rm = RestoreManager(target_path=str(target), backup_dir=str(backup_dir))

        # find_restore_points will return a full backup (not incremental),
        # so the incremental_points list will be empty and it falls back.
        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            with patch.object(rm, "find_restore_points", return_value=[
                RestorePoint(
                    backup_id="full-001",
                    timestamp=ts_full,
                    restore_type="full",
                    backup_path=str(backup_file),
                    metadata={},
                )
            ]):
                result = rm.restore_point_in_time(target_time, use_incremental=True)

        mock_catalog.get_backup.assert_called_once_with("full-001")
        assert result == str(target)

    def test_no_backup_raises_value_error(self, tmp_path):
        """When no backup is available for the given time, raises ValueError."""
        target = tmp_path / "restore.durus"
        rm = RestoreManager(target_path=str(target))

        target_time = datetime(2026, 4, 25, 12, 0, 0)

        with patch.object(rm, "find_restore_points", return_value=[]):
            with pytest.raises(ValueError, match="No backup available"):
                rm.restore_point_in_time(target_time)


# ===========================================================================
# RestoreManager.restore_incremental_chain tests
# ===========================================================================

class TestRestoreIncrementalChain:
    """Tests for the restore_incremental_chain method."""

    def test_base_backup_not_found_raises(self, tmp_path):
        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = None

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            with pytest.raises(ValueError, match="Base backup not found"):
                rm.restore_incremental_chain("nonexistent-base")

    def test_normal_chain_restore(self, tmp_path):
        """Restore a base backup and apply incremental chain."""
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"

        # Create actual backup files
        base_file = tmp_path / "base-001.durus"
        base_file.write_text("base-data")
        inc_file = tmp_path / "inc-001.durus"
        inc_file.write_text("inc-data")

        base_metadata = _make_backup_metadata(
            backup_id="base-001",
            backup_type=BackupType.FULL,
            source_path=str(base_file),
        )
        inc_metadata = _make_backup_metadata(
            backup_id="inc-001",
            backup_type=BackupType.INCREMENTAL,
            timestamp=datetime(2026, 4, 26, 12, 0, 0),
            source_path=str(inc_file),
            parent_backup_id="base-001",
        )

        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = base_metadata
        mock_catalog.get_incremental_chain.return_value = [inc_metadata]

        rm = RestoreManager(target_path=str(target), backup_dir=str(backup_dir))

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            with patch.object(rm, "_merge_incremental_restore") as mock_merge:
                result = rm.restore_incremental_chain("base-001")

        mock_catalog.get_backup.assert_called_with("base-001")
        mock_catalog.get_incremental_chain.assert_called_with("base-001")
        mock_merge.assert_called_once()
        assert result == str(target)

    def test_chain_restore_multiple_incrementals(self, tmp_path):
        """Restore base + two incremental backups."""
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"

        base_file = tmp_path / "base-001.durus"
        base_file.write_text("base-data")
        inc1_file = tmp_path / "inc-001.durus"
        inc1_file.write_text("inc1-data")
        inc2_file = tmp_path / "inc-002.durus"
        inc2_file.write_text("inc2-data")

        base_metadata = _make_backup_metadata(
            backup_id="base-001",
            backup_type=BackupType.FULL,
            source_path=str(base_file),
        )
        inc1_metadata = _make_backup_metadata(
            backup_id="inc-001",
            backup_type=BackupType.INCREMENTAL,
            timestamp=datetime(2026, 4, 26, 10, 0, 0),
            source_path=str(inc1_file),
            parent_backup_id="base-001",
        )
        inc2_metadata = _make_backup_metadata(
            backup_id="inc-002",
            backup_type=BackupType.INCREMENTAL,
            timestamp=datetime(2026, 4, 26, 12, 0, 0),
            source_path=str(inc2_file),
            parent_backup_id="inc-001",
        )

        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = base_metadata
        mock_catalog.get_incremental_chain.return_value = [inc1_metadata, inc2_metadata]

        rm = RestoreManager(target_path=str(target), backup_dir=str(backup_dir))

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            with patch.object(rm, "_merge_incremental_restore") as mock_merge:
                result = rm.restore_incremental_chain("base-001")

        assert mock_merge.call_count == 2
        assert result == str(target)


# ===========================================================================
# RestoreManager._merge_incremental_restore tests
# ===========================================================================

class TestMergeIncrementalRestore:
    """Tests for the _merge_incremental_restore method."""

    def test_copies_incremental_to_final_path(self, tmp_path):
        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        incremental_path = tmp_path / "incremental_data"
        incremental_path.write_text("merged-content")
        final_path = tmp_path / "final.durus"

        rm._merge_incremental_restore(
            base_path=tmp_path / "base",
            incremental_path=incremental_path,
            final_path=final_path,
        )

        assert final_path.exists()
        assert final_path.read_text() == "merged-content"


# ===========================================================================
# RestoreManager.restore_emergency tests
# ===========================================================================

class TestRestoreEmergency:
    """Tests for the restore_emergency method."""

    def test_normal_emergency_restore(self, tmp_path):
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"
        backup_file = tmp_path / "backup-001.durus"
        backup_file.write_text("emergency-data")

        metadata = _make_backup_metadata(
            backup_id="backup-001",
            source_path=str(backup_file),
        )

        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = metadata

        rm = RestoreManager(target_path=str(target), backup_dir=str(backup_dir))

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            result = rm.restore_emergency("backup-001")

        assert result == str(target)
        assert target.read_text() == "emergency-data"

    def test_backup_not_found_raises_value_error(self, tmp_path):
        backup_dir = tmp_path / "backups"
        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = None

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"), backup_dir=str(backup_dir))

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            with pytest.raises(ValueError, match="Backup not found"):
                rm.restore_emergency("nonexistent-id")

    def test_restore_failure_raises(self, tmp_path):
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"

        metadata = _make_backup_metadata(
            backup_id="backup-001",
            source_path="/nonexistent/backup.durus",
        )

        mock_catalog = MagicMock()
        mock_catalog.get_backup.return_value = metadata

        rm = RestoreManager(target_path=str(target), backup_dir=str(backup_dir))

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            with pytest.raises(FileNotFoundError):
                rm.restore_emergency("backup-001")


# ===========================================================================
# RestoreManager.verify_restore tests
# ===========================================================================

class TestVerifyRestore:
    """Tests for the verify_restore method."""

    def test_file_does_not_exist_returns_false(self, tmp_path):
        rm = RestoreManager(target_path=str(tmp_path / "nonexistent.durus"))
        metadata = _make_backup_metadata()

        result = rm.verify_restore(metadata)
        assert result is False

    def test_storage_type_not_file_returns_true(self, tmp_path):
        """When storage_type is not 'file', verify returns True if file exists."""
        target = tmp_path / "restore.durus"
        target.write_text("data")
        rm = RestoreManager(target_path=str(target), storage_type="s3")
        metadata = _make_backup_metadata()

        result = rm.verify_restore(metadata)
        assert result is True

    def test_file_storage_type_opens_successfully(self, tmp_path):
        """When storage_type is 'file', FileStorage and Connection are used."""
        target = tmp_path / "restore.durus"
        target.write_text("data")
        rm = RestoreManager(target_path=str(target), storage_type="file")
        metadata = _make_backup_metadata()

        mock_storage = MagicMock()
        mock_connection = MagicMock()

        with patch("dhara.backup.restore.FileStorage", return_value=mock_storage) as mock_fs_cls:
            with patch("dhara.backup.restore.Connection", return_value=mock_connection) as mock_conn_cls:
                result = rm.verify_restore(metadata)

        mock_fs_cls.assert_called_once_with(str(target))
        mock_conn_cls.assert_called_once_with(mock_storage)
        mock_connection.get_root.assert_called_once()
        mock_storage.close.assert_called_once()
        assert result is True

    def test_file_storage_type_open_fails_returns_false(self, tmp_path):
        """When FileStorage or Connection raises, verify returns False."""
        target = tmp_path / "restore.durus"
        target.write_text("data")
        rm = RestoreManager(target_path=str(target), storage_type="file")
        metadata = _make_backup_metadata()

        with patch("dhara.backup.restore.FileStorage", side_effect=Exception("corrupt file")):
            result = rm.verify_restore(metadata)

        assert result is False

    def test_file_storage_get_root_fails_returns_false(self, tmp_path):
        """When Connection.get_root raises, verify returns False."""
        target = tmp_path / "restore.durus"
        target.write_text("data")
        rm = RestoreManager(target_path=str(target), storage_type="file")
        metadata = _make_backup_metadata()

        mock_storage = MagicMock()
        mock_connection = MagicMock()
        mock_connection.get_root.side_effect = Exception("bad root")

        with patch("dhara.backup.restore.FileStorage", return_value=mock_storage):
            with patch("dhara.backup.restore.Connection", return_value=mock_connection):
                result = rm.verify_restore(metadata)

        assert result is False


# ===========================================================================
# RestoreManager._calculate_checksum tests
# ===========================================================================

class TestCalculateChecksum:
    """Tests for the _calculate_checksum method."""

    def test_returns_hex_digest(self, tmp_path):
        test_file = tmp_path / "test.dat"
        test_file.write_bytes(b"hello world")

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        checksum = rm._calculate_checksum(str(test_file))

        import hashlib
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert checksum == expected
        assert len(checksum) == 64  # SHA256 hex digest is 64 chars

    def test_different_files_different_checksums(self, tmp_path):
        file1 = tmp_path / "a.dat"
        file1.write_bytes(b"content-a")
        file2 = tmp_path / "b.dat"
        file2.write_bytes(b"content-b")

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        cs1 = rm._calculate_checksum(str(file1))
        cs2 = rm._calculate_checksum(str(file2))

        assert cs1 != cs2

    def test_empty_file_checksum(self, tmp_path):
        empty_file = tmp_path / "empty.dat"
        empty_file.write_bytes(b"")

        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"))
        checksum = rm._calculate_checksum(str(empty_file))

        import hashlib
        expected = hashlib.sha256(b"").hexdigest()
        assert checksum == expected


# ===========================================================================
# RestoreManager.get_restore_summary tests
# ===========================================================================

class TestGetRestoreSummary:
    """Tests for the get_restore_summary method."""

    def test_empty_catalog(self, tmp_path):
        backup_dir = tmp_path / "backups"
        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"), backup_dir=str(backup_dir))

        mock_catalog = MagicMock()
        mock_catalog.get_all_backups.return_value = []

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            summary = rm.get_restore_summary()

        assert summary["total_backups"] == 0
        assert summary["by_type"] == {"full": 0, "incremental": 0, "differential": 0}
        assert summary["oldest_backup"] is None
        assert summary["newest_backup"] is None
        assert summary["storage_type"] == "file"
        assert summary["cloud_enabled"] is False
        assert summary["encryption_enabled"] is False

    def test_populated_catalog_with_type_grouping(self, tmp_path):
        ts1 = datetime(2026, 4, 20, 12, 0, 0)
        ts2 = datetime(2026, 4, 24, 12, 0, 0)
        ts3 = datetime(2026, 4, 22, 12, 0, 0)

        b_full = _make_backup_metadata(backup_id="f1", backup_type=BackupType.FULL, timestamp=ts1)
        b_inc = _make_backup_metadata(backup_id="i1", backup_type=BackupType.INCREMENTAL, timestamp=ts2)
        b_diff = _make_backup_metadata(backup_id="d1", backup_type=BackupType.DIFFERENTIAL, timestamp=ts3)

        backup_dir = tmp_path / "backups"
        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"), backup_dir=str(backup_dir))

        mock_catalog = MagicMock()
        mock_catalog.get_all_backups.return_value = [b_full, b_inc, b_diff]

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            summary = rm.get_restore_summary()

        assert summary["total_backups"] == 3
        assert summary["by_type"] == {"full": 1, "incremental": 1, "differential": 1}
        assert summary["oldest_backup"] == ts1
        assert summary["newest_backup"] == ts2

    def test_cloud_enabled_and_encryption_enabled_flags(self, tmp_path):
        backup_dir = tmp_path / "backups"
        target = tmp_path / "restore.durus"

        cloud_adapter = MagicMock()
        key = b"x" * 32

        with patch("dhara.backup.restore.EncryptionEngine", return_value=MagicMock()):
            rm = RestoreManager(
                target_path=str(target),
                backup_dir=str(backup_dir),
                cloud_adapter=cloud_adapter,
                encryption_key=key,
            )

        mock_catalog = MagicMock()
        mock_catalog.get_all_backups.return_value = []

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            summary = rm.get_restore_summary()

        assert summary["cloud_enabled"] is True
        assert summary["encryption_enabled"] is True

    def test_multiple_backups_same_type(self, tmp_path):
        ts1 = datetime(2026, 4, 20, 12, 0, 0)
        ts2 = datetime(2026, 4, 21, 12, 0, 0)
        ts3 = datetime(2026, 4, 22, 12, 0, 0)

        b1 = _make_backup_metadata(backup_id="f1", backup_type=BackupType.FULL, timestamp=ts1)
        b2 = _make_backup_metadata(backup_id="f2", backup_type=BackupType.FULL, timestamp=ts2)
        b3 = _make_backup_metadata(backup_id="f3", backup_type=BackupType.FULL, timestamp=ts3)

        backup_dir = tmp_path / "backups"
        rm = RestoreManager(target_path=str(tmp_path / "restore.durus"), backup_dir=str(backup_dir))

        mock_catalog = MagicMock()
        mock_catalog.get_all_backups.return_value = [b1, b2, b3]

        with patch("dhara.backup.restore.BackupCatalog", return_value=mock_catalog):
            summary = rm.get_restore_summary()

        assert summary["total_backups"] == 3
        assert summary["by_type"]["full"] == 3
        assert summary["by_type"]["incremental"] == 0
        assert summary["by_type"]["differential"] == 0

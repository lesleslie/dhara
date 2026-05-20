"""Tests for the real dhara.backup.manager module.

These tests avoid the legacy skipped backup-manager file and exercise the
actual implementation with small, isolated filesystem stubs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import dhara.backup.catalog as backup_catalog_mod
import dhara.backup.manager as backup_manager_mod
from dhara.backup.manager import BackupManager, BackupMetadata, BackupType


class DummyStorage:
    def __init__(self, filename: Path):
        self._filename = filename

    def get_filename(self) -> str:
        return str(self._filename)


class FakeCatalog:
    def __init__(self, backup_dir):
        self.backup_dir = backup_dir

    def get_last_backup(self):
        return self.last_backup

    def get_last_backup_of_type(self, backup_type):
        return self.last_backup_of_type

    def get_all_backups(self):
        return self.backups

    def remove_backup(self, backup_id):
        self.removed.append(backup_id)


def _make_source_file(tmp_path: Path, name: str = "source.db") -> Path:
    path = tmp_path / name
    path.write_bytes(b"database-bytes")
    return path


def _make_manager(tmp_path: Path, source_file: Path) -> BackupManager:
    storage = DummyStorage(source_file)
    return BackupManager(storage=storage, backup_dir=str(tmp_path / "backups"))


def _patch_file_storage(monkeypatch):
    monkeypatch.setattr(backup_manager_mod, "FileStorage", DummyStorage)


class TestBackupManagerInit:
    def test_init_creates_backup_dir_and_defaults(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)
        assert manager.backup_dir.exists()
        assert manager.compression.level == 3
        assert manager.encryption is None
        assert manager.retention_policy == {
            "full": 30,
            "incremental": 7,
            "differential": 14,
        }

    def test_init_with_encryption_key(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = BackupManager(
            storage=DummyStorage(source),
            backup_dir=str(tmp_path / "backups"),
            encryption_key=backup_manager_mod.Fernet.generate_key(),
        )
        assert manager.encryption is not None

    def test_encryption_engine_generates_key_when_missing(self):
        engine = backup_manager_mod.EncryptionEngine()
        assert engine.get_key()


class TestBackupManagerMetadata:
    def test_from_dict_round_trip(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)
        metadata = manager._create_backup_metadata(
            BackupType.FULL,
            str(source),
            source.stat().st_size,
        )

        round_tripped = BackupMetadata.from_dict(metadata.to_dict())

        assert round_tripped.backup_id == metadata.backup_id
        assert round_tripped.backup_type == metadata.backup_type
        assert round_tripped.timestamp == metadata.timestamp

    def test_create_backup_metadata_uses_retention_policy(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)
        manager.retention_policy["full"] = 99

        metadata = manager._create_backup_metadata(
            BackupType.FULL,
            str(source),
            source.stat().st_size,
        )

        assert isinstance(metadata, BackupMetadata)
        assert metadata.backup_type == BackupType.FULL
        assert metadata.source_path == str(source)
        assert metadata.retention_days == 99
        assert metadata.encryption_enabled is False

    def test_calculate_checksum(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)
        checksum = manager._calculate_checksum(str(source))
        assert len(checksum) == 64


class TestBackupManagerEngines:
    def test_compression_engine_round_trip(self, tmp_path):
        input_path = tmp_path / "input.bin"
        compressed_path = tmp_path / "input.bin.zst"
        output_path = tmp_path / "output.bin"
        input_path.write_bytes(b"hello hello hello")

        engine = backup_manager_mod.CompressionEngine(level=1)
        assert engine.compress(b"abc")
        assert engine.decompress(engine.compress(b"abc")) == b"abc"
        engine.compress_file(str(input_path), str(compressed_path))
        assert compressed_path.exists()
        engine.decompress_file(str(compressed_path), str(output_path))
        assert output_path.read_bytes() == input_path.read_bytes()

    def test_encryption_engine_round_trip(self, tmp_path):
        input_path = tmp_path / "input.bin"
        encrypted_path = tmp_path / "input.bin.enc"
        decrypted_path = tmp_path / "output.bin"
        input_path.write_bytes(b"secret bytes")

        key = backup_manager_mod.Fernet.generate_key()
        engine = backup_manager_mod.EncryptionEngine(key=key)
        assert engine.get_key() == key
        assert engine.decrypt(engine.encrypt(b"abc")) == b"abc"
        engine.encrypt_file(str(input_path), str(encrypted_path))
        assert encrypted_path.exists()
        engine.decrypt_file(str(encrypted_path), str(decrypted_path))
        assert decrypted_path.read_bytes() == input_path.read_bytes()


class TestBackupManagerBackups:
    def test_perform_full_backup(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = _make_manager(tmp_path, source)

        metadata = manager.perform_full_backup()

        assert metadata.backup_type == BackupType.FULL
        assert metadata.source_path.endswith(".durus.zst")
        assert metadata.encryption_enabled is False
        assert Path(metadata.source_path).exists()

    def test_perform_full_backup_with_encryption(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = BackupManager(
            storage=DummyStorage(source),
            backup_dir=str(tmp_path / "backups"),
            encryption_key=backup_manager_mod.Fernet.generate_key(),
        )

        metadata = manager.perform_full_backup()

        assert metadata.encryption_enabled is True
        assert metadata.source_path.endswith(".enc")

    def test_perform_incremental_backup(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = _make_manager(tmp_path, source)
        full_backup = manager.perform_full_backup()

        fake_catalog = MagicMock()
        fake_catalog.get_last_backup.return_value = full_backup
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        metadata = manager.perform_incremental_backup()

        assert metadata.backup_type == BackupType.INCREMENTAL
        assert metadata.parent_backup_id == full_backup.backup_id
        assert Path(metadata.source_path).exists()

    def test_perform_incremental_backup_with_encryption(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = BackupManager(
            storage=DummyStorage(source),
            backup_dir=str(tmp_path / "backups"),
            encryption_key=backup_manager_mod.Fernet.generate_key(),
        )
        full_backup = manager.perform_full_backup()

        fake_catalog = MagicMock()
        fake_catalog.get_last_backup.return_value = full_backup
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        metadata = manager.perform_incremental_backup()

        assert metadata.encryption_enabled is True
        assert metadata.source_path.endswith(".enc")

    def test_perform_incremental_backup_without_parent_raises(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = _make_manager(tmp_path, source)

        fake_catalog = MagicMock()
        fake_catalog.get_last_backup.return_value = None
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        with pytest.raises(ValueError, match="No previous backup found"):
            manager.perform_incremental_backup()

    def test_perform_incremental_backup_wrong_parent_type_raises(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = _make_manager(tmp_path, source)
        wrong_parent = BackupMetadata(
            backup_id="inc-parent",
            backup_type=BackupType.INCREMENTAL,
            timestamp=datetime.now(),
            source_path=str(source),
            size_bytes=1,
            checksum="deadbeef",
        )

        fake_catalog = MagicMock()
        fake_catalog.get_last_backup.return_value = wrong_parent
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        with pytest.raises(ValueError, match="requires a full backup"):
            manager.perform_incremental_backup()

    def test_perform_differential_backup(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = _make_manager(tmp_path, source)
        full_backup = manager.perform_full_backup()

        fake_catalog = MagicMock()
        fake_catalog.get_last_backup_of_type.return_value = full_backup
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        metadata = manager.perform_differential_backup()

        assert metadata.backup_type == BackupType.DIFFERENTIAL
        assert metadata.parent_backup_id == full_backup.backup_id
        assert Path(metadata.source_path).exists()

    def test_perform_differential_backup_with_backup_id(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = _make_manager(tmp_path, source)
        full_backup = manager.perform_full_backup()

        fake_catalog = MagicMock()
        fake_catalog.get_backup.return_value = full_backup
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        metadata = manager.perform_differential_backup(full_backup.backup_id)

        assert metadata.parent_backup_id == full_backup.backup_id

    def test_perform_differential_backup_without_full_raises(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = _make_manager(tmp_path, source)

        fake_catalog = MagicMock()
        fake_catalog.get_last_backup_of_type.return_value = None
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        with pytest.raises(ValueError, match="No full backup found"):
            manager.perform_differential_backup()

    def test_perform_differential_backup_with_encryption(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        _patch_file_storage(monkeypatch)
        manager = BackupManager(
            storage=DummyStorage(source),
            backup_dir=str(tmp_path / "backups"),
            encryption_key=backup_manager_mod.Fernet.generate_key(),
        )
        full_backup = manager.perform_full_backup()

        fake_catalog = MagicMock()
        fake_catalog.get_last_backup_of_type.return_value = full_backup
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        metadata = manager.perform_differential_backup()

        assert metadata.encryption_enabled is True
        assert metadata.source_path.endswith(".enc")


class TestBackupManagerCloudAndCleanup:
    def test_upload_to_cloud_no_adapter(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)
        metadata = manager._create_backup_metadata(
            BackupType.FULL,
            str(source),
            source.stat().st_size,
        )

        assert manager.upload_to_cloud(metadata) is False

    def test_upload_to_cloud_missing_file(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)
        metadata = BackupMetadata(
            backup_id="missing",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            source_path=str(tmp_path / "missing.durus"),
            size_bytes=1,
            checksum="deadbeef",
        )
        manager.cloud_adapter = MagicMock()

        assert manager.upload_to_cloud(metadata) is False

    def test_upload_to_cloud_success(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)
        cloud = MagicMock()
        manager.cloud_adapter = cloud
        metadata = manager._create_backup_metadata(
            BackupType.FULL,
            str(source),
            source.stat().st_size,
        )

        assert manager.upload_to_cloud(metadata) is True
        cloud.upload_file.assert_called_once()
        cloud.upload_json.assert_called_once()

    def test_upload_to_cloud_exception_returns_false(self, tmp_path):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)
        cloud = MagicMock()
        cloud.upload_file.side_effect = RuntimeError("boom")
        manager.cloud_adapter = cloud
        metadata = manager._create_backup_metadata(
            BackupType.FULL,
            str(source),
            source.stat().st_size,
        )

        assert manager.upload_to_cloud(metadata) is False

    def test_cleanup_old_backups(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)

        expired_file = tmp_path / "expired.durus"
        expired_file.write_bytes(b"x")
        current_file = tmp_path / "current.durus"
        current_file.write_bytes(b"y")

        expired = BackupMetadata(
            backup_id="expired",
            backup_type=BackupType.FULL,
            timestamp=datetime.now() - timedelta(days=40),
            source_path=str(expired_file),
            size_bytes=1,
            checksum="deadbeef",
            retention_days=30,
        )
        current = BackupMetadata(
            backup_id="current",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            source_path=str(current_file),
            size_bytes=1,
            checksum="deadbeef",
            retention_days=30,
        )

        fake_catalog = MagicMock()
        fake_catalog.get_all_backups.return_value = [expired, current]
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        removed = manager.cleanup_old_backups()

        assert removed == 1
        assert not expired_file.exists()
        assert current_file.exists()
        fake_catalog.remove_backup.assert_called_once_with("expired")

    def test_cleanup_old_backups_missing_file(self, tmp_path, monkeypatch):
        source = _make_source_file(tmp_path)
        manager = _make_manager(tmp_path, source)

        missing_file = tmp_path / "missing-expired.durus"
        expired = BackupMetadata(
            backup_id="missing-expired",
            backup_type=BackupType.FULL,
            timestamp=datetime.now() - timedelta(days=40),
            source_path=str(missing_file),
            size_bytes=1,
            checksum="deadbeef",
            retention_days=30,
        )

        fake_catalog = MagicMock()
        fake_catalog.get_all_backups.return_value = [expired]
        monkeypatch.setattr(backup_catalog_mod, "BackupCatalog", lambda backup_dir: fake_catalog)

        removed = manager.cleanup_old_backups()

        assert removed == 1
        fake_catalog.remove_backup.assert_called_once_with("missing-expired")

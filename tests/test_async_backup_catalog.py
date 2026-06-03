"""Tests for dhara.backup.catalog.AsyncBackupCatalog."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import shutil

from dhara.backup.catalog import AsyncBackupCatalog
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


class TestAsyncBackupCatalog:
    @pytest.fixture
    def temp_dir(self) -> Path:
        path = Path(tempfile.mkdtemp())
        yield path
        shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    async def catalog_with_conn(self, temp_dir: Path) -> AsyncBackupCatalog:
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        catalog = AsyncBackupCatalog(temp_dir, connection=conn)
        yield catalog
        catalog.close()

    @pytest.mark.asyncio
    async def test_add_and_get_backup_async(self, catalog_with_conn: AsyncBackupCatalog):
        """add_backup_async stores and get_backup_async retrieves."""
        await catalog_with_conn.add_backup_async(_meta(
            "test-backup-001",
            BackupType.FULL,
            "/data/db",
            1024,
        ))
        result = await catalog_with_conn.get_backup_async("test-backup-001")
        assert result is not None
        assert result.backup_id == "test-backup-001"
        assert result.backup_type == BackupType.FULL

    @pytest.mark.asyncio
    async def test_get_all_backups_async(self, catalog_with_conn: AsyncBackupCatalog):
        """get_all_backups_async returns all stored backups."""
        for i in range(3):
            await catalog_with_conn.add_backup_async(_meta(
                f"backup-{i}",
                BackupType.INCREMENTAL,
                f"/data/db-{i}",
                100 * i,
            ))
        backups = await catalog_with_conn.get_all_backups_async()
        assert len(backups) == 3

    @pytest.mark.asyncio
    async def test_remove_backup_async(self, catalog_with_conn: AsyncBackupCatalog):
        """remove_backup_async deletes a backup from catalog."""
        await catalog_with_conn.add_backup_async(_meta(
            "to-remove",
            BackupType.FULL,
            "/data/db",
            512,
        ))
        removed = await catalog_with_conn.remove_backup_async("to-remove")
        assert removed is True
        result = await catalog_with_conn.get_backup_async("to-remove")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_backups_by_type_async(self, catalog_with_conn: AsyncBackupCatalog):
        """get_backups_by_type_async filters by backup type."""
        await catalog_with_conn.add_backup_async(_meta(
            "full-1", BackupType.FULL, "/data/db", 100,
        ))
        await catalog_with_conn.add_backup_async(_meta(
            "incr-1", BackupType.INCREMENTAL, "/data/db", 50,
        ))
        full = await catalog_with_conn.get_backups_by_type_async(BackupType.FULL)
        assert len(full) == 1
        assert full[0].backup_id == "full-1"

    @pytest.mark.asyncio
    async def test_get_last_backup_async(self, catalog_with_conn: AsyncBackupCatalog):
        """get_last_backup_async returns most recent backup."""
        await catalog_with_conn.add_backup_async(_meta(
            "old-backup", BackupType.FULL, "/data/db", 100, days_ago=2,
        ))
        await catalog_with_conn.add_backup_async(_meta(
            "new-backup", BackupType.FULL, "/data/db", 200,
        ))
        last = await catalog_with_conn.get_last_backup_async()
        assert last is not None
        assert last.backup_id == "new-backup"

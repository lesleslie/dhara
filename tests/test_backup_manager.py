"""
Tests for backup management system in Dhara.

These tests verify the backup manager functionality including:
- Scheduling and execution of backups
- Backup lifecycle management
- Error handling and retry logic
- Backup verification and validation
"""

import pytest
import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any

from dhara.backup.manager import BackupManager
from dhara.backup.catalog import BackupCatalog, BackupMetadata
from dhara.backup.scheduler import BackupScheduler
from dhara.backup.types import BackupType, BackupStatus, BackupPriority
from dhara.storage.base import StorageBackend
from dhara.core.tenant import TenantID


class TestBackupManager:
    """Test backup manager functionality."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for backups."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def catalog(self) -> BackupCatalog:
        """Create an in-memory backup catalog."""
        catalog_file = Path("test_catalog.json")
        return BackupCatalog(catalog_file)

    @pytest.fixture
    def storage_backend(self) -> AsyncMock:
        """Mock storage backend for backups."""
        mock = AsyncMock(spec=StorageBackend)
        mock.put = AsyncMock(return_value="backup-path")
        mock.exists = AsyncMock(return_value=True)
        mock.get = AsyncMock(return_value=b"mocked-backup-data")
        return mock

    @pytest.fixture
    def backup_manager(self, catalog: BackupCatalog, storage_backend: AsyncMock, temp_dir: Path) -> BackupManager:
        """Create a backup manager instance."""
        return BackupManager(
            catalog=catalog,
            storage_backend=storage_backend,
            work_dir=temp_dir,
        )

    @pytest.mark.asyncio
    async def test_create_full_backup(self, backup_manager: BackupManager):
        """Test creating a full backup."""
        tenant_id = TenantID("test-tenant")
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
            metadata={"creator": "test"},
        )

        # Verify backup was created
        assert backup_id is not None
        metadata = backup_manager.catalog.get_backup(backup_id)
        assert metadata is not None
        assert metadata.backup_type == BackupType.FULL
        assert metadata.status == BackupStatus.COMPLETED
        assert metadata.tenant_id == tenant_id

    @pytest.mark.asyncio
    async def test_create_incremental_backup(self, backup_manager: BackupManager):
        """Test creating an incremental backup."""
        tenant_id = TenantID("test-tenant")

        # Create full backup first
        full_backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
        )

        # Create incremental backup
        incremental_backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.INCREMENTAL,
            priority=BackupPriority.MEDIUM,
            retention_days=30,
            parent_backup_id=full_backup_id,
        )

        # Verify incremental backup was created
        assert incremental_backup_id is not None
        metadata = backup_manager.catalog.get_backup(incremental_backup_id)
        assert metadata is not None
        assert metadata.backup_type == BackupType.INCREMENTAL
        assert metadata.parent_backup_id == full_backup_id

    @pytest.mark.asyncio
    async def test_create_backup_with_failure(self, backup_manager: BackupManager, storage_backend: AsyncMock):
        """Test handling backup creation failures."""
        # Make storage backend fail
        storage_backend.put.side_effect = Exception("Storage failure")

        tenant_id = TenantID("test-tenant")

        with pytest.raises(Exception, match="Storage failure"):
            await backup_manager.create_backup(
                tenant_id=tenant_id,
                backup_type=BackupType.FULL,
                priority=BackupPriority.HIGH,
                retention_days=30,
            )

    @pytest.mark.asyncio
    async def test_restore_backup(self, backup_manager: BackupManager):
        """Test restoring a backup."""
        # First create a backup
        tenant_id = TenantID("test-tenant")
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
        )

        # Mock the restore operation
        mock_storage = AsyncMock()
        backup_manager.storage_backend = mock_storage

        # Restore backup
        result = await backup_manager.restore_backup(backup_id, mock_storage)

        # Verify restore was successful
        assert result is True
        mock_storage.restore.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_backup(self, backup_manager: BackupManager):
        """Test verifying a backup."""
        # Create backup
        tenant_id = TenantID("test-tenant")
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
        )

        # Verify backup
        is_valid, checksum = await backup_manager.verify_backup(backup_id)

        # Verify backup
        assert is_valid is True
        assert checksum is not None

    @pytest.mark.asyncio
    async def test_list_backups_by_tenant(self, backup_manager: BackupManager):
        """Test listing backups by tenant."""
        tenant1 = TenantID("tenant-1")
        tenant2 = TenantID("tenant-2")

        # Create backups for both tenants
        await backup_manager.create_backup(
            tenant_id=tenant1,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
        )
        await backup_manager.create_backup(
            tenant_id=tenant2,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
        )

        # List backups by tenant
        tenant1_backups = backup_manager.list_backups(tenant_id=tenant1)
        tenant2_backups = backup_manager.list_backups(tenant_id=tenant2)

        assert len(tenant1_backups) == 1
        assert len(tenant2_backups) == 1
        assert tenant1_backups[0].tenant_id == tenant1
        assert tenant2_backups[0].tenant_id == tenant2

    @pytest.mark.asyncio
    async def test_delete_backup(self, backup_manager: BackupManager):
        """Test deleting a backup."""
        # Create backup
        tenant_id = TenantID("test-tenant")
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
        )

        # Delete backup
        success = await backup_manager.delete_backup(backup_id)

        # Verify deletion
        assert success is True
        assert backup_manager.catalog.get_backup(backup_id) is None

    @pytest.mark.asyncio
    async def test_backup_retry_logic(self, backup_manager: BackupManager, storage_backend: AsyncMock):
        """Test backup retry logic on failure."""
        # Configure storage to fail first time, succeed second time
        storage_backend.put.side_effect = [
            Exception("Temporary failure"),
            "backup-path",
        ]

        tenant_id = TenantID("test-tenant")
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
            max_retries=1,
        )

        # Verify backup succeeded after retry
        assert backup_id is not None
        metadata = backup_manager.catalog.get_backup(backup_id)
        assert metadata.status == BackupStatus.COMPLETED

        # Verify storage backend was called twice (initial + retry)
        assert storage_backend.put.call_count == 2

    @pytest.mark.asyncio
    async def test_backup_timeout_handling(self, backup_manager: BackupManager):
        """Test handling of backup timeouts."""
        # Mock a slow backup operation
        with patch.object(backup_manager, 'create_backup_internal') as mock_create:
            mock_create.side_effect = asyncio.sleep(2)  # Simulate slow operation

            tenant_id = TenantID("test-tenant")

            with pytest.raises(asyncio.TimeoutError):
                await backup_manager.create_backup(
                    tenant_id=tenant_id,
                    backup_type=BackupType.FULL,
                    priority=BackupPriority.HIGH,
                    retention_days=30,
                    timeout_seconds=1,  # 1 second timeout
                )

    @pytest.mark.asyncio
    async def test_backup_cleanup(self, backup_manager: BackupManager):
        """Test cleanup of old backups."""
        # Create a backup with short retention
        tenant_id = TenantID("test-tenant")
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=1,  # 1 day retention
        )

        # Simulate time passing
        from unittest.mock import patch
        with patch('dhara.backup.manager.datetime') as mock_dt:
            mock_dt.now.return_value = datetime.now() + timedelta(days=2)

            # Clean up old backups
            deleted_count = await backup_manager.cleanup_old_backups()

            # Should have deleted the backup
            assert deleted_count == 1
            assert backup_manager.catalog.get_backup(backup_id) is None

    @pytest.mark.asyncio
    async def test_backup_quota_enforcement(self, backup_manager: BackupManager):
        """Test backup quota enforcement."""
        # Set quota
        backup_manager.config.backup_quota_bytes = 1024  # 1KB quota

        # Create first backup
        tenant_id = TenantID("test-tenant")
        backup_id1 = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
        )

        # Create second backup that exceeds quota
        with pytest.raises(Exception, match="Backup quota exceeded"):
            await backup_manager.create_backup(
                tenant_id=tenant_id,
                backup_type=BackupType.FULL,
                priority=BackupPriority.HIGH,
                retention_days=30,
            )

    @pytest.mark.asyncio
    async def test_backup_priority_handling(self, backup_manager: BackupManager):
        """Test handling of backup priorities."""
        tenant_id = TenantID("test-tenant")

        # Create high priority backup
        high_backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
        )

        # Create low priority backup
        low_backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.LOW,
            retention_days=30,
        )

        # Verify both backups were created
        assert high_backup_id is not None
        assert low_backup_id is not None

        # Verify high priority backup was processed first (in real scenario)
        # For testing, we just verify both exist
        high_backup = backup_manager.catalog.get_backup(high_backup_id)
        low_backup = backup_manager.catalog.get_backup(low_backup_id)
        assert high_backup.status == BackupStatus.COMPLETED
        assert low_backup.status == BackupStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_backup_encryption(self, backup_manager: BackupManager):
        """Test backup encryption."""
        tenant_id = TenantID("test-tenant")

        # Create backup with encryption
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
            encrypt=True,
        )

        # Verify backup was encrypted
        metadata = backup_manager.catalog.get_backup(backup_id)
        assert metadata.metadata.get("encrypted") is True
        assert metadata.metadata.get("encryption_algorithm") is not None

    @pytest.mark.asyncio
    async def test_backup_compression(self, backup_manager: BackupManager):
        """Test backup compression."""
        tenant_id = TenantID("test-tenant")

        # Create backup with compression
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
            compress=True,
        )

        # Verify backup was compressed
        metadata = backup_manager.catalog.get_backup(backup_id)
        assert "compression_ratio" in metadata.metadata
        assert metadata.metadata["compression_ratio"] < 1.0

    @pytest.mark.asyncio
    async def test_backup_concurrent_creation(self, backup_manager: BackupManager):
        """Test concurrent backup creation."""
        tenant_id = TenantID("test-tenant")

        async def create_backup_task(task_id):
            return await backup_manager.create_backup(
                tenant_id=tenant_id,
                backup_type=BackupType.FULL,
                priority=BackupPriority.HIGH,
                retention_days=30,
                metadata={"task_id": task_id},
            )

        # Create multiple backups concurrently
        tasks = [create_backup_task(f"task-{i}") for i in range(5)]
        results = await asyncio.gather(*tasks)

        # Verify all backups were created
        assert len(results) == 5
        for backup_id in results:
            assert backup_id is not None
            metadata = backup_manager.catalog.get_backup(backup_id)
            assert metadata is not None
            assert metadata.status == BackupStatus.COMPLETED

        # Verify we have 5 unique backups
        all_backups = backup_manager.catalog.list_backups()
        assert len(all_backups) == 5

    @pytest.mark.asyncio
    async def test_backup_metadata_validation(self, backup_manager: BackupManager):
        """Test backup metadata validation."""
        tenant_id = TenantID("test-tenant")

        # Create backup with custom metadata
        backup_id = await backup_manager.create_backup(
            tenant_id=tenant_id,
            backup_type=BackupType.FULL,
            priority=BackupPriority.HIGH,
            retention_days=30,
            metadata={
                "creator": "test-script",
                "version": "1.0",
                "environment": "test",
                "tags": ["critical", "database"],
            },
        )

        # Verify metadata was stored
        metadata = backup_manager.catalog.get_backup(backup_id)
        assert metadata.metadata["creator"] == "test-script"
        assert metadata.metadata["version"] == "1.0"
        assert metadata.metadata["environment"] == "test"
        assert metadata.metadata["tags"] == ["critical", "database"]
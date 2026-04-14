"""
Tests for backup catalog management in Dhara.

These tests verify the backup catalog functionality including:
- Adding, updating, and listing backups
- Backup metadata management
- Catalog persistence and recovery
"""

import pytest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock

# Mock missing dependencies for testing
try:
    from dhara.backup.catalog import BackupCatalog, BackupMetadata
    from dhara.backup.types import BackupType, BackupStatus
    from dhara.storage.base import StorageBackend
    from dhara.core.tenant import TenantID
except ImportError as e:
    print(f"Warning: Import error {e}. Using mock implementations.")

    class MockTenantID:
        def __init__(self, value):
            self.value = value

        def __str__(self):
            return self.value

    class BackupType:
        FULL = "full"
        INCREMENTAL = "incremental"
        DIFFERENTIAL = "differential"

    class BackupStatus:
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"

    class BackupMetadata:
        def __init__(self, tenant_id, backup_id, timestamp, backup_type,
                    storage_backend, storage_path, size_bytes, checksum,
                    status, retention_days=30, **kwargs):
            self.tenant_id = tenant_id
            self.backup_id = backup_id
            self.timestamp = timestamp
            self.backup_type = backup_type
            self.storage_backend = storage_backend
            self.storage_path = storage_path
            self.size_bytes = size_bytes
            self.checksum = checksum
            self.status = status
            self.retention_days = retention_days
            self.metadata = kwargs

        def to_dict(self):
            return {
                "tenant_id": str(self.tenant_id),
                "backup_id": self.backup_id,
                "timestamp": self.timestamp.isoformat(),
                "backup_type": self.backup_type,
                "storage_backend": self.storage_backend,
                "storage_path": self.storage_path,
                "size_bytes": self.size_bytes,
                "checksum": self.checksum,
                "status": self.status,
                "retention_days": self.retention_days,
                "metadata": self.metadata,
            }

    class MockBackupCatalog:
        def __init__(self, catalog_file):
            self.catalog_file = Path(catalog_file)
            self.backups = {}

        def add_backup(self, metadata):
            self.backups[metadata.backup_id] = metadata

        def get_backup(self, backup_id):
            return self.backups.get(backup_id)

        def list_backups(self, **filters):
            results = []
            for backup in self.backups.values():
                match = True
                for key, value in filters.items():
                    if getattr(backup, key) != value:
                        match = False
                        break
                if match:
                    results.append(backup)
            return results

        def delete_backup(self, backup_id):
            if backup_id in self.backups:
                del self.backups[backup_id]
                return True
            return False

        def exists(self):
            return self.catalog_file.exists()

        def validate(self):
            return True, []

    BackupCatalog = MockBackupCatalog
    StorageBackend = AsyncMock


class TestBackupCatalog:
    """Test backup catalog functionality."""

    @pytest.fixture
    def catalog_file(self) -> Path:
        """Create a temporary catalog file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_file = Path(f.name)
        yield temp_file
        # Cleanup
        if temp_file.exists():
            temp_file.unlink()

    @pytest.fixture
    def catalog(self, catalog_file: Path) -> BackupCatalog:
        """Create a backup catalog instance."""
        return BackupCatalog(catalog_file)

    @pytest.fixture
    def sample_backup_metadata(self) -> BackupMetadata:
        """Create sample backup metadata for testing."""
        return BackupMetadata(
            tenant_id=TenantID("test-tenant"),
            backup_id="test-backup-123",
            timestamp=datetime.now(),
            backup_type=BackupType.FULL,
            storage_backend="local",
            storage_path="/path/to/backup",
            size_bytes=1024,
            checksum="abc123",
            status=BackupStatus.COMPLETED,
            retention_days=30,
            compression_ratio=0.8,
            metadata={"creator": "test-script", "version": "1.0"},
        )

    def test_catalog_initialization(self, catalog: BackupCatalog, catalog_file: Path):
        """Test that catalog initializes correctly."""
        assert catalog.catalog_file == catalog_file
        assert len(catalog.list_backups()) == 0
        assert not catalog.exists()

    def test_add_backup(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test adding a backup to the catalog."""
        # Add backup
        catalog.add_backup(sample_backup_metadata)

        # Verify backup was added
        backups = catalog.list_backups()
        assert len(backups) == 1
        assert backups[0].backup_id == "test-backup-123"

        # Test persistence
        new_catalog = BackupCatalog(catalog.catalog_file)
        backups = new_catalog.list_backups()
        assert len(backups) == 1
        assert backups[0].backup_id == "test-backup-123"

    def test_add_duplicate_backup(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test that adding a duplicate backup updates the existing one."""
        # Add backup first time
        catalog.add_backup(sample_backup_metadata)
        backups = catalog.list_backups()
        assert len(backups) == 1

        # Update backup metadata
        updated_metadata = sample_backup_metadata.model_copy()
        updated_metadata.status = BackupStatus.VERIFYING
        catalog.add_backup(updated_metadata)

        # Verify backup was updated
        backups = catalog.list_backups()
        assert len(backups) == 1
        assert backups[0].status == BackupStatus.VERIFYING

    def test_get_backup(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test retrieving a specific backup by ID."""
        # Add backup
        catalog.add_backup(sample_backup_metadata)

        # Get backup
        backup = catalog.get_backup("test-backup-123")
        assert backup is not None
        assert backup.backup_id == "test-backup-123"
        assert backup.tenant_id == TenantID("test-tenant")

        # Test non-existent backup
        backup = catalog.get_backup("non-existent")
        assert backup is None

    def test_list_backups_by_type(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test listing backups by type."""
        # Add different type backups
        full_backup = sample_backup_metadata.model_copy()
        full_backup.backup_id = "full-backup"
        full_backup.backup_type = BackupType.FULL

        incremental_backup = sample_backup_metadata.model_copy()
        incremental_backup.backup_id = "incremental-backup"
        incremental_backup.backup_type = BackupType.INCREMENTAL

        catalog.add_backup(full_backup)
        catalog.add_backup(incremental_backup)

        # Test listing by type
        full_backups = catalog.list_backups(backup_type=BackupType.FULL)
        incremental_backups = catalog.list_backups(backup_type=BackupType.INCREMENTAL)

        assert len(full_backups) == 1
        assert full_backups[0].backup_id == "full-backup"
        assert len(incremental_backups) == 1
        assert incremental_backups[0].backup_id == "incremental-backup"

    def test_list_backups_by_tenant(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test listing backups by tenant ID."""
        # Add backups for different tenants
        backup1 = sample_backup_metadata.model_copy()
        backup1.tenant_id = TenantID("tenant-1")
        backup1.backup_id = "backup-tenant-1"

        backup2 = sample_backup_metadata.model_copy()
        backup2.tenant_id = TenantID("tenant-2")
        backup2.backup_id = "backup-tenant-2"

        catalog.add_backup(backup1)
        catalog.add_backup(backup2)

        # Test listing by tenant
        tenant1_backups = catalog.list_backups(tenant_id=TenantID("tenant-1"))
        tenant2_backups = catalog.list_backups(tenant_id=TenantID("tenant-2"))

        assert len(tenant1_backups) == 1
        assert tenant1_backups[0].tenant_id == TenantID("tenant-1")
        assert len(tenant2_backups) == 1
        assert tenant2_backups[0].tenant_id == TenantID("tenant-2")

    def test_list_backups_by_status(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test listing backups by status."""
        # Add backups with different statuses
        completed_backup = sample_backup_metadata.model_copy()
        completed_backup.backup_id = "completed-backup"
        completed_backup.status = BackupStatus.COMPLETED

        failed_backup = sample_backup_metadata.model_copy()
        failed_backup.backup_id = "failed-backup"
        failed_backup.status = BackupStatus.FAILED

        catalog.add_backup(completed_backup)
        catalog.add_backup(failed_backup)

        # Test listing by status
        completed_backups = catalog.list_backups(status=BackupStatus.COMPLETED)
        failed_backups = catalog.list_backups(status=BackupStatus.FAILED)

        assert len(completed_backups) == 1
        assert completed_backups[0].status == BackupStatus.COMPLETED
        assert len(failed_backups) == 1
        assert failed_backups[0].status == BackupStatus.FAILED

    def test_list_backups_pagination(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test listing backups with pagination."""
        # Add multiple backups
        for i in range(5):
            metadata = sample_backup_metadata.model_copy()
            metadata.backup_id = f"backup-{i}"
            catalog.add_backup(metadata)

        # Test pagination
        page1 = catalog.list_backups(limit=2)
        page2 = catalog.list_backups(limit=2, offset=2)
        page3 = catalog.list_backups(limit=2, offset=4)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1
        assert page1[0].backup_id == "backup-0"
        assert page2[0].backup_id == "backup-2"
        assert page3[0].backup_id == "backup-4"

    def test_delete_backup(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test deleting a backup from the catalog."""
        # Add backup
        catalog.add_backup(sample_backup_metadata)
        assert len(catalog.list_backups()) == 1

        # Delete backup
        deleted = catalog.delete_backup("test-backup-123")
        assert deleted is True
        assert len(catalog.list_backups()) == 0

        # Test deleting non-existent backup
        deleted = catalog.delete_backup("non-existent")
        assert deleted is False

    def test_get_latest_backup(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test getting the latest backup for a tenant."""
        # Add multiple backups for the same tenant
        backups = []
        for i in range(3):
            metadata = sample_backup_metadata.model_copy()
            metadata.backup_id = f"backup-{i}"
            metadata.timestamp = datetime.now() + timedelta(hours=i)
            backups.append(metadata)
            catalog.add_backup(metadata)

        # Get latest backup
        latest = catalog.get_latest_backup(TenantID("test-tenant"))
        assert latest is not None
        assert latest.backup_id == "backup-2"  # Last one added

    def test_get_backups_before_timestamp(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test getting backups before a specific timestamp."""
        # Add backups with different timestamps
        now = datetime.now()
        metadata1 = sample_backup_metadata.model_copy()
        metadata1.backup_id = "backup-old"
        metadata1.timestamp = now - timedelta(days=2)

        metadata2 = sample_backup_metadata.model_copy()
        metadata2.backup_id = "backup-new"
        metadata2.timestamp = now - timedelta(days=1)

        catalog.add_backup(metadata1)
        catalog.add_backup(metadata2)

        # Get backups before timestamp
        threshold = now - timedelta(days=1.5)
        old_backups = catalog.get_backups_before_timestamp(TenantID("test-tenant"), threshold)

        assert len(old_backups) == 1
        assert old_backups[0].backup_id == "backup-old"

    def test_calculate_storage_usage(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test calculating storage usage."""
        # Add backups
        backups = []
        for i in range(3):
            metadata = sample_backup_metadata.model_copy()
            metadata.backup_id = f"backup-{i}"
            metadata.size_bytes = 1024 * (i + 1)  # 1KB, 2KB, 3KB
            backups.append(metadata)
            catalog.add_backup(metadata)

        # Calculate usage
        usage = catalog.calculate_storage_usage()

        assert usage["total_backups"] == 3
        assert usage["total_size_bytes"] == 6144  # 1+2+3 KB
        assert usage["average_size_bytes"] == 2048  # 6144/3

    def test_catalog_cleanup(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test cleaning up old backups based on retention."""
        # Add backup with short retention
        metadata = sample_backup_metadata.model_copy()
        metadata.backup_id = "short-retention"
        metadata.retention_days = 1  # 1 day retention
        catalog.add_backup(metadata)

        # Add backup with long retention
        metadata2 = sample_backup_metadata.model_copy()
        metadata2.backup_id = "long-retention"
        metadata2.retention_days = 30  # 30 day retention
        catalog.add_backup(metadata2)

        # Simulate time passing
        from unittest.mock import patch
        with patch('dhara.backup.catalog.datetime') as mock_dt:
            mock_dt.now.return_value = datetime.now() + timedelta(days=2)

            # Clean up old backups
            deleted = catalog.cleanup_old_backups()

            # Should have deleted one backup
            assert deleted == 1
            assert len(catalog.list_backups()) == 1
            assert catalog.list_backups()[0].backup_id == "long-retention"

    def test_catalog_validation(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test catalog validation functionality."""
        # Add valid backup
        catalog.add_backup(sample_backup_metadata)

        # Validate catalog
        is_valid, errors = catalog.validate()
        assert is_valid is True
        assert len(errors) == 0

        # Test validation with missing required field
        invalid_metadata = sample_backup_metadata.model_copy()
        invalid_metadata.backup_id = ""  # Invalid backup ID
        invalid_metadata.status = BackupStatus.PENDING

        # Add invalid metadata
        catalog.add_backup(invalid_metadata)

        # Should now be invalid
        is_valid, errors = catalog.validate()
        assert is_valid is False
        assert len(errors) > 0

    def test_catalog_migration(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test catalog migration functionality."""
        # Add backup
        catalog.add_backup(sample_backup_metadata)

        # Simulate migration
        migration_info = catalog.migrate()

        assert migration_info["original_backups"] == 1
        assert migration_info["migrated_backups"] == 1
        assert "migration_timestamp" in migration_info
        assert "version" in migration_info

    def test_concurrent_access(self, catalog: BackupCatalog, sample_backup_metadata: BackupMetadata):
        """Test concurrent access to the catalog."""
        import threading
        from queue import Queue

        results = Queue()

        def add_backup(backup_id):
            try:
                metadata = sample_backup_metadata.model_copy()
                metadata.backup_id = backup_id
                catalog.add_backup(metadata)
                results.put(("success", backup_id))
            except Exception as e:
                results.put(("error", str(e)))

        # Add backups concurrently
        threads = []
        for i in range(10):
            thread = threading.Thread(target=add_backup, args=(f"concurrent-{i}",))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all backups were added
        success_count = 0
        error_count = 0
        while not results.empty():
            result = results.get()
            if result[0] == "success":
                success_count += 1
            else:
                error_count += 1

        assert success_count == 10
        assert error_count == 0

        # Verify all backups are in catalog
        backups = catalog.list_backups()
        assert len(backups) == 10
"""
Integration tests for backup and restore functionality.

These tests cover:
- Backup creation and management
- Restore operations
- Compression and encryption
- Verification and testing
- Cloud storage integration
"""

import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add durus to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from druva.backup.manager import BackupManager, BackupType
from druva.backup.restore import RestoreManager
from druva.backup.catalog import BackupCatalog
from druva.backup.scheduler import BackupScheduler, BackupJob
from druva.backup.storage import StorageFactory
from druva.backup.verification import BackupVerification
from druva.file_storage import FileStorage
from druva.persistent_dict import PersistentDict


class TestBackupManager:
    """Test backup manager functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.temp_dir, "test_db.durus")
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

        # Create test database
        storage = FileStorage(self.test_db)
        root = PersistentDict()
        root["test_key"] = "test_value"
        root["nested"] = {"inner": "data"}
        storage.store(root)
        storage.close()

        # Create backup manager
        self.storage = FileStorage(self.test_db)
        self.backup_manager = BackupManager(
            storage=self.storage,
            backup_dir=self.backup_dir,
            compression_level=3
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_full_backup(self):
        """Test full backup creation."""
        # Perform backup
        metadata = self.backup_manager.perform_full_backup()

        # Verify metadata
        assert metadata.backup_type == BackupType.FULL
        assert metadata.backup_id is not None
        assert os.path.exists(metadata.source_path)
        assert metadata.size_bytes > 0
        assert metadata.checksum is not None

        # Verify backup file exists
        backup_path = Path(metadata.source_path)
        assert backup_path.exists()
        assert backup_path.suffix == ".zst"  # Compressed

    def test_incremental_backup(self):
        """Test incremental backup creation."""
        # First create a full backup
        full_backup = self.backup_manager.perform_full_backup()
        catalog = BackupCatalog(self.backup_dir)
        catalog.add_backup(full_backup)

        # Modify database
        root = self.storage.open()
        root["new_key"] = "new_value"
        root.close()

        # Perform incremental backup
        incremental_backup = self.backup_manager.perform_incremental_backup(full_backup.backup_id)

        # Verify metadata
        assert incremental_backup.backup_type == BackupType.INCREMENTAL
        assert incremental_backup.parent_backup_id == full_backup.backup_id
        assert incremental_backup.backup_id != full_backup.backup_id

    def test_differential_backup(self):
        """Test differential backup creation."""
        # First create a full backup
        full_backup = self.backup_manager.perform_full_backup()
        catalog = BackupCatalog(self.backup_dir)
        catalog.add_backup(full_backup)

        # Modify database
        root = self.storage.open()
        root["diff_key"] = "diff_value"
        root.close()

        # Perform differential backup
        diff_backup = self.backup_manager.perform_differential_backup(full_backup.backup_id)

        # Verify metadata
        assert diff_backup.backup_type == BackupType.DIFFERENTIAL
        assert diff_backup.parent_backup_id == full_backup.backup_id

    def test_cleanup_old_backups(self):
        """Test cleanup of old backups."""
        # Create test backups
        full_backup = self.backup_manager.perform_full_backup()
        catalog = BackupCatalog(self.backup_dir)
        catalog.add_backup(full_backup)

        # Modify retention
        full_backup.retention_days = -1  # Expired
        catalog.add_backup(full_backup)

        # Run cleanup
        removed_count = self.backup_manager.cleanup_old_backups()

        # Verify cleanup worked
        assert removed_count > 0
        backups = catalog.get_all_backups()
        assert len(backups) == 0

    def test_checksum_verification(self):
        """Test checksum calculation."""
        # Create a test file
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content")

        # Calculate checksum
        checksum = self.backup_manager._calculate_checksum(test_file)
        assert len(checksum) == 64  # SHA256 hex length
        assert checksum == "b961ffe92a7dfec0f3ceba3a70a338d7f3530cc33e8c45f6c6b8458353e8e69e"


class TestRestoreManager:
    """Test restore manager functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.temp_dir, "test_db.durus")
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        self.restore_dir = os.path.join(self.temp_dir, "restores")
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.restore_dir, exist_ok=True)

        # Create test database
        storage = FileStorage(self.test_db)
        root = PersistentDict()
        root["original_key"] = "original_value"
        storage.store(root)
        storage.close()

        # Create backup
        self.storage = FileStorage(self.test_db)
        self.backup_manager = BackupManager(
            storage=self.storage,
            backup_dir=self.backup_dir
        )
        self.backup_metadata = self.backup_manager.perform_full_backup()

        # Add to catalog
        self.catalog = BackupCatalog(self.backup_dir)
        self.catalog.add_backup(self.backup_metadata)

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_simple_restore(self):
        """Test basic restore functionality."""
        # Create restore manager
        restore_manager = RestoreManager(
            target_path=os.path.join(self.restore_dir, "restored_db.durus"),
            backup_dir=self.backup_dir
        )

        # Perform restore
        restored_path = restore_manager._restore_from_backup(self.backup_metadata)

        # Verify restore
        assert os.path.exists(restored_path)
        assert os.path.getsize(restored_path) > 0

        # Verify database is accessible
        restored_storage = FileStorage(restored_path)
        root = restored_storage.open()
        assert "original_key" in root
        assert root["original_key"] == "original_value"
        restored_storage.close()

    def test_find_restore_points(self):
        """Test finding restore points."""
        restore_manager = RestoreManager(
            target_path=os.path.join(self.restore_dir, "test.durus"),
            backup_dir=self.backup_dir
        )

        # Find all restore points
        restore_points = restore_manager.find_restore_points()

        assert len(restore_points) == 1
        assert restore_points[0].backup_id == self.backup_metadata.backup_id

    def test_point_in_time_restore(self):
        """Test point-in-time restore."""
        restore_manager = RestoreManager(
            target_path=os.path.join(self.restore_dir, "restored_db.durus"),
            backup_dir=self.backup_dir
        )

        # Test with backup timestamp
        restore_point = restore_manager.restore_point_in_time(self.backup_metadata.timestamp)

        assert os.path.exists(restore_point)

    def test_verify_restore(self):
        """Test restore verification."""
        restore_manager = RestoreManager(
            target_path=os.path.join(self.restore_dir, "restored_db.durus"),
            backup_dir=self.backup_dir
        )

        # Restore and verify
        restore_manager._restore_from_backup(self.backup_metadata)
        is_valid = restore_manager.verify_restore(self.backup_metadata)

        assert is_valid is True

    def test_get_restore_summary(self):
        """Test getting restore summary."""
        restore_manager = RestoreManager(
            target_path=os.path.join(self.restore_dir, "test.durus"),
            backup_dir=self.backup_dir
        )

        summary = restore_manager.get_restore_summary()

        assert "total_backups" in summary
        assert "storage_type" in summary
        assert "encryption_enabled" in summary
        assert summary["total_backups"] == 1


class TestBackupCatalog:
    """Test backup catalog functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.catalog = BackupCatalog(self.backup_dir)

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_add_and_get_backup(self):
        """Test adding and retrieving backups."""
        from druva.backup.manager import BackupMetadata, BackupType

        # Create test metadata
        metadata = BackupMetadata(
            backup_id="test_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            source_path="/path/to/backup.durus",
            size_bytes=1024,
            checksum="abc123"
        )

        # Add to catalog
        self.catalog.add_backup(metadata)

        # Retrieve from catalog
        retrieved = self.catalog.get_backup("test_backup")
        assert retrieved is not None
        assert retrieved.backup_id == "test_backup"
        assert retrieved.backup_type == BackupType.FULL

    def test_get_last_backup(self):
        """Test getting last backup."""
        from druva.backup.manager import BackupMetadata, BackupType

        # Add multiple backups
        now = datetime.now()
        backup1 = BackupMetadata(
            backup_id="backup1",
            backup_type=BackupType.FULL,
            timestamp=now,
            source_path="/path/1",
            size_bytes=1024,
            checksum="abc123"
        )

        backup2 = BackupMetadata(
            backup_id="backup2",
            backup_type=BackupType.INCREMENTAL,
            timestamp=now + timedelta(minutes=1),
            source_path="/path/2",
            size_bytes=512,
            checksum="def456",
            parent_backup_id="backup1"
        )

        self.catalog.add_backup(backup1)
        self.catalog.add_backup(backup2)

        # Get last backup
        last_backup = self.catalog.get_last_backup()
        assert last_backup.backup_id == "backup2"

    def test_get_incremental_chain(self):
        """Test getting incremental backup chain."""
        from druva.backup.manager import BackupMetadata, BackupType

        # Create a chain
        now = datetime.now()
        full_backup = BackupMetadata(
            backup_id="full",
            backup_type=BackupType.FULL,
            timestamp=now,
            source_path="/path/full",
            size_bytes=1024,
            checksum="abc123"
        )

        inc1 = BackupMetadata(
            backup_id="inc1",
            backup_type=BackupType.INCREMENTAL,
            timestamp=now + timedelta(minutes=1),
            source_path="/path/inc1",
            size_bytes=512,
            checksum="def456",
            parent_backup_id="full"
        )

        inc2 = BackupMetadata(
            backup_id="inc2",
            backup_type=BackupType.INCREMENTAL,
            timestamp=now + timedelta(minutes=2),
            source_path="/path/inc2",
            size_bytes=256,
            checksum="ghi789",
            parent_backup_id="inc1"
        )

        self.catalog.add_backup(full_backup)
        self.catalog.add_backup(inc1)
        self.catalog.add_backup(inc2)

        # Get chain
        chain = self.catalog.get_incremental_chain("full")
        assert len(chain) == 2
        assert chain[0].backup_id == "inc1"
        assert chain[1].backup_id == "inc2"

    def test_search_backups(self):
        """Test searching backups."""
        from druva.backup.manager import BackupMetadata, BackupType

        # Add test backups
        now = datetime.now()
        backup1 = BackupMetadata(
            backup_id="full_backup_20240101",
            backup_type=BackupType.FULL,
            timestamp=now,
            source_path="/path/1",
            size_bytes=1024,
            checksum="abc123"
        )

        backup2 = BackupMetadata(
            backup_id="incremental_backup_20240101",
            backup_type=BackupType.INCREMENTAL,
            timestamp=now + timedelta(hours=1),
            source_path="/path/2",
            size_bytes=512,
            checksum="def456"
        )

        self.catalog.add_backup(backup1)
        self.catalog.add_backup(backup2)

        # Search by type
        full_backups = self.catalog.search_backups(backup_type=BackupType.FULL)
        assert len(full_backups) == 1
        assert full_backups[0].backup_type == BackupType.FULL

        # Search by string
        incremental_backups = self.catalog.search_backups(contains_string="incremental")
        assert len(incremental_backups) == 1
        assert "incremental" in incremental_backups[0].backup_id


class TestBackupScheduler:
    """Test backup scheduler functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        self.restore_dir = os.path.join(self.temp_dir, "restores")
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.restore_dir, exist_ok=True)

        # Create test database
        self.test_db = os.path.join(self.temp_dir, "test_db.durus")
        storage = FileStorage(self.test_db)
        root = PersistentDict()
        root["test_key"] = "test_value"
        storage.store(root)
        storage.close()

        # Create backup manager
        self.storage = FileStorage(self.test_db)
        self.backup_manager = BackupManager(
            storage=self.storage,
            backup_dir=self.backup_dir
        )

        # Create scheduler
        self.scheduler = BackupScheduler(
            backup_dir=self.backup_dir,
            backup_manager=self.backup_manager,
            auto_verify=False
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        self.scheduler.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_add_job(self):
        """Test adding backup job."""
        job = self.scheduler.add_job(
            name="test_job",
            backup_type=BackupType.FULL,
            schedule_spec="daily",
            retention_days=30
        )

        assert job.name == "test_job"
        assert job.backup_type == BackupType.FULL
        assert job.schedule_spec == "daily"

    def test_enable_disable_job(self):
        """Test enabling and disabling jobs."""
        # Add job
        job = self.scheduler.add_job(
            name="test_job",
            backup_type=BackupType.FULL,
            schedule_spec="daily"
        )

        # Disable job
        assert self.scheduler.disable_job("test_job") is True
        assert job.enabled is False

        # Enable job
        assert self.scheduler.enable_job("test_job") is True
        assert job.enabled is True

    def test_run_job_immediately(self):
        """Test running job immediately."""
        # Add job
        self.scheduler.add_job(
            name="immediate_job",
            backup_type=BackupType.FULL,
            schedule_spec="daily"
        )

        # Run immediately
        result = self.scheduler.run_job("immediate_job")

        assert result is not None
        assert result["status"] in ["success", "failed"]

    def test_get_all_jobs_status(self):
        """Test getting all job statuses."""
        # Add multiple jobs
        self.scheduler.add_job(
            name="job1",
            backup_type=BackupType.FULL,
            schedule_spec="daily"
        )

        self.scheduler.add_job(
            name="job2",
            backup_type=BackupType.INCREMENTAL,
            schedule_spec="hourly"
        )

        # Get all statuses
        statuses = self.scheduler.get_all_jobs_status()

        assert len(statuses) == 2
        assert "job1" in statuses
        assert "job2" in statuses
        assert "backup_type" in statuses["job1"]
        assert "backup_type" in statuses["job2"]


class TestBackupVerification:
    """Test backup verification functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        self.test_restore_dir = os.path.join(self.temp_dir, "test_restores")
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.test_restore_dir, exist_ok=True)

        # Create test database
        self.test_db = os.path.join(self.temp_dir, "test_db.durus")
        storage = FileStorage(self.test_db)
        root = PersistentDict()
        root["test_key"] = "test_value"
        storage.store(root)
        storage.close()

        # Create backup
        self.storage = FileStorage(self.test_db)
        self.backup_manager = BackupManager(
            storage=self.storage,
            backup_dir=self.backup_dir
        )
        self.backup_metadata = self.backup_manager.perform_full_backup()

        # Add to catalog
        self.catalog = BackupCatalog(self.backup_dir)
        self.catalog.add_backup(self.backup_metadata)

        # Create verification
        self.verification = BackupVerification(
            backup_dir=self.backup_dir,
            test_restore_dir=self.test_restore_dir
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_check_backup_integrity(self):
        """Test backup integrity check."""
        result = self.verification.check_backup_integrity(self.backup_metadata)

        assert result.status == "passed"
        assert result.check_name == "integrity_check"
        assert "duration_seconds" in result.details

    def test_check_compression_ratio(self):
        """Test compression ratio check."""
        result = self.verification.check_compression_ratio(self.backup_metadata)

        assert result.status in ["passed", "warning"]
        assert result.check_name == "compression_check"
        assert "compression_ratio" in result.details

    def test_perform_test_restore(self):
        """Test performing a test restore."""
        result = self.verification.perform_test_restore(self.backup_metadata)

        assert result.status == "passed"
        assert result.check_name == "test_restore"
        assert "duration_seconds" in result.details

    def test_check_retention_policy(self):
        """Test retention policy check."""
        result = self.verification.check_retention_policy(self.backup_metadata)

        assert result.status in ["passed", "warning"]
        assert result.check_name == "retention_check"
        assert "retention_date" in result.details

    def test_run_all_checks(self):
        """Test running all checks."""
        results = self.verification.run_all_checks(self.backup_metadata)

        assert "integrity" in results
        assert "compression" in results
        assert "test_restore" in results
        assert "retention" in results

        # All checks should have passed
        for result in results.values():
            assert result.status in ["passed", "warning"]

    def test_generate_verification_report(self):
        """Test generating verification report."""
        report = self.verification.generate_verification_report(self.backup_metadata)

        assert "backup_id" in report
        assert "overall_status" in report
        assert "checks" in report
        assert "timestamp" in report

        # Check structure
        assert "integrity" in report["checks"]
        assert "test_restore" in report["checks"]


class TestStorageAdapters:
    """Test cloud storage adapters."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "test.txt")
        self.test_dir = os.path.join(self.temp_dir, "upload_test")
        os.makedirs(self.test_dir, exist_ok=True)

        # Create test files
        with open(self.test_file, "w") as f:
            f.write("test content")

        for i in range(3):
            with open(os.path.join(self.test_dir, f"file{i}.txt"), "w") as f:
                f.write(f"content {i}")

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch('boto3.client')
    def test_s3_adapter(self, mock_boto3):
        """Test S3 storage adapter."""
        # Mock S3 client
        mock_client = Mock()
        mock_boto3.return_value = mock_client

        from druva.backup.storage import S3Storage

        # Create adapter
        adapter = S3Storage(
            bucket_name="test-bucket",
            access_key="test-key",
            secret_key="test-secret"
        )

        # Test upload
        result = adapter.upload_file(self.test_file, "test/backup.txt")
        assert result is True
        mock_client.upload_file.assert_called_once()

        # Test download
        result = adapter.download_file("test/backup.txt", self.test_file)
        assert result is True
        mock_client.download_file.assert_called_once()

    @patch('google.cloud.storage.Client')
    def test_gcs_adapter(self, mock_client):
        """Test GCS storage adapter."""
        # Mock GCS client
        mock_blob = Mock()
        mock_blob.upload_from_filename.return_value = None
        mock_blob.download_to_filename.return_value = None
        mock_blob.name = "test/backup.txt"
        mock_blob.size = 1024
        mock_blob.time_created = "2024-01-01T00:00:00Z"
        mock_container = Mock()
        mock_container.blob.return_value = mock_blob
        mock_client.return_value.bucket.return_value = mock_container

        from druva.backup.storage import GCSStorage

        # Create adapter
        adapter = GCSStorage(bucket_name="test-bucket")

        # Test upload
        result = adapter.upload_file(self.test_file, "test/backup.txt")
        assert result is True

        # Test download
        result = adapter.download_file("test/backup.txt", self.test_file)
        assert result is True

    @patch('azure.storage.blob.BlobServiceClient')
    def test_azure_adapter(self, mock_client):
        """Test Azure Blob Storage adapter."""
        # Mock Azure client
        mock_blob_client = Mock()
        mock_blob_client.upload_blob.return_value = None
        mock_blob_client.download_blob.return_value.readall.return_value = b"test content"
        mock_container = Mock()
        mock_container.get_blob_client.return_value = mock_blob_client
        mock_client.return_value.get_container_client.return_value = mock_container

        from druva.backup.storage import AzureBlobStorage

        # Create adapter
        adapter = AzureBlobStorage(
            connection_string="DefaultEndpointsProtocol=https;AccountName=test;AccountKey=test=="
        )

        # Test upload
        result = adapter.upload_file(self.test_file, "test/backup.txt")
        assert result is True

        # Test download
        result = adapter.download_file("test/backup.txt", self.test_file)
        assert result is True


class TestIntegrationScenarios:
    """Integration test scenarios for backup and restore."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.temp_dir, "test_db.durus")
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        self.restore_dir = os.path.join(self.temp_dir, "restores")
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.restore_dir, exist_ok=True)

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_backup_restore_cycle(self):
        """Test complete backup and restore cycle."""
        # Create initial database
        storage = FileStorage(self.test_db)
        root = PersistentDict()
        root["data"] = {"key1": "value1", "key2": "value2"}
        root["metadata"] = {"created": datetime.now().isoformat()}
        storage.store(root)
        storage.close()

        # Create backup manager
        storage = FileStorage(self.test_db)
        backup_manager = BackupManager(
            storage=storage,
            backup_dir=self.backup_dir
        )

        # Perform full backup
        backup_metadata = backup_manager.perform_full_backup()
        catalog = BackupCatalog(self.backup_dir)
        catalog.add_backup(backup_metadata)

        # Modify database
        storage = FileStorage(self.test_db)
        root = storage.open()
        root["data"]["key3"] = "value3"
        root.close()

        # Perform incremental backup
        incremental_backup = backup_manager.perform_incremental_backup(backup_metadata.backup_id)
        catalog.add_backup(incremental_backup)

        # Restore to point in time
        restore_manager = RestoreManager(
            target_path=os.path.join(self.restore_dir, "restored_db.durus"),
            backup_dir=self.backup_dir
        )

        # Restore from full backup
        restored_path = restore_manager.restore_point_in_time(backup_metadata.timestamp)

        # Verify restored data
        restored_storage = FileStorage(restored_path)
        restored_root = restored_storage.open()
        assert "data" in restored_root
        assert "key1" in restored_root["data"]
        assert "key2" in restored_root["data"]
        assert "key3" not in restored_root["data"]
        restored_storage.close()

        # Verify with verification system
        verification = BackupVerification(
            backup_dir=self.backup_dir,
            test_restore_dir=self.test_restore_dir
        )
        results = verification.run_all_checks(backup_metadata)

        # All checks should pass
        for result in results.values():
            assert result.status != "failed"

    def test_encrypted_backup_restore(self):
        """Test encrypted backup and restore."""
        from druva.backup.manager import EncryptionEngine

        # Create initial database
        storage = FileStorage(self.test_db)
        root = PersistentDict()
        root["secret_data"] = "sensitive information"
        storage.store(root)
        storage.close()

        # Create encryption key
        encryption_key = Fernet.generate_key()

        # Create backup manager with encryption
        storage = FileStorage(self.test_db)
        backup_manager = BackupManager(
            storage=storage,
            backup_dir=self.backup_dir,
            encryption_key=encryption_key
        )

        # Perform encrypted backup
        backup_metadata = backup_manager.perform_full_backup()
        assert backup_metadata.encryption_enabled is True

        # Create restore manager with same key
        restore_manager = RestoreManager(
            target_path=os.path.join(self.restore_dir, "restored_db.durus"),
            backup_dir=self.backup_dir,
            encryption_key=encryption_key
        )

        # Restore encrypted backup
        restored_path = restore_manager._restore_from_backup(backup_metadata)

        # Verify decrypted data
        restored_storage = FileStorage(restored_path)
        restored_root = restored_storage.open()
        assert "secret_data" in restored_root
        assert restored_root["secret_data"] == "sensitive information"
        restored_storage.close()

    def test_disaster_recovery_scenario(self):
        """Test disaster recovery scenario."""
        # Create database with significant data
        storage = FileStorage(self.test_db)
        root = PersistentDict()

        # Add substantial data
        for i in range(1000):
            root[f"item_{i}"] = f"value_{i}"

        storage.store(root)
        storage.close()

        # Create backups
        storage = FileStorage(self.test_db)
        backup_manager = BackupManager(
            storage=storage,
            backup_dir=self.backup_dir
        )

        # Full backup
        full_backup = backup_manager.perform_full_backup()
        catalog = BackupCatalog(self.backup_dir)
        catalog.add_backup(full_backup)

        # Modify data
        storage = FileStorage(self.test_db)
        root = storage.open()
        root["new_data"] = "important information"
        root.close()

        # Differential backup
        diff_backup = backup_manager.perform_differential_backup(full_backup.backup_id)
        catalog.add_backup(diff_backup)

        # Simulate disaster - delete original database
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

        # Restore from latest backup
        restore_manager = RestoreManager(
            target_path=os.path.join(self.restore_dir, "recovered_db.durus"),
            backup_dir=self.backup_dir
        )

        # Use most recent backup
        latest_backup = catalog.get_last_backup()
        recovered_path = restore_manager._restore_from_backup(latest_backup)

        # Verify recovery
        assert os.path.exists(recovered_path)
        recovered_storage = FileStorage(recovered_path)
        recovered_root = recovered_storage.open()

        # Check data integrity
        assert "new_data" in recovered_root
        assert recovered_root["new_data"] == "important information"

        # Check some original data
        assert "item_0" in recovered_root
        assert recovered_root["item_0"] == "value_0"

        recovered_storage.close()

        # Run verification
        verification = BackupVerification(
            backup_dir=self.backup_dir,
            test_restore_dir=self.test_restore_dir
        )
        report = verification.generate_verification_report(latest_backup)

        assert report["overall_status"] != "failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

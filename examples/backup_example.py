#!/usr/bin/env python3
"""
Example usage of the Durus backup and restore system.

This script demonstrates:
1. Setting up backup managers
2. Creating different types of backups
3. Automated scheduling
4. Restore operations
5. Verification and testing
"""

import os
import sys
import tempfile
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add durus to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dhruva.file_storage import FileStorage
from dhruva.persistent_dict import PersistentDict
from dhruva.backup.manager import BackupManager, BackupType
from dhruva.backup.restore import RestoreManager
from dhruva.backup.scheduler import BackupScheduler
from dhruva.backup.verification import BackupVerification
from dhruva.backup.storage import StorageFactory
from cryptography.fernet import Fernet

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_sample_database(path: str) -> FileStorage:
    """Create a sample database with some test data."""
    logger.info(f"Creating sample database at {path}")

    # Create storage
    storage = FileStorage(path)
    root = PersistentDict()

    # Add sample data
    root["metadata"] = {
        "created": datetime.now().isoformat(),
        "version": "1.0",
        "type": "sample_database"
    }

    root["users"] = {
        "user1": {"name": "Alice", "email": "alice@example.com", "active": True},
        "user2": {"name": "Bob", "email": "bob@example.com", "active": True},
        "user3": {"name": "Charlie", "email": "charlie@example.com", "active": False}
    }

    root["settings"] = {
        "theme": "dark",
        "language": "en",
        "notifications": True
    }

    # Store root object
    storage.store(root)
    storage.close()

    logger.info("Sample database created successfully")
    return storage

def demonstrate_backup_manager():
    """Demonstrate backup manager functionality."""
    logger.info("=== Demonstrating Backup Manager ===")

    # Setup directories
    temp_dir = tempfile.mkdtemp(prefix="durus_backup_demo_")
    db_path = os.path.join(temp_dir, "sample_db.durus")
    backup_dir = os.path.join(temp_dir, "backups")

    # Create sample database
    storage = create_sample_database(db_path)

    # Create backup manager
    backup_manager = BackupManager(
        storage=storage,
        backup_dir=backup_dir,
        compression_level=3
    )

    # Perform full backup
    logger.info("Creating full backup...")
    full_backup = backup_manager.perform_full_backup()
    logger.info(f"Full backup created: {full_backup.backup_id}")
    logger.info(f"Size: {full_backup.size_bytes} bytes")
    logger.info(f"Compression ratio: {full_backup.compression_ratio:.2%}")

    # Add some new data
    storage = FileStorage(db_path)
    root = storage.open()
    root["new_data"] = "This was added after backup"
    root["users"]["user4"] = {"name": "David", "email": "david@example.com", "active": True}
    root.close()

    # Perform incremental backup
    logger.info("Creating incremental backup...")
    incremental_backup = backup_manager.perform_incremental_backup(full_backup.backup_id)
    logger.info(f"Incremental backup created: {incremental_backup.backup_id}")
    logger.info(f"Parent backup: {incremental_backup.parent_backup_id}")

    # Add more data
    storage = FileStorage(db_path)
    root = storage.open()
    root["more_data"] = "Additional data for differential backup"
    root["users"]["user5"] = {"name": "Eve", "email": "eve@example.com", "active": True}
    root.close()

    # Perform differential backup
    logger.info("Creating differential backup...")
    diff_backup = backup_manager.perform_differential_backup(full_backup.backup_id)
    logger.info(f"Differential backup created: {diff_backup.backup_id}")

    # Cleanup old backups
    logger.info("Cleaning up old backups...")
    cleanup_count = backup_manager.cleanup_old_backups()
    logger.info(f"Cleaned up {cleanup_count} old backups")

    logger.info("Backup demonstration completed successfully")
    return temp_dir, [full_backup, incremental_backup, diff_backup]

def demonstrate_restore_manager(temp_dir, backups):
    """Demonstrate restore manager functionality."""
    logger.info("=== Demonstrating Restore Manager ===")

    restore_dir = os.path.join(temp_dir, "restores")

    # Create restore manager
    restore_manager = RestoreManager(
        target_path=os.path.join(restore_dir, "restored_db.durus"),
        backup_dir=os.path.join(temp_dir, "backups")
    )

    # Get restore summary
    summary = restore_manager.get_restore_summary()
    logger.info(f"Restore summary: {summary}")

    # Find restore points
    restore_points = restore_manager.find_restore_points()
    logger.info(f"Available restore points: {len(restore_points)}")
    for rp in restore_points:
        logger.info(f"  - {rp.backup_id} ({rp.restore_type}) at {rp.timestamp}")

    # Restore from latest backup
    latest_backup = backups[-1]
    logger.info(f"Restoring from latest backup: {latest_backup.backup_id}")

    restored_path = restore_manager.restore_point_in_time(latest_backup.timestamp)
    logger.info(f"Database restored to: {restored_path}")

    # Verify restore
    is_valid = restore_manager.verify_restore(latest_backup)
    logger.info(f"Restore verification: {'PASSED' if is_valid else 'FAILED'}")

    # Show restored data
    restored_storage = FileStorage(restored_path)
    restored_root = restored_storage.open()
    logger.info("Restored data preview:")
    logger.info(f"  Metadata: {restored_root['metadata']['created']}")
    logger.info(f"  User count: {len(restored_root['users'])}")
    logger.info(f"  Settings theme: {restored_root['settings']['theme']}")
    restored_storage.close()

    logger.info("Restore demonstration completed successfully")

def demonstrate_scheduling(temp_dir):
    """Demonstrate backup scheduling."""
    logger.info("=== Demonstrating Backup Scheduler ===")

    backup_dir = os.path.join(temp_dir, "backups")
    db_path = os.path.join(temp_dir, "sample_db.durus")

    # Create backup manager
    storage = FileStorage(db_path)
    backup_manager = BackupManager(
        storage=storage,
        backup_dir=backup_dir
    )

    # Create scheduler
    scheduler = BackupScheduler(
        backup_dir=backup_dir,
        backup_manager=backup_manager,
        auto_verify=False  # Disable for demo
    )

    # Configure default jobs
    scheduler.configure_default_jobs()

    # Add custom job
    custom_job = scheduler.add_job(
        name="demo_backup",
        backup_type=BackupType.FULL,
        schedule_spec="daily",
        retention_days=7,
        callbacks={
            "on_success": lambda metadata, job: logger.info(f"Demo backup successful: {metadata.backup_id}"),
            "on_failure": lambda job, error: logger.error(f"Demo backup failed: {error}")
        }
    )

    logger.info(f"Added custom job: {custom_job.name}")

    # Show job statuses
    statuses = scheduler.get_all_jobs_status()
    logger.info("Current job statuses:")
    for name, status in statuses.items():
        logger.info(f"  {name}: {status['backup_type']} - {'enabled' if status['enabled'] else 'disabled'}")

    # Run job immediately
    logger.info("Running demo job immediately...")
    result = scheduler.run_job("demo_backup")
    logger.info(f"Job result: {result['status']}")

    # Stop scheduler
    scheduler.stop()

    logger.info("Scheduling demonstration completed successfully")

def demonstrate_verification(temp_dir):
    """Demonstrate backup verification."""
    logger.info("=== Demonstrating Backup Verification ===")

    backup_dir = os.path.join(temp_dir, "backups")

    # Create verification instance
    verification = BackupVerification(
        backup_dir=backup_dir,
        test_restore_dir=os.path.join(temp_dir, "test_restores"),
        max_test_size_mb=10  # Small limit for demo
    )

    # Get catalog
    from dhruva.backup.catalog import BackupCatalog
    catalog = BackupCatalog(backup_dir)
    all_backups = catalog.get_all_backups()

    if all_backups:
        # Check backup integrity
        backup = all_backups[0]
        logger.info(f"Checking integrity of backup: {backup.backup_id}")

        integrity_result = verification.check_backup_integrity(backup)
        logger.info(f"Integrity check: {integrity_result.status} - {integrity_result.message}")

        # Check compression ratio
        compression_result = verification.check_compression_ratio(backup)
        logger.info(f"Compression ratio: {compression_result.status} - {compression_result.message}")

        # Check retention policy
        retention_result = verification.check_retention_policy(backup)
        logger.info(f"Retention policy: {retention_result.status} - {retention_result.message}")

        # Run all checks
        all_results = verification.run_all_checks(backup)
        logger.info("All verification results:")
        for check_name, result in all_results.items():
            logger.info(f"  {check_name}: {result.status}")

        # Generate report
        report = verification.generate_verification_report(backup)
        logger.info(f"Overall status: {report['overall_status']}")

    # Clean up test restores
    cleaned_count = verification.cleanup_test_restores()
    logger.info(f"Cleaned up {cleaned_count} test restore directories")

    logger.info("Verification demonstration completed successfully")

def demonstrate_encryption(temp_dir):
    """Demonstrate encrypted backups."""
    logger.info("=== Demonstrating Encryption ===")

    # Generate encryption key
    encryption_key = Fernet.generate_key()
    logger.info(f"Generated encryption key: {encryption_key.decode()}")

    # Create backup manager with encryption
    db_path = os.path.join(temp_dir, "sample_db.durus")
    storage = FileStorage(db_path)
    backup_manager = BackupManager(
        storage=storage,
        backup_dir=os.path.join(temp_dir, "encrypted_backups"),
        encryption_key=encryption_key
    )

    # Perform encrypted backup
    encrypted_backup = backup_manager.perform_full_backup()
    logger.info(f"Encrypted backup created: {encrypted_backup.backup_id}")
    logger.info(f"Encryption enabled: {encrypted_backup.encryption_enabled}")

    # Verify backup file is encrypted
    backup_path = Path(encrypted_backup.source_path)
    if backup_path.suffix == ".enc":
        logger.info("Backup file is encrypted (.enc extension)")

    # Create restore manager with same key
    restore_manager = RestoreManager(
        target_path=os.path.join(temp_dir, "restored_encrypted.durus"),
        backup_dir=os.path.join(temp_dir, "encrypted_backups"),
        encryption_key=encryption_key
    )

    # Restore encrypted backup
    restored_path = restore_manager._restore_from_backup(encrypted_backup)
    logger.info(f"Encrypted backup restored to: {restored_path}")

    # Verify restored data
    restored_storage = FileStorage(restored_path)
    restored_root = restored_storage.open()
    logger.info(f"Restored metadata: {restored_root['metadata']['created']}")
    restored_storage.close()

    logger.info("Encryption demonstration completed successfully")

def demonstrate_cloud_storage():
    """Demonstrate cloud storage integration (mock)."""
    logger.info("=== Demonstrating Cloud Storage Integration ===")

    try:
        # Mock cloud storage for demonstration
        from unittest.mock import Mock

        # Create mock adapter
        mock_adapter = Mock()
        mock_adapter.upload_file.return_value = True
        mock_adapter.download_file.return_value = True
        mock_adapter.upload_json.return_value = True
        mock_adapter.list_files.return_value = [
            {"name": "backup1.durus.zst.enc", "size": 1024000, "last_modified": "2024-01-01T00:00:00Z"}
        ]

        # Create backup manager with cloud adapter
        temp_dir = tempfile.mkdtemp()
        backup_manager = BackupManager(
            storage=None,  # Mock for demo
            backup_dir=temp_dir,
            cloud_adapter=mock_adapter
        )

        # Mock backup metadata
        from dhruva.backup.manager import BackupMetadata, BackupType
        mock_metadata = BackupMetadata(
            backup_id="demo_cloud_backup",
            backup_type=BackupType.FULL,
            timestamp=datetime.now(),
            source_path=os.path.join(temp_dir, "demo_backup.durus"),
            size_bytes=1024000,
            checksum="abc123"
        )

        # Upload to cloud
        upload_result = backup_manager.upload_to_cloud(mock_metadata)
        logger.info(f"Cloud upload result: {upload_result}")

        # List cloud files
        cloud_files = mock_adapter.list_files()
        logger.info(f"Cloud files: {len(cloud_files)}")
        for file in cloud_files:
            logger.info(f"  - {file['name']} ({file['size']} bytes)")

        logger.info("Cloud storage demonstration completed successfully")

    except Exception as e:
        logger.error(f"Cloud storage demo failed: {e}")
        logger.info("This may be due to missing cloud storage libraries")

def main():
    """Main demonstration function."""
    logger.info("Starting Durus Backup System Demonstration")

    try:
        # Demonstrate basic backup functionality
        temp_dir, backups = demonstrate_backup_manager()

        # Demonstrate restore functionality
        demonstrate_restore_manager(temp_dir, backups)

        # Demonstrate scheduling
        demonstrate_scheduling(temp_dir)

        # Demonstrate verification
        demonstrate_verification(temp_dir)

        # Demonstrate encryption
        demonstrate_encryption(temp_dir)

        # Demonstrate cloud storage
        demonstrate_cloud_storage()

        logger.info("=== All Demonstrations Completed Successfully ===")
        logger.info(f"Demo files are in: {temp_dir}")
        logger.info("You can examine the backup files and catalogs manually.")

    except Exception as e:
        logger.error(f"Demonstration failed: {e}")
        raise

if __name__ == "__main__":
    main()

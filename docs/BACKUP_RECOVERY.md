# Dhara Backup and Recovery Guide

This guide provides comprehensive instructions for backing up and restoring Dhara databases, ensuring data durability and disaster recovery capabilities.

## Table of Contents

1. [Overview](#overview)
1. [Quick Start](#quick-start)
1. [Backup Types](#backup-types)
1. [Configuration](#configuration)
1. [Automated Backups](#automated-backups)
1. [Restore Operations](#restore-operations)
1. [Verification and Testing](#verification-and-testing)
1. [Cloud Storage Integration](#cloud-storage-integration)
1. [Security Considerations](#security-considerations)
1. [Troubleshooting](#troubleshooting)

## Overview

The Dhara backup and recovery system provides:

- **Multiple backup types**: Full, incremental, and differential backups
- **Automated scheduling**: Cron-style backup scheduling
- **Compression and encryption**: Efficient storage and secure backups
- **Cloud integration**: Automatic upload to cloud storage (S3, GCS, Azure)
- **Point-in-time recovery**: Restore to any specific timestamp
- **Verification system**: Automated backup integrity testing
- **Disaster recovery**: Comprehensive recovery procedures

## Quick Start

### Basic Backup

```python
from dhara.storage.file import FileStorage
from dhara.backup.manager import BackupManager

# Create storage
storage = FileStorage("my_database.dhara")

# Create backup manager
backup_manager = BackupManager(
    storage=storage,
    backup_dir="./backups",
    compression_level=3
)

# Perform full backup
metadata = backup_manager.perform_full_backup()
print(f"Backup created: {metadata.backup_id}")
```

### Basic Restore

```python
from dhara.backup.restore import RestoreManager

# Create restore manager
restore_manager = RestoreManager(
    target_path="./restored_db.dhara",
    backup_dir="./backups"
)

# Restore from backup
restored_path = restore_manager.restore_point_in_time(metadata.timestamp)
print(f"Database restored to: {restored_path}")
```

## Backup Types

### Full Backups

Complete snapshots of the entire database.

**Pros:**

- Simple to restore
- No dependency on previous backups
- Can be used as standalone recovery points

**Cons:**

- Large storage requirements
- Longer backup times

When to use:

- Initial backup
- Weekly/monthly backups
- Recovery from major failures

### Incremental Backups

Only store changes since the last backup (of any type).

**Pros:**

- Minimal storage space
- Faster backup times
- Good for frequent backups

**Cons:**

- Restore requires base backup + all incrementals
- More complex recovery process

When to use:

- Hourly backups
- Frequent backups for busy systems

### Differential Backups

Store changes since the last full backup.

**Pros:**

- Faster than full backups
- Simpler restore than incremental chains
- Less storage than full backups

**Cons:**

- Larger than incrementals
- Still growing in size

When to use:

- Daily backups
- Balance between full and incremental approaches

## Configuration

### Basic Configuration

```python
from dhara.backup.manager import BackupManager
from dhara.backup.models import BackupType

backup_manager = BackupManager(
    storage=storage,                    # Dhara storage instance
    backup_dir="./backups",            # Backup directory
    compression_level=3,              # ZSTD compression level (1-19)
    encryption_key=None,               # Optional encryption key
    cloud_adapter=None,                # Optional cloud adapter
    retention_policy={                 # Custom retention policy
        "full": 30,                    # Keep full backups for 30 days
        "incremental": 7,              # Keep incrementals for 7 days
        "differential": 14             # Keep differentials for 14 days
    }
)
```

### Encryption Configuration

```python
from cryptography.fernet import Fernet

from dhara.backup.manager import BackupManager

# Generate encryption key
key = Fernet.generate_key()

# Create manager with encryption
backup_manager = BackupManager(
    storage=storage,
    backup_dir="./backups",
    encryption_key=key
)

# Store the key securely (environment variable or vault)
print(f"Encryption key: {key.decode()}")
```

### Cloud Storage Configuration

```python
from dhara.backup.storage import StorageFactory

# S3 Configuration
s3_adapter = StorageFactory.create_storage(
    "s3",
    bucket_name="my-dhara-backups",
    region="us-east-1",
    access_key="your-access-key",
    secret_key="your-secret-key"
)

# GCS Configuration
gcs_adapter = StorageFactory.create_storage(
    "gcs",
    bucket_name="my-dhara-backups",
    project_id="my-project",
    credentials_path="credentials.json"
)

# Azure Configuration
azure_adapter = StorageFactory.create_storage(
    "azure",
    container_name="backups",
    connection_string="DefaultEndpointsProtocol=https;AccountName=..."
)

# Use adapter in backup manager
backup_manager = BackupManager(
    storage=storage,
    backup_dir="./backups",
    cloud_adapter=s3_adapter
)
```

## Automated Backups

### Scheduler Configuration

```python
from dhara.backup.manager import BackupManager
from dhara.backup.models import BackupType
from dhara.backup.scheduler import BackupScheduler

# Create backup manager
backup_manager = BackupManager(storage=storage, backup_dir="./backups")

# Create scheduler
scheduler = BackupScheduler(
    backup_dir="./backups",
    backup_manager=backup_manager,
    auto_verify=True,          # Enable automatic verification
    verify_interval=3600       # Check backups every hour
)

# Configure default backup jobs
scheduler.configure_default_jobs()

# Or add custom jobs
scheduler.add_job(
    name="midnight_full",
    backup_type=BackupType.FULL,
    schedule_spec="00:00",      # Daily at midnight
    retention_days=30,
    callbacks={
        "on_success": lambda metadata, job: print(f"Backup successful: {metadata.backup_id}"),
        "on_failure": lambda job, error: print(f"Backup failed: {error}")
    }
)

scheduler.add_job(
    name="hourly_incremental",
    backup_type=BackupType.INCREMENTAL,
    schedule_spec="hourly",
    retention_days=7
)

# Start scheduler
scheduler.start()
```

### Running in Background

```python
import threading
import time

def run_scheduler():
    scheduler = BackupScheduler(...)
    scheduler.start()

    # Keep scheduler running
    while True:
        time.sleep(60)

# Run in background thread
scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()
```

## Restore Operations

### Point-in-Time Recovery

```python
from dhara.backup.restore import RestoreManager

# Create restore manager
restore_manager = RestoreManager(
    target_path="./restored_db.dhara",
    backup_dir="./backups"
)

# Restore to specific timestamp
target_time = datetime(2024, 1, 1, 12, 0, 0)
restored_path = restore_manager.restore_point_in_time(target_time)

# Verify restore
is_valid = restore_manager.verify_restore(backup_metadata)
print(f"Restore verification: {is_valid}")
```

### Incremental Restore

```python
# Restore from incremental chain
restored_path = restore_manager.restore_incremental_chain(base_backup_id)

# This will restore the base backup and apply all subsequent incremental backups
```

### Emergency Restore

```python
# Quick emergency restore
restored_path = restore_manager.restore_emergency(backup_id)

# This performs a restore without verification for emergency situations
```

### Finding Restore Points

```python
# Find available restore points
restore_points = restore_manager.find_restore_points(
    start_time=datetime(2024, 1, 1),
    end_time=datetime(2024, 1, 2),
    backup_type=BackupType.FULL
)

for point in restore_points:
    print(f"Available restore: {point} - {point.timestamp}")

# Get restore summary
summary = restore_manager.get_restore_summary()
print(f"Total backups: {summary['total_backups']}")
print(f"Cloud storage: {summary['cloud_enabled']}")
```

## Verification and Testing

### Manual Verification

```python
from dhara.backup.scheduler import BackupVerification

# Create verification instance
verification = BackupVerification(
    backup_dir="./backups",
    test_restore_dir="./test_restores",
    timeout_seconds=300,
    max_test_size_mb=100
)

# Check specific backup
result = verification.check_backup_integrity(backup_metadata)
print(f"Integrity check: {result.status} - {result.message}")

# Test restore
result = verification.perform_test_restore(backup_metadata)
print(f"Test restore: {result.status}")

# Check retention policy
result = verification.check_retention_policy(backup_metadata)
print(f"Retention: {result.message}")
```

### Automated Verification

```python
# Run all checks
results = verification.run_all_checks(backup_metadata)

for check_name, result in results.items():
    print(f"{check_name}: {result.status} - {result.message}")

# Generate comprehensive report
report = verification.generate_verification_report(backup_metadata)
print(f"Overall status: {report['overall_status']}")
```

### Regular Testing

```python
# Set up automated testing in your backup scheduler
scheduler.add_job(
    name="weekly_verification",
    backup_type=BackupType.FULL,
    schedule_spec="weekly",
    callbacks={
        "on_success": lambda metadata, job: run_verification_tests(metadata)
    }
)

def run_verification_tests(metadata):
    verification = BackupVerification(...)
    results = verification.run_all_checks(metadata)

    # Send alert if any check fails
    for result in results.values():
        if result.status == "failed":
            send_alert(f"Backup verification failed: {result.message}")
```

## Cloud Storage Integration

### S3 Configuration

```python
import boto3

from dhara.backup.storage import S3Storage

# Using AWS credentials
s3 = S3Storage(
    bucket_name="dhara-backups",
    region="us-west-2",
    access_key=os.getenv("AWS_ACCESS_KEY"),
    secret_key=os.getenv("AWS_SECRET_KEY")
)

# Upload backup
s3.upload_file("/path/to/backup.dhara", "backups/latest/backup.dhara")

# List backups
backups = s3.list_files("backups/")
for backup in backups:
    print(f"Backup: {backup['key']} - {backup['size']} bytes")
```

### Google Cloud Storage

```python
from dhara.backup.storage import GCSStorage

# Using service account
gcs = GCSStorage(
    bucket_name="dhara-backups",
    credentials_path="service-account.json"
)

# Upload backup metadata
gcs.upload_json(metadata.to_dict(), "backups/latest/metadata.json")
```

### Azure Blob Storage

```python
from dhara.backup.storage import AzureBlobStorage

# Using connection string
azure = AzureBlobStorage(
    container_name="dhara-backups",
    connection_string="DefaultEndpointsProtocol=https;..."
)
```

## Security Considerations

### Encryption

1. **Use strong encryption**:

   ```python
   from cryptography.fernet import Fernet
   key = Fernet.generate_key()
   ```

1. **Store keys securely**:

   - Use environment variables
   - Use secret management systems
   - Never commit keys to version control

1. **Rotate encryption keys** periodically\*\*

### Access Control

1. **Restrict file permissions**:

   ```bash
   chmod 600 backups/*.durus
   chmod 700 backups/
   ```

1. **Use file system encryption** (LUKS, BitLocker, FileVault)

1. **Cloud storage security**:

   - Use IAM roles instead of long-term credentials
   - Enable bucket encryption
   - Set proper bucket policies

### Network Security

1. **Use HTTPS** for cloud transfers
1. **Implement VPN** for remote access
1. **Firewall rules** to restrict access to backup servers

### Backup Protection

1. **Regular access audits**
1. **Change management procedures**
1. **Incident response plan**

## Troubleshooting

### Common Issues

#### Backup Failures

**Issue**: Permission denied

```python
# Fix: Ensure proper permissions
os.chmod(backup_dir, 0o700)
```

**Issue**: Storage space full

```python
# Fix: Clean old backups or increase storage
backup_manager.cleanup_old_backups()
```

**Issue**: Compression failed

```python
# Fix: Check zstd installation
pip install zstandard
```

#### Restore Failures

**Issue**: Missing backup file

```python
# Fix: Check cloud connectivity or local path
if not Path(backup_metadata.source_path).exists():
    # Download from cloud
    cloud_adapter.download_file(remote_path, local_path)
```

**Issue**: Checksum mismatch

```python
# Fix: Verify file integrity
result = verification.check_backup_integrity(backup_metadata)
if result.status == "failed":
    logger.error(f"Corrupted backup: {result.message}")
```

#### Performance Issues

**Issue**: Slow backups

```python
# Fix: Adjust compression level
backup_manager = BackupManager(
    storage=storage,
    compression_level=1  # Lower compression = faster
)
```

**Issue**: High CPU usage

```python
# Fix: Limit concurrent operations
import threading
max_threads = 2
```

### Debugging Tips

1. **Enable logging**:

   ```python
   import logging
   logging.basicConfig(level=logging.INFO)
   ```

1. **Check catalog integrity**:

   ```python
   catalog = BackupCatalog("./backups")
   issues = catalog.validate_catalog_integrity()
   for issue in issues:
       logger.warning(f"Catalog issue: {issue}")
   ```

1. **Monitor backup health**:

   ```python
   # Get backup statistics
   stats = catalog.get_backup_statistics()
   logger.info(f"Total size: {stats['total_size_mb']:.2f} MB")
   logger.info(f"Retention compliance: {stats['retention_compliance']:.1f}%")
   ```

### Disaster Recovery Checklist

1. ✅ Verify backups exist and are accessible
1. ✅ Test restore process
1. ✅ Confirm encryption keys are available
1. ✅ Check cloud connectivity
1. ✅ Validate retention policies
1. ✅ Run verification tests
1. ✅ Document recovery procedures
1. ✅ Conduct DR drills

## Best Practices

### Regular Operations

1. **Daily**: Run verification checks
1. **Weekly**: Test restore procedures
1. **Monthly**: Review retention policies
1. **Quarterly**: Conduct DR drills

### Performance Optimization

1. **Schedule during off-peak hours**
1. **Use appropriate compression levels**
1. **Monitor storage usage**
1. **Test performance regularly**

### Security

1. **Regular key rotation**
1. **Access reviews**
1. **Vulnerability scanning**
1. **Backup offsite storage**

### Monitoring

1. **Track success rates**
1. **Monitor storage costs**
1. **Alert on failures**
1. **Log all operations**

## API Reference

### BackupManager

```python
class BackupManager:
    def __init__(self, storage, backup_dir, compression_level=3, ...):
        pass

    def perform_full_backup(self) -> BackupMetadata:
        pass

    def perform_incremental_backup(self, last_backup_id=None) -> BackupMetadata:
        pass

    def perform_differential_backup(self, last_full_backup_id=None) -> BackupMetadata:
        pass

    def upload_to_cloud(self, backup_metadata) -> bool:
        pass

    def cleanup_old_backups(self) -> None:
        pass
```

### RestoreManager

```python
class RestoreManager:
    def __init__(self, target_path, backup_dir, storage_type="file", ...):
        pass

    def restore_point_in_time(self, target_time, use_incremental=False) -> str:
        pass

    def restore_incremental_chain(self, base_backup_id) -> str:
        pass

    def restore_emergency(self, backup_id) -> str:
        pass

    def verify_restore(self, backup_metadata) -> bool:
        pass
```

### BackupScheduler

```python
class BackupScheduler:
    def __init__(self, backup_dir, backup_manager, auto_verify=True, ...):
        pass

    def add_job(self, name, backup_type, schedule_spec, ...):
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def configure_default_jobs(self) -> None:
        pass
```

### BackupVerification

```python
class BackupVerification:
    def __init__(self, backup_dir, test_restore_dir, ...):
        pass

    def check_backup_integrity(self, backup_metadata) -> CheckResult:
        pass

    def perform_test_restore(self, backup_metadata) -> CheckResult:
        pass

    def run_all_checks(self, backup_metadata=None) -> Dict[str, CheckResult]:
        pass

    def generate_verification_report(self, backup_metadata=None) -> Dict[str, Any]:
        pass
```

This comprehensive backup and recovery system ensures data durability and provides robust disaster recovery capabilities for Dhara databases.

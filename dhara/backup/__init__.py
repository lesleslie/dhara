"""
Backup and restore system for Durus database.

This package provides comprehensive backup and restore capabilities for Durus databases,
including:

- Full, incremental, and differential backups
- Automated scheduling
- Compression and encryption
- Cloud storage integration
- Point-in-time recovery
- Backup verification and testing
"""

from .catalog import BackupCatalog
from .manager import BackupManager
from .restore import RestoreManager
from .scheduler import BackupScheduler
from .storage import (
    AzureBlobStorage,
    AzureBlobStorageAdapter,
    GCSStorage,
    GCSStorageAdapter,
    LocalStorageAdapter,
    S3Storage,
    S3StorageAdapter,
    StorageAdapter,
    StorageAdapterFactory,
)
from .verification import BackupVerification

__all__ = [
    "BackupManager",
    "RestoreManager",
    "BackupCatalog",
    "BackupScheduler",
    "StorageAdapter",
    "S3Storage",
    "S3StorageAdapter",
    "GCSStorage",
    "GCSStorageAdapter",
    "AzureBlobStorage",
    "AzureBlobStorageAdapter",
    "LocalStorageAdapter",
    "StorageAdapterFactory",
    "BackupVerification",
]

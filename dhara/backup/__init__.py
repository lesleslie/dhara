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

from importlib import import_module

from .catalog import BackupCatalog
from .manager import BackupManager
from .restore import RestoreManager
from .scheduler import BackupScheduler
from .verification import BackupVerification

_STORAGE_EXPORTS = {
    "StorageAdapter",
    "S3Storage",
    "S3StorageAdapter",
    "GCSStorage",
    "GCSStorageAdapter",
    "AzureBlobStorage",
    "AzureBlobStorageAdapter",
    "LocalStorageAdapter",
    "StorageAdapterFactory",
}

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


def __getattr__(name: str):
    """Lazily expose storage adapter symbols.

    Importing :mod:`dhara.backup` should not eagerly import the Oneiric-backed
    storage layer because it pulls in optional heavy dependencies at module load
    time. The storage names remain available through attribute access and
    ``from dhara.backup import ...``.
    """
    if name in _STORAGE_EXPORTS:
        storage = import_module(".storage", __name__)
        return getattr(storage, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

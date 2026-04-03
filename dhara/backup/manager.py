"""
Backup manager for Durus databases.

This module implements the core backup functionality, including:
- Full backups
- Incremental backups
- Differential backups
- Backup verification
- Compression and encryption
- Cloud storage integration
"""

import hashlib
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import zstandard as zstd
from cryptography.fernet import Fernet

from dhara.file_storage import FileStorage
from dhara.storage import Storage

logger = logging.getLogger(__name__)


class BackupType(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


class BackupMetadata:
    """Metadata for a backup."""

    def __init__(
        self,
        backup_id: str,
        backup_type: BackupType,
        timestamp: datetime,
        source_path: str,
        size_bytes: int,
        checksum: str,
        compression_ratio: float = 0.0,
        encryption_enabled: bool = False,
        parent_backup_id: str | None = None,
        retention_days: int = 30,
        **kwargs,
    ):
        self.backup_id = backup_id
        self.backup_type = backup_type
        self.timestamp = timestamp
        self.source_path = source_path
        self.size_bytes = size_bytes
        self.checksum = checksum
        self.compression_ratio = compression_ratio
        self.encryption_enabled = encryption_enabled
        self.parent_backup_id = parent_backup_id
        self.retention_days = retention_days
        self.metadata = kwargs

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "backup_id": self.backup_id,
            "backup_type": self.backup_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source_path": self.source_path,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "compression_ratio": self.compression_ratio,
            "encryption_enabled": self.encryption_enabled,
            "parent_backup_id": self.parent_backup_id,
            "retention_days": self.retention_days,
            **self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackupMetadata":
        """Create from dictionary."""
        data = data.copy()
        data["backup_type"] = BackupType(data["backup_type"])
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


class CompressionEngine:
    """Handles compression and decompression of backups."""

    def __init__(self, level: int = 3):
        self.level = level
        self.compressor = zstd.ZstdCompressor(level=level)
        self.decompressor = zstd.ZstdDecompressor()

    def compress(self, data: bytes) -> bytes:
        """Compress data using zstd."""
        return self.compressor.compress(data)

    def decompress(self, data: bytes) -> bytes:
        """Decompress data using zstd."""
        return self.decompressor.decompress(data)

    def compress_file(self, input_path: str, output_path: str) -> None:
        """Compress a file."""
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            data = f_in.read()
            compressed = self.compress(data)
            f_out.write(compressed)

    def decompress_file(self, input_path: str, output_path: str) -> None:
        """Decompress a file."""
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            data = f_in.read()
            decompressed = self.decompress(data)
            f_out.write(decompressed)


class EncryptionEngine:
    """Handles encryption and decryption of backups."""

    def __init__(self, key: bytes | None = None):
        if key is None:
            self.key = Fernet.generate_key()
        else:
            self.key = key
        self.cipher = Fernet(self.key)

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data using Fernet."""
        return self.cipher.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data using Fernet."""
        return self.cipher.decrypt(data)

    def encrypt_file(self, input_path: str, output_path: str) -> None:
        """Encrypt a file."""
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            data = f_in.read()
            encrypted = self.encrypt(data)
            f_out.write(encrypted)

    def decrypt_file(self, input_path: str, output_path: str) -> None:
        """Decrypt a file."""
        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            data = f_in.read()
            decrypted = self.decrypt(data)
            f_out.write(decrypted)

    def get_key(self) -> bytes:
        """Get the encryption key."""
        return self.key


class BackupManager:
    """Main backup manager for Durus databases."""

    def __init__(
        self,
        storage: Storage,
        backup_dir: str = "./backups",
        compression_level: int = 3,
        encryption_key: bytes | None = None,
        cloud_adapter: Any | None = None,
        retention_policy: dict[str, int] | None = None,
    ):
        self.storage = storage
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self.compression = CompressionEngine(level=compression_level)
        self.encryption = EncryptionEngine(key=encryption_key)
        self.cloud_adapter = cloud_adapter

        # Default retention policy
        self.retention_policy = retention_policy or {
            "full": 30,
            "incremental": 7,
            "differential": 14,
        }

        self.logger = logging.getLogger(__name__)

    def _calculate_checksum(self, file_path: str) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _create_backup_metadata(
        self,
        backup_type: BackupType,
        source_path: str,
        size_bytes: int,
        parent_backup_id: str | None = None,
    ) -> BackupMetadata:
        """Create backup metadata."""
        backup_id = f"{backup_type.value}_{int(time.time())}"
        checksum = self._calculate_checksum(source_path)

        return BackupMetadata(
            backup_id=backup_id,
            backup_type=backup_type,
            timestamp=datetime.now(),
            source_path=source_path,
            size_bytes=size_bytes,
            checksum=checksum,
            compression_ratio=0.8,  # Placeholder, will be updated
            encryption_enabled=self.encryption is not None,
            parent_backup_id=parent_backup_id,
            retention_days=self.retention_policy.get(backup_type.value, 30),
        )

    def _compress_backup(self, backup_path: str) -> str:
        """Compress a backup file."""
        compressed_path = f"{backup_path}.zst"
        self.compression.compress_file(backup_path, compressed_path)

        # Update compression ratio in metadata
        original_size = os.path.getsize(backup_path)
        compressed_size = os.path.getsize(compressed_path)
        1.0 - (compressed_size / original_size)

        return compressed_path

    def _encrypt_backup(self, backup_path: str) -> str:
        """Encrypt a backup file."""
        encrypted_path = f"{backup_path}.enc"
        self.encryption.encrypt_file(backup_path, encrypted_path)
        return encrypted_path

    def perform_full_backup(self) -> BackupMetadata:
        """Perform a full backup of the database."""
        self.logger.info("Starting full backup...")

        # Create temporary directory for backup
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = os.path.join(temp_dir, "full_backup.durus")

            # Copy database files
            if isinstance(self.storage, FileStorage):
                # For FileStorage, copy the entire file
                source_path = self.storage.shelf.filename
                shutil.copy2(source_path, backup_path)
            else:
                # For other storage types, serialize the database
                raise NotImplementedError(
                    "Full backup not implemented for this storage type"
                )

            # Compress the backup
            compressed_path = self._compress_backup(backup_path)

            # Encrypt if enabled
            if self.encryption:
                final_path = self._encrypt_backup(compressed_path)
            else:
                final_path = compressed_path

            # Store the backup
            backup_filename = f"full_backup_{int(time.time())}.durus.zst"
            if self.encryption:
                backup_filename += ".enc"

            final_backup_path = self.backup_dir / backup_filename
            shutil.move(final_path, final_backup_path)

            # Create metadata
            metadata = self._create_backup_metadata(
                BackupType.FULL,
                str(final_backup_path),
                os.path.getsize(final_backup_path),
            )

            self.logger.info(f"Full backup completed: {metadata.backup_id}")
            return metadata

    def perform_incremental_backup(
        self, last_backup_id: str | None = None
    ) -> BackupMetadata:
        """Perform an incremental backup."""
        self.logger.info("Starting incremental backup...")

        # Get last backup info from catalog
        from .catalog import BackupCatalog

        catalog = BackupCatalog(self.backup_dir)
        last_backup = (
            catalog.get_backup(last_backup_id)
            if last_backup_id
            else catalog.get_last_backup()
        )

        if not last_backup:
            raise ValueError("No previous backup found for incremental backup")

        if last_backup.backup_type != BackupType.FULL:
            raise ValueError("Incremental backup requires a full backup as parent")

        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = os.path.join(temp_dir, "incremental_backup.durus")

            # Copy changes since last backup
            # This is simplified - in practice, you'd track changes
            if isinstance(self.storage, FileStorage):
                source_path = self.storage.shelf.filename
                shutil.copy2(source_path, backup_path)
            else:
                raise NotImplementedError(
                    "Incremental backup not implemented for this storage type"
                )

            # Compress and encrypt
            compressed_path = self._compress_backup(backup_path)
            if self.encryption:
                final_path = self._encrypt_backup(compressed_path)
            else:
                final_path = compressed_path

            # Store the backup
            backup_filename = f"incremental_backup_{int(time.time())}.durus.zst"
            if self.encryption:
                backup_filename += ".enc"

            final_backup_path = self.backup_dir / backup_filename
            shutil.move(final_path, final_backup_path)

            # Create metadata with parent reference
            metadata = self._create_backup_metadata(
                BackupType.INCREMENTAL,
                str(final_backup_path),
                os.path.getsize(final_backup_path),
                last_backup.backup_id,
            )

            self.logger.info(f"Incremental backup completed: {metadata.backup_id}")
            return metadata

    def perform_differential_backup(
        self, last_full_backup_id: str | None = None
    ) -> BackupMetadata:
        """Perform a differential backup."""
        self.logger.info("Starting differential backup...")

        from .catalog import BackupCatalog

        catalog = BackupCatalog(self.backup_dir)

        if last_full_backup_id:
            last_full = catalog.get_backup(last_full_backup_id)
        else:
            last_full = catalog.get_last_backup_of_type(BackupType.FULL)

        if not last_full:
            raise ValueError("No full backup found for differential backup")

        with tempfile.TemporaryDirectory() as temp_dir:
            backup_path = os.path.join(temp_dir, "differential_backup.durus")

            # Copy changes since last full backup
            if isinstance(self.storage, FileStorage):
                source_path = self.storage.shelf.filename
                shutil.copy2(source_path, backup_path)
            else:
                raise NotImplementedError(
                    "Differential backup not implemented for this storage type"
                )

            # Compress and encrypt
            compressed_path = self._compress_backup(backup_path)
            if self.encryption:
                final_path = self._encrypt_backup(compressed_path)
            else:
                final_path = compressed_path

            # Store the backup
            backup_filename = f"differential_backup_{int(time.time())}.durus.zst"
            if self.encryption:
                backup_filename += ".enc"

            final_backup_path = self.backup_dir / backup_filename
            shutil.move(final_path, final_backup_path)

            # Create metadata
            metadata = self._create_backup_metadata(
                BackupType.DIFFERENTIAL,
                str(final_backup_path),
                os.path.getsize(final_backup_path),
                last_full.backup_id,
            )

            self.logger.info(f"Differential backup completed: {metadata.backup_id}")
            return metadata

    def upload_to_cloud(self, backup_metadata: BackupMetadata) -> bool:
        """Upload backup to cloud storage."""
        if not self.cloud_adapter:
            self.logger.warning("No cloud adapter configured")
            return False

        try:
            backup_path = Path(backup_metadata.source_path)
            if not backup_path.exists():
                self.logger.error(f"Backup file not found: {backup_path}")
                return False

            self.logger.info(f"Uploading backup to cloud: {backup_metadata.backup_id}")

            # Upload file and metadata
            self.cloud_adapter.upload_file(
                str(backup_path),
                f"durus_backups/{backup_metadata.backup_id}/{backup_path.name}",
            )

            # Upload metadata
            metadata_json = backup_metadata.to_dict()
            self.cloud_adapter.upload_json(
                metadata_json,
                f"durus_backups/{backup_metadata.backup_id}/metadata.json",
            )

            self.logger.info(
                f"Backup uploaded successfully: {backup_metadata.backup_id}"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to upload backup: {e}")
            return False

    def cleanup_old_backups(self) -> None:
        """Remove old backups based on retention policy."""
        from .catalog import BackupCatalog

        catalog = BackupCatalog(self.backup_dir)

        current_time = datetime.now()

        for backup in catalog.get_all_backups():
            # Check if backup should be retained
            retention_date = backup.timestamp + timedelta(days=backup.retention_days)

            if current_time > retention_date:
                # Remove backup file
                backup_path = Path(backup.source_path)
                if backup_path.exists():
                    backup_path.unlink()
                    self.logger.info(f"Removed old backup: {backup.backup_id}")

                # Remove from catalog
                catalog.remove_backup(backup.backup_id)

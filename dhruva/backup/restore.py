"""
Restore manager for Durus databases.

This module implements restore functionality including:
- Point-in-time recovery
- Incremental restore
- Rollback verification
- Emergency restore procedures
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from dhruva.file_storage import FileStorage

from .catalog import BackupCatalog
from .manager import BackupMetadata, BackupType, CompressionEngine, EncryptionEngine

logger = logging.getLogger(__name__)


class RestorePoint:
    """Represents a restore point."""

    def __init__(
        self,
        backup_id: str,
        timestamp: datetime,
        restore_type: str,
        backup_path: str,
        metadata: dict[str, Any],
    ):
        self.backup_id = backup_id
        self.timestamp = timestamp
        self.restore_type = restore_type
        self.backup_path = backup_path
        self.metadata = metadata

    def __str__(self):
        return f"RestorePoint(id={self.backup_id}, type={self.restore_type}, time={self.timestamp})"


class RestoreManager:
    """Main restore manager for Durus databases."""

    def __init__(
        self,
        target_path: str,
        backup_dir: str = "./backups",
        storage_type: str = "file",
        encryption_key: bytes | None = None,
        cloud_adapter: Any | None = None,
    ):
        self.target_path = Path(target_path)
        self.backup_dir = Path(backup_dir)
        self.storage_type = storage_type
        self.encryption = (
            EncryptionEngine(key=encryption_key) if encryption_key else None
        )
        self.cloud_adapter = cloud_adapter

        self.logger = logging.getLogger(__name__)

    def _ensure_target_directory(self) -> None:
        """Ensure target directory exists and is empty."""
        self.target_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing files if they exist
        if self.target_path.exists():
            if self.target_path.is_dir():
                shutil.rmtree(self.target_path)
            else:
                self.target_path.unlink()

        self.target_path.parent.mkdir(parents=True, exist_ok=True)

    def _restore_from_backup(self, backup_metadata: BackupMetadata) -> str:
        """Restore database from a backup file."""
        backup_path = Path(backup_metadata.source_path)

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            # Step 1: Download from cloud if necessary
            if not backup_path.exists() and self.cloud_adapter:
                self.logger.info(
                    f"Downloading backup from cloud: {backup_metadata.backup_id}"
                )
                backup_path = self._download_backup_from_cloud(backup_metadata)

            # Step 2: Decrypt if encrypted
            if backup_metadata.encryption_enabled and self.encryption:
                decrypted_path = os.path.join(temp_dir, "decrypted_backup.durus")
                self.encryption.decrypt_file(str(backup_path), decrypted_path)
                backup_path = Path(decrypted_path)

            # Step 3: Decompress if compressed
            if backup_path.suffix == ".zst":
                decompressed_path = os.path.join(temp_dir, "decompressed_backup.durus")
                compression_engine = CompressionEngine()
                compression_engine.decompress_file(str(backup_path), decompressed_path)
                backup_path = Path(decompressed_path)

            # Step 4: Restore to target location
            self._ensure_target_directory()
            shutil.copy2(str(backup_path), self.target_path)

            self.logger.info(
                f"Database restored from backup: {backup_metadata.backup_id}"
            )
            return str(self.target_path)

    def _download_backup_from_cloud(self, backup_metadata: BackupMetadata) -> Path:
        """Download backup from cloud storage."""
        if not self.cloud_adapter:
            raise ValueError("No cloud adapter configured")

        temp_dir = tempfile.mkdtemp()
        backup_filename = os.path.basename(backup_metadata.source_path)
        local_path = os.path.join(temp_dir, backup_filename)

        try:
            self.cloud_adapter.download_file(
                f"durus_backups/{backup_metadata.backup_id}/{backup_filename}",
                local_path,
            )
            return Path(local_path)
        except Exception as e:
            self.logger.error(f"Failed to download backup from cloud: {e}")
            raise

    def find_restore_points(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        backup_type: BackupType | None = None,
    ) -> list[RestorePoint]:
        """Find available restore points."""
        catalog = BackupCatalog(self.backup_dir)
        backups = catalog.get_all_backups()

        restore_points = []

        for backup in backups:
            # Filter by time range
            if start_time and backup.timestamp < start_time:
                continue
            if end_time and backup.timestamp > end_time:
                continue

            # Filter by backup type
            if backup_type and backup.backup_type != backup_type:
                continue

            restore_point = RestorePoint(
                backup_id=backup.backup_id,
                timestamp=backup.timestamp,
                restore_type=backup.backup_type.value,
                backup_path=backup.source_path,
                metadata=backup.to_dict(),
            )
            restore_points.append(restore_point)

        # Sort by timestamp (newest first)
        restore_points.sort(key=lambda x: x.timestamp, reverse=True)

        return restore_points

    def restore_point_in_time(
        self, target_time: datetime, use_incremental: bool = False
    ) -> str:
        """Restore database to a specific point in time."""
        self.logger.info(f"Starting point-in-time restore to {target_time}")

        # Find best backup for this restore
        restore_points = self.find_restore_points(end_time=target_time)

        if not restore_points:
            raise ValueError(
                f"No backup available for point-in-time restore to {target_time}"
            )

        # Select the most appropriate backup
        if use_incremental:
            # Try to use incremental backup if available
            incremental_points = [
                rp for rp in restore_points if rp.restore_type == "incremental"
            ]
            if incremental_points:
                backup = BackupCatalog(self.backup_dir).get_backup(
                    incremental_points[0].backup_id
                )
            else:
                backup = BackupCatalog(self.backup_dir).get_backup(
                    restore_points[0].backup_id
                )
        else:
            # Use the latest backup available
            backup = BackupCatalog(self.backup_dir).get_backup(
                restore_points[0].backup_id
            )

        self.logger.info(f"Restoring from backup: {backup.backup_id}")
        return self._restore_from_backup(backup)

    def restore_incremental_chain(self, base_backup_id: str) -> str:
        """Restore database from a chain of incremental backups."""
        self.logger.info(
            f"Starting incremental restore from base backup: {base_backup_id}"
        )

        catalog = BackupCatalog(self.backup_dir)

        # Get base backup
        base_backup = catalog.get_backup(base_backup_id)
        if not base_backup:
            raise ValueError(f"Base backup not found: {base_backup_id}")

        # Restore base backup
        self.logger.info(f"Restoring base backup: {base_backup.backup_id}")
        temp_path = Path(tempfile.mkdtemp())
        original_target = self.target_path

        # Temporarily change target to temp directory
        self.target_path = temp_path / "base_restore"
        self._restore_from_backup(base_backup)

        # Apply incremental backups in order
        incremental_backups = catalog.get_incremental_chain(base_backup_id)

        for incremental_backup in incremental_backups:
            self.logger.info(
                f"Applying incremental backup: {incremental_backup.backup_id}"
            )
            incremental_path = temp_path / f"inc_{incremental_backup.backup_id}"
            self.target_path = incremental_path
            self._restore_from_backup(incremental_backup)

            # Merge incremental changes into base restore
            self._merge_incremental_restore(
                base_path=temp_path / "base_restore",
                incremental_path=incremental_path,
                final_path=original_target,
            )

        # Clean up temp directory
        shutil.rmtree(temp_path)

        self.logger.info("Incremental restore completed successfully")
        return str(original_target)

    def _merge_incremental_restore(
        self, base_path: Path, incremental_path: Path, final_path: Path
    ) -> None:
        """Merge incremental restore into final path."""
        # This is a simplified version - in practice, you'd need to handle
        # the specific Durus storage format properly
        shutil.copy2(str(incremental_path), str(final_path))

    def restore_emergency(self, backup_id: str) -> str:
        """Perform emergency restore from backup."""
        self.logger.warning(f"Starting emergency restore from backup: {backup_id}")

        catalog = BackupCatalog(self.backup_dir)
        backup = catalog.get_backup(backup_id)

        if not backup:
            raise ValueError(f"Backup not found: {backup_id}")

        try:
            return self._restore_from_backup(backup)
        except Exception as e:
            self.logger.error(f"Emergency restore failed: {e}")
            raise

    def verify_restore(self, backup_metadata: BackupMetadata) -> bool:
        """Verify that restore was successful."""
        try:
            # Check that target file exists
            if not self.target_path.exists():
                self.logger.error("Restored file does not exist")
                return False

            # Check file size
            if os.path.getsize(self.target_path) != backup_metadata.size_bytes:
                self.logger.error(
                    f"File size mismatch: expected {backup_metadata.size_bytes}, got {os.path.getsize(self.target_path)}"
                )
                return False

            # Check checksum
            checksum = self._calculate_checksum(self.target_path)
            if checksum != backup_metadata.checksum:
                self.logger.error(
                    f"Checksum mismatch: expected {backup_metadata.checksum}, got {checksum}"
                )
                return False

            # Try to open storage
            if self.storage_type == "file":
                try:
                    storage = FileStorage(str(self.target_path))
                    connection = storage.open()
                    connection.get_root()
                    # Basic verification - can access root
                    connection.close()
                    return True
                except Exception as e:
                    self.logger.error(f"Failed to open restored storage: {e}")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Restore verification failed: {e}")
            return False

    def _calculate_checksum(self, file_path: str) -> str:
        """Calculate SHA256 checksum of a file."""
        import hashlib

        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def get_restore_summary(self) -> dict[str, Any]:
        """Get summary of restore capabilities and available backups."""
        catalog = BackupCatalog(self.backup_dir)
        backups = catalog.get_all_backups()

        # Group by type
        by_type = {
            "full": [b for b in backups if b.backup_type == BackupType.FULL],
            "incremental": [
                b for b in backups if b.backup_type == BackupType.INCREMENTAL
            ],
            "differential": [
                b for b in backups if b.backup_type == BackupType.DIFFERENTIAL
            ],
        }

        return {
            "total_backups": len(backups),
            "by_type": {k: len(v) for k, v in by_type.items()},
            "oldest_backup": min((b.timestamp for b in backups), default=None),
            "newest_backup": max((b.timestamp for b in backups), default=None),
            "storage_type": self.storage_type,
            "cloud_enabled": self.cloud_adapter is not None,
            "encryption_enabled": self.encryption is not None,
        }

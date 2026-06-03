from __future__ import annotations

"""
from __future__ import annotations
Restore manager for Dhara databases.

This module implements restore functionality including:
- Point-in-time recovery
- Incremental restore
- Rollback verification
- Emergency restore procedures
- AsyncRestoreManager for async tool dispatch
"""

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from dhara.core.connection import AsyncConnection, Connection
from dhara.storage.file import FileStorage

from .catalog import AsyncBackupCatalog, BackupCatalog
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

    def __str__(self) -> str:
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
            if self.cloud_adapter:
                self.logger.info(
                    f"Downloading backup from cloud: {backup_metadata.backup_id}"
                )
                backup_path = self._download_backup_from_cloud(backup_metadata)
            else:
                raise FileNotFoundError(f"Backup file not found: {backup_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            # Step 1: Decrypt if encrypted
            if backup_metadata.encryption_enabled and self.encryption:
                decrypted_path = os.path.join(temp_dir, "decrypted_backup.dhara.zst")
                self.encryption.decrypt_file(str(backup_path), decrypted_path)
                backup_path = Path(decrypted_path)

            # Step 2: Decompress if compressed
            if backup_path.suffix == ".zst":
                decompressed_path = os.path.join(temp_dir, "decompressed_backup.dhara")
                compression_engine = CompressionEngine()
                compression_engine.decompress_file(str(backup_path), decompressed_path)
                backup_path = Path(decompressed_path)

            # Step 3: Restore to target location
            self._ensure_target_directory()
            shutil.copy2(backup_path, self.target_path)

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
                f"dhara_backups/{backup_metadata.backup_id}/{backup_filename}",
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
        backups = BackupCatalog(self.backup_dir).get_all_backups()

        restore_points: list[RestorePoint] = []

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
        restore_points.sort(key=lambda x: x.timestamp, reverse=True)  # type: ignore[arg-type]

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

        if not backup:
            raise ValueError("Backup not found for id")
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
        shutil.copy2(incremental_path, final_path)

    def restore_emergency(self, backup_id: str) -> str:
        """Perform emergency restore from backup."""
        self.logger.warning(f"Starting emergency restore from backup: {backup_id}")

        backup = BackupCatalog(self.backup_dir).get_backup(backup_id)

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

            # Verify restored storage can be opened and root accessed.
            if self.storage_type == "file":
                try:
                    storage = FileStorage(str(self.target_path))
                    connection = Connection(storage)
                    connection.get_root()
                    storage.close()
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
            for byte_block in iter(lambda: f.read(4096), b""):  # type: ignore[arg-type]
                sha256_hash.update(byte_block)  # type: ignore[arg-type]
        return sha256_hash.hexdigest()

    def get_restore_summary(self) -> dict[str, Any]:
        """Get summary of restore capabilities and available backups."""
        backups = BackupCatalog(self.backup_dir).get_all_backups()

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


class AsyncRestoreManager:
    """Async Dhara-backed restore manager using AsyncConnection.

    Delegates blocking I/O to a thread pool so that async tool dispatch
    remains event-loop-friendly. Uses AsyncBackupCatalog for catalog access.
    """

    def __init__(
        self,
        target_path: str,
        backup_dir: str = "./backups",
        encryption_key: bytes | None = None,
        cloud_adapter: Any | None = None,
    ) -> None:
        self.target_path = Path(target_path)
        self.backup_dir = Path(backup_dir)
        self.encryption = (
            EncryptionEngine(key=encryption_key) if encryption_key else None
        )
        self.cloud_adapter = cloud_adapter
        self._catalog: AsyncBackupCatalog | None = None
        self.logger = logging.getLogger(__name__)

    async def _get_catalog(self) -> AsyncBackupCatalog:
        if self._catalog is None:
            self._catalog = AsyncBackupCatalog(self.backup_dir)
        return self._catalog

    def _ensure_target_directory(self) -> None:
        """Ensure target directory exists and is empty."""
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        if self.target_path.exists():
            if self.target_path.is_dir():
                shutil.rmtree(self.target_path)
            else:
                self.target_path.unlink()
        self.target_path.parent.mkdir(parents=True, exist_ok=True)

    def _restore_from_backup(self, backup_metadata: BackupMetadata) -> str:
        """Restore database from a backup file (blocking, runs in thread pool)."""
        backup_path = Path(backup_metadata.source_path)

        if not backup_path.exists():
            if self.cloud_adapter:
                self.logger.info(
                    f"Downloading backup from cloud: {backup_metadata.backup_id}"
                )
                backup_path = self._download_backup_from_cloud(backup_metadata)
            else:
                raise FileNotFoundError(f"Backup file not found: {backup_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            if backup_metadata.encryption_enabled and self.encryption:
                decrypted_path = os.path.join(temp_dir, "decrypted_backup.dhara.zst")
                self.encryption.decrypt_file(str(backup_path), decrypted_path)
                backup_path = Path(decrypted_path)

            if backup_path.suffix == ".zst":
                decompressed_path = os.path.join(temp_dir, "decompressed_backup.dhara")
                compression_engine = CompressionEngine()
                compression_engine.decompress_file(str(backup_path), decompressed_path)
                backup_path = Path(decompressed_path)

            self._ensure_target_directory()
            shutil.copy2(backup_path, self.target_path)

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
                f"dhara_backups/{backup_metadata.backup_id}/{backup_filename}",
                local_path,
            )
            return Path(local_path)
        except Exception as e:
            self.logger.error(f"Failed to download backup from cloud: {e}")
            raise

    async def find_restore_points_async(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        backup_type: BackupType | None = None,
    ) -> list[RestorePoint]:
        """Find available restore points (async)."""
        catalog = await self._get_catalog()
        backups = await catalog.get_all_backups_async()

        restore_points: list[RestorePoint] = []
        for backup in backups:
            if start_time and backup.timestamp < start_time:
                continue
            if end_time and backup.timestamp > end_time:
                continue
            if backup_type and backup.backup_type != backup_type:
                continue
            restore_points.append(
                RestorePoint(
                    backup_id=backup.backup_id,
                    timestamp=backup.timestamp,
                    restore_type=backup.backup_type.value,
                    backup_path=backup.source_path,
                    metadata=backup.to_dict(),
                )
            )

        restore_points.sort(key=lambda x: x.timestamp, reverse=True)
        return restore_points

    async def restore_point_in_time_async(
        self, target_time: datetime, use_incremental: bool = False
    ) -> str:
        """Restore database to a specific point in time (async)."""
        self.logger.info(f"Starting async point-in-time restore to {target_time}")
        restore_points = await self.find_restore_points_async(end_time=target_time)

        if not restore_points:
            raise ValueError(
                f"No backup available for point-in-time restore to {target_time}"
            )

        if use_incremental:
            incremental_points = [
                rp for rp in restore_points if rp.restore_type == "incremental"
            ]
            if incremental_points:
                catalog = await self._get_catalog()
                backup = await catalog.get_backup_async(incremental_points[0].backup_id)
            else:
                catalog = await self._get_catalog()
                backup = await catalog.get_backup_async(restore_points[0].backup_id)
        else:
            catalog = await self._get_catalog()
            backup = await catalog.get_backup_async(restore_points[0].backup_id)

        if not backup:
            raise ValueError("Backup not found for id")
        self.logger.info(f"Restoring from backup: {backup.backup_id}")

        # Run blocking restore in thread pool
        return await asyncio.to_thread(self._restore_from_backup, backup)

    async def restore_emergency_async(self, backup_id: str) -> str:
        """Perform emergency restore from backup (async)."""
        self.logger.warning(
            f"Starting async emergency restore from backup: {backup_id}"
        )
        catalog = await self._get_catalog()
        backup = await catalog.get_backup_async(backup_id)

        if not backup:
            raise ValueError(f"Backup not found: {backup_id}")

        try:
            return await asyncio.to_thread(self._restore_from_backup, backup)
        except Exception as e:
            self.logger.error(f"Emergency restore failed: {e}")
            raise

    async def verify_restore_async(self, backup_metadata: BackupMetadata) -> bool:
        """Verify that restore was successful (async)."""
        try:
            if not self.target_path.exists():
                self.logger.error("Restored file does not exist")
                return False

            if self.backup_dir.name == "file" or not hasattr(self, "storage_type"):
                # Simple verification: try to open as FileStorage
                try:
                    storage = FileStorage(str(self.target_path))
                    conn = await AsyncConnection.new(storage)
                    await conn.get_root()
                    await conn.close()
                    return True
                except Exception as e:
                    self.logger.error(f"Failed to open restored storage: {e}")
                    return False
            return True
        except Exception as e:
            self.logger.error(f"Restore verification failed: {e}")
            return False

    async def get_restore_summary_async(self) -> dict[str, Any]:
        """Get summary of restore capabilities and available backups (async)."""
        catalog = await self._get_catalog()
        backups = await catalog.get_all_backups_async()

        by_type: dict[str, list[BackupMetadata]] = {
            "full": [],
            "incremental": [],
            "differential": [],
        }
        for b in backups:
            by_type[b.backup_type.value].append(b)

        return {
            "total_backups": len(backups),
            "by_type": {k: len(v) for k, v in by_type.items()},
            "oldest_backup": min((b.timestamp for b in backups), default=None),
            "newest_backup": max((b.timestamp for b in backups), default=None),
            "storage_type": "file",
            "cloud_enabled": self.cloud_adapter is not None,
            "encryption_enabled": self.encryption is not None,
        }

    def close(self) -> None:
        """Close the catalog connection."""
        if self._catalog is not None:
            self._catalog.close()
            self._catalog = None

    def __enter__(self) -> AsyncRestoreManager:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def __aenter__(self) -> AsyncRestoreManager:
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.close()

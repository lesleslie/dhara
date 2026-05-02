"""
Backup catalog for managing backup metadata.

This module provides:
- Backup metadata storage and retrieval
- Backup chain management
- Search and filter capabilities
- Persistence using Durus itself
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dhara.collections.dict import PersistentDict
from dhara.core import Connection
from dhara.storage.file import FileStorage

from .manager import BackupMetadata, BackupType

logger = logging.getLogger(__name__)


class BackupCatalog:
    """Manages backup metadata and provides search capabilities."""

    def __init__(self, backup_dir: str | Path):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.backup_dir / "backup_catalog.durus"
        self.catalog = self._load_catalog()

    def _load_catalog(self) -> dict[str, dict[str, Any]]:
        """Load catalog data into an in-memory dictionary."""
        if not self.catalog_path.exists():
            return {}

        storage = FileStorage(str(self.catalog_path))
        connection = Connection(storage)
        root = connection.get_root()
        backups = root.get("backups", {})
        catalog = {backup_id: dict(metadata) for backup_id, metadata in backups.items()}
        storage.close()
        return catalog

    def _save_catalog(self) -> None:
        """Save catalog to disk."""
        try:
            storage = FileStorage(str(self.catalog_path))
            connection = Connection(storage)
            root = connection.get_root()
            root["backups"] = PersistentDict(self.catalog)
            connection.commit()
            storage.close()
        except Exception as e:
            logger.error(f"Failed to save catalog: {e}")

    def _refresh_catalog(self) -> None:
        """Refresh in-memory state from disk."""
        self.catalog = self._load_catalog()

    def add_backup(self, metadata: BackupMetadata) -> None:
        """Add backup to catalog."""
        self.catalog[metadata.backup_id] = metadata.to_dict()
        self._save_catalog()

    def get_backup(self, backup_id: str) -> BackupMetadata | None:
        """Get backup by ID."""
        self._refresh_catalog()
        if backup_id in self.catalog:
            data = self.catalog[backup_id]
            return BackupMetadata.from_dict(data)
        return None

    def get_all_backups(self) -> list[BackupMetadata]:
        """Get all backups."""
        self._refresh_catalog()
        backups = []
        for data in self.catalog.values():
            backups.append(BackupMetadata.from_dict(data))
        return backups

    def remove_backup(self, backup_id: str) -> bool:
        """Remove backup from catalog."""
        if backup_id in self.catalog:
            del self.catalog[backup_id]
            self._save_catalog()
            return True
        return False

    def get_backups_by_type(self, backup_type: BackupType) -> list[BackupMetadata]:
        """Get backups of specific type."""
        return [b for b in self.get_all_backups() if b.backup_type == backup_type]

    def get_last_backup(self) -> BackupMetadata | None:
        """Get the most recent backup."""
        backups = self.get_all_backups()
        if not backups:
            return None
        return max(backups, key=lambda b: b.timestamp)

    def get_last_backup_of_type(self, backup_type: BackupType) -> BackupMetadata | None:
        """Get the most recent backup of specific type."""
        backups = self.get_backups_by_type(backup_type)
        if not backups:
            return None
        return max(backups, key=lambda b: b.timestamp)

    def get_incremental_chain(self, base_backup_id: str) -> list[BackupMetadata]:
        """Get incremental backups forming a chain from base backup."""
        chain = []
        current_parent = base_backup_id

        while True:
            next_backup = min(
                (
                    backup
                    for backup in self.get_all_backups()
                    if backup.backup_type == BackupType.INCREMENTAL
                    and backup.parent_backup_id == current_parent
                ),
                key=lambda backup: backup.timestamp,
                default=None,
            )
            if next_backup is None:
                break
            chain.append(next_backup)
            current_parent = next_backup.backup_id

        return chain

    def get_differential_backups(self, base_backup_id: str) -> list[BackupMetadata]:
        """Get all differential backups based on a full backup."""
        base_backup = self.get_backup(base_backup_id)
        if not base_backup or base_backup.backup_type != BackupType.FULL:
            return []

        return [
            b
            for b in self.get_all_backups()
            if b.backup_type == BackupType.DIFFERENTIAL
            and b.parent_backup_id == base_backup_id
        ]

    def search_backups(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        backup_type: BackupType | None = None,
        contains_string: str | None = None,
    ) -> list[BackupMetadata]:
        """Search backups with various filters."""
        results = self.get_all_backups()

        # Filter by time range
        if start_time:
            results = [b for b in results if b.timestamp >= start_time]
        if end_time:
            results = [b for b in results if b.timestamp <= end_time]

        # Filter by type
        if backup_type:
            results = [b for b in results if b.backup_type == backup_type]

        # Filter by string in backup ID
        if contains_string:
            results = [
                b for b in results if contains_string.lower() in b.backup_id.lower()
            ]

        return results

    def get_backup_statistics(self) -> dict[str, Any]:
        """Get statistics about backups."""
        backups = self.get_all_backups()

        if not backups:
            return {
                "total_backups": 0,
                "total_size": 0,
                "by_type": {},
                "avg_size": 0,
                "retention_compliance": 0,
            }

        # Calculate statistics
        total_size = sum(b.size_bytes for b in backups)
        by_type = {}
        for b in backups:
            btype = b.backup_type.value
            by_type[btype] = by_type.get(btype, 0) + 1

        # Check retention compliance
        current_time = datetime.now()
        compliant_backups = 0
        for b in backups:
            retention_date = b.timestamp + timedelta(days=b.retention_days)
            if current_time <= retention_date:
                compliant_backups += 1

        retention_compliance = (
            (compliant_backups / len(backups)) * 100 if backups else 0
        )

        return {
            "total_backups": len(backups),
            "total_size": total_size,
            "total_size_mb": total_size / (1024 * 1024),
            "by_type": by_type,
            "avg_size": total_size / len(backups),
            "avg_size_mb": (total_size / len(backups)) / (1024 * 1024),
            "retention_compliance": retention_compliance,
        }

    def cleanup_expired_backups(self) -> int:
        """Remove expired backups from catalog and filesystem."""
        current_time = datetime.now()
        removed_count = 0

        for backup in self.get_all_backups():
            retention_date = backup.timestamp + timedelta(days=backup.retention_days)

            if current_time > retention_date:
                # Remove from filesystem
                backup_path = Path(backup.source_path)
                if backup_path.exists():
                    backup_path.unlink()
                    logger.info(f"Removed expired backup file: {backup.backup_id}")

                # Remove from catalog
                if self.remove_backup(backup.backup_id):
                    removed_count += 1
                    logger.info(
                        f"Removed expired backup from catalog: {backup.backup_id}"
                    )

        return removed_count

    def export_catalog(self, export_path: str) -> None:
        """Export catalog to JSON file."""
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "backups": [b.to_dict() for b in self.get_all_backups()],
            "statistics": self.get_backup_statistics(),
        }

        with open(export_path, "w") as f:
            json.dump(export_data, f, indent=2)

    def import_catalog(self, import_path: str) -> int:
        """Import catalog from JSON file."""
        with open(import_path) as f:
            import_data = json.load(f)

        imported_count = 0
        for backup_data in import_data.get("backups", []):
            backup = BackupMetadata.from_dict(backup_data)
            self.add_backup(backup)
            imported_count += 1

        return imported_count

    def validate_catalog_integrity(self) -> list[str]:
        """Validate catalog integrity and return list of issues."""
        issues = []

        # Check for duplicate backup IDs
        backup_ids = []
        for backup in self.get_all_backups():
            if backup.backup_id in backup_ids:
                issues.append(f"Duplicate backup ID: {backup.backup_id}")
            else:
                backup_ids.append(backup.backup_id)

        # Check for orphaned backups (missing parent backup)
        for backup in self.get_all_backups():
            if backup.backup_type in [BackupType.INCREMENTAL, BackupType.DIFFERENTIAL]:
                if not backup.parent_backup_id:
                    issues.append(f"Orphaned backup: {backup.backup_id} missing parent")
                else:
                    parent = self.get_backup(backup.parent_backup_id)
                    if not parent:
                        issues.append(
                            f"Missing parent backup: {backup.backup_id} depends on {backup.parent_backup_id}"
                        )

        # Check for missing backup files
        for backup in self.get_all_backups():
            backup_path = Path(backup.source_path)
            if not backup_path.exists():
                issues.append(
                    f"Missing backup file: {backup.backup_id} at {backup.source_path}"
                )

        return issues

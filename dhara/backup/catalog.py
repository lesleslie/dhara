from __future__ import annotations

"""
Backup catalog for managing backup metadata.

This module provides:
- Backup metadata storage and retrieval
- Backup chain management
- Search and filter capabilities
- Persistence using Durus itself
- AsyncBackupCatalog for async tool dispatch via asyncio.to_thread
"""

import json
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

from dhara.collections.dict import PersistentDict
from dhara.core.connection import AsyncConnection
from dhara.storage.async_file import AsyncFileStorage

from .manager import BackupMetadata, BackupType

logger = logging.getLogger(__name__)


class BackupCatalog:
    """Manages backup metadata and provides search capabilities."""

    def __init__(self, backup_dir: str | Path):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.backup_dir / "backup_catalog.dhara"
        self.catalog = self._load_catalog()

    def _load_catalog(self) -> dict[str, dict[str, Any]]:
        """Load catalog data into an in-memory dictionary."""
        if not self.catalog_path.exists():
            return {}

        import asyncio

        async def _do_load() -> dict[str, dict[str, Any]]:
            storage = AsyncFileStorage(str(self.catalog_path))
            try:
                await storage.init()
                connection = await AsyncConnection.new(storage)
                root = await connection.get_root()
                backups_obj = root.get("backups", {})
                # On disk the catalog may round-trip as a nested
                # ``__state__`` dict (older pickle-style state)
                # rather than a hydrated ``PersistentDict``.
                # Unwrap that representation here so ``.items()``
                # yields the real (backup_id → metadata) map.
                if (
                    isinstance(backups_obj, dict)
                    and "__state__" in backups_obj
                    and isinstance(backups_obj["__state__"], dict)
                    and "data" in backups_obj["__state__"]
                ):
                    backups_data = backups_obj["__state__"]["data"]
                else:
                    backups_data = (
                        dict(backups_obj.items())
                        if hasattr(backups_obj, "items")
                        else {}
                    )
                result = {
                    backup_id: metadata.copy()
                    for backup_id, metadata in backups_data.items()
                }
                await storage.close()
                return result
            except Exception:  # cleanup boundary; re-raises after closing storage
                with suppress(Exception):
                    await storage.close()
                raise

        try:
            return asyncio.run(_do_load())
        except Exception as e:  # noqa: BLE001  # outer fail-soft: log and return empty catalog
            logger.error(f"Failed to load catalog: {e}")
            return {}

    def _save_catalog(self) -> None:
        """Save catalog to disk.

        Each call opens a fresh AsyncFileStorage + AsyncConnection so the
        lock is fully released between saves. We retry on transient I/O
        errors with a tiny exponential backoff so a second save
        immediately after the first doesn't race the lock.

        When the catalog file already exists, the loaded root's
        ``_p_connection`` may be detached (Dhara's pure-Python fallback
        does not always re-attach it after ``get_root``), so direct
        ``root["backups"] = ...`` mutations could fail to register in
        the connection's ``changed`` map and the commit would silently
        drop the new state. We re-attach the connection and reset the
        root's status to ``SAVED`` (when the slot is available) so the
        next mutation correctly fires ``_p_note_change`` and the commit
        persists the entire ``self.catalog`` payload.
        """
        import asyncio
        import time

        last_err: Exception | None = None

        async def _do_save() -> None:
            storage = AsyncFileStorage(str(self.catalog_path))
            with suppress(Exception):
                # Already-initialized files raise on init; ignore and
                # rely on AsyncConnection to open.
                await storage.init()
            connection = await AsyncConnection.new(storage)
            root = await connection.get_root()
            # Re-attach the connection so the assignment below is
            # tracked for commit. Use ``setattr`` with a default
            # fallback so test doubles that swap ``root`` for a
            # plain ``dict`` (e.g. ``TestBackupCatalogSave``) keep
            # working — the assignment is a no-op there and the
            # downstream ``root[...] = ...`` exercises the same
            # code path that the original implementation did.
            with suppress(AttributeError):
                root._p_connection = connection
            with suppress(AttributeError):
                root._p_set_status_saved()
            root["backups"] = PersistentDict(self.catalog)
            # Manually register the change on the async connection —
            # ``_p_note_change`` schedules ``conn.note_change`` as a
            # background task via ``asyncio.create_task``, which would
            # race ``commit`` in a sync wrapper. Calling the async
            # method directly guarantees ``connection.changed`` has
            # the root before commit walks it.
            with suppress(AttributeError):
                root._p_connection = connection
            connection.note_change(root)
            await connection.commit()
            await storage.close()

        for attempt in range(5):
            try:
                asyncio.run(_do_save())
                return
            except (BlockingIOError, OSError) as e:
                last_err = e
                # Lock not yet released — back off briefly and retry
                time.sleep(0.005 * (2**attempt))
            except Exception as e:  # noqa: BLE001  # save boundary: any non-IO error is logged and swallowed
                logger.error(f"Failed to save catalog: {e}")
                return
        logger.error(f"Failed to save catalog after retries: {last_err}")

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
        return [BackupMetadata.from_dict(data) for data in self.catalog.values()]

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
        by_type: dict[str, int] = {}
        for b in backups:
            btype = b.backup_type.value
            by_type[btype] = by_type.get(btype, 0) + 1

        # Check retention compliance
        current_time = datetime.now(UTC)
        compliant_backups = 0
        for b in backups:
            ts = (
                b.timestamp
                if b.timestamp.tzinfo is not None
                else b.timestamp.replace(tzinfo=UTC)
            )
            retention_date = ts + timedelta(days=b.retention_days)
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
        current_time = datetime.now(UTC)
        removed_count = 0

        for backup in self.get_all_backups():
            ts = (
                backup.timestamp
                if backup.timestamp.tzinfo is not None
                else backup.timestamp.replace(tzinfo=UTC)
            )
            retention_date = ts + timedelta(days=backup.retention_days)

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
            "export_timestamp": datetime.now(UTC).isoformat(),
            "backups": [b.to_dict() for b in self.get_all_backups()],
            "statistics": self.get_backup_statistics(),
        }

        # Use Path for file operations (robust against str subclasses)
        export_path_obj = Path(export_path)
        with export_path_obj.open("w") as f:
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
            if backup.backup_type in (BackupType.INCREMENTAL, BackupType.DIFFERENTIAL):
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


class AsyncBackupCatalog:
    """Async Dhara-backed backup catalog using AsyncConnection.

    Accepts an optional pre-configured AsyncConnection for testing,
    or creates one from the backup_dir on first use.

    Uses plain dicts for backup metadata (not PersistentDict) to avoid
    async persistence complexity — backup catalog is a cache, not
    the primary store.
    """

    def __init__(
        self,
        backup_dir: str | Path,
        connection: AsyncConnection | None = None,
    ) -> None:
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.backup_dir / "backup_catalog.dhara"
        self._provided_connection = connection
        self._connection: AsyncConnection | None = connection

    async def _get_connection(self) -> AsyncConnection:
        if self._connection is None:
            from dhara.storage.async_file import AsyncFileStorage

            storage = AsyncFileStorage(str(self.catalog_path))
            self._connection = await AsyncConnection.new(storage)
        return self._connection

    async def _load_catalog(self) -> dict[str, dict[str, Any]]:
        conn = await self._get_connection()
        root = await conn.get_root()
        backups = root.get("backups", {})
        return backups.copy() if backups else {}

    async def _save_catalog(self, catalog: dict[str, dict[str, Any]]) -> None:
        conn = await self._get_connection()
        root = await conn.get_root()
        root["backups"] = catalog  # plain dict - catalog is a cache, not primary store

    async def add_backup_async(self, metadata: BackupMetadata) -> None:
        """Add backup to catalog (async)."""
        catalog = await self._load_catalog()
        catalog[metadata.backup_id] = metadata.to_dict()
        await self._save_catalog(catalog)

    async def get_backup_async(self, backup_id: str) -> BackupMetadata | None:
        """Get backup by ID (async)."""
        catalog = await self._load_catalog()
        if backup_id in catalog:
            data = catalog[backup_id]
            return BackupMetadata.from_dict(data)
        return None

    async def get_all_backups_async(self) -> list[BackupMetadata]:
        """Get all backups (async)."""
        catalog = await self._load_catalog()
        return [BackupMetadata.from_dict(data) for data in catalog.values()]

    async def remove_backup_async(self, backup_id: str) -> bool:
        """Remove backup from catalog (async)."""
        catalog = await self._load_catalog()
        if backup_id in catalog:
            del catalog[backup_id]
            await self._save_catalog(catalog)
            return True
        return False

    async def get_backups_by_type_async(
        self, backup_type: BackupType
    ) -> list[BackupMetadata]:
        """Get backups of specific type (async)."""
        backups = await self.get_all_backups_async()
        return [b for b in backups if b.backup_type == backup_type]

    async def get_last_backup_async(self) -> BackupMetadata | None:
        """Get the most recent backup (async)."""
        backups = await self.get_all_backups_async()
        if not backups:
            return None
        return max(backups, key=lambda b: b.timestamp)

    async def search_backups_async(
        self,
        start_time: Any = None,
        end_time: Any = None,
        backup_type: BackupType | None = None,
        contains_string: str | None = None,
    ) -> list[BackupMetadata]:
        """Search backups with various filters (async)."""
        results = await self.get_all_backups_async()

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

    def close(self) -> None:
        """Close the connection if we created it (not if provided)."""
        if self._connection is not None and self._provided_connection is None:
            # We created this connection ourselves; close it
            self._connection = None
        # If _provided_connection was set, caller owns it

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        self.close()

"""
Tests for backup catalog (dhara.backup.catalog).

Covers BackupCatalog including:
- Initialisation and catalog loading
- CRUD operations (add, get, remove backups)
- Filtering by type, time range, and string matching
- Incremental chain and differential backup retrieval
- Backup statistics and retention compliance
- Expired backup cleanup (catalog + filesystem)
- Import/export to JSON
- Catalog integrity validation
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dhara.backup.catalog import BackupCatalog
from dhara.backup.manager import BackupMetadata, BackupType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metadata(
    backup_id: str = "b1",
    backup_type: BackupType = BackupType.FULL,
    source_path: str | None = None,
    parent_backup_id: str | None = None,
    timestamp: datetime | None = None,
    retention_days: int = 30,
    size_bytes: int = 1024,
) -> BackupMetadata:
    """Create a BackupMetadata instance for testing."""
    return BackupMetadata(
        backup_id=backup_id,
        backup_type=backup_type,
        timestamp=timestamp or datetime(2026, 1, 15, 12, 0, 0),
        source_path=source_path or "/tmp/does-not-exist.bak",
        size_bytes=size_bytes,
        checksum="abc123",
        compression_ratio=0.8,
        encryption_enabled=False,
        parent_backup_id=parent_backup_id,
        retention_days=retention_days,
    )


def _metadata_dict(backup_id="b1", **overrides):
    """Build a dict that round-trips through to_dict / from_dict."""
    m = _make_metadata(backup_id=backup_id, **overrides)
    return m.to_dict()


# ===========================================================================
# Initialisation and catalog loading
# ===========================================================================


class TestBackupCatalogInit:
    """Test BackupCatalog initialisation."""

    def test_init_creates_backup_dir(self, tmp_path):
        backup_dir = tmp_path / "new_subdir"
        catalog = BackupCatalog(str(backup_dir))
        assert backup_dir.exists()
        assert catalog.backup_dir == backup_dir

    def test_init_catalog_path(self, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        assert catalog.catalog_path == tmp_path / "backup_catalog.durus"

    @patch.object(BackupCatalog, "_load_catalog", return_value={"existing": "data"})
    def test_init_loads_existing_catalog(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        assert catalog.catalog == {"existing": "data"}

    def test_init_empty_catalog_when_no_file(self, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        # catalog_path does not exist, so _load_catalog returns {}
        assert catalog.catalog == {}


class TestBackupCatalogLoad:
    """Test _load_catalog internals."""

    @patch("dhara.backup.catalog.FileStorage")
    @patch("dhara.backup.catalog.Connection")
    def test_load_from_existing_file(self, MockConnection, MockFileStorage, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        # Place a catalog file so the exists() check passes
        catalog.catalog_path.touch()

        mock_root = {"backups": {"b1": {"backup_id": "b1", "backup_type": "full", "timestamp": datetime.now().isoformat()}}}
        mock_conn = MockConnection.return_value
        mock_conn.get_root.return_value = mock_root

        result = catalog._load_catalog()
        assert "b1" in result

    def test_load_returns_empty_when_no_file(self, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        # Ensure no catalog file exists
        assert not catalog.catalog_path.exists()
        result = catalog._load_catalog()
        assert result == {}


class TestBackupCatalogSave:
    """Test _save_catalog."""

    @patch("dhara.backup.catalog.FileStorage")
    @patch("dhara.backup.catalog.Connection")
    @patch("dhara.backup.catalog.PersistentDict")
    def test_save_writes_catalog(self, MockPDict, MockConnection, MockFileStorage, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        catalog.catalog = {"b1": {"backup_id": "b1"}}

        mock_conn = MockConnection.return_value
        root = {}
        mock_conn.get_root.return_value = root

        catalog._save_catalog()
        mock_conn.commit.assert_called_once()
        MockFileStorage.return_value.close.assert_called()

    @patch("dhara.backup.catalog.FileStorage", side_effect=OSError("write err"))
    def test_save_handles_error(self, MockFileStorage, tmp_path, caplog):
        catalog = BackupCatalog(str(tmp_path))
        catalog.catalog = {"b1": {"backup_id": "b1"}}
        with caplog.at_level("ERROR"):
            catalog._save_catalog()
        assert "Failed to save catalog" in caplog.text


# ===========================================================================
# CRUD operations
# ===========================================================================


class TestBackupCatalogAdd:
    """Test add_backup."""

    @patch.object(BackupCatalog, "_save_catalog")
    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_add_stores_in_catalog(self, mock_load, mock_save, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        metadata = _make_metadata("add-1")
        catalog.add_backup(metadata)
        assert "add-1" in catalog.catalog
        assert catalog.catalog["add-1"]["backup_id"] == "add-1"
        mock_save.assert_called_once()

    @patch.object(BackupCatalog, "_save_catalog")
    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_add_preserves_all_fields(self, mock_load, mock_save, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        ts = datetime(2026, 3, 10, 8, 30, 0)
        metadata = _make_metadata("full-1", timestamp=ts, retention_days=14)
        catalog.add_backup(metadata)
        data = catalog.catalog["full-1"]
        assert data["backup_type"] == "full"
        assert data["timestamp"] == ts.isoformat()
        assert data["retention_days"] == 14


class TestBackupCatalogGet:
    """Test get_backup."""

    @patch.object(BackupCatalog, "_load_catalog")
    @patch.object(BackupCatalog, "_save_catalog")
    def test_get_existing_backup(self, mock_save, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        d = _metadata_dict("get-1", timestamp=ts)
        mock_load.return_value = {"get-1": d}

        catalog = BackupCatalog(str(tmp_path))
        result = catalog.get_backup("get-1")
        assert result is not None
        assert result.backup_id == "get-1"

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_get_nonexistent_returns_none(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        assert catalog.get_backup("nope") is None


class TestBackupCatalogGetAll:
    """Test get_all_backups."""

    @patch.object(BackupCatalog, "_load_catalog")
    @patch.object(BackupCatalog, "_save_catalog")
    def test_get_all_returns_all(self, mock_save, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        mock_load.return_value = {
            "b1": _metadata_dict("b1", timestamp=ts),
            "b2": _metadata_dict("b2", timestamp=ts, backup_type=BackupType.INCREMENTAL),
        }
        catalog = BackupCatalog(str(tmp_path))
        backups = catalog.get_all_backups()
        assert len(backups) == 2
        ids = {b.backup_id for b in backups}
        assert ids == {"b1", "b2"}

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_get_all_empty(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        assert catalog.get_all_backups() == []


class TestBackupCatalogRemove:
    """Test remove_backup."""

    @patch.object(BackupCatalog, "_load_catalog")
    @patch.object(BackupCatalog, "_save_catalog")
    def test_remove_existing(self, mock_save, mock_load, tmp_path):
        d = _metadata_dict("rm-1")
        mock_load.return_value = {"rm-1": d}
        catalog = BackupCatalog(str(tmp_path))
        result = catalog.remove_backup("rm-1")
        assert result is True
        assert "rm-1" not in catalog.catalog
        mock_save.assert_called_once()

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_remove_nonexistent(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        result = catalog.remove_backup("ghost")
        assert result is False


# ===========================================================================
# Filtering
# ===========================================================================


class TestBackupCatalogGetByType:
    """Test get_backups_by_type."""

    @patch.object(BackupCatalog, "_load_catalog")
    def test_filter_by_full_type(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        mock_load.return_value = {
            "f1": _metadata_dict("f1", timestamp=ts, backup_type=BackupType.FULL),
            "i1": _metadata_dict("i1", timestamp=ts, backup_type=BackupType.INCREMENTAL),
            "f2": _metadata_dict("f2", timestamp=ts, backup_type=BackupType.FULL),
        }
        catalog = BackupCatalog(str(tmp_path))
        full_backups = catalog.get_backups_by_type(BackupType.FULL)
        assert len(full_backups) == 2
        assert all(b.backup_type is BackupType.FULL for b in full_backups)

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_filter_returns_empty_when_no_matches(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        result = catalog.get_backups_by_type(BackupType.DIFFERENTIAL)
        assert result == []


class TestBackupCatalogGetLast:
    """Test get_last_backup and get_last_backup_of_type."""

    @patch.object(BackupCatalog, "_load_catalog")
    def test_get_last_backup(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 2, 0, 0, 0)
        t3 = datetime(2026, 1, 3, 0, 0, 0)
        mock_load.return_value = {
            "b1": _metadata_dict("b1", timestamp=t1),
            "b2": _metadata_dict("b2", timestamp=t3),
            "b3": _metadata_dict("b3", timestamp=t2),
        }
        catalog = BackupCatalog(str(tmp_path))
        last = catalog.get_last_backup()
        assert last is not None
        assert last.backup_id == "b2"

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_get_last_backup_empty(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        assert catalog.get_last_backup() is None

    @patch.object(BackupCatalog, "_load_catalog")
    def test_get_last_backup_of_type(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 5, 0, 0, 0)
        t3 = datetime(2026, 1, 3, 0, 0, 0)
        mock_load.return_value = {
            "f1": _metadata_dict("f1", timestamp=t1, backup_type=BackupType.FULL),
            "i1": _metadata_dict("i1", timestamp=t2, backup_type=BackupType.INCREMENTAL),
            "f2": _metadata_dict("f2", timestamp=t3, backup_type=BackupType.FULL),
        }
        catalog = BackupCatalog(str(tmp_path))
        last_full = catalog.get_last_backup_of_type(BackupType.FULL)
        assert last_full is not None
        assert last_full.backup_id == "f2"

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_get_last_backup_of_type_empty(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        assert catalog.get_last_backup_of_type(BackupType.FULL) is None


class TestBackupCatalogIncrementalChain:
    """Test get_incremental_chain."""

    @patch.object(BackupCatalog, "_load_catalog")
    def test_chain_with_multiple_incrementals(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 2, 0, 0, 0)
        t3 = datetime(2026, 1, 3, 0, 0, 0)
        mock_load.return_value = {
            "full-1": _metadata_dict("full-1", timestamp=t1, backup_type=BackupType.FULL),
            "inc-1": _metadata_dict(
                "inc-1", timestamp=t2, backup_type=BackupType.INCREMENTAL, parent_backup_id="full-1"
            ),
            "inc-2": _metadata_dict(
                "inc-2", timestamp=t3, backup_type=BackupType.INCREMENTAL, parent_backup_id="inc-1"
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        chain = catalog.get_incremental_chain("full-1")
        assert len(chain) == 2
        assert chain[0].backup_id == "inc-1"
        assert chain[1].backup_id == "inc-2"

    @patch.object(BackupCatalog, "_load_catalog")
    def test_chain_with_no_incrementals(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        mock_load.return_value = {
            "full-1": _metadata_dict("full-1", timestamp=t1, backup_type=BackupType.FULL),
        }
        catalog = BackupCatalog(str(tmp_path))
        chain = catalog.get_incremental_chain("full-1")
        assert chain == []

    @patch.object(BackupCatalog, "_load_catalog")
    def test_chain_single_incremental(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 2, 0, 0, 0)
        mock_load.return_value = {
            "full-1": _metadata_dict("full-1", timestamp=t1, backup_type=BackupType.FULL),
            "inc-1": _metadata_dict(
                "inc-1", timestamp=t2, backup_type=BackupType.INCREMENTAL, parent_backup_id="full-1"
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        chain = catalog.get_incremental_chain("full-1")
        assert len(chain) == 1
        assert chain[0].backup_id == "inc-1"


class TestBackupCatalogDifferentialBackups:
    """Test get_differential_backups."""

    @patch.object(BackupCatalog, "_load_catalog")
    def test_get_differentials_for_full(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 2, 0, 0, 0)
        t3 = datetime(2026, 1, 3, 0, 0, 0)
        mock_load.return_value = {
            "full-1": _metadata_dict("full-1", timestamp=t1, backup_type=BackupType.FULL),
            "diff-1": _metadata_dict(
                "diff-1", timestamp=t2, backup_type=BackupType.DIFFERENTIAL, parent_backup_id="full-1"
            ),
            "diff-2": _metadata_dict(
                "diff-2", timestamp=t3, backup_type=BackupType.DIFFERENTIAL, parent_backup_id="full-1"
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        diffs = catalog.get_differential_backups("full-1")
        assert len(diffs) == 2

    @patch.object(BackupCatalog, "_load_catalog")
    def test_get_differentials_non_full_base(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        mock_load.return_value = {
            "inc-1": _metadata_dict("inc-1", timestamp=t1, backup_type=BackupType.INCREMENTAL),
        }
        catalog = BackupCatalog(str(tmp_path))
        # Base is incremental, not full -> empty
        diffs = catalog.get_differential_backups("inc-1")
        assert diffs == []

    @patch.object(BackupCatalog, "_load_catalog")
    def test_get_differentials_missing_base(self, mock_load, tmp_path):
        mock_load.return_value = {}
        catalog = BackupCatalog(str(tmp_path))
        diffs = catalog.get_differential_backups("nonexistent")
        assert diffs == []

    @patch.object(BackupCatalog, "_load_catalog")
    def test_get_differentials_only_matching_parent(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 2, 0, 0, 0)
        mock_load.return_value = {
            "full-1": _metadata_dict("full-1", timestamp=t1, backup_type=BackupType.FULL),
            "full-2": _metadata_dict("full-2", timestamp=t2, backup_type=BackupType.FULL),
            "diff-a": _metadata_dict(
                "diff-a", timestamp=t2, backup_type=BackupType.DIFFERENTIAL, parent_backup_id="full-1"
            ),
            "diff-b": _metadata_dict(
                "diff-b", timestamp=t2, backup_type=BackupType.DIFFERENTIAL, parent_backup_id="full-2"
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        diffs = catalog.get_differential_backups("full-1")
        assert len(diffs) == 1
        assert diffs[0].backup_id == "diff-a"


class TestBackupCatalogSearch:
    """Test search_backups."""

    @patch.object(BackupCatalog, "_load_catalog")
    def test_search_by_time_range(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 1, 15, 0, 0, 0)
        t3 = datetime(2026, 2, 1, 0, 0, 0)
        mock_load.return_value = {
            "b1": _metadata_dict("b1", timestamp=t1),
            "b2": _metadata_dict("b2", timestamp=t2),
            "b3": _metadata_dict("b3", timestamp=t3),
        }
        catalog = BackupCatalog(str(tmp_path))
        results = catalog.search_backups(
            start_time=datetime(2026, 1, 10, 0, 0, 0),
            end_time=datetime(2026, 1, 20, 0, 0, 0),
        )
        assert len(results) == 1
        assert results[0].backup_id == "b2"

    @patch.object(BackupCatalog, "_load_catalog")
    def test_search_by_start_time_only(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 2, 1, 0, 0, 0)
        mock_load.return_value = {
            "b1": _metadata_dict("b1", timestamp=t1),
            "b2": _metadata_dict("b2", timestamp=t2),
        }
        catalog = BackupCatalog(str(tmp_path))
        results = catalog.search_backups(start_time=datetime(2026, 1, 15, 0, 0, 0))
        assert len(results) == 1
        assert results[0].backup_id == "b2"

    @patch.object(BackupCatalog, "_load_catalog")
    def test_search_by_end_time_only(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 2, 1, 0, 0, 0)
        mock_load.return_value = {
            "b1": _metadata_dict("b1", timestamp=t1),
            "b2": _metadata_dict("b2", timestamp=t2),
        }
        catalog = BackupCatalog(str(tmp_path))
        results = catalog.search_backups(end_time=datetime(2026, 1, 15, 0, 0, 0))
        assert len(results) == 1
        assert results[0].backup_id == "b1"

    @patch.object(BackupCatalog, "_load_catalog")
    def test_search_by_backup_type(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 1, 0, 0, 0)
        mock_load.return_value = {
            "f1": _metadata_dict("f1", timestamp=ts, backup_type=BackupType.FULL),
            "i1": _metadata_dict("i1", timestamp=ts, backup_type=BackupType.INCREMENTAL),
        }
        catalog = BackupCatalog(str(tmp_path))
        results = catalog.search_backups(backup_type=BackupType.FULL)
        assert len(results) == 1
        assert results[0].backup_id == "f1"

    @patch.object(BackupCatalog, "_load_catalog")
    def test_search_by_contains_string(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 1, 0, 0, 0)
        mock_load.return_value = {
            "full-daily-1": _metadata_dict("full-daily-1", timestamp=ts),
            "inc-hourly-1": _metadata_dict("inc-hourly-1", timestamp=ts),
        }
        catalog = BackupCatalog(str(tmp_path))
        results = catalog.search_backups(contains_string="daily")
        assert len(results) == 1
        assert results[0].backup_id == "full-daily-1"

    @patch.object(BackupCatalog, "_load_catalog")
    def test_search_contains_string_case_insensitive(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 1, 0, 0, 0)
        mock_load.return_value = {
            "FULL-1": _metadata_dict("FULL-1", timestamp=ts),
        }
        catalog = BackupCatalog(str(tmp_path))
        results = catalog.search_backups(contains_string="full")
        assert len(results) == 1

    @patch.object(BackupCatalog, "_load_catalog")
    def test_search_no_filters_returns_all(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 1, 0, 0, 0)
        mock_load.return_value = {
            "b1": _metadata_dict("b1", timestamp=ts),
            "b2": _metadata_dict("b2", timestamp=ts),
        }
        catalog = BackupCatalog(str(tmp_path))
        results = catalog.search_backups()
        assert len(results) == 2

    @patch.object(BackupCatalog, "_load_catalog")
    def test_search_combined_filters(self, mock_load, tmp_path):
        t1 = datetime(2026, 1, 1, 0, 0, 0)
        t2 = datetime(2026, 2, 1, 0, 0, 0)
        mock_load.return_value = {
            "full-1": _metadata_dict("full-1", timestamp=t1, backup_type=BackupType.FULL),
            "full-2": _metadata_dict("full-2", timestamp=t2, backup_type=BackupType.FULL),
            "inc-1": _metadata_dict("inc-1", timestamp=t2, backup_type=BackupType.INCREMENTAL),
        }
        catalog = BackupCatalog(str(tmp_path))
        results = catalog.search_backups(
            start_time=datetime(2026, 1, 15, 0, 0, 0),
            backup_type=BackupType.FULL,
        )
        assert len(results) == 1
        assert results[0].backup_id == "full-2"


# ===========================================================================
# Statistics
# ===========================================================================


class TestBackupCatalogStatistics:
    """Test get_backup_statistics."""

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_statistics_empty_catalog(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        stats = catalog.get_backup_statistics()
        assert stats["total_backups"] == 0
        assert stats["total_size"] == 0
        assert stats["by_type"] == {}
        assert stats["avg_size"] == 0
        assert stats["retention_compliance"] == 0

    @patch.object(BackupCatalog, "_load_catalog")
    def test_statistics_with_backups(self, mock_load, tmp_path):
        ts = datetime.now()
        mock_load.return_value = {
            "f1": _metadata_dict("f1", timestamp=ts, backup_type=BackupType.FULL, size_bytes=2000),
            "i1": _metadata_dict("i1", timestamp=ts, backup_type=BackupType.INCREMENTAL, size_bytes=500),
        }
        catalog = BackupCatalog(str(tmp_path))
        stats = catalog.get_backup_statistics()
        assert stats["total_backups"] == 2
        assert stats["total_size"] == 2500
        assert stats["by_type"]["full"] == 1
        assert stats["by_type"]["incremental"] == 1
        assert stats["avg_size"] == 1250.0
        assert "total_size_mb" in stats
        assert "avg_size_mb" in stats

    @patch.object(BackupCatalog, "_load_catalog")
    def test_retention_compliance(self, mock_load, tmp_path):
        now = datetime.now()
        # One compliant (far future timestamp), one expired
        future = now + timedelta(days=100)
        past = now - timedelta(days=60)
        mock_load.return_value = {
            "ok": _metadata_dict("ok", timestamp=future, retention_days=30),
            "expired": _metadata_dict("expired", timestamp=past, retention_days=7),
        }
        catalog = BackupCatalog(str(tmp_path))
        stats = catalog.get_backup_statistics()
        # Both are in catalog, but only one is within retention
        assert stats["retention_compliance"] == 50.0


# ===========================================================================
# Cleanup expired backups
# ===========================================================================


class TestBackupCatalogCleanup:
    """Test cleanup_expired_backups."""

    @patch.object(BackupCatalog, "_load_catalog")
    @patch.object(BackupCatalog, "_save_catalog")
    def test_cleanup_removes_expired(self, mock_save, mock_load, tmp_path):
        now = datetime.now()
        expired_ts = now - timedelta(days=60)
        fresh_ts = now - timedelta(days=1)
        mock_load.return_value = {
            "expired-1": _metadata_dict(
                "expired-1", timestamp=expired_ts, retention_days=7,
                source_path=str(tmp_path / "expired.bak"),
            ),
            "fresh-1": _metadata_dict(
                "fresh-1", timestamp=fresh_ts, retention_days=30,
                source_path=str(tmp_path / "fresh.bak"),
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        count = catalog.cleanup_expired_backups()
        assert count == 1
        assert "expired-1" not in catalog.catalog
        assert "fresh-1" in catalog.catalog

    @patch.object(BackupCatalog, "_load_catalog")
    @patch.object(BackupCatalog, "_save_catalog")
    def test_cleanup_removes_file_from_filesystem(self, mock_save, mock_load, tmp_path):
        now = datetime.now()
        expired_ts = now - timedelta(days=60)
        backup_file = tmp_path / "old.bak"
        backup_file.write_text("data")

        mock_load.return_value = {
            "old-1": _metadata_dict(
                "old-1", timestamp=expired_ts, retention_days=7,
                source_path=str(backup_file),
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        catalog.cleanup_expired_backups()
        assert not backup_file.exists()

    @patch.object(BackupCatalog, "_load_catalog")
    @patch.object(BackupCatalog, "_save_catalog")
    def test_cleanup_handles_missing_file_gracefully(self, mock_save, mock_load, tmp_path):
        now = datetime.now()
        expired_ts = now - timedelta(days=60)
        mock_load.return_value = {
            "old-1": _metadata_dict(
                "old-1", timestamp=expired_ts, retention_days=7,
                source_path=str(tmp_path / "nonexistent.bak"),
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        count = catalog.cleanup_expired_backups()
        # Should still remove from catalog even if file is gone
        assert count == 1

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_cleanup_empty_catalog(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        assert catalog.cleanup_expired_backups() == 0


# ===========================================================================
# Export / Import
# ===========================================================================


class TestBackupCatalogExport:
    """Test export_catalog."""

    @patch.object(BackupCatalog, "_load_catalog")
    def test_export_creates_json(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        mock_load.return_value = {
            "b1": _metadata_dict("b1", timestamp=ts),
        }
        catalog = BackupCatalog(str(tmp_path))
        export_path = tmp_path / "export.json"
        catalog.export_catalog(str(export_path))

        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert "export_timestamp" in data
        assert "backups" in data
        assert "statistics" in data
        assert len(data["backups"]) == 1
        assert data["backups"][0]["backup_id"] == "b1"

    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_export_empty_catalog(self, mock_load, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        export_path = tmp_path / "empty_export.json"
        catalog.export_catalog(str(export_path))
        data = json.loads(export_path.read_text())
        assert data["backups"] == []


class TestBackupCatalogImport:
    """Test import_catalog."""

    @patch.object(BackupCatalog, "_save_catalog")
    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_import_from_json(self, mock_load, mock_save, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        ts = datetime(2026, 1, 15, 12, 0, 0)
        import_data = {
            "backups": [
                _metadata_dict("imp-1", timestamp=ts),
                _metadata_dict("imp-2", timestamp=ts),
            ]
        }
        import_path = tmp_path / "import.json"
        import_path.write_text(json.dumps(import_data))

        count = catalog.import_catalog(str(import_path))
        assert count == 2
        assert "imp-1" in catalog.catalog
        assert "imp-2" in catalog.catalog
        assert mock_save.call_count == 2

    @patch.object(BackupCatalog, "_save_catalog")
    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_import_empty_json(self, mock_load, mock_save, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        import_path = tmp_path / "empty_import.json"
        import_path.write_text(json.dumps({"backups": []}))

        count = catalog.import_catalog(str(import_path))
        assert count == 0

    @patch.object(BackupCatalog, "_save_catalog")
    @patch.object(BackupCatalog, "_load_catalog", return_value={})
    def test_import_json_without_backups_key(self, mock_load, mock_save, tmp_path):
        catalog = BackupCatalog(str(tmp_path))
        import_path = tmp_path / "no_key.json"
        import_path.write_text(json.dumps({}))

        count = catalog.import_catalog(str(import_path))
        assert count == 0


# ===========================================================================
# Catalog integrity validation
# ===========================================================================


class TestBackupCatalogValidate:
    """Test validate_catalog_integrity."""

    @patch.object(BackupCatalog, "_load_catalog")
    def test_valid_catalog_no_issues(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        mock_load.return_value = {
            "f1": _metadata_dict("f1", timestamp=ts, backup_type=BackupType.FULL),
        }
        catalog = BackupCatalog(str(tmp_path))
        # The source_path won't exist, so we expect "Missing backup file" issues
        issues = catalog.validate_catalog_integrity()
        # With a non-existent file path we get a missing file issue
        assert any("Missing backup file" in i for i in issues)

    @patch.object(BackupCatalog, "_load_catalog")
    def test_detects_duplicate_ids(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        d = _metadata_dict("dup-1", timestamp=ts)
        mock_load.return_value = {
            "dup-1a": d,
            "dup-1b": d,  # same backup_id "dup-1"
        }
        catalog = BackupCatalog(str(tmp_path))
        issues = catalog.validate_catalog_integrity()
        assert any("Duplicate backup ID" in i for i in issues)

    @patch.object(BackupCatalog, "_load_catalog")
    def test_detects_orphaned_incremental_no_parent(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        mock_load.return_value = {
            "inc-orphan": _metadata_dict(
                "inc-orphan", timestamp=ts, backup_type=BackupType.INCREMENTAL,
                parent_backup_id=None,
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        issues = catalog.validate_catalog_integrity()
        assert any("Orphaned backup" in i for i in issues)

    @patch.object(BackupCatalog, "_load_catalog")
    def test_detects_missing_parent(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        mock_load.return_value = {
            "inc-1": _metadata_dict(
                "inc-1", timestamp=ts, backup_type=BackupType.INCREMENTAL,
                parent_backup_id="missing-parent",
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        issues = catalog.validate_catalog_integrity()
        assert any("Missing parent backup" in i for i in issues)

    @patch.object(BackupCatalog, "_load_catalog")
    def test_no_issues_for_full_backup(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        source = tmp_path / "backup.bak"
        source.write_bytes(b"data")
        mock_load.return_value = {
            "f1": _metadata_dict(
                "f1", timestamp=ts, backup_type=BackupType.FULL,
                source_path=str(source),
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        issues = catalog.validate_catalog_integrity()
        # Full backup with no parent needed and file exists
        assert issues == []

    @patch.object(BackupCatalog, "_load_catalog")
    def test_incremental_with_valid_parent(self, mock_load, tmp_path):
        ts = datetime(2026, 1, 15, 12, 0, 0)
        source = tmp_path / "full.bak"
        source.write_bytes(b"data")
        inc_source = tmp_path / "inc.bak"
        inc_source.write_bytes(b"data")

        mock_load.return_value = {
            "full-1": _metadata_dict(
                "full-1", timestamp=ts, backup_type=BackupType.FULL,
                source_path=str(source),
            ),
            "inc-1": _metadata_dict(
                "inc-1", timestamp=ts, backup_type=BackupType.INCREMENTAL,
                parent_backup_id="full-1",
                source_path=str(inc_source),
            ),
        }
        catalog = BackupCatalog(str(tmp_path))
        issues = catalog.validate_catalog_integrity()
        assert issues == []

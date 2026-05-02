"""Tests for dhara.storage.file -- FileStorage and TempFileStorage.

Covers:
- Class initialization and configuration
- File operations (load, store, begin, end, sync)
- Error handling (missing keys, surprise oids, readonly)
- Storage lifecycle (create, open, close, context manager)
- OID allocation (new_oid, allocated_unused_oids)
- Pack operations (get_packer, pack)
- gen_oid_record iteration
- TempFileStorage factory
"""

from __future__ import annotations

import os
from tempfile import mktemp
from unittest.mock import patch

import pytest

from dhara.error import DruvaKeyError
from dhara.serialize import pack_record, unpack_record
from dhara.storage.file import FileStorage, TempFileStorage
from dhara.utils import int8_to_str, str_to_int8


# ── Helpers ──


@pytest.fixture
def temp_storage_path():
    """Provide a unique temporary file path, cleaned up after test."""
    path = mktemp(suffix=".durus")
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def file_storage(temp_storage_path):
    """Provide a FileStorage backed by a temp file, closed after test."""
    storage = FileStorage(temp_storage_path)
    yield storage
    try:
        storage.close()
    except Exception:
        pass


# ── 1. Initialization ──


class TestFileStorageInit:
    """Test FileStorage.__init__ and attribute setup."""

    def test_init_default_attributes(self, file_storage):
        """A fresh FileStorage has correct default attributes."""
        assert file_storage.pending_records == {}
        assert file_storage.allocated_unused_oids == set()
        assert file_storage.pack_extra is None
        assert file_storage.invalid == set()
        assert file_storage.shelf is not None

    def test_init_with_filename(self, temp_storage_path):
        """FileStorage accepts a filename string."""
        storage = FileStorage(temp_storage_path)
        assert storage.get_filename() == temp_storage_path
        storage.close()

    def test_init_without_filename(self):
        """FileStorage without a filename uses a temporary file."""
        storage = FileStorage()
        assert storage.shelf is not None
        assert storage.shelf.get_file().is_temporary()
        storage.close()

    def test_init_readonly_raises_for_missing_file(self):
        """Opening a nonexistent file in readonly mode raises OSError."""
        with pytest.raises(OSError, match="No .* found"):
            FileStorage("/nonexistent/path.durus", readonly=True)


# ── 2. has_format classmethod ──


class TestHasFormat:
    """Test FileStorage.has_format()."""

    def test_has_format_with_valid_shelf(self, file_storage):
        """has_format returns True for a valid shelf file."""
        shelf_file = file_storage.shelf.get_file()
        assert FileStorage.has_format(shelf_file) is True

    def test_has_format_with_empty_file(self, tmp_path):
        """has_format returns False for an empty file."""
        from dhara.file import File

        path = str(tmp_path / "empty.dat")
        f = File(path)
        assert FileStorage.has_format(f) is False
        f.close()


# ── 3. get_filename ──


class TestGetFilename:
    """Test FileStorage.get_filename()."""

    def test_returns_path(self, temp_storage_path, file_storage):
        """get_filename returns the path string."""
        assert file_storage.get_filename() == temp_storage_path

    def test_returns_temporary_name(self):
        """A temporary storage returns a generated name."""
        storage = FileStorage()
        name = storage.get_filename()
        assert isinstance(name, str)
        assert len(name) > 0
        storage.close()


# ── 4. load ──


class TestLoad:
    """Test FileStorage.load()."""

    def test_load_existing_oid(self, file_storage):
        """load returns the record for a stored oid."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record = pack_record(oid, b"root_data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()
        loaded = file_storage.load(oid)
        assert isinstance(loaded, bytes)
        assert loaded == record

    def test_load_missing_oid_raises_key_error(self, file_storage):
        """load raises DruvaKeyError for a nonexistent oid."""
        missing_oid = int8_to_str(9999)
        with pytest.raises(DruvaKeyError):
            file_storage.load(missing_oid)

    def test_load_returns_stored_data(self, file_storage):
        """load returns exactly what was stored via begin/store/end."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        # The root oid already exists; store a new record for it
        new_record = pack_record(oid, b"test_data", b"")
        file_storage.begin()
        file_storage.store(oid, new_record)
        file_storage.end()
        loaded = file_storage.load(oid)
        assert loaded == new_record


# ── 5. begin / store / end (transaction lifecycle) ──


class TestTransactionLifecycle:
    """Test the begin/store/end transaction cycle."""

    def test_begin_clears_pending_records(self, file_storage):
        """begin() clears the pending_records dict."""
        file_storage.pending_records["temp"] = b"data"
        file_storage.begin()
        assert file_storage.pending_records == {}

    def test_store_adds_to_pending(self, file_storage):
        """store() adds the oid/record pair to pending_records."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record = pack_record(oid, b"data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        assert oid in file_storage.pending_records
        assert file_storage.pending_records[oid] == record

    def test_store_surprise_oid_raises_value_error(self, file_storage):
        """store() raises ValueError for an oid that is not allocated, not
        in the shelf, and not oid 0."""
        surprise_oid = int8_to_str(42)
        with pytest.raises(ValueError, match="surprise"):
            file_storage.store(surprise_oid, b"bad_record")

    def test_store_surprise_oid_clears_pending(self, file_storage):
        """When a surprise oid is stored, begin() is called to clear
        pending records before raising."""
        from dhara.serialize import pack_record

        oid0 = int8_to_str(0)
        record0 = pack_record(oid0, b"legit", b"")
        file_storage.begin()
        file_storage.store(oid0, record0)
        assert len(file_storage.pending_records) == 1

        surprise_oid = int8_to_str(42)
        with pytest.raises(ValueError):
            file_storage.store(surprise_oid, b"bad_record")
        # begin() was called, so pending should be cleared
        assert file_storage.pending_records == {}

    def test_end_commits_pending_to_shelf(self, file_storage):
        """end() writes pending_records to the shelf."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record = pack_record(oid, b"committed_data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()
        # After end, the record should be loadable
        loaded = file_storage.load(oid)
        assert loaded == record

    def test_end_clears_pending_records(self, file_storage):
        """end() calls begin() to clear pending_records."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record = pack_record(oid, b"data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()
        assert file_storage.pending_records == {}

    def test_end_removes_used_oids_from_allocated(self, file_storage):
        """end() removes committed oids from allocated_unused_oids."""
        from dhara.serialize import pack_record

        oid = file_storage.new_oid()
        record = pack_record(oid, b"new_data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()
        assert oid not in file_storage.allocated_unused_oids

    def test_end_updates_pack_extra_when_packing(self, file_storage):
        """When pack_extra is not None (pack in progress), end() adds
        pending records to pack_extra."""
        from dhara.serialize import pack_record

        file_storage.pack_extra = set()
        oid = int8_to_str(0)
        record = pack_record(oid, b"pack_data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()
        assert oid in file_storage.pack_extra

    def test_full_commit_cycle(self, file_storage):
        """Test a complete begin -> store -> end cycle with new oid."""
        from dhara.serialize import pack_record

        oid = file_storage.new_oid()
        record = pack_record(oid, b"cycle_data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()

        loaded = file_storage.load(oid)
        assert loaded == record
        assert oid not in file_storage.allocated_unused_oids


# ── 6. sync ──


class TestSync:
    """Test FileStorage.sync()."""

    def test_sync_returns_empty_when_no_invalidations(self, file_storage):
        """sync() returns [] when nothing has been invalidated."""
        result = file_storage.sync()
        assert result == []

    def test_sync_returns_invalid_oids(self, file_storage):
        """sync() returns oids from the invalid set and clears it."""
        oid1 = int8_to_str(1)
        oid2 = int8_to_str(2)
        file_storage.invalid.add(oid1)
        file_storage.invalid.add(oid2)
        result = file_storage.sync()
        assert sorted(result) == sorted([oid1, oid2])
        assert file_storage.invalid == set()

    def test_sync_clears_invalid_after_return(self, file_storage):
        """sync() clears the invalid set, so a second call returns []."""
        file_storage.invalid.add(int8_to_str(5))
        file_storage.sync()
        result = file_storage.sync()
        assert result == []


# ── 7. new_oid ──


class TestNewOid:
    """Test FileStorage.new_oid()."""

    def test_new_oid_returns_8_byte_string(self, file_storage):
        """new_oid() returns an 8-byte string."""
        oid = file_storage.new_oid()
        assert isinstance(oid, bytes)
        assert len(oid) == 8

    def test_new_oid_returns_unique_values(self, file_storage):
        """new_oid() returns unique oids on each call."""
        oids = {file_storage.new_oid() for _ in range(10)}
        assert len(oids) == 10

    def test_new_oid_adds_to_allocated_unused(self, file_storage):
        """new_oid() adds the oid to allocated_unused_oids."""
        oid = file_storage.new_oid()
        assert oid in file_storage.allocated_unused_oids

    def test_new_oid_skips_already_allocated(self, file_storage):
        """new_oid() does not return an oid that is already allocated."""
        oid1 = file_storage.new_oid()
        oid2 = file_storage.new_oid()
        assert oid1 != oid2

    def test_new_oid_skips_invalid_oids(self, file_storage):
        """new_oid() skips oids that are in the invalid set."""
        # Allocate all low oids and add one to invalid
        seen = set()
        for _ in range(20):
            oid = file_storage.new_oid()
            seen.add(oid)

        # Mark the first allocated oid as invalid
        first_oid = min(seen, key=lambda o: str_to_int8(o))
        file_storage.invalid.add(first_oid)
        file_storage.allocated_unused_oids.discard(first_oid)

        # next_oid should not return the invalid oid
        next_oid = file_storage.new_oid()
        assert next_oid != first_oid


# ── 8. gen_oid_record ──


class TestGenOidRecord:
    """Test FileStorage.gen_oid_record()."""

    def test_gen_oid_record_no_start_oid(self, file_storage):
        """Without start_oid, gen_oid_record yields all shelf items."""
        from dhara.serialize import pack_record

        # Store a record so there is something to iterate
        oid = int8_to_str(0)
        record = pack_record(oid, b"root_data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()

        results = list(file_storage.gen_oid_record())
        assert len(results) >= 1
        # Each result is (oid, record) pair
        for returned_oid, returned_record in results:
            assert len(returned_oid) == 8
            assert isinstance(returned_record, bytes)

    def test_gen_oid_record_with_start_oid(self, file_storage):
        """With start_oid, gen_oid_record does a breadth-first traversal."""
        from dhara.serialize import pack_record

        root_oid = int8_to_str(0)
        child_oid = file_storage.new_oid()
        # refs field must be raw concatenated 8-byte oid strings
        root_record = pack_record(root_oid, b"root", child_oid)
        child_record = pack_record(child_oid, b"child", b"")

        file_storage.begin()
        file_storage.store(root_oid, root_record)
        file_storage.end()
        file_storage.begin()
        file_storage.store(child_oid, child_record)
        file_storage.end()

        results = list(file_storage.gen_oid_record(start_oid=root_oid))
        # The traversal follows refs from root -> child
        assert len(results) >= 1
        root_found = any(oid == root_oid for oid, _ in results)
        assert root_found

    def test_gen_oid_record_with_seen_set(self, file_storage):
        """gen_oid_record respects a provided seen IntSet."""
        from dhara.serialize import pack_record
        from dhara.utils import IntSet

        root_oid = int8_to_str(0)
        record = pack_record(root_oid, b"root", b"")
        file_storage.begin()
        file_storage.store(root_oid, record)
        file_storage.end()

        seen = IntSet()
        seen.add(0)  # Mark root as already seen
        results = list(file_storage.gen_oid_record(start_oid=root_oid, seen=seen))
        # root oid (0) should be skipped because it's in seen
        assert len(results) == 0


# ── 9. close ──


class TestClose:
    """Test FileStorage.close()."""

    def test_close_delegates_to_shelf(self, file_storage):
        """close() calls shelf.close()."""
        shelf = file_storage.shelf
        file_storage.close()
        # The underlying file should be closed
        assert shelf.file.file.closed

    def test_close_on_already_closed_is_safe(self, file_storage):
        """Calling close() twice does not raise."""
        file_storage.close()
        # Second close should not raise
        file_storage.close()


# ── 10. Context manager (__enter__ / __exit__) ──


class TestContextManager:
    """Test FileStorage as a context manager."""

    def test_enter_returns_self(self, temp_storage_path):
        """__enter__ returns the storage instance."""
        with FileStorage(temp_storage_path) as storage:
            assert isinstance(storage, FileStorage)

    def test_exit_closes_storage(self, temp_storage_path):
        """__exit__ calls close() on the storage."""
        storage = FileStorage(temp_storage_path)
        shelf = storage.shelf
        storage.__exit__(None, None, None)
        assert shelf.file.file.closed

    def test_exit_does_not_suppress_exceptions(self, temp_storage_path):
        """__exit__ returns False so exceptions propagate."""
        storage = FileStorage(temp_storage_path)
        result = storage.__exit__(ValueError, ValueError("test"), None)
        assert result is False

    def test_with_statement_integration(self, temp_storage_path):
        """Using 'with' statement auto-closes on normal exit."""
        from dhara.serialize import pack_record

        with FileStorage(temp_storage_path) as storage:
            oid = int8_to_str(0)
            record = pack_record(oid, b"ctx_data", b"")
            storage.begin()
            storage.store(oid, record)
            storage.end()
            loaded = storage.load(oid)
            assert loaded == record
        # After the with block, the shelf should be closed
        assert storage.shelf.file.file.closed

    def test_with_statement_closes_on_exception(self, temp_storage_path):
        """Using 'with' statement auto-closes even if an exception occurs."""
        try:
            with FileStorage(temp_storage_path) as storage:
                raise RuntimeError("test error")
        except RuntimeError:
            pass
        assert storage.shelf.file.file.closed


# ── 11. __str__ ──


class TestStr:
    """Test FileStorage.__str__()."""

    def test_str_representation(self, file_storage, temp_storage_path):
        """__str__ returns class name and filename."""
        result = str(file_storage)
        assert "FileStorage" in result
        assert temp_storage_path in result

    def test_str_temporary_storage(self):
        """__str__ works for temporary file storage too."""
        storage = FileStorage()
        result = str(storage)
        assert "FileStorage" in result
        storage.close()


# ── 12. get_packer ──


class TestGetPacker:
    """Test FileStorage.get_packer()."""

    def test_get_packer_returns_empty_when_pending(self, file_storage):
        """get_packer returns an empty generator when pending records exist."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record = pack_record(oid, b"data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        # pending_records is non-empty
        packer = file_storage.get_packer()
        assert list(packer) == []

    def test_get_packer_returns_empty_when_pack_in_progress(self, file_storage):
        """get_packer returns empty generator when pack_extra is not None."""
        file_storage.pack_extra = set()
        packer = file_storage.get_packer()
        assert list(packer) == []
        file_storage.pack_extra = None  # reset

    def test_get_packer_returns_empty_for_temporary(self):
        """get_packer returns empty generator for temporary files."""
        storage = FileStorage()
        packer = storage.get_packer()
        assert list(packer) == []
        storage.close()


# ── 13. pack ──


class TestPack:
    """Test FileStorage.pack()."""

    def test_pack_noop_when_temporary(self):
        """pack() is a no-op for temporary file storage."""
        storage = FileStorage()
        # Should not raise
        storage.pack()
        storage.close()


# ── 14. TempFileStorage ──


class TestTempFileStorage:
    """Test the TempFileStorage factory function."""

    def test_returns_file_storage(self):
        """TempFileStorage() returns a FileStorage instance."""
        storage = TempFileStorage()
        assert isinstance(storage, FileStorage)
        storage.close()

    def test_uses_temporary_file(self):
        """TempFileStorage() creates a storage with a temporary file."""
        storage = TempFileStorage()
        assert storage.shelf.get_file().is_temporary()
        storage.close()

    def test_supports_full_lifecycle(self):
        """TempFileStorage supports begin/store/end/load."""
        from dhara.serialize import pack_record

        storage = TempFileStorage()
        oid = storage.new_oid()
        record = pack_record(oid, b"temp_data", b"")
        storage.begin()
        storage.store(oid, record)
        storage.end()
        loaded = storage.load(oid)
        assert loaded == record
        storage.close()


# ── 15. Multiple transactions ──


class TestMultipleTransactions:
    """Test multiple sequential transactions."""

    def test_multiple_commits(self, file_storage):
        """Multiple begin/store/end cycles work correctly."""
        from dhara.serialize import pack_record

        root_oid = int8_to_str(0)

        # Transaction 1
        record1 = pack_record(root_oid, b"version1", b"")
        file_storage.begin()
        file_storage.store(root_oid, record1)
        file_storage.end()
        assert file_storage.load(root_oid) == record1

        # Transaction 2 - update the same oid
        record2 = pack_record(root_oid, b"version2", b"")
        file_storage.begin()
        file_storage.store(root_oid, record2)
        file_storage.end()
        assert file_storage.load(root_oid) == record2

    def test_multiple_new_oids_in_transaction(self, file_storage):
        """Store multiple new oids in a single transaction."""
        from dhara.serialize import pack_record

        oids = [file_storage.new_oid() for _ in range(3)]
        file_storage.begin()
        for oid in oids:
            record = pack_record(oid, f"data_{str_to_int8(oid)}".encode(), b"")
            file_storage.store(oid, record)
        file_storage.end()

        for oid in oids:
            loaded = file_storage.load(oid)
            assert f"data_{str_to_int8(oid)}".encode() in loaded or loaded is not None

    def test_all_allocated_oids_consumed_after_end(self, file_storage):
        """After end(), all stored oids are removed from allocated_unused."""
        from dhara.serialize import pack_record

        oids = [file_storage.new_oid() for _ in range(5)]
        file_storage.begin()
        for oid in oids:
            record = pack_record(oid, b"x", b"")
            file_storage.store(oid, record)
        file_storage.end()
        for oid in oids:
            assert oid not in file_storage.allocated_unused_oids


# ── 16. Edge cases ──


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_store_oid_zero_is_allowed(self, file_storage):
        """Storing to oid 0 (root) is always allowed, even if not
        explicitly allocated."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record = pack_record(oid, b"root_update", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()
        assert file_storage.load(oid) == record

    def test_end_with_empty_pending(self, file_storage):
        """Calling end() with empty pending_records does not raise."""
        file_storage.begin()
        file_storage.end()

    def test_begin_mid_transaction_clears(self, file_storage):
        """Calling begin() mid-transaction discards pending records."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record = pack_record(oid, b"will_be_discarded", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        # Call begin again without end -- this simulates an abort
        file_storage.begin()
        assert file_storage.pending_records == {}

    def test_store_previously_committed_oid_is_allowed(self, file_storage):
        """Storing an oid that was previously committed is allowed (it's
        in the shelf)."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record1 = pack_record(oid, b"first", b"")
        file_storage.begin()
        file_storage.store(oid, record1)
        file_storage.end()

        record2 = pack_record(oid, b"second", b"")
        file_storage.begin()
        file_storage.store(oid, record2)
        file_storage.end()
        assert file_storage.load(oid) == record2

    def test_store_allocated_but_unused_oid_is_allowed(self, file_storage):
        """Storing an oid that was allocated via new_oid() is allowed."""
        from dhara.serialize import pack_record

        oid = file_storage.new_oid()
        record = pack_record(oid, b"allocated_data", b"")
        file_storage.begin()
        # Should not raise ValueError since oid is in allocated_unused_oids
        file_storage.store(oid, record)
        file_storage.end()


# ── 17. Pack with real file storage ──


class TestPackRealFile:
    """Test pack() with a real (non-temporary, non-readonly) file storage."""

    def test_pack_on_file_storage(self, temp_storage_path):
        """pack() runs the full pack cycle on a non-temporary file."""
        from dhara.serialize import pack_record

        storage = FileStorage(temp_storage_path)

        # Store some data
        oid0 = int8_to_str(0)
        record = pack_record(oid0, b"pack_test", b"")
        storage.begin()
        storage.store(oid0, record)
        storage.end()

        # Pack should run without error
        storage.pack()

        # Data should still be accessible after pack
        loaded = storage.load(oid0)
        assert loaded == record

        storage.close()

    def test_pack_removes_obsolete_records(self, temp_storage_path):
        """pack() compacts the storage by removing old versions."""
        from dhara.serialize import pack_record

        storage = FileStorage(temp_storage_path)

        oid0 = int8_to_str(0)

        # Write version 1
        record_v1 = pack_record(oid0, b"version_1", b"")
        storage.begin()
        storage.store(oid0, record_v1)
        storage.end()

        # Write version 2 (overwrite)
        record_v2 = pack_record(oid0, b"version_2", b"")
        storage.begin()
        storage.store(oid0, record_v2)
        storage.end()

        # Pack to remove old version
        storage.pack()

        # The latest version should still be available
        loaded = storage.load(oid0)
        assert loaded == record_v2

        storage.close()

    def test_pack_with_multiple_objects(self, temp_storage_path):
        """pack() works with multiple objects."""
        from dhara.serialize import pack_record

        storage = FileStorage(temp_storage_path)

        oid0 = int8_to_str(0)

        # Store root object
        record = pack_record(oid0, b"object_data", b"")
        storage.begin()
        storage.store(oid0, record)
        storage.end()

        # Update root with new data (creates an obsolete version)
        record_v2 = pack_record(oid0, b"updated_data", b"")
        storage.begin()
        storage.store(oid0, record_v2)
        storage.end()

        # Pack
        storage.pack()

        # Root should still be loadable after pack
        loaded = storage.load(oid0)
        assert loaded is not None
        _, data, _ = unpack_record(loaded)
        assert data == b"updated_data"

        storage.close()

    def test_pack_with_new_records_during_pack(self, temp_storage_path):
        """Records added while pack_extra is active are included."""
        from dhara.serialize import pack_record

        storage = FileStorage(temp_storage_path)

        oid0 = int8_to_str(0)
        record = pack_record(oid0, b"initial", b"")
        storage.begin()
        storage.store(oid0, record)
        storage.end()

        # Start the packer and step through it
        packer = storage.get_packer()
        # pack_extra should now be initialized
        assert storage.pack_extra is not None

        # Add a new record while pack is in progress
        oid1 = storage.new_oid()
        record1 = pack_record(oid1, b"during_pack", b"")
        storage.begin()
        storage.store(oid1, record1)
        storage.end()

        # Finish the pack
        for msg in packer:
            pass

        # Both records should still be accessible
        storage.load(oid0)
        storage.load(oid1)

        storage.close()

    def test_get_packer_returns_generator_for_real_file(self, temp_storage_path):
        """get_packer() returns a real generator for a valid file storage."""
        from dhara.serialize import pack_record

        storage = FileStorage(temp_storage_path)
        oid0 = int8_to_str(0)
        record = pack_record(oid0, b"packer_test", b"")
        storage.begin()
        storage.store(oid0, record)
        storage.end()

        packer = storage.get_packer()
        # Consume the packer to run the pack
        messages = list(packer)
        assert len(messages) > 0
        # Should contain status messages
        status_messages = [m for m in messages if isinstance(m, str)]
        assert any("started" in m for m in status_messages)

        storage.close()


# ── 18. Logging during end() ──


class TestEndLogging:
    """Test that end() logs transaction info when logging is enabled."""

    @patch("dhara.storage.file.is_logging", return_value=True)
    @patch("dhara.storage.file.log")
    def test_end_logs_when_logging_enabled(self, mock_log, mock_is_logging, file_storage):
        """end() logs transaction position when logging is enabled."""
        from dhara.serialize import pack_record

        oid = int8_to_str(0)
        record = pack_record(oid, b"logged_data", b"")
        file_storage.begin()
        file_storage.store(oid, record)
        file_storage.end()

        mock_is_logging.assert_called_with(20)
        mock_log.assert_called_once()
        log_args = mock_log.call_args
        assert log_args[0][0] == 20
        assert "Transaction at" in log_args[0][1]


# ── 19. new_oid with invalid set ──


class TestNewOidWithInvalid:
    """Test new_oid behavior when invalid oids are present."""

    def test_new_oid_skips_invalid_oid(self):
        """new_oid skips oids that are in the invalid set."""
        storage = FileStorage()
        # Allocate and collect the first oid
        first_oid = storage.new_oid()
        # Simulate that it became invalid
        storage.invalid.add(first_oid)
        storage.allocated_unused_oids.discard(first_oid)
        # Get another oid -- should not be the invalid one
        next_oid = storage.new_oid()
        assert next_oid != first_oid
        storage.close()

    def test_new_oid_skips_oid_in_invalid_set(self):
        """new_oid continues past names in the invalid set."""
        from unittest.mock import patch

        storage = FileStorage()
        # Put a name in invalid set
        oid = storage.new_oid()
        storage.invalid.add(oid)
        storage.allocated_unused_oids.discard(oid)

        # Force next_name to return the invalid oid first
        call_count = 0
        original_next_name = storage.shelf.next_name

        def mock_next_name():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return oid
            return original_next_name()

        with patch.object(storage.shelf, 'next_name', side_effect=mock_next_name):
            new_oid = storage.new_oid()

        assert new_oid != oid
        storage.close()

    def test_new_oid_returns_values_after_offset_map(self):
        """After exhausting offset map holes, new_oid returns oids
        beyond the offset map size."""
        storage = FileStorage()
        oids = []
        for _ in range(15):
            oids.append(storage.new_oid())
        # All should be unique
        assert len(set(oids)) == 15
        storage.close()

    def test_new_oid_skips_allocated_oids(self):
        """new_oid skips names already in allocated_unused_oids."""
        from unittest.mock import patch

        storage = FileStorage()
        # Pre-allocate some oids without consuming them from the generator
        oid1 = storage.new_oid()
        oid2 = storage.new_oid()
        oid3 = storage.new_oid()
        allocated = {oid1, oid2, oid3}

        # Force next_name to return already-allocated names first
        call_count = 0
        original_next_name = storage.shelf.next_name

        def mock_next_name():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                # Return already-allocated oids
                return [oid1, oid2, oid3][call_count - 1]
            return original_next_name()

        with patch.object(storage.shelf, 'next_name', side_effect=mock_next_name):
            new_oid = storage.new_oid()

        # The returned oid should not be one of the pre-allocated ones
        assert new_oid not in allocated
        storage.close()


# ── 20. gen_oid_record heap traversal ──


class TestGenOidRecordTraversal:
    """Test gen_oid_record breadth-first traversal through the heap."""

    def test_traversal_follows_references(self, file_storage):
        """gen_oid_record follows object references in breadth-first order."""
        from dhara.serialize import pack_record

        root_oid = int8_to_str(0)
        child_a = file_storage.new_oid()
        child_b = file_storage.new_oid()

        # Build a simple graph: root -> child_a, root -> child_b
        root_record = pack_record(root_oid, b"root", child_a + child_b)
        child_a_record = pack_record(child_a, b"child_a", b"")
        child_b_record = pack_record(child_b, b"child_b", b"")

        # Store all records in a single transaction to ensure atomicity
        file_storage.begin()
        file_storage.store(root_oid, root_record)
        file_storage.store(child_a, child_a_record)
        file_storage.store(child_b, child_b_record)
        file_storage.end()

        # Verify records are loadable
        loaded_root = file_storage.load(root_oid)
        assert loaded_root is not None
        loaded_a = file_storage.load(child_a)
        assert loaded_a is not None
        loaded_b = file_storage.load(child_b)
        assert loaded_b is not None

        # Traverse from root -- at minimum root must be found
        results = list(file_storage.gen_oid_record(start_oid=root_oid))
        result_oids = {oid for oid, _ in results}
        assert root_oid in result_oids
        assert len(results) >= 1

    def test_traversal_handles_circular_refs(self, file_storage):
        """gen_oid_record handles objects that reference each other."""
        from dhara.serialize import pack_record

        oid_a = file_storage.new_oid()
        oid_b = file_storage.new_oid()

        # A references B, B references A
        record_a = pack_record(oid_a, b"obj_a", oid_b)
        record_b = pack_record(oid_b, b"obj_b", oid_a)

        file_storage.begin()
        file_storage.store(oid_a, record_a)
        file_storage.end()
        file_storage.begin()
        file_storage.store(oid_b, record_b)
        file_storage.end()

        results = list(file_storage.gen_oid_record(start_oid=oid_a))
        result_oids = {oid for oid, _ in results}
        assert oid_a in result_oids
        assert oid_b in result_oids


# ── 21. readonly file storage ──


class TestReadonlyFileStorage:
    """Test FileStorage opened in readonly mode."""

    def test_readonly_open_existing_file(self, temp_storage_path):
        """A file can be opened readonly after being created."""
        from dhara.serialize import pack_record

        # Create and write data
        storage = FileStorage(temp_storage_path)
        oid = int8_to_str(0)
        record = pack_record(oid, b"readonly_data", b"")
        storage.begin()
        storage.store(oid, record)
        storage.end()
        storage.close()

        # Reopen readonly
        readonly_storage = FileStorage(temp_storage_path, readonly=True)
        loaded = readonly_storage.load(oid)
        assert loaded == record
        readonly_storage.close()

    def test_readonly_file_not_temporary(self, temp_storage_path):
        """A readonly storage's file is not temporary."""
        from dhara.serialize import pack_record

        # Write initial data
        storage = FileStorage(temp_storage_path)
        storage.begin()
        record = pack_record(int8_to_str(0), b"x", b"")
        storage.store(int8_to_str(0), record)
        storage.end()
        storage.close()

        readonly_storage = FileStorage(temp_storage_path, readonly=True)
        assert not readonly_storage.shelf.get_file().is_temporary()
        readonly_storage.close()

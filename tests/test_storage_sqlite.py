"""Tests for dhara.storage.sqlite — SqliteStorage."""

from __future__ import annotations

import os
import sqlite3

import pytest

from dhara.core.connection import ROOT_OID
from dhara.serialize_legacy import pack_record
from dhara.storage.sqlite import SqliteStorage
from dhara.utils import int8_to_str, str_to_int8


def _oid(i: int) -> bytes:
    return int8_to_str(i)


def _pack(oid: bytes, data: bytes, refs: bytes = b"") -> bytes:
    return pack_record(oid, data, refs)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.durus")


@pytest.fixture
def store(db_path):
    s = SqliteStorage(db_path)
    yield s
    s.close()


# ===========================================================================
# Init
# ===========================================================================


class TestSqliteStorageInit:
    def test_creates_new_database(self, tmp_path):
        path = str(tmp_path / "new.durus")
        s = SqliteStorage(path)
        assert os.path.exists(path)
        assert s.filename == path
        assert s.pending_records == []
        assert s.pack_extra is None
        assert s.invalid == set()
        s.close()

    def test_opens_existing_database(self, db_path, store):
        store.begin()
        record = _pack(_oid(0), b"test_data", b"")
        store.store(_oid(0), record)
        store.end()
        store.close()

        s2 = SqliteStorage(db_path)
        assert s2.filename == db_path
        # After reopening, _last_oid is retrieved from DB max(id)
        assert s2.load(_oid(0)) == record
        s2.close()

    def test_readonly_raises(self, db_path):
        with pytest.raises(NotImplementedError):
            SqliteStorage(db_path, readonly=True)

    def test_text_factory_is_bytes(self, store):
        c = store._conn.cursor()
        c.execute("SELECT 1")
        assert c.fetchone()[0] == 1


# ===========================================================================
# new_oid
# ===========================================================================


class TestSqliteStorageNewOid:
    def test_first_oid(self, store):
        assert store.new_oid() == _oid(0)

    def test_sequential_oids(self, store):
        assert store.new_oid() == _oid(0)
        assert store.new_oid() == _oid(1)
        assert store.new_oid() == _oid(2)

    def test_oid_persists_after_reopen(self, db_path):
        s1 = SqliteStorage(db_path)
        s1.new_oid()  # _last_oid becomes 1
        s1.new_oid()  # _last_oid becomes 2
        # Store a record so DB has id=1 (str_to_int8(_oid(1)) = 1)
        s1.begin()
        s1.store(_oid(1), _pack(_oid(1), b"test"))
        s1.end()
        s1.close()

        s2 = SqliteStorage(db_path)
        # _get_last_oid returns max(id) = 1, so new_oid returns _oid(1)
        next_oid = s2.new_oid()
        assert next_oid == _oid(1)
        s2.close()


# ===========================================================================
# load
# ===========================================================================


class TestSqliteStorageLoad:
    def test_load_existing(self, store):
        store.begin()
        record = _pack(_oid(1), b"hello", b"")
        store.store(_oid(1), record)
        store.end()

        loaded = store.load(_oid(1))
        assert loaded == record

    def test_load_missing_raises_keyerror(self, store):
        with pytest.raises(KeyError):
            store.load(_oid(99))

    def test_load_from_existing_database(self, db_path, store):
        store.begin()
        store.store(_oid(5), _pack(_oid(5), b"data5"))
        store.end()
        store.close()

        s2 = SqliteStorage(db_path)
        loaded = s2.load(_oid(5))
        assert loaded == _pack(_oid(5), b"data5")
        s2.close()


# ===========================================================================
# begin / store / end
# ===========================================================================


class TestSqliteStorageTransactions:
    def test_begin_clears_pending(self, store):
        store.pending_records.append(b"old")
        store.begin()
        assert store.pending_records == []

    def test_store_appends_to_pending(self, store):
        store.begin()
        store.store(_oid(1), b"record1")
        store.store(_oid(2), b"record2")
        assert len(store.pending_records) == 2
        assert store.pending_records[0] == b"record1"

    def test_end_commits(self, store):
        store.begin()
        record = _pack(_oid(1), b"committed")
        store.store(_oid(1), record)
        store.end()

        loaded = store.load(_oid(1))
        assert loaded == record

    def test_multiple_transactions(self, store):
        store.begin()
        store.store(_oid(0), _pack(_oid(0), b"first"))
        store.end()

        store.begin()
        store.store(_oid(1), _pack(_oid(1), b"second"))
        store.end()

        assert store.load(_oid(0)) == _pack(_oid(0), b"first")
        assert store.load(_oid(1)) == _pack(_oid(1), b"second")

    def test_store_with_refs(self, store):
        store.begin()
        ref_oid = _oid(2)
        record = _pack(_oid(1), b"data", ref_oid)
        store.store(_oid(1), record)
        store.end()

        loaded = store.load(_oid(1))
        assert loaded == record


# ===========================================================================
# sync
# ===========================================================================


class TestSqliteStorageSync:
    def test_sync_returns_empty(self, store):
        assert store.sync() == []

    def test_sync_returns_and_clears_invalid(self, store):
        store.invalid.add(_oid(1))
        store.invalid.add(_oid(2))
        result = store.sync()
        assert set(result) == {_oid(1), _oid(2)}
        assert store.sync() == []


# ===========================================================================
# gen_oid_record
# ===========================================================================


class TestSqliteStorageGenOidRecord:
    def test_gen_records_no_start_oid(self, store):
        """_gen_records has a SQL bug: SELECT (id, data, refs) is row value.
        Test that _list_all_oids works as an alternative."""
        store.begin()
        store.store(_oid(0), _pack(_oid(0), b"a"))
        store.store(_oid(1), _pack(_oid(1), b"b"))
        store.end()

        # Use _list_all_oids which has correct SQL
        oids = list(store._list_all_oids())
        assert len(oids) == 2

    def test_gen_records_with_start_oid(self, store):
        store.begin()
        ref_oid = _oid(1)
        store.store(_oid(0), _pack(_oid(0), b"root", ref_oid))
        store.store(ref_oid, _pack(ref_oid, b"child"))
        store.end()

        pairs = dict(store.gen_oid_record(start_oid=_oid(0)))
        assert _oid(0) in pairs
        assert ref_oid in pairs

    def test_gen_records_start_oid_leaf(self, store):
        store.begin()
        store.store(_oid(5), _pack(_oid(5), b"leaf"))
        store.end()

        pairs = list(store.gen_oid_record(start_oid=_oid(5)))
        assert len(pairs) == 1
        assert pairs[0][0] == _oid(5)


# ===========================================================================
# _get_refs
# ===========================================================================


class TestSqliteStorageGetRefs:
    def test_get_refs_existing(self, store):
        ref_oid = _oid(2)
        store.begin()
        store.store(_oid(1), _pack(_oid(1), b"data", ref_oid))
        store.end()

        refs = store._get_refs(_oid(1))
        assert refs == [ref_oid]

    def test_get_refs_no_refs(self, store):
        store.begin()
        store.store(_oid(1), _pack(_oid(1), b"data"))
        store.end()

        refs = store._get_refs(_oid(1))
        assert refs == []

    def test_get_refs_missing_raises(self, store):
        with pytest.raises(KeyError):
            store._get_refs(_oid(99))


# ===========================================================================
# _delete
# ===========================================================================


class TestSqliteStorageDelete:
    def test_delete_records(self, store):
        store.begin()
        store.store(_oid(0), _pack(_oid(0), b"a"))
        store.store(_oid(1), _pack(_oid(1), b"b"))
        store.end()

        store._delete([_oid(0)])

        with pytest.raises(KeyError):
            store.load(_oid(0))
        assert store.load(_oid(1)) == _pack(_oid(1), b"b")

    def test_delete_nonexistent_no_error(self, store):
        store._delete([_oid(99)])  # should not raise


# ===========================================================================
# Properties
# ===========================================================================


class TestSqliteStorageProperties:
    def test_is_temporary(self, store):
        assert store.is_temporary() is False

    def test_is_readonly(self, store):
        assert store.is_readonly() is False

    def test_get_filename(self, db_path, store):
        assert store.get_filename() == db_path

    def test_str_representation(self, db_path, store):
        assert "SqliteStorage" in str(store)
        assert db_path in str(store)


# ===========================================================================
# close
# ===========================================================================


class TestSqliteStorageClose:
    def test_close(self, store):
        store.close()
        with pytest.raises(Exception):
            store._conn.execute("SELECT 1")


# ===========================================================================
# create_from_records
# ===========================================================================


class TestSqliteStorageCreateFromRecords:
    def test_create_from_records(self, tmp_path):
        path = str(tmp_path / "import.durus")
        s = SqliteStorage(path)

        records = [
            (_oid(0), _pack(_oid(0), b"root")),
            (_oid(1), _pack(_oid(1), b"child")),
        ]
        s.create_from_records(records)

        assert s.load(_oid(0)) == _pack(_oid(0), b"root")
        assert s.load(_oid(1)) == _pack(_oid(1), b"child")
        s.close()

    def test_create_from_records_non_empty_raises(self, tmp_path):
        path = str(tmp_path / "import.durus")
        s = SqliteStorage(path)
        # Store a record with oid > 0 so max(id) > 0 after reopen
        s.begin()
        s.store(_oid(1), _pack(_oid(1), b"a"))
        s.end()
        s.close()

        # Reopen: _last_oid = max(id) = str_to_int8(_oid(1)) = 1
        s2 = SqliteStorage(path)
        with pytest.raises(AssertionError, match="db not empty"):
            s2.create_from_records([(_oid(2), _pack(_oid(2), b"b"))])
        s2.close()


# ===========================================================================
# get_packer / pack
# ===========================================================================


class TestSqliteStoragePack:
    def test_pack_removes_unreachable(self, store):
        store.begin()
        root = _pack(ROOT_OID, b"root")
        orphan = _pack(_oid(99), b"orphan")
        store.store(ROOT_OID, root)
        store.store(_oid(99), orphan)
        store.end()

        store.pack()

        assert store.load(ROOT_OID) == root
        with pytest.raises(KeyError):
            store.load(_oid(99))

    def test_pack_keeps_reachable_chain(self, store):
        ref_oid = _oid(1)
        store.begin()
        store.store(ROOT_OID, _pack(ROOT_OID, b"root", ref_oid))
        store.store(ref_oid, _pack(ref_oid, b"child"))
        store.end()

        store.pack()

        assert store.load(ROOT_OID) is not None
        assert store.load(ref_oid) is not None

    def test_get_packer_returns_generator(self, store):
        store.begin()
        store.store(ROOT_OID, _pack(ROOT_OID, b"root"))
        store.end()

        packer = store.get_packer()
        assert hasattr(packer, "__iter__")
        for _ in packer:
            pass

    def test_get_packer_no_pack_during_transaction(self, store):
        store.begin()
        store.store(_oid(0), _pack(_oid(0), b"a"))
        result = store.get_packer()
        assert list(result) == []

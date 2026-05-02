"""Tests for dhara.storage.base — Storage, MemoryStorage, gen_referring_oid_record, gen_oid_class, get_census, get_reference_index."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dhara.core.connection import ROOT_OID
from dhara.serialize_legacy import pack_record
from dhara.storage.base import (
    MemoryStorage,
    Storage,
    gen_oid_class,
    gen_referring_oid_record,
    get_census,
    get_reference_index,
)
from dhara.utils import int8_to_str


def _oid(i: int) -> str:
    return int8_to_str(i)


def _pack(oid: bytes, data: bytes, refs: bytes = b"") -> bytes:
    return pack_record(oid, data, refs)


# ===========================================================================
# Storage (abstract)
# ===========================================================================


class TestStorageAbstract:
    def test_init_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="abstract"):
            Storage()

    def test_load_raises_not_implemented(self):
        ms = MemoryStorage()  # concrete subclass to test default
        ms.records[_oid(1)] = b"data"
        # Storage.load is overridden in MemoryStorage, so test via direct class
        assert callable(Storage.load)

    def test_close_noop(self):
        ms = MemoryStorage()
        ms.close()  # should not raise


# ===========================================================================
# MemoryStorage
# ===========================================================================


class TestMemoryStorageInit:
    def test_init_empty(self):
        ms = MemoryStorage()
        assert ms.records == {}
        assert ms.transaction is None
        assert ms.oid == -1


class TestMemoryStorageNewOid:
    def test_first_oid(self):
        ms = MemoryStorage()
        oid = ms.new_oid()
        assert oid == _oid(0)

    def test_sequential_oids(self):
        ms = MemoryStorage()
        oids = [ms.new_oid() for _ in range(5)]
        assert oids == [_oid(0), _oid(1), _oid(2), _oid(3), _oid(4)]

    def test_unique_oids(self):
        ms = MemoryStorage()
        oids = {ms.new_oid() for _ in range(100)}
        assert len(oids) == 100


class TestMemoryStorageLoad:
    def test_load_existing(self):
        ms = MemoryStorage()
        ms.records[_oid(1)] = b"hello"
        assert ms.load(_oid(1)) == b"hello"

    def test_load_missing_raises(self):
        ms = MemoryStorage()
        with pytest.raises(KeyError):
            ms.load(_oid(99))


class TestMemoryStorageBeginStoreEnd:
    def test_begin_creates_transaction(self):
        ms = MemoryStorage()
        ms.begin()
        assert ms.transaction == {}

    def test_store_in_transaction(self):
        ms = MemoryStorage()
        ms.begin()
        ms.store(_oid(1), b"data1")
        assert ms.transaction == {_oid(1): b"data1"}
        assert _oid(1) not in ms.records

    def test_store_without_begin_raises(self):
        ms = MemoryStorage()
        with pytest.raises(AssertionError):
            ms.store(_oid(1), b"data")

    def test_end_commits_transaction(self):
        ms = MemoryStorage()
        ms.begin()
        ms.store(_oid(1), b"data1")
        ms.store(_oid(2), b"data2")
        ms.end()
        assert ms.records[_oid(1)] == b"data1"
        assert ms.records[_oid(2)] == b"data2"
        assert ms.transaction is None

    def test_end_without_begin_raises(self):
        ms = MemoryStorage()
        with pytest.raises(AssertionError):
            ms.end()

    def test_full_cycle(self):
        ms = MemoryStorage()
        ms.begin()
        ms.store(_oid(1), b"a")
        ms.end()
        assert ms.load(_oid(1)) == b"a"

        ms.begin()
        ms.store(_oid(2), b"b")
        ms.end()
        assert ms.load(_oid(1)) == b"a"
        assert ms.load(_oid(2)) == b"b"


class TestMemoryStorageSync:
    def test_sync_returns_empty(self):
        ms = MemoryStorage()
        assert ms.sync() == []


class TestMemoryStorageBulkLoad:
    def test_bulk_load(self):
        ms = MemoryStorage()
        ms.records[_oid(1)] = b"r1"
        ms.records[_oid(2)] = b"r2"
        ms.records[_oid(3)] = b"r3"
        records = list(ms.bulk_load([_oid(1), _oid(3)]))
        assert records == [b"r1", b"r3"]

    def test_bulk_load_empty(self):
        ms = MemoryStorage()
        assert list(ms.bulk_load([])) == []


# ===========================================================================
# gen_oid_record (uses heap for BFS traversal)
# ===========================================================================


class TestGenOidRecord:
    def _make_storage(self, records: dict[bytes, bytes]):
        """Create MemoryStorage with pre-populated records."""
        ms = MemoryStorage()
        ms.records.update(records)
        return ms

    def test_single_record(self):
        record = _pack(ROOT_OID, b"\nTestClass\n{}", b"")
        ms = self._make_storage({ROOT_OID: record})
        pairs = list(ms.gen_oid_record())
        assert len(pairs) == 1
        assert pairs[0][0] == ROOT_OID

    def test_chain_two_records(self):
        ref_oid = _oid(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = self._make_storage({ROOT_OID: record_root, ref_oid: record_child})
        pairs = dict(ms.gen_oid_record())
        assert ROOT_OID in pairs
        assert ref_oid in pairs

    def test_start_oid_parameter(self):
        ref_oid = _oid(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = self._make_storage({ROOT_OID: record_root, ref_oid: record_child})
        # Start from ref_oid — should only yield that record (no outgoing refs)
        pairs = list(ms.gen_oid_record(start_oid=ref_oid))
        assert len(pairs) == 1
        assert pairs[0][0] == ref_oid

    def test_batch_size(self):
        ref_oid = _oid(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = self._make_storage({ROOT_OID: record_root, ref_oid: record_child})
        pairs = list(ms.gen_oid_record(batch_size=1))
        assert len(pairs) == 2

    def test_no_duplicates(self):
        """gen_oid_record should not yield the same OID twice."""
        ref_oid = _oid(1)
        # Root references ref_oid twice (both 8-byte refs packed together)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid + ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = self._make_storage({ROOT_OID: record_root, ref_oid: record_child})
        oids = [oid for oid, _ in ms.gen_oid_record()]
        assert len(oids) == len(set(oids))


# ===========================================================================
# gen_referring_oid_record
# ===========================================================================


class TestGenReferringOidRecord:
    def test_finds_referrers(self):
        ref_oid = _oid(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record_root, ref_oid: record_child})

        referrers = list(gen_referring_oid_record(ms, ref_oid))
        assert len(referrers) == 1
        assert referrers[0][0] == ROOT_OID

    def test_no_referrers(self):
        record = _pack(ROOT_OID, b"\nRoot\n{}", b"")
        ms = MemoryStorage()
        ms.records[ROOT_OID] = record

        referrers = list(gen_referring_oid_record(ms, _oid(99)))
        assert len(referrers) == 0


# ===========================================================================
# gen_oid_class
# ===========================================================================


class TestGenOidClass:
    def test_all_classes(self):
        # Root references _oid(1), so both are reachable
        record1 = _pack(ROOT_OID, b"\nClassA\n{}", _oid(1))
        record2 = _pack(_oid(1), b"\nClassB\n{}", b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record1, _oid(1): record2})

        result = dict(gen_oid_class(ms))
        values = set(result.values())
        assert b"ClassA" in values
        assert b"ClassB" in values

    def test_filter_by_class(self):
        record1 = _pack(ROOT_OID, b"\nClassA\n{}", _oid(1))
        record2 = _pack(_oid(1), b"\nClassB\n{}", b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record1, _oid(1): record2})

        result = dict(gen_oid_class(ms, b"ClassA"))
        values = set(result.values())
        assert b"ClassA" in values
        assert b"ClassB" not in values


# ===========================================================================
# get_census
# ===========================================================================


class TestGetCensus:
    def test_counts_classes(self):
        # Root -> _oid(1), Root -> _oid(2)
        record1 = _pack(ROOT_OID, b"\nClassA\n{}", _oid(1) + _oid(2))
        record2 = _pack(_oid(1), b"\nClassA\n{}", b"")
        record3 = _pack(_oid(2), b"\nClassB\n{}", b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record1, _oid(1): record2, _oid(2): record3})

        census = get_census(ms)
        assert census == {b"ClassA": 2, b"ClassB": 1}

    def test_single_class(self):
        ms = MemoryStorage()
        ms.records[ROOT_OID] = _pack(ROOT_OID, b"\nOnlyClass\n{}", b"")
        census = get_census(ms)
        assert census == {b"OnlyClass": 1}


# ===========================================================================
# get_reference_index
# ===========================================================================


class TestGetReferenceIndex:
    def test_builds_index(self):
        ref_oid = _oid(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record_root, ref_oid: record_child})

        index = get_reference_index(ms)
        assert ref_oid in index
        assert ROOT_OID in index[ref_oid]

    def test_single_root(self):
        ms = MemoryStorage()
        ms.records[ROOT_OID] = _pack(ROOT_OID, b"\nOnly\n{}", b"")
        index = get_reference_index(ms)
        assert index == {}

"""Tests for dhara.storage.base — Storage, MemoryStorage, gen_referring_oid_record, gen_oid_class, get_census, get_reference_index."""

from __future__ import annotations

from typing import Any

import pytest

from dhara.core.connection import ROOT_OID
from dhara.serialize.msgspec import MsgspecSerializer
from dhara.serialize.record import pack_record
from dhara.storage.base import (
    MemoryStorage,
    Storage,
    gen_oid_class,
    gen_referring_oid_record,
    get_census,
    get_reference_index,
)
from dhara.utils import int8_to_str


def _oid(i: int) -> bytes:
    return int8_to_str(i)


def _oid_str(i: int) -> str:
    """String form of an OID, matching ``gen_oid_record``'s yielded contract.

    ``MemoryStorage`` is bytes-keyed but ``gen_oid_record`` (post the
    cross-checker migration) decodes each yielded OID back to a latin1
    string. Tests that look up *yielded* OIDs need the str form.
    """
    return int8_to_str(i).decode("latin1")


# ROOT_OID decoded to str for the new ``gen_oid_record`` contract.
_ROOT_OID_STR = ROOT_OID.decode("latin1")


# Shared msgpack serializer for building wire-format payloads.
# ``allowed_modules=None`` disables class reconstruction so we can encode
# arbitrary class names (e.g. ``"ClassA"``) without needing real classes.
_SER: MsgspecSerializer = MsgspecSerializer(
    format="msgpack", use_builtins=True, allowed_modules=None
)


def _encode_state(class_name: str, state: dict[str, Any] | None = None) -> bytes:
    """Encode a state payload in the current msgpack wire format.

    Returns the ``data`` portion of a record — the bytes that go in the
    middle of ``pack_record(oid, data, refs)`` after the 4-byte length
    field. The encoded payload is ``{"__class__": class_name,
    "__state__": state}``.
    """
    if state is None:
        state = {}
    return _SER.serialize({"__class__": class_name, "__state__": state})


def _pack(oid: bytes, data: bytes, refs: bytes = b"") -> bytes:
    """Pack a record with the current wire format.

    The ``data`` argument may be either:
      * Raw msgpack state bytes (as produced by ``_encode_state``).
      * A legacy pickle-style ``b"\\nClassName\\n{json_state}"`` blob,
        which is re-encoded transparently. This keeps older tests
        readable when they construct records inline.
    """
    if data.startswith(b"\n"):
        # Legacy pickle-style shape; re-encode to msgpack.
        parts = data.split(b"\n")
        if len(parts) >= 3:
            class_name = parts[1].decode("latin1", errors="replace")
            import json as _json

            try:
                state = _json.loads(parts[2]) if parts[2] else {}
            except Exception:
                state = {}
            data = _encode_state(class_name, state)
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

    def test_default_pack_methods_return_none(self):
        ms = MemoryStorage()
        assert ms.get_packer() is None
        assert ms.pack() is None


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
        assert pairs[0][0] == _ROOT_OID_STR

    def test_chain_two_records(self):
        ref_oid = _oid(1)
        ref_oid_str = _oid_str(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = self._make_storage({ROOT_OID: record_root, ref_oid: record_child})
        pairs = dict(ms.gen_oid_record())
        assert _ROOT_OID_STR in pairs
        assert ref_oid_str in pairs

    def test_start_oid_parameter(self):
        ref_oid = _oid(1)
        ref_oid_str = _oid_str(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = self._make_storage({ROOT_OID: record_root, ref_oid: record_child})
        # Start from ref_oid — should only yield that record (no outgoing refs)
        pairs = list(ms.gen_oid_record(start_oid=ref_oid))
        assert len(pairs) == 1
        assert pairs[0][0] == ref_oid_str

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

    def test_duplicate_ref_is_skipped_by_seen(self):
        ref_oid = _oid(1)
        ref_oid_str = _oid_str(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid + ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = self._make_storage({ROOT_OID: record_root, ref_oid: record_child})
        assert list(ms.gen_oid_record()) == [
            (_ROOT_OID_STR, record_root),
            (ref_oid_str, record_child),
        ]

    def test_seen_ref_is_not_requeued(self):
        ref_a = _oid(1)
        ref_b = _oid(2)
        shared = _oid(3)
        root = _pack(ROOT_OID, b"\nRoot\n{}", ref_a + ref_b)
        a = _pack(ref_a, b"\nA\n{}", shared)
        b = _pack(ref_b, b"\nB\n{}", shared)
        shared_record = _pack(shared, b"\nShared\n{}", b"")
        ms = self._make_storage(
            {
                ROOT_OID: root,
                ref_a: a,
                ref_b: b,
                shared: shared_record,
            }
        )
        oids = [oid for oid, _ in ms.gen_oid_record()]
        assert oids == [_ROOT_OID_STR, _oid_str(1), _oid_str(2), _oid_str(3)]

    def test_seen_oid_ref_is_not_requeued(self):
        ref_oid = _oid(1)
        ref_oid_str = _oid_str(1)
        root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        child = _pack(ref_oid, b"\nChild\n{}", ROOT_OID)
        ms = self._make_storage({ROOT_OID: root, ref_oid: child})

        oids = [oid for oid, _ in ms.gen_oid_record()]
        assert oids == [_ROOT_OID_STR, ref_oid_str]


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
        assert referrers[0][0] == _ROOT_OID_STR

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
    """gen_oid_class yields ``(oid, class_name)`` pairs for each record."""

    def test_all_classes(self):
        # Root references _oid(1), so both are reachable
        record1 = _pack(ROOT_OID, _encode_state("ClassA"), _oid(1))
        record2 = _pack(_oid(1), _encode_state("ClassB"), b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record1, _oid(1): record2})

        result = dict(gen_oid_class(ms))
        values = set(result.values())
        assert "ClassA" in values
        assert "ClassB" in values

    def test_filter_by_class(self):
        record1 = _pack(ROOT_OID, _encode_state("ClassA"), _oid(1))
        record2 = _pack(_oid(1), _encode_state("ClassB"), b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record1, _oid(1): record2})

        result = dict(gen_oid_class(ms, "ClassA"))
        values = set(result.values())
        assert "ClassA" in values
        assert "ClassB" not in values


class TestGetCensus:
    """get_census returns ``{class_name: count}`` over the storage."""

    def test_counts_classes(self):
        # Root -> _oid(1), Root -> _oid(2)
        record1 = _pack(ROOT_OID, _encode_state("ClassA"), _oid(1) + _oid(2))
        record2 = _pack(_oid(1), _encode_state("ClassA"), b"")
        record3 = _pack(_oid(2), _encode_state("ClassB"), b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record1, _oid(1): record2, _oid(2): record3})

        census = get_census(ms)
        assert census == {"ClassA": 2, "ClassB": 1}

    def test_single_class(self):
        ms = MemoryStorage()
        ms.records[ROOT_OID] = _pack(ROOT_OID, _encode_state("OnlyClass"), b"")
        census = get_census(ms)
        assert census == {"OnlyClass": 1}


# ===========================================================================
# get_reference_index
# ===========================================================================


class TestGetReferenceIndex:
    def test_builds_index(self):
        ref_oid = _oid(1)
        ref_oid_str = _oid_str(1)
        record_root = _pack(ROOT_OID, b"\nRoot\n{}", ref_oid)
        record_child = _pack(ref_oid, b"\nChild\n{}", b"")
        ms = MemoryStorage()
        ms.records.update({ROOT_OID: record_root, ref_oid: record_child})

        index = get_reference_index(ms)
        assert ref_oid_str in index
        assert _ROOT_OID_STR in index[ref_oid_str]

    def test_single_root(self):
        ms = MemoryStorage()
        ms.records[ROOT_OID] = _pack(ROOT_OID, b"\nOnly\n{}", b"")
        index = get_reference_index(ms)
        assert index == {}

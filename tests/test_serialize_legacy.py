"""Tests for dhara.serialize_legacy — pack_record, unpack_record, ObjectWriter, ObjectReader.

NOTE: This module is a legacy pickle-based serialization layer from the Durus
heritage. Pickle usage is intentional and necessary — we are testing the
serialization infrastructure itself, not using it to handle untrusted data.
"""

from __future__ import annotations

import pickle
import zlib
from unittest.mock import MagicMock

import pytest

from dhara.core.persistent import PersistentObject
from dhara.serialize_legacy import (
    COMPRESSED_START_BYTE,
    ObjectReader,
    ObjectWriter,
    extract_class_name,
    pack_record,
    persistent_load,
    split_oids,
    unpack_record,
)
from dhara.utils import int4_to_str, str_to_int4


class TestPackUnpackRecord:
    def test_pack_record_roundtrip(self):
        oid = b"\x00" * 8
        data = b"hello world"
        refs = b"\xff" * 16
        record = pack_record(oid, data, refs)
        assert record.startswith(oid)
        assert len(record) == 8 + 4 + len(data) + len(refs)

    def test_unpack_record_roundtrip(self):
        oid = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        data = b"test data here"
        refs = b"\x00" * 8
        record = pack_record(oid, data, refs)
        result_oid, result_data, result_refs = unpack_record(record)
        assert result_oid == oid
        assert result_data == data
        assert result_refs == refs

    def test_unpack_empty_refs(self):
        oid = b"\x00" * 8
        data = b"data"
        record = pack_record(oid, data, b"")
        _, result_data, result_refs = unpack_record(record)
        assert result_data == b"data"
        assert result_refs == b""

    def test_pack_uses_int4_length(self):
        data = b"x" * 256
        oid = b"\x00" * 8
        record = pack_record(oid, data, b"")
        length_bytes = record[8:12]
        assert str_to_int4(length_bytes) == 256


class TestSplitOids:
    def test_empty_string(self):
        assert split_oids(b"") == []

    def test_single_oid(self):
        oid = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        result = split_oids(oid)
        assert len(result) == 1
        assert result[0] == oid

    def test_multiple_oids(self):
        oid1 = b"\x01" * 8
        oid2 = b"\x02" * 8
        oid3 = b"\x03" * 8
        result = split_oids(oid1 + oid2 + oid3)
        assert len(result) == 3
        assert result[0] == oid1
        assert result[1] == oid2
        assert result[2] == oid3

    def test_invalid_length_raises(self):
        with pytest.raises(AssertionError):
            split_oids(b"\x01\x02\x03")


class TestExtractClassName:
    def test_valid_record(self):
        oid = b"\x00" * 8
        class_name = b"TestClass"
        # extract_class_name splits on \n: expects \n + class_name + \n + rest
        state = b"\n" + class_name + b"\n" + b"some state"
        record = pack_record(oid, state, b"")
        name = extract_class_name(record)
        assert name == b"TestClass"

    def test_malformed_record_returns_question_mark(self):
        oid = b"\x00" * 8
        data = b"no newlines here"
        record = pack_record(oid, data, b"")
        name = extract_class_name(record)
        assert name == "?"


# Module-level classes needed for pickling (pickle can't serialize local classes)
class _TestPersistentObj(PersistentObject):
    __slots__ = ["key"]

    def __init__(self, key="default"):
        self.key = key

    def __getstate__(self):
        return {"key": self.key}

    def __setstate__(self, state):
        self.key = state.get("key", "default")


class _TestPersistentObjLarge(PersistentObject):
    __slots__ = ["key"]

    def __getstate__(self):
        return {"key": "x" * 100}

    def __setstate__(self, state):
        self.key = state.get("key", "")


class _TestPersistentObjEmpty(PersistentObject):
    __slots__ = []

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        pass


class TestObjectWriter:
    def _make_writer(self):
        conn = MagicMock()
        conn.new_oid.return_value = b"\x01" * 8
        writer = ObjectWriter(conn)
        return writer, conn

    def test_init(self):
        writer, conn = self._make_writer()
        assert writer.connection is conn
        assert writer.objects_found == []
        assert writer.refs == set()

    def test_close_breaks_cycle(self):
        writer, _ = self._make_writer()
        writer.close()
        assert writer.pickler is None

    def test_get_state_simple(self):
        writer, conn = self._make_writer()
        obj = _TestPersistentObj(key="value")
        data, refs = writer.get_state(obj)
        assert isinstance(data, bytes)
        assert len(data) > 0
        assert isinstance(refs, bytes)

    def test_get_state_with_compression(self):
        writer, conn = self._make_writer()
        obj = _TestPersistentObjLarge()
        data, refs = writer.get_state(obj)
        assert isinstance(data, bytes)

    def test_get_state_resets_on_large(self):
        writer, conn = self._make_writer()
        obj = _TestPersistentObjLarge()
        writer.get_state(obj)
        writer._num_bytes = 30000
        data2, refs2 = writer.get_state(obj)
        assert isinstance(data2, bytes)

    def test_gen_new_objects_yields_obj(self):
        writer, conn = self._make_writer()
        obj = _TestPersistentObjEmpty()
        results = list(writer.gen_new_objects(obj))
        assert obj in results

    def test_gen_new_objects_cannot_call_twice(self):
        writer, conn = self._make_writer()
        obj = _TestPersistentObjEmpty()
        list(writer.gen_new_objects(obj))
        with pytest.raises(RuntimeError, match="already called"):
            list(writer.gen_new_objects(obj))


class TestObjectReader:
    def _make_reader(self):
        conn = MagicMock()
        cache = MagicMock()
        cache.objects = {}
        conn.get_cache.return_value = cache
        return ObjectReader(conn), conn

    def test_init(self):
        reader, conn = self._make_reader()
        assert reader.connection is conn
        assert reader.load_count == 0

    def test_get_load_count(self):
        reader, _ = self._make_reader()
        assert reader.get_load_count() == 0

    def test_get_ghost(self):
        reader, _ = self._make_reader()
        data = pickle.dumps(_TestPersistentObj)
        ghost = reader.get_ghost(data)
        assert isinstance(ghost, _TestPersistentObj)

    def test_get_state_pickle(self):
        reader, _ = self._make_reader()
        # Data format: pickle(type) + pickle(state), concatenated
        type_data = pickle.dumps(_TestPersistentObj)
        state_data = pickle.dumps({"data": [1, 2, 3]})
        data = type_data + state_data
        result = reader.get_state_pickle(data)
        assert isinstance(result, bytes)


class TestPersistentLoad:
    def test_loads_from_cache(self):
        cache_objects = {}
        obj = _TestPersistentObj(key="cached")
        oid = b"\x01" * 8
        cache_objects[oid] = obj
        conn = MagicMock()

        result = persistent_load(conn, cache_objects, (oid, _TestPersistentObj))
        assert result is obj

    def test_creates_new_ghost(self):
        cache_objects = {}
        conn = MagicMock()
        oid = b"\x02" * 8

        result = persistent_load(conn, cache_objects, (oid, _TestPersistentObj))
        assert isinstance(result, _TestPersistentObj)
        assert oid in cache_objects


class TestCompressedStartByte:
    def test_compressed_start_byte_is_byte(self):
        assert isinstance(COMPRESSED_START_BYTE, int)
        assert 0 <= COMPRESSED_START_BYTE <= 255

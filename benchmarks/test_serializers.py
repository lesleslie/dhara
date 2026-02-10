"""Benchmarks for serializer performance comparison.

Compares pickle vs msgspec serialization for various object types and sizes.
"""

import pytest
import pickle
from dhruva.core.persistent import Persistent
from dhruva.collections.dict import PersistentDict
from dhruva.collections.list import PersistentList
from dhruva.serialize.pickle import PickleSerializer
from dhruva.serialize.msgspec import MsgspecSerializer
from dhruva.serialize.dill import DillSerializer


class TestPersistent(Persistent):
    """Test persistent object."""

    def __init__(self):
        self.data = {}
        self.timestamp = 0


# Test data
SIMPLE_DICT = {f"key_{i}": f"value_{i}" for i in range(100)}
LARGE_DICT = {f"key_{i}": f"value_{i}" * 10 for i in range(10000)}
LARGE_LIST = [f"item_{i}" * 10 for i in range(10000)]


def test_pickle_serialize_simple_dict(benchmark):
    """Benchmark pickle serialization of simple dict."""
    serializer = PickleSerializer()
    benchmark(serializer.serialize, SIMPLE_DICT)


def test_msgspec_serialize_simple_dict(benchmark):
    """Benchmark msgspec serialization of simple dict."""
    serializer = MsgspecSerializer()
    benchmark(serializer.serialize, SIMPLE_DICT)


def test_pickle_deserialize_simple_dict(benchmark):
    """Benchmark pickle deserialization of simple dict."""
    serializer = PickleSerializer()
    data = serializer.serialize(SIMPLE_DICT)
    benchmark(serializer.deserialize, data)


def test_msgspec_deserialize_simple_dict(benchmark):
    """Benchmark msgspec deserialization of simple dict."""
    serializer = MsgspecSerializer()
    data = serializer.serialize(SIMPLE_DICT)
    benchmark(serializer.deserialize, data)


def test_pickle_serialize_large_dict(benchmark):
    """Benchmark pickle serialization of large dict."""
    serializer = PickleSerializer()
    benchmark(serializer.serialize, LARGE_DICT)


def test_msgspec_serialize_large_dict(benchmark):
    """Benchmark msgspec serialization of large dict."""
    serializer = MsgspecSerializer()
    benchmark(serializer.serialize, LARGE_DICT)


def test_persistent_pickle_roundtrip(benchmark):
    """Benchmark pickle roundtrip for Persistent object."""
    obj = TestPersistent()
    obj.data = LARGE_DICT.copy()
    serializer = PickleSerializer()
    data = serializer.serialize(obj)
    benchmark(lambda: serializer.deserialize(data))


def test_persistent_msgspec_roundtrip(benchmark):
    """Benchmark msgspec roundtrip for Persistent object."""
    obj = TestPersistent()
    obj.data = LARGE_DICT.copy()
    serializer = MsgspecSerializer()
    data = serializer.serialize(obj)
    benchmark(lambda: serializer.deserialize(data))


def test_persistent_dict_pickle(benchmark):
    """Benchmark pickle serialization of PersistentDict."""
    pd = PersistentDict(LARGE_DICT)
    serializer = PickleSerializer()
    benchmark(serializer.serialize, pd)


def test_persistent_dict_msgspec(benchmark):
    """Benchmark msgspec serialization of PersistentDict."""
    pd = PersistentDict(LARGE_DICT)
    serializer = MsgspecSerializer()
    benchmark(serializer.serialize, pd)


def test_serialized_size_comparison_simple(benchmark):
    """Compare serialized sizes for simple dict."""
    pickle_size = len(PickleSerializer().serialize(SIMPLE_DICT))
    msgspec_size = len(MsgspecSerializer().serialize(SIMPLE_DICT))

    assert msgspec_size < pickle_size, "msgspec should be smaller"
    reduction = (1 - msgspec_size / pickle_size) * 100

    # Return for benchmark output
    return {
        'pickle_size': pickle_size,
        'msgspec_size': msgspec_size,
        'reduction_percent': reduction
    }


def test_serialized_size_comparison_large(benchmark):
    """Compare serialized sizes for large dict."""
    pickle_size = len(PickleSerializer().serialize(LARGE_DICT))
    msgspec_size = len(MsgspecSerializer().serialize(LARGE_DICT))

    assert msgspec_size < pickle_size, "msgspec should be smaller"
    reduction = (1 - msgspec_size / pickle_size) * 100

    return {
        'pickle_size': pickle_size,
        'msgspec_size': msgspec_size,
        'reduction_percent': reduction
    }

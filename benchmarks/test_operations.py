"""Benchmarks for core Durus operations."""

import time
import pytest
from dhara.core import Connection
from dhara.storage.base import MemoryStorage
from dhara.collections.dict import PersistentDict
from dhara.core.persistent import Persistent


class Counter(Persistent):
    """Simple counter for testing."""

    def __init__(self):
        self.count = 0


def test_connection_creation(benchmark):
    """Benchmark connection creation."""
    storage = MemoryStorage()
    benchmark(Connection, storage)


def test_root_access(benchmark, memory_connection):
    """Benchmark root object access."""
    benchmark(memory_connection.get_root)


def test_simple_commit(benchmark, memory_connection):
    """Benchmark simple commit."""
    root = memory_connection.get_root()

    def commit():
        root['timestamp'] = time.time()
        memory_connection.commit()

    benchmark(commit)


def test_bulk_insert_100(benchmark, memory_connection):
    """Benchmark bulk insert of 100 objects."""
    root = memory_connection.get_root()

    def bulk_insert():
        for i in range(100):
            root[f'key_{i}'] = f'value_{i}' * 10
        memory_connection.commit()

    benchmark(bulk_insert)


def test_bulk_insert_1000(benchmark, memory_connection):
    """Benchmark bulk insert of 1000 objects."""
    root = memory_connection.get_root()

    def bulk_insert():
        for i in range(1000):
            root[f'key_{i}'] = f'value_{i}' * 10
        memory_connection.commit()

    benchmark(bulk_insert)


def test_persistent_object_creation(benchmark, memory_connection):
    """Benchmark creating persistent objects."""
    root = memory_connection.get_root()

    def create_objects():
        for i in range(100):
            obj = Counter()
            obj.count = i
            root[f'counter_{i}'] = obj
        memory_connection.commit()

    benchmark(create_objects)

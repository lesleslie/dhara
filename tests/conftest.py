"""
pytest configuration and shared fixtures for Durus tests.

This file provides common fixtures used across multiple test files,
migrated from the legacy test/ directory.
"""

from os import unlink
from os.path import exists

import pytest
import pytest_asyncio

from dhara.core import AsyncConnection, Connection
from dhara.storage import AsyncMemoryStorage, MemoryStorage
from dhara.storage.async_file import AsyncFileStorage


@pytest.fixture
def memory_storage():
    return MemoryStorage()


@pytest.fixture
def async_memory_storage():
    return AsyncMemoryStorage()


@pytest.fixture
def temp_file_storage():
    from tempfile import mktemp

    filename = mktemp(suffix=".dhara")
    # ``AsyncFileStorage`` is a path-compatible drop-in for the legacy
    # ``FileStorage``; the legacy SHELF-format class is being removed by
    # the async-first migration.  Tests that consumed ``temp_file_storage``
    # as a sync ``Storage`` instance must now ``await`` its lifecycle;
    # the few call sites in this tree (test_core_connection_methods)
    # adapt to the async shape below.
    storage = AsyncFileStorage(filename)
    yield storage
    if exists(filename):
        unlink(filename)


@pytest.fixture
def connection(memory_storage):
    return Connection(memory_storage)


@pytest_asyncio.fixture
async def async_connection(async_memory_storage):
    """AsyncConnection backed by AsyncMemoryStorage for async tests."""
    return await AsyncConnection.new(async_memory_storage)


@pytest.fixture
def file_connection(temp_file_storage):
    # ``file_connection`` is used by tests that expect a real on-disk
    # store; the new ``AsyncFileStorage`` requires an async init, so the
    # fixture spins up an ``AsyncConnection`` instead of the sync
    # ``Connection`` that the legacy fixture returned.  Callers should
    # ``await async_connection.get_root()`` to interact with the root.
    import asyncio

    async def _open() -> AsyncConnection:
        await temp_file_storage.init()
        return await AsyncConnection.new(temp_file_storage)

    return asyncio.run(_open())


@pytest.fixture
def msgspec_serializer():
    from dhara.serialize import MsgspecSerializer
    return MsgspecSerializer()


@pytest.fixture
def fallback_serializer():
    from dhara.serialize import FallbackSerializer
    return FallbackSerializer()


@pytest.fixture
def temp_storage_dir():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def empty_root(connection):
    return connection.get_root()


@pytest.fixture
def sample_data():
    return {
        "users": {
            "alice": {"email": "alice@example.com", "age": 30},
            "bob": {"email": "bob@example.com", "age": 25},
        },
        "settings": {
            "theme": "dark",
            "language": "en",
        },
    }


@pytest.fixture
def large_dataset():
    return {f"key_{i}": f"value_{i}" * 100 for i in range(1000)}


@pytest.fixture
def persistent_class():
    from dhara import Persistent

    class TestObject(Persistent):
        def __init__(self, value):
            self.value = value

    return TestObject

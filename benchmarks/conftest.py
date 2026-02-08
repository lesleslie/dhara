"""Shared fixtures for benchmarks."""

import os
import tempfile
import pytest
from dhruva.core import Connection
from dhruva.storage.base import MemoryStorage
from dhruva.storage import FileStorage, SqliteStorage
from dhruva.core.persistent import Persistent


@pytest.fixture
def temp_file():
    """Create a temporary file path."""
    fd, path = tempfile.mkstemp(suffix='.durus')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def temp_sqlite_file():
    """Create a temporary SQLite file path."""
    fd, path = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def memory_storage():
    """Create a memory storage."""
    return MemoryStorage()


@pytest.fixture
def file_storage(temp_file):
    """Create a file storage."""
    return FileStorage(temp_file)


@pytest.fixture
def sqlite_storage(temp_sqlite_file):
    """Create a SQLite storage."""
    return SqliteStorage(temp_sqlite_file)


@pytest.fixture
def memory_connection(memory_storage):
    """Create a connection with memory storage."""
    return Connection(memory_storage, cache_size=1000)


@pytest.fixture
def file_connection(file_storage):
    """Create a connection with file storage."""
    return Connection(file_storage, cache_size=1000)


@pytest.fixture
def sqlite_connection(sqlite_storage):
    """Create a connection with SQLite storage."""
    return Connection(sqlite_storage, cache_size=1000)


class TestPersistent(Persistent):
    """Test persistent object for benchmarks."""

    def __init__(self, data=None):
        self.data = data or {}
        self.timestamp = 0
        self.counter = 0

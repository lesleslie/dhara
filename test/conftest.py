"""
pytest configuration and shared fixtures for Durus tests.

This file provides common fixtures used across multiple test files,
replacing the setup methods from the legacy sancho.utest framework.
"""

from os import unlink
from os.path import exists

import pytest

from dhruva.core import Connection
from dhruva.storage import FileStorage, MemoryStorage


@pytest.fixture
def memory_storage():
    """
    Provides a fresh MemoryStorage instance for each test.

    Usage:
        def test_something(memory_storage):
            storage = memory_storage
            # use storage
    """
    return MemoryStorage()


@pytest.fixture
def temp_file_storage():
    """
    Provides a temporary FileStorage instance that is cleaned up after the test.

    The storage file is automatically deleted after the test completes.

    Usage:
        def test_something(temp_file_storage):
            storage = temp_file_storage
            # use storage
            # file is automatically cleaned up
    """
    from tempfile import mktemp

    filename = mktemp(suffix=".durus")
    storage = FileStorage(filename)
    yield storage
    # Cleanup: remove the temporary file
    if exists(filename):
        unlink(filename)


@pytest.fixture
def connection(memory_storage):
    """
    Provides a Connection with MemoryStorage for each test.

    This is the most commonly used fixture for tests that need
    a connection but don't care about the specific storage backend.

    Usage:
        def test_something(connection):
            root = connection.get_root()
            # test root
    """
    return Connection(memory_storage)


@pytest.fixture
def file_connection(temp_file_storage):
    """
    Provides a Connection with FileStorage for tests that need file-based persistence.

    Usage:
        def test_something(file_connection):
            root = file_connection.get_root()
            # test with file storage
    """
    return Connection(temp_file_storage)

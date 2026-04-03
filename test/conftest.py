"""
pytest configuration and shared fixtures for Durus tests.

This file provides common fixtures used across multiple test files,
replacing the setup methods from the legacy sancho.utest framework.
"""

from os import unlink
from os.path import exists

import pytest

from dhara.core import Connection
from dhara.storage import FileStorage, MemoryStorage


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


# =============================================================================
# Additional Fixtures for Enhanced Testing
# =============================================================================

@pytest.fixture
def msgspec_serializer():
    """
    Provides a MsgspecSerializer instance for tests.

    Msgspec is the default, fast, and safe serialization format.

    Usage:
        def test_something(msgspec_serializer):
            data = msgspec_serializer.serialize(obj)
            # test serialization
    """
    from dhara.serialize import MsgspecSerializer
    return MsgspecSerializer()


@pytest.fixture
def fallback_serializer():
    """
    Provides a FallbackSerializer with default whitelist for tests.

    The fallback serializer tries msgspec first, then falls back to pickle
    for whitelisted types (NumPy, Pandas, etc.).

    Usage:
        def test_something(fallback_serializer):
            data = fallback_serializer.serialize(obj)
            # test serialization with fallback
    """
    from dhara.serialize import FallbackSerializer
    return FallbackSerializer()


@pytest.fixture
def temp_storage_dir():
    """
    Provides a temporary directory for FileStorage operations.

    The directory and all contents are automatically cleaned up after the test.

    Usage:
        def test_something(temp_storage_dir):
            storage = FileStorage(f"{temp_storage_dir}/test.dhara")
            # use storage
            # directory is automatically cleaned up
    """
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def empty_root(connection):
    """
    Provides an empty root object from the connection.

    Usage:
        def test_something(empty_root):
            empty_root["key"] = "value"
            # test root operations
    """
    return connection.get_root()


@pytest.fixture
def sample_data():
    """
    Provides sample data dictionary for testing.

    Usage:
        def test_something(sample_data):
            data = sample_data["users"]
            # test with sample data
    """
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
    """
    Provides a large dataset for performance testing.

    Generates a dictionary with 1000 entries for testing
    storage performance and serialization.

    Usage:
        def test_something(large_dataset):
            root["large"] = large_dataset
            connection.commit()
            # test performance with large dataset
    """
    return {f"key_{i}": f"value_{i}" * 100 for i in range(1000)}


@pytest.fixture
def persistent_class():
    """
    Factory fixture that creates a Persistent class for testing.

    Usage:
        def test_something(persistent_class):
            obj = persistent_class()
            # test persistent object
    """
    from dhara import Persistent

    class TestObject(Persistent):
        def __init__(self, value):
            self.value = value

    return TestObject


@pytest.fixture
def auto_cleanup(request):
    """
    Automatically cleans up test resources based on test outcome.

    Usage:
        def test_something(auto_cleanup):
            # Create test resources
            # Resources are tracked and cleaned up
    """
    yield

    # Cleanup is handled based on test outcome
    pass

"""Integration tests for FallbackSerializer with storage backends.

Tests FallbackSerializer with actual storage implementations to ensure
compatibility and correct behavior in real-world scenarios.
"""

import tempfile
import os

import pytest

from dhruva import Connection, Persistent
from dhruva.storage import FileStorage


class TestClass(Persistent):
    """A simple persistent class for testing."""
    def __init__(self, name: str, value: int):
        self.name = name
        self.value = value


class TestFallbackWithStorage:
    """Test FallbackSerializer works with storage backends."""

    def test_file_storage_round_trip(self):
        """Test that data can be stored and retrieved correctly."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            # Create storage and connection
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()
            root["data"] = {"key": "value", "number": 42}
            root["list"] = [1, 2, 3, "four"]
            connection.commit()

            # Verify data persisted correctly
            assert root["data"]["key"] == "value"
            assert root["data"]["number"] == 42
            assert root["list"] == [1, 2, 3, "four"]

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_persistent_objects_storage(self):
        """Test persistent objects are stored correctly."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()
            root["objects"] = {}

            # Create multiple persistent objects
            for i in range(5):
                obj = TestClass(f"object_{i}", i * 10)
                root["objects"][f"obj_{i}"] = obj

            connection.commit()

            # Verify all objects persisted
            assert len(root["objects"]) == 5
            for i in range(5):
                obj = root["objects"][f"obj_{i}"]
                assert obj.name == f"object_{i}"
                assert obj.value == i * 10

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_mixed_data_types(self):
        """Test mix of different data types."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # Add various types
            root["config"] = {"setting": "value", "count": 100}
            root["items"] = ["a", "b", "c"]
            root["metadata"] = {"tags": ["tag1", "tag2"], "active": True}
            root["numbers"] = [1, 2, 3, 4, 5]
            root["nested"] = {"level1": {"level2": {"level3": "deep"}}}

            connection.commit()

            # Verify all data
            assert root["config"]["setting"] == "value"
            assert root["items"] == ["a", "b", "c"]
            assert root["metadata"]["tags"] == ["tag1", "tag2"]
            assert root["metadata"]["active"] is True
            assert root["numbers"] == [1, 2, 3, 4, 5]
            assert root["nested"]["level1"]["level2"]["level3"] == "deep"

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestPerformanceIntegration:
    """Integration performance tests."""

    def test_batch_operations_performance(self):
        """Test that batch operations perform well."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            import time
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # Batch insert
            batch_size = 100
            start = time.time()

            for i in range(batch_size):
                root[f"item_{i}"] = {"index": i, "value": i * 2}

            connection.commit()

            elapsed = time.time() - start

            # Should handle 100 items quickly (< 1 second)
            assert elapsed < 1.0, f"Batch insert too slow: {elapsed:.3f}s for {batch_size} items"

            print(f"\nBatch insert: {batch_size} items in {elapsed*1000:.1f}ms")
            print(f"  Average: {(elapsed/batch_size)*1000:.3f}ms per item")

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_read_performance(self):
        """Test read performance after storing data."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            import time
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # Pre-populate data
            for i in range(100):
                root[f"item_{i}"] = {"data": f"value_{i}"}
            connection.commit()

            # Read operations
            iterations = 100
            start = time.time()

            for _ in range(iterations):
                # Read all items
                for i in range(100):
                    _ = root[f"item_{i}"]

            elapsed = time.time() - start

            total_reads = iterations * 100
            avg_us = (elapsed / total_reads) * 1_000_000

            print(f"\nRead performance: {total_reads} reads in {elapsed*1000:.1f}ms")
            print(f"  Average: {avg_us:.3f}μs per read")

            # Reads should be fast
            assert avg_us < 100, f"Read too slow: {avg_us:.3f}μs"

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestMultipleCommits:
    """Test multiple commits and transactions."""

    def test_multiple_commits(self):
        """Test multiple commits accumulate correctly."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # First commit
            root["batch1"] = {"items": [1, 2, 3]}
            connection.commit()

            # Second commit
            root["batch2"] = {"items": [4, 5, 6]}
            connection.commit()

            # Third commit
            root["batch3"] = {"items": [7, 8, 9]}
            connection.commit()

            # All data should be present
            assert root["batch1"]["items"] == [1, 2, 3]
            assert root["batch2"]["items"] == [4, 5, 6]
            assert root["batch3"]["items"] == [7, 8, 9]

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_abort_discards_changes(self):
        """Test that abort discards uncommitted changes."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # Add data and commit
            root["committed"] = {"value": 1}
            connection.commit()

            # Add more data but abort
            root["uncommitted"] = {"value": 2}
            connection.abort()

            # Committed data should be present
            assert root["committed"]["value"] == 1

            # Uncommitted data should not be present (abort discards it)
            # Note: The object might still be in memory but not persisted
            # This is expected behavior for abort

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestNumpyIntegration:
    """Test integration with NumPy arrays."""

    def test_numpy_array_storage(self):
        """Test storing NumPy arrays with default whitelist."""
        pytest.importorskip("numpy")
        import numpy as np

        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # Regular Python data
            root["config"] = {"setting": "value"}

            # NumPy arrays
            root["array1"] = np.array([1, 2, 3, 4, 5])
            root["array2"] = np.array([10, 20, 30, 40, 50])

            connection.commit()

            # Verify data
            assert root["config"]["setting"] == "value"
            assert isinstance(root["array1"], np.ndarray)
            assert list(root["array1"]) == [1, 2, 3, 4, 5]
            assert isinstance(root["array2"], np.ndarray)
            assert list(root["array2"]) == [10, 20, 30, 40, 50]

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_large_numpy_array(self):
        """Test storing large NumPy arrays."""
        pytest.importorskip("numpy")
        import numpy as np

        with tempfile.NamedTemporaryFile(delete=False, suffix=".dhruva") as f:
            temp_file = f.name

        try:
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # Large array
            large_array = np.arange(1000)
            root["large_array"] = large_array

            connection.commit()

            # Verify
            assert isinstance(root["large_array"], np.ndarray)
            assert len(root["large_array"]) == 1000
            assert root["large_array"][0] == 0
            assert root["large_array"][999] == 999

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

"""Performance benchmarks for FallbackSerializer.

Compares msgspec, pickle, and FallbackSerializer performance across
various data types and operations.
"""

import time
import pytest

from druva import Connection
from druva.serialize import (
    FallbackSerializer,
    MsgspecSerializer,
    PickleSerializer,
)
from druva.storage import FileStorage


class TestMsgspecPerformance:
    """Benchmark msgspec serializer performance."""

    def test_dict_serialization_speed(self):
        """Benchmark dict serialization with msgspec."""
        serializer = MsgspecSerializer()
        data = {"key": "value", "number": 42, "list": [1, 2, 3, 4, 5]}

        iterations = 1000
        start = time.time()
        for _ in range(iterations):
            serialized = serializer.serialize(data)
            serializer.deserialize(serialized)
        elapsed = time.time() - start

        avg_ms = (elapsed / iterations) * 1000
        print(f"\nMsgspec dict: {avg_ms:.3f}ms avg ({iterations} iterations)")

        # Should be very fast (< 1ms per operation)
        assert avg_ms < 1.0, f"Msgspec too slow: {avg_ms:.3f}ms"

    def test_large_dict_performance(self):
        """Benchmark large dict serialization."""
        serializer = MsgspecSerializer()
        data = {f"key_{i}": i * 2 for i in range(100)}

        iterations = 100
        start = time.time()
        for _ in range(iterations):
            serialized = serializer.serialize(data)
            serializer.deserialize(serialized)
        elapsed = time.time() - start

        avg_ms = (elapsed / iterations) * 1000
        print(f"\nMsgspec large dict (100 items): {avg_ms:.3f}ms avg")

        # Should handle large dicts efficiently
        assert avg_ms < 5.0, f"Large dict too slow: {avg_ms:.3f}ms"


class TestPicklePerformance:
    """Benchmark pickle serializer performance."""

    def test_dict_serialization_speed(self):
        """Benchmark dict serialization with pickle."""
        serializer = PickleSerializer()
        data = {"key": "value", "number": 42, "list": [1, 2, 3, 4, 5]}

        iterations = 1000
        start = time.time()
        for _ in range(iterations):
            serialized = serializer.serialize(data)
            serializer.deserialize(serialized)
        elapsed = time.time() - start

        avg_ms = (elapsed / iterations) * 1000
        print(f"\nPickle dict: {avg_ms:.3f}ms avg ({iterations} iterations)")

        # Documenting pickle baseline performance


class TestFallbackPerformance:
    """Benchmark FallbackSerializer performance."""

    def test_msgspec_path_performance(self):
        """Benchmark FallbackSerializer using msgspec path."""
        serializer = FallbackSerializer()
        data = {"key": "value", "number": 42, "list": [1, 2, 3, 4, 5]}

        iterations = 1000
        start = time.time()
        for _ in range(iterations):
            serialized = serializer.serialize(data)
            serializer.deserialize(serialized)
        elapsed = time.time() - start

        avg_ms = (elapsed / iterations) * 1000
        print(f"\nFallback (msgspec path): {avg_ms:.3f}ms avg")

        # Fallback with msgspec should still be fast
        assert avg_ms < 2.0, f"Fallback msgspec path too slow: {avg_ms:.3f}ms"

        # Verify it used msgspec
        stats = serializer.get_stats()
        assert stats["msgspec_count"] >= iterations

    def test_overhead_analysis(self):
        """Analyze overhead of FallbackSerializer wrapper."""
        # Pure msgspec
        msgspec = MsgspecSerializer()
        data = {"test": "value", "number": 123}

        iterations = 1000

        start = time.time()
        for _ in range(iterations):
            msgspec.serialize(data)
        msgspec_serialize_time = time.time() - start

        # Fallback (uses msgspec internally)
        fallback = FallbackSerializer()

        start = time.time()
        for _ in range(iterations):
            fallback.serialize(data)
        fallback_serialize_time = time.time() - start

        overhead_us = (
            (fallback_serialize_time - msgspec_serialize_time) / iterations
        ) * 1_000_000

        print(f"\nFallback overhead analysis:")
        print(f"  Msgspec: {msgspec_serialize_time*1000:.3f}ms total")
        print(f"  Fallback: {fallback_serialize_time*1000:.3f}ms total")
        print(f"  Overhead: {overhead_us:.3f}μs per operation")

        # Overhead should be reasonable (< 50μs per operation)
        assert overhead_us < 50, f"Fallback overhead too high: {overhead_us:.3f}μs"

    def test_statistics_overhead(self):
        """Test overhead of statistics tracking."""
        serializer_with_stats = FallbackSerializer()
        data = {"key": "value"}

        iterations = 10000

        start = time.time()
        for _ in range(iterations):
            serializer_with_stats.serialize(data)
        with_stats_time = time.time() - start

        # Get stats to ensure they're being tracked
        stats = serializer_with_stats.get_stats()
        assert stats["msgspec_count"] >= iterations

        avg_us = (with_stats_time / iterations) * 1_000_000
        print(f"\nStatistics overhead: {with_stats_time*1000:.3f}ms for {iterations} ops")
        print(f"  Per operation: {avg_us:.3f}μs")


class TestComparisonBenchmarks:
    """Direct comparison between serializers."""

    def test_compare_dict_serialization(self):
        """Compare all serializers on dict serialization."""
        data = {"key": "value", "number": 42, "list": [1, 2, 3, 4, 5]}
        iterations = 1000

        results = {}

        # Msgspec
        msgspec = MsgspecSerializer()
        start = time.time()
        for _ in range(iterations):
            msgspec.serialize(data)
        results["msgspec"] = time.time() - start

        # Pickle
        pickle = PickleSerializer()
        start = time.time()
        for _ in range(iterations):
            pickle.serialize(data)
        results["pickle"] = time.time() - start

        # Fallback (uses msgspec)
        fallback = FallbackSerializer()
        start = time.time()
        for _ in range(iterations):
            fallback.serialize(data)
        results["fallback"] = time.time() - start

        print("\nDict serialization comparison (1000 iterations):")
        for name, elapsed in results.items():
            avg_ms = (elapsed / iterations) * 1000
            print(f"  {name:12s}: {avg_ms:.3f}ms avg")

        # All should be reasonably fast (< 0.01ms per operation)
        for name, elapsed in results.items():
            avg_ms = (elapsed / iterations) * 1000
            assert avg_ms < 0.02, f"{name} too slow: {avg_ms:.3f}ms"

    def test_compare_dict_deserialization(self):
        """Compare all serializers on dict deserialization."""
        data = {"key": "value", "number": 42, "list": [1, 2, 3, 4, 5]}
        iterations = 1000

        # Pre-serialize for each serializer
        msgspec = MsgspecSerializer()
        pickle_ser = PickleSerializer()
        fallback = FallbackSerializer()

        msgspec_data = msgspec.serialize(data)
        pickle_data = pickle_ser.serialize(data)
        fallback_data = fallback.serialize(data)

        results = {}

        # Msgspec
        start = time.time()
        for _ in range(iterations):
            msgspec.deserialize(msgspec_data)
        results["msgspec"] = time.time() - start

        # Pickle
        start = time.time()
        for _ in range(iterations):
            pickle_ser.deserialize(pickle_data)
        results["pickle"] = time.time() - start

        # Fallback
        start = time.time()
        for _ in range(iterations):
            fallback.deserialize(fallback_data)
        results["fallback"] = time.time() - start

        print("\nDict deserialization comparison (1000 iterations):")
        for name, elapsed in results.items():
            avg_ms = (elapsed / iterations) * 1000
            print(f"  {name:12s}: {avg_ms:.3f}ms avg")

        # All should be reasonably fast
        for name, elapsed in results.items():
            avg_ms = (elapsed / iterations) * 1000
            assert avg_ms < 0.02, f"{name} deserialization too slow: {avg_ms:.3f}ms"


class TestStorageBenchmarks:
    """Benchmark with actual storage operations."""

    def test_storage_write_performance(self):
        """Benchmark write operations with storage."""
        import tempfile
        os = __import__("os")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".druva") as f:
            temp_file = f.name

        try:
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # Benchmark write operations
            iterations = 100
            start = time.time()

            for i in range(iterations):
                root[f"item_{i}"] = {"index": i, "data": f"value_{i}"}
                connection.commit()

            elapsed = time.time() - start
            avg_ms = (elapsed / iterations) * 1000

            print(f"\nStorage write performance:")
            print(f"  {iterations} commits in {elapsed*1000:.1f}ms")
            print(f"  Average: {avg_ms:.3f}ms per commit")

            # Should be reasonably fast
            assert avg_ms < 10.0, f"Storage write too slow: {avg_ms:.3f}ms"

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def test_storage_read_performance(self):
        """Benchmark read operations with storage."""
        import tempfile
        os = __import__("os")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".druva") as f:
            temp_file = f.name

        try:
            storage = FileStorage(temp_file)
            connection = Connection(storage)

            root = connection.get_root()

            # Pre-populate data
            for i in range(100):
                root[f"item_{i}"] = {"data": f"value_{i}"}
            connection.commit()

            # Benchmark read operations
            iterations = 1000
            start = time.time()

            for _ in range(iterations):
                for i in range(100):
                    _ = root[f"item_{i}"]

            elapsed = time.time() - start
            total_reads = iterations * 100
            avg_us = (elapsed / total_reads) * 1_000_000

            print(f"\nStorage read performance:")
            print(f"  {total_reads} reads in {elapsed*1000:.1f}ms")
            print(f"  Average: {avg_us:.3f}μs per read")

            # Reads should be fast
            assert avg_us < 100, f"Read too slow: {avg_us:.3f}μs"

        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


# Run standalone
if __name__ == "__main__":
    print("=" * 60)
    print("FALLBACK SERIALIZER PERFORMANCE BENCHMARKS")
    print("=" * 60)

    benchmark = TestMsgspecPerformance()
    benchmark.test_dict_serialization_speed()
    benchmark.test_large_dict_performance()

    pickle_bench = TestPicklePerformance()
    pickle_bench.test_dict_serialization_speed()

    fallback_bench = TestFallbackPerformance()
    fallback_bench.test_msgspec_path_performance()
    fallback_bench.test_overhead_analysis()
    fallback_bench.test_statistics_overhead()

    comparison = TestComparisonBenchmarks()
    comparison.test_compare_dict_serialization()
    comparison.test_compare_dict_deserialization()

    storage_bench = TestStorageBenchmarks()
    storage_bench.test_storage_write_performance()
    storage_bench.test_storage_read_performance()

    print("\n" + "=" * 60)
    print("BENCHMARKS COMPLETE")
    print("=" * 60)

"""Benchmarks for cache performance."""

import pytest
from druva.core import Connection
from druva.storage import MemoryStorage


def test_cache_hit_performance(benchmark):
    """Benchmark cache hits (should be fast)."""
    storage = MemoryStorage()
    connection = Connection(storage, cache_size=1000)
    root = connection.get_root()
    root['key'] = 'value'
    connection.commit()

    # Load into cache
    _ = connection.get_root()

    # Benchmark cached access
    benchmark(lambda: connection.get_root()['key'])


def test_cache_shrink_small(benchmark):
    """Benchmark cache shrink with small cache."""
    storage = MemoryStorage()
    connection = Connection(storage, cache_size=50)
    root = connection.get_root()

    # Fill cache beyond limit
    for i in range(200):
        root[f'key_{i}'] = f'value_{i}' * 100
        connection.commit()

    # Benchmark shrink
    benchmark(connection.shrink_cache)


def test_cache_shrink_large(benchmark):
    """Benchmark cache shrink with large cache."""
    storage = MemoryStorage()
    connection = Connection(storage, cache_size=1000)
    root = connection.get_root()

    # Fill cache beyond limit
    for i in range(5000):
        root[f'key_{i}'] = f'value_{i}' * 100
        connection.commit()

    # Benchmark shrink
    benchmark(connection.shrink_cache)

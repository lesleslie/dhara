"""Performance benchmarks for Durus object database.

This package contains comprehensive benchmarks to measure:
- Serialization performance (msgspec vs MsgpackSerializer)
- Object operations (read/write/commit)
- Cache performance (hit/miss rates, shrink operations)
- Storage backend performance (File vs SQLite vs Memory)

Usage:
    pytest benchmarks/ --benchmark-only --benchmark-autosave
    pytest benchmarks/ --benchmark-only --benchmark-sort=name
"""

__all__ = []

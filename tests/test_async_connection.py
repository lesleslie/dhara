"""
Tests for AsyncConnection in dhara.core.connection.

These tests verify the async connection class works correctly with AsyncStorage
implementations like AsyncMemoryStorage.
"""

from __future__ import annotations

import pytest

import asyncio

import pytest
from dhara.core.connection import AsyncConnection
from dhara.storage.memory import AsyncMemoryStorage
from dhara.storage.memory import AsyncMemoryStorage
from dhara.storage.sqlite import AsyncSqliteStorage


@pytest.fixture
async def storage() -> AsyncMemoryStorage:
    """Create and initialize an AsyncMemoryStorage instance."""
    s = AsyncMemoryStorage()
    await s.init()
    yield s
    await s.close()


@pytest.fixture
async def conn(storage: AsyncMemoryStorage) -> AsyncConnection:
    """Create and return an AsyncConnection with initialized storage."""
    return await AsyncConnection.new(storage)


@pytest.mark.asyncio
async def test_async_connection_get_set():
    """Test basic get/set operations on AsyncConnection."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        root = await conn.get_root()
        root["key"] = "value"
        await conn.commit()

        # Verify the value was committed
        loaded = await conn.get(root._p_oid)
        assert loaded is not None
        assert loaded.get("key") == "value"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_abort():
    """Test that abort clears changes and increments transaction serial."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        root = await conn.get_root()

        # Manually record a change (since sync __setitem__ can't await async note_change)
        await conn.note_change(root)
        assert root._p_oid in conn.changed

        # Abort should clear changes
        await conn.abort()
        assert root._p_oid not in conn.changed

        # Transaction serial should be incremented
        serial = await conn.get_transaction_serial()
        assert serial >= 1
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_get_crawler():
    """Test that get_crawler returns objects from storage."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        root = await conn.get_root()

        # Manually record the change since sync __setitem__ can't await async note_change
        await conn.note_change(root)
        await conn.commit()

        # Crawl and verify we get at least the root object
        crawled = []
        async for obj in conn.get_crawler():
            crawled.append(obj)
        assert len(crawled) >= 1
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_pack():
    """Test that pack executes without error."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        # Pack should not raise
        await conn.pack()
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_factory_returns_instance():
    """Test that AsyncConnection.new returns a properly initialized instance."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        assert conn is not None
        assert conn.storage is storage
        assert conn.root is not None
        # Root should be a PersistentDict
        assert hasattr(conn.root, "data")
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_get_storage():
    """Test get_storage returns the underlying storage."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        retrieved_storage = await conn.get_storage()
        assert retrieved_storage is storage
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_get_cache_count():
    """Test get_cache_count returns the number of cached objects."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        count = await conn.get_cache_count()
        assert count >= 1  # At least the root object
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_get_cache_size():
    """Test get_cache_size returns the configured cache size."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage, cache_size=50000)
        size = await conn.get_cache_size()
        assert size == 50000
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_set_cache_size():
    """Test set_cache_size updates the cache size."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage, cache_size=100000)
        await conn.set_cache_size(200000)
        size = await conn.get_cache_size()
        assert size == 200000
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_get_transaction_serial():
    """Test get_transaction_serial returns the transaction count."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        initial_serial = await conn.get_transaction_serial()
        assert initial_serial >= 0

        # Commit should increment the serial
        root = await conn.get_root()
        root["txn_key"] = "txn_value"
        await conn.commit()

        new_serial = await conn.get_transaction_serial()
        assert new_serial > initial_serial
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_get_root():
    """Test get_root returns the root object."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        root = await conn.get_root()
        assert root is not None
        assert root._p_oid is not None
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_note_access_and_change():
    """Test note_access and note_change update object state."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        root = await conn.get_root()

        # note_change should add to changed dict
        await conn.note_change(root)
        assert root._p_oid in conn.changed

        # After commit, changed should be cleared
        await conn.commit()
        assert root._p_oid not in conn.changed
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_shrink_cache():
    """Test shrink_cache executes without error."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage, cache_size=10)
        # Add some objects
        root = await conn.get_root()
        for i in range(20):
            root[f"shrink_key{i}"] = f"value{i}"
        await conn.commit()

        # Shrink should not raise
        await conn.shrink_cache()
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_commit_increments_serial():
    """Test that commit increments transaction_serial."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        serial_before = await conn.get_transaction_serial()

        root = await conn.get_root()
        root["commit_test"] = "value"
        await conn.commit()

        serial_after = await conn.get_transaction_serial()
        assert serial_after == serial_before + 1
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_abort_increments_serial():
    """Test that abort increments transaction_serial."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        serial_before = await conn.get_transaction_serial()

        root = await conn.get_root()
        root["abort_test"] = "value"
        await conn.abort()

        serial_after = await conn.get_transaction_serial()
        assert serial_after == serial_before + 1
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_get_load_count():
    """Test get_load_count returns the number of times objects were loaded."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)
        initial_count = await conn.get_load_count()

        # Access the root, which should increment load count
        root = await conn.get_root()
        _ = root._p_oid  # Force access

        # Load count may or may not increase depending on cache state
        count = await conn.get_load_count()
        assert count >= initial_count
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_with_multiple_transactions():
    """Test multiple commit/abort cycles."""
    storage = AsyncMemoryStorage()
    await storage.init()
    try:
        conn = await AsyncConnection.new(storage)

        # First transaction
        root = await conn.get_root()
        root["txn1"] = "value1"
        await conn.commit()

        # Second transaction
        root["txn2"] = "value2"
        await conn.commit()

        # Verify both values persist
        root_reloaded = await conn.get_root()
        assert root_reloaded.get("txn1") == "value1"
        assert root_reloaded.get("txn2") == "value2"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_async_connection_race_on_empty_storage(tmp_path):
    """Concurrent AsyncConnection.new() on empty storage must not corrupt state."""
    db_path = str(tmp_path / "test_init_race.db")
    storage = AsyncSqliteStorage(url=f"sqlite+aiosqlite://{db_path}")
    await storage.init()

    async def create_connection() -> AsyncConnection:
        return await AsyncConnection.new(storage)

    # Spawn 10 connections concurrently on empty storage
    results = await asyncio.gather(*[create_connection() for _ in range(10)])

    # Verify all connections have valid root
    roots = [conn.root for conn in results]
    assert all(root is not None for root in roots)

    # Verify root OID is consistent (ROOT_OID = "\x00\x00\x00\x00\x00\x00\x00\x00")
    from dhara.core.connection import ROOT_OID
    for conn in results:
        assert conn.root._p_oid == ROOT_OID

    # Cleanup
    for conn in results:
        await conn.abort()
    await storage.close()

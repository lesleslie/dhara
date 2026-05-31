"""
Tests for async methods on PersistentObject (Task 8).

These tests verify that the async wrapper methods on PersistentObject
work correctly with AsyncConnection.

Note: The abort behavior tests reveal a deeper issue with async integration -
when note_change is a coroutine, it gets scheduled but may not complete before
abort checks the changed dict. This is a known limitation of the current
_async wrapping approach.
"""

import pytest

from dhara.storage.memory import AsyncMemoryStorage
from dhara.core.connection import AsyncConnection


@pytest.mark.asyncio
async def test_async_persistent_object_commit_async():
    """Test _p_commit_async persists changes correctly."""
    storage = AsyncMemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    root["key"] = "value"
    await root._p_commit_async()
    # Use sync access for committed values
    assert root["key"] == "value"
    # Or use _p_get_async for async-safe access
    value = await root._p_get_async("key")
    assert value == "value"


@pytest.mark.asyncio
async def test_async_persistent_object_get_async():
    """Test _p_get_async retrieves values correctly."""
    storage = AsyncMemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    root["key"] = "value"
    await root._p_commit_async()
    value = await root._p_get_async("key")
    assert value == "value"


@pytest.mark.asyncio
async def test_async_persistent_object_get_async_default():
    """Test _p_get_async returns default for missing keys."""
    storage = AsyncMemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    value = await root._p_get_async("nonexistent", "default")
    assert value == "default"


@pytest.mark.asyncio
async def test_async_persistent_object_set_async():
    """Test _p_set_async sets values correctly."""
    storage = AsyncMemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    await root._p_set_async("key", "value")
    await root._p_commit_async()
    # Use sync access for committed values
    assert root["key"] == "value"


@pytest.mark.asyncio
async def test_async_persistent_object_set_async_multiple():
    """Test _p_set_async with multiple keys."""
    storage = AsyncMemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    await root._p_set_async("key1", "value1")
    await root._p_set_async("key2", "value2")
    await root._p_commit_async()
    assert root["key1"] == "value1"
    assert root["key2"] == "value2"


@pytest.mark.asyncio
async def test_async_persistent_object_get_after_commit():
    """Test _p_get_async works after multiple commits."""
    storage = AsyncMemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()

    root["a"] = 1
    await root._p_commit_async()

    root["b"] = 2
    await root._p_commit_async()

    # Both values should be accessible
    assert await root._p_get_async("a") == 1
    assert await root._p_get_async("b") == 2
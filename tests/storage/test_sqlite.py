"""Tests for AsyncSqliteStorage using aiosqlite."""

import asyncio
import os
import pytest
from dhara.storage.sqlite import AsyncSqliteStorage


@pytest.mark.asyncio
async def test_async_sqlite_storage_load_store():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    oid = await storage.new_oid()
    await storage.begin()
    await storage.store(oid, b"test record data")
    await storage.end()
    result = await storage.load(oid)
    assert result == b"test record data"


@pytest.mark.asyncio
async def test_async_sqlite_storage_health():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    assert await storage.health() is True


@pytest.mark.asyncio
async def test_async_sqlite_storage_close():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    await storage.close()


@pytest.mark.asyncio
async def test_async_sqlite_storage_gen_oid_record():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()
    await storage.begin()
    await storage.store(oid1, b"record1")
    await storage.store(oid2, b"record2")
    await storage.end()
    records = [r async for r in storage.gen_oid_record()]
    assert len(records) == 2


@pytest.mark.asyncio
async def test_async_sqlite_storage_context_manager():
    async with AsyncSqliteStorage(":memory:") as storage:
        oid = await storage.new_oid()
        await storage.begin()
        await storage.store(oid, b"context manager test")
        await storage.end()
        result = await storage.load(oid)
        assert result == b"context manager test"


@pytest.mark.asyncio
async def test_async_sqlite_storage_sync():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    oid = await storage.new_oid()
    await storage.begin()
    await storage.store(oid, b"sync test")
    await storage.end()
    invalidations = await storage.sync()
    # sync returns list of invalidated OIDs (empty if none)
    assert isinstance(invalidations, list)


@pytest.mark.asyncio
async def test_async_sqlite_storage_bulk_load():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()
    await storage.begin()
    await storage.store(oid1, b"bulk1")
    await storage.store(oid2, b"bulk2")
    await storage.end()
    results = [r async for r in storage.bulk_load([oid1, oid2])]
    assert len(results) == 2
    assert results[0] == b"bulk1"
    assert results[1] == b"bulk2"


@pytest.mark.asyncio
async def test_async_sqlite_storage_multiple_transactions():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()

    # First transaction
    oid1 = await storage.new_oid()
    await storage.begin()
    await storage.store(oid1, b"tx1")
    await storage.end()

    # Second transaction
    oid2 = await storage.new_oid()
    await storage.begin()
    await storage.store(oid2, b"tx2")
    await storage.end()

    assert await storage.load(oid1) == b"tx1"
    assert await storage.load(oid2) == b"tx2"


@pytest.mark.asyncio
async def test_new_oid_is_unique_under_concurrent_access(tmp_path):
    """Multiple concurrent new_oid() calls must return unique OIDs."""
    db_path = tmp_path / "test_atomic_oid.db"
    # Use file-based database, not :memory:, to ensure real I/O
    storage = AsyncSqliteStorage(url=f"sqlite+aiosqlite://{db_path}")
    await storage.init()

    async def generate_oids(count: int) -> set[str]:
        oids = set()
        for _ in range(count):
            oid = await storage.new_oid()
            oids.add(oid)
            # Yield control to allow interleaving with other tasks
            await asyncio.sleep(0)
        return oids

    # Generate 200 OIDs concurrently (100 each from two tasks)
    # Higher count and explicit sleep to encourage race conditions
    results = await asyncio.gather(
        generate_oids(100),
        generate_oids(100),
    )
    all_oids = results[0] | results[1]

    # Must have 200 unique OIDs — no collisions
    assert len(all_oids) == 200, f"OID collision detected: {200 - len(all_oids)} duplicates"

    await storage.close()
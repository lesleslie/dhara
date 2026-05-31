# tests/storage/test_postgres.py
import pytest
from dhara.storage.postgres import AsyncPostgresStorage

@pytest.mark.asyncio
async def test_async_postgres_storage_load_store():
    storage = AsyncPostgresStorage("postgresql://localhost/testdb")
    await storage.init()
    oid = await storage.new_oid()
    await storage.begin()
    await storage.store(oid, b"test record data")
    await storage.end()
    result = await storage.load(oid)
    assert result == b"test record data"

@pytest.mark.asyncio
async def test_async_postgres_storage_connection_pool():
    storage = AsyncPostgresStorage("postgresql://localhost/testdb", min_size=2, max_size=5)
    await storage.init()
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()
    await storage.begin()
    await storage.store(oid1, b"data1")
    await storage.store(oid2, b"data2")
    await storage.end()
    assert await storage.health() is True

@pytest.mark.asyncio
async def test_async_postgres_storage_close():
    storage = AsyncPostgresStorage("postgresql://localhost/testdb")
    await storage.init()
    await storage.close()

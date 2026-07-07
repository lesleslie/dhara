# tests/storage/test_postgres.py
#
# These tests exercise AsyncPostgresStorage end-to-end against a real
# PostgreSQL instance (database "testdb"). The backend itself is not
# yet implemented — dhara.mcp.server_core.__init__ raises
# NotImplementedError when storage_backend == "postgres". These tests
# are skipped until:
#
#   1. The PostgreSQL storage backend lands (see dhara/storage/postgres.py).
#   2. A CI fixture provides a `testdb` database for pytest to connect to.
#
# Track the unimplemented backend in dhara/mcp/server_core.py and the
# asyncpg fixture requirement in the test infra before un-skipping.

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "PostgreSQL storage backend is not yet implemented and these "
        "tests require a real 'testdb' database. See "
        "dhara/storage/postgres.py and dhara/mcp/server_core.py."
    )
)


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
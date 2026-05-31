"""
Tests for AsyncMemoryStorage.
"""

from __future__ import annotations

import pytest

from dhara.storage.memory import AsyncMemoryStorage


@pytest.fixture
async def storage() -> AsyncMemoryStorage:
    """Create and initialize an AsyncMemoryStorage instance."""
    s = AsyncMemoryStorage()
    await s.init()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_init(storage: AsyncMemoryStorage) -> None:
    """Test that init is a no-op and storage is ready."""
    await storage.init()
    assert storage.records == {}
    assert storage.transaction is None
    assert storage.oid == -1


@pytest.mark.asyncio
async def test_new_oid(storage: AsyncMemoryStorage) -> None:
    """Test OID generation."""
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()
    oid3 = await storage.new_oid()

    assert oid1 != oid2 != oid3
    # OIDs should be consecutive integers as bytes
    assert oid1 == b"\x00\x00\x00\x00\x00\x00\x00\x00"
    assert oid2 == b"\x00\x00\x00\x00\x00\x00\x00\x01"
    assert oid3 == b"\x00\x00\x00\x00\x00\x00\x00\x02"


@pytest.mark.asyncio
async def test_begin_commit_cycle(storage: AsyncMemoryStorage) -> None:
    """Test transaction begin/store/end cycle."""
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()

    record1 = b"record1_data"
    record2 = b"record2_data"

    await storage.begin()
    await storage.store(oid1, record1)
    await storage.store(oid2, record2)
    await storage.end()

    assert storage.records[oid1] == record1
    assert storage.records[oid2] == record2
    assert storage.transaction is None


@pytest.mark.asyncio
async def test_load_existing_oid(storage: AsyncMemoryStorage) -> None:
    """Test loading an existing record."""
    oid = await storage.new_oid()
    record = b"test_record"

    await storage.begin()
    await storage.store(oid, record)
    await storage.end()

    loaded = await storage.load(oid)
    assert loaded == record


@pytest.mark.asyncio
async def test_load_missing_oid_raises(storage: AsyncMemoryStorage) -> None:
    """Test that loading a missing OID raises KeyError."""
    with pytest.raises(KeyError):
        await storage.load(b"\x00\x00\x00\x00\x00\x00\x00\xff")


@pytest.mark.asyncio
async def test_sync_returns_empty_list(storage: AsyncMemoryStorage) -> None:
    """Test that sync returns an empty list (no invalidations)."""
    result = await storage.sync()
    assert result == []


@pytest.mark.asyncio
async def test_gen_oid_record(storage: AsyncMemoryStorage) -> None:
    """Test generating all oid-record pairs."""
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()
    record1 = b"data1"
    record2 = b"data2"

    await storage.begin()
    await storage.store(oid1, record1)
    await storage.store(oid2, record2)
    await storage.end()

    results = []
    async for oid, record in storage.gen_oid_record():
        results.append((oid, record))

    assert len(results) == 2
    assert (oid1, record1) in results
    assert (oid2, record2) in results


@pytest.mark.asyncio
async def test_bulk_load(storage: AsyncMemoryStorage) -> None:
    """Test bulk loading multiple OIDs."""
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()
    oid3 = await storage.new_oid()
    record1 = b"data1"
    record2 = b"data2"

    await storage.begin()
    await storage.store(oid1, record1)
    await storage.store(oid2, record2)
    # oid3 has no record
    await storage.end()

    oids = [oid1, oid2, oid3]
    results = []
    async for record in storage.bulk_load(oids):
        results.append(record)

    assert len(results) == 2
    assert record1 in results
    assert record2 in results


@pytest.mark.asyncio
async def test_pack_is_noop(storage: AsyncMemoryStorage) -> None:
    """Test that pack is a no-op for memory storage."""
    oid = await storage.new_oid()
    record = b"data"
    await storage.begin()
    await storage.store(oid, record)
    await storage.end()

    await storage.pack()
    # Record should still be there (pack doesn't remove anything)
    assert storage.records[oid] == record


@pytest.mark.asyncio
async def test_health_returns_true(storage: AsyncMemoryStorage) -> None:
    """Test that health check returns True."""
    result = await storage.health()
    assert result is True


@pytest.mark.asyncio
async def test_cleanup_is_noop(storage: AsyncMemoryStorage) -> None:
    """Test that cleanup is a no-op."""
    await storage.cleanup()
    # Storage should still be functional
    assert storage.records == {}


@pytest.mark.asyncio
async def test_close_is_noop(storage: AsyncMemoryStorage) -> None:
    """Test that close is a no-op."""
    oid = await storage.new_oid()
    record = b"data"
    await storage.begin()
    await storage.store(oid, record)
    await storage.end()

    await storage.close()
    # Records should still be accessible after close
    assert storage.records[oid] == record


@pytest.mark.asyncio
async def test_get_packer_returns_none(storage: AsyncMemoryStorage) -> None:
    """Test that get_packer returns None."""
    result = storage.get_packer()
    assert result is None


@pytest.mark.asyncio
async def test_async_context_manager() -> None:
    """Test async context manager protocol."""
    async with AsyncMemoryStorage() as storage:
        oid = await storage.new_oid()
        record = b"context_test"
        await storage.begin()
        await storage.store(oid, record)
        await storage.end()
        assert storage.records[oid] == record

    # After context exit, storage should be closed
    assert storage.records[oid] == record  # Data persists after close


@pytest.mark.asyncio
async def test_transaction_isolation(storage: AsyncMemoryStorage) -> None:
    """Test that transaction changes are not visible until end."""
    oid = await storage.new_oid()
    record1 = b"committed"
    record2 = b"pending"

    # First commit
    await storage.begin()
    await storage.store(oid, record1)
    await storage.end()

    # Second transaction - should not affect records until end
    await storage.begin()
    await storage.store(oid, record2)
    # Records should still have old value
    assert storage.records[oid] == record1
    await storage.end()
    # Now records should have new value
    assert storage.records[oid] == record2

# tests/unit/test_postgres_storage.py
#
# These tests target the AsyncPostgresStorage implementation
# (aliased as PostgresStorageAdapter for backward compatibility).
# The PostgreSQL storage backend is fully implemented — see
# dhara/storage/postgres.py and the wiring in dhara/mcp/server_core.py.
#
# OID API note: dhara/utils.py:str_to_int8 requires bytes input.
# All OIDs in the tests below are 8-byte big-endian bytes, matching
# the bytes-based OID contract used by every storage backend after
# the 69e812d commit.

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from dhara.storage.postgres import PostgresStorageAdapter, PostgresStorageSettings
from dhara.utils import int8_to_str
from dhara.serialize.record import pack_record


class TestPostgresStorageAdapterInit:
    """Test PostgresStorageAdapter initialization and health."""

    def test_init_creates_pool(self):
        settings = PostgresStorageSettings(
            pg_url="postgresql://user:pass@localhost:5432/dhara"
        )
        adapter = PostgresStorageAdapter(settings)
        assert adapter._pool is None  # lazy init
        assert adapter._in_transaction is False

    def test_init_without_explicit_url_falls_through_to_oneiric(self):
        """When pg_url is None, AsyncPostgresStorage falls through to the
        Oneiric-config URL (or the hard-coded default). This replaced the
        pre-69e812d behavior of raising ValueError. The settings object
        itself accepts pg_url=None and stores url=None; the adapter's
        __init__ resolves the final URL lazily via Oneiric config.
        """
        settings = PostgresStorageSettings(pg_url=None)
        assert settings.url is None
        # Adapter construction must succeed (not raise) — URL resolution
        # is deferred until first connect.
        adapter = PostgresStorageAdapter(settings)
        # The adapter either picks up Oneiric config or the local default.
        assert adapter._url is not None
        assert adapter._url.startswith("postgresql://")

    @pytest.mark.asyncio
    async def test_health_returns_true_when_pool_responds(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = MagicMock()  # pool.acquire() is sync, returns async ctx manager
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "1"
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = ctx
        adapter._pool = mock_pool
        result = await adapter.health()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_returns_false_when_pool_raises(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = MagicMock()
        mock_pool.acquire.side_effect = OSError("connection refused")
        adapter._pool = mock_pool
        result = await adapter.health()
        assert result is False


class TestPostgresStorageAdapterSync:
    """Test sync() returns dirty OIDs and deletes them atomically."""

    @pytest.mark.asyncio
    async def test_sync_returns_dirty_oids_and_deletes_them(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        # First call to fetch dirty oids, second call to delete
        mock_conn.fetch.return_value = [{"oid": 1}, {"oid": 2}]
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = ctx
        adapter._pool = mock_pool

        result = await adapter.sync()
        # After 69e812d, sync() returns bytes (int8_to_str), not str.
        assert result == [int8_to_str(1), int8_to_str(2)]
        assert all(isinstance(oid, bytes) for oid in result)
        # Verify delete was called
        mock_conn.execute.assert_called()


class TestPostgresStorageAdapterTransaction:
    """Test transaction lifecycle: begin, store, end."""

    @pytest.mark.asyncio
    async def test_begin_twice_raises_runtime_error(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_tx = AsyncMock()
        # Override transaction to return mock_tx synchronously (it's a sync method on connection)
        mock_conn.transaction.return_value = mock_tx
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        adapter._pool = mock_pool

        await adapter.begin()
        with pytest.raises(RuntimeError, match="already in transaction"):
            await adapter.begin()

    @pytest.mark.asyncio
    async def test_store_without_begin_raises_runtime_error(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        # No pool set, so any call that reaches the guard will fail

        with pytest.raises(RuntimeError, match="outside transaction"):
            await adapter.store("123", b"data")

    @pytest.mark.asyncio
    async def test_full_transaction_lifecycle(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_tx = AsyncMock()
        mock_conn.transaction.return_value = mock_tx
        mock_conn.execute = AsyncMock()
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()
        adapter._pool = mock_pool

        await adapter.begin()
        # OID must be bytes (8-byte big-endian) after the 69e812d commit.
        # The record arg must be a real packed record (oid|data_len|data|
        # refs_len|refs), not raw bytes — Postgres store() unpacks it.
        oid = int8_to_str(123)
        packed = pack_record(oid, b"test_data", b"")
        await adapter.store(oid, packed)
        await adapter.end()

        # Verify execute was called for insert and dirty_mark
        assert mock_conn.execute.call_count >= 2
        # Verify commit was called
        mock_tx.start.assert_called_once()
        mock_tx.commit.assert_called_once()


class TestPostgresStorageAdapterLoad:
    """Test load raises KeyError for missing oid."""

    @pytest.mark.asyncio
    async def test_load_missing_oid_raises_keyerror(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None  # no row found
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = ctx
        adapter._pool = mock_pool

        with pytest.raises(KeyError):
            # OID must be bytes (8-byte big-endian) after 69e812d.
            await adapter.load(int8_to_str(123))


class TestPostgresStorageAdapterOid:
    """Test new_oid uses nextval()."""

    @pytest.mark.asyncio
    async def test_new_oid_returns_int_bytes_from_sequence(self):
        settings = PostgresStorageSettings(pg_url="postgresql://localhost/dhara")
        adapter = PostgresStorageAdapter(settings)
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = 42  # nextval returns 42
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = ctx
        adapter._pool = mock_pool

        oid = await adapter.new_oid()
        # After 69e812d, new_oid() returns bytes (int8_to_str), not str.
        assert oid == int8_to_str(42)
        assert isinstance(oid, bytes)
        assert len(oid) == 8
        mock_conn.fetchval.assert_called_once_with("SELECT nextval('dhara_oid_seq')")

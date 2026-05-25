# tests/unit/test_postgres_storage.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from dhara.storage.postgres import PostgresStorageAdapter, PostgresStorageSettings


class TestPostgresStorageAdapterInit:
    """Test PostgresStorageAdapter initialization and health."""

    def test_init_creates_pool(self):
        settings = PostgresStorageSettings(
            pg_url="postgresql://user:pass@localhost:5432/dhara"
        )
        adapter = PostgresStorageAdapter(settings)
        assert adapter._pool is None  # lazy init
        assert adapter._in_transaction is False

    def test_init_without_explicit_url_raises(self):
        with pytest.raises(ValueError, match="pg_url"):
            settings = PostgresStorageSettings(pg_url=None)
            PostgresStorageAdapter(settings)

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
            await adapter.load("123")


class TestPostgresStorageAdapterOid:
    """Test new_oid uses nextval()."""

    @pytest.mark.asyncio
    async def test_new_oid_returns_int_string_from_sequence(self):
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
        assert oid == "42"
        mock_conn.fetchval.assert_called_once_with("SELECT nextval('dhara_oid_seq')")
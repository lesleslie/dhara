"""Tests for DharaMCPServer backend selection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dhara.core.config import DharaSettings
from dhara.mcp.server_core import DharaMCPServer


class TestDharaMCPServerBackendSelection:
    def test_default_uses_filestorage(self):
        """Default storage_backend=file should use AsyncFileStorage."""
        settings = DharaSettings()
        with patch("pathlib.Path.mkdir"), \
             patch("dhara.mcp.server_core.Connection") as mock_conn, \
             patch("dhara.mcp.server_core.AsyncFileStorage") as mock_fs:
            mock_instance = MagicMock()
            mock_instance.new_oid = MagicMock(return_value="test_oid")
            mock_fs.return_value = mock_instance
            mock_conn.return_value = MagicMock()
            DharaMCPServer(settings)
            mock_fs.assert_called_once()

    @patch("dhara.storage.postgres.PostgresStorageAdapter")
    @patch("dhara.mcp.server_core.Connection")
    def test_postgres_backend_uses_postgres_adapter(
        self, mock_conn, mock_adapter_class
    ):
        """storage_backend=postgres should use PostgresStorageAdapter."""
        settings = DharaSettings(
            storage_backend="postgres",
            storage_pg_url="postgresql://localhost/dhara",
        )
        mock_adapter = MagicMock()
        mock_adapter.new_oid = MagicMock(return_value="test_oid")
        mock_adapter_class.return_value = mock_adapter
        mock_conn.return_value = MagicMock()
        with patch("pathlib.Path.mkdir"):
            server = DharaMCPServer(settings)
        mock_adapter_class.assert_called_once()
        assert server.storage is mock_adapter

    @patch("dhara.storage.redis_cache.RedisCacheAdapter")
    @patch("dhara.mcp.server_core.AsyncFileStorage")
    @patch("dhara.mcp.server_core.Connection")
    def test_redis_cache_backend_instantiates_redis_cache(
        self, mock_conn, mock_fs, mock_adapter_class
    ):
        """cache_backend=redis should use RedisCacheAdapter."""
        settings = DharaSettings(
            cache_backend="redis",
            cache_redis_url="redis://localhost:6379",
            cache_redis_token="token123",
            cache_ttl=7200,
            cache_stampede_jitter_ms=200,
        )
        mock_adapter = MagicMock()
        mock_adapter.new_oid = MagicMock(return_value="test_oid")
        mock_fs.return_value = mock_adapter
        mock_adapter_class.return_value = mock_adapter
        mock_conn.return_value = MagicMock()
        with patch("pathlib.Path.mkdir"):
            server = DharaMCPServer(settings)
        call_args = mock_adapter_class.call_args
        assert call_args is not None
        assert server.cache is mock_adapter

    @patch("dhara.storage.redis_cache.RedisCacheAdapter")
    @patch("dhara.mcp.server_core.AsyncFileStorage")
    @patch("dhara.mcp.server_core.Connection")
    def test_memory_cache_backend_no_redis(
        self, mock_conn, mock_fs, mock_redis_class
    ):
        """cache_backend=memory should not instantiate RedisCacheAdapter."""
        settings = DharaSettings(
            cache_backend="memory",
        )
        mock_adapter = MagicMock()
        mock_adapter.new_oid = MagicMock(return_value="test_oid")
        mock_fs.return_value = mock_adapter
        mock_conn.return_value = MagicMock()
        with patch("pathlib.Path.mkdir"):
            DharaMCPServer(settings)
        mock_redis_class.assert_not_called()

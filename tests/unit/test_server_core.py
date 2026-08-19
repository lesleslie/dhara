"""Tests for DharaMCPServer backend selection."""

from __future__ import annotations

from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dhara.core.config import DharaSettings
from dhara.core.connection import ROOT_OID
from dhara.mcp.server_core import DharaMCPServer


@pytest.fixture(autouse=True)
def _reset_cache_wire_loop() -> None:
    """Stop and reset ``_CACHE_WIRE_LOOP`` before AND after each test.

    Mirrors the fixture in ``tests/test_mcp_server_core.py`` so this file
    can construct multiple ``DharaMCPServer`` instances in one process.
    Without resetting the loop between tests, subsequent
    ``DharaMCPServer(...)`` constructions call ``run_until_complete`` on a
    loop that is already running, raising ``RuntimeError: This event loop
    is already running``.
    """

    def _reset_loop() -> None:
        try:
            from dhara.mcp.server_core import _CACHE_WIRE_LOOP as _loop
        except ImportError:
            return
        if _loop is None:
            return
        with suppress(Exception):
            _loop.call_soon_threadsafe(_loop.stop)
        if hasattr(_loop, "_dhara_wire_thread"):
            _loop._dhara_wire_thread = None  # ty: ignore[unresolved-attribute]
        with suppress(Exception):
            if not _loop.is_closed():
                _loop.close()
        import dhara.mcp.server_core as _core

        _core._CACHE_WIRE_LOOP = None

    _reset_loop()
    yield
    _reset_loop()


class TestDharaMCPServerBackendSelection:
    def test_default_uses_filestorage(self):
        """Default storage_backend=file should use AsyncFileStorage."""
        settings = DharaSettings()
        with patch("pathlib.Path.mkdir"), \
             patch("dhara.mcp.server_core.Connection") as mock_conn, \
             patch("dhara.mcp.server_core.AsyncFileStorage") as mock_fs:
            mock_instance = AsyncMock()
            mock_instance.new_oid = AsyncMock(return_value=ROOT_OID)
            mock_instance.load = AsyncMock(side_effect=KeyError)
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
        mock_adapter = AsyncMock()
        mock_adapter.new_oid = AsyncMock(return_value=ROOT_OID)
        mock_adapter.load = AsyncMock(side_effect=KeyError)
        mock_adapter_class.return_value = mock_adapter
        mock_conn.return_value = MagicMock()
        with patch("pathlib.Path.mkdir"):
            server = DharaMCPServer(settings)
        mock_adapter_class.assert_called_once()
        assert server.storage is mock_adapter

    @patch(
        "dhara.mcp.adapter_lookup.resolve_cache_adapter",
        new_callable=AsyncMock,
    )
    @patch("dhara.mcp.server_core.AsyncFileStorage")
    @patch("dhara.mcp.server_core.Connection")
    def test_redis_cache_backend_instantiates_redis_cache(
        self, mock_conn, mock_fs, mock_resolve
    ):
        """cache_backend=redis should use RedisCacheAdapter."""
        settings = DharaSettings(cache_backend="redis")
        mock_adapter = AsyncMock()
        mock_adapter.new_oid = AsyncMock(return_value=ROOT_OID)
        mock_adapter.load = AsyncMock(side_effect=KeyError)
        mock_fs.return_value = mock_adapter
        mock_conn.return_value = MagicMock()
        mock_resolve.return_value = mock_adapter
        with patch("pathlib.Path.mkdir"):
            server = DharaMCPServer(settings)
        mock_resolve.assert_awaited_once()
        assert mock_resolve.await_args.kwargs["backend"] == "redis"
        assert server.cache is mock_adapter

    @patch(
        "dhara.mcp.adapter_lookup.resolve_cache_adapter",
        new_callable=AsyncMock,
    )
    @patch("dhara.mcp.server_core.AsyncFileStorage")
    @patch("dhara.mcp.server_core.Connection")
    def test_memory_cache_backend_no_redis(
        self, mock_conn, mock_fs, mock_resolve
    ):
        """cache_backend=memory should resolve only the memory adapter."""
        settings = DharaSettings(cache_backend="memory")
        mock_adapter = AsyncMock()
        mock_adapter.new_oid = AsyncMock(return_value=ROOT_OID)
        mock_adapter.load = AsyncMock(side_effect=KeyError)
        mock_fs.return_value = mock_adapter
        mock_conn.return_value = MagicMock()
        mock_resolve.return_value = mock_adapter
        with patch("pathlib.Path.mkdir"):
            DharaMCPServer(settings)
        mock_resolve.assert_awaited_once()
        assert mock_resolve.await_args.kwargs["backend"] == "memory"

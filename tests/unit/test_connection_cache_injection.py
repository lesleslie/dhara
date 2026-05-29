from __future__ import annotations

from unittest.mock import MagicMock

from dhara.core.connection import Connection
from dhara.storage import MemoryStorage


class TestConnectionCacheInjection:
    def test_connection_accepts_external_cache(self):
        mock_storage = MemoryStorage()
        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        conn = Connection(mock_storage, cache=mock_cache)
        assert conn.cache is mock_cache

    def test_connection_creates_lrUCache_when_cache_not_provided(self):
        mock_storage = MemoryStorage()
        conn = Connection(mock_storage)
        from dhara.core.connection import Cache
        assert isinstance(conn.cache, Cache)

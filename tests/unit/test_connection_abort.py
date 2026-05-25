from __future__ import annotations

from unittest.mock import MagicMock, patch

from dhara.core.connection import Connection


class TestConnectionAbortCacheInvalidation:
    def test_abort_calls_cache_clear(self):
        """Test that abort() calls cache.clear() to invalidate uncommitted oids."""
        mock_storage = MagicMock()
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_storage.sync.return_value = []
        mock_storage.new_oid.return_value = "0" * 16

        # Patch the Storage class and Cache class in connection module
        with patch.object(Connection, '__init__', lambda self, storage, cache_size=100000, root_class=None: None):
            conn = object.__new__(Connection)
            conn.storage = mock_storage
            conn.cache = mock_cache
            conn.changed = {}
            conn.invalid_oids = set()
            conn.new_oid = mock_storage.new_oid
            conn.transaction_serial = 0

            conn.abort()
            # cache.clear() should be called after abort to invalidate uncommitted oids
            mock_cache.clear.assert_called()
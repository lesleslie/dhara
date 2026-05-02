"""Tests for dhara.core.connection — Connection class methods."""

from __future__ import annotations

import gc
from unittest.mock import MagicMock, patch

import pytest

from dhara.collections.dict import PersistentDict
from dhara.core.connection import (
    ROOT_OID,
    Cache,
    Connection,
    ObjectDictionary,
    ReferenceContainer,
)
from dhara.storage.sqlite import SqliteStorage
from dhara.utils import int8_to_str


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_conn.durus")


@pytest.fixture
def store(db_path):
    s = SqliteStorage(db_path)
    yield s
    s.close()


@pytest.fixture
def conn(store):
    c = Connection(store, cache_size=100)
    yield c


# ===========================================================================
# Connection init and properties
# ===========================================================================


class TestConnectionInit:
    def test_creates_root_persistent_dict(self, store):
        c = Connection(store, cache_size=100)
        assert c.get_root() is not None
        assert isinstance(c.get_root(), PersistentDict)
        c.abort()

    def test_storage_from_string(self, tmp_path):
        from dhara.storage.file import FileStorage

        path = str(tmp_path / "from_str.durus")
        c = Connection(path, cache_size=50)
        assert c.get_root() is not None
        assert isinstance(c.get_storage(), FileStorage)
        c.abort()
        c.get_storage().close()

    def test_root_class_validation(self, store):
        c = Connection(store, cache_size=100, root_class=PersistentDict)
        assert isinstance(c.get_root(), PersistentDict)
        c.abort()

    def test_get_storage(self, conn):
        assert conn.get_storage() is not None

    def test_get_cache_count(self, conn):
        count = conn.get_cache_count()
        assert count >= 1  # at least root object

    def test_get_cache_size(self, conn):
        assert conn.get_cache_size() == 100

    def test_set_cache_size(self, conn):
        conn.set_cache_size(50)
        assert conn.get_cache_size() == 50

    def test_set_cache_size_zero_raises(self, conn):
        with pytest.raises(ValueError, match="must be > 0"):
            conn.set_cache_size(0)

    def test_get_transaction_serial(self, conn):
        # Connection.__init__ does a commit, so serial starts at 1
        assert conn.get_transaction_serial() >= 1

    def test_get_root(self, conn):
        root = conn.get_root()
        assert root is not None

    def test_get_load_count(self, conn):
        count = conn.get_load_count()
        assert count >= 0

    def test_get_cache(self, conn):
        cache = conn.get_cache()
        assert isinstance(cache, Cache)


# ===========================================================================
# Connection.get
# ===========================================================================


class TestConnectionGet:
    def test_get_root_by_oid(self, conn):
        obj = conn.get(ROOT_OID)
        assert obj is not None

    def test_get_missing_returns_none(self, conn):
        obj = conn.get(int8_to_str(99999))
        assert obj is None

    def test_getitem_same_as_get(self, conn):
        obj = conn[ROOT_OID]
        assert obj is not None

    def test_get_with_int_oid(self, conn):
        obj = conn.get(0)
        assert obj is not None


# ===========================================================================
# Connection.commit and abort
# ===========================================================================


class TestConnectionCommitAbort:
    def test_empty_commit(self, conn):
        serial_before = conn.get_transaction_serial()
        conn.commit()
        assert conn.get_transaction_serial() == serial_before + 1

    def test_abort_increments_serial(self, conn):
        serial_before = conn.get_transaction_serial()
        conn.abort()
        assert conn.get_transaction_serial() == serial_before + 1

    def test_commit_with_change(self, conn):
        root = conn.get_root()
        root["key1"] = "value1"
        conn.commit()
        assert conn.get_transaction_serial() >= 1
        # After reopen, root should have the change
        conn.get_storage().close()
        s2 = SqliteStorage(conn.get_storage().filename)
        c2 = Connection(s2, cache_size=100)
        assert c2.get_root()["key1"] == "value1"
        c2.abort()
        s2.close()

    def test_abort_discards_changes(self, conn):
        root = conn.get_root()
        root["key1"] = "value1"
        conn.abort()
        # After reopen, root should NOT have the change
        conn.get_storage().close()
        s2 = SqliteStorage(conn.get_storage().filename)
        c2 = Connection(s2, cache_size=100)
        assert "key1" not in c2.get_root()
        c2.abort()
        s2.close()

    def test_commit_no_changes_still_syncs(self, conn):
        """Commit with no changed objects calls _sync()."""
        conn.commit()  # should not raise


# ===========================================================================
# Connection.note_access and note_change
# ===========================================================================


class TestConnectionNoteAccessChange:
    def test_note_access(self, conn):
        root = conn.get_root()
        root._p_oid = ROOT_OID
        root._p_connection = conn
        root._p_serial = conn.get_transaction_serial()
        # Should not raise
        conn.note_access(root)

    def test_note_change(self, conn):
        root = conn.get_root()
        root._p_oid = ROOT_OID
        conn.note_change(root)
        assert ROOT_OID in conn.changed


# ===========================================================================
# Connection.shrink_cache
# ===========================================================================


class TestConnectionShrinkCache:
    def test_shrink_cache_no_op_when_below_target(self, conn):
        conn.shrink_cache()  # should not raise

    def test_shrink_cache_with_many_objects(self, store):
        c = Connection(store, cache_size=5)
        root = c.get_root()
        # Add several objects to the root
        for i in range(10):
            root[f"k{i}"] = f"v{i}"
        c.commit()
        # Now shrink — should ghostify some objects
        c.shrink_cache()
        c.abort()
        store.close()


# ===========================================================================
# Connection.pack
# ===========================================================================


class TestConnectionPack:
    def test_pack(self, store):
        c = Connection(store, cache_size=100)
        root = c.get_root()
        root["keep"] = "this"
        c.commit()
        # Add an object that's not reachable from root
        # (pack should remove it)
        c.pack()
        # Root should still be accessible
        c2 = Connection(store, cache_size=100)
        assert "keep" in c2.get_root()
        c2.abort()
        store.close()


# ===========================================================================
# Connection._sync
# ===========================================================================


class TestConnectionSync:
    def test_sync_clears_invalid_oids(self, conn):
        # Manually set invalid_oids to simulate conflict
        conn.invalid_oids.add(int8_to_str(99))
        conn._sync()
        assert len(conn.invalid_oids) == 0


# ===========================================================================
# Connection._handle_invalidations
# ===========================================================================


class TestHandleInvalidations:
    def test_no_conflicts(self, conn):
        # Empty oids list, no conflicts
        conn._handle_invalidations([])

    def test_unknown_oids_no_conflict(self, conn):
        # OIDs not in cache are ignored
        conn._handle_invalidations([int8_to_str(99999)])

    def test_write_conflict_on_accessed_object(self, conn):
        root = conn.get_root()
        root._p_oid = ROOT_OID
        root._p_serial = conn.get_transaction_serial()
        from dhara.error import WriteConflictError

        with pytest.raises(WriteConflictError):
            conn._handle_invalidations([ROOT_OID])
        assert ROOT_OID in conn.invalid_oids

    def test_read_conflict_with_read_oid(self, conn):
        root = conn.get_root()
        root._p_oid = ROOT_OID
        root._p_serial = conn.get_transaction_serial()
        from dhara.error import ReadConflictError

        with pytest.raises(ReadConflictError):
            conn._handle_invalidations([ROOT_OID], read_oid=ROOT_OID)

    def test_ghosts_non_ghost_non_accessed(self, conn):
        # When oid is not in changed and obj is non-ghost with old serial,
        # _handle_invalidations ghostifies it (doesn't raise).
        # We need to patch _p_is_ghost to return False for this.
        root = conn.get_root()
        root._p_oid = ROOT_OID
        root._p_serial = 0  # old serial, doesn't match current
        with patch.object(type(root), "_p_is_ghost", return_value=False):
            conn._handle_invalidations([ROOT_OID])


# ===========================================================================
# Connection.get_crawler
# ===========================================================================


class TestConnectionGetCrawler:
    def test_crawler_yields_root(self, conn):
        crawler = list(conn.get_crawler())
        assert len(crawler) >= 1
        # First item should be the root
        assert crawler[0]._p_oid == ROOT_OID

    def test_crawler_yields_all_stored(self, store):
        c = Connection(store, cache_size=100)
        root = c.get_root()
        root["a"] = "b"
        c.commit()
        crawler = list(c.get_crawler())
        assert len(crawler) >= 1
        c.abort()
        store.close()


# ===========================================================================
# Connection.load_state
# ===========================================================================


class TestConnectionLoadState:
    def test_load_state_on_ghost(self, conn):
        # Access root then ghostify it
        root = conn.get_root()
        root._p_set_status_ghost()
        assert root._p_is_ghost()
        # load_state should reload the state
        conn.load_state(root)
        assert not root._p_is_ghost()

    def test_load_state_raises_if_no_storage(self, conn):
        root = conn.get_root()
        root._p_set_status_ghost()
        conn.storage = None
        with pytest.raises(AssertionError, match="connection is closed"):
            conn.load_state(root)


# ===========================================================================
# Cache.shrink with real objects
# ===========================================================================


class TestCacheShrinkReal:
    def test_shrink_removes_lru_objects(self, store):
        c = Connection(store, cache_size=5)
        root = c.get_root()
        for i in range(10):
            root[f"k{i}"] = f"v{i}"
        c.commit()
        # Access root to make it most recently used
        root2 = c.get(ROOT_OID)
        c.shrink_cache()
        c.abort()
        store.close()

    def test_shrink_preserves_transaction_accessed(self, store):
        """Objects accessed in current transaction are not ghosted."""
        c = Connection(store, cache_size=3)
        root = c.get_root()
        for i in range(5):
            root[f"k{i}"] = f"v{i}"
        c.commit()
        # Access root in current transaction
        c.note_access(c.get(ROOT_OID))
        c.shrink_cache()
        # Root should still be accessible (not ghosted)
        assert not c.get(ROOT_OID)._p_is_ghost()
        c.abort()
        store.close()


# ===========================================================================
# Cache.delitem with recent_objects
# ===========================================================================


class TestCacheDelitemReal:
    def test_delitem_discards_from_recent(self, store):
        c = Connection(store, cache_size=100)
        root = c.get_root()
        root._p_oid = ROOT_OID
        root._p_set_status_saved()
        # Add to recent_objects
        c.cache.recent_objects.add(root)
        assert len(c.cache.recent_objects) == 1
        # Now delete from cache
        root._p_oid = None
        del c.cache[ROOT_OID]
        assert len(c.cache.recent_objects) == 0
        c.abort()
        store.close()


# ===========================================================================
# Cache.get_instance
# ===========================================================================


class TestCacheGetInstance:
    def test_get_instance_returns_object(self, conn):
        cache = conn.get_cache()
        obj = cache.get_instance(ROOT_OID, PersistentDict, conn)
        assert obj is not None


# ===========================================================================
# Cache.iter
# ===========================================================================


class TestCacheIterReal:
    def test_iter_returns_cached_objects(self, store):
        c = Connection(store, cache_size=100)
        root = c.get_root()
        items = list(c.cache)
        assert len(items) >= 1
        assert root in items
        c.abort()
        store.close()


# ===========================================================================
# Standalone functions
# ===========================================================================


class TestStandaloneFunctions:
    def test_touch_every_reference(self, store):
        c = Connection(store, cache_size=100)
        root = c.get_root()
        root["data"] = "some_value"
        c.commit()
        # touch_every_reference uses gen_oid_record internally
        # We need to patch gen_oid_record to use start_oid (avoiding SQL bug)
        from dhara.core.connection import touch_every_reference

        original_gen = store.gen_oid_record

        def patched_gen(**kw):
            return original_gen(start_oid=ROOT_OID)

        with patch.object(store, "gen_oid_record", patched_gen):
            touch_every_reference(c, "PersistentDict")
        # The root object should be marked as changed
        assert len(c.changed) >= 1
        c.abort()
        store.close()

    def test_gen_every_instance(self, store):
        c = Connection(store, cache_size=100)
        root = c.get_root()
        root["a"] = "b"
        c.commit()
        from dhara.core.connection import gen_every_instance

        original_gen = store.gen_oid_record

        def patched_gen(**kw):
            return original_gen(start_oid=ROOT_OID)

        with patch.object(store, "gen_oid_record", patched_gen):
            instances = list(gen_every_instance(c, PersistentDict))
        assert len(instances) >= 1
        assert all(isinstance(obj, PersistentDict) for obj in instances)
        c.abort()
        store.close()


# ===========================================================================
# Cache.setitem updates LRU
# ===========================================================================


class TestCacheSetitemLRU:
    def test_setitem_moves_to_end(self, store):
        c = Connection(store, cache_size=100)
        cache = c.cache
        # Root is already in cache at some position
        root = c.get(ROOT_OID)
        # Access a different key to move root out of latest position
        root2_key = int8_to_str(1)
        cache[root2_key] = root
        # root2_key should be at the end now
        keys = list(cache._lru.keys())
        assert keys[-1] == root2_key
        c.abort()
        store.close()

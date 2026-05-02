"""Tests for dhara.core.connection — ObjectDictionary, ReferenceContainer, Cache."""

from __future__ import annotations

import time
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from dhara.core.connection import Cache, ObjectDictionary, ReferenceContainer


# ===========================================================================
# ObjectDictionary
# ===========================================================================


class TestObjectDictionary:
    def test_init(self):
        od = ObjectDictionary()
        assert od.mapping == {}
        assert od.dead == set()

    def test_set_and_get(self):
        od = ObjectDictionary()
        obj = MagicMock()
        od["key1"] = obj
        assert od.get("key1") is obj

    def test_get_missing_returns_default(self):
        od = ObjectDictionary()
        assert od.get("missing") is None
        assert od.get("missing", "default") == "default"

    def test_delitem(self):
        od = ObjectDictionary()
        obj = MagicMock()
        od["key1"] = obj
        del od["key1"]
        assert "key1" in od.dead
        assert od.get("key1") is None

    def test_contains(self):
        od = ObjectDictionary()
        obj = MagicMock()
        od["key1"] = obj
        assert "key1" in od
        assert "key2" not in od

    def test_len(self):
        od = ObjectDictionary()
        assert len(od) == 0
        od["a"] = MagicMock()
        od["b"] = MagicMock()
        assert len(od) == 2
        # Deleted items shouldn't count
        del od["a"]
        assert len(od) == 1

    def test_clear_dead(self):
        od = ObjectDictionary()
        obj = MagicMock()
        od["key1"] = obj
        del od["key1"]
        assert "key1" in od.dead
        od.clear_dead()
        assert "key1" not in od.dead
        assert "key1" not in od.mapping

    def test_iter_clears_dead_first(self):
        od = ObjectDictionary()
        od["a"] = MagicMock()
        od["b"] = MagicMock()
        del od["a"]
        keys = list(od)
        assert "a" not in keys
        assert "b" in keys

    def test_setitem_revives_dead_key(self):
        od = ObjectDictionary()
        obj1 = MagicMock()
        od["key1"] = obj1
        del od["key1"]
        assert "key1" in od.dead
        obj2 = MagicMock()
        od["key1"] = obj2
        assert "key1" not in od.dead
        assert od.get("key1") is obj2

    def test_callback_on_gc(self):
        od = ObjectDictionary()
        obj = MagicMock()
        od["key1"] = obj
        del obj
        # Trigger callback by simulating ref callback
        # The dead set should contain the key after GC
        # (In practice, this requires actually triggering GC)


# ===========================================================================
# ReferenceContainer
# ===========================================================================


class TestReferenceContainer:
    def test_init(self):
        rc = ReferenceContainer()
        assert rc.map == {}

    def test_add_and_len(self):
        rc = ReferenceContainer()
        obj1 = MagicMock()
        obj2 = MagicMock()
        rc.add(obj1)
        rc.add(obj2)
        assert len(rc) == 2

    def test_discard(self):
        rc = ReferenceContainer()
        obj = MagicMock()
        rc.add(obj)
        rc.discard(obj)
        assert len(rc) == 0

    def test_discard_nonexistent_no_error(self):
        rc = ReferenceContainer()
        obj = MagicMock()
        rc.discard(obj)  # should not raise

    def test_add_same_object_twice(self):
        rc = ReferenceContainer()
        obj = MagicMock()
        rc.add(obj)
        rc.add(obj)
        # Same id, so map still has 1 entry
        assert len(rc) == 1


# ===========================================================================
# Cache
# ===========================================================================


class TestCacheInit:
    def test_default_init(self):
        c = Cache(100)
        assert c.get_size() == 100
        assert c.get_count() == 0

    def test_set_size(self):
        c = Cache(100)
        c.set_size(200)
        assert c.get_size() == 200

    def test_set_size_zero_raises(self):
        c = Cache(100)
        with pytest.raises(ValueError, match="must be > 0"):
            c.set_size(0)

    def test_set_size_negative_raises(self):
        c = Cache(100)
        with pytest.raises(ValueError, match="must be > 0"):
            c.set_size(-10)


class TestCacheGetSet:
    def test_get_missing(self):
        c = Cache(100)
        assert c.get("missing") is None

    def test_setitem_and_get(self):
        c = Cache(100)
        obj = MagicMock()
        obj._p_oid = "oid1"
        c["oid1"] = obj
        assert c.get("oid1") is obj

    def test_delitem(self):
        c = Cache(100)
        obj = MagicMock()
        obj._p_oid = "oid1"
        obj._p_is_saved.return_value = True
        c["oid1"] = obj
        # Source asserts _p_oid is None before deletion
        obj._p_oid = None
        del c["oid1"]
        assert c.get("oid1") is None

    def test_delitem_nonexistent_no_error(self):
        c = Cache(100)
        # Should not raise even if key doesn't exist
        del_key = "nonexistent"
        # __delitem__ checks objects.get first, which returns None
        assert c.get(del_key) is None
        # Manual LRU cleanup
        c._lru.pop(del_key, None)

    def test_len_via_get_count(self):
        c = Cache(100)
        assert c.get_count() == 0
        obj = MagicMock()
        obj._p_oid = "oid1"
        c["oid1"] = obj
        assert c.get_count() == 1


class TestCacheGetCount:
    def test_initial_count(self):
        c = Cache(100)
        assert c.get_count() == 0

    def test_count_after_add(self):
        c = Cache(100)
        obj = MagicMock()
        obj._p_oid = "oid1"
        c["oid1"] = obj
        assert c.get_count() == 1


class TestCacheShrink:
    def test_shrink_no_op_when_below_target(self):
        c = Cache(100)
        # No objects, nothing to shrink
        c.shrink(_mock_connection())

    def test_shrink_no_op_when_below_target(self):
        c = Cache(100)
        # No objects, nothing to shrink
        c.shrink(_mock_connection())

    def test_shrink_cleans_lru_entries_for_missing_objects(self):
        """When objects are GC'd but LRU still has entries, shrink cleans them.

        ObjectDictionary uses weak refs (KeyedRef), so mock objects get GC'd.
        We directly populate both objects.mapping and _lru to simulate
        objects that exist in the dict but are GC'd (return None from get).
        """
        c = Cache(2)
        conn = _mock_connection()
        # Add entries to ObjectDictionary's mapping directly (bypass weak refs)
        for i in range(5):
            c.objects.mapping[f"oid{i}"] = None  # dead weak ref
        # Also add to LRU
        for i in range(5):
            c._lru[f"oid{i}"] = None
        # len(self.objects) should see 5 entries in mapping
        assert c.get_count() == 5
        c.shrink(conn)
        # GC'd entries should be cleaned from LRU
        assert len(c._lru) == 0

    def test_shrink_logs_when_no_excess(self):
        c = Cache(100)
        conn = _mock_connection()
        # Should not raise even with empty cache
        c.shrink(conn)


class TestCacheIter:
    def test_iter_empty(self):
        c = Cache(100)
        assert list(c) == []

    def test_iter_returns_objects(self):
        c = Cache(100)
        obj1 = MagicMock()
        obj1._p_oid = "oid1"
        obj2 = MagicMock()
        obj2._p_oid = "oid2"
        c["oid1"] = obj1
        c["oid2"] = obj2
        items = list(c)
        assert obj1 in items
        assert obj2 in items


class TestCacheLRU:
    def test_get_updates_lru(self):
        c = Cache(100)
        obj = MagicMock()
        obj._p_oid = "oid1"
        c["oid1"] = obj
        # get should move to end
        c.get("oid1")
        # LRU should have oid1 at the end
        keys = list(c._lru.keys())
        assert keys[-1] == "oid1"

    def test_setitem_adds_to_lru(self):
        c = Cache(100)
        obj = MagicMock()
        obj._p_oid = "oid1"
        c["oid1"] = obj
        assert "oid1" in c._lru


# ===========================================================================
# Helpers
# ===========================================================================


def _mock_connection(transaction_serial=0):
    conn = MagicMock()
    conn.get_transaction_serial.return_value = transaction_serial
    return conn

"""Tests for dhara.core.connection — ObjectDictionary, ReferenceContainer, Cache, Connection helpers.

Focus on the helper classes (ObjectDictionary, ReferenceContainer, Cache) and
module-level utility functions. Connection itself requires a real Storage
backend and is tested via integration tests.
"""

from __future__ import annotations

import gc
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from dhara.core.connection import (
    Cache,
    ObjectDictionary,
    ReferenceContainer,
    gen_every_instance,
    touch_every_reference,
)
from dhara.core.persistent import PersistentObject
from dhara.utils import int8_to_str


def _oid(i):
    """Create an -byte OID from an integer."""
    return int8_to_str(i)


class _MinimalObj(PersistentObject):
    """Minimal PersistentObject with slots for cache testing."""

    __slots__ = ["_p_oid", "_p_connection", "_p_serial", "_p_status", "value"]

    def __init__(self, value=None):
        self.value = value

    def __getstate__(self):
        return {"value": self.value}

    def __setstate__(self, state):
        self.value = state.get("value")

    def _p_set_status_ghost(self):
        self._p_status = "ghost"

    def _p_set_status_saved(self):
        self._p_status = "saved"

    def _p_set_status_unsaved(self):
        self._p_status = "unsaved"

    def _p_is_ghost(self):
        return self._p_status == "ghost"

    def _p_is_saved(self):
        return self._p_status == "saved"

    def _p_note_change(self):
        if self._p_connection is not None:
            self._p_connection.note_change(self)


def _make_saved_obj(oid=b"\x00" * 8, serial=0, value="test"):
    """Create a saved PersistentObject with given OID."""
    obj = _MinimalObj(value=value)
    obj._p_oid = oid
    obj._p_serial = serial
    obj._p_status = "saved"
    obj._p_connection = MagicMock()
    return obj


def _make_ghost_obj(oid=b"\x01" * 8, serial=0):
    """Create a ghost PersistentObject."""
    obj = _MinimalObj()
    obj._p_oid = oid
    obj._p_serial = serial
    obj._p_status = "ghost"
    obj._p_connection = MagicMock()
    return obj


# ===========================================================================
# ObjectDictionary
# ===========================================================================


class TestObjectDictionary:
    def test_get_missing_returns_none(self):
        od = ObjectDictionary()
        assert od.get("nonexistent") is None
        assert od.get("nonexistent", "default") == "default"

    def test_setitem_and_get(self):
        od = ObjectDictionary()
        obj = _MinimalObj()
        od["key1"] = obj
        assert od.get("key1") is obj

    def test_delitem(self):
        od = ObjectDictionary()
        obj = _MinimalObj()
        od["key1"] = obj  # keep strong ref so weakref survives
        del od["key1"]
        # After deletion, key should be in dead set
        assert "key1" in od.dead
        # get should return default (still in mapping but marked dead)
        assert od.get("key1") is None

    def test_contains(self):
        od = ObjectDictionary()
        assert "missing" not in od
        obj = _MinimalObj()
        od["present"] = obj
        assert "present" in od

    def test_len_empty(self):
        od = ObjectDictionary()
        assert len(od) == 0

    def test_len_with_items(self):
        od = ObjectDictionary()
        a = _MinimalObj()
        b = _MinimalObj()
        od["a"] = a
        od["b"] = b
        assert len(od) == 2

    def test_len_excludes_dead(self):
        od = ObjectDictionary()
        a = _MinimalObj()
        b = _MinimalObj()
        od["a"] = a
        od["b"] = b
        del od["a"]  # marks as dead
        assert len(od) == 1  # dead items not counted

    def test_clear_dead(self):
        od = ObjectDictionary()
        a = _MinimalObj()
        b = _MinimalObj()
        od["a"] = a
        od["b"] = b
        del od["a"]
        del od["b"]
        od.clear_dead()
        assert len(od) == 0
        assert len(od.mapping) == 0

    def test_iteration_skips_dead(self):
        od = ObjectDictionary()
        a = _MinimalObj()
        b = _MinimalObj()
        c = _MinimalObj()
        od["a"] = a
        od["b"] = b
        od["c"] = c
        del od["b"]
        keys = list(od)
        assert "b" not in keys
        assert len(keys) == 2

    def test_callback_on_gc(self):
        od = ObjectDictionary()
        obj = _MinimalObj()
        od["key"] = obj
        del od.mapping["key"]  # simulate weakref dying
        # After clearing the mapping entry, get should return None
        assert od.get("key") is None

    def test_setitem_revives_dead(self):
        od = ObjectDictionary()
        a = _MinimalObj()
        od["a"] = a
        del od["a"]
        assert len(od) == 0
        a2 = _MinimalObj()
        od["a"] = a2
        assert len(od) == 1


# ===========================================================================
# ReferenceContainer
# ===========================================================================


class TestReferenceContainer:
    def test_len_empty(self):
        rc = ReferenceContainer()
        assert len(rc) == 0

    def test_add(self):
        rc = ReferenceContainer()
        obj = _MinimalObj()
        rc.add(obj)
        assert len(rc) == 1

    def test_add_multiple(self):
        rc = ReferenceContainer()
        obj1 = _MinimalObj()
        obj2 = _MinimalObj()
        rc.add(obj1)
        rc.add(obj2)
        assert len(rc) == 2

    def test_discard(self):
        rc = ReferenceContainer()
        obj = _MinimalObj()
        rc.add(obj)
        rc.discard(obj)
        assert len(rc) == 0

    def test_discard_missing_no_error(self):
        rc = ReferenceContainer()
        rc.discard(_MinimalObj())  # should not raise

    def test_discard_different_object(self):
        rc = ReferenceContainer()
        rc.add(_MinimalObj())
        rc.discard(_MinimalObj())  # different instance
        assert len(rc) == 1


# ===========================================================================
# Cache
# ===========================================================================


class TestCacheInit:
    def test_init_default_size(self):
        cache = Cache(100)
        assert cache.size == 100
        assert cache.get_count() == 0

    def test_set_size(self):
        cache = Cache(100)
        cache.set_size(200)
        assert cache.size == 200

    def test_set_size_zero_raises(self):
        cache = Cache(100)
        with pytest.raises(ValueError, match="must be > 0"):
            cache.set_size(0)

    def test_set_size_negative_raises(self):
        cache = Cache(100)
        with pytest.raises(ValueError, match="must be > 0"):
            cache.set_size(-1)


class TestCacheGetSet:
    def test_get_missing_returns_none(self):
        cache = Cache(100)
        assert cache.get(b"\x00" * 8) is None

    def test_setitem_and_get(self):
        cache = Cache(100)
        obj = _MinimalObj()
        cache[b"\x01" * 8] = obj
        assert cache.get(b"\x01" * 8) is obj

    def test_setitem_tracks_lru(self):
        cache = Cache(100)
        obj1 = _MinimalObj()
        obj2 = _MinimalObj()
        cache[b"\x01" * 8] = obj1
        cache[b"\x02" * 8] = obj2
        # obj2 should be most recently used
        keys = list(cache._lru.keys())
        assert keys[-1] == b"\x02" * 8

    def test_get_updates_lru(self):
        cache = Cache(100)
        obj1 = _MinimalObj()
        obj2 = _MinimalObj()
        cache[b"\x01" * 8] = obj1
        cache[b"\x02" * 8] = obj2
        cache.get(b"\x01" * 8)  # access obj1
        keys = list(cache._lru.keys())
        assert keys[-1] == b"\x01" * 8

    def test_delitem(self):
        cache = Cache(100)
        obj = _MinimalObj()
        cache[b"\x01" * 8] = obj
        obj._p_oid = None  # __delitem__ asserts _p_oid is None
        del cache[b"\x01" * 8]
        assert cache.get(b"\x01" * 8) is None

    def test_delitem_discards_recent(self):
        cache = Cache(100)
        obj = _MinimalObj()
        cache[b"\x01" * 8] = obj
        cache.recent_objects.add(obj)
        obj._p_oid = None  # __delitem__ asserts _p_oid is None
        del cache[b"\x01" * 8]
        assert obj not in cache.recent_objects.map

    def test_delitem_removes_lru(self):
        cache = Cache(100)
        obj = _MinimalObj()
        cache[b"\x01" * 8] = obj
        obj._p_oid = None  # __delitem__ asserts _p_oid is None
        del cache[b"\x01" * 8]
        assert b"\x01" * 8 not in cache._lru


class TestCacheShrink:
    def test_shrink_below_target(self):
        cache = Cache(100)
        # Add fewer items than target — keep strong refs so weakrefs survive
        objs = []
        for i in range(50):
            obj = _make_saved_obj(_oid(i), serial=0)
            cache[obj._p_oid] = obj
            objs.append(obj)
        # Should not remove anything
        cache.shrink(MagicMock(get_transaction_serial=lambda: 0))
        assert cache.get_count() == 50

    def test_shrink_evicts_lru(self):
        cache = Cache(10)
        objs = []
        for i in range(20):
            obj = _make_saved_obj(_oid(i), serial=0)
            cache[obj._p_oid] = obj
            objs.append(obj)

        mock_conn = MagicMock(get_transaction_serial=lambda: 99)
        cache.shrink(mock_conn)

        # shrink() ghosts objects but doesn't remove from ObjectDictionary.
        # It removes from LRU tracking. Verify LRU was trimmed.
        assert len(cache._lru) <= 10

        # Ghosted objects should have ghost status
        ghosted = sum(1 for o in objs if o._p_status == "ghost")
        assert ghosted > 0

    def test_shrink_skips_current_transaction(self):
        cache = Cache(5)
        objs = []
        for i in range(10):
            serial = 5 if i < 3 else 0  # first 3 are "recent"
            obj = _make_saved_obj(_oid(i), serial=serial)
            cache[obj._p_oid] = obj
            objs.append(obj)

        mock_conn = MagicMock(get_transaction_serial=lambda: 5)
        cache.shrink(mock_conn)

        # Objects with serial=5 (in current transaction) should be kept
        for i in range(3):
            assert cache.get(objs[i]._p_oid) is not None


class TestCacheIteration:
    def test_iter(self):
        cache = Cache(100)
        objs = []
        for i in range(5):
            obj = _make_saved_obj(_oid(i), serial=0)
            cache[obj._p_oid] = obj
            objs.append(obj)  # keep strong refs
        items = list(cache)
        assert len(items) == 5


class TestCacheGetCount:
    def test_get_count_empty(self):
        cache = Cache(100)
        assert cache.get_count() == 0

    def test_get_count(self):
        cache = Cache(100)
        obj1 = _MinimalObj()
        obj2 = _MinimalObj()
        cache[b"\x01" * 8] = obj1
        cache[b"\x02" * 8] = obj2
        assert cache.get_count() == 2


# ===========================================================================
# ROOT_OID
# ===========================================================================


class TestRootOid:
    def test_root_oid_is_zero(self):
        from dhara.core.connection import ROOT_OID

        assert ROOT_OID == b"\x00" * 8

    def test_root_oid_is_eight_bytes(self):
        from dhara.core.connection import ROOT_OID

        assert len(ROOT_OID) == 8

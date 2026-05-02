"""Comprehensive tests for dhara.collections.dict.PersistentDict.

Tests every public method, branch, and edge case. The class extends
PersistentObject (which requires a connection for mutation tracking),
so a mock _p_connection is injected via the _make_dict helper.

Line coverage targets (the 18 previously-missed lines):
  39   - __getitem__ __missing__ fallback
  66   - iteritems()
  69-70 - iterkeys()
  73-74 - itervalues()
  85   - update() >1 arg TypeError
  86->98 - update() PersistentDict branch
  89   - update() plain dict branch
  92-97 - update() keys() branch
  99   - update() kwargs loop
  123-126 - fromkeys() classmethod
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dhara.collections.dict import PersistentDict
from dhara.core.persistent import PersistentObject


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_dict(*args, **kwargs):
    """Create a PersistentDict with a mock connection for mutation tracking."""
    d = PersistentDict(*args, **kwargs)
    d._p_connection = MagicMock()
    return d


# ===========================================================================
# Init
# ===========================================================================


class TestInit:
    def test_empty(self):
        d = _make_dict()
        assert len(d) == 0
        assert d.data == {}

    def test_init_with_dict(self):
        d = _make_dict({"a": 1, "b": 2})
        assert d["a"] == 1
        assert d["b"] == 2
        assert len(d) == 2

    def test_init_with_kwargs(self):
        d = _make_dict(x=10, y=20)
        assert d["x"] == 10
        assert d["y"] == 20

    def test_init_with_dict_and_kwargs(self):
        d = _make_dict({"a": 1}, b=2)
        assert d["a"] == 1
        assert d["b"] == 2

    def test_init_with_list_of_pairs(self):
        d = _make_dict([("k1", "v1"), ("k2", "v2")])
        assert d["k1"] == "v1"
        assert d["k2"] == "v2"

    def test_slots(self):
        d = _make_dict()
        assert hasattr(d, "data")
        # PersistentObject uses __slots__, so __dict__ should not exist
        # on the instance itself (only PersistentBase slots).
        assert "data" in type(d).__slots__

    def test_data_is_class_attribute(self):
        assert PersistentDict.data_is is dict


# ===========================================================================
# __getitem__ and __missing__
# ===========================================================================


class TestGetitem:
    def test_existing_key(self):
        d = _make_dict({"a": 1})
        assert d["a"] == 1

    def test_missing_key_raises_keyerror(self):
        d = _make_dict()
        with pytest.raises(KeyError):
            _ = d["missing"]

    def test_missing_key_with_subclass(self):
        """Cover line 39: __missing__ fallback."""

        class DefaultDict(PersistentDict):
            def __missing__(self, key):
                return 0

        d = DefaultDict()
        d._p_connection = MagicMock()
        assert d["any_key"] == 0

    def test_non_string_keys(self):
        d = _make_dict()
        d[42] = "answer"
        d[(1, 2)] = "tuple_key"
        assert d[42] == "answer"
        assert d[(1, 2)] == "tuple_key"

    def test_none_value(self):
        d = _make_dict()
        d["key"] = None
        assert d["key"] is None
        assert "key" in d


# ===========================================================================
# __setitem__ and __delitem__
# ===========================================================================


class TestSetitemDelitem:
    def test_setitem(self):
        d = _make_dict()
        d["key"] = "value"
        assert d["key"] == "value"

    def test_setitem_overwrite(self):
        d = _make_dict()
        d["key"] = "v1"
        d["key"] = "v2"
        assert d["key"] == "v2"
        assert len(d) == 1

    def test_setitem_calls_p_note_change(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as mock_note:
            d = PersistentDict()
            d._p_connection = MagicMock()
            mock_note.reset_mock()
            d["k"] = "v"
            mock_note.assert_called_once_with(d)

    def test_delitem(self):
        d = _make_dict({"a": 1})
        del d["a"]
        assert "a" not in d
        assert len(d) == 0

    def test_delitem_missing_raises(self):
        d = _make_dict()
        with pytest.raises(KeyError):
            del d["missing"]

    def test_delitem_calls_p_note_change(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as mock_note:
            d = PersistentDict({"a": 1})
            d._p_connection = MagicMock()
            mock_note.reset_mock()
            del d["a"]
            mock_note.assert_called_once_with(d)


# ===========================================================================
# __contains__ and __len__
# ===========================================================================


class TestContainsAndLen:
    def test_contains_existing(self):
        d = _make_dict({"a": 1})
        assert "a" in d

    def test_contains_missing(self):
        d = _make_dict()
        assert "missing" not in d

    def test_len_empty(self):
        d = _make_dict()
        assert len(d) == 0

    def test_len_nonempty(self):
        d = _make_dict()
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        assert len(d) == 3

    def test_len_after_delete(self):
        d = _make_dict({"a": 1, "b": 2})
        del d["a"]
        assert len(d) == 1


# ===========================================================================
# __iter__
# ===========================================================================


class TestIteration:
    def test_iter_empty(self):
        d = _make_dict()
        assert list(d) == []

    def test_iter_keys(self):
        d = _make_dict({"a": 1, "b": 2})
        assert set(d) == {"a", "b"}

    def test_iter_multiple_times(self):
        d = _make_dict({"x": 1})
        first = list(d)
        second = list(d)
        assert first == second


# ===========================================================================
# keys(), values(), items()
# ===========================================================================


class TestViews:
    def test_keys_returns_list(self):
        d = _make_dict({"a": 1, "b": 2})
        keys = d.keys()
        assert isinstance(keys, list)
        assert set(keys) == {"a", "b"}

    def test_keys_empty(self):
        d = _make_dict()
        assert d.keys() == []

    def test_values_returns_list(self):
        d = _make_dict({"a": 1, "b": 2})
        values = d.values()
        assert isinstance(values, list)
        assert set(values) == {1, 2}

    def test_values_empty(self):
        d = _make_dict()
        assert d.values() == []

    def test_items_returns_list(self):
        d = _make_dict({"a": 1})
        items = d.items()
        assert isinstance(items, list)
        assert ("a", 1) in items

    def test_items_empty(self):
        d = _make_dict()
        assert d.items() == []

    def test_items_preserves_all(self):
        d = _make_dict({"a": 1, "b": 2, "c": 3})
        items = d.items()
        assert len(items) == 3
        assert set(items) == {("a", 1), ("b", 2), ("c", 3)}


# ===========================================================================
# iteritems(), iterkeys(), itervalues()
# ===========================================================================


class TestIterMethods:
    def test_iteritems(self):
        """Cover line 66."""
        d = _make_dict({"a": 1, "b": 2})
        result = dict(d.iteritems())
        assert result == {"a": 1, "b": 2}

    def test_iteritems_empty(self):
        d = _make_dict()
        assert list(d.iteritems()) == []

    def test_iteritems_yields_pairs(self):
        d = _make_dict({"a": 1})
        result = list(d.iteritems())
        assert result == [("a", 1)]

    def test_iteritems_is_iterable(self):
        d = _make_dict({"a": 1})
        it = d.iteritems()
        # In Python 3, iteritems returns dict_items view, which is iterable
        assert iter(it) is not None
        assert list(it) == [("a", 1)]

    def test_iterkeys(self):
        """Cover lines 69-70."""
        d = _make_dict({"a": 1, "b": 2, "c": 3})
        keys = list(d.iterkeys())
        assert set(keys) == {"a", "b", "c"}

    def test_iterkeys_empty(self):
        d = _make_dict()
        assert list(d.iterkeys()) == []

    def test_itervalues(self):
        """Cover lines 73-74."""
        d = _make_dict({"a": 1, "b": 2, "c": 3})
        values = list(d.itervalues())
        assert set(values) == {1, 2, 3}

    def test_itervalues_empty(self):
        d = _make_dict()
        assert list(d.itervalues()) == []


# ===========================================================================
# get(), setdefault()
# ===========================================================================


class TestGetAndSetdefault:
    def test_get_existing(self):
        d = _make_dict({"key": "value"})
        assert d.get("key") == "value"

    def test_get_missing_no_default(self):
        d = _make_dict()
        assert d.get("missing") is None

    def test_get_missing_with_default(self):
        d = _make_dict()
        assert d.get("missing", 42) == 42

    def test_get_none_value_key(self):
        d = _make_dict({"key": None})
        assert d.get("key") is None

    def test_get_default_on_existing_key(self):
        d = _make_dict({"key": "value"})
        assert d.get("key", "default") == "value"

    def test_setdefault_existing(self):
        d = _make_dict({"key": "original"})
        result = d.setdefault("key", "default")
        assert result == "original"
        assert d["key"] == "original"

    def test_setdefault_missing(self):
        d = _make_dict()
        result = d.setdefault("key", "default")
        assert result == "default"
        assert d["key"] == "default"

    def test_setdefault_none_value(self):
        d = _make_dict()
        result = d.setdefault("key", None)
        assert result is None
        assert "key" in d

    def test_setdefault_calls_p_note_change_on_missing(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as mock_note:
            d = PersistentDict()
            d._p_connection = MagicMock()
            mock_note.reset_mock()
            d.setdefault("new_key", 99)
            mock_note.assert_called_once_with(d)

    def test_setdefault_no_change_on_existing(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as mock_note:
            d = PersistentDict({"key": "val"})
            d._p_connection = MagicMock()
            mock_note.reset_mock()
            d.setdefault("key", "other")
            mock_note.assert_not_called()


# ===========================================================================
# update()
# ===========================================================================


class TestUpdate:
    def test_update_with_dict(self):
        d = _make_dict({"a": 1})
        d.update({"b": 2, "c": 3})
        assert d["b"] == 2
        assert d["c"] == 3
        assert d["a"] == 1

    def test_update_with_persistent_dict(self):
        """Cover line 89: isinstance(other, PersistentDict) branch."""
        d = _make_dict({"a": 1})
        other = _make_dict({"b": 2})
        d.update(other)
        assert d["a"] == 1
        assert d["b"] == 2

    def test_update_with_mapping_object(self):
        """Cover lines 92-97: hasattr(other, 'keys') branch."""
        d = _make_dict({"a": 1})

        class SimpleMapping:
            def keys(self):
                return ["x", "y"]

            def __getitem__(self, key):
                return key.upper()

        d.update(SimpleMapping())
        assert d["x"] == "X"
        assert d["y"] == "Y"

    def test_update_with_iterable_of_pairs(self):
        """Cover lines 96-97: else branch (no keys attr, iterate pairs)."""
        d = _make_dict({"a": 1})
        d.update([("b", 2), ("c", 3)])
        assert d["b"] == 2
        assert d["c"] == 3

    def test_update_with_kwargs(self):
        """Cover line 99: kwargs loop."""
        d = _make_dict({"a": 1})
        d.update(b=2, c=3)
        assert d["a"] == 1
        assert d["b"] == 2
        assert d["c"] == 3

    def test_update_with_dict_and_kwargs(self):
        d = _make_dict()
        d.update({"a": 1}, b=2)
        assert d["a"] == 1
        assert d["b"] == 2

    def test_update_with_persistent_dict_and_kwargs(self):
        d = _make_dict()
        other = _make_dict({"a": 1})
        d.update(other, b=2)
        assert d["a"] == 1
        assert d["b"] == 2

    def test_update_too_many_args_raises(self):
        """Cover line 85: >1 positional arg TypeError."""
        d = _make_dict()
        with pytest.raises(TypeError, match="expected at most 1 argument"):
            d.update({"a": 1}, {"b": 2})

    def test_update_empty(self):
        d = _make_dict({"a": 1})
        d.update()
        assert d["a"] == 1
        assert len(d) == 1

    def test_update_calls_p_note_change(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as mock_note:
            d = PersistentDict()
            d._p_connection = MagicMock()
            mock_note.reset_mock()
            d.update({"a": 1})
            mock_note.assert_called_once_with(d)

    def test_update_overwrites_existing(self):
        d = _make_dict({"a": 1})
        d.update({"a": 99})
        assert d["a"] == 99


# ===========================================================================
# clear()
# ===========================================================================


class TestClear:
    def test_clear_nonempty(self):
        d = _make_dict({"a": 1, "b": 2})
        d.clear()
        assert len(d) == 0
        assert list(d.keys()) == []

    def test_clear_empty(self):
        d = _make_dict()
        d.clear()
        assert len(d) == 0

    def test_clear_calls_p_note_change(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as mock_note:
            d = PersistentDict({"a": 1})
            d._p_connection = MagicMock()
            mock_note.reset_mock()
            d.clear()
            mock_note.assert_called_once_with(d)

    def test_clear_then_add(self):
        d = _make_dict({"a": 1})
        d.clear()
        d["b"] = 2
        assert len(d) == 1
        assert d["b"] == 2


# ===========================================================================
# pop() and popitem()
# ===========================================================================


class TestPopAndPopitem:
    def test_pop_existing(self):
        d = _make_dict({"key": "value"})
        result = d.pop("key")
        assert result == "value"
        assert "key" not in d

    def test_pop_missing_with_default(self):
        d = _make_dict()
        assert d.pop("missing", 42) == 42

    def test_pop_missing_no_default_raises(self):
        d = _make_dict()
        with pytest.raises(KeyError):
            d.pop("missing")

    def test_pop_calls_p_note_change(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as mock_note:
            d = PersistentDict({"a": 1})
            d._p_connection = MagicMock()
            mock_note.reset_mock()
            d.pop("a")
            mock_note.assert_called_once_with(d)

    def test_popitem(self):
        d = _make_dict({"a": 1, "b": 2})
        key, value = d.popitem()
        assert key in ("a", "b")
        assert value in (1, 2)
        assert len(d) == 1

    def test_popitem_empty_raises(self):
        d = _make_dict()
        with pytest.raises(KeyError):
            d.popitem()

    def test_popitem_calls_p_note_change(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as mock_note:
            d = PersistentDict({"a": 1})
            d._p_connection = MagicMock()
            mock_note.reset_mock()
            d.popitem()
            mock_note.assert_called_once_with(d)


# ===========================================================================
# copy()
# ===========================================================================


class TestCopy:
    def test_copy_independence(self):
        d = _make_dict({"a": 1})
        copied = d.copy()
        assert copied["a"] == 1
        copied["b"] = 2
        assert "b" not in d

    def test_copy_does_not_affect_original(self):
        d = _make_dict({"a": 1, "b": 2})
        copied = d.copy()
        del copied["a"]
        assert "a" in d
        assert len(d) == 2

    def test_copy_empty(self):
        d = _make_dict()
        copied = d.copy()
        assert len(copied) == 0

    def test_copy_is_persistent_dict(self):
        d = _make_dict({"a": 1})
        copied = d.copy()
        assert isinstance(copied, PersistentDict)

    def test_copy_data_is_independent(self):
        """Ensure the internal data dict is a shallow copy, not shared."""
        d = _make_dict({"a": [1, 2]})
        copied = d.copy()
        copied.data["a"].append(3)
        # Shallow copy: nested list is shared
        assert d["a"] == [1, 2, 3]
        # But top-level dict keys are independent
        copied["b"] = 99
        assert "b" not in d


# ===========================================================================
# has_key()
# ===========================================================================


class TestHasKey:
    def test_has_key_true(self):
        d = _make_dict({"key": "value"})
        assert d.has_key("key") is True

    def test_has_key_false(self):
        d = _make_dict()
        assert d.has_key("missing") is False


# ===========================================================================
# Equality / Inequality
# ===========================================================================


class TestEquality:
    def test_eq_same_data(self):
        d1 = _make_dict({"a": 1})
        d2 = _make_dict({"a": 1})
        assert d1 == d2

    def test_eq_self(self):
        d = _make_dict({"a": 1})
        assert d == d

    def test_ne_different_data(self):
        d1 = _make_dict({"a": 1})
        d2 = _make_dict({"a": 2})
        assert d1 != d2

    def test_ne_different_keys(self):
        d1 = _make_dict({"a": 1})
        d2 = _make_dict({"b": 1})
        assert d1 != d2

    def test_ne_with_plain_dict(self):
        d = _make_dict()
        assert d != {"a": 1}

    def test_ne_with_non_dict(self):
        d = _make_dict()
        assert d != "not a dict"
        assert d != 42
        assert d != None

    def test_ne_empty_dicts(self):
        d1 = _make_dict()
        d2 = _make_dict()
        assert d1 == d2

    def test_ne_with_plain_dict_same_content(self):
        """Even if data matches, PersistentDict != plain dict."""
        d = _make_dict({"a": 1})
        assert d != {"a": 1}


# ===========================================================================
# fromkeys() classmethod
# ===========================================================================


class TestFromkeys:
    def test_fromkeys_list(self):
        """Cover lines 123-126."""
        d = PersistentDict.fromkeys(["a", "b", "c"])
        assert isinstance(d, PersistentDict)
        assert d["a"] is None
        assert d["b"] is None
        assert d["c"] is None
        assert len(d) == 3

    def test_fromkeys_with_value(self):
        d = PersistentDict.fromkeys([1, 2, 3], value=42)
        assert d[1] == 42
        assert d[2] == 42
        assert d[3] == 42

    def test_fromkeys_empty_iterable(self):
        d = PersistentDict.fromkeys([])
        assert len(d) == 0

    def test_fromkeys_tuple(self):
        d = PersistentDict.fromkeys(("x", "y"))
        assert d["x"] is None
        assert d["y"] is None

    def test_fromkeys_generator(self):
        d = PersistentDict.fromkeys(str(k) for k in range(3))
        assert set(d.keys()) == {"0", "1", "2"}

    def test_fromkeys_is_classmethod(self):
        assert isinstance(PersistentDict.__dict__["fromkeys"], classmethod)


# ===========================================================================
# MutableMapping protocol
# ===========================================================================


class TestMutableMappingProtocol:
    def test_is_mutable_mapping(self):
        import collections.abc

        d = _make_dict()
        assert isinstance(d, collections.abc.MutableMapping)

    def test_is_mapping(self):
        import collections.abc

        d = _make_dict()
        assert isinstance(d, collections.abc.Mapping)

    def test_persistent_object_inheritance(self):
        from dhara.core.persistent import PersistentObject

        d = _make_dict()
        assert isinstance(d, PersistentObject)


# ===========================================================================
# _p_note_change() tracking
# ===========================================================================


class TestMutationTracking:
    """Ensure mutating methods call _p_note_change()."""

    def test_setitem_tracks(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as m:
            d = PersistentDict()
            d._p_connection = MagicMock()
            m.reset_mock()
            d["k"] = "v"
            m.assert_called_once_with(d)

    def test_delitem_tracks(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as m:
            d = PersistentDict({"k": "v"})
            d._p_connection = MagicMock()
            m.reset_mock()
            del d["k"]
            m.assert_called_once_with(d)

    def test_clear_tracks(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as m:
            d = PersistentDict({"k": "v"})
            d._p_connection = MagicMock()
            m.reset_mock()
            d.clear()
            m.assert_called_once_with(d)

    def test_update_tracks(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as m:
            d = PersistentDict()
            d._p_connection = MagicMock()
            m.reset_mock()
            d.update({"k": "v"})
            m.assert_called_once_with(d)

    def test_pop_tracks(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as m:
            d = PersistentDict({"k": "v"})
            d._p_connection = MagicMock()
            m.reset_mock()
            d.pop("k")
            m.assert_called_once_with(d)

    def test_popitem_tracks(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as m:
            d = PersistentDict({"k": "v"})
            d._p_connection = MagicMock()
            m.reset_mock()
            d.popitem()
            m.assert_called_once_with(d)

    def test_setdefault_missing_tracks(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as m:
            d = PersistentDict()
            d._p_connection = MagicMock()
            m.reset_mock()
            d.setdefault("k", "v")
            m.assert_called_once_with(d)

    def test_setdefault_existing_no_track(self):
        with patch.object(PersistentObject, "_p_note_change", autospec=True) as m:
            d = PersistentDict({"k": "v"})
            d._p_connection = MagicMock()
            m.reset_mock()
            d.setdefault("k", "other")
            m.assert_not_called()


# ===========================================================================
# Edge cases: empty dict, large dict, types
# ===========================================================================


class TestEdgeCases:
    def test_empty_getitem_raises(self):
        d = _make_dict()
        with pytest.raises(KeyError):
            _ = d["key"]

    def test_empty_pop_raises(self):
        d = _make_dict()
        with pytest.raises(KeyError):
            d.pop("key")

    def test_empty_popitem_raises(self):
        d = _make_dict()
        with pytest.raises(KeyError):
            d.popitem()

    def test_empty_delitem_raises(self):
        d = _make_dict()
        with pytest.raises(KeyError):
            del d["key"]

    def test_large_dict(self):
        d = _make_dict()
        for i in range(500):
            d[f"key_{i}"] = i
        assert len(d) == 500
        assert d["key_0"] == 0
        assert d["key_499"] == 499

    def test_large_dict_clear(self):
        d = _make_dict({f"k{i}": i for i in range(200)})
        d.clear()
        assert len(d) == 0

    def test_large_dict_update(self):
        d = _make_dict()
        d.update({f"k{i}": i for i in range(200)})
        assert len(d) == 200

    def test_large_dict_iteration(self):
        data = {f"k{i}": i for i in range(100)}
        d = _make_dict(data)
        assert set(d) == set(data.keys())

    def test_zero_key(self):
        d = _make_dict()
        d[0] = "zero"
        assert d[0] == "zero"

    def test_false_key(self):
        d = _make_dict()
        d[False] = "false"
        assert d[False] == "false"

    def test_empty_string_key(self):
        d = _make_dict()
        d[""] = "empty"
        assert d[""] == "empty"

    def test_overwrite_many_times(self):
        d = _make_dict()
        for i in range(50):
            d["key"] = i
        assert d["key"] == 49
        assert len(d) == 1

    def test_pop_all_items(self):
        d = _make_dict({"a": 1, "b": 2, "c": 3})
        keys = list(d.keys())
        for k in keys:
            d.pop(k)
        assert len(d) == 0

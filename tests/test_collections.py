"""Tests for persistent collections.

Tests PersistentDict from dhara.collections.dict. The collections
inherit from PersistentObject which requires storage, so these tests
mock the persistence layer to test collection behavior in isolation.
"""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_persistence():
    """Auto-mock PersistentBase._p_note_change and __new__ for all tests."""
    with (
        patch("dhara.core.persistent.PersistentBase._p_note_change", create=True, autospec=False),
        patch("dhara.core.persistent.PersistentBase._p_load_state", create=True, autospec=False),
    ):
        yield


class TestPersistentDict:
    """Tests for PersistentDict with mocked persistence."""

    @pytest.fixture
    def pdict(self):
        from dhara.collections.dict import PersistentDict

        return PersistentDict()

    def test_init_empty(self, pdict):
        assert len(pdict) == 0

    def test_init_with_data(self):
        from dhara.collections.dict import PersistentDict

        d = PersistentDict({"a": 1, "b": 2})
        assert d["a"] == 1
        assert d["b"] == 2

    def test_setitem_getitem(self, pdict):
        pdict["key"] = "value"
        assert pdict["key"] == "value"

    def test_setitem_overwrite(self, pdict):
        pdict["key"] = "v1"
        pdict["key"] = "v2"
        assert pdict["key"] == "v2"

    def test_delitem(self, pdict):
        pdict["key"] = "value"
        del pdict["key"]
        assert "key" not in pdict

    def test_delitem_missing_raises(self, pdict):
        with pytest.raises(KeyError):
            del pdict["missing"]

    def test_getitem_missing_raises(self, pdict):
        with pytest.raises(KeyError):
            _ = pdict["missing"]

    def test_get_with_default(self, pdict):
        assert pdict.get("missing") is None
        assert pdict.get("missing", 42) == 42

    def test_get_existing(self, pdict):
        pdict["key"] = "value"
        assert pdict.get("key") == "value"

    def test_contains(self, pdict):
        pdict["key"] = "value"
        assert "key" in pdict
        assert "missing" not in pdict

    def test_len(self, pdict):
        pdict["a"] = 1
        pdict["b"] = 2
        pdict["c"] = 3
        assert len(pdict) == 3

    def test_keys(self, pdict):
        pdict["a"] = 1
        pdict["b"] = 2
        keys = pdict.keys()
        assert isinstance(keys, list)
        assert set(keys) == {"a", "b"}

    def test_values(self, pdict):
        pdict["a"] = 1
        pdict["b"] = 2
        values = pdict.values()
        assert isinstance(values, list)
        assert set(values) == {1, 2}

    def test_items(self, pdict):
        pdict["a"] = 1
        items = pdict.items()
        assert isinstance(items, list)
        assert ("a", 1) in items

    def test_clear(self, pdict):
        pdict["a"] = 1
        pdict["b"] = 2
        pdict.clear()
        assert len(pdict) == 0

    def test_update(self, pdict):
        pdict["a"] = 1
        pdict.update({"b": 2, "c": 3})
        assert pdict["b"] == 2
        assert pdict["c"] == 3
        assert pdict["a"] == 1

    def test_setdefault_existing(self, pdict):
        pdict["key"] = "original"
        result = pdict.setdefault("key", "default")
        assert result == "original"

    def test_setdefault_missing(self, pdict):
        result = pdict.setdefault("key", "default")
        assert result == "default"
        assert pdict["key"] == "default"

    def test_pop(self, pdict):
        pdict["key"] = "value"
        result = pdict.pop("key")
        assert result == "value"
        assert "key" not in pdict

    def test_pop_missing_with_default(self, pdict):
        assert pdict.pop("missing", 42) == 42

    def test_pop_missing_no_default_raises(self, pdict):
        with pytest.raises(KeyError):
            pdict.pop("missing")

    def test_popitem(self, pdict):
        pdict["a"] = 1
        pdict["b"] = 2
        key, value = pdict.popitem()
        assert key in ("a", "b")
        assert value in (1, 2)
        assert len(pdict) == 1

    def test_copy(self, pdict):
        pdict["a"] = 1
        copied = pdict.copy()
        assert copied["a"] == 1
        copied["b"] = 2
        assert "b" not in pdict

    def test_equality(self):
        from dhara.collections.dict import PersistentDict

        d1 = PersistentDict({"a": 1})
        d2 = PersistentDict({"a": 1})
        assert d1 == d2

    def test_inequality(self):
        from dhara.collections.dict import PersistentDict

        d1 = PersistentDict({"a": 1})
        d2 = PersistentDict({"a": 2})
        assert d1 != d2

    def test_inequality_with_dict(self, pdict):
        assert pdict != {"a": 1}

    def test_has_key(self, pdict):
        pdict["key"] = "value"
        assert pdict.has_key("key") is True
        assert pdict.has_key("missing") is False

    def test_iteration(self, pdict):
        pdict["a"] = 1
        pdict["b"] = 2
        keys = list(pdict)
        assert set(keys) == {"a", "b"}

    def test_non_string_keys(self, pdict):
        pdict[42] = "answer"
        assert pdict[42] == "answer"

    def test_none_value(self, pdict):
        pdict["key"] = None
        assert pdict["key"] is None
        assert "key" in pdict

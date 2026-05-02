"""Tests for dhara.collections.list — PersistentList."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dhara.collections.list import PersistentList


def _make_list(*args, **kwargs):
    """Create a PersistentList with a mock connection for mutation tracking."""
    pl = PersistentList(*args, **kwargs)
    pl._p_connection = MagicMock()
    return pl


# ===========================================================================
# Init
# ===========================================================================


class TestPersistentListInit:
    def test_empty(self):
        pl = _make_list()
        assert len(pl) == 0
        assert pl.data == []

    def test_init_with_iterable(self):
        pl = _make_list([1, 2, 3])
        assert pl.data == [1, 2, 3]

    def test_init_with_generator(self):
        pl = _make_list(range(3))
        assert pl.data == [0, 1, 2]

    def test_slots(self):
        pl = _make_list()
        assert hasattr(pl, "data")
        with pytest.raises(AttributeError):
            pl.__dict__


# ===========================================================================
# Comparison operators
# ===========================================================================


class TestPersistentListComparison:
    def test_lt(self):
        assert _make_list([1]) < _make_list([2])

    def test_lt_plain_list(self):
        assert _make_list([1]) < [2]

    def test_lt_self_returns_false(self):
        pl = _make_list([1])
        assert not (pl < pl)

    def test_le_equal(self):
        pl = _make_list([1, 2])
        assert pl <= _make_list([1, 2])
        assert pl <= [1, 2]

    def test_le_subset(self):
        assert _make_list([1]) <= _make_list([1, 2])

    def test_eq_same(self):
        pl1 = _make_list([1, 2])
        pl2 = _make_list([1, 2])
        assert pl1 == pl2

    def test_eq_self(self):
        pl = _make_list([1])
        assert pl == pl

    def test_eq_plain_list(self):
        assert _make_list([1, 2]) == [1, 2]

    def test_ne(self):
        assert _make_list([1]) != _make_list([2])
        assert _make_list([1]) != [2]
        assert _make_list([1]) != "not a list"

    def test_gt(self):
        assert _make_list([2]) > _make_list([1])

    def test_ge_equal(self):
        pl = _make_list([1])
        assert pl >= _make_list([1])

    def test_ge_superset(self):
        assert _make_list([1, 2]) >= _make_list([1])


# ===========================================================================
# Container protocol
# ===========================================================================


class TestPersistentListContainer:
    def test_contains(self):
        pl = _make_list([1, 2, 3])
        assert 2 in pl
        assert 99 not in pl

    def test_len(self):
        pl = _make_list([1, 2, 3])
        assert len(pl) == 3

    def test_getitem(self):
        pl = _make_list([10, 20, 30])
        assert pl[0] == 10
        assert pl[-1] == 30
        assert pl[1:3] == [20, 30]

    def test_getslice(self):
        pl = _make_list([1, 2, 3, 4, 5])
        result = pl.__getslice__(1, 3)
        assert isinstance(result, PersistentList)
        assert result == [2, 3]

    def test_setitem(self):
        pl = _make_list([1, 2, 3])
        pl[1] = 99
        assert pl[1] == 99

    def test_delitem(self):
        pl = _make_list([1, 2, 3])
        del pl[1]
        assert pl.data == [1, 3]


# ===========================================================================
# Slice operations
# ===========================================================================


class TestPersistentListSlices:
    def test_setslice_persistent_list(self):
        pl = _make_list([1, 2, 3])
        pl.__setslice__(0, 2, _make_list([10, 20]))
        assert pl.data == [10, 20, 3]

    def test_setslice_plain_list(self):
        pl = _make_list([1, 2, 3])
        pl.__setslice__(0, 2, [10, 20])
        assert pl.data == [10, 20, 3]

    def test_setslice_iterable(self):
        pl = _make_list([1, 2, 3])
        pl.__setslice__(0, 1, (99,))
        assert pl.data == [99, 2, 3]

    def test_delslice(self):
        pl = _make_list([1, 2, 3, 4, 5])
        pl.__delslice__(1, 4)
        assert pl.data == [1, 5]


# ===========================================================================
# Concatenation
# ===========================================================================


class TestPersistentListConcat:
    def test_add_persistent_list(self):
        result = _make_list([1, 2]) + _make_list([3, 4])
        assert isinstance(result, PersistentList)
        assert result == [1, 2, 3, 4]

    def test_add_plain_list(self):
        result = _make_list([1]) + [2, 3]
        assert isinstance(result, PersistentList)
        assert result == [1, 2, 3]

    def test_add_iterable(self):
        result = _make_list([1]) + (2, 3)
        assert isinstance(result, PersistentList)
        assert result == [1, 2, 3]

    def test_radd_plain_list(self):
        result = [1, 2] + _make_list([3, 4])
        assert isinstance(result, PersistentList)
        assert result == [1, 2, 3, 4]

    def test_radd_persistent_list(self):
        result = _make_list([1]) + _make_list([2])
        assert result == [1, 2]

    def test_iadd_persistent_list(self):
        pl = _make_list([1])
        pl += _make_list([2, 3])
        assert pl.data == [1, 2, 3]

    def test_iadd_plain_list(self):
        pl = _make_list([1])
        pl += [2, 3]
        assert pl.data == [1, 2, 3]

    def test_iadd_returns_self(self):
        pl = _make_list([1])
        pl += [2]
        # iadd returns self
        assert pl.data == [1, 2]


# ===========================================================================
# Multiplication
# ===========================================================================


class TestPersistentListMul:
    def test_mul(self):
        result = _make_list([1, 2]) * 3
        assert isinstance(result, PersistentList)
        assert result == [1, 2, 1, 2, 1, 2]

    def test_rmul(self):
        result = 2 * _make_list([1])
        assert isinstance(result, PersistentList)
        assert result == [1, 1]

    def test_imul(self):
        pl = _make_list([1, 2])
        pl *= 2
        assert pl.data == [1, 2, 1, 2]


# ===========================================================================
# Mutating methods
# ===========================================================================


class TestPersistentListMutating:
    def test_append(self):
        pl = _make_list([1])
        pl.append(2)
        assert pl.data == [1, 2]

    def test_insert(self):
        pl = _make_list([1, 3])
        pl.insert(1, 2)
        assert pl.data == [1, 2, 3]

    def test_pop_default(self):
        pl = _make_list([1, 2, 3])
        val = pl.pop()
        assert val == 3
        assert pl.data == [1, 2]

    def test_pop_index(self):
        pl = _make_list([1, 2, 3])
        val = pl.pop(0)
        assert val == 1
        assert pl.data == [2, 3]

    def test_pop_empty_raises(self):
        pl = _make_list()
        with pytest.raises(IndexError):
            pl.pop()

    def test_remove(self):
        pl = _make_list([1, 2, 3])
        pl.remove(2)
        assert pl.data == [1, 3]

    def test_remove_missing_raises(self):
        pl = _make_list([1])
        with pytest.raises(ValueError):
            pl.remove(99)

    def test_reverse(self):
        pl = _make_list([1, 2, 3])
        pl.reverse()
        assert pl.data == [3, 2, 1]

    def test_sort(self):
        pl = _make_list([3, 1, 2])
        pl.sort()
        assert pl.data == [1, 2, 3]

    def test_sort_reverse(self):
        pl = _make_list([1, 3, 2])
        pl.sort(reverse=True)
        assert pl.data == [3, 2, 1]

    def test_sort_key(self):
        pl = _make_list([3, 1, 2])
        pl.sort(key=lambda x: -x)
        assert pl.data == [3, 2, 1]

    def test_extend_persistent_list(self):
        pl = _make_list([1])
        pl.extend(_make_list([2, 3]))
        assert pl.data == [1, 2, 3]

    def test_extend_plain_list(self):
        pl = _make_list([1])
        pl.extend([2, 3])
        assert pl.data == [1, 2, 3]

    def test_extend_iterable(self):
        pl = _make_list([1])
        pl.extend((2, 3))
        assert pl.data == [1, 2, 3]


# ===========================================================================
# Non-mutating methods
# ===========================================================================


class TestPersistentListNonMutating:
    def test_count(self):
        pl = _make_list([1, 2, 2, 3])
        assert pl.count(2) == 2
        assert pl.count(99) == 0

    def test_index(self):
        pl = _make_list([10, 20, 30])
        assert pl.index(20) == 1

    def test_index_with_start(self):
        pl = _make_list([1, 2, 1, 2])
        assert pl.index(1, 1) == 2

    def test_index_with_start_stop(self):
        pl = _make_list([1, 2, 1, 2])
        assert pl.index(1, 1, 3) == 2

    def test_index_missing_raises(self):
        pl = _make_list([1])
        with pytest.raises(ValueError):
            pl.index(99)


# ===========================================================================
# Cast behavior (tested indirectly through comparison operators above)
# ===========================================================================
# __cast is a name-mangled private method (_PersistentList__cast).
# It's tested indirectly via __eq__, __lt__, __le__ etc. which call it.

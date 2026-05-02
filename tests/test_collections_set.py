"""Tests for dhara.collections.set — PersistentSet."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dhara.collections.set import PersistentSet


def _make_set(*args):
    """Create a PersistentSet with a mock connection for mutation tracking."""
    ps = PersistentSet(*args)
    # Set up a mock connection so _p_note_change() doesn't assert on None
    ps._p_connection = MagicMock()
    return ps


class TestPersistentSetInit:
    def test_empty_set(self):
        ps = _make_set()
        assert len(ps) == 0

    def test_init_with_iterable(self):
        ps = _make_set([1, 2, 3])
        assert len(ps) == 3
        assert 1 in ps
        assert 2 in ps
        assert 3 in ps

    def test_init_deduplicates(self):
        ps = _make_set([1, 1, 2])
        assert len(ps) == 2

    def test_slots(self):
        ps = _make_set()
        assert hasattr(ps, "s")
        with pytest.raises(AttributeError):
            ps.__dict__


class TestPersistentSetRepr:
    def test_repr_no_oid(self):
        ps = _make_set([1, 2])
        r = repr(ps)
        assert "PersistentSet" in r
        assert "1" in r
        assert "2" in r

    def test_repr_with_oid(self):
        ps = _make_set([1])
        ps._p_oid = b"\x00" * 8
        r = repr(ps)
        assert "PersistentSet" in r


class TestPersistentSetContains:
    def test_contains_present(self):
        ps = _make_set([1, 2])
        assert 1 in ps
        assert 2 in ps

    def test_contains_absent(self):
        ps = _make_set([1])
        assert 99 not in ps


class TestPersistentSetEquality:
    def test_eq_same(self):
        ps1 = _make_set([1, 2])
        ps2 = _make_set([1, 2])
        assert ps1 == ps2

    def test_eq_different(self):
        ps1 = _make_set([1])
        ps2 = _make_set([2])
        assert ps1 != ps2

    def test_eq_not_persistent_set(self):
        ps = _make_set([1, 2])
        assert ps != {1, 2}
        assert ps != [1, 2]

    def test_ne(self):
        ps1 = _make_set([1])
        ps2 = _make_set([2])
        assert ps1 != ps2

    def test_ne_not_persistent_set(self):
        ps = _make_set([1])
        assert ps != "not a set"


class TestPersistentSetComparison:
    def test_le_subset(self):
        ps1 = _make_set([1])
        ps2 = _make_set([1, 2])
        assert ps1 <= ps2

    def test_le_equal(self):
        ps1 = _make_set([1, 2])
        ps2 = _make_set([1, 2])
        assert ps1 <= ps2

    def test_le_not_subset(self):
        ps1 = _make_set([1, 2])
        ps2 = _make_set([1])
        assert not (ps1 <= ps2)

    def test_lt_proper_subset(self):
        ps1 = _make_set([1])
        ps2 = _make_set([1, 2])
        assert ps1 < ps2

    def test_lt_equal_raises(self):
        ps1 = _make_set([1, 2])
        ps2 = _make_set([1, 2])
        assert not (ps1 < ps2)

    def test_ge_superset(self):
        ps1 = _make_set([1, 2])
        ps2 = _make_set([1])
        assert ps1 >= ps2

    def test_gt_proper_superset(self):
        ps1 = _make_set([1, 2])
        ps2 = _make_set([1])
        assert ps1 > ps2

    def test_comparison_non_persistent_set_raises(self):
        ps = _make_set([1])
        with pytest.raises(TypeError):
            ps < {1, 2}
        with pytest.raises(TypeError):
            ps <= {1, 2}
        with pytest.raises(TypeError):
            ps > {1, 2}
        with pytest.raises(TypeError):
            ps >= {1, 2}


class TestPersistentSetSetOperations:
    def test_and(self):
        ps1 = _make_set([1, 2, 3])
        ps2 = _make_set([2, 3, 4])
        result = ps1 & ps2
        assert isinstance(result, PersistentSet)
        assert result.s == {2, 3}

    def test_and_with_plain_set(self):
        ps = _make_set([1, 2, 3])
        result = ps & {2, 3, 4}
        assert isinstance(result, PersistentSet)
        assert result.s == {2, 3}

    def test_or(self):
        ps1 = _make_set([1, 2])
        ps2 = _make_set([2, 3])
        result = ps1 | ps2
        assert result.s == {1, 2, 3}

    def test_or_with_plain_set(self):
        ps = _make_set([1])
        result = ps | {2, 3}
        assert result.s == {1, 2, 3}

    def test_sub(self):
        ps1 = _make_set([1, 2, 3])
        ps2 = _make_set([2])
        result = ps1 - ps2
        assert result.s == {1, 3}

    def test_sub_with_plain_set(self):
        ps = _make_set([1, 2])
        result = ps - {1}
        assert result.s == {2}

    def test_xor(self):
        ps1 = _make_set([1, 2])
        ps2 = _make_set([2, 3])
        result = ps1 ^ ps2
        assert result.s == {1, 3}

    def test_xor_with_plain_set(self):
        ps = _make_set([1, 2])
        result = ps ^ {2, 3}
        assert result.s == {1, 3}

    def test_rand(self):
        ps = _make_set([1, 2])
        result = {1, 3} & ps
        assert isinstance(result, PersistentSet)
        assert result.s == {1}

    def test_ror(self):
        ps = _make_set([1, 2])
        result = {2, 3} | ps
        assert isinstance(result, PersistentSet)
        assert result.s == {1, 2, 3}

    def test_rsub(self):
        ps = _make_set([2, 3])
        result = {1, 2, 3} - ps
        assert isinstance(result, PersistentSet)
        assert result.s == {1}

    def test_rxor(self):
        ps = _make_set([1, 2])
        result = {2, 3} ^ ps
        assert isinstance(result, PersistentSet)
        assert result.s == {1, 3}


class TestPersistentSetInplaceOperations:
    def test_iand(self):
        ps = _make_set([1, 2, 3])
        other = _make_set([2, 3, 4])
        ps &= other
        assert ps.s == {2, 3}

    def test_iand_with_plain_set(self):
        ps = _make_set([1, 2, 3])
        ps &= {2}
        assert ps.s == {2}

    def test_ior(self):
        ps = _make_set([1])
        other = _make_set([2])
        ps |= other
        assert ps.s == {1, 2}

    def test_ior_with_plain_set(self):
        ps = _make_set([1])
        ps |= {2, 3}
        assert ps.s == {1, 2, 3}

    def test_isub(self):
        ps = _make_set([1, 2, 3])
        other = _make_set([1])
        ps -= other
        assert ps.s == {2, 3}

    def test_isub_with_plain_set(self):
        ps = _make_set([1, 2])
        ps -= {1}
        assert ps.s == {2}

    def test_ixor(self):
        ps = _make_set([1, 2])
        other = _make_set([2, 3])
        ps ^= other
        assert ps.s == {1, 3}

    def test_ixor_with_plain_set(self):
        ps = _make_set([1, 2])
        ps ^= {2, 3}
        assert ps.s == {1, 3}


class TestPersistentSetMutatingMethods:
    def test_add(self):
        ps = _make_set()
        ps.add(1)
        assert 1 in ps

    def test_discard(self):
        ps = _make_set([1])
        ps.discard(1)
        assert 1 not in ps

    def test_discard_missing_no_error(self):
        ps = _make_set()
        ps.discard(99)  # should not raise

    def test_remove(self):
        ps = _make_set([1])
        ps.remove(1)
        assert 1 not in ps

    def test_remove_missing_raises(self):
        ps = _make_set()
        with pytest.raises(KeyError):
            ps.remove(99)

    def test_pop(self):
        ps = _make_set([1])
        val = ps.pop()
        assert val == 1
        assert len(ps) == 0

    def test_pop_empty_raises(self):
        ps = _make_set()
        with pytest.raises(KeyError):
            ps.pop()

    def test_clear(self):
        ps = _make_set([1, 2, 3])
        ps.clear()
        assert len(ps) == 0

    def test_copy(self):
        ps = _make_set([1, 2])
        ps2 = ps.copy()
        assert isinstance(ps2, PersistentSet)
        assert ps2.s == {1, 2}
        assert ps2 is not ps

    def test_update(self):
        ps = _make_set([1])
        ps.update([2, 3])
        assert ps.s == {1, 2, 3}

    def test_update_with_set(self):
        ps = _make_set([1])
        ps.update({2, 3})
        assert ps.s == {1, 2, 3}


class TestPersistentSetSetMethods:
    def test_difference(self):
        ps = _make_set([1, 2, 3])
        result = ps.difference({2})
        assert isinstance(result, PersistentSet)
        assert result.s == {1, 3}

    def test_difference_update(self):
        ps = _make_set([1, 2, 3])
        ps.difference_update({2})
        assert ps.s == {1, 3}

    def test_intersection(self):
        ps = _make_set([1, 2, 3])
        result = ps.intersection({2, 3, 4})
        assert isinstance(result, PersistentSet)
        assert result.s == {2, 3}

    def test_intersection_multiple(self):
        ps = _make_set([1, 2, 3, 4])
        result = ps.intersection({1, 2}, {2, 3})
        assert result.s == {2}

    def test_intersection_update(self):
        ps = _make_set([1, 2, 3])
        ps.intersection_update({2})
        assert ps.s == {2}

    def test_issubset(self):
        ps = _make_set([1])
        assert ps.issubset({1, 2})
        assert not ps.issubset({2, 3})

    def test_issuperset(self):
        ps = _make_set([1, 2])
        assert ps.issuperset({1})
        assert not ps.issuperset({3})

    def test_symmetric_difference(self):
        ps = _make_set([1, 2])
        result = ps.symmetric_difference({2, 3})
        assert isinstance(result, PersistentSet)
        assert result.s == {1, 3}

    def test_symmetric_difference_update(self):
        ps = _make_set([1, 2])
        ps.symmetric_difference_update({2, 3})
        assert ps.s == {1, 3}

    def test_union(self):
        ps = _make_set([1])
        result = ps.union({2}, {3})
        assert isinstance(result, PersistentSet)
        assert result.s == {1, 2, 3}


class TestPersistentSetIteration:
    def test_iter(self):
        ps = _make_set([1, 2, 3])
        assert set(ps) == {1, 2, 3}

    def test_len(self):
        ps = _make_set([1, 2, 3])
        assert len(ps) == 3

    def test_contains_magic(self):
        ps = _make_set([1])
        assert 1 in ps
        assert 2 not in ps

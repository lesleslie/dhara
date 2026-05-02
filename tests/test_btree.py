"""Tests for dhara.collections.btree — BTree and BNode variants."""

from __future__ import annotations

import pytest

from dhara.collections.btree import BTree, BNode4, BNode8, BNode16


class TestBTreeCreation:
    """Test BTree construction and basic dict-like interface."""

    def test_default_constructor(self):
        t = BTree()
        assert len(t) == 0

    def test_insert_and_retrieve(self):
        t = BTree()
        t[0] = "a"
        t[1] = "b"
        assert t[0] == "a"
        assert t[1] == "b"

    def test_contains(self):
        t = BTree()
        t[42] = "answer"
        assert 42 in t
        assert 99 not in t

    def test_delete(self):
        t = BTree()
        t[1] = "one"
        del t[1]
        assert 1 not in t

    def test_clear_resets_tree(self):
        t = BTree()
        for i in range(10):
            t[i] = f"v{i}"
        assert len(t) == 10
        t.clear()
        assert len(t) == 0

    def test_get_default(self):
        t = BTree()
        assert t.get(42) is None
        assert t.get(42, "default") == "default"

    def test_get_existing(self):
        t = BTree()
        t[5] = "five"
        assert t.get(5) == "five"

    def test_setdefault_new(self):
        t = BTree()
        result = t.setdefault(10, "ten")
        assert result == "ten"
        assert t[10] == "ten"

    def test_setdefault_existing(self):
        t = BTree()
        t[10] = "original"
        result = t.setdefault(10, "new")
        assert result == "original"

    def test_update(self):
        t = BTree()
        t.update({1: "a", 2: "b", 3: "c"})
        assert len(t) == 3
        assert t[2] == "b"

    def test_has_key(self):
        t = BTree()
        t[5] = "x"
        assert t.has_key(5)
        assert not t.has_key(99)

    def test_get_min_max_item(self):
        t = BTree()
        t[10] = "ten"
        t[5] = "five"
        t[15] = "fifteen"
        assert t.get_min_item() == (5, "five")
        assert t.get_max_item() == (15, "fifteen")


class TestBTreeIteration:
    """Test BTree iteration methods."""

    def test_iter_keys(self):
        t = BTree()
        for i in [3, 1, 2]:
            t[i] = f"v{i}"
        assert list(t.keys()) == [1, 2, 3]

    def test_iter_values(self):
        t = BTree()
        t[1] = "a"
        t[2] = "b"
        assert list(t.values()) == ["a", "b"]

    def test_iter_items(self):
        t = BTree()
        t[1] = "a"
        t[2] = "b"
        assert list(t.items()) == [(1, "a"), (2, "b")]

    def test_reversed(self):
        t = BTree()
        for i in range(5):
            t[i] = f"v{i}"
        assert list(reversed(t)) == [4, 3, 2, 1, 0]

    def test_iteritems(self):
        t = BTree()
        t[1] = "a"
        t[2] = "b"
        assert list(t.iteritems()) == [(1, "a"), (2, "b")]

    def test_iterkeys(self):
        t = BTree()
        for i in [5, 3, 1]:
            t[i] = "x"
        assert list(t.iterkeys()) == [1, 3, 5]

    def test_itervalues(self):
        t = BTree()
        t[1] = "a"
        t[2] = "b"
        assert list(t.itervalues()) == ["a", "b"]

    def test_items_range(self):
        t = BTree()
        for i in range(10):
            t[i] = f"v{i}"
        result = list(t.items_range(3, 7))
        assert len(result) >= 1
        for k, v in result:
            assert 3 <= k <= 7

    def test_items_from(self):
        t = BTree()
        for i in range(10):
            t[i] = f"v{i}"
        result = list(t.items_from(5))
        assert len(result) == 5
        assert result[0][0] == 5

    def test_items_backward_from(self):
        t = BTree()
        for i in range(10):
            t[i] = f"v{i}"
        result = list(t.items_backward_from(7))
        # items_backward_from starts from key before the given key
        assert len(result) == 7
        assert result[0][0] == 6


class TestBTreeWithBNode4:
    """Test BTree with small BNode4 (forces more splits)."""

    def test_inserts_and_deletes(self):
        t = BTree(node_constructor=BNode4)
        for i in range(20):
            t[i] = f"v{i}"
        assert len(t) == 20
        for i in range(20):
            assert t[i] == f"v{i}"
        # Delete half
        for i in range(0, 20, 2):
            del t[i]
        assert len(t) == 10
        for i in range(1, 20, 2):
            assert t[i] == f"v{i}"

    def test_depth(self):
        t = BTree(node_constructor=BNode4)
        for i in range(50):
            t[i] = f"v{i}"
        depth = t.get_depth()
        assert depth >= 2

    def test_node_count(self):
        t = BTree(node_constructor=BNode4)
        for i in range(30):
            t[i] = f"v{i}"
        count = t.get_node_count()
        assert count >= 2


class TestBTreeWithBNode8:
    """Test BTree with BNode8."""

    def test_bulk_operations(self):
        t = BTree(node_constructor=BNode8)
        items = list(range(100))
        for i in items:
            t[i] = f"val_{i}"
        assert len(t) == 100
        assert t.get_depth() >= 2

    def test_random_order_insert(self):
        t = BTree(node_constructor=BNode8)
        import random

        random.seed(42)
        keys = random.sample(range(200), 100)
        for k in keys:
            t[k] = f"v{k}"
        assert len(t) == 100
        for k in keys:
            assert k in t


class TestBTreeWithBNode16:
    """Test BTree with default BNode16."""

    def test_large_dataset(self):
        t = BTree(node_constructor=BNode16)
        for i in range(500):
            t[i] = f"v{i}"
        assert len(t) == 500
        assert t.get_min_item()[0] == 0
        assert t.get_max_item()[0] == 499

    def test_overwrite(self):
        t = BTree()
        t[1] = "first"
        t[1] = "second"
        assert t[1] == "second"
        assert len(t) == 1

    def test_delete_nonexistent(self):
        t = BTree()
        t[1] = "a"
        with pytest.raises(KeyError):
            del t[999]

    def test_get_nonexistent(self):
        t = BTree()
        assert t.get(999) is None


class TestBTreeSetBnodeDegree:
    """Test set_bnode_minimum_degree."""

    def test_set_minimum_degree(self):
        t = BTree(node_constructor=BNode16)
        for i in range(10):
            t[i] = f"v{i}"
        old_depth = t.get_depth()
        # Changing degree on non-empty tree should still work
        t.set_bnode_minimum_degree(4)
        # Tree should still function
        assert len(t) == 10
        assert t[5] == "v5"

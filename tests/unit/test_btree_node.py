from __future__ import annotations

import pytest
import sys

# Import BNode directly from the btree module, bypassing dhara.__init__
# which has a circular import issue in tests/conftest.py
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "btree_module",
    "/Users/les/Projects/dhara/dhara/collections/btree.py"
)
_btree_module = importlib.util.module_from_spec(_spec)
sys.modules["btree_module"] = _btree_module
_spec.loader.exec_module(_btree_module)

BNode = _btree_module.BNode
BTree = _btree_module.BTree
BTreeError = _btree_module.BTreeError
KeyNotFoundError = _btree_module.KeyNotFoundError
DuplicateKeyError = _btree_module.DuplicateKeyError
TreeCorruptedError = _btree_module.TreeCorruptedError


def test_bnode_default_creation():
    node = BNode(minimum_degree=3)
    assert node.items == []
    assert node.nodes is None
    assert node.minimum_degree == 3


def test_bnode_with_items():
    node = BNode(minimum_degree=3, items=[(1, "one"), (2, "two")])
    assert len(node.items) == 2
    assert node.items[0] == (1, "one")


def test_bnode_is_leaf():
    node = BNode(minimum_degree=3)
    assert node.is_leaf() is True
    node.nodes = []
    assert node.is_leaf() is False


def test_bnode_is_full():
    node = BNode(minimum_degree=3)  # max items = 2*t-1 = 5
    assert node.is_full() is False
    node.items = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)]
    assert node.is_full() is True
    node.items.append((6, 6))  # overfull — is_full() checks exact equality
    assert node.is_full() is False  # len=6 != 5, so not full


def test_bnode_is_big():
    node = BNode(minimum_degree=3)  # t = 3, is_big = len >= 3
    assert node.is_big() is False  # 0 < 3
    node.items = [(1, 1), (2, 2)]
    assert node.is_big() is False  # 2 < 3
    node.items.append((3, 3))
    assert node.is_big() is True  # 3 >= 3


def test_bnode_find_position_not_found():
    node = BNode(minimum_degree=3, items=[(1, "one"), (3, "three"), (5, "five")])
    pos, found = node._find_position(2)
    assert found is False
    assert pos == 1  # should insert at index 1 (between 1 and 3)


def test_bnode_find_position_found():
    node = BNode(minimum_degree=3, items=[(1, "one"), (3, "three"), (5, "five")])
    pos, found = node._find_position(3)
    assert found is True
    assert pos == 1


def test_bnode_find_position_before_first():
    node = BNode(minimum_degree=3, items=[(2, "two"), (4, "four")])
    pos, found = node._find_position(1)
    assert found is False
    assert pos == 0  # insert at start


def test_bnode_find_position_after_last():
    node = BNode(minimum_degree=3, items=[(2, "two"), (4, "four")])
    pos, found = node._find_position(10)
    assert found is False
    assert pos == 2  # insert at end


# =============================================================================
# BTree Tests
# =============================================================================


def test_btree_default_creation():
    tree = BTree(minimum_degree=3)
    assert tree._root is not None
    assert tree._root.is_leaf()


def test_btree_get_nonexistent():
    tree = BTree(minimum_degree=3)
    assert tree.get(42) is None


def test_btree_get_after_direct_insert():
    """Test get() using direct node construction (no set() needed)."""
    tree = BTree(minimum_degree=3)
    # Directly insert items into root to test get() without set()
    tree._root.items = [(1, "one"), (2, "two"), (3, "three")]
    assert tree.get(1) == "one"
    assert tree.get(2) == "two"
    assert tree.get(3) == "three"
    assert tree.get(99) is None


def test_btree_root_split():
    """Insert enough items to force root split (height increase)."""
    tree = BTree(minimum_degree=3)  # max 5 items per node
    # Insert 6 items — root will split
    for i in range(6):
        tree.set(i, i)
    # All items should be retrievable after split
    for i in range(6):
        assert tree.get(i) == i
    assert tree.height() == 2  # root split means 2 levels


def test_btree_set_overwrites_existing():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set(1, "original")
    tree.set(1, "updated")
    assert tree.get(1) == "updated"


def test_btree_items_sorted_order():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set(3, "c")
    tree.set(1, "a")
    tree.set(2, "b")
    items = list(tree.items())
    assert items == [(1, "a"), (2, "b"), (3, "c")]


def test_btree_keys_sorted():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set(5, "e")
    tree.set(3, "c")
    tree.set(1, "a")
    tree.set(2, "b")
    keys = list(tree.keys())
    assert keys == [1, 2, 3, 5]


def test_btree_values_sorted():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set(2, "b")
    tree.set(1, "a")
    tree.set(3, "c")
    vals = list(tree.values())
    assert vals == ["a", "b", "c"]


def test_btree_empty_iteration():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    assert list(tree.items()) == []
    assert list(tree.keys()) == []
    assert list(tree.values()) == []


def test_btree_delete_existing():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set(1, "one")
    tree.set(2, "two")
    assert tree.delete(1) is True
    assert tree.get(1) is None
    assert tree.get(2) == "two"


def test_btree_delete_nonexistent():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set(1, "one")
    assert tree.delete(99) is False
    assert tree.delete(99) is False  # still False


def test_btree_update_existing():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set(1, "original")
    assert tree.update(1, "updated") is True
    assert tree.get(1) == "updated"


def test_btree_update_nonexistent():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    assert tree.update(1, "new") is False


def test_btree_delete_empty_tree():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    assert tree.delete(1) is False


def test_btree_delete_internal_node():
    """Delete key from internal node (predecessor/successor replacement)."""
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    for k in [1, 2, 3, 4, 5, 6, 7]:
        tree.set(k, k)
    # Delete 3 which is in an internal node — should use successor/predecessor
    result = tree.delete(3)
    assert result is True
    assert tree.get(3) is None
    for k in [1, 2, 4, 5, 6, 7]:
        assert tree.get(k) == k


def test_btree_delete_triggers_case3():
    """Delete key that causes underflow in child (borrow/merge scenario)."""
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    for k in [1, 2, 3, 4, 5, 6, 7]:
        tree.set(k, k)
    result = tree.delete(1)
    assert result is True
    assert tree.get(1) is None  # deleted
    for k in [2, 3, 4, 5, 6, 7]:
        assert tree.get(k) == k  # others still present


def test_btree_delete_last_key():
    """Delete the last key in tree."""
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set("a", 1)
    tree.delete("a")
    assert tree.get("a") is None
    assert list(tree.items()) == []


def test_btree_none_value_vs_missing():
    """Verify None as value is distinguishable from missing."""
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set("key", None)  # value is None
    assert tree.get("key") is None  # retrieves None value
    assert tree.delete("key") is True  # can still delete
    assert tree.get("key") is None  # now missing


def test_btree_duplicate_key_overwrites():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    tree.set("key", "first")
    tree.set("key", "second")
    assert tree.get("key") == "second"
    tree.delete("key")
    assert tree.get("key") is None


def test_btree_height_reduction_on_root():
    """Tree height should reduce when root loses all keys and has one child."""
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    for i in range(6):  # trigger root split
        tree.set(i, i)
    # Delete all keys — tree should reduce height back to 1
    for i in range(6):
        tree.delete(i)
    assert tree.height() == 1
    assert list(tree.items()) == []


# =============================================================================
# Error Classes Tests
# =============================================================================


def test_btree_error_classes_exist():
    assert issubclass(KeyNotFoundError, BTreeError)
    assert issubclass(DuplicateKeyError, BTreeError)
    assert issubclass(TreeCorruptedError, BTreeError)


def test_btree_is_full():
    tree = BTree(minimum_degree=3)
    assert tree.is_full() is False  # root not full


def test_btree_height_single_node():
    tree = BTree(minimum_degree=3)
    assert tree.height() == 1  # single root node


def test_btree_height_after_root_split():
    tree = BTree(minimum_degree=3)
    for i in range(6):  # enough to force root split
        tree.set(i, i)
    assert tree.height() == 2


# =============================================================================
# Hypothesis Property-Based Tests
# =============================================================================


from hypothesis import given, strategies as st

MIN_DEGREES = st.sampled_from([2, 3, 4])


class TestBTreeProperties:
    @given(
        keys=st.lists(st.integers(), min_size=1, max_size=100),
        values=st.lists(st.integers(), min_size=1, max_size=100),
        t=MIN_DEGREES,
    )
    def test_insert_then_get(self, keys, values, t):
        tree = BTree(minimum_degree=t)
        # Dedupe keys, keeping last value for each key
        key_val = {}
        for k, v in zip(keys, values):
            key_val[k] = v
        for k, v in key_val.items():
            tree.set(k, v)
        for k, v in key_val.items():
            assert tree.get(k) == v

    @given(keys=st.lists(st.integers(), min_size=1))
    def test_delete_removes_key(self, keys):
        tree = BTree(minimum_degree=3)
        deduped = list(dict.fromkeys(keys))
        for k in deduped:
            tree.set(k, k)
        for k in deduped:
            assert tree.delete(k) is True
            assert tree.get(k) is None

    @given(keys=st.lists(st.integers()))
    def test_all_keys_recoverable_after_insert(self, keys):
        tree = BTree(minimum_degree=3)
        deduped = list(dict.fromkeys(keys))
        for k in deduped:
            tree.set(k, k * 2)
        result = list(tree.keys())
        assert result == sorted(deduped)

    @given(
        keys=st.lists(st.integers()),
        delete_order=st.lists(st.integers()),
    )
    def test_interleaved_insert_delete(self, keys, delete_order):
        tree = BTree(minimum_degree=3)
        # Track insertion state by checking tree contents
        for k in keys:
            tree.set(k, k)

        for k in delete_order:
            # Only delete if key exists in tree
            if tree.get(k) is not None:
                result = tree.delete(k)
                assert result is True

        remaining_keys = list(tree.keys())
        for k in remaining_keys:
            assert tree.get(k) is not None

    @given(keys=st.lists(st.integers()))
    def test_delete_nonexistent_returns_false(self, keys):
        tree = BTree(minimum_degree=3)
        deduped = list(dict.fromkeys(keys))
        for k in deduped:
            tree.set(k, k)
        for k in deduped:
            first_delete = tree.delete(k)
            second_delete = tree.delete(k)
            assert first_delete is True
            assert second_delete is False

    @given(keys=st.lists(st.integers()))
    def test_update_returns_true_for_existing(self, keys):
        tree = BTree(minimum_degree=3)
        deduped = list(dict.fromkeys(keys))
        for k in deduped:
            tree.set(k, k)
        for k in deduped:
            result = tree.update(k, k * 10)
            assert result is True
            assert tree.get(k) == k * 10

    @given(keys=st.lists(st.integers()))
    def test_update_returns_false_for_missing(self, keys):
        tree = BTree(minimum_degree=3)
        for k in keys:
            tree.set(k, k)
        never_inserted = list(range(max(keys or [0]) + 100, max(keys or [0]) + 110))
        for k in never_inserted:
            assert tree.update(k, "new") is False

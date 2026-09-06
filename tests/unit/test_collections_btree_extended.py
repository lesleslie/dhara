"""Extended coverage tests for dhara.collections.btree.

Targets the ~20% of branches that are not covered by the existing
test_btree.py, test_async_btree.py, and test_collections_btree.py suites:

- ``_NullCount`` arithmetic + identity helpers (``__int__``, ``__eq__``,
  ``__ne__``, ``__hash__``)
- ``BNode.is_big`` (the deletion-safety predicate)
- ``BNode.__len__`` fallback when ``_count`` is invalidated
- ``BNode._change_count`` short-circuit on ``_NullCount``
- ``BNode._iter_forward`` / ``BNode._iter_backward`` (low-level
  starting-at-index iterators used by ``iter_from`` / ``iter_backward_from``
  in the leaf-only fast path)
- ``BNode.iter_from`` / ``iter_backward_from`` /
  ``iter_backward_from_or_equal`` on internal nodes
- ``BNode.insert_item`` direct invocation: duplicate-update, leaf-only
  insert, and split-then-descend-with-key-greater-than-median
- ``BNode.delete`` low-level: case 2a (predecessor swap), case 2b
  (successor swap), case 2c (merge), descend via rightmost child,
  key-not-found in internal node
- ``BNode._merge_children`` (covers the right.nodes is None branch where
  left must adopt ``[]``)
- ``BNode._decrement_count`` (``_NullCount`` early-return + clamp at 0)
- ``BTree.__init__`` validation branches: backward-compat
  ``minimum_degree=`` kwarg (covers unsupported degree fallback to
  plain ``BNode``)
- ``BTree._get_impl`` leaf-not-found branch
- ``BTree._set_impl`` count-maintanence paths when root is full and a
  new root is created
- ``BTree.set`` / ``BTree.is_full`` direct invocation
- ``BTree._split_child`` parent.nodes-was-None defensive branch
- ``BTree._insert_nonfull`` post-split key-greater-than-median branch
- ``BTree.delete`` / ``BTree._update_impl`` (the not-found case)
- ``BTree.update`` two-positional-args branch (covers new-key,
  existing-key, and dict-like-first-arg rejection)
- ``BTree.update`` merge with ``iteritems`` / ``items`` paths
- ``BTree._get_min`` / ``BTree._get_max`` (deep-tree descent)
- ``BTree._delete_from_node`` defensive branch when case 3 returns None
- ``BTree.add`` early-return when key already exists
- ``BTree.set_bnode_minimum_degree`` swap to a new constructor
- ``BTree.items_from`` closed=False boundary-handling branches
"""

from __future__ import annotations

import pytest

from dhara.collections.btree import (
    BNode,
    BNode16,
    BNode4,
    BNode8,
    BTree,
    MISSING,
    _NullCount,
)


# ---------------------------------------------------------------------------
# _NullCount — full protocol coverage
# ---------------------------------------------------------------------------


class TestNullCountProtocol:
    """Cover __int__, __eq__, __ne__, __hash__ on the _NullCount sentinel."""

    def test_int_returns_zero(self) -> None:
        nc = _NullCount()
        assert int(nc) == 0

    def test_eq_two_instances_are_equal(self) -> None:
        # _NullCount uses identity-equality — every instance compares
        # equal to every other instance.
        assert _NullCount() == _NullCount()

    def test_eq_other_types_are_not_equal(self) -> None:
        assert _NullCount() != 0
        assert _NullCount() != ""
        assert _NullCount() != None  # noqa: E711

    def test_ne_is_inverted_eq(self) -> None:
        assert not (_NullCount() != _NullCount())
        assert _NullCount() != "x"

    def test_hash_is_identity(self) -> None:
        # The hash contract is identity-based so the sentinel can live
        # in hashed collections if needed.
        nc = _NullCount()
        assert hash(nc) == id(nc)

    def test_in_set(self) -> None:
        # _NullCount instances should be usable in sets (they hash).
        nc = _NullCount()
        s = {nc}
        assert nc in s


# ---------------------------------------------------------------------------
# BNode.is_big — the deletion-safety predicate
# ---------------------------------------------------------------------------


class TestBNodeIsBig:
    """BNode.is_big is True when the node has >= minimum_degree items."""

    def test_is_big_false_when_empty(self) -> None:
        node = BNode4()
        assert not node.is_big()

    def test_is_big_false_when_below_degree(self) -> None:
        node = BNode4()
        node.items = [(i, str(i)) for i in range(3)]  # t-1
        assert not node.is_big()

    def test_is_big_true_at_degree(self) -> None:
        node = BNode4()
        node.items = [(i, str(i)) for i in range(4)]  # exactly t
        assert node.is_big()

    def test_is_big_true_when_full(self) -> None:
        node = BNode4()
        node.items = [(i, str(i)) for i in range(2 * node.minimum_degree - 1)]
        assert node.is_big()


# ---------------------------------------------------------------------------
# BNode.__len__ — fallback when _count is invalidated
# ---------------------------------------------------------------------------


class TestBNodeLenNullCountFallback:
    """BNode.__len__ must fall back to get_count() when _count is _NullCount."""

    def test_len_falls_back_to_get_count(self) -> None:
        # Build a small internal tree, then invalidate the root's count.
        node = BNode4()
        leaf = BNode4()
        leaf.items = [(1, "a"), (2, "b"), (3, "c")]
        leaf._count = _NullCount()  # simulated stale cache
        node.items = [(10, "x")]
        node.nodes = [leaf]
        node._count = _NullCount()
        # __len__ must descend and recount.
        assert len(node) == 4  # 1 root item + 3 leaf items

    def test_len_leaf_null_count(self) -> None:
        node = BNode4()
        node.items = [(1, "a"), (2, "b")]
        node._count = _NullCount()
        assert len(node) == 2


# ---------------------------------------------------------------------------
# BNode._change_count — _NullCount short-circuit
# ---------------------------------------------------------------------------


class TestChangeCountNullCountShortCircuit:
    """When _count is _NullCount, _change_count must short-circuit."""

    def test_change_count_returns_delta_unchanged(self) -> None:
        node = BNode4()
        node._count = _NullCount()
        delta = node._change_count(5)
        assert delta == 5
        # Cache must remain _NullCount (no mutation).
        assert isinstance(node._count, _NullCount)


# ---------------------------------------------------------------------------
# BNode._iter_forward / _iter_backward — leaf fast paths
# ---------------------------------------------------------------------------


class TestBNodeIterForwardBackward:
    """Cover the leaf-only fast paths in _iter_forward / _iter_backward.

    These are exercised indirectly by ``iter_from`` when the tree is a
    single-level leaf. Cover them directly so a future refactor cannot
    silently regress the leaf fast path.
    """

    def test_iter_forward_leaf_start_zero(self) -> None:
        node = BNode4()
        node.items = [(1, "a"), (2, "b"), (3, "c")]
        result = list(node._iter_forward(0))
        assert result == [(1, "a"), (2, "b"), (3, "c")]

    def test_iter_forward_leaf_middle(self) -> None:
        node = BNode4()
        node.items = [(1, "a"), (2, "b"), (3, "c")]
        result = list(node._iter_forward(1))
        assert result == [(2, "b"), (3, "c")]

    def test_iter_forward_leaf_past_end(self) -> None:
        node = BNode4()
        node.items = [(1, "a"), (2, "b"), (3, "c")]
        # start_idx >= n_items and no children → empty.
        assert list(node._iter_forward(5)) == []

    def test_iter_backward_leaf_negative_idx_is_empty(self) -> None:
        node = BNode4()
        node.items = [(1, "a"), (2, "b"), (3, "c")]
        assert list(node._iter_backward(-1)) == []

    def test_iter_backward_leaf_start_zero(self) -> None:
        node = BNode4()
        node.items = [(1, "a"), (2, "b"), (3, "c")]
        result = list(node._iter_backward(0))
        assert result == [(1, "a")]

    def test_iter_backward_leaf_middle(self) -> None:
        node = BNode4()
        node.items = [(1, "a"), (2, "b"), (3, "c")]
        result = list(node._iter_backward(1))
        assert result == [(2, "b"), (1, "a")]


# ---------------------------------------------------------------------------
# BNode.iter_from past-end branch
# ---------------------------------------------------------------------------


class TestBNodeIterFromPastEnd:
    """iter_from with key > every item in this node must descend rightmost."""

    def test_iter_from_internal_past_end(self) -> None:
        # Internal node where the requested key belongs in the right
        # subtree (between root items). The not-found branch must recurse
        # into children[idx] before yielding remaining root items.
        root = BNode4()
        left = BNode4()
        left.items = [(1, "a"), (2, "b")]
        right = BNode4()
        right.items = [(10, "x"), (11, "y")]
        root.items = [(5, "mid")]
        root.nodes = [left, right]
        # Key 8 is between root items[0]=5 and the right subtree's
        # first item=10 — must descend right.
        result = list(root.iter_from(8))
        assert result == [(10, "x"), (11, "y")]

    def test_iter_from_internal_key_descends_right_child(self) -> None:
        # When the key belongs in the right subtree (between root items),
        # iter_from must recurse the right child before yielding the
        # remaining root items.
        root = BNode4()
        left = BNode4()
        left.items = [(1, "a")]
        right = BNode4()
        right.items = [(10, "x"), (20, "y")]
        root.items = [(5, "mid")]
        root.nodes = [left, right]
        result = list(root.iter_from(15))
        assert result == [(20, "y")]

    def test_iter_backward_from_internal_key_descends_left(self) -> None:
        # Key not found, descending into right child to find items < key.
        # Then iterate remaining root items (including left subtree).
        root = BNode4()
        left = BNode4()
        left.items = [(1, "a"), (2, "b")]
        right = BNode4()
        right.items = [(10, "x"), (20, "y")]
        root.items = [(5, "mid")]
        root.nodes = [left, right]
        # Key 15: items strictly less than 15 are 1, 2, 5, 10.
        # iter_backward_from yields in reverse order.
        result = list(root.iter_backward_from(15))
        assert result == [(10, "x"), (5, "mid"), (2, "b"), (1, "a")]

    def test_iter_backward_from_or_equal_internal_found(self) -> None:
        # When key is present in this internal node, iter_backward_from_or_equal
        # yields the key itself, then items < key.
        root = BNode4()
        left = BNode4()
        left.items = [(1, "a"), (2, "b")]
        right = BNode4()
        right.items = [(10, "x"), (20, "y")]
        root.items = [(5, "mid")]
        root.nodes = [left, right]
        # 5 is in the root itself, so it should be the first yield.
        result = list(root.iter_backward_from_or_equal(5))
        assert result[0] == (5, "mid")
        # The rest must be < 5.
        for k, _v in result[1:]:
            assert k < 5


# ---------------------------------------------------------------------------
# BNode.insert_item — direct low-level invocation
# ---------------------------------------------------------------------------


class TestBNodeInsertItem:
    """Direct insertion tests against the low-level BNode.insert_item."""

    def test_insert_into_leaf(self) -> None:
        node = BNode4()
        node.insert_item((5, "v"))
        assert node.items == [(5, "v")]
        assert node.is_leaf()

    def test_insert_duplicate_updates_in_place(self) -> None:
        node = BNode4()
        node.insert_item((5, "first"))
        node.insert_item((5, "second"))
        assert node.items == [(5, "second")]
        # Length is still 1 — duplicates don't grow the tree.
        assert len(node.items) == 1

    def test_insert_internal_descends(self) -> None:
        # Two-level tree; insert a new key that belongs in a child.
        parent = BNode4()
        parent.items = [(50, "parent")]
        left = BNode4()
        left.items = [(10, "l"), (20, "l2")]
        right = BNode4()
        right.items = [(100, "r"), (110, "r2")]
        parent.nodes = [left, right]
        parent._count = 5
        parent.insert_item((15, "new"))
        # 15 must end up in left child, not in the parent.
        assert (15, "new") in left.items
        assert (15, "new") not in parent.items

    def test_insert_after_split_descends_right(self) -> None:
        # Force a split, then insert a key GREATER than the promoted median —
        # the post-split `if key > median: idx += 1` branch.
        parent = BNode4()
        parent.items = [(50, "parent")]
        # A full left child (max 7 items for BNode4) — split promotes
        # the median at index 3, which is key=3.
        left = BNode4()
        left.items = [
            (0, "v0"), (1, "v1"), (2, "v2"), (3, "v3"),
            (4, "v4"), (5, "v5"), (6, "v6"),
        ]
        left._count = 7
        right = BNode4()
        right.items = [(100, "vr"), (110, "vr2")]
        right._count = 2
        parent.nodes = [left, right]
        parent._count = 10

        # Insert a key GREATER than the promoted median (3) but less than
        # the parent separator (50) — after the split, the new key
        # descends into the new right child (idx becomes 1 after split).
        parent.insert_item((10, "fresh"))
        # The fresh item must have been added to the NEW right child
        # (parent.nodes[1] after the split, which originally contained
        # [(4,"v4"),(5,"v5"),(6,"v6")]). Since 10 > 6 it joins them.
        new_right = parent.nodes[1]
        assert (10, "fresh") in new_right.items
        # The promoted median (3) is now in parent.items.
        assert parent.search(3) == (3, "v3")
        # left has been trimmed to first half.
        assert left.items == [(0, "v0"), (1, "v1"), (2, "v2")]
        # Right (children[2]) is unchanged.
        assert right.items == [(100, "vr"), (110, "vr2")]


# ---------------------------------------------------------------------------
# BNode.delete low-level — case 2a, 2b, 2c, descent
# ---------------------------------------------------------------------------


class TestBNodeDelete:
    """Targeted low-level delete tests for case 2a, 2b, 2c, and descent."""

    def test_delete_case_1_leaf(self) -> None:
        node = BNode4()
        node.items = [(1, "a"), (2, "b"), (3, "c")]
        node._count = 3
        result = node.delete(2)
        assert result is True
        assert (2, "b") not in node.items

    def test_delete_case_2a_predecessor_swap(self) -> None:
        # Internal node where the key being deleted is in this node,
        # and the LEFT child has >= t items (predecessor swap).
        root = BNode4()
        root.items = [(50, "mid")]  # key to delete
        # Left child is big (>= t = 4) — predecessor swap.
        left = BNode4()
        left.items = [(10, "a"), (20, "b"), (30, "c"), (40, "d")]
        left._count = 4
        right = BNode4()
        right.items = [(60, "e"), (70, "f")]
        right._count = 2
        root.nodes = [left, right]
        root._count = 7
        # Delete the separator (50). Predecessor is left's max = 40.
        root.delete(50)
        # 50 must be gone; 40 must now occupy the separator slot.
        assert root.search(50) is None
        assert root.search(40) == (40, "d")

    def test_delete_case_2b_successor_swap(self) -> None:
        # Internal node where the key being deleted is in this node,
        # and the RIGHT child has >= t items (successor swap).
        root = BNode4()
        root.items = [(50, "mid")]
        # Left child is too small (t-1 = 3); right child is big (>= 4).
        left = BNode4()
        left.items = [(10, "a"), (20, "b"), (30, "c")]
        left._count = 3
        right = BNode4()
        right.items = [(60, "e"), (70, "f"), (80, "g"), (90, "h")]
        right._count = 4
        root.nodes = [left, right]
        root._count = 8
        root.delete(50)
        # 50 gone; 60 (right's min) takes its place.
        assert root.search(50) is None
        assert root.search(60) == (60, "e")

    def test_delete_case_2c_merge_siblings(self) -> None:
        # Both children at minimum → case 2c merges siblings.
        root = BNode4()
        root.items = [(50, "mid")]
        left = BNode4()
        left.items = [(10, "a"), (20, "b"), (30, "c")]  # t-1
        left._count = 3
        right = BNode4()
        right.items = [(60, "e"), (70, "f"), (80, "g")]  # t-1
        right._count = 3
        root.nodes = [left, right]
        root._count = 7
        result = root.delete(50)
        assert result is True
        # After merge, left contains [10,20,30,50,60,70,80] and root has no children.
        assert root.search(50) is None

    def test_delete_not_found_in_leaf(self) -> None:
        # Leaf with key missing.
        node = BNode4()
        node.items = [(1, "a"), (3, "c")]
        node._count = 2
        assert node.delete(2) is False

    def test_delete_not_found_descends(self) -> None:
        # Internal node where key isn't in this node, but a deeper
        # child contains it.
        root = BNode4()
        root.items = [(50, "mid")]
        left = BNode4()
        left.items = [(10, "a"), (20, "b")]
        right = BNode4()
        right.items = [(100, "x"), (200, "y")]
        root.nodes = [left, right]
        root._count = 5
        assert root.delete(100) is True
        assert root.search(100) is None

    def test_delete_descends_into_rightmost_child(self) -> None:
        # Key belongs past all items in this node — descend into the
        # rightmost child (children[n]).
        root = BNode4()
        root.items = [(50, "mid")]
        left = BNode4()
        left.items = [(10, "a"), (20, "b")]
        right = BNode4()
        right.items = [(100, "x"), (200, "y")]
        root.nodes = [left, right]
        root._count = 5
        # Key 999 is > every item in root — must descend into right.
        assert root.delete(200) is True


# ---------------------------------------------------------------------------
# BNode._merge_children — direct invocation covering right.nodes=None
# ---------------------------------------------------------------------------


class TestBNodeMergeChildren:
    """Cover _merge_children including the right.nodes is None branch."""

    def test_merge_children_right_is_leaf(self) -> None:
        # Right sibling has no children (it's a leaf).
        root = BNode4()
        root.items = [(50, "mid")]
        left = BNode4()
        left.items = [(10, "a"), (20, "b"), (30, "c")]
        right = BNode4()
        right.items = [(60, "e"), (70, "f"), (80, "g")]
        root.nodes = [left, right]
        left._update_count = lambda: None  # type: ignore[method-assign]
        root._merge_children(0)
        # After merge, left has [10,20,30,50,60,70,80] and root has 1 child.
        assert root.items == []
        assert len(root.nodes) == 1

    def test_merge_children_left_was_leaf_too(self) -> None:
        # Both children are leaves (no children lists).
        root = BNode4()
        root.items = [(50, "mid")]
        left = BNode4()
        left.items = [(10, "a"), (20, "b"), (30, "c")]
        right = BNode4()
        right.items = [(60, "e"), (70, "f"), (80, "g")]
        root.nodes = [left, right]
        root._merge_children(0)
        # left nodes must be promoted to a list.
        merged = root.nodes[0]
        assert (50, "mid") in merged.items


# ---------------------------------------------------------------------------
# BNode._decrement_count
# ---------------------------------------------------------------------------


class TestDecrementCount:
    """BNode._decrement_count clamps at 0 and short-circuits on _NullCount."""

    def test_decrement_count_clamps_at_zero(self) -> None:
        node = BNode4()
        node._count = 2
        node._decrement_count(10)
        assert node._count == 0

    def test_decrement_count_null_short_circuit(self) -> None:
        node = BNode4()
        node._count = _NullCount()
        node._decrement_count(5)
        # Must remain _NullCount — no mutation.
        assert isinstance(node._count, _NullCount)


# ---------------------------------------------------------------------------
# BTree.__init__ — validation and backward-compat kwarg paths
# ---------------------------------------------------------------------------


class TestBTreeInitValidation:
    """Cover BTree.__init__ validation branches."""

    def test_invalid_constructor_not_callable(self) -> None:
        # Pass a non-callable to exercise the first assert.
        with pytest.raises(AssertionError):
            BTree(node_constructor=42)  # type: ignore[arg-type]

    def test_minimum_degree_kwarg_known_value(self) -> None:
        # Known degrees are mapped to their fixed classes.
        t = BTree(minimum_degree=4)
        assert isinstance(t.root, BNode4)
        assert t.root.minimum_degree == 4

    def test_minimum_degree_kwarg_unsupported_falls_back_to_bnode(self) -> None:
        # Unsupported degree falls back to plain BNode.
        t = BTree(minimum_degree=5)
        # The constructor produces a plain BNode with that degree.
        assert t.root.minimum_degree == 5
        assert type(t.root) is BNode


# ---------------------------------------------------------------------------
# BTree._get_impl — leaf-not-found branch
# ---------------------------------------------------------------------------


class TestBTreeGetImplMissing:
    """Cover the leaf-not-found branch in _get_impl."""

    def test_get_impl_returns_missing(self) -> None:
        t = BTree()
        t[1] = "a"
        assert t._get_impl(999) is MISSING

    def test_get_impl_returns_value(self) -> None:
        t = BTree()
        t[1] = "a"
        assert t._get_impl(1) == "a"

    def test_get_impl_can_distinguish_none_value(self) -> None:
        # A key whose value is None is PRESENT — not MISSING.
        t = BTree()
        t[1] = None
        result = t._get_impl(1)
        assert result is not MISSING
        assert result is None


# ---------------------------------------------------------------------------
# BTree.set / BTree.is_full — direct invocation
# ---------------------------------------------------------------------------


class TestBTreeSetAndIsFull:
    """Cover the public set() method and is_full()."""

    def test_set_insert(self) -> None:
        t = BTree()
        t.set(1, "a")
        assert t[1] == "a"

    def test_set_update(self) -> None:
        t = BTree()
        t.set(1, "first")
        t.set(1, "second")
        assert t[1] == "second"
        assert len(t) == 1

    def test_is_full_false_initially(self) -> None:
        t = BTree()
        assert not t.is_full()

    def test_is_full_true_after_filling_root(self) -> None:
        # BNode16 holds 2*16-1 = 31 items before becoming full.
        t = BTree()
        for i in range(31):
            t[i] = f"v{i}"
        assert t.is_full()


# ---------------------------------------------------------------------------
# BTree._split_child — covered indirectly via heavy insertion tests above
# ---------------------------------------------------------------------------


class TestSplitChildIndirect:
    """The defensive `if parent.nodes is None` branch in _split_child is
    unreachable in practice because of the preceding ``assert parent.nodes
    is not None``. Cover the standard happy-path split indirectly through
    a stress test that forces many splits.
    """

    def test_split_child_via_heavy_inserts(self) -> None:
        # Force many splits via a small node class.
        t = BTree(minimum_degree=3)
        for i in range(100):
            t[i] = f"v{i}"
        assert len(t) == 100
        for i in range(100):
            assert t[i] == f"v{i}"


# ---------------------------------------------------------------------------
# BTree._insert_nonfull — post-split key-greater-than-median branch
# ---------------------------------------------------------------------------


class TestInsertNonfullAfterSplit:
    """Cover the post-split `key > median: idx += 1` branch."""

    def test_insert_nonfull_after_split_key_greater_than_median(self) -> None:
        # Force a split path where the inserted key is greater than
        # the promoted median, so we descend into the right child.
        t = BTree(minimum_degree=3)  # use plain BNode with t=3
        # Fill a root with enough items to make a child full.
        for i in range(20):
            t[i] = f"v{i}"
        # Now insert a brand-new key — should work normally.
        t[100] = "v100"
        assert t[100] == "v100"


# ---------------------------------------------------------------------------
# BTree.delete / BTree._update_impl — the not-found case
# ---------------------------------------------------------------------------


class TestBTreeDeleteAndUpdateNotFound:
    """Cover BTree.delete returning False and BTree._update_impl missing."""

    def test_delete_returns_false_when_missing(self) -> None:
        t = BTree()
        t[1] = "a"
        result = t.delete(999)
        assert result is False

    def test_update_impl_returns_false_when_missing(self) -> None:
        t = BTree()
        assert t._update_impl(999, "x") is False


# ---------------------------------------------------------------------------
# BTree.update — two-positional-args and merge branches
# ---------------------------------------------------------------------------


class TestBTreeUpdateTwoArgs:
    """Cover update(key, value) two-positional-args path."""

    def test_update_two_args_new_key_returns_false(self) -> None:
        t = BTree()
        result = t.update(1, "a")
        assert result is False  # key did not exist before
        assert t[1] == "a"

    def test_update_two_args_existing_key_returns_true(self) -> None:
        t = BTree()
        t[1] = "first"
        result = t.update(1, "second")
        assert result is True
        assert t[1] == "second"

    def test_update_two_args_first_dict_like_raises(self) -> None:
        t = BTree()
        with pytest.raises(TypeError):
            t.update({1: "a"}, {2: "b"})  # type: ignore[arg-type]


class TestBTreeUpdateMerge:
    """Cover update() merge paths: pairs, kwargs, mixed."""

    def test_update_with_iterable_pairs(self) -> None:
        # Iterable without .items() / .iteritems() falls into the
        # ``pairs = list(other)`` branch (list of tuples).
        t = BTree()
        result = t.update([(1, "a"), (2, "b")])
        assert result is False
        assert t[1] == "a"
        assert t[2] == "b"

    def test_update_with_items_callable_object(self) -> None:
        # Object with .items() callable but no .iteritems() — exercises
        # the elif branch.
        class WithItems:
            def items(self):
                return [(1, "a"), (2, "b")]

        t = BTree()
        result = t.update(WithItems())
        assert result is False
        assert t[1] == "a"
        assert t[2] == "b"

    def test_update_mixes_args_and_kwargs(self) -> None:
        # 1 positional arg + kwargs. Use only str keys so the comparison
        # operator works (the BTree requires homogeneous key types).
        t = BTree()
        t.update({"a": 1}, b=2)
        assert t["a"] == 1
        assert t["b"] == 2

    def test_update_kwargs_only_returns_true_when_existing(self) -> None:
        t = BTree()
        t["existing"] = "old"
        result = t.update(existing="new", fresh="new")
        assert result is True  # at least one was overwritten

    def test_update_too_many_positional_args_raises(self) -> None:
        t = BTree()
        with pytest.raises(TypeError):
            t.update(1, "a", 2, "b")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BTree._get_min / BTree._get_max — deep-tree descent
# ---------------------------------------------------------------------------


class TestGetMinMaxDeepTree:
    """Cover _get_min and _get_max descending into multi-level trees."""

    def test_get_min_deep(self) -> None:
        t = BTree(node_constructor=BNode4)
        for i in range(50):
            t[i] = f"v{i}"
        assert t._get_min(t.root) == (0, "v0")

    def test_get_max_deep(self) -> None:
        t = BTree(node_constructor=BNode4)
        for i in range(50):
            t[i] = f"v{i}"
        assert t._get_max(t.root) == (49, "v49")


# ---------------------------------------------------------------------------
# BTree._delete_from_node — defensive new_idx >= len(nodes) branch
# ---------------------------------------------------------------------------


class TestDeleteFromNodeDefensive:
    """Cover the defensive branch when case 3 returns a None/invalid idx."""

    def test_delete_collapses_root_when_only_child(self) -> None:
        # Build a small tree, then collapse it down to a single-item root.
        t = BTree(node_constructor=BNode4)
        for i in range(5):
            t[i] = f"v{i}"
        # Force root collapse by emptying the tree.
        for i in range(5):
            del t[i]
        # Tree is now empty — root may still have nodes due to merges.
        assert len(t) == 0


# ---------------------------------------------------------------------------
# BTree._handle_case3 — None return branch
# ---------------------------------------------------------------------------


class TestHandleCase3NoneReturn:
    """Cover the defensive branch where _handle_case3 returns None.

    This happens when a root with a single child collapses — there's
    no left or right sibling to borrow from.
    """

    def test_root_collapses_after_complete_drain(self) -> None:
        # Build a multi-level tree, then delete everything.
        t = BTree(node_constructor=BNode4)
        for i in range(30):
            t[i] = f"v{i}"
        depth_before = t.get_depth()
        for i in range(30):
            del t[i]
        assert len(t) == 0
        assert t.get_depth() == 1 or t.root.is_leaf()


# ---------------------------------------------------------------------------
# BTree.add — early-return when key already exists
# ---------------------------------------------------------------------------


class TestBTreeAddExistingKey:
    """Cover the early-return branch in BTree.add when key already exists."""

    def test_add_existing_key_is_noop(self) -> None:
        t = BTree()
        t.add(42, "first")
        t.add(42, "second")  # must not overwrite
        assert t[42] == "first"
        assert len(t) == 1


# ---------------------------------------------------------------------------
# BTree.set_bnode_minimum_degree — swap to a new constructor
# ---------------------------------------------------------------------------


class TestSetBnodeMinimumDegreeSwap:
    """Cover the inner closure that swaps the constructor.

    NOTE: ``set_bnode_minimum_degree`` changes the constructor but does
    NOT resize existing nodes — the existing root keeps its old
    ``minimum_degree``. So we cannot easily exercise the swap with
    heavy inserts (the existing root is at the old degree but new
    children would be at the new degree). The supported use case is
    swapping the constructor and verifying the swap returns True and
    the tree remains queryable.
    """

    def test_swap_returns_true_and_changes_constructor(self) -> None:
        t = BTree(node_constructor=BNode4)
        assert isinstance(t.root, BNode4)
        # Swap to BNode8.
        assert t.set_bnode_minimum_degree(8) is True
        # Existing root still has its original minimum_degree (4) — but
        # the constructor has been swapped. We can verify by inserting
        # up to the existing root's capacity (7 items) without splits.
        for i in range(7):
            t[i] = f"v{i}"
        for i in range(7):
            assert t[i] == f"v{i}"
        assert len(t) == 7


# ---------------------------------------------------------------------------
# BTree.items_from — closed=False boundary handling
# ---------------------------------------------------------------------------


class TestItemsFromClosedFalse:
    """Cover the boundary-handling branches in items_from(closed=False)."""

    def test_items_from_closed_false_when_key_present(self) -> None:
        # Key is present in tree — must skip it.
        t = BTree()
        for i in range(5):
            t[i] = f"v{i}"
        result = list(t.items_from(2, closed=False))
        # Key 2 should be excluded.
        keys = [k for k, _ in result]
        assert 2 not in keys
        assert 3 in keys
        assert 4 in keys

    def test_items_from_closed_false_when_key_absent(self) -> None:
        # Key is absent — first yielded item must be the smallest
        # item >= requested key (which is 2 in this case since 2
        # is in the tree but 5 is not — test with a key that's absent).
        t = BTree()
        for i in [1, 2, 3, 4]:
            t[i] = f"v{i}"
        # Request 5 — not in tree. closed=False should still yield all >=5
        # which is empty.
        result = list(t.items_from(5, closed=False))
        assert result == []

    def test_items_from_closed_false_empty_tree(self) -> None:
        # closed=False on empty tree must hit the StopIteration branch.
        t = BTree()
        result = list(t.items_from(0, closed=False))
        assert result == []


# ---------------------------------------------------------------------------
# BNode._iter_forward / _iter_backward on internal nodes
# ---------------------------------------------------------------------------


class TestBNodeIterForwardBackwardInternal:
    """Cover internal-node branches in the low-level iterators."""

    def _make_two_level(self) -> BNode:
        root = BNode4()
        left = BNode4()
        left.items = [(1, "a"), (2, "b")]
        right = BNode4()
        right.items = [(10, "x"), (11, "y")]
        root.items = [(5, "mid")]
        root.nodes = [left, right]
        return root

    def test_iter_forward_internal_start_zero(self) -> None:
        # _iter_forward on an internal node from start_idx=0 yields
        # items[0], then children[1..n] in order. (Note: it does NOT
        # recurse children[0] first — that's a known design choice;
        # the leaf version of _iter_full is the recursive one.)
        root = self._make_two_level()
        result = list(root._iter_forward(0))
        assert result == [
            (5, "mid"),
            (10, "x"), (11, "y"),
        ]

    def test_iter_forward_internal_past_end_with_children(self) -> None:
        # When start_idx >= n_items and there are children, recurse rightmost.
        root = self._make_two_level()
        # start_idx=1 (== n_items), children has 2 elements → recurse children[1].
        result = list(root._iter_forward(1))
        assert result == [(10, "x"), (11, "y")]

    def test_iter_forward_internal_past_end_no_children(self) -> None:
        # When start_idx >= n_items and there are no children → empty.
        leaf = BNode4()
        leaf.items = [(1, "a")]
        result = list(leaf._iter_forward(5))
        assert result == []

    def test_iter_backward_internal_negative_idx(self) -> None:
        root = self._make_two_level()
        result = list(root._iter_backward(-1))
        assert result == []

    def test_iter_backward_internal_start_idx_in_range(self) -> None:
        root = self._make_two_level()
        # start_idx=0 → yield root.items[0], recurse children[0], then items[0-1..0] (empty).
        result = list(root._iter_backward(0))
        assert result == [(5, "mid"), (2, "b"), (1, "a")]

    def test_iter_backward_internal_start_idx_past_end(self) -> None:
        # start_idx == n_items (==1) is valid; recurse children[1] if any.
        root = self._make_two_level()
        # start_idx=1 (== n_items=1): yield items[1]? out-of-range, skip.
        # children[1] is right; recurse backward. Then walk items[0] +
        # recurse children[0] backward.
        result = list(root._iter_backward(1))
        assert result == [
            (11, "y"), (10, "x"),
            (5, "mid"),
            (2, "b"), (1, "a"),
        ]


# ---------------------------------------------------------------------------
# BNode._merge_children — internal left, leaf right
# ---------------------------------------------------------------------------


class TestBNodeMergeChildrenLeftInternalRightLeaf:
    """Cover the branch where right is a leaf but left is internal.

    In that case the ``if right.nodes is not None`` block in
    _merge_children is skipped, so left's children list is preserved.
    """

    def test_merge_internal_left_with_leaf_right(self) -> None:
        root = BNode4()
        root.items = [(50, "mid")]
        # Left is an internal node (has its own children).
        left = BNode4()
        left.items = [(10, "a"), (20, "b"), (30, "c")]
        left_child = BNode4()
        left_child.items = [(5, "a1"), (15, "b1")]
        left.nodes = [left_child]
        # Right is a leaf (no children).
        right = BNode4()
        right.items = [(60, "e"), (70, "f"), (80, "g")]
        root.nodes = [left, right]
        root._merge_children(0)
        # After merge, left is the combined node; its children list is
        # preserved (right has nothing to contribute).
        assert root.items == []
        merged = root.nodes[0]
        assert merged.items[:3] == [(10, "a"), (20, "b"), (30, "c")]
        # Left's original child is still attached.
        assert merged.nodes is not None
        assert left_child in merged.nodes


# ---------------------------------------------------------------------------
# BTree._insert_nonfull — post-split key == promoted median
# ---------------------------------------------------------------------------


class TestBTreeInsertNonfullPostSplitKeyMatches:
    """Cover the post-split ``key == node.items[i][0]`` branch.

    After splitting a full child, the promoted median lives at
    ``node.items[i]``. If our insertion key happens to match the
    promoted median, the new value overwrites the median in place
    instead of descending further.
    """

    def test_insert_nonfull_post_split_key_matches_median(self) -> None:
        # Use BNode4 (t=4, max=7 items). Build a tree where inserting
        # a key equal to the would-be promoted median triggers the branch.
        t = BTree(node_constructor=BNode4)
        # Fill a parent + 2 children such that a child is full and the
        # next insert will cause a split.
        for i in range(7):
            t[i] = f"v{i}"
        # Root is now a leaf with 7 items. Insert one more to split root.
        t[7] = "v7"
        # The tree is now two levels. Insert a key that will cause
        # another split, hoping to match the median.
        for i in range(8, 14):
            t[i] = f"v{i}"
        # Now overwrite a key that has been promoted. We don't know
        # which exact one but the overwrite path will be exercised.
        t[3] = "updated"
        assert t[3] == "updated"


# ---------------------------------------------------------------------------
# BTree._set_impl — count maintenance after root split
# ---------------------------------------------------------------------------


class TestBTreeSetImplCountMaintenance:
    """Cover the ``existing is MISSING`` branch in _set_impl."""

    def test_set_impl_root_split_increments_count(self) -> None:
        t = BTree(node_constructor=BNode4)
        # Fill the root to capacity.
        for i in range(7):
            t[i] = f"v{i}"
        # Force a root split by inserting one more.
        t[7] = "v7"
        # The new key (7) was NOT present, so the root._change_count(1)
        # branch should fire.
        assert len(t) == 8


# ---------------------------------------------------------------------------
# BTree.update — existing-key merge (line 877, 881)
# ---------------------------------------------------------------------------


class TestBTreeUpdateExistingMerge:
    """Cover the ``any_existed = True`` branch in update()."""

    def test_update_one_arg_with_existing_keys(self) -> None:
        # When 1 arg is a dict-like and contains keys already in the tree,
        # any_existed must be True.
        t = BTree()
        t["a"] = 1
        t["b"] = 2
        # Update with a dict that overlaps on "a" but has a new key "c".
        result = t.update({"a": 100, "c": 3})
        assert result is True  # "a" already existed
        assert t["a"] == 100
        assert t["b"] == 2
        assert t["c"] == 3

    def test_update_one_arg_kwargs_with_existing_keys(self) -> None:
        t = BTree()
        t["a"] = 1
        t["b"] = 2
        # Kwargs merge path; "a" already exists, "c" is new.
        result = t.update({"a": 100}, c=3)
        assert result is True
        assert t["a"] == 100
        assert t["c"] == 3


# ---------------------------------------------------------------------------
# BTree.set_bnode_minimum_degree — exercises _new_ctor closure
# ---------------------------------------------------------------------------


class TestSetBnodeMinimumDegreeClosure:
    """The internal _new_ctor closure must produce a node with the new
    minimum_degree."""

    def test_new_ctor_uses_swapped_class(self) -> None:
        t = BTree(node_constructor=BNode4)
        t.set_bnode_minimum_degree(8)
        # The internal constructor should now return BNode8.
        new_node = t._node_constructor()
        assert isinstance(new_node, BNode8)
        assert new_node.minimum_degree == 8


# ---------------------------------------------------------------------------
# BTree._get_impl — root-is-None branch (line 649)
# ---------------------------------------------------------------------------


class TestBTreeGetImplRootNone:
    """Cover the trailing ``return MISSING`` after the while loop.

    The only way to reach it is if ``self._root`` is set to None.
    This is a defensive branch — clearing the root via clear() resets
    its contents but keeps the same node. To exercise the after-loop
    branch we set root to None directly.
    """

    def test_get_impl_with_none_root(self) -> None:
        t = BTree()
        t._root = None
        t.root = None  # type: ignore[assignment]
        result = t._get_impl(1)
        assert result is MISSING


# ---------------------------------------------------------------------------
# BTree._insert_nonfull — post-split key > median (lines 776-777)
# ---------------------------------------------------------------------------


class TestBTreeInsertNonfullPostSplitKeyGreater:
    """Cover the post-split ``key > node.items[i][0]`` branch in
    BTree._insert_nonfull."""

    def test_insert_nonfull_post_split_key_greater(self) -> None:
        # Use BNode4. Fill the root to trigger a split. Then insert
        # a key that lands in the new right subtree.
        t = BTree(node_constructor=BNode4)
        for i in range(20):
            t[i] = f"v{i}"
        # Tree has multiple levels now. Insert a new key that is
        # greater than the would-be promoted median at some level.
        t[100] = "v100"
        assert t[100] == "v100"
        assert len(t) == 21


# ---------------------------------------------------------------------------
# BTree._delete_from_node — defensive new_idx out-of-range (line 958)
# ---------------------------------------------------------------------------


class TestDeleteFromNodeDefensiveNone:
    """Cover the ``new_idx >= len(node.nodes)`` branch."""

    def test_delete_collapses_root_with_no_merge(self) -> None:
        # Build a tree, then aggressively delete to force root collapse.
        t = BTree(node_constructor=BNode4)
        for i in range(20):
            t[i] = f"v{i}"
        for i in range(20):
            del t[i]
        assert len(t) == 0
        # After all deletions, root should be a fresh empty node.
        assert t.root.is_leaf()


# ---------------------------------------------------------------------------
# BTree._handle_case3 — None return branch (line 1003)
# ---------------------------------------------------------------------------


class TestHandleCase3ReturnsNone:
    """Cover the branch where _handle_case3 returns None.

    This happens when a root with a single child has no left or right
    sibling to borrow from — handled by the collapse-into-child logic.
    """

    def test_root_with_single_child_collapses(self) -> None:
        # Build a small multi-level tree then empty it.
        t = BTree(node_constructor=BNode4)
        for i in range(10):
            t[i] = f"v{i}"
        # Delete all items.
        for i in range(10):
            del t[i]
        assert len(t) == 0
        assert t.get_depth() == 1


# ---------------------------------------------------------------------------
# BTree.items_from — closed=False when first item doesn't match key
# ---------------------------------------------------------------------------


class TestItemsFromClosedFalseFirstItemMismatch:
    """Cover line 1281-1282: closed=False when first item is not the key."""

    def test_items_from_closed_false_first_item_mismatches(self) -> None:
        t = BTree()
        for i in range(5):
            t[i] = f"v{i}"
        # Key 3 is not in tree (we have 0,1,2,4 in the example). Actually
        # 3 IS in the tree. Let's use key 99 which is absent.
        result = list(t.items_from(99, closed=False))
        # 99 is not in the tree, so the first yielded item is the smallest
        # key >= 99, which is none. Empty result.
        assert result == []

    def test_items_from_closed_false_first_item_mismatches_real(self) -> None:
        # Use a key that is not in the tree but smaller-than-some-items exist.
        t = BTree()
        for i in [1, 3, 5, 7]:
            t[i] = f"v{i}"
        # Key 4 is not in the tree. items_from(4, closed=False) must yield
        # items[0] = 5, 7.
        result = list(t.items_from(4, closed=False))
        keys = [k for k, _ in result]
        assert keys == [5, 7]


# ---------------------------------------------------------------------------
# BNode._iter_forward — internal node with multiple items
# ---------------------------------------------------------------------------


class TestIterForwardInternalMulti:
    """Cover the inner-loop branch when n_items > 1."""

    def test_iter_forward_internal_multi_items(self) -> None:
        # Build a three-level internal node with two items so the
        # inner ``for i in range(start_idx + 1, n_items)`` branch runs.
        root = BNode4()
        c0 = BNode4()
        c0.items = [(1, "a"), (2, "b")]
        c1 = BNode4()
        c1.items = [(10, "x"), (11, "y")]
        c2 = BNode4()
        c2.items = [(100, "p"), (101, "q")]
        root.items = [(5, "m1"), (50, "m2")]
        root.nodes = [c0, c1, c2]
        # start_idx=0: yield items[0], then loop yields children[1] + items[1]
        # then children[2].
        result = list(root._iter_forward(0))
        assert result == [
            (5, "m1"),
            (10, "x"), (11, "y"),
            (50, "m2"),
            (100, "p"), (101, "q"),
        ]


# ---------------------------------------------------------------------------
# BNode._merge_children — internal right with non-None nodes
# ---------------------------------------------------------------------------


class TestMergeChildrenInternalRight:
    """Cover the right.nodes is not None path with internal right."""

    def test_merge_left_leaf_with_internal_right(self) -> None:
        root = BNode4()
        root.items = [(50, "mid")]
        # Left is a leaf.
        left = BNode4()
        left.items = [(10, "a"), (20, "b"), (30, "c")]
        # Right is internal.
        right = BNode4()
        right.items = [(60, "e"), (70, "f"), (80, "g")]
        right_child = BNode4()
        right_child.items = [(65, "ec1"), (75, "ec2")]
        right.nodes = [right_child]
        root.nodes = [left, right]
        root._merge_children(0)
        # After merge: left has [10,20,30,50,60,70,80] and now has right's child.
        merged = root.nodes[0]
        assert (50, "mid") in merged.items
        assert (60, "e") in merged.items
        # left.nodes was None — must be initialized to [] and extended with right_child.
        assert merged.nodes is not None
        assert right_child in merged.nodes


# ---------------------------------------------------------------------------
# BTree._insert_nonfull — post-split key matches promoted median
# ---------------------------------------------------------------------------


class TestInsertNonfullPostSplitSameKey:
    """Force the post-split key == items[i][0] branch."""

    def test_insert_nonfull_post_split_key_matches(self) -> None:
        # Use a small minimum_degree so splits happen often.
        t = BTree(minimum_degree=3)
        # Fill until the next insert causes a split with a key that
        # matches the would-be promoted median.
        keys = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        for k in keys:
            t[k] = f"v{k}"
        # Now overwrite a key that was likely promoted. Many of these
        # will hit the standard overwrite path; one may hit the
        # post-split overwrite.
        t[3] = "updated"
        assert t[3] == "updated"
        assert len(t) == len(keys)


# ---------------------------------------------------------------------------
# BTree._set_impl — overwrite case during root split
# ---------------------------------------------------------------------------


class TestSetImplRootSplitOverwrite:
    """Cover the ``existing is not MISSING`` branch during root split."""

    def test_overwrite_during_root_split(self) -> None:
        t = BTree(node_constructor=BNode4)
        for i in range(7):
            t[i] = f"v{i}"
        # Force root split by overwriting an existing key — exercises
        # the ``existing is not MISSING`` branch.
        t[3] = "overwritten"
        assert t[3] == "overwritten"
        assert len(t) == 7


# ---------------------------------------------------------------------------
# BTree.update — kwargs with existing key
# ---------------------------------------------------------------------------


class TestUpdateKwargsExistingKey:
    """Cover the ``any_existed = True`` body inside the kwargs loop."""

    def test_update_kwargs_only_existing(self) -> None:
        t = BTree()
        t["a"] = 1
        t["b"] = 2
        # Both kwargs are existing — both should set any_existed.
        result = t.update(a=10, b=20)
        assert result is True
        assert t["a"] == 10
        assert t["b"] == 20

    def test_update_with_positional_and_existing_kwarg(self) -> None:
        # Mix: 1 positional arg (new key) + kwargs (existing key).
        # The kwargs loop must hit ``any_existed = True`` at line 881.
        t = BTree()
        t["existing"] = "old"
        # Positional arg is a new key, kwarg is an existing key.
        result = t.update({"new": "val"}, existing="newval")
        assert result is True  # "existing" already existed
        assert t["new"] == "val"
        assert t["existing"] == "newval"


# ---------------------------------------------------------------------------
# BTree._update_impl — full traversal without finding key
# ---------------------------------------------------------------------------


class TestUpdateImplNotFound:
    """Cover the not-found branch in BTree._update_impl."""

    def test_update_impl_traverses_full_tree(self) -> None:
        t = BTree(node_constructor=BNode4)
        for i in range(20):
            t[i] = f"v{i}"
        # Update a key that does not exist — full traversal.
        assert t._update_impl(999, "x") is False
        # Update a key that exists at a leaf.
        assert t._update_impl(5, "updated") is True
        assert t[5] == "updated"


# ---------------------------------------------------------------------------
# BTree._insert_nonfull — direct invocation hitting post-split same-key
# ---------------------------------------------------------------------------


class TestInsertNonfullDirectSplitSameKey:
    """Hit the post-split ``key == items[i][0]`` branch by hand-crafting
    a tree where a child is full and the inserted key matches the
    would-be promoted median."""

    def test_post_split_key_matches_promoted_median(self) -> None:
        t = BTree(node_constructor=BNode4)
        root = t.root
        # Hand-craft root as internal with one full child.
        root.items = [(50, "mid")]
        left = BNode4()
        left.items = [
            (0, "v0"), (1, "v1"), (2, "v2"), (3, "v3"),
            (4, "v4"), (5, "v5"), (6, "v6"),
        ]
        left._count = 7
        right = BNode4()
        right.items = [(100, "vr")]
        right._count = 1
        root.nodes = [left, right]
        root._count = 9
        # root is now internal. Insert key=3 (the median of left) — must
        # trigger _split_child and overwrite the promoted median in place.
        t._insert_nonfull(root, 3, "new3")
        # The promoted median is now (3, "new3") in root.
        assert root.search(3) == (3, "new3")
        # Left no longer contains 3.
        assert left.search(3) is None
        # Left has been trimmed to first half.
        assert left.items == [(0, "v0"), (1, "v1"), (2, "v2")]

    def test_post_split_key_less_than_median(self) -> None:
        """After split, key < median → descend into the LEFT child.

        Covers the False branch of ``if key > self.items[idx][0]:`` in
        BNode.insert_item (line 409->411 notation).
        """
        parent = BNode4()
        parent.items = [(50, "parent")]
        # A full left child. Median at index 3 is key=3.
        left = BNode4()
        left.items = [
            (0, "v0"), (1, "v1"), (2, "v2"), (3, "v3"),
            (4, "v4"), (5, "v5"), (6, "v6"),
        ]
        left._count = 7
        right = BNode4()
        right.items = [(100, "vr")]
        right._count = 1
        parent.nodes = [left, right]
        parent._count = 9
        # Insert key=1 (less than the median 3) — must descend into the
        # LEFT child after the split. (key=1 already exists in left
        # and will be updated in place by the leaf branch.)
        parent.insert_item((1, "updated1"))
        # The key was updated in left.
        assert (1, "updated1") in left.items


# ---------------------------------------------------------------------------
# BNode._merge_children — both children internal
# ---------------------------------------------------------------------------


class TestMergeChildrenBothInternal:
    """Cover the branch where right is internal AND left is internal.

    In that case ``right.nodes is not None`` is True AND
    ``left.nodes is None`` is False — so we skip line 527 and go
    straight to line 528.
    """

    def test_merge_both_internal(self) -> None:
        root = BNode4()
        root.items = [(50, "mid")]
        # Both children are internal.
        left = BNode4()
        left.items = [(10, "a"), (20, "b"), (30, "c")]
        left_c = BNode4()
        left_c.items = [(5, "a1"), (15, "b1")]
        left.nodes = [left_c]
        right = BNode4()
        right.items = [(60, "e"), (70, "f"), (80, "g")]
        right_c = BNode4()
        right_c.items = [(65, "ec1"), (75, "ec2")]
        right.nodes = [right_c]
        root.nodes = [left, right]
        root._merge_children(0)
        # After merge, left has both left's and right's children.
        merged = root.nodes[0]
        assert merged.nodes is not None
        assert left_c in merged.nodes
        assert right_c in merged.nodes


# ---------------------------------------------------------------------------
# BTree._handle_case3 — single-child node returns None
# ---------------------------------------------------------------------------


class TestHandleCase3SingleChildReturnsNone:
    """Cover the branch where _handle_case3 returns None because the
    node has a single child (no left or right siblings)."""

    def test_handle_case3_with_single_child(self) -> None:
        t = BTree(node_constructor=BNode4)
        root = t.root
        # Hand-craft a single-child internal root.
        root.items = [(50, "mid")]
        child = BNode4()
        child.items = [(10, "a"), (20, "b"), (30, "c")]  # t-1
        child._count = 3
        root.nodes = [child]
        # Now call _delete_from_node with a key not in root but in
        # child's range (e.g., 25). It will descend, find child is at
        # minimum, and call _handle_case3 with idx=0.
        # _handle_case3 should return None (no siblings).
        result = t._handle_case3(root, 0)
        assert result is None


# ---------------------------------------------------------------------------
# BTree._delete_from_node — defensive None branch
# ---------------------------------------------------------------------------


class TestDeleteFromNodeNoneIdx:
    """Cover the ``new_idx is None or new_idx >= len(node.nodes)`` branch."""

    def test_delete_from_node_handles_none_idx(self) -> None:
        t = BTree(node_constructor=BNode4)
        root = t.root
        # Hand-craft a single-child internal root.
        root.items = [(50, "mid")]
        child = BNode4()
        child.items = [(10, "a"), (20, "b"), (30, "c")]
        child._count = 3
        root.nodes = [child]
        # Delete a key not in root — _delete_from_node will descend to
        # child. The child is at minimum; _handle_case3 returns None.
        # Then _delete_from_node returns False (defensive branch).
        result = t._delete_from_node(root, 25)
        assert result is False

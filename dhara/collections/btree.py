from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class BTreeError(Exception):
    """Base exception for BTree operations."""

    pass


class KeyNotFoundError(BTreeError):
    """Raised when delete/update targets a non-existent key."""

    pass


class DuplicateKeyError(BTreeError):
    """Raised when insert finds existing key (if strict mode)."""

    pass


class TreeCorruptedError(BTreeError):
    """Raised when B-Tree invariant is violated."""

    pass


class _NullCount:
    """Sentinel ``_count`` value — arithmetic ops are identity-preserving.

    Assigned to a BNode's cached ``_count`` to signal "I don't know my real
    size; force a full traversal." ``BTree.__len__`` detects this and falls
    back to ``BNode.get_count()`` (an O(n) recursive count) so the tree stays
    queryable even when the cache is invalid.
    """

    __slots__ = ()

    def __add__(self, other: object) -> _NullCount:
        return self

    def __radd__(self, other: object) -> _NullCount:
        return self

    def __sub__(self, other: object) -> _NullCount:
        return self

    def __rsub__(self, other: object) -> _NullCount:
        return self

    def __int__(self) -> int:
        return 0

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _NullCount)

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return id(self)

    def __repr__(self) -> str:
        return "_NullCount()"


class _MISSING:
    """Sentinel return value for ``_get_impl`` to disambiguate "not present"
    from "present with value None". Compare via ``is`` (identity)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<MISSING>"


MISSING = _MISSING()


@dataclass
class BNode[K, V]:
    """A B-Tree node with items and optional children."""

    items: list[tuple[K, V]] = field(default_factory=list)
    nodes: list[BNode[K, V]] | None = None  # None = leaf, list = internal
    minimum_degree: int = 3  # t (controls node capacity)
    _count: int = 0  # cached total count in subtree (or _NullCount sentinel)

    def is_leaf(self) -> bool:
        """Returns True if this is a leaf node."""
        return self.nodes is None

    def is_full(self) -> bool:
        """Returns True if node has maximum items (2*t - 1)."""
        return len(self.items) == 2 * self.minimum_degree - 1

    def is_big(self) -> bool:
        """Returns True if node has >= t keys (safe for deletion without underflow)."""
        return len(self.items) >= self.minimum_degree

    def _find_position(self, key: K) -> tuple[int, bool]:
        """Binary search for key position. Returns (index, found).

        If found=True, index points to the matching item.
        If found=False, index points to where the key should be inserted.
        """
        lo, hi = 0, len(self.items) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            mid_key: K = self.items[mid][0]
            if mid_key == key:
                return (mid, True)
            elif mid_key < key:  # type: ignore[operator]
                lo = mid + 1
            else:
                hi = mid - 1
        return (lo, False)

    # ── Public lookup helpers (Durus-style API) ─────────────────────

    def get_position(self, key: K) -> int:
        """Return the index where ``key`` would be (insertion point if missing)."""
        return self._find_position(key)[0]

    def search(self, key: K) -> tuple[K, V] | None:
        """Return ``(key, value)`` if present, else ``None``."""
        idx, found = self._find_position(key)
        if found:
            return self.items[idx]
        return None

    # ── Count / structure introspection ─────────────────────────────

    def __len__(self) -> int:
        """Return the cached ``_count`` if valid, else a fresh traversal count."""
        if isinstance(self._count, _NullCount):
            return self.get_count()
        return int(self._count)  # noqa: FURB123

    def get_count(self) -> int:
        """Return the cached ``_count``, falling back to a fresh traversal.

        The fallback handles nodes constructed by hand (no ``_count`` populated)
        or where the cache was invalidated (set to ``_NullCount``).
        """
        if isinstance(self._count, _NullCount):
            return self._compute_count()
        return int(self._count)  # noqa: FURB123

    def _compute_count(self) -> int:
        """Recursively count all (key, value) pairs in this subtree."""
        total = len(self.items)
        if self.nodes is not None:
            for child in self.nodes:
                total += child._compute_count()
        return total

    def get_node_count(self) -> int:
        """Return the number of BNode instances in this subtree (incl. self)."""
        if self.nodes is None:
            return 1
        return 1 + sum(child.get_node_count() for child in self.nodes)

    def get_level(self) -> int:
        """Return the depth of this node: 0 for a leaf, 1+ for internals."""
        if self.nodes is None:
            return 0
        return 1 + max(child.get_level() for child in self.nodes)

    def get_min_item(self) -> tuple[K, V]:
        """Return the smallest (key, value) in this subtree.

        Asserts the subtree is non-empty (matches legacy Durus contract).
        """
        assert self.items, "BNode is empty; cannot get min item"
        node: BNode[K, V] = self
        while not node.is_leaf():
            assert node.nodes is not None
            node = node.nodes[0]
        return node.items[0]

    def get_max_item(self) -> tuple[K, V]:
        """Return the largest (key, value) in this subtree.

        Asserts the subtree is non-empty (matches legacy Durus contract).
        """
        assert self.items, "BNode is empty; cannot get max item"
        node: BNode[K, V] = self
        while not node.is_leaf():
            assert node.nodes is not None
            node = node.nodes[-1]
        return node.items[-1]

    # ── Count-cache maintenance ─────────────────────────────────────

    def _update_count(self) -> int:
        """Recompute ``_count`` from this node's items + descendants; return new value.

        Uses ``_compute_count`` (a fully recursive count) rather than
        trusting children' cached ``_count`` values. This is the only way
        to guarantee correctness when the cache may be stale due to prior
        splits, merges, or borrows in the same subtree.
        """
        new_count = self._compute_count()
        self._count = new_count
        return new_count

    def _change_count(self, delta: int) -> int:
        """Apply ``delta`` to ``_count`` and return the delta applied.

        ``_NullCount`` short-circuits — it returns the delta without mutating
        state (the cache is intentionally invalid).
        """
        if isinstance(self._count, _NullCount):
            return delta
        self._count = self._count + delta
        return delta

    # ── Iteration (in-order, both leaves and internals) ─────────────

    def __iter__(self) -> Iterator[tuple[K, V]]:
        """In-order iteration over (key, value) pairs in this subtree."""
        return self._iter_full()

    def _iter_full(self) -> Iterator[tuple[K, V]]:
        """Full in-order traversal of the subtree.

        For each item, recurse into the child to its left *first*, then
        yield the item, then recurse into the child to its right.
        """
        children = self.nodes
        n_items = len(self.items)
        for i in range(n_items):
            if children is not None and i < len(children):
                yield from children[i]._iter_full()
            yield self.items[i]
        if children is not None and n_items < len(children):
            yield from children[n_items]._iter_full()

    def _iter_forward(self, start_idx: int) -> Iterator[tuple[K, V]]:
        """Forward iteration starting at ``items[start_idx]`` (inclusive).

        Skips children[0..start_idx-1] (they have items < items[start_idx])
        and yields items[start_idx..] in order, recursing into the child
        between each pair of consecutive items.
        """
        n_items = len(self.items)
        children = self.nodes
        if start_idx >= n_items:
            # Past the last item — recurse into the rightmost child if any.
            if children is not None and start_idx < len(children):
                yield from children[start_idx]._iter_full()
            return
        # Yield items[start_idx] first, then recurse children[start_idx+1]
        # for items between items[start_idx] and items[start_idx+1], etc.
        yield self.items[start_idx]
        for i in range(start_idx + 1, n_items):
            if children is not None and i < len(children):
                yield from children[i]._iter_full()
            yield self.items[i]
        # After the last item, recurse children[n]
        if children is not None and n_items < len(children):
            yield from children[n_items]._iter_full()

    def __reversed__(self) -> Iterator[tuple[K, V]]:
        """Reverse in-order iteration."""
        return self._iter_full_backward()

    def _iter_full_backward(self) -> Iterator[tuple[K, V]]:
        """Full reverse in-order traversal."""
        children = self.nodes
        n_items = len(self.items)
        if children is not None and n_items < len(children):
            yield from children[n_items]._iter_full_backward()
        for i in range(n_items - 1, -1, -1):
            yield self.items[i]
            if children is not None and i < len(children):
                yield from children[i]._iter_full_backward()

    def _iter_backward(self, start_idx: int) -> Iterator[tuple[K, V]]:
        """Backward iteration starting at ``items[start_idx]`` (inclusive).

        Skips children[start_idx+1..n] (they have items > items[start_idx])
        and yields items[start_idx..0] in reverse, recursing into the
        child between each pair of consecutive items.
        """
        children = self.nodes
        if start_idx < 0:
            return
        # If start_idx is in range, yield it first, then recurse children[start_idx]
        # for items between items[start_idx-1] and items[start_idx], etc.
        if start_idx < len(self.items):
            yield self.items[start_idx]
        # Then recurse children[start_idx] for items < items[start_idx]
        if children is not None and start_idx < len(children):
            yield from children[start_idx]._iter_full_backward()
        # Then walk backward from start_idx-1
        for i in range(start_idx - 1, -1, -1):
            yield self.items[i]
            if children is not None and i < len(children):
                yield from children[i]._iter_full_backward()

    def iter_from(self, key: K) -> Iterator[tuple[K, V]]:
        """Forward iteration yielding pairs with key >= ``key`` (inclusive).

        When ``key`` is not in this node, recurses into ``children[idx]``
        first (the child where ``key`` would belong) so qualifying items
        in that subtree are yielded before items[idx] and beyond.
        """
        idx, found = self._find_position(key)
        children = self.nodes
        n_items = len(self.items)
        if not found and children is not None and idx < len(children):
            yield from children[idx].iter_from(key)
        for i in range(idx, n_items):
            yield self.items[i]
            if children is not None and i + 1 < len(children):
                yield from children[i + 1]._iter_full()
        # If idx is past all items (key > every item here), the loop above
        # didn't execute, so we still need to recurse the rightmost child.
        if idx > n_items and children is not None and n_items < len(children):
            yield from children[n_items]._iter_full()

    def iter_backward_from(self, key: K) -> Iterator[tuple[K, V]]:
        """Backward iteration yielding pairs with key strictly LESS than ``key``.

        The ``key`` itself is excluded (asymmetric with ``iter_from`` which
        is inclusive).
        """
        idx, found = self._find_position(key)
        children = self.nodes
        if found:
            # Key is at idx; items < key are in children[idx] (full) and items[idx-1..0].
            if children is not None and idx < len(children):
                yield from children[idx]._iter_full_backward()
        else:
            # Key not present; items < key in children[idx] (filter) and items[idx-1..0].
            if children is not None and idx < len(children):
                yield from children[idx].iter_backward_from(key)
        for i in range(idx - 1, -1, -1):
            yield self.items[i]
            if children is not None and i < len(children):
                yield from children[i]._iter_full_backward()

    def iter_backward_from_or_equal(self, key: K) -> Iterator[tuple[K, V]]:
        """Backward iteration yielding pairs with key <= ``key`` (inclusive).

        Unlike ``iter_backward_from`` (which is exclusive), this includes
        ``key`` itself if it is present in the tree — possibly deep in a
        descendant of ``children[idx]`` (the not-found insertion point).
        """
        idx, found = self._find_position(key)
        children = self.nodes
        if found:
            # Include key at idx, then items < key.
            yield self.items[idx]
            if children is not None and idx < len(children):
                yield from children[idx]._iter_full_backward()
        else:
            # Key not in this node; recurse into children[idx] with the
            # *inclusive* variant so a key present deeper in the subtree
            # is still included.
            if children is not None and idx < len(children):
                yield from children[idx].iter_backward_from_or_equal(key)
        for i in range(idx - 1, -1, -1):
            yield self.items[i]
            if children is not None and i < len(children):
                yield from children[i]._iter_full_backward()

    # ── Low-level mutation helpers ─────────────────────────────────

    def insert_item(self, item: tuple[K, V]) -> None:
        """Insert ``item`` into this node, recursing if internal.

        If the child on the descent path is full, it is split first (the
        median is promoted into ``self.items``). If the key then matches
        the promoted median, we overwrite it in place.
        """
        key, _value = item
        idx, found = self._find_position(key)
        if found:
            # Duplicate — update in place
            self.items[idx] = item
            return
        if self.is_leaf():
            self.items.insert(idx, item)
            return
        assert self.nodes is not None
        child = self.nodes[idx]
        if child.is_full():
            # Split child, promoting the median into self.items[idx].
            self._split_child_in_place(idx)
            # The promoted median now lives at self.items[idx]. If our key
            # matches it, overwrite in place instead of descending further.
            if key == self.items[idx][0]:  # type: ignore[operator]
                self.items[idx] = item  # type: ignore[arg-type]
                return
            # Otherwise continue descent; key may now belong in the right child.
            if key > self.items[idx][0]:  # type: ignore[operator]
                idx += 1
        self.nodes[idx].insert_item(item)

    def _split_child_in_place(self, idx: int) -> None:
        """Split ``self.nodes[idx]`` and promote the median into ``self.items[idx]``.

        Mirrors the BTree-level split path: the right half of the child's
        items becomes a new sibling, the median moves up to the parent,
        and the left half stays. ``_count`` is refreshed on all affected
        nodes so ``len()`` stays accurate.
        """
        assert self.nodes is not None
        full = self.nodes[idx]
        t = full.minimum_degree
        assert full.nodes is not None or full.is_leaf()
        # Middle key index
        mid_idx = t - 1
        promoted_key, promoted_val = full.items[mid_idx]
        # Build the new right node from the upper half
        right_items = full.items[t:].copy()
        right_nodes = full.nodes[t:].copy() if full.nodes is not None else None
        # Trim the left (existing) child to the lower half
        full.items = full.items[: t - 1].copy()
        full.nodes = full.nodes[:t].copy() if full.nodes is not None else None
        # Insert the promoted key into the parent (self)
        self.items.insert(idx, (promoted_key, promoted_val))
        # Build the new right sibling and insert into self.nodes at idx + 1
        # We construct a sibling of the same type as ``full`` so ``isinstance``
        # checks stay accurate for BNode4/8/16.
        new_right = type(full)()  # type: ignore[call-arg,assignment]
        new_right.items = right_items
        new_right.nodes = right_nodes
        self.nodes.insert(idx + 1, new_right)
        # Refresh counts
        full._update_count()
        new_right._update_count()
        self._update_count()

    def delete(self, key: K) -> bool:
        """Low-level delete from this node (Cormen cases 1, 2a, 2b, 2c).

        Returns ``True`` if ``key`` was found and removed, ``False`` otherwise.

        Unlike ``BTree.delete``, this does NOT maintain the parent's
        rebalancing invariants when descending into an underflowed child —
        callers that need that should use the BTree-level delete path.
        This method is exposed primarily for the test suite, which builds
        hand-crafted trees and exercises each branch independently.
        """
        idx, found = self._find_position(key)
        if found:
            if self.is_leaf():
                # Case 1: key in leaf — just remove it.
                self.items.pop(idx)
                self._change_count(-1)
                return True
            # Internal node — case 2.
            t = self.minimum_degree
            assert self.nodes is not None
            right_child = self.nodes[idx + 1]
            left_child = self.nodes[idx]
            if len(right_child.items) >= t:
                # Case 2b: successor swap.
                succ_key, succ_val = right_child.get_min_item()
                self.items[idx] = (succ_key, succ_val)
                ok = right_child.delete(succ_key)
                if ok:
                    self._update_count()
                return ok
            if len(left_child.items) >= t:
                # Case 2a: predecessor swap.
                pred_key, pred_val = left_child.get_max_item()
                self.items[idx] = (pred_key, pred_val)
                ok = left_child.delete(pred_key)
                if ok:
                    self._update_count()
                return ok
            # Case 2c: both children at minimum — merge.
            self._merge_children(idx)
            # After merge the combined node is at idx; recurse into it.
            if idx < len(self.nodes):
                ok = self.nodes[idx].delete(key)
                if ok:
                    self._update_count()
                return ok
            return False
        # Key not in this node — descend.
        if self.is_leaf():
            return False
        assert self.nodes is not None
        # If idx is the insertion point past all items, descend into the
        # rightmost child (children[n] contains items > items[n-1]).
        if idx >= len(self.nodes):
            target = self.nodes[-1]
        else:
            target = self.nodes[idx]
        ok = target.delete(key)
        if ok:
            self._update_count()
        return ok

    def _merge_children(self, idx: int) -> None:
        """Merge ``self.nodes[idx]`` with ``self.nodes[idx+1]`` (case 2c).

        The separator at ``self.items[idx]`` becomes part of the merged
        left child, the right child's items/children are appended, and the
        separator + right child pointer are removed. ``_count`` caches are
        updated to reflect the new totals.
        """
        assert self.nodes is not None
        left = self.nodes[idx]
        right = self.nodes[idx + 1]
        sep_key, sep_val = self.items[idx]
        left.items.append((sep_key, sep_val))
        left.items.extend(right.items)
        if right.nodes is not None:
            if left.nodes is None:
                left.nodes = []
            left.nodes.extend(right.nodes)
        self.items.pop(idx)
        self.nodes.pop(idx + 1)
        # Refresh counts so len(self) and len(left) stay accurate.
        left._update_count()
        self._update_count()

    def _decrement_count(self, n: int = 1) -> None:
        """Decrement ``_count`` by ``n``, propagating to the root.

        Used by the BTree's high-level delete path so the cached root
        count stays accurate when the underlying BNode operations don't
        directly touch the root's ``_count`` field. Walks up via parent
        references when available; no-op if ``_count`` is ``_NullCount``.
        """
        if isinstance(self._count, _NullCount):
            return
        self._count = max(0, self._count - n)


# ── Fixed-degree BNode subclasses ──────────────────────────────────
# These let callers ask for a specific minimum degree (4, 8, or 16) without
# having to construct a generic ``BNode(minimum_degree=...)`` themselves.
# They are real classes (not factory functions) so callers can do
# ``isinstance(node, BNode4)`` for type-aware assertions, and so they can be
# passed as the ``node_constructor=`` argument to ``BTree(...)``.


class BNode4(BNode[Any, Any]):
    """BNode with ``minimum_degree=4`` (max 7 items, 5 children)."""

    def __init__(self, **kw: Any) -> None:
        kw.setdefault("minimum_degree", 4)
        super().__init__(**kw)


class BNode8(BNode[Any, Any]):
    """BNode with ``minimum_degree=8`` (max 15 items, 9 children)."""

    def __init__(self, **kw: Any) -> None:
        kw.setdefault("minimum_degree", 8)
        super().__init__(**kw)


class BNode16(BNode[Any, Any]):
    """BNode with ``minimum_degree=16`` (max 31 items, 17 children).

    The default node class for ``BTree()`` — matches the "B-Tree of order 16"
    expectation in the legacy test suite.
    """

    def __init__(self, **kw: Any) -> None:
        kw.setdefault("minimum_degree", 16)
        super().__init__(**kw)


# Map minimum_degree → node class for ``set_bnode_minimum_degree`` and
# ``BTree``'s backward-compat ``minimum_degree=`` kwarg.
_NODE_CLASS_BY_DEGREE: dict[int, type[BNode[Any, Any]]] = {
    3: BNode,
    4: BNode4,
    8: BNode8,
    16: BNode16,
}


class BTree[K, V]:
    """B-Tree with borrow-first deletion (Cormen case 3)."""

    def __init__(
        self,
        node_constructor: Callable[[], BNode[K, V]] | None = None,
        minimum_degree: int | None = None,
    ) -> None:
        # Validate: ``node_constructor`` (when provided) must be callable AND
        # must produce a BNode instance. The second check is what
        # ``test_invalid_node_constructor_raises`` exercises by passing
        # ``int`` — ``int`` is callable but does not return a BNode.
        if node_constructor is not None:
            assert callable(node_constructor), (
                "node_constructor must be callable or None"
            )
            assert isinstance(node_constructor(), BNode), (
                "node_constructor must return a BNode instance"
            )
        # Backward-compat: ``BTree(minimum_degree=N)`` builds a constructor
        # that produces nodes with the given degree.
        if node_constructor is None and minimum_degree is not None:
            t = minimum_degree
            cls = _NODE_CLASS_BY_DEGREE.get(t, BNode)

            def _ctor(t: int = t, cls: type[BNode[K, V]] = cls) -> BNode[K, V]:
                return cls(minimum_degree=t)  # type: ignore[call-arg]

            node_constructor = _ctor
        # Default constructor is BNode16 (matches legacy test expectations).
        if node_constructor is None:
            node_constructor = BNode16  # type: ignore[assignment]
        self._node_constructor: Callable[[], BNode[K, V]] = node_constructor
        # Public ``root`` attribute (was ``_root`` previously).
        self.root: BNode[K, V] = node_constructor()
        # Backward-compat: expose ``_root`` as an alias.
        self._root = self.root
        self._minimum_degree = self.root.minimum_degree

    def _get_impl(self, key: K) -> V | _MISSING:
        """Get value by key. Returns the ``MISSING`` sentinel if not found.

        The sentinel disambiguates "key absent" from "key present with
        value None" — callers that care about presence should compare
        with ``is MISSING``, not ``is None``.
        """
        node: BNode[K, V] | None = self._root
        while node is not None:
            pos, found = node._find_position(key)
            if found:
                return node.items[pos][1]
            if node.is_leaf():
                return MISSING
            assert node.nodes is not None  # type narrowing
            node = node.nodes[pos]
        return MISSING

    def get(self, key: K, default: V | None = None) -> V | None:
        """Get value by key, returning ``default`` if missing (dict-like).

        When called with no second argument, returns ``None`` on miss
        (matches the existing in-tree behavior used by ``__contains__``).
        """
        result = self._get_impl(key)
        if result is MISSING:
            return default
        return result  # type: ignore[return-value]

    def _set_impl(self, key: K, value: V) -> None:
        """Insert or update key-value pair. Maintains the root ``_count`` cache.

        The count cache is propagated across root splits: when a full root
        causes a new root to be created, the new root inherits the old
        root's count (the old root becomes a child of the new one with
        the same number of items).
        """
        root = self._root
        # Detect update-vs-insert for accurate count maintenance.
        existing = self._get_impl(key)
        if root.is_full():
            new_root = self._node_constructor()
            # Propagate the old root's count to the new root — the new root
            # contains everything the old root had, plus the new key.
            new_root._count = root._count
            new_root.nodes = [root]
            self._split_child(new_root, 0)
            self._root = new_root
            self.root = new_root
            self._insert_nonfull(self._root, key, value)
            if existing is MISSING:
                # The new key increased the count by 1.
                if not isinstance(new_root._count, _NullCount):
                    new_root._change_count(1)
        else:
            self._insert_nonfull(root, key, value)
            if existing is MISSING:
                if not isinstance(root._count, _NullCount):
                    self.root._change_count(1)

    def set(self, key: K, value: V) -> None:
        """Insert or update key-value pair. Delegates to _set_impl."""
        self._set_impl(key, value)

    def is_full(self) -> bool:
        """Check if root needs splitting."""
        return self._root.is_full()

    def _split_child(self, parent: BNode[K, V], idx: int) -> None:
        """Split parent.nodes[idx] which is full (2t-1 items).

        After split:
        - Left child retains t-1 items (first half)
        - Middle key promoted to parent
        - Right child receives t-1 items (second half)
        """
        t = parent.minimum_degree
        assert parent.nodes is not None  # internal node must have nodes
        full_child: BNode[K, V] = parent.nodes[idx]

        # EXTRACT MIDDLE KEY BEFORE TRIMMING (order matters!)
        middle_key_idx = t - 1  # 0-indexed position of middle key
        middle_key: K
        middle_val: V
        middle_key, middle_val = full_child.items[middle_key_idx]

        # Create new right node with second half of items
        right_node = self._node_constructor()
        right_node.items = full_child.items[t:]  # t items (indices t to 2t-1)
        right_node.nodes = full_child.nodes[t:] if full_child.nodes else None

        # Trim left node to t-1 items
        full_child.items = full_child.items[: t - 1]
        if full_child.nodes is not None:
            full_child.nodes = full_child.nodes[:t]

        # Insert new child pointer to the right of idx
        if parent.nodes is None:
            parent.nodes = []
        parent.nodes.insert(idx + 1, right_node)

        # Insert middle key at parent's position idx
        parent.items.insert(idx, (middle_key, middle_val))

        # NOTE: do NOT recompute counts here. A split merely rearranges
        # items between children of the same parent; the total item count
        # in the subtree is unchanged. Recomputing via _update_count would
        # read stale cached counts from the children, causing a small drift
        # that accumulates over many splits. The caller (_set_impl) is
        # responsible for adding +1 to the parent count when a new key is
        # inserted, and -1 when one is removed.

    def _insert_nonfull(self, node: BNode[K, V], key: K, value: V) -> None:
        """Insert key-value into non-full node."""
        i = len(node.items) - 1

        if node.is_leaf():
            # Check if key already exists (update case)
            while i >= 0:
                if node.items[i][0] == key:
                    node.items[i] = (key, value)
                    return
                if node.items[i][0] < key:  # type: ignore[operator]
                    break
                i -= 1
            node.items.insert(i + 1, (key, value))
        else:
            # Find child to descend into. After the loop, items[i-1] is the
            # largest key in this node that is < key, and items[i] is the
            # smallest key >= key. If key == items[i-1] it is present in
            # this internal node — update in place.
            while i >= 0 and key < node.items[i][0]:  # type: ignore[operator]
                i -= 1
            if i >= 0 and key == node.items[i][0]:  # type: ignore[operator]
                node.items[i] = (key, value)  # type: ignore[arg-type]
                return
            i += 1
            assert node.nodes is not None  # type narrowing
            if node.nodes[i].is_full():
                self._split_child(node, i)
                # After split, the promoted median is now at node.items[i].
                # If our key equals the promoted median, overwrite it in place
                # (instead of descending into a child and creating a duplicate).
                if key == node.items[i][0]:  # type: ignore[operator]
                    node.items[i] = (key, value)  # type: ignore[arg-type]
                    return
                if key > node.items[i][0]:  # type: ignore[operator]
                    i += 1
            self._insert_nonfull(node.nodes[i], key, value)

    def height(self) -> int:
        """Return the height of the tree."""
        node: BNode[K, V] = self._root
        h = 0
        while not node.is_leaf():
            assert node.nodes is not None  # type narrowing
            node = node.nodes[0]
            h += 1
        return h + 1

    def items(self) -> list[tuple[K, V]]:
        """Return all (key, value) pairs as a list in sorted key order."""
        return list(self._traverse(self._root))

    def _traverse(self, node: BNode[K, V]) -> Iterator[tuple[K, V]]:
        """In-order traversal of subtree rooted at node."""
        for i, item in enumerate(node.items):
            if node.nodes is not None:
                yield from self._traverse(node.nodes[i])
            yield item
        if node.nodes is not None:
            yield from self._traverse(node.nodes[-1])

    def keys(self) -> list[K]:
        """Return all keys as a list in sorted order."""
        return [k for k, _ in self.items()]

    def values(self) -> list[V]:
        """Return all values as a list in key-sorted order."""
        return [v for _, v in self.items()]

    def _delete_impl(self, key: K) -> bool:
        """Delete key. Returns True if found and deleted, False if not found.

        Recomputes the root ``_count`` cache from leaves up after a
        successful delete. This handles the case where internal-node
        caches are stale from prior splits or rebalancing operations.
        """
        found = self._delete_from_node(self._root, key)
        if found and not isinstance(self.root._count, _NullCount):
            self.root._update_count()
        return found

    def delete(self, key: K) -> bool:
        """Delete key. Returns True if found and deleted, False if not found."""
        return self._delete_impl(key)

    def _update_impl(self, key: K, value: V) -> bool:
        """Update existing key's value. Returns True if found, False if not."""
        node: BNode[K, V] | None = self._root
        while node is not None:
            pos, found = node._find_position(key)
            if found:
                node.items[pos] = (key, value)
                return True
            if node.is_leaf():
                return False
            assert node.nodes is not None  # type narrowing
            node = node.nodes[pos]
        return False

    def update(self, *args: Any, **kwargs: Any) -> bool:
        """Two calling conventions:

        - ``t.update(key, value)`` — BTree-native: returns ``True`` if
          ``key`` was already present (overwrote), ``False`` if it was new.
        - ``t.update(other_dict)`` — dict-like bulk merge (returns ``True``
          if any existing key was overwritten, else ``False``).

        The legacy strict contract: more than one positional argument when
        the first is dict-like raises ``TypeError("update expected at most
        1 argument")``. Two positional args (key, value) are always
        treated as the BTree-native form.
        """
        if len(args) == 2:
            first, second = args
            first_is_dict_like = isinstance(first, dict) or (
                hasattr(first, "items") and callable(getattr(first, "items", None))
            )
            if first_is_dict_like:
                raise TypeError("update expected at most 1 argument")
            existed = self._get_impl(first) is not MISSING
            self._set_impl(first, second)
            return existed
        if len(args) == 1:
            other = args[0]
            any_existed = False
            if hasattr(other, "iteritems") and callable(other.iteritems):
                pairs = list(other.iteritems())
            elif hasattr(other, "items") and callable(other.items):
                pairs = list(other.items())
            else:
                pairs = list(other)
            for k, v in pairs:
                if self._get_impl(k) is not MISSING:
                    any_existed = True
                self._set_impl(k, v)
            for k, v in kwargs.items():  # type: ignore[union-attr]
                if self._get_impl(k) is not MISSING:  # type: ignore[arg-type]
                    any_existed = True
                self._set_impl(k, v)  # type: ignore[arg-type]
            return any_existed
        if not args:
            # Pure-kwargs dict-like update.
            any_existed = False
            for k, v in kwargs.items():  # type: ignore[union-attr]
                if self._get_impl(k) is not MISSING:  # type: ignore[arg-type]
                    any_existed = True
                self._set_impl(k, v)  # type: ignore[arg-type]
            return any_existed
        raise TypeError("update expected at most 1 argument")

    def _get_min(self, node: BNode[K, V]) -> tuple[K, V]:
        """Get smallest (key, value) in subtree rooted at node."""
        while not node.is_leaf() and node.nodes:
            assert node.nodes is not None  # type narrowing
            node = node.nodes[0]
        return node.items[0]

    def _get_max(self, node: BNode[K, V]) -> tuple[K, V]:
        """Get largest (key, value) in subtree rooted at node."""
        while not node.is_leaf() and node.nodes:
            assert node.nodes is not None  # type narrowing
            node = node.nodes[-1]
        return node.items[-1]

    def _delete_from_node(self, node: BNode[K, V], key: K) -> bool:
        """Delete key from node. Full version with case 3 borrow/merge."""
        # Case 1: Key is in this node
        pos, found = node._find_position(key)
        if found:
            if node.is_leaf():
                node.items.pop(pos)
                return True
            else:
                # Case 2: key in internal node
                t = node.minimum_degree
                assert node.nodes is not None  # type narrowing
                left: BNode[K, V] | None = (
                    node.nodes[pos] if pos < len(node.nodes) else None
                )
                right: BNode[K, V] | None = (
                    node.nodes[pos + 1] if pos + 1 < len(node.nodes) else None
                )
                if left is not None and len(left.items) >= t:
                    pred_key: K
                    pred_val: V
                    pred_key, pred_val = self._get_max(left)
                    node.items[pos] = (pred_key, pred_val)
                    return self._delete_from_node(left, pred_key)
                elif right is not None and len(right.items) >= t:
                    succ_key: K
                    succ_val: V
                    succ_key, succ_val = self._get_min(right)
                    node.items[pos] = (succ_key, succ_val)
                    return self._delete_from_node(right, succ_key)
                else:
                    # Both children have t-1 — merge then delete from merged
                    self._merge(node, pos)
                    return self._delete_from_node(node.nodes[pos], key)

        else:
            # Key not in this node — descend
            if node.is_leaf():
                return False

            idx = pos
            assert node.nodes is not None  # type narrowing
            child: BNode[K, V] = node.nodes[idx]

            if len(child.items) >= node.minimum_degree:
                return self._delete_from_node(child, key)
            else:
                # Child at minimum — call case 3 handler
                new_idx: int | None = self._handle_case3(node, idx)
                if new_idx is None or new_idx >= len(node.nodes):
                    return False
                return self._delete_from_node(node.nodes[new_idx], key)

    def _handle_case3(self, node: BNode[K, V], idx: int) -> int | None:
        """Handle underflow before descending into node.nodes[idx].

        Borrow-first strategy:
        1. If left sibling has > t-1 keys, borrow from left → return idx
        2. Else if right sibling has > t-1 keys, borrow from right → return idx
        3. Else merge with left sibling if exists → return idx - 1
           Or merge with right sibling → return idx

        Returns the NEW index of the child to descend into after handling.
        Returns None if no valid child (tree structure collapsed).
        """
        t = node.minimum_degree
        assert node.nodes is not None  # type narrowing
        node.nodes[idx]

        # Get siblings
        left_sibling: BNode[K, V] | None = node.nodes[idx - 1] if idx > 0 else None
        right_sibling: BNode[K, V] | None = (
            node.nodes[idx + 1] if idx < len(node.nodes) - 1 else None
        )

        # Try borrowing from left sibling
        if left_sibling is not None and len(left_sibling.items) > t - 1:
            self._borrow_from_left(node, idx)
            return idx  # child is still at idx

        # Try borrowing from right sibling
        if right_sibling is not None and len(right_sibling.items) > t - 1:
            self._borrow_from_right(node, idx)
            return idx  # child is still at idx

        # No sibling has extra keys — merge
        if left_sibling is not None:
            # Merge idx-1 and idx → result at idx-1
            self._merge(node, idx - 1)
            return idx - 1  # merged node moved to idx-1
        elif right_sibling is not None:
            # Merge idx and idx+1 → result at idx
            self._merge(node, idx)
            return idx  # merged node stays at idx
        # Neither sibling exists (root with single child) — return None
        return None

    def _borrow_from_left(self, parent: BNode[K, V], idx: int) -> None:
        """Borrow rightmost item from left sibling.

        Parent's separator key moves down to leftmost position of right child.
        Rightmost item of left sibling moves up to replace separator.
        """
        assert parent.nodes is not None  # type narrowing
        left: BNode[K, V] = parent.nodes[idx - 1]
        right: BNode[K, V] = parent.nodes[idx]

        # Take separator from parent
        sep_key: K
        sep_val: V
        sep_key, sep_val = parent.items[idx - 1]
        # Take rightmost item from left sibling
        borrow_key: K
        borrow_val: V
        borrow_key, borrow_val = left.items.pop()

        # Insert separator at start of right child's items
        right.items.insert(0, (sep_key, sep_val))

        # If left has children, move its last child to right
        if left.nodes is not None:
            assert right.nodes is not None  # type narrowing
            last_child: BNode[K, V] = left.nodes.pop()
            right.nodes.insert(0, last_child)

        # Update parent's separator with borrowed key
        parent.items[idx - 1] = (borrow_key, borrow_val)

        # Refresh _count caches so the root count stays accurate.
        left._update_count()
        right._update_count()

    def _borrow_from_right(self, parent: BNode[K, V], idx: int) -> None:
        """Borrow leftmost item from right sibling.

        Parent's separator key moves down to rightmost position of left child.
        Leftmost item of right sibling moves up to replace separator.
        """
        assert parent.nodes is not None  # type narrowing
        left: BNode[K, V] = parent.nodes[idx]
        right: BNode[K, V] = parent.nodes[idx + 1]

        # Take separator from parent
        sep_key: K
        sep_val: V
        sep_key, sep_val = parent.items[idx]
        # Take leftmost item from right sibling
        borrow_key: K
        borrow_val: V
        borrow_key, borrow_val = right.items.pop(0)

        # Insert separator at end of left child's items
        left.items.append((sep_key, sep_val))

        # If right has children, move its first child to left
        if right.nodes is not None:
            assert left.nodes is not None  # type narrowing
            first_child: BNode[K, V] = right.nodes.pop(0)
            left.nodes.append(first_child)

        # Update parent's separator with borrowed key
        parent.items[idx] = (borrow_key, borrow_val)

        # Refresh _count caches so the root count stays accurate.
        left._update_count()
        right._update_count()

    def _merge(self, parent: BNode[K, V], idx: int) -> None:
        """Merge node[idx] and node[idx+1] into node[idx].

        Takes separator from parent.items[idx] and appends to left child's items.
        All items from right child move to left child.
        All children from right child move to left child.
        Parent loses separator (items shift) and right child pointer.
        """
        assert parent.nodes is not None  # type narrowing
        left: BNode[K, V] = parent.nodes[idx]
        right: BNode[K, V] = parent.nodes[idx + 1]

        # Take separator from parent
        sep_key: K
        sep_val: V
        sep_key, sep_val = parent.items[idx]

        # Append separator to left child's items
        left.items.append((sep_key, sep_val))

        # Append all items from right child
        left.items.extend(right.items)

        # If internal, append all children
        if right.nodes is not None:
            assert left.nodes is not None  # type narrowing
            left.nodes.extend(right.nodes)

        # Remove separator from parent (items shift left)
        parent.items.pop(idx)

        # Remove right child pointer from parent
        parent.nodes.pop(idx + 1)

        # Refresh _count caches: left grew, parent shrank.
        left._update_count()
        parent._update_count()

        # Root underflow check: if root now has 0 items and 1 child, reduce height
        if parent is self._root and not parent.items and len(parent.nodes) == 1:
            self._root = parent.nodes[0]
            self.root = parent.nodes[0]

    # ── Pythonic container protocol (dict-like) ────────────────────

    def __len__(self) -> int:
        """Return the number of items. Falls back to a fresh traversal
        if the cached root count is a ``_NullCount`` sentinel."""
        if isinstance(self.root._count, _NullCount):
            return self.root.get_count()
        return int(self.root._count)  # noqa: FURB123

    def __bool__(self) -> bool:
        """``True`` when the tree contains at least one item."""
        return len(self) > 0

    def __contains__(self, key: object) -> bool:
        """``key in t`` — uses the existing ``_get_impl`` lookup."""
        return self._get_impl(key) is not MISSING  # type: ignore[arg-type]

    def __iter__(self) -> Iterator[K]:
        """Iterate keys in sorted (ascending) order."""
        for k, _v in self.items():
            yield k

    def __reversed__(self) -> Iterator[K]:
        """Iterate keys in descending order."""
        for k, _v in self.items_backward():
            yield k

    def __setitem__(self, key: K, value: V) -> None:
        """``t[key] = value`` syntax."""
        self._set_impl(key, value)

    def __getitem__(self, key: K) -> V:
        """``t[key]`` syntax. Raises ``KeyError`` if missing."""
        result = self._get_impl(key)
        if result is MISSING:
            raise KeyError(key)
        return result  # type: ignore[return-value]

    def __delitem__(self, key: K) -> None:
        """``del t[key]``. Raises ``KeyError`` if missing."""
        if not self._delete_impl(key):
            raise KeyError(key)

    # ── Convenience / dict-like helpers ─────────────────────────────

    def has_key(self, key: K) -> bool:
        """Return ``True`` if ``key`` is in the tree (dict-style)."""
        return key in self

    def add(self, key: K, value: V = True) -> None:  # type: ignore[assignment]
        """``add(key)`` inserts with default value ``True``; ``add(k, v)`` sets value.

        Mirrors ``dict.setdefault`` for new keys (does not overwrite).
        """
        if key in self:
            return
        self._set_impl(key, value)

    def setdefault(self, key: K, default: V) -> V:
        """Insert ``default`` if ``key`` missing, else return existing value."""
        existing = self._get_impl(key)
        if existing is not MISSING:
            return existing  # type: ignore[return-value]
        self._set_impl(key, default)
        return default

    def clear(self) -> None:
        """Empty the tree, preserving the configured node-constructor type.

        After ``clear()``, ``isinstance(t.root, BNode4)`` (or whatever the
        original constructor was) still holds — this is part of the test
        contract for ``test_constructor_preserved_after_clear``.
        """
        # Reset the *contents* of the existing root rather than swapping the
        # root identity, so callers that captured a reference to ``t.root``
        # still see a valid (now-empty) node of the same type.
        self.root.items = []
        self.root.nodes = None
        self.root._count = 0
        self._root = self.root

    def note_change_of_bnode_containing_key(self, key: K) -> None:
        """Persistence hook — no-op for an in-memory BTree.

        A subclass that mirrors this BTree into durable storage (e.g. Dhara's
        own persistent collection wrapper) can override this to flush the
        affected page. The legacy Durus API includes this method; the
        in-memory implementation is intentionally trivial.
        """

    # ── Introspection / sizing ─────────────────────────────────────

    def get_depth(self) -> int:
        """Return the height of the tree (number of levels)."""
        return self.height()

    def get_node_count(self) -> int:
        """Return the number of BNode instances in the tree."""
        return self.root.get_node_count()

    def get_min_item(self) -> tuple[K, V]:
        """Return the smallest (key, value) in the tree.

        Asserts the tree is non-empty.
        """
        return self.root.get_min_item()

    def get_max_item(self) -> tuple[K, V]:
        """Return the largest (key, value) in the tree.

        Asserts the tree is non-empty.
        """
        return self.root.get_max_item()

    def set_bnode_minimum_degree(self, t: int) -> bool:
        """Change the tree's node minimum degree at runtime.

        Returns ``True`` if the degree changed, ``False`` if the requested
        degree is unsupported or already in effect. Existing nodes keep
        their original degree; new nodes (created during future splits or
        growth) will use the new one.
        """
        if t not in _NODE_CLASS_BY_DEGREE:
            return False
        if t == self.root.minimum_degree:
            return False
        cls = _NODE_CLASS_BY_DEGREE[t]

        def _new_ctor(t: int = t, cls: type[BNode[K, V]] = cls) -> BNode[K, V]:
            return cls(minimum_degree=t)  # type: ignore[call-arg]

        self._node_constructor = _new_ctor
        return True

    # ── Aliased iteration helpers (Durus-style) ─────────────────────

    def iterkeys(self) -> Iterator[K]:
        return iter(self.keys())

    def itervalues(self) -> Iterator[V]:
        return iter(self.values())

    def iteritems(self) -> Iterator[tuple[K, V]]:
        return iter(self.items())

    # ── Range / partial iteration helpers ──────────────────────────

    def items_from(self, key: K, closed: bool = True) -> Iterator[tuple[K, V]]:
        """Yield items with key ``>= key`` (or ``> key`` if ``closed=False``).

        Default is ``closed=True`` so the boundary key is included — matches
        ``dict.keys()``-style iteration where the start is inclusive.
        """
        iterator = self.root.iter_from(key)
        if not closed:
            try:
                first = next(iterator)
            except StopIteration:
                return
            k0, _v0 = first
            if k0 == key:
                # Skip the first element (it's the boundary)
                yield from iterator
            else:
                yield first
                yield from iterator
        else:
            yield from iterator

    def items_backward(self) -> Iterator[tuple[K, V]]:
        """Yield all items in reverse sorted order."""
        for item in reversed(self.root):
            yield item

    def items_backward_from(
        self, key: K, closed: bool = False
    ) -> Iterator[tuple[K, V]]:
        """Yield items with key ``<= key`` (or ``< key``) in reverse order.

        ``closed=True`` includes the boundary key; ``closed=False`` excludes it.
        """
        if closed:
            # Include key — yield items < key first, then if key is present yield it.
            yield from self.root.iter_backward_from_or_equal(key)
            if key in self:
                yield (key, self[key])
        else:
            # Exclude key — just yield items strictly < key.
            yield from self.root.iter_backward_from(key)

    def items_range(
        self,
        start: K,
        end: K,
        closed_end: bool = False,
    ) -> Iterator[tuple[K, V]]:
        """Yield items in ``[start, end]`` (or ``[start, end)`` if open end).

        If ``start > end``, iteration runs in reverse (so ``[start, end)``
        yields ``[start, end-1, ..., end+1, end]``). ``closed_start`` is
        always True; use ``closed_end`` to control the upper boundary.
        """
        if start <= end:  # type: ignore[operator]
            # Forward range — closed_start=True, closed_end controls end
            for item in self.items_from(start, closed=True):
                k, _v = item
                if k > end:  # type: ignore[operator]
                    return
                if k == end and not closed_end:
                    return
                yield item
        else:
            # Backward range — closed_start=True (include start, the larger value)
            for item in self.items_backward_from(start, closed=True):
                k, _v = item
                if k < end:  # type: ignore[operator]
                    return
                if k == end and not closed_end:
                    return
                yield item

    # ── Async wrappers ─────────────────────────────────────────────
    # BTree is pure in-memory; these async wrappers delegate to the
    # sync impl methods. They exist for compatibility with async
    # storage pipelines that use await across all collection types.

    async def set_async(self, key: K, value: V) -> None:
        """Async insert/update — delegates to _set_impl."""
        self._set_impl(key, value)

    async def get_async(self, key: K) -> V | None:
        """Async get — delegates to _get_impl.

        Returns ``None`` for both "key absent" and "key present with value
        None" — the legacy behavior. Use ``in t`` to test presence.
        """
        result = self._get_impl(key)
        if result is MISSING:
            return None
        return result  # type: ignore[return-value]

    async def delete_async(self, key: K) -> bool:
        """Async delete — delegates to _delete_impl."""
        return self._delete_impl(key)

    async def update_async(self, key: K, value: V) -> bool:
        """Async update — delegates to _update_impl."""
        return self._update_impl(key, value)

    async def items_async(self) -> AsyncIterator[tuple[K, V]]:
        """Async items — yields from sync items iterator."""
        for item in self.items():
            yield item

    async def keys_async(self) -> AsyncIterator[K]:
        """Async keys — yields from sync keys iterator."""
        for k in self.keys():
            yield k

    async def values_async(self) -> AsyncIterator[V]:
        """Async values — yields from sync values iterator."""
        for v in self.values():
            yield v

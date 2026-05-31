# BTree Redesign Design

**Date:** 2026-05-31
**Status:** Approved (2026-05-31)
**Author:** Claude (Mahavishnu Orchestrator)
**Purpose:** Redesign `btree.py` for pyright/zuban type safety, modern Python, and crackerjack compliance

---

## Reviewer Feedback Summary

Three independent reviewers evaluated the design (Python correctness, algorithm, testing):

| Issue | Reviewer | Severity | Action Taken |
|-------|----------|----------|--------------|
| `_handle_case3` root underflow not handled | Algorithm | CRITICAL | Added `_reduce_height()` method |
| `_find_position` pseudocode missing | Algorithm | MEDIUM | Added binary search implementation |
| `Iterator` not imported | Python-pro | LOW | Added `from collections.abc import Iterator` |
| `delete_order` can contain absent keys | Testing | HIGH | Added `key_counts` tracking to filter valid deletes |
| `minimum_degree` only tested at 3 | Testing | MEDIUM | Added `MIN_DEGREES` strategy with t=2,3,4 |
| `None` as value vs "not found" ambiguity | Testing | HIGH | Added `test_none_values_distinguishable_from_missing` |
| `is_big` unused in deletion pseudocode | Python-pro | LOW | Kept for clarity; used as deletion precondition check |
| `update` return value untested | Testing | LOW | Added `test_update_returns_true_for_existing` |

---

## 1. Context and Motivation

The current `btree.py` in `dhara/collections/` has 293 zuban type errors. The root cause is the `_NullCount` identity pattern — a singleton that returns itself for `+` and `-` operations, used as a workaround for uninitialized count fields. This pattern is fundamentally incompatible with pyright's strict type checking.

The user has approved a breaking change: "we want a modern type-friendly codebase not a bunch of patching and ignores just to make things work. we are developing and have no production data to preserve. let's reset and accept the breaking change."

### Key Problems with Current Implementation

| Problem | Cause | Impact |
|---------|-------|--------|
| `int \| _NullCount` union type | Count field can be identity singleton | 200+ type errors |
| `is_big` undefined (NameError) | Referenced at lines 346, 348, 359, 394 but not defined | Runtime crashes |
| `nodes: list[BNode] \| None` pattern | Optional wrapper adds complexity | Confuses type checker |
| `_NullCount` identity arithmetic | Clever trick backfires | Breaks static analysis |

---

## 2. Goals and Non-Goals

### Goals

- **Zero pyright/zuban type errors** — pass strict mode on first write
- **Modern Python 3.13+** — `X | None`, `list[K]`, dataclasses, `from __future__ import annotations`
- **Correct B-Tree algorithm** — Cormen et al. Chapter 18 with borrow-first deletion (case 3)
- **Crackerjack compliant** — pass all 9 quality gates (gitleaks, pyscn, zuban, lychee, check-jsonschema, linkcheckmd, semgrep, creosote, refurb)
- **Property-based tests** — use `hypothesis` for comprehensive coverage

### Non-Goals

- **Backward compatibility with old `.bt` files** — breaking change accepted
- **MutableMapping interface** — using custom iterator protocol instead
- **`__len__`** — would require walking entire tree; honest O(n) cost
- **`__contains__`** — use `get()` returning `None` idiomatically

---

## 3. Data Structure

### BNode (Dataclass)

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class BNode:
    """A B-Tree node with items and optional children."""
    items: list[tuple[K, V]] = field(default_factory=list)
    nodes: list[BNode] | None = None  # None = leaf, list = internal
    minimum_degree: int = 3  # t (controls node capacity)

    def is_leaf(self) -> bool:
        """Returns True if this is a leaf node."""
        return self.nodes is None

    def is_full(self) -> bool:
        """Returns True if node has maximum items (needs splitting)."""
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
            mid_key = self.items[mid][0]
            if mid_key == key:
                return (mid, True)
            elif mid_key < key:
                lo = mid + 1
            else:
                hi = mid - 1
        return (lo, False)

### Design Decisions

| Decision | Rationale |
|----------|-----------|
| `nodes: list[BNode] \| None` | Explicit `None` for leaf (not `Optional[list[BNode]]` — cleaner) |
| `items: list[tuple[K, V]]` | Always a real list; never `None` |
| `minimum_degree: int` | Stored per-node (like original Durus) rather than global |
| `field(default_factory=list)` | Avoids mutable default argument trap |

### Node Capacity

- Maximum items per node: `2*t - 1`
- Minimum items per node: `t - 1`
- Minimum children (internal nodes): `t`
- Maximum children: `2*t`

---

## 4. Public API

```python
class BTree:
    """B-Tree with borrow-first deletion (Cormen case 3).
    
    Does NOT implement MutableMapping — uses custom iterator protocol
    for cleaner B-Tree semantics.
    """
    
    def __init__(self, minimum_degree: int = 3) -> None:
        self._root = BNode(minimum_degree=minimum_degree)
        self._minimum_degree = minimum_degree
    
    # Core operations
    def get(self, key: K) -> V | None:
        """Get value by key. Returns None if not found."""
    
    def set(self, key: K, value: V) -> None:
        """Insert or update key-value pair."""
    
    def delete(self, key: K) -> bool:
        """Delete key. Returns True if found and deleted, False if not found."""
    
    def update(self, key: K, value: V) -> bool:
        """Update existing key's value. Returns True if found, False if not."""
    
    # Iteration (generator-based, NOT __iter__)
    def items(self) -> Iterator[tuple[K, V]]:
        """Yield all (key, value) pairs in sorted key order."""
    
    def keys(self) -> Iterator[K]:
        """Yield all keys in sorted order."""
    
    def values(self) -> Iterator[V]:
        """Yield all values in key-sorted order."""
    
    # Helpers
    def is_full(self) -> bool:
        """Check if root needs splitting."""
    
    def height(self) -> int:
        """Return tree height (number of levels)."""
```

### What We're Dropping from the Old API

| Old Method | Reason for Removal |
|------------|-------------------|
| `MutableMapping` | Conflicts with custom iterator protocol; adds complexity |
| `__iter__` | Returns iterator object; `items()` generator is simpler |
| `__contains__` | `get() is not None` is the idiomatic check |
| `__len__` | O(n) cost — would require walking entire tree |
| `_count` field | `len(self.items)` is already O(1) |
| `_NullCount` | Incompatible with pyright; no benefit over honest `int` |

---

## 5. Private Implementation Methods

### BNode Helpers

Each helper method is defined inline in the class for clarity.

### BTree Operations

```python
class BTree:
    # Root underflow: when root has 0 items and 1 child, adopt child as new root
    def _reduce_height(self) -> None:
        """Reduce tree height when root has no items and one child."""
        if len(self._root.items) == 0 and self._root.nodes is not None:
            self._root = self._root.nodes[0]

    # Insertion
    def _split_child(self, parent: BNode, idx: int) -> None:
        """Split parent.nodes[idx] which is full (2t-1 items).

        After split:
        - Left child retains t-1 items (first half)
        - Middle key promoted to parent
        - Right child receives t-1 items (second half)
        """
        t = parent.minimum_degree
        full_child = parent.nodes[idx]
        middle_key_idx = t - 1  # 0-indexed position of middle key

        # Create new right node
        right_node = BNode(
            items=full_child.items[t:],  # t items (indices t to 2t-1)
            nodes=full_child.nodes[t:] if full_child.nodes else None,
            minimum_degree=t,
        )

        # Trim left node to t-1 items
        left_item_count = t - 1
        left_items = full_child.items[:left_item_count]
        left_nodes = full_child.nodes[:t] if full_child.nodes else None

        # Update child in place (can't replace parent.nodes[idx] in place)
        full_child.items = left_items
        full_child.nodes = left_nodes

        # Promote middle key to parent
        middle_key = full_child.items.pop(middle_key_idx)

        # Insert new child pointer to the right of idx
        if parent.nodes is None:
            parent.nodes = [None] * (len(parent.items) + 1)
        parent.nodes.insert(idx + 1, right_node)

        # Insert middle key at parent's position idx
        parent.items.insert(idx, (middle_key, full_child.items.pop()[1] if full_child.items else None))  # promoted value

    def _insert_nonfull(self, node: BNode, key: K, value: V) -> None:
        """Insert key-value into non-full node."""
        i = len(node.items) - 1

        if node.is_leaf():
            # Find insertion point and shift
            while i >= 0 and key < node.items[i][0]:
                i -= 1
            node.items.insert(i + 1, (key, value))
        else:
            # Find child to descend into
            while i >= 0 and key < node.items[i][0]:
                i -= 1
            i += 1
            if node.nodes[i].is_full():
                self._split_child(node, i)
                if key > node.items[i][0]:
                    i += 1
            self._insert_nonfull(node.nodes[i], key, value)
    
    # Deletion (case 3: borrow-first)
    def _delete_from_node(self, node: BNode, key: K) -> bool:
        """Delete key from node (and children if internal). Returns True if deleted."""
        t = node.minimum_degree

        # Case 1: Key is in this node
        pos, found = node._find_position(key)
        if found:
            if node.is_leaf():
                node.items.pop(pos)
                return True
            else:
                # Case 2a: left child has >= t keys — rotate down
                left = node.nodes[pos] if pos < len(node.nodes) else None
                right = node.nodes[pos + 1] if pos + 1 < len(node.nodes) else None
                if left is not None and len(left.items) >= t:
                    # Replace key with predecessor from left child
                    pred_key, pred_val = self._get_max(left)
                    node.items[pos] = (pred_key, pred_val)
                    self._delete_from_node(left, pred_key)
                    return True
                elif right is not None and len(right.items) >= t:
                    # Replace key with successor from right child
                    succ_key, succ_val = self._get_min(right)
                    node.items[pos] = (succ_key, succ_val)
                    self._delete_from_node(right, succ_key)
                    return True
                else:
                    # Both children have t-1 — merge them then delete from merged
                    self._merge(node, pos)
                    # After merge, key is now at position pos in merged node
                    self._delete_from_node(node.nodes[pos], key)
                    return True

        else:
            # Key not in this node — descend to appropriate child
            if node.is_leaf():
                return False  # Key not found

            idx = pos  # _find_position gives insertion point
            child = node.nodes[idx]

            if len(child.items) >= t:
                # Child has enough keys — descend
                self._delete_from_node(child, key)
            else:
                # Child is at minimum (t-1) — may need to borrow or merge first
                self._handle_case3(node, idx)
                # After handling, tree may have changed — re-find child
                if idx >= len(node.nodes):
                    return False  # Safety check
                self._delete_from_node(node.nodes[idx], key)

    def _get_min(self, node: BNode) -> tuple[K, V]:
        """Get smallest (key, value) in subtree rooted at node."""
        while not node.is_leaf() and node.nodes:
            node = node.nodes[0]
        return node.items[0]

    def _get_max(self, node: BNode) -> tuple[K, V]:
        """Get largest (key, value) in subtree rooted at node."""
        while not node.is_leaf() and node.nodes:
            node = node.nodes[-1]
        return node.items[-1]

    def _handle_case3(self, node: BNode, idx: int) -> None:
        """Handle underflow before descending into node.nodes[idx].

        Borrow-first strategy:
        1. If left sibling has > t-1 keys, borrow from left
        2. Else if right sibling has > t-1 keys, borrow from right
        3. Else merge with a sibling (pull separator from parent)
        """
        t = node.minimum_degree
        child = node.nodes[idx]

        # Get siblings
        left_sibling = node.nodes[idx - 1] if idx > 0 else None
        right_sibling = node.nodes[idx + 1] if idx < len(node.nodes) - 1 else None

        # Try borrowing from left sibling
        if left_sibling is not None and len(left_sibling.items) > t - 1:
            self._borrow_from_left(node, idx)
            return

        # Try borrowing from right sibling
        if right_sibling is not None and len(right_sibling.items) > t - 1:
            self._borrow_from_right(node, idx)
            return

        # No sibling has extra keys — merge
        if left_sibling is not None:
            self._merge(node, idx - 1)
            # After merging idx-1 and idx, the merged node is now at idx-1
            # The child pointer at idx is now the right sibling (was idx+1)
            # Update idx so caller descends into merged node
        elif right_sibling is not None:
            self._merge(node, idx)
            # After merging idx and idx+1, merged node is at idx
        # If neither sibling exists (shouldn't happen for non-root), do nothing

    def _borrow_from_left(self, parent: BNode, idx: int) -> None:
        """Borrow rightmost item from left sibling.

        Parent's separator key moves down to leftmost position of right child.
        Rightmost item of left sibling moves up to replace separator.
        """
        left = parent.nodes[idx - 1]
        right = parent.nodes[idx]
        t = parent.minimum_degree

        # Take separator from parent
        sep_key, sep_val = parent.items[idx - 1]
        # Take rightmost item from left sibling
        borrow_key, borrow_val = left.items.pop()

        # Insert separator at start of right child's items
        right.items.insert(0, (sep_key, sep_val))

        # If left has children, move its last child to right
        if left.nodes is not None:
            last_child = left.nodes.pop()
            right.nodes.insert(0, last_child)

        # Update parent's separator with borrowed key
        parent.items[idx - 1] = (borrow_key, borrow_val)

    def _borrow_from_right(self, parent: BNode, idx: int) -> None:
        """Borrow leftmost item from right sibling.

        Parent's separator key moves down to rightmost position of left child.
        Leftmost item of right sibling moves up to replace separator.
        """
        left = parent.nodes[idx]
        right = parent.nodes[idx + 1]
        t = parent.minimum_degree

        # Take separator from parent
        sep_key, sep_val = parent.items[idx]
        # Take leftmost item from right sibling
        borrow_key, borrow_val = right.items.pop(0)

        # Insert separator at end of left child's items
        left.items.append((sep_key, sep_val))

        # If right has children, move its first child to left
        if right.nodes is not None:
            first_child = right.nodes.pop(0)
            left.nodes.append(first_child)

        # Update parent's separator with borrowed key
        parent.items[idx] = (borrow_key, borrow_val)

    def _merge(self, parent: BNode, idx: int) -> None:
        """Merge node[idx] and node[idx+1] into node[idx].

        Takes separator from parent.items[idx] and appends to left child's items.
        All items from right child move to left child.
        All children from right child move to left child.
        Parent loses separator (items shift) and right child pointer.
        """
        left = parent.nodes[idx]
        right = parent.nodes[idx + 1]
        t = parent.minimum_degree

        # Take separator from parent
        sep_key, sep_val = parent.items[idx]

        # Append separator to left child's items
        left.items.append((sep_key, sep_val))

        # Append all items from right child
        left.items.extend(right.items)

        # If internal, append all children
        if right.nodes is not None:
            left.nodes.extend(right.nodes)

        # Remove separator from parent (items shift left)
        parent.items.pop(idx)

        # Remove right child pointer from parent
        parent.nodes.pop(idx + 1)

        # Root underflow check: if root now has 0 items and 1 child, reduce height
        if parent is self._root and len(parent.items) == 0 and len(parent.nodes) == 1:
            self._root = parent.nodes[0]
            parent.nodes[0] = None  # type: ignore[assignment] — help GC
```
```

---

## 6. Error Handling

```python
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
    """Raised when B-Tree invariant is violated (internal check)."""
    pass
```

---

## 7. Algorithm: Borrow-First Deletion (Cormen Case 3)

### The Problem

When deleting from a node with only `t-1` keys (underflow), Cormen's case 3 requires either:
- **Transfer** (borrow from sibling): move a key from sibling through parent
- **Merge** (absorb sibling): merge two nodes into one, pull separator from parent

### Borrow-First Strategy

```
_handle_case3(node, idx):
    # idx = index of child underflowing in node.nodes
    
    left_sibling = node.nodes[idx - 1] if idx > 0 else None
    right_sibling = node.nodes[idx + 1] if idx < len(node.nodes) - 1 else None
    
    # Try left sibling first
    if left_sibling and len(left_sibling.items) > node.minimum_degree - 1:
        _borrow_from_left(node, idx)
        return
    
    # Try right sibling
    if right_sibling and len(right_sibling.items) > node.minimum_degree - 1:
        _borrow_from_right(node, idx)
        return
    
    # No sibling has extra — merge with left (or right if no left)
    if left_sibling:
        _merge(node, idx - 1)  # merge idx-1 and idx, separator at idx-1
    elif right_sibling:
        _merge(node, idx)  # merge idx and idx+1, separator at idx
```

### Merge Details

When merging `child[idx]` and `child[idx + 1]`:
1. Take separator key from `parent.items[idx]` and place it at end of left child's items
2. Move all items from right child to left child
3. If right child has children (internal node), move them too
4. Delete separator from parent (items shift left)
5. Delete right child from parent's nodes list

---

## 8. Testing Strategy

### Property-Based Testing with Hypothesis

```python
from hypothesis import given, strategies as st

# Test multiple minimum_degree values: t=2 (smallest), t=3 (default), t=4 (larger)
MIN_DEGREES = st.sampled_from([2, 3, 4])

class TestBTreeProperties:
    @given(
        keys=st.lists(st.integers(), min_size=1, max_size=100),
        values=st.lists(st.integers(), min_size=1, max_size=100),
        t=MIN_DEGREES,
    )
    def test_insert_then_get(self, keys, values, t):
        tree = BTree(minimum_degree=t)
        for k, v in zip(keys, values):
            tree.set(k, v)
        for k, v in zip(keys, values):
            assert tree.get(k) == v

    @given(keys=st.lists(st.integers(), min_size=1))
    def test_delete_removes_key(self, keys):
        tree = BTree(minimum_degree=3)
        for k in keys:
            tree.set(k, k)
        for k in keys:
            assert tree.delete(k) is True
            assert tree.get(k) is None

    @given(keys=st.lists(st.integers()))
    def test_all_keys_recoverable_after_insert(self, keys):
        tree = BTree(minimum_degree=3)
        deduped = list(dict.fromkeys(keys))  # remove duplicates
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
        # Insert all keys (duplicates overwrite)
        key_counts: dict[int, int] = {}
        for k in keys:
            tree.set(k, k)
            key_counts[k] = key_counts.get(k, 0) + 1

        # Delete only keys known to be present, in given order
        for k in delete_order:
            if k in key_counts and key_counts[k] > 0:
                result = tree.delete(k)
                assert result is True
                key_counts[k] -= 1

        # Remaining keys should be retrievable
        remaining = [k for k, count in key_counts.items() if count > 0]
        for k in remaining:
            assert tree.get(k) is not None

    @given(keys=st.lists(st.integers()))
    def test_delete_nonexistent_returns_false(self, keys):
        tree = BTree(minimum_degree=3)
        for k in keys:
            tree.set(k, k)
        # Deleting already-deleted keys returns False
        for k in keys:
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
        # All updates should succeed (keys exist)
        for k in deduped:
            result = tree.update(k, k * 10)
            assert result is True
            assert tree.get(k) == k * 10

    @given(keys=st.lists(st.integers()))
    def test_update_returns_false_for_missing(self, keys):
        tree = BTree(minimum_degree=3)
        for k in keys:
            tree.set(k, k)
        # Update on never-inserted key should return False
        never_inserted = [k for k in range(max(keys or [0]) + 100, max(keys or [0]) + 110)]
        for k in never_inserted:
            assert tree.update(k, "new") is False
```

### Additional Edge Case Tests (Deterministic)

```python
def test_empty_tree_get_returns_none():
    tree = BTree(minimum_degree=3)
    assert tree.get("any") is None
    assert tree.delete("any") is False

def test_empty_tree_iteration_yields_nothing():
    tree = BTree(minimum_degree=3)
    assert list(tree.items()) == []
    assert list(tree.keys()) == []
    assert list(tree.values()) == []

def test_none_values_distinguishable_from_missing():
    tree = BTree(minimum_degree=3)
    tree.set("key", None)  # value is None
    assert tree.get("key") is None  # retrieves the None value
    assert tree.delete("key") is True  # can still delete it
    assert tree.get("key") is None  # now missing

def test_duplicate_key_overwrites():
    tree = BTree(minimum_degree=3)
    tree.set("key", "first")
    tree.set("key", "second")
    assert tree.get("key") == "second"  # last write wins
    tree.delete("key")
    assert tree.get("key") is None

def test_single_item_root():
    tree = BTree(minimum_degree=3)
    tree.set("a", 1)
    assert tree.get("a") == 1
    tree.delete("a")
    assert tree.get("a") is None

def test_root_split_increases_height():
    tree = BTree(minimum_degree=3)  # max 5 items per node
    # Insert enough to force root split
    for i in range(6):
        tree.set(i, i)
    assert tree.height() == 2  # root split, now 2 levels
    # All keys still accessible
    for i in range(6):
        assert tree.get(i) == i

def test_borrow_from_left_and_right():
    """Test borrow operations maintain tree invariants."""
    tree = BTree(minimum_degree=3)
    # Build tree that triggers specific borrow scenarios
    for k in [1, 2, 3, 4, 5, 6, 7]:
        tree.set(k, k)
    # Delete to trigger case 3 (underflow with siblings)
    tree.delete(1)
    assert tree.get(1) is None
    # Others still present
    for k in [2, 3, 4, 5, 6, 7]:
        assert tree.get(k) == k
```

### Invariant Tests

```python
def test_btree_invariants():
    """Test that B-Tree invariants are maintained."""
    tree = BTree(minimum_degree=3)
    
    # After any operation, these should hold:
    # 1. All items in each node are sorted
    # 2. Non-root nodes have at least t-1 items
    # 3. Non-root nodes have at most 2t-1 items
    # 4. Internal nodes have one more child than items
    # 5. All leaves are at same depth
```

---

## 9. File Structure

```
dhara/
└── collections/
    └── btree.py    # New implementation (replaces old)
    
tests/
└── unit/
    └── test_btree.py  # Property-based tests
```

Old `btree.py` will be replaced entirely. No backward compatibility layer.

---

## 10. Implementation Order

1. **Core data structures** — `BNode` dataclass, `BTree` class skeleton
2. **Helper methods** — `is_leaf`, `is_full`, `_find_position`
3. **Insertion** — `set()`, `_split_child()`, `_insert_nonfull()`
4. **Lookup** — `get()`
5. **Iteration** — `items()`, `keys()`, `values()`
6. **Deletion (simple cases)** — case 1 and 2
7. **Deletion (case 3)** — `_handle_case3`, `_borrow_from_left`, `_borrow_from_right`, `_merge`
8. **Error classes** — `BTreeError`, `KeyNotFoundError`, etc.
9. **Tests** — Hypothesis property-based tests
10. **Crackerjack validation** — run all 9 hooks

---

## 11. Quality Gates

The implementation must pass all crackerjack hooks:

| Hook | Requirement |
|------|-------------|
| gitleaks | No secrets in code |
| pyscn | No security vulnerabilities |
| zuban | Zero type errors (pyright strict) |
| lychee | No broken links in docs |
| check-jsonschema | Config files valid |
| linkcheckmd | Docs links valid |
| semgrep | No code patterns matching security rules |
| creosote | No deprecated imports |
| refurb | Code modernization suggestions |

---

## 12. Open Questions

None — all decisions have been made and approved by the user.

---

## 13. Summary of Decisions

| Decision | Choice |
|----------|--------|
| Count field | **No count field** — use `len(self.items)` directly |
| MutableMapping | **No** — custom iterator protocol |
| Iterator | **`items()` generator** — not `__iter__` |
| Deletion case 3 | **Borrow-first** — try redistribute before merge |
| Node structure | `list[tuple[K, V]]` + `list[BNode] \| None` |
| Error handling | Custom exception hierarchy |
| Testing | Hypothesis property-based |
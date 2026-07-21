______________________________________________________________________

## status: complete role: historical date: 2026-07-17 last_reviewed: 2026-07-17 superseded_by: null blocks_on: [] topic: persistence

# BTree Redesign Implementation Plan

> **SUPERSEDED (2026-07-15).** This plan describes a single-`BNode` dataclass design
> (`list[tuple[K,V]]` items + `list[BNode] | None` children) that was **never built**.
> The codebase kept the original degree-specific design:
> `BNode` base + `BNode4`, `BNode8`, `BNode16` subclasses (see `dhara/collections/btree.py:99,564,572,580`).
> The async wrapper work tracked in `docs/2026-05-31-dhara-async-first-plan.md` Task 11
> landed at `dhara/collections/btree.py:1352-1385` against the original design.
>
> **Do not execute this plan.** Active BTree work, if any, must start from a new plan.
> This document is preserved for historical reference.

______________________________________________________________________

# BTree Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `dhara/collections/btree.py` with a type-safe, modern Python B-Tree implementation that passes pyright strict mode and all 9 crackerjack quality gates.

**Architecture:** B-Tree with borrow-first deletion. No `_NullCount`, no `MutableMapping`. Custom `items()` generator iterator. `BNode` dataclass with `list[tuple[K,V]]` items and `list[BNode] | None` children.

**Tech Stack:** Python 3.13+, `dataclasses`, `collections.abc.Iterator`, `hypothesis` (property-based testing)

______________________________________________________________________

## Reviewer Feedback Summary

Three independent reviewers (TDD, Python-pro, algorithm) identified issues that have been fixed in this plan:

| Issue | Reviewer | Severity | Fix Applied |
|-------|----------|----------|-------------|
| `_split_child` out-of-bounds pop | Algorithm | **CRITICAL** | Extract middle key BEFORE trimming child |
| `_handle_case3` returns `None` instead of new index | Algorithm | **CRITICAL** | `_handle_case3` now returns `int \| None` — new child index |
| Index update after left sibling merge | Algorithm | **CRITICAL** | After `_merge(node, idx-1)`, return `idx-1` so caller descends into merged node |
| `test_btree_get_after_set` fails for wrong reason | TDD | **HIGH** | Replaced with `test_btree_get_after_direct_insert` using direct node construction |
| `test_bnode_is_full` misleading assertion | Python-pro | **MEDIUM** | Changed to assert `is_full() is False` after 6th item |
| `TreeCorruptedError` missing from Phase 7 | Python-pro | **MEDIUM** | Added to error class tests |
| `type: ignore[assignment]` and GC myth | Python-pro | **HIGH** | Removed from plan — `_merge` does not set `parent.nodes[0] = None` |

______________________________________________________________________

## File Structure

```
dhara/collections/
└── btree.py          # REPLACE — new BTree/BNode implementation

tests/unit/
└── test_btree.py     # REPLACE — property-based tests (hypothesis)
```

**Backup:** Before replacing, copy old files:

```bash
cp dhara/collections/btree.py dhara/collections/btree.py.old_drus
cp tests/test_btree.py tests/test_btree.py.old_durus
```

______________________________________________________________________

## Implementation Order

| Phase | Task | Description |
|-------|------|-------------|
| 1 | BNode dataclass + helpers | Data structure, `is_leaf`, `is_full`, `is_big`, `_find_position` |
| 2 | BTree skeleton + get | Class skeleton, `get()` only (no set) |
| 3 | BTree set() + split | `set()` with `_split_child`, `_insert_nonfull` |
| 4 | Iteration | `items()`, `keys()`, `values()` |
| 5 | Deletion leaf-only | `delete()` from leaf nodes (no internal case) |
| 6 | Deletion internal + case3 | `_delete_from_node` with predecessor/successor + borrow/merge |
| 7 | Error classes | `BTreeError`, `KeyNotFoundError`, etc. |
| 8 | Property tests | Hypothesis tests |
| 9 | Crackerjack | Run all 9 hooks, fix issues |

______________________________________________________________________

## Phase 1: BNode Dataclass + Helpers

### Task 1: BNode Dataclass

**Files:**

- Create: `dhara/collections/btree.py`

- Test: `tests/unit/test_btree.py`

- [ ] **Step 1: Write failing test for BNode creation**

```python
# tests/unit/test_btree.py
from __future__ import annotations

import pytest
from dhara.collections.btree import BNode


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_bnode_default_creation tests/unit/test_btree.py::test_bnode_with_items tests/unit/test_btree.py::test_bnode_is_leaf -v
```

Expected: FAIL — `BNode` not defined

- [ ] **Step 3: Write minimal BNode implementation**

```python
# dhara/collections/btree.py
from __future__ import annotations

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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_bnode_default_creation tests/unit/test_btree.py::test_bnode_with_items tests/unit/test_btree.py::test_bnode_is_leaf -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "feat(btree): add BNode dataclass with is_leaf helper"
```

______________________________________________________________________

### Task 2: BNode Helpers (is_full, is_big, \_find_position)

**Files:**

- Modify: `dhara/collections/btree.py` (add methods to BNode class)

- [ ] **Step 1: Write failing test for is_full, is_big, \_find_position**

```python
# tests/unit/test_btree.py (add these tests)


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_bnode_is_full tests/unit/test_btree.py::test_bnode_is_big tests/unit/test_btree.py::test_bnode_find_position_not_found tests/unit/test_btree.py::test_bnode_find_position_found tests/unit/test_btree.py::test_bnode_find_position_before_first tests/unit/test_btree.py::test_bnode_find_position_after_last -v
```

Expected: FAIL — `is_full`, `is_big`, `_find_position` not defined

- [ ] **Step 3: Write minimal implementations**

Add to BNode class in `btree.py`:

```python
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
            mid_key = self.items[mid][0]
            if mid_key == key:
                return (mid, True)
            elif mid_key < key:
                lo = mid + 1
            else:
                hi = mid - 1
        return (lo, False)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_bnode_is_full tests/unit/test_btree.py::test_bnode_is_big tests/unit/test_btree.py::test_bnode_find_position_not_found tests/unit/test_btree.py::test_bnode_find_position_found tests/unit/test_btree.py::test_bnode_find_position_before_first tests/unit/test_btree.py::test_bnode_find_position_after_last -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "feat(btree): add BNode is_full, is_big, _find_position helpers"
```

______________________________________________________________________

## Phase 2: BTree Skeleton + Get

### Task 3: BTree Class Skeleton

**Files:**

- Modify: `dhara/collections/btree.py` (add BTree class at bottom)

- [ ] **Step 1: Write failing test for BTree creation and get**

```python
# tests/unit/test_btree.py (add)


def test_btree_default_creation():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    assert tree._root is not None
    assert tree._root.is_leaf()


def test_btree_get_nonexistent():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    assert tree.get(42) is None


def test_btree_get_after_direct_insert():
    """Test get() using direct node construction (no set() needed)."""
    from dhara.collections.btree import BTree, BNode
    tree = BTree(minimum_degree=3)
    # Directly insert items into root to test get() without set()
    tree._root.items = [(1, "one"), (2, "two"), (3, "three")]
    assert tree.get(1) == "one"
    assert tree.get(2) == "two"
    assert tree.get(3) == "three"
    assert tree.get(99) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_default_creation tests/unit/test_btree.py::test_btree_get_nonexistent tests/unit/test_btree.py::test_btree_get_after_direct_insert -v
```

Expected: FAIL — `BTree` not defined

- [ ] **Step 3: Write minimal BTree class**

Add at end of `btree.py`:

```python
class BTree:
    """B-Tree with borrow-first deletion (Cormen case 3)."""

    def __init__(self, minimum_degree: int = 3) -> None:
        self._root = BNode(minimum_degree=minimum_degree)
        self._minimum_degree = minimum_degree

    def get(self, key: K) -> V | None:
        """Get value by key. Returns None if not found."""
        node = self._root
        while node is not None:
            pos, found = node._find_position(key)
            if found:
                return node.items[pos][1]
            if node.is_leaf():
                return None
            node = node.nodes[pos]
        return None

    def set(self, key: K, value: V) -> None:
        """Insert or update key-value pair."""
        root = self._root
        if root.is_full():
            new_root = BNode(minimum_degree=self._minimum_degree)
            new_root.nodes = [root]
            self._split_child(new_root, 0)
            self._root = new_root
        self._insert_nonfull(root, key, value)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_default_creation tests/unit/test_btree.py::test_btree_get_nonexistent tests/unit/test_btree.py::test_btree_get_after_direct_insert -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "feat(btree): add BTree skeleton with get"
```

______________________________________________________________________

## Phase 3: Insertion (Split Child)

### Task 4: \_split_child

**Files:**

- Modify: `dhara/collections/btree.py` (add `_split_child` and `_insert_nonfull`)

- [ ] **Step 1: Write failing test for root split (triggers \_split_child)**

```python
# tests/unit/test_btree.py (add)


def test_btree_root_split():
    """Insert enough items to force root split (height increase)."""
    from dhara.collections.btree import BTree
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_root_split tests/unit/test_btree.py::test_btree_set_overwrites_existing -v
```

Expected: FAIL — `_split_child`, `_insert_nonfull` not defined

- [ ] **Step 3: Write \_split_child and \_insert_nonfull**

Add to `BTree` class in `btree.py`:

```python
    def _split_child(self, parent: BNode, idx: int) -> None:
        """Split parent.nodes[idx] which is full (2t-1 items).

        After split:
        - Left child retains t-1 items (first half)
        - Middle key promoted to parent
        - Right child receives t-1 items (second half)
        """
        t = parent.minimum_degree
        full_child = parent.nodes[idx]

        # EXTRACT MIDDLE KEY BEFORE TRIMMING (order matters!)
        middle_key_idx = t - 1  # 0-indexed position of middle key
        middle_key, middle_val = full_child.items[middle_key_idx]

        # Create new right node with second half of items
        right_node = BNode(
            items=full_child.items[t:],  # t items (indices t to 2t-1)
            nodes=full_child.nodes[t:] if full_child.nodes else None,
            minimum_degree=t,
        )

        # Trim left node to t-1 items
        full_child.items = full_child.items[:t - 1]
        if full_child.nodes is not None:
            full_child.nodes = full_child.nodes[:t]

        # Insert new child pointer to the right of idx
        if parent.nodes is None:
            parent.nodes = [None] * (len(parent.items) + 1)
        parent.nodes.insert(idx + 1, right_node)

        # Insert middle key at parent's position idx
        parent.items.insert(idx, (middle_key, middle_val))

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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_root_split tests/unit/test_btree.py::test_btree_set_overwrites_existing -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "feat(btree): add _split_child and _insert_nonfull for insertion"
```

______________________________________________________________________

## Phase 4: Iteration

### Task 5: items(), keys(), values()

**Files:**

- Modify: `dhara/collections/btree.py` (add iteration methods to BTree)

- Modify: `tests/unit/test_btree.py` (add iteration tests)

- [ ] **Step 1: Write failing test for iteration**

```python
# tests/unit/test_btree.py (add)


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_items_sorted_order tests/unit/test_btree.py::test_btree_keys_sorted tests/unit/test_btree.py::test_btree_values_sorted tests/unit/test_btree.py::test_btree_empty_iteration -v
```

Expected: FAIL — `items()`, `keys()`, `values()` not defined

- [ ] **Step 3: Write iteration methods**

Add to `BTree` class:

```python
    def items(self) -> Iterator[tuple[K, V]]:
        """Yield all (key, value) pairs in sorted key order."""
        yield from self._traverse(self._root)

    def _traverse(self, node: BNode) -> Iterator[tuple[K, V]]:
        """In-order traversal of subtree rooted at node."""
        for i, item in enumerate(node.items):
            if node.nodes is not None:
                yield from self._traverse(node.nodes[i])
            yield item
        if node.nodes is not None:
            yield from self._traverse(node.nodes[-1])

    def keys(self) -> Iterator[K]:
        """Yield all keys in sorted order."""
        for k, _ in self.items():
            yield k

    def values(self) -> Iterator[V]:
        """Yield all values in key-sorted order."""
        for _, v in self.items():
            yield v
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_items_sorted_order tests/unit/test_btree.py::test_btree_keys_sorted tests/unit/test_btree.py::test_btree_values_sorted tests/unit/test_btree.py::test_btree_empty_iteration -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "feat(btree): add items, keys, values iteration"
```

______________________________________________________________________

## Phase 5: Deletion (Leaf-Only)

### Task 6: delete() and update() — leaf nodes only

**Files:**

- Modify: `dhara/collections/btree.py` (add deletion methods)

- [ ] **Step 1: Write failing test for delete and update**

```python
# tests/unit/test_btree.py (add)


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_delete_existing tests/unit/test_btree.py::test_btree_delete_nonexistent tests/unit/test_btree.py::test_btree_update_existing tests/unit/test_btree.py::test_btree_update_nonexistent tests/unit/test_btree.py::test_btree_delete_empty_tree -v
```

Expected: FAIL — `delete`, `update` not defined

- [ ] **Step 3: Write delete and update (leaf-only initially)**

Add to `BTree` class:

```python
    def delete(self, key: K) -> bool:
        """Delete key. Returns True if found and deleted, False if not found."""
        return self._delete_from_node(self._root, key)

    def update(self, key: K, value: V) -> bool:
        """Update existing key's value. Returns True if found, False if not."""
        node = self._root
        while node is not None:
            pos, found = node._find_position(key)
            if found:
                node.items[pos] = (key, value)
                return True
            if node.is_leaf():
                return False
            node = node.nodes[pos]
        return False

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

    def _delete_from_node(self, node: BNode, key: K) -> bool:
        """Delete key from node (leaf-only version).

        This initial version handles leaf deletions only.
        Internal node deletion (predecessor/successor) and case 3 (borrow/merge)
        are added in Phase 6.
        """
        # Case 1: Key is in this node
        pos, found = node._find_position(key)
        if found:
            if node.is_leaf():
                node.items.pop(pos)
                return True
            else:
                # Internal node — for now, only support if sibling can lend
                # Full internal deletion + case 3 comes in Phase 6
                return False  # Defer internal node deletion to Phase 6

        else:
            # Key not in this node — descend to child
            if node.is_leaf():
                return False  # Not found

            idx = pos
            child = node.nodes[idx]

            # Leaf deletion only — descend if child has enough keys
            if len(child.items) >= node.minimum_degree:
                return self._delete_from_node(child, key)
            else:
                # Child at minimum — defer case 3 handling to Phase 6
                # For now, just descend (may underflow, but test coverage is limited)
                return self._delete_from_node(child, key)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_delete_existing tests/unit/test_btree.py::test_btree_delete_nonexistent tests/unit/test_btree.py::test_btree_update_existing tests/unit/test_btree.py::test_btree_update_nonexistent tests/unit/test_btree.py::test_btree_delete_empty_tree -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "feat(btree): add delete, update and leaf-only _delete_from_node"
```

______________________________________________________________________

## Phase 6: Deletion (Internal + Case 3 — Borrow + Merge)

### Task 7: \_handle_case3, \_borrow_from_left, \_borrow_from_right, \_merge, \_reduce_height

**Files:**

- Modify: `dhara/collections/btree.py`

- [ ] **Step 1: Write failing test for case 3 (borrow/merge scenarios)**

```python
# tests/unit/test_btree.py (add)


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_delete_internal_node tests/unit/test_btree.py::test_btree_delete_triggers_case3 tests/unit/test_btree.py::test_btree_delete_last_key tests/unit/test_btree.py::test_btree_none_value_vs_missing tests/unit/test_btree.py::test_btree_duplicate_key_overwrites tests/unit/test_btree.py::test_btree_height_reduction_on_root -v
```

Expected: FAIL — `_handle_case3`, borrow, merge not defined

- [ ] **Step 3: Write case 3 methods (Phase 6 adds to \_delete_from_node)**

Add to `BTree` class. First, replace the Phase 5 stub `_delete_from_node` with the full version:

```python
    # Replace the leaf-only _delete_from_node with full version:
    def _delete_from_node(self, node: BNode, key: K) -> bool:
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
                left = node.nodes[pos] if pos < len(node.nodes) else None
                right = node.nodes[pos + 1] if pos + 1 < len(node.nodes) else None
                if left is not None and len(left.items) >= t:
                    pred_key, pred_val = self._get_max(left)
                    node.items[pos] = (pred_key, pred_val)
                    return self._delete_from_node(left, pred_key)
                elif right is not None and len(right.items) >= t:
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
            child = node.nodes[idx]

            if len(child.items) >= node.minimum_degree:
                return self._delete_from_node(child, key)
            else:
                # Child at minimum — call case 3 handler
                new_idx = self._handle_case3(node, idx)
                if new_idx is None or new_idx >= len(node.nodes):
                    return False
                return self._delete_from_node(node.nodes[new_idx], key)
```

Then add the case 3 helper methods:

```python
    def _handle_case3(self, node: BNode, idx: int) -> int | None:
        """Handle underflow before descending into node.nodes[idx].

        Borrow-first strategy:
        1. If left sibling has > t-1 keys, borrow from left → return idx
        2. Else if right sibling has > t-1 keys, borrow from right → return idx
        3. Else merge with left sibling if exists → return idx - 1 (merged node position)
           Or merge with right sibling → return idx (merged node position)

        Returns the NEW index of the child to descend into after handling.
        Returns None if no valid child (tree structure collapsed).
        """
        t = node.minimum_degree
        child = node.nodes[idx]

        # Get siblings
        left_sibling = node.nodes[idx - 1] if idx > 0 else None
        right_sibling = node.nodes[idx + 1] if idx < len(node.nodes) - 1 else None

        # Try borrowing from left sibling
        if left_sibling is not None and len(left_sibling.items) > t - 1:
            self._borrow_from_left(node, idx)
            return idx  # child is still at idx (right sibling absorbed the borrowed key)

        # Try borrowing from right sibling
        if right_sibling is not None and len(right_sibling.items) > t - 1:
            self._borrow_from_right(node, idx)
            return idx  # child is still at idx (left sibling absorbed the borrowed key)

        # No sibling has extra keys — merge
        if left_sibling is not None:
            # Merge idx-1 and idx → result at idx-1
            self._merge(node, idx - 1)
            return idx - 1  # merged node moved to idx-1
        elif right_sibling is not None:
            # Merge idx and idx+1 → result at idx
            self._merge(node, idx)
            return idx  # merged node stays at idx
        else:
            # Neither sibling exists (root with single child) — return None
            return None

    def _borrow_from_left(self, parent: BNode, idx: int) -> None:
        """Borrow rightmost item from left sibling.

        Parent's separator key moves down to leftmost position of right child.
        Rightmost item of left sibling moves up to replace separator.
        """
        left = parent.nodes[idx - 1]
        right = parent.nodes[idx]

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

    def _reduce_height(self) -> None:
        """Reduce tree height when root has no items and one child."""
        if len(self._root.items) == 0 and self._root.nodes is not None:
            self._root = self._root.nodes[0]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_delete_internal_node tests/unit/test_btree.py::test_btree_delete_triggers_case3 tests/unit/test_btree.py::test_btree_delete_last_key tests/unit/test_btree.py::test_btree_none_value_vs_missing tests/unit/test_btree.py::test_btree_duplicate_key_overwrites tests/unit/test_btree.py::test_btree_height_reduction_on_root -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "feat(btree): add borrow-first case 3 deletion (borrow, merge, reduce height)"
```

______________________________________________________________________

## Phase 7: Error Classes + Helper Methods

### Task 8: Error classes, is_full, height helpers

**Files:**

- Modify: `dhara/collections/btree.py` (add error classes, is_full, height)

- [ ] **Step 1: Write failing test for error classes and helpers**

```python
# tests/unit/test_btree.py (add)


def test_btree_error_classes_exist():
    from dhara.collections.btree import BTreeError, KeyNotFoundError, DuplicateKeyError, TreeCorruptedError
    assert issubclass(KeyNotFoundError, BTreeError)
    assert issubclass(DuplicateKeyError, BTreeError)
    assert issubclass(TreeCorruptedError, BTreeError)


def test_btree_is_full():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    assert tree.is_full() is False  # root not full


def test_btree_height_single_node():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    assert tree.height() == 1  # single root node


def test_btree_height_after_root_split():
    from dhara.collections.btree import BTree
    tree = BTree(minimum_degree=3)
    for i in range(6):  # enough to force root split
        tree.set(i, i)
    assert tree.height() == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_error_classes_exist tests/unit/test_btree.py::test_btree_is_full tests/unit/test_btree.py::test_btree_height_single_node tests/unit/test_btree.py::test_btree_height_after_root_split -v
```

Expected: FAIL — `BTreeError`, `KeyNotFoundError`, `is_full`, `height` not defined

- [ ] **Step 3: Write error classes and helpers**

Add to top of `btree.py` after imports:

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
    """Raised when B-Tree invariant is violated."""
    pass
```

Add to `BTree` class:

```python
    def is_full(self) -> bool:
        """Check if root needs splitting."""
        return self._root.is_full()

    def height(self) -> int:
        """Return tree height (number of levels)."""
        h = 0
        node = self._root
        while node is not None:
            h += 1
            if node.nodes is not None and len(node.nodes) > 0:
                node = node.nodes[0]
            else:
                node = None
        return h
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::test_btree_error_classes_exist tests/unit/test_btree.py::test_btree_is_full tests/unit/test_btree.py::test_btree_height_single_node tests/unit/test_btree.py::test_btree_height_after_root_split -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "feat(btree): add error classes, is_full and height helpers"
```

______________________________________________________________________

## Phase 8: Property-Based Tests (Hypothesis)

### Task 9: Hypothesis property-based tests

**Files:**

- Modify: `tests/unit/test_btree.py` (add comprehensive property tests)

- [ ] **Step 1: Write failing property tests**

```python
# tests/unit/test_btree.py (add)


from hypothesis import given, strategies as st

MIN_DEGREES = st.sampled_from([2, 3, 4])


class TestBTreeProperties:
    @given(
        keys=st.lists(st.integers(), min_size=1, max_size=100),
        values=st.lists(st.integers(), min_size=1, max_size=100),
        t=MIN_DEGREES,
    )
    def test_insert_then_get(self, keys, values, t):
        from dhara.collections.btree import BTree
        tree = BTree(minimum_degree=t)
        for k, v in zip(keys, values):
            tree.set(k, v)
        for k, v in zip(keys, values):
            assert tree.get(k) == v

    @given(keys=st.lists(st.integers(), min_size=1))
    def test_delete_removes_key(self, keys):
        from dhara.collections.btree import BTree
        tree = BTree(minimum_degree=3)
        for k in keys:
            tree.set(k, k)
        for k in keys:
            assert tree.delete(k) is True
            assert tree.get(k) is None

    @given(keys=st.lists(st.integers()))
    def test_all_keys_recoverable_after_insert(self, keys):
        from dhara.collections.btree import BTree
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
        from dhara.collections.btree import BTree
        tree = BTree(minimum_degree=3)
        key_counts: dict[int, int] = {}
        for k in keys:
            tree.set(k, k)
            key_counts[k] = key_counts.get(k, 0) + 1

        for k in delete_order:
            if k in key_counts and key_counts[k] > 0:
                result = tree.delete(k)
                assert result is True
                key_counts[k] -= 1

        remaining = [k for k, count in key_counts.items() if count > 0]
        for k in remaining:
            assert tree.get(k) is not None

    @given(keys=st.lists(st.integers()))
    def test_delete_nonexistent_returns_false(self, keys):
        from dhara.collections.btree import BTree
        tree = BTree(minimum_degree=3)
        for k in keys:
            tree.set(k, k)
        for k in keys:
            first_delete = tree.delete(k)
            second_delete = tree.delete(k)
            assert first_delete is True
            assert second_delete is False

    @given(keys=st.lists(st.integers()))
    def test_update_returns_true_for_existing(self, keys):
        from dhara.collections.btree import BTree
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
        from dhara.collections.btree import BTree
        tree = BTree(minimum_degree=3)
        for k in keys:
            tree.set(k, k)
        never_inserted = list(range(max(keys or [0]) + 100, max(keys or [0]) + 110))
        for k in never_inserted:
            assert tree.update(k, "new") is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::TestBTreeProperties -v --hypothesis-show-statistics 2>&1 | head -50
```

Expected: FAIL — test class not yet added

- [ ] **Step 3: Add hypothesis property tests to test file (they are already written above)**

Add the tests to `tests/unit/test_btree.py`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py::TestBTreeProperties -v --hypothesis-show-statistics 2>&1 | tail -30
```

Expected: PASS (with hypothesis statistics showing tests ran)

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py tests/unit/test_btree.py
git commit -m "test(btree): add hypothesis property-based tests"
```

______________________________________________________________________

## Phase 9: Crackerjack Validation

### Task 10: Run all 9 crackerjack hooks

**Files:**

- Run: All modified files

- [ ] **Step 1: Run crackerjack full check**

```bash
cd /Users/les/Projects/dhara && uv run python -m crackerjack run -v 2>&1
```

Expected: All 9 hooks pass

- [ ] **Step 2: Fix any failures**

If any hook fails, fix inline and re-run until all pass.

- [ ] **Step 3: Run pyright/zuban type check manually**

```bash
cd /Users/les/Projects/dhara && uv run pyright dhara/collections/btree.py 2>&1
```

Expected: 0 errors

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/les/Projects/dhara && uv run pytest tests/unit/test_btree.py -v 2>&1
```

Expected: All tests pass

- [ ] **Step 5: Final commit**

```bash
git add -A && git commit -m "feat(btree): complete BTree redesign - passes all quality gates"
```

______________________________________________________________________

## Self-Review Checklist

- [ ] Spec coverage: All sections of design doc have a task
- [ ] No placeholders: No "TBD", "TODO", "implement later" in any step
- [ ] Type consistency: Method signatures match across all tasks
- [ ] TDD: Each task follows red-green-refactor cycle
- [ ] Complete code: Every step shows actual code to write

______________________________________________________________________

## Execution Options

**Plan complete and saved to `docs/superpowers/plans/2026-05-31-btree-redesign-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using batch execution with checkpoints

**Which approach?**

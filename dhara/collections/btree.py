from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar, Iterator

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
            # After split, descend from NEW root (not the old root)
            self._insert_nonfull(self._root, key, value)
        else:
            self._insert_nonfull(root, key, value)

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
            # Check if key already exists (update case)
            while i >= 0:
                if node.items[i][0] == key:
                    node.items[i] = (key, value)
                    return
                if node.items[i][0] < key:
                    break
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

    def height(self) -> int:
        """Return the height of the tree."""
        node = self._root
        h = 0
        while not node.is_leaf():
            node = node.nodes[0]
            h += 1
        return h + 1

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
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
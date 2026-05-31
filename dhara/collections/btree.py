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


# Placeholder - full BTree implementation in later task
class BTree:
    """B-Tree placeholder - full implementation in later tasks."""
    pass
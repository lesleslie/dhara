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


    def _handle_case3(self, node: BNode, idx: int) -> int | None:
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
        child = node.nodes[idx]

        # Get siblings
        left_sibling = node.nodes[idx - 1] if idx > 0 else None
        right_sibling = node.nodes[idx + 1] if idx < len(node.nodes) - 1 else None

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
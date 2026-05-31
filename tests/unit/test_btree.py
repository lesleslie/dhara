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
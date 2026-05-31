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